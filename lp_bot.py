"""LP bot that follows the DLMM feed: enters every posted alert with its exact setup (one-sided SOL, two-sided, or
one-sided token) and exits at the feed's take profit (first 5m close up EXIT_TP_PCT, default 2%, incl. fees) or after
72h. Posts every entry and exit.

  python3 lp_bot.py            -> run forever (launchd: com.sinclair.lp-bot)
  python3 lp_bot.py --once     -> one pass, then exit

Paper mode (default) sends nothing on chain. It enters at the pool's live price when it sees the alert, tracks the
position with the backtest model (exact bins + shape-weighted fees), and at exit prices the token sale with a real
swap quote from the pool, plus the bin-array rent the open would have paid. Live mode runs lp_exec/lp_exec.mjs with
LP_BOT_KEYPAIR and measures PnL from the wallet's SOL balance.

Env (.env): LP_BOT_MODE=paper|live, LP_BOT_SIZE_SOL (0.5), LP_BOT_VERDICTS (comma list, empty = every posted alert),
LP_BOT_MAX_ALERT_AGE_MIN (15), LP_BOT_STATUS_HOURS (6: open-positions update). Live-only safety limits: LP_BOT_MAX_OPEN (3), LP_BOT_DAILY_LOSS_SOL (1.0),
LP_BOT_MIN_TVL (10000),
LP_BOT_LIVE_MAX_SOL (0.25, hard cap per position in live mode), LP_BOT_RESERVE_SOL (0.1 kept for fees/rent),
LP_BOT_MIN_DEPTH_PCT (50: ranges are cut to bin arrays that already exist, never creating new ones; skip if that leaves
less than this % of depth below price),
LP_BOT_WEBHOOK_URL (default: the first POOL_WEBHOOK_URL), LP_BOT_RPC_URL, LP_BOT_KEYPAIR (live only).
"""
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

import backtest_alerts as bt
from pool_watch import get, load_dotenv

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "out" / "lp_bot_state.json"
TRADES = ROOT / "out" / "lp_bot_trades.jsonl"
EXEC = ROOT / "lp_exec" / "lp_exec.mjs"
NODE = shutil.which("node") or "/opt/homebrew/bin/node"
TX_FEE_SOL = 0.00005  # rough per-transaction fee incl. priority, for paper mode only


def env(name, default):
    return type(default)(os.getenv(name) or default)


def run_exec(*args):
    p = subprocess.run([NODE, str(EXEC), *map(str, args)], capture_output=True, text=True, timeout=300, cwd=EXEC.parent)
    lines = [l for l in p.stdout.splitlines() if l.startswith("{")]
    return json.loads(lines[-1]) if lines else {"ok": False, "error": (p.stderr or p.stdout).strip()[-300:]}


def post(payload):
    url = os.getenv("LP_BOT_WEBHOOK_URL") or next((u.strip() for u in os.getenv("POOL_WEBHOOK_URL", "").split(",") if u.strip()), "")
    if not url:
        return
    from send_discord import send
    try:
        send(payload, url=url)
    except Exception as e:
        print(f"discord post failed: {e}", flush=True)


def live_price(a):
    """Token priced in SOL right now (the API gives Y per X)."""
    p = (get(f"https://dlmm.datapi.meteora.ag/pools/{a['pool']}") or {}).get("current_price")
    return (p if a["base_is_x"] else 1 / p) if p else None


def holdings(bins, price, scale):
    """(SOL, tokens) a position built from `bins` holds at `price`, scaled from the model's 100 units to real SOL."""
    sol = tokens = 0.0
    for b, kind, amt in bins:
        if kind == "quote":
            sol, tokens = (sol + amt, tokens) if price >= b else (sol, tokens + amt / b)
        else:
            sol, tokens = (sol + amt * b, tokens) if price > b else (sol, tokens + amt)
    return sol * scale, tokens * scale


def wallet_sol():
    w = run_exec("wallet")
    return w.get("sol") if w.get("ok") else None


def tracks_for(pool):
    out = []
    if bt.TRACKS.exists():
        for line in bt.TRACKS.read_text().splitlines():
            try:
                x = json.loads(line)
                if x["pool"] == pool:
                    out.append((x["t"], x["tvl"]))
            except (ValueError, KeyError):
                pass
    return sorted(out)


