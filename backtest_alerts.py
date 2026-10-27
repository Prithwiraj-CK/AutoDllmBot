"""Backtest the DLMM feed alerts from what was logged at alert time, and optionally post a summary to Discord.

  python3 backtest_alerts.py              -> alerts from the last 7 days, print report
  python3 backtest_alerts.py --days 14    -> longer window
  python3 backtest_alerts.py --post       -> also send the report to RESULTS_WEBHOOK_URL (default: first POOL_WEBHOOK_URL)

Data: out/alerts.jsonl (setup, entry price, pool size at alert), out/alert_tracks.jsonl (pool TVL every 30 min
for 72h after each alert), Meteora 5m OHLCV + per-5m fee history. Each alert opens a $100 position with exactly the
setup it recommended:
- bins spaced by the pool's bin step across the range, weighted by shape (Spot even, Bid-Ask heavier at the far
  edge, Curve heavier near price); one-sided SOL below, one-sided token above, or two-sided half/half
- a bin converts fully when price trades through it (DLMM bins are path-independent), so inventory value at any
  close is exact for that price
- fees = the pool's real LP fees in each 5m candle x $100 / (pool TVL at that time + $100), counted for the share
  of the candle's high-low range that overlaps the position's range, weighted by the shape's density there
- exit: the first 5m close where the position is up EXIT_TP_PCT (default 2%) incl. fees and 1% slippage on the token
  part, else 72h
Not modelled (stated in the report): fee share inside individual bins (bin-level liquidity history isn't public),
entry slippage, tx fees and rent, SOL/USD moves.
"""
import json
import math
import os
import statistics as st
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ALERTS, TRACKS = ROOT / "out" / "alerts.jsonl", ROOT / "out" / "alert_tracks.jsonl"
API = "https://dlmm.datapi.meteora.ag"
POS, HORIZON = 100.0, 72
MIN_TVL = 10_000  # below this a $100 position would be a big chunk of the pool and the fee-share model breaks
EXIT_TP = float(os.getenv("EXIT_TP_PCT", "2")) / 100  # close at the first 5m close this far up, fees included
SELL_COST = 0.01  # slippage on selling the token part at close


def load_env():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip())


def get(path):
    for _ in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(API + path, headers={"User-Agent": "sinclair-x-bot"}), timeout=30) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
        except Exception:
            pass
        time.sleep(1)
    return None


def series(pool, kind, start, end):
    out, s = [], start
    while s < end:  # the API returns ~97 candles per call: 5m candles in 8h chunks
        e = min(s + 8 * 3600, end)
        out += ((get(f"/pools/{pool}/{kind}?timeframe=5m&start_time={int(s)}&end_time={int(e)}") or {}).get("data") or [])
        s = e
        time.sleep(0.1)
    uniq = {c["timestamp"]: c for c in out}
    return [uniq[k] for k in sorted(uniq)]


def build_bins(a, p0):
    step = 1 + a["bin_step"] / 10000
    lo, hi = a["lo"], a["hi"]
    n_below = max(1, round(math.log(1 / (1 + lo / 100)) / math.log(step))) if lo < 0 else 0
    n_above = max(1, round(math.log(1 + hi / 100) / math.log(step))) if hi > 0 else 0

    def weights(n):
        w = [1.0] * n if a["shape"] == "Spot" else [i + 1.0 for i in range(n)] if a["shape"] == "Bid-Ask" else [n - i + 0.0 for i in range(n)]
        total = sum(w)
        return [x / total for x in w]

    below = POS if n_above == 0 else (0 if n_below == 0 else POS / 2)
    bins = [(p0 * step ** -(i + 1), "quote", below * w) for i, w in enumerate(weights(n_below))]
    bins += [(p0 * step ** (i + 1), "token", (POS - below) * w / p0) for i, w in enumerate(weights(n_above))]
    return bins


def value(bins, price):
    v = 0.0
    for b, kind, amt in bins:
        if kind == "quote":
            v += amt if price >= b else amt / b * price
        else:
            v += amt * price if price <= b else amt * b
    return v


def token_value(bins, price):
    """Part of the position held in the token at this price: what has to be sold on close."""
    return sum(amt / b * price if kind == "quote" else amt * price
               for b, kind, amt in bins if (kind == "quote" and price < b) or (kind == "token" and price <= b))


def tvl_at(tracks, ts, fallback):
    best = fallback
    for t, tvl in tracks:
        if t <= ts + 1800 and tvl is not None:
            best = tvl
    return best


