"""State and compact formatting for public AI take notifications."""
import os
import statistics
import time
from datetime import datetime

import pool_watch as w
import lp_model as model


def should_post(previous, action, vol, fee, now):
    if not previous:
        return True
    if previous["action"] != action:
        return True
    if vol >= 2 * max(previous.get("vol", 0), 1) or fee >= 2 * max(previous.get("fee", 0), 0.001):
        return True
    return now - previous["t"] >= 86400


def queue_skip(state, m, decision, route):
    state.setdefault("skip_digest", []).append({"t": time.time(), "mint": m["mint"], "name": m["name"],
                                                  "why": decision["why"], "age_h": m["age_h"],
                                                  "vol_1h": m["vol_1h"], "route": route})


def digest_due(state, now):
    day = datetime.fromtimestamp(now, w.IST).strftime("%Y-%m-%d")
    hour = datetime.fromtimestamp(now, w.IST).hour
    return hour >= int(os.getenv("LP_TRADER_DIGEST_HOUR_IST", "9")) and state.get("digest_day") != day, day


def digest_lines(rows):
    latest = {}
    for r in rows:
        latest[r["mint"]] = r
    return [f"{w.strip_names(r['name'])} · {w.strip_names(r['why']).replace(chr(10), ' ')[:120]} "
            f"· {r['age_h']:.0f}h old · ${r['vol_1h']:,.0f}/h" for r in latest.values()]


def hit_rate(results, now):
    xs = [r["pnl_pct"] for r in results if now - r["t"] <= 7 * 86400]
    return (f"AI calls last 7 days: {sum(x > 0 for x in xs)} of {len(xs)} green, "
            f"median {statistics.median(xs):+.1f}%") if xs else "AI calls last 7 days: no completed simulations yet"


def simulate_take(take, candles, fees):
    """Mark the posted layers at the chosen horizon using actual candles and fees, and entry-time fee share."""
    plan = take["plan"]
    layers = plan.get("layers") or [{"shape": plan["shape"], "lo": plan["lo"], "hi": plan["hi"], "w": 1.0}]
    stake, p0 = take["stake_quote"], take["price"]
    bins = model.bins_layers(p0, layers, take["bin_step"], stake)
    due = take["t"] + take["hold_h"] * 3600
    post = [c for c in candles if c["timestamp"] >= take["t"] and c["timestamp"] + 300 <= due]
    if not post or post[-1]["timestamp"] + 600 < due:
        return None
    fee_quote = sum(model.candle_fees_share(bins, c, fees.get(c["timestamp"], 0) / take["quote_usd"],
                                            take["share"]) for c in post)
    last = post[-1]["close"]
    pnl = (model.value(bins, last) + fee_quote) / stake - 1
    return {"pnl_pct": pnl * 100, "price_pct": (last / p0 - 1) * 100, "fee_pct": fee_quote / stake * 100}
