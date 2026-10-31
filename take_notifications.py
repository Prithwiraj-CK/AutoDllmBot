"""State and compact formatting for public AI take notifications."""
import os
import statistics
import time
from datetime import datetime

import pool_watch as w


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