def simulate(a, tracks, tp=None):
    """Mark a $100 position with the alert's setup on every 5m close. 'tp' = the first close where it's up EXIT_TP
    (fees included, after SELL_COST on the token part), else the 72h close."""
    tp = EXIT_TP if tp is None else tp
    end = min(time.time(), a["t"] + (HORIZON + 1) * 3600)
    candles = series(a["pool"], "ohlcv", a["t"] - 300, end)
    fees = {f["timestamp"]: max((f.get("fees") or 0) - (f.get("protocol_fees") or 0), 0)
            for f in series(a["pool"], "volume/history", a["t"] - 300, end)}
    if not a["base_is_x"]:  # API prices are Y per X; flip so price is always base in quote
        candles = [dict(c, open=1 / c["open"], close=1 / c["close"], high=1 / c["low"], low=1 / c["high"]) for c in candles]
    now = time.time()
    # completed candles that start after the alert: the one the alert landed in also holds pre-alert price action
    post = [c for c in candles if c["timestamp"] + 300 <= now and c["timestamp"] >= a["t"]]
    if not post:
        return None
    p0 = a.get("entry_price") or post[0]["close"]
    bins = build_bins(a, p0)
    bot, top = min(b for b, *_ in bins), max(b for b, *_ in bins)
    cap = [(b, amt if kind == "quote" else amt * b) for b, kind, amt in bins]  # $ placed in each bin at entry

    def density(lo, hi):
        """How much of the position sits where price traded, vs an even spread (1.0). Bid-Ask is thin near entry
        and thick at the bottom, so fees earned near entry are worth less to it than an even split suggests."""
        inb = [v for b, v in cap if lo <= b <= hi] or [min(cap, key=lambda x: abs(x[0] - (lo + hi) / 2))[1]]
        return sum(inb) / POS / (len(inb) / len(cap))
    res, fee_acc, low = {}, 0.0, float("inf")
    for c in post:
        overlap = max(0.0, min(c["high"], top) - max(c["low"], bot))
        frac = overlap / (c["high"] - c["low"]) if c["high"] > c["low"] else float(bot <= c["close"] <= top)
        tvl = max(tvl_at(tracks, c["timestamp"], a["tvl"]), MIN_TVL)  # a drained pool can't hand $100 most of its fees
        if frac:
            fee_acc += (fees.get(c["timestamp"], 0.0) * POS / (max(tvl, 0) + POS) * frac
                        * density(max(c["low"], bot), min(c["high"], top)))
        if "tp" not in res:
            low = min(low, c["low"])
        hrs = (c["timestamp"] + 300 - a["t"]) / 3600
        pnl = (value(bins, c["close"]) + fee_acc - SELL_COST * token_value(bins, c["close"])) / POS - 1
        if "tp" not in res and pnl >= tp:
            res["tp"], res["tp_hit"], res["exit_price"] = (pnl, hrs, fee_acc / POS), True, c["close"]
        for h in (24, 72):
            if f"h{h}" not in res and hrs >= h:
                res[f"h{h}"] = (pnl, hrs, fee_acc / POS)
        res["last"] = (pnl, hrs, fee_acc / POS)
    if "last" not in res:
        return None
    res["open"] = res["last"][1] < HORIZON  # still inside the 72h window: marked to the latest close
    for k in ("h24", "h72"):
        res.setdefault(k, res["last"])
    res.setdefault("tp", res["h72"])
    res["low_pct"] = (min(c["low"] for c in post) / p0 - 1) * 100
    res["low_to_exit_pct"] = (low / p0 - 1) * 100 if low != float("inf") else 0.0
    res["range_bottom_pct"] = (bot / p0 - 1) * 100
    res["hours_elapsed"] = (now - a["t"]) / 3600
    return res


def summarize(rows, key):
    x = [r[key][0] for r in rows]
    return {"n": len(x), "avg": st.mean(x) * 100, "median": st.median(x) * 100,
            "win": sum(v > 0 for v in x) / len(x) * 100, "total": sum(x) * POS,
            "fees": st.mean(r[key][2] for r in rows) * 100}