def realized_24h(state):
    return sum(t["pnl_sol"] for t in state["closed"] if time.time() - t["exit_t"] < 86400)


def tag(mode):
    return "🧪 paper" if mode == "paper" else "💸 live"


def try_enter(a, state, mode):
    """Returns a reason string if skipped, else None (and records the open position)."""
    size = env("LP_BOT_SIZE_SOL", 0.5)
    if mode == "live":
        size = min(size, env("LP_BOT_LIVE_MAX_SOL", 0.25))
    verdicts = [v.strip().upper() for v in os.getenv("LP_BOT_VERDICTS", "").split(",") if v.strip()]
    if time.time() - a["t"] > env("LP_BOT_MAX_ALERT_AGE_MIN", 15) * 60:
        return "alert too old"
    if verdicts and a.get("verdict", "").upper() not in verdicts:
        return f"verdict {a.get('verdict')} not in LP_BOT_VERDICTS"
    if not a["name"].upper().endswith("-SOL"):
        return "not a SOL pair"
    if mode == "live":  # safety limits for real money; paper follows every alert as posted
        if (a.get("tvl") or 0) < env("LP_BOT_MIN_TVL", 10000):
            return "pool TVL under the minimum"
        if len(state["open"]) >= env("LP_BOT_MAX_OPEN", 3):
            return "max open positions reached"
        if realized_24h(state) <= -env("LP_BOT_DAILY_LOSS_SOL", 1.0):
            return "daily loss limit hit"
        if any(p["alert"]["pool"] == a["pool"] for p in state["open"].values()):
            return "already in this pool"  # close() withdraws every position in a pool, so one at a time
    price = live_price(a)
    if not price:
        return "no live price"
    plan = run_exec("plan", a["pool"], a["shape"], a["lo"], a["hi"], size)
    if not plan.get("ok"):
        return f"plan failed: {plan.get('error')}"
    trimmed = None
    if plan["binArraysToCreate"]:  # never pay bin-array rent: cut the range to arrays that already exist, or skip
        fit, depth = plan.get("fit"), env("LP_BOT_MIN_DEPTH_PCT", 50)
        if not fit or (a["lo"] < 0 and fit["lo"] > -depth) or (a["hi"] > 0 and fit["hi"] <= 0):
            return (f"needs {plan['binArraysToCreate']} new bin arrays; existing ones only reach "
                    f"{fit['lo'] if fit else 0}% (min -{depth:g}%)")
        trimmed = (a["lo"], a["hi"])
        a = dict(a, lo=fit["lo"], hi=fit["hi"])
        plan = run_exec("plan", a["pool"], a["shape"], a["lo"], a["hi"], size)
        if not plan.get("ok") or plan["binArraysToCreate"]:
            return "trimmed range still needs new bin arrays"
    price = plan.get("price") or price  # the active bin on-chain; the API price can lag minutes behind on fast pools
    swap_cost = 0.0
    if mode == "paper" and a["hi"] > 0:  # the range above price needs the token: buy it with half the SOL, or all of it
        spend = size / 2 if a["lo"] < 0 else size
        q = run_exec("quote", a["pool"], spend, "buy")
        swap_cost = max(spend - q["out"] * price, 0.0) if q.get("ok") else 0.0
    pos = {"key": f"{a['pool']}:{int(a['t'])}", "alert": a, "mode": mode, "size": size, "entry_t": time.time(),
           "entry_price": price, "alert_price": a["entry_price"], "plan": plan, "swap_cost": swap_cost}
    if mode == "live":
        reserve = env("LP_BOT_RESERVE_SOL", 0.1)
        before = wallet_sol()
        if before is None or before < size + plan["rentNotRefunded"] + plan["rentRefunded"] + reserve:
            return f"wallet too low ({before} SOL)"
        res = run_exec("open", a["pool"], a["shape"], a["lo"], a["hi"], size)
        if not res.get("ok"):
            post({"content": f"**{tag(mode)} · ⚠️ open failed for {a['name']}**: {res.get('error')}\n{res.get('note', '')}"})
            return f"open failed: {res.get('error')}"
        pos.update(position=res["position"], sol_before=before, sol_after_open=wallet_sol(), txs=res["log"])
    state["open"][pos["key"]] = pos
    drift = (price / a["entry_price"] - 1) * 100
    post({"content": f"**{tag(mode)} · ▶️ entered {a['name']}**",
          "embeds": [{"color": 0x2962FF, "description": "\n".join([
              f"{size:g} SOL · **{a['shape']}** · {a['side']} · range {a['lo']}% → {a['hi']:+}% · {plan['bins']} bins",
              *([f"range cut from {trimmed[0]}% → {trimmed[1]:+}% so it creates no new bin arrays"] if trimmed else []),
              *([f"bought the token side for {swap_cost:.4f} SOL in swap fees/impact"] if swap_cost else []),
              f"entry price {drift:+.1f}% vs the alert price ({(pos['entry_t'] - a['t']) / 60:.0f} min after the alert)",
              f"rent: {plan['rentRefunded']:.3f} SOL back on close · 0 new bin arrays",
              f"exit: first time it's up {bt.EXIT_TP * 100:g}% incl. fees, or 72h"])}]})
    return None


