"""Watch the Discord reader's message log for Solana token / pool addresses, research the token's
Meteora DLMM pool, and post a breakdown (volume, fees, flow, safety, example LP setup, chart) to a webhook.

  python3 pool_watch.py              -> follow DISCORD_MESSAGE_LOG from where it last stopped, forever
  python3 pool_watch.py --from-start -> also process everything already in the log
  python3 pool_watch.py --once       -> process what's there and exit

Env: DISCORD_MESSAGE_LOG   JSONL written by discord_reader.py (default out/discord_messages.jsonl)
     POOL_WEBHOOK_URL      where breakdowns go
     RESULTS_WEBHOOK_URL   where check-ins/results go (default: only the first POOL_WEBHOOK_URL; "off" = don't post)
     POOL_REPOST_HOURS     research the same token again only after this long (default 24)
     POOL_SCAN=0           turn off the pool scanner (on by default); SCAN_WEBHOOK_URL (default: first POOL_WEBHOOK_URL),
                           SCAN_MAX_PER_HOUR (3), SCAN_MIN_TVL, SCAN_MIN_VOL_1H, SCAN_MIN_FEE_TVL_1H, SCAN_EVERY_MIN
     DRY_RUN=1             print instead of sending

People mostly paste token CAs, so any base58 string is resolved: a Meteora DLMM pool is used directly,
a token mint (or another DEX's pair) maps to that token's busiest DLMM pool. Wallets etc. are skipped.
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STATE = ROOT / "out" / "pool_watch_state.json"
PAIR = "https://api.dexscreener.com/latest/dex/pairs/solana/"
TOKEN_PAIRS = "https://api.dexscreener.com/token-pairs/v1/solana/"
ADDRESS = re.compile(r"(?<![1-9A-HJ-NP-Za-km-z])[1-9A-HJ-NP-Za-km-z]{32,44}(?![1-9A-HJ-NP-Za-km-z])")
# dexscreener links lowercase the address, so the regex above can't recover it; the API accepts it as-is
DEX_LINK = re.compile(r"dexscreener\.com/solana/([0-9a-z]{32,44})", re.I)
QUOTES = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
          "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", "JuprjznTrTSp2UFa3ZBUFgwdAmtZCq4MQCwysN55USD"}
SKIP = QUOTES | {"11111111111111111111111111111111"}
NOT_FOUND_RETRY = 6 * 3600
MAX_MESSAGE_AGE = 3 * 3600  # after a restart the reader replays recent history; don't alert on stale mentions  # a token with no DLMM pool yet may get one later


def load_dotenv():
    env = ROOT / ".env"
    if env.exists():
        for line in env.read_text().splitlines():
            k, sep, v = line.partition("=")
            if sep and not line.lstrip().startswith("#"):
                os.environ.setdefault(k.strip(), v.strip())


def get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "sinclair-x-bot", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None
        raise


def candidates(text):
    found = ADDRESS.findall(text) + DEX_LINK.findall(text)
    return [a for a in dict.fromkeys(found) if a not in SKIP]


def is_dlmm(pair):
    return pair.get("dexId") == "meteora" and "DLMM" in (pair.get("labels") or [])


def resolve(address):
    """Return (mint, DLMM pool address) for a pool or token address, or None."""
    pairs = (get(PAIR + address) or {}).get("pairs") or []
    if pairs:
        pair = pairs[0]
        base = pair["baseToken"]["address"]
        mint = pair["quoteToken"]["address"] if base in QUOTES else base
        if is_dlmm(pair):
            return mint, pair["pairAddress"]
    else:
        mint = address
    dlmm = [p for p in (get(TOKEN_PAIRS + mint) or []) if is_dlmm(p)]
    if not dlmm:
        return None
    best = max(dlmm, key=lambda p: ((p.get("volume") or {}).get("h24") or 0, (p.get("liquidity") or {}).get("usd") or 0))
    return mint, best["pairAddress"]


def research_pool(pool):
    """research.chart() -> out/chart.png + the pool data (the AI trader posts the advice, see lp_trader.post_take)."""
    import research
    try:
        research.chart(pool, watermark=None)
    except SystemExit as e:  # e.g. "no candles for this pool"
        raise RuntimeError(str(e))
    return json.loads((ROOT / "out" / "chart_pool.json").read_text())


usd = None  # set from research on first use


def day_pace(p):
    """24h volume and fee/TVL, extrapolated for pools younger than a day (a 1h-old pool's '24h' is 1h of data)."""
    age = max(p["pool_age_hours"], 1)
    scale = 24 / age if age < 24 else 1
    return p["volume_24h"] * scale, p["fee_tvl_pct_24h"] * scale, scale > 1


def verdict(p):
    s, rc, bt = p["strategy"], p.get("rugcheck") or {}, p["base_token"]
    vol_day, fee_tvl_day, _ = day_pace(p)
    red = []
    if any(r.startswith("danger") for r in rc.get("risks", [])):
        red.append("rugcheck danger flags")
    if bt.get("freeze_authority_disabled") is False:
        red.append("freeze authority active")
    if p["tvl"] < 10_000:
        red.append("TVL too thin")
    if vol_day < 25_000:
        red.append("under $25K/day volume, not enough to pay fees")
    if red:
        return "🔴 **pass**", red
    yellow = []
    if p["pool_age_hours"] < 48:
        yellow.append("pool under 2 days old")
    if fee_tvl_day > 50:
        yellow.append("fee/TVL this high usually means violent price moves")
    if s["range_24h_pct"] > 150:
        yellow.append(f"{s['range_24h_pct']}% 24h range")
    yellow += [w for w in s["warnings"] if w not in yellow and "day old" not in w]
    if p["pool_age_hours"] < 24 or len(yellow) >= 2:
        return "🟡 **degen only, small size**", yellow
    return "🟢 **LP-able with a plan**", yellow


def breakdown(p, take):
    """The research card for one pool; `take` = the AI trader's decision lines, shown first."""
    global usd
    import research
    usd = research.usd
    s, fl, bt, rc = p["strategy"], p.get("flow") or {}, p["base_token"], p.get("rugcheck") or {}
    addr = p["address"]
    pc = fl.get("price_change_pct") or {}
    t24, t1 = fl.get("txns_24h") or {}, fl.get("txns_1h") or {}
    age = f"{p['pool_age_hours'] / 24:.1f}d" if p["pool_age_hours"] >= 48 else f"{p['pool_age_hours']:.0f}h"
    vol_day, fee_tvl_day, young = day_pace(p)
    per_1k = fee_tvl_day * 10
    pace = f" · day pace ≈ {usd(vol_day)} vol (first {max(p['pool_age_hours'], 1):.0f}h extrapolated, launches fade)" if young else ""
    risks = rc.get("risks") or []
    socials = " + ".join(k for k, ok in (("site", fl.get("has_website")), ("X", fl.get("has_twitter"))) if ok) or "none"

    lines = list(take) + ["", 
        "**📊 volume & fees**",
        f"TVL {usd(p['tvl'])} · 24h vol {usd(p['volume_24h'])} · 1h vol {usd(p['volume_1h'])} · vol/TVL {p['volume_to_tvl']}x{pace}",
        f"24h fees {usd(p['fees_24h'])} · fee/TVL 24h **{p['fee_tvl_pct_24h']}%** "
        + (f"(pool avg ≈ ${p['fee_tvl_pct_24h'] * 10:,.0f} per $1K in its first {max(p['pool_age_hours'], 1):.0f}h)" if young
           else f"(pool avg ≈ ${per_1k:,.0f}/day per $1K)"),
        f"bin step {p['bin_step']} · base fee {p['base_fee_pct']}% · pool age {age}",
        "",
        "**🔄 flow & price**",
        " · ".join(f"{k[1:]}h {pc[k]:+.1f}%" for k in ("h1", "h6", "h24") if pc.get(k) is not None) + f" · 24h range {s['range_24h_pct']}%",
        f"buys/sells 24h {t24.get('buys', '–')}/{t24.get('sells', '–')} · 1h {t1.get('buys', '–')}/{t1.get('sells', '–')}",
        "",
        "**🛡️ token safety**",
        f"MC {usd(bt['market_cap']) if bt.get('market_cap') else 'n/a'} · holders {bt['holders']:,} · MC/holder {usd(p['mc_per_holder']) if p.get('mc_per_holder') else 'n/a'}"
        if bt.get("holders") else f"MC {usd(bt['market_cap']) if bt.get('market_cap') else 'n/a'}",
        f"freeze auth {'revoked' if bt.get('freeze_authority_disabled') else '**ACTIVE**'} · socials {socials} · "
        + ("rugcheck n/a" if "error" in rc else f"rugcheck {len(risks)} risk{'s' if len(risks) != 1 else ''}"
           + (f" ({'; '.join(risks[:3])})" if risks else "")),
    ]
    links = [f"[Meteora](https://app.meteora.ag/dlmm/{addr})", f"[DexScreener](https://dexscreener.com/solana/{addr})",
             f"[RugCheck](https://rugcheck.xyz/tokens/{bt['mint']})"]
    lines += ["", " · ".join(links)]
    return {
        "content": f"**🧪 {p['name']}**",
        "embeds": [{
            "title": f"{p['name']} · Meteora DLMM",
            "url": f"https://app.meteora.ag/dlmm/{addr}",
            "description": "\n".join(lines)[:4000],
            "image": {"url": "attachment://chart.png"},
            "footer": {"text": "decision: the AI LP bot (Claude), research, not financial advice · data: Meteora, DexScreener, RugCheck"},
            "color": 0x7C3AED,
        }],
    }


# ---------- Claude analysis (via the local Claude Code CLI, on the user's plan) ----------

CLAUDE_BIN = os.path.expanduser(os.getenv("CLAUDE_BIN", "~/.local/bin/claude"))
KNOWLEDGE = Path(os.getenv("POOL_KNOWLEDGE") or ROOT / "knowledge" / "DLMM_KNOWLEDGE.md")
NAMES = [(re.compile(r"\s*@\w+"), ""),
         (re.compile(r"(?i)\b(the\s+)?evil\s*panda('?s)?(\s+strat(egy)?)?"), "the wide-range approach"),
         (re.compile(r"(?i)\b(the\s+)?bonus\s+stage(\s+strat(egy)?)?"), "the after-the-dump two-sided approach"),
         (re.compile(r"(?i)\b(the\s+|a\s+)?heart\s+attack(\s+strat(egy)?)?"), "a tight-range approach")]


def strip_names(text):
    for pat, repl in NAMES:
        text = pat.sub(repl, text)
    return re.sub(r"\s{2,}", " ", text).strip()


def indicators(candles):
    import research
    closes = [c["close"] for c in candles]
    out = {"timeframe_candles": len(candles)}
    r2 = research.rsi(closes, 2)
    out["rsi2_last"] = round(r2[-1], 1) if r2 and r2[-1] is not None else None
    if len(closes) >= 20:
        win = closes[-20:]
        mean = sum(win) / 20
        sd = (sum((x - mean) ** 2 for x in win) / 20) ** 0.5
        out["bb_upper"], out["close_above_bb_upper"] = mean + 2 * sd, closes[-1] > mean + 2 * sd
    if len(closes) >= 35:
        def ema(xs, n):
            k, e, res = 2 / (n + 1), xs[0], []
            for x in xs:
                e = x * k + e * (1 - k)
                res.append(e)
            return res
        macd = [a - b for a, b in zip(ema(closes, 12), ema(closes, 26))]
        hist = [m - s for m, s in zip(macd, ema(macd, 9))]
        out["macd_hist_last2"] = [round(h / closes[-1] * 100, 3) for h in hist[-2:]]  # % of price
        out["macd_first_green_bar"] = hist[-2] <= 0 < hist[-1]
    if len(candles) >= 12:  # SuperTrend(10, 3)
        trs = [max(c["high"] - c["low"], abs(c["high"] - p["close"]), abs(c["low"] - p["close"]))
               for p, c in zip(candles, candles[1:])]
        atr = sum(trs[:10]) / 10
        up, dn, trend = None, None, 1
        for i in range(11, len(candles)):
            atr = (atr * 9 + trs[i - 1]) / 10
            c = candles[i]
            mid = (c["high"] + c["low"]) / 2
            bu, bd = mid + 3 * atr, mid - 3 * atr
            up = bu if up is None or bu < up or candles[i - 1]["close"] > up else up
            dn = bd if dn is None or bd > dn or candles[i - 1]["close"] < dn else dn
            trend = 1 if c["close"] > up else -1 if c["close"] < dn else trend
        out["supertrend"] = "bullish (price above)" if trend == 1 else "bearish (price below)"
    return out


def result_webhooks():
    """Where check-ins/results/backtests go: RESULTS_WEBHOOK_URL, else only the first POOL_WEBHOOK_URL (Billi's server)."""
    raw = os.getenv("RESULTS_WEBHOOK_URL") or os.getenv("POOL_WEBHOOK_URL", "").split(",")[0]
    return [] if raw.strip().lower() == "off" else [u.strip() for u in raw.split(",") if u.strip()]


def post(payload, urls=None, chart=None, wait=False):
    """Send to every webhook in POOL_WEBHOOK_URL (comma-separated), or `urls`; one failing doesn't block the others."""
    from send_discord import send
    chart = chart or ROOT / "out" / "chart.png"
    urls = urls or [u.strip() for u in os.getenv("POOL_WEBHOOK_URL", "").split(",") if u.strip()]
    sent = 0
    messages = {}
    for url in urls:
        for _ in range(5):
            try:
                message = send(payload, [chart], url=url, wait=wait)
                if message and all(message.get(k) for k in ("guild_id", "channel_id", "id")):
                    messages[url] = f"https://discord.com/channels/{message['guild_id']}/{message['channel_id']}/{message['id']}"
                sent += 1
                break
            except urllib.error.HTTPError as e:
                if e.code != 429:
                    print(f"webhook …{url[-6:]} failed: HTTP {e.code}", flush=True)
                    break
                time.sleep(float(json.loads(e.read() or b"{}").get("retry_after", 2)))
        else:
            print(f"webhook …{url[-6:]} still rate-limited", flush=True)
    if not sent:
        raise RuntimeError("no webhook accepted the alert")
    return messages


def too_old(record):
    try:
        sent = datetime.fromisoformat(record["created_at"]).timestamp()
    except (KeyError, TypeError, ValueError):
        return False
    return time.time() - sent > MAX_MESSAGE_AGE


ALERTS = ROOT / "out" / "alerts.jsonl"
TRACKS = ROOT / "out" / "alert_tracks.jsonl"
TRACK_EVERY, TRACK_FOR = 1800, 73 * 3600


def log_alert(p, mint, posted, origin="feed"):
    """Everything a backtest needs, as it was at alert time."""
    s = p["strategy"]
    rec = {"t": time.time(), "posted": posted, "origin": origin, "name": p["name"], "pool": p["address"], "mint": mint,
           "verdict": verdict(p)[0], "source": "rules",
           "shape": s["shape"], "side": s["side"], "lo": s["range_low_pct"], "hi": s["range_high_pct"], "bins": s["bins"],
           "bin_step": p["bin_step"], "base_fee_pct": p["base_fee_pct"], "dynamic_fee_pct": p.get("dynamic_fee_pct"),
           "tvl": p["tvl"], "volume_1h": p["volume_1h"], "volume_24h": p["volume_24h"], "fees_24h": p["fees_24h"],
           "fee_tvl_pct_24h": p["fee_tvl_pct_24h"], "pool_age_hours": p["pool_age_hours"], "base_is_x": p["base_is_x"],
           "entry_price": p.get("last_close"), "entry_candle_ts": p.get("last_candle_ts")}
    with ALERTS.open("a") as f:
        f.write(json.dumps(rec) + "\n")


def track_alerted_pools(state):
    """Every 30 min, record TVL of pools alerted in the last 73h, so backtests use the real pool size over time."""
    now = time.time()
    if now - state.get("last_track", 0) < TRACK_EVERY or not ALERTS.exists():
        return
    state["last_track"] = now
    pools = {}
    for line in ALERTS.read_text().splitlines():
        try:
            a = json.loads(line)
        except ValueError:
            continue
        if now - a["t"] < TRACK_FOR:
            pools[a["pool"]] = True
    with TRACKS.open("a") as f:
        for pool in pools:
            try:
                d = get("https://dlmm.datapi.meteora.ag/pools/" + pool) or {}
                f.write(json.dumps({"t": now, "pool": pool, "tvl": d.get("tvl"), "fees_24h": (d.get("fees") or {}).get("24h"),
                                    "volume_24h": (d.get("volume") or {}).get("24h")}) + "\n")
            except Exception as e:
                print(f"track failed for {pool}: {e}", flush=True)


FOLLOWUPS = ROOT / "out" / "followups.json"
CHECKINS = [int(h) for h in os.getenv("FOLLOWUP_CHECKINS", "6,24,48").split(",") if h.strip()]  # hours, while still open
IST = timezone(timedelta(hours=5, minutes=30))


def bt_tp():
    import backtest_alerts as bt
    return bt.EXIT_TP * 100


def followup_text(a, r, checkin=None):
    """checkin=N: a still-open position marked at its latest close N hours in; None: the final result."""
    pnl, hrs, fee = r["last"] if checkin else r["tp"]
    price = pnl - fee
    when = datetime.fromtimestamp(a["t"], IST).strftime("%d %b %H:%M IST")
    held_low, bottom = r["low_to_exit_pct"], r["range_bottom_pct"]
    lines = [f"alert: {when} · setup **{a['shape']}** · {a['side']} · range {a['lo']}% → {a['hi']:+}% · entered at the alert price", ""]
    if checkin:
        lines.append(f"⏳ **{hrs:.0f}h in, still open**: hasn't reached +{bt_tp():g}% yet. if you closed it now:")
    elif r.get("tp_hit"):
        lines.append(f"✅ reached the +{bt_tp():g}% take profit after **{hrs:.1f}h** → closed on that 5m candle")
    elif hrs < 71.5:
        lines.append(f"⏱️ never reached +{bt_tp():g}%, and the pool stopped trading after {hrs:.0f}h → valued at its last price")
    else:
        lines.append(f"⏱️ never reached +{bt_tp():g}% within 72h → closed at 72h")
    lines += [f"result on $100: **{'+' if pnl >= 0 else '-'}${abs(pnl) * 100:.2f} ({pnl * 100:+.1f}%)** = fees +${fee * 100:.2f} "
              f"· price move {'+' if price >= 0 else '-'}${abs(price) * 100:.2f}",
              f"lowest price {'so far' if checkin else 'before closing'}: {held_low:+.0f}% (range bottom {bottom:+.0f}%) → "
              + ("range held" if held_low > bottom else "price fell through the bottom of the range")]
    if checkin:
        nxt = [h for h in CHECKINS if h > checkin]
        lines.append(f"next update: {f'{nxt[0]}h check-in, or ' if nxt else ''}the final result at +{bt_tp():g}% (72h max)")
    holds = [f"{h}h {r[f'h{h}'][0] * 100:+.1f}%" for h in (24, 72) if r["hours_elapsed"] >= h]
    if holds and r.get("tp_hit"):
        lines.append("if you'd held instead: " + " · ".join(holds))
    title = f"check-in {hrs:.0f}h after the alert" if checkin else "what happened after the alert"
    return {"content": f"**{'⏳' if checkin else '📊'} {a['name']} · {title}**",
            "embeds": [{"description": "\n".join(lines), "color": 0x787B86 if checkin else 0x26A69A if pnl >= 0 else 0xEF5350,
                        "footer": {"text": "simulated $100 with the alert's exact setup: every bin converted at its price, real pool "
                                           "fees x $100/(pool TVL at the time + $100), weighted by how much of the position sat where price "
                                           "traded, 5m candles, 1% slippage on the token part, TVL floored at $10K. not included: where "
                                           "other LPs sat, tx fees/rent. "
                                           "research, not financial advice"}}]}


def check_followups(state):
    """Per posted alert: a check-in at each CHECKINS hour while the simulated position is open, then the final
    result once it closes (take profit, or 72h)."""
    now = time.time()
    if now - state.get("last_follow", 0) < 1800 or not ALERTS.exists():
        return
    state["last_follow"] = now
    import backtest_alerts as bt
    done = json.loads(FOLLOWUPS.read_text()) if FOLLOWUPS.exists() else {}
    done.setdefault("_start", now)  # only alerts from when this was switched on, so old ones don't flood the feed
    tracks = {}
    if TRACKS.exists():
        for line in TRACKS.read_text().splitlines():
            try:
                x = json.loads(line)
                tracks.setdefault(x["pool"], []).append((x["t"], x["tvl"]))
            except (ValueError, KeyError):
                pass
    for line in ALERTS.read_text().splitlines():
        try:
            a = json.loads(line)
        except ValueError:
            continue
        key = f"{a['pool']}:{int(a['t'])}"
        if (not a.get("posted") or key in done or a["t"] < done["_start"] or not a.get("entry_price")
                or now - a["t"] < 3600):
            continue
        if (a.get("tvl") or 0) < bt.MIN_TVL:
            done[key] = "pool under $10K TVL, not simulated"
            continue
        try:
            r = bt.simulate(a, sorted(tracks.get(a["pool"], [])))
        except Exception as e:
            print(f"followup sim failed for {a['name']}: {e}", flush=True)
            continue
        if not r:
            continue
        checkin = None
        if not r.get("tp_hit") and r["hours_elapsed"] < 72:
            due = [h for h in CHECKINS if r["hours_elapsed"] >= h and f"{key}:{h}h" not in done]
            if not due:
                continue
            checkin = due[-1]  # after downtime, post only the latest one that's due
            for h in due:
                done[f"{key}:{h}h"] = now
        payload = followup_text(a, r, checkin)
        from send_discord import send  # RESULTS_WEBHOOK_URL=off: tracked, not posted
        for url in result_webhooks():
            try:
                send(payload, url=url)
            except Exception as e:
                print(f"followup post failed: {e}", flush=True)
        if checkin:
            print(f"checkin {checkin}h posted {a['name']} {r['last'][0] * 100:+.1f}%", flush=True)
            continue
        done[key] = now
        print(f"followup posted {a['name']} {r['tp'][0] * 100:+.1f}%", flush=True)
    FOLLOWUPS.write_text(json.dumps(done))



# ---------- pool scanner: find pools the way the profitable LP wallets do ----------
# From 20K closed positions of 8 profitable DLMM wallets: SOL pairs, bin step ~100, base fee 1-2%+, busy right now
# (high 1h volume and fees vs TVL), and one of three moments: a fresh pool pumping, an older pool with $1M+ a day
# running up, or an older pool 30%+ off its 24h high after a run.

DATAPI = "https://dlmm.datapi.meteora.ag"
SOL_MINT = "So11111111111111111111111111111111111111112"
SCAN_EVERY = float(os.getenv("SCAN_EVERY_MIN", "5")) * 60
SCAN_MAX_PER_HOUR = int(os.getenv("SCAN_MAX_PER_HOUR", "5"))
SCAN_MIN_TVL = float(os.getenv("SCAN_MIN_TVL", "10000"))
SCAN_MIN_VOL_1H = float(os.getenv("SCAN_MIN_VOL_1H", "30000"))
SCAN_MIN_FEE_TVL_1H = float(os.getenv("SCAN_MIN_FEE_TVL_1H", "0.5"))  # % of TVL earned in fees in the last hour
SCAN_STEADY_MIN_TVL = float(os.getenv("SCAN_STEADY_MIN_TVL", "5000"))
SCAN_STEADY_MIN_VOL_1H = float(os.getenv("SCAN_STEADY_MIN_VOL_1H", "8000"))
SCAN_STEADY_MIN_VOL_30M = float(os.getenv("SCAN_STEADY_MIN_VOL_30M", "2000"))
SCAN_STEADY_MIN_FEE_TVL_1H = float(os.getenv("SCAN_STEADY_MIN_FEE_TVL_1H", "0.05"))


def scan_webhooks():
    """Scanner alerts go to SCAN_WEBHOOK_URL, else only the first POOL_WEBHOOK_URL (Billi's server)."""
    raw = os.getenv("SCAN_WEBHOOK_URL") or os.getenv("POOL_WEBHOOK_URL", "").split(",")[0]
    return [] if raw.strip().lower() == "off" else [u.strip() for u in raw.split(",") if u.strip()]


def scan_profile(pool):
    """(profile, why) if this pool looks like what the wallets enter, else None."""
    x, y, cfg = pool["token_x"], pool["token_y"], pool["pool_config"]
    quote = next((a for a in (SOL_MINT, *sorted(QUOTES - {SOL_MINT}))
                  if a in (x["address"], y["address"])), None)
    if not quote or pool.get("is_blacklisted"):
        return None
    tok = y if x["address"] == quote else x
    if tok["address"] in QUOTES or tok.get("freeze_authority_disabled") is False:
        return None
    if cfg["base_fee_pct"] < 1:
        return None
    vol, ft = pool.get("volume") or {}, pool.get("fee_tvl_ratio") or {}
    now = time.time()
    age = (now - pool["created_at"] / 1000) / 3600
    old = (quote == SOL_MINT and 80 <= cfg["bin_step"] <= 125 and age < 168
           and pool["tvl"] >= SCAN_MIN_TVL and (vol.get("1h") or 0) >= SCAN_MIN_VOL_1H
           and (ft.get("1h") or 0) >= SCAN_MIN_FEE_TVL_1H)
    v30 = vol.get("30m")
    if (v30 is None and 48 <= age <= 672 and 50 <= cfg["bin_step"] <= 250
            and pool["tvl"] >= SCAN_STEADY_MIN_TVL and (vol.get("1h") or 0) >= SCAN_STEADY_MIN_VOL_1H
            and (ft.get("1h") or 0) >= SCAN_STEADY_MIN_FEE_TVL_1H):
        d = get(f"{DATAPI}/pools/{pool['address']}/volume/history?timeframe=5m&start_time={int(now - 2100)}&end_time={int(now)}") or {}
        v30 = sum((c.get("volume") or 0) for c in (d.get("data") or []) if c.get("timestamp", 0) + 300 <= now)
    steady = (48 <= age <= 672 and 50 <= cfg["bin_step"] <= 250
              and pool["tvl"] >= SCAN_STEADY_MIN_TVL
              and (vol.get("1h") or 0) >= SCAN_STEADY_MIN_VOL_1H
              and (v30 or 0) >= SCAN_STEADY_MIN_VOL_30M
              and (ft.get("1h") or 0) >= SCAN_STEADY_MIN_FEE_TVL_1H)
    if not (old or steady):
        return None
    cs = (get(f"{DATAPI}/pools/{pool['address']}/ohlcv?timeframe=1h&start_time={int(now - 25 * 3600)}&end_time={int(now)}") or {}).get("data") or []
    if len(cs) < 2:
        return None
    flip = x["address"] == quote  # prices are Y per X; we want the token priced in its quote
    close = [1 / c["close"] if flip else c["close"] for c in cs]
    high = max(1 / c["low"] if flip else c["high"] for c in cs)
    chg = lambda h: (close[-1] / close[-1 - h] - 1) * 100 if len(close) > h else None
    c1, c24, off_high = chg(1), chg(24) if len(close) > 24 else (close[-1] / close[0] - 1) * 100, (close[-1] / high - 1) * 100
    why = (f"pool {age:.0f}h old · 1h {c1:+.0f}% · 24h {c24:+.0f}% · {off_high:+.0f}% from the 24h high · "
           f"1h vol ${vol['1h'] / 1e3:,.0f}K · 1h fees {ft['1h']:.1f}% of TVL · bin step {cfg['bin_step']} · base fee {cfg['base_fee_pct']:g}%")
    if steady and (c1 or 0) >= -20 and off_high <= -15:
        return "steady pool", why
    if not old:
        return None
    if age < 24 and (c1 or 0) >= 20:
        return "fresh pool pumping", why
    if age >= 24 and (vol.get("24h") or 0) >= 1_000_000 and c24 >= 50:
        return "busy pool running up", why
    if age >= 24 and off_high <= -30 and (vol.get("24h") or 0) >= 200_000:
        return "dip after a run", why
    return None


def scan_candidates():
    pools = {}
    for sort in ("fee_tvl_ratio_1h:desc", "volume_1h:desc", "fee_tvl_ratio_30m:desc", "volume_24h:desc"):
        for page in (1, 2):
            d = get(f"{DATAPI}/pools?page={page}&page_size=50&sort_by={sort}&filter_by=tvl%3E{int(min(SCAN_MIN_TVL, SCAN_STEADY_MIN_TVL))}") or {}
            for pool in d.get("data") or []:
                pools[pool["address"]] = pool
    return sorted(pools.values(), key=lambda q: -((q.get("fee_tvl_ratio") or {}).get("1h") or 0))


def main():
    load_dotenv()
    global SCAN_EVERY, SCAN_MAX_PER_HOUR, SCAN_MIN_TVL, SCAN_MIN_VOL_1H, SCAN_MIN_FEE_TVL_1H
    global SCAN_STEADY_MIN_TVL, SCAN_STEADY_MIN_VOL_1H, SCAN_STEADY_MIN_VOL_30M, SCAN_STEADY_MIN_FEE_TVL_1H
    SCAN_EVERY = float(os.getenv("SCAN_EVERY_MIN", "5")) * 60
    SCAN_MAX_PER_HOUR = int(os.getenv("SCAN_MAX_PER_HOUR", "5"))
    SCAN_MIN_TVL = float(os.getenv("SCAN_MIN_TVL", "10000"))
    SCAN_MIN_VOL_1H = float(os.getenv("SCAN_MIN_VOL_1H", "30000"))
    SCAN_MIN_FEE_TVL_1H = float(os.getenv("SCAN_MIN_FEE_TVL_1H", "0.5"))
    SCAN_STEADY_MIN_TVL = float(os.getenv("SCAN_STEADY_MIN_TVL", "5000"))
    SCAN_STEADY_MIN_VOL_1H = float(os.getenv("SCAN_STEADY_MIN_VOL_1H", "8000"))
    SCAN_STEADY_MIN_VOL_30M = float(os.getenv("SCAN_STEADY_MIN_VOL_30M", "2000"))
    SCAN_STEADY_MIN_FEE_TVL_1H = float(os.getenv("SCAN_STEADY_MIN_FEE_TVL_1H", "0.05"))
    log_path = ROOT / (os.getenv("DISCORD_MESSAGE_LOG") or "out/discord_messages.jsonl")
    repost_after = float(os.getenv("POOL_REPOST_HOURS", "24")) * 3600
    if not os.getenv("DRY_RUN") and not os.getenv("POOL_WEBHOOK_URL"):
        sys.exit("Set POOL_WEBHOOK_URL in .env")
    state = json.loads(STATE.read_text()) if STATE.exists() else {}
    posted = state.get("posted", {})        # mint or pool -> unix time last researched
    misses = state.get("misses", {})        # address -> unix time it had no DLMM pool or got a PASS verdict
    offset = 0 if "--from-start" in sys.argv else state.get("offset")
    if offset is None:  # first run: start at the end so old messages don't flood the channel
        offset = log_path.stat().st_size if log_path.exists() else 0

    def save():
        now = time.time()
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps({
            "offset": offset,
            "posted": {k: t for k, t in posted.items() if now - t < 7 * 86400},
            "misses": {k: t for k, t in misses.items() if now - t < NOT_FOUND_RETRY},
        }))

    def handle(address, record):
        now = time.time()
        if now - misses.get(address, 0) < NOT_FOUND_RETRY or now - posted.get(address, 0) < repost_after:
            return
        found = resolve(address)
        if not found:
            misses[address] = now
            return
        mint, pool = found
        if now - max(posted.get(mint, 0), posted.get(pool, 0)) < repost_after:
            return
        p = research_pool(pool)
        log_alert(p, mint, posted=False)  # the AI trader decides and posts its take (lp_trader.post_take)
        misses[address] = misses[mint] = misses[pool] = now  # look again if it's mentioned after NOT_FOUND_RETRY
        print(f"alert {p['name']} {pool} from #{record.get('channel_name')} -> AI trader", flush=True)

    scan_log = []  # times the scanner posted, for the hourly cap

    def scan():
        now = time.time()
        if os.getenv("POOL_SCAN", "1") == "0" or now - track_state.get("last_scan", 0) < SCAN_EVERY:
            return
        track_state["last_scan"] = now
        scan_log[:] = [t for t in scan_log if now - t < 3600]
        for pool in scan_candidates():
            if len(scan_log) >= SCAN_MAX_PER_HOUR:
                return
            addr = pool["address"]
            tok = pool["token_y"] if pool["token_x"]["address"] in QUOTES else pool["token_x"]
            mint = tok["address"]
            if any(now - posted.get(k, 0) < repost_after or now - misses.get(k, 0) < NOT_FOUND_RETRY for k in (addr, mint)):
                continue
            found = scan_profile(pool)
            if not found:
                continue
            profile, why = found
            p = research_pool(addr)
            log_alert(p, mint, posted=False, origin=f"scanner: {profile}")  # the AI trader decides and posts
            posted[addr] = posted[mint] = now
            scan_log.append(now)
            save()
            print(f"scanner alert {p['name']} {addr} ({profile}) -> AI trader", flush=True)

    print(f"watching {log_path.relative_to(ROOT)} from byte {offset}", flush=True)
    track_state = {}
    while True:
        if os.getenv("WALLET_OPENS", "1") != "0" and time.time() - track_state.get("last_wallet_poll", 0) >= float(os.getenv("WALLET_POLL_MIN", "10")) * 60:
            try:
                import wallet_opens
                wallet_opens.poll(dry="--wallet-dry-run" in sys.argv)
                track_state["last_wallet_poll"] = time.time()
            except Exception as e:
                print(f"wallet poll failed: {e}", flush=True)
        try:
            scan()
        except Exception as e:
            print(f"scanner error: {e}", flush=True)
        try:
            track_alerted_pools(track_state)
        except Exception as e:
            print(f"tracking error: {e}", flush=True)
        try:
            check_followups(track_state)
        except Exception as e:
            print(f"followup error: {e}", flush=True)
        if log_path.exists():
            if log_path.stat().st_size < offset:  # log was truncated/rotated
                offset = 0
            with log_path.open("rb") as f:
                f.seek(offset)
                for line in f:
                    if not line.endswith(b"\n"):
                        break  # partial write; read it next time
                    offset += len(line)
                    try:
                        record = json.loads(line)
                    except ValueError:
                        continue
                    if too_old(record):
                        continue
                    for address in candidates(record.get("content") or ""):
                        try:
                            handle(address, record)
                        except Exception as e:  # one bad token/API hiccup shouldn't stop the watcher
                            print(f"failed on {address}: {e}", flush=True)
                    save()
        if "--once" in sys.argv:
            save()
            return
        time.sleep(5)


if __name__ == "__main__":
    main()