def report(days):
    since = time.time() - days * 86400
    alerts = [json.loads(l) for l in ALERTS.read_text().splitlines() if l.strip()] if ALERTS.exists() else []
    alerts = [a for a in alerts if a["t"] >= since and a.get("entry_price") is not None and time.time() - a["t"] > 2 * 3600]
    tracks = {}
    if TRACKS.exists():
        for l in TRACKS.read_text().splitlines():
            try:
                r = json.loads(l)
                tracks.setdefault(r["pool"], []).append((r["t"], r["tvl"]))
            except (ValueError, KeyError):
                pass
    rows, too_small = [], []
    for a in alerts:
        if (a.get("tvl") or 0) < MIN_TVL:
            too_small.append(a)
            continue
        r = simulate(a, sorted(tracks.get(a["pool"], [])))
        if r:
            rows.append(dict(a, **r))
    lines = [f"**📊 DLMM feed backtest · last {days:g} days** ({len(rows)} alerts simulated)", ""]
    if too_small:
        lines += [f"not simulated: {len(too_small)} alert(s) whose pool had under ${MIN_TVL:,} TVL at alert time "
                  f"({sum(a['posted'] for a in too_small)} posted, {sum(not a['posted'] for a in too_small)} PASS). "
                  f"a $100 position would be a big share of a pool that thin, so the fee model can't price it", ""]
    if not rows:
        return "\n".join(lines + ["no logged alerts in this window yet"]), rows
    feed = lambda r: not str(r.get("origin", "feed")).startswith("scanner")
    for label, group in (("posted alerts (channel feed)", [r for r in rows if r["posted"] and feed(r)]),
                         ("posted alerts (pool scanner)", [r for r in rows if r["posted"] and not feed(r)]),
                         ("skipped as PASS", [r for r in rows if not r["posted"]])):
        if not group:
            continue
        lines.append(f"**{label}** · $100 per alert, exact setup from the alert")
        for key, name in (("tp", f"take profit at +{EXIT_TP * 100:g}% (72h max)"), ("h24", "hold 24h"), ("h72", "hold 72h")):
            s = summarize(group, key)
            lines.append(f"{name}: avg **{s['avg']:+.1f}%** · median {s['median']:+.1f}% · win {s['win']:.0f}% · "
                         f"total **${s['total']:+.0f}** (fees {s['fees']:.1f}% avg, median-based view: {s['median']:+.1f}%)")
        lines.append("")
    old = [r for r in rows if r["posted"] and r["hi"] == 0 and (r["shape"] != "Bid-Ask" or r["lo"] > -90)]
    if old:  # alerts from before the current setup rule, re-run with it
        now_rule = [x for x in (simulate(dict(r, shape="Bid-Ask", lo=min(r["lo"], -90)), sorted(tracks.get(r["pool"], [])))
                                for r in old) if x]
        if now_rule:
            s = summarize(now_rule, "tp")
            lines += [f"**{len(now_rule)} of these alerts re-run with today's setup rule** (one-sided SOL → Bid-Ask, -90% or deeper)",
                      f"take profit at +{EXIT_TP * 100:g}%: avg **{s['avg']:+.1f}%** · median {s['median']:+.1f}% · win {s['win']:.0f}% · "
                      f"total **${s['total']:+.0f}**", ""]
    posted = sorted([r for r in rows if r["posted"]], key=lambda r: r["tp"][0])
    if posted:
        fmt = lambda r: f"{r['name']} {r['tp'][0] * 100:+.0f}%"
        lines.append("best: " + ", ".join(fmt(r) for r in posted[::-1][:3]))
        lines.append("worst: " + ", ".join(fmt(r) for r in posted[:3]))
        rugs = [r for r in posted if r["low_pct"] < -80]
        lines.append(f"tokens that fell >80%: {len(rugs)} · range covered the fall: {sum(r['lo'] <= r['low_pct'] for r in rugs)}")
        opened = sum(r["open"] for r in rows)
        if opened:
            lines.append(f"{opened} alert(s) are under 72h old and marked at the latest price")
    lines += ["", "*model: exact bin conversion per close, real pool fees x $100/(pool TVL at the time + $100), "
                  "weighted by how much of the position sat where price traded, 5m candles, 1% slippage on the token part. "
                  "pool TVL floored at $10K. not included: where other LPs sat, tx fees/rent, SOL/USD moves. "
                  "research, not financial advice*"]
    return "\n".join(lines), rows


def main():
    load_env()
    days = float(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else 7
    text, rows = report(days)
    print(text)
    (ROOT / "out" / "backtest_last.json").write_text(json.dumps(rows, indent=1, default=str))
    if "--post" in sys.argv:
        from send_discord import send
        raw = os.getenv("RESULTS_WEBHOOK_URL") or os.getenv("POOL_WEBHOOK_URL", "").split(",")[0]
        for url in [] if raw.strip().lower() == "off" else [u.strip() for u in raw.split(",") if u.strip()]:
            try:
                send({"embeds": [{"description": text[:4000], "color": 0x7C3AED}]}, url=url)
            except Exception as e:
                print(f"post failed: {e}")


if __name__ == "__main__":
    main()