def check_exit(pos, mode):
    """Returns (reason, model result) when the position should close now."""
    a = dict(pos["alert"], t=pos["entry_t"], entry_price=pos["entry_price"])
    r = bt.simulate(a, tracks_for(a["pool"]))
    held = (time.time() - pos["entry_t"]) / 3600
    if r and r.get("tp_hit"):
        if r["last"][0] < bt.EXIT_TP:  # the +2% close came and went before this check saw it
            return f"take profit +{bt.EXIT_TP * 100:g}% was hit at {r['tp'][1]:.1f}h, but price had dropped by the time it closed", r
        return f"take profit +{bt.EXIT_TP * 100:g}%", r
    if held >= bt.HORIZON:
        return "72h", r
    return None, r


def exit_position(pos, reason, r, state, mode):
    a = pos["alert"]
    price = live_price(a) or (r and r.get("exit_price")) or pos["entry_price"]
    fee_frac = r["last"][2] if r else 0.0
    model_pnl = r["last"][0] if r else None
    if mode == "live":
        res = run_exec("close", a["pool"])
        if not res.get("ok"):
            post({"content": f"**{tag(mode)} · ⚠️ close failed for {a['name']}**: {res.get('error')} (will retry)"})
            return False
        after = wallet_sol()
        pnl_sol = after - pos["sol_before"]
        detail = f"wallet: {pos['sol_before']:.4f} → {after:.4f} SOL (everything included: fees, rent, swaps, tx fees)"
    else:
        bins = bt.build_bins(dict(a, entry_price=pos["entry_price"]), pos["entry_price"])
        sol, tokens = holdings(bins, price, pos["size"] / bt.POS)
        q = run_exec("quote", a["pool"], tokens) if tokens > 0 else {"ok": True, "solOut": 0.0, "priceImpactPct": 0.0}
        sell = q["solOut"] if q.get("ok") else tokens * price
        fees = fee_frac * pos["size"]
        costs = pos["plan"]["rentNotRefunded"] + pos.get("swap_cost", 0.0) + TX_FEE_SOL * (2 + pos["plan"]["bins"] // 26)
        pnl_sol = sol + sell + fees - pos["size"] - costs
        detail = (f"SOL left {sol:.4f} + token sold {sell:.4f} (impact {q.get('priceImpactPct', 0):.1f}%) "
                  f"+ fees {fees:.4f} − rent/swap/tx {costs:.4f}")
    trade = {"key": pos["key"], "name": a["name"], "mode": mode, "size": pos["size"], "entry_t": pos["entry_t"],
             "exit_t": time.time(), "reason": reason, "entry_price": pos["entry_price"], "exit_price": price,
             "pnl_sol": pnl_sol, "pnl_pct": pnl_sol / pos["size"] * 100, "model_pnl_pct": model_pnl and model_pnl * 100}
    with TRADES.open("a") as f:
        f.write(json.dumps(trade) + "\n")
    state["closed"].append(trade)
    state["open"].pop(pos["key"], None)
    hrs = (trade["exit_t"] - pos["entry_t"]) / 3600
    total = sum(t["pnl_sol"] for t in state["closed"] if t["mode"] == mode)
    n = sum(t["mode"] == mode for t in state["closed"])
    post({"content": f"**{tag(mode)} · ⏹️ closed {a['name']}** · {reason} after {hrs:.1f}h",
          "embeds": [{"color": 0x26A69A if pnl_sol >= 0 else 0xEF5350, "description": "\n".join([
              f"result: **{pnl_sol:+.4f} SOL ({trade['pnl_pct']:+.1f}%)** on {pos['size']:g} SOL",
              detail,
              f"price {(price / pos['entry_price'] - 1) * 100:+.1f}% since entry",
              f"bot total so far: {total:+.4f} SOL over {n} trade(s)"])}]})
    return True


def post_status(state, mode, marks):
    """Every LP_BOT_STATUS_HOURS: open positions marked by the model, plus the closed total."""
    lines = []
    for key, pos in state["open"].items():
        r, a = marks.get(key), pos["alert"]
        hrs = (time.time() - pos["entry_t"]) / 3600
        if r:
            pnl, _, fee = r["last"]
            lines.append(f"**{a['name']}** · {hrs:.0f}h · {a['shape']} {a['lo']}% → {a['hi']:+}% · now **{pnl * 100:+.1f}%** "
                         f"(fees {fee * 100:+.1f}%) · lowest {r['low_pct']:+.0f}%")
        else:
            lines.append(f"**{a['name']}** · {hrs:.0f}h · not marked yet")
    closed = [t for t in state["closed"] if t["mode"] == mode]
    total = sum(t["pnl_sol"] for t in closed)
    wins = sum(t["pnl_sol"] > 0 for t in closed)
    lines += ["", f"closed: {len(closed)} trade(s) · {wins} green · total **{total:+.4f} SOL**"
              + (f" · best {max(t['pnl_pct'] for t in closed):+.1f}% · worst {min(t['pnl_pct'] for t in closed):+.1f}%" if closed else ""),
              f"open marks are the model before rent/swap costs; closes include them · exit: first +{bt.EXIT_TP * 100:g}% incl. fees, or 72h"]
    post({"content": f"**{tag(mode)} · 📋 positions update** · {len(state['open'])} open",
          "embeds": [{"color": 0x787B86, "description": "\n".join(lines)[:4000]}]})


def main():
    load_dotenv()
    mode = os.getenv("LP_BOT_MODE", "paper").lower()
    if mode == "live" and not os.getenv("LP_BOT_KEYPAIR"):
        sys.exit("LP_BOT_MODE=live needs LP_BOT_KEYPAIR")
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    state.setdefault("start", time.time())  # only alerts after the bot was switched on
    state.setdefault("open", {})
    state.setdefault("closed", [])
    state.setdefault("seen", {})
    print(f"lp bot started in {mode} mode, {len(state['open'])} open", flush=True)
    last_check, marks = 0.0, {}
    state.setdefault("last_status", 0.0)
    while True:
        if bt.ALERTS.exists():
            for line in bt.ALERTS.read_text().splitlines():
                try:
                    a = json.loads(line)
                except ValueError:
                    continue
                key = f"{a['pool']}:{int(a['t'])}"
                if not a.get("posted") or a["t"] < state["start"] or key in state["seen"] or not a.get("entry_price"):
                    continue
                if os.getenv("LP_BOT_NO_NEW") == "1":  # replaced by lp_trader.py: only finish the open positions
                    continue
                reason = try_enter(a, state, mode)
                state["seen"][key] = reason or "entered"
                print(f"{a['name']}: {reason or 'entered'}", flush=True)
        if time.time() - last_check > 300:
            last_check = time.time()
            for pos in list(state["open"].values()):
                try:
                    reason, r = check_exit(pos, mode)
                    marks[pos["key"]] = r
                    if reason:
                        exit_position(pos, reason, r, state, mode)
                        print(f"closed {pos['alert']['name']}: {reason}", flush=True)
                except Exception as e:
                    print(f"exit check failed for {pos['alert']['name']}: {e}", flush=True)
            if state["open"] and time.time() - state["last_status"] > env("LP_BOT_STATUS_HOURS", 6.0) * 3600:
                state["last_status"] = time.time()
                post_status(state, mode, marks)
        STATE.write_text(json.dumps(state))
        if "--once" in sys.argv:
            break
        time.sleep(60)


if __name__ == "__main__":
    main()
