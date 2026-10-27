"""Live Meteora DLMM pool research + chart images. No API keys needed.

  python3 research.py scan            -> out/pools.json       top pools by fee/TVL, with flow + safety data
  python3 research.py chart <address> -> out/chart.png        candles, VPVR, RSI, example LP range, stats panel
                                         out/chart_pool.json  every number on the chart + the strategy idea

Data: Meteora DLMM data API, DexScreener API, RugCheck summary.
"""
import json
import math
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent
OUT = ROOT / "out"
METEORA = "https://dlmm.datapi.meteora.ag"
DEXSCREENER = "https://api.dexscreener.com/latest/dex/pairs/solana/"
RUGCHECK = "https://api.rugcheck.xyz/v1/tokens/{}/report/summary"
QUOTES = {"So11111111111111111111111111111111111111112", "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
          "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB"}


def get(url, params=None):
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"User-Agent": "sinclair-x-bot", "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)


def rugcheck(mint):
    try:
        d = get(RUGCHECK.format(mint))
        return {
            "score_normalised": d.get("score_normalised"),
            "lp_locked_pct": round(d.get("lpLockedPct") or 0, 1),
            "risks": [f"{r.get('level')}: {r.get('name')}" for r in d.get("risks", [])],
        }
    except Exception as e:  # rugcheck is rate-limited / flaky; research continues without it
        return {"error": str(e)}


def dexscreener(addresses):
    """Flow data (buys/sells, price change, socials) for up to 30 pools in one call."""
    try:
        pairs = get(DEXSCREENER + ",".join(addresses)).get("pairs") or []
    except Exception:
        return {}
    out = {}
    for p in pairs:
        tx = p.get("txns", {})
        out[p["pairAddress"]] = {
            "price_usd": float(p["priceUsd"]) if p.get("priceUsd") else None,
            "price_change_pct": p.get("priceChange", {}),
            "txns_24h": tx.get("h24", {}),
            "txns_1h": tx.get("h1", {}),
            "volume_1h": (p.get("volume") or {}).get("h1"),
            "has_website": bool((p.get("info") or {}).get("websites")),
            "has_twitter": any(s.get("type") == "twitter" for s in (p.get("info") or {}).get("socials", [])),
            "dexscreener_url": p.get("url"),
        }
    return out


def summarize(p):
    base_is_x = p["token_x"]["address"] not in QUOTES
    base, quote = (p["token_x"], p["token_y"]) if base_is_x else (p["token_y"], p["token_x"])
    age_h = (time.time() - p["created_at"] / 1000) / 3600
    vol, tvl = p["volume"]["24h"], p["tvl"]
    return {
        "address": p["address"],
        "name": p["name"] if base.get("symbol") else f"{base['address'][:4]}…{base['address'][-4:]}-{quote['symbol']}",
        "meteora_url": f"https://app.meteora.ag/dlmm/{p['address']}",
        "quote_symbol": quote["symbol"],
        "base_is_x": base_is_x,
        "base_token": {
            "symbol": base["symbol"], "mint": base["address"], "verified": base.get("is_verified"),
            "holders": base.get("holders"), "market_cap": base.get("market_cap"),
            "freeze_authority_disabled": base.get("freeze_authority_disabled"),
        },
        "pool_age_hours": round(age_h, 1),
        "bin_step": p["pool_config"]["bin_step"],
        "base_fee_pct": p["pool_config"]["base_fee_pct"],
        "dynamic_fee_pct": p.get("dynamic_fee_pct"),
        "tvl": round(tvl),
        "volume_1h": round(p["volume"]["1h"]),
        "volume_24h": round(vol),
        "fees_24h": round(p["fees"]["24h"]),
        "fee_tvl_pct_24h": round(p["fee_tvl_ratio"]["24h"], 2),
        "fee_tvl_pct_1h": round(p["fee_tvl_ratio"]["1h"], 3),
        "volume_to_tvl": round(vol / tvl, 1) if tvl else None,
        "mc_per_holder": round(base["market_cap"] / base["holders"]) if base.get("holders") and base.get("market_cap") else None,
    }


def scan(limit=8):
    d = get(f"{METEORA}/pools", {
        "page_size": 40,
        "sort_by": "fee_tvl_ratio_24h:desc",
        "filter_by": "tvl>25000 && volume_24h>250000 && is_blacklisted=false",
    })
    pools = [summarize(p) for p in d["data"]][:limit]
    flow = dexscreener([p["address"] for p in pools])
    for p in pools:
        p["flow"] = flow.get(p["address"])
        p["rugcheck"] = rugcheck(p["base_token"]["mint"])
        time.sleep(0.5)
    try:
        metrics = get(f"{METEORA}/stats/protocol_metrics")
    except Exception:
        metrics = None
    OUT.mkdir(exist_ok=True)
    out = {"generated_at": datetime.now(timezone.utc).isoformat(), "protocol_metrics": metrics, "pools": pools}
    (OUT / "pools.json").write_text(json.dumps(out, indent=2) + "\n")
    print(f"{len(pools)} pools -> out/pools.json")
    for p in pools:
        ch = ((p["flow"] or {}).get("price_change_pct") or {}).get("h24")
        print(f"  {p['name']:<22} tvl ${p['tvl']:>9,}  vol24 ${p['volume_24h']:>11,}  fee/tvl {p['fee_tvl_pct_24h']:>6}%  "
              f"24h {ch}%  bin {p['bin_step']:>3}  age {p['pool_age_hours']}h  {p['address']}")


# ---------- indicators ----------

def rsi(closes, n=14):
    if len(closes) <= n:
        return [None] * len(closes)
    out = [None] * n
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, n + 1)]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, n + 1)]
    ag, al = sum(gains) / n, sum(losses) / n
    out.append(100 - 100 / (1 + ag / al) if al else 100)
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
        out.append(100 - 100 / (1 + ag / al) if al else 100)
    return out


def volume_profile(candles, buckets=28):
    lo, hi = min(c["low"] for c in candles), max(c["high"] for c in candles)
    if hi <= lo:
        return [], []
    step = (hi - lo) / buckets
    vols = [0.0] * buckets
    for c in candles:
        a = int((c["low"] - lo) / step)
        b = min(int((c["high"] - lo) / step), buckets - 1)
        for k in range(a, b + 1):
            vols[k] += c["volume"] / (b - a + 1)
    return [lo + step * (k + 0.5) for k in range(buckets)], vols


def strategy(p, candles):
    """Rule-of-thumb DLMM setup from the LP Army playbook. An example for research posts, not advice."""
    last = candles[-1]["close"]
    day = [c for c in candles if c["timestamp"] >= candles[-1]["timestamp"] - 86400]
    hi, lo = max(c["high"] for c in day), min(c["low"] for c in day)
    range_pct = (hi / lo - 1) * 100
    ch24 = ((p.get("flow") or {}).get("price_change_pct") or {}).get("h24")
    if ch24 is None:
        ch24 = (last / day[0]["open"] - 1) * 100
    volatile = range_pct > 60 or p["pool_age_hours"] < 48

    if ch24 <= -30:
        shape, side = "Bid-Ask", "one-sided SOL below price"
        low, high = -min(85, max(40, range_pct * 0.7)), 0
        why = "downtrend: let it DCA you in on the way down and earn fees on the chop"
    elif ch24 >= 40:
        shape, side = "Spot", "one-sided SOL below price"
        low, high = -min(60, max(25, range_pct * 0.5)), 0
        why = "after a pump: catch the pullback instead of chasing the top"
    elif volatile:
        shape, side = "Bid-Ask", "one-sided SOL below price"
        low, high = -min(80, max(35, range_pct * 0.6)), 0
        why = "high volatility: wide range, weight the edges, small size"
    else:
        shape, side = "Spot", "two-sided around price"
        half = max(8, range_pct / 2)
        low, high = -half, half
        why = "range-bound: keep liquidity where the chop is"

    if volatile and high == 0 and low > -85:  # backtest: shallower ranges on fresh/volatile tokens got blown through by rugs
        low = -85
    bins = math.ceil(math.log((1 + high / 100) / (1 + low / 100)) / math.log(1 + p["bin_step"] / 10000))

    warnings = []
    if p["pool_age_hours"] < 24:
        warnings.append("pool under 1 day old")
    rc = p.get("rugcheck") or {}
    if any(r.startswith("danger") for r in rc.get("risks", [])):
        warnings.append("rugcheck danger flags")
    if p["base_token"].get("freeze_authority_disabled") is False:
        warnings.append("freeze authority active")
    t1 = (p.get("flow") or {}).get("txns_1h") or {}
    if t1.get("sells", 0) > 1.4 * max(t1.get("buys", 0), 1):
        warnings.append("sellers dominating the last hour")
    if p["volume_24h"] and p["volume_1h"] < 0.25 * p["volume_24h"] / 24:
        warnings.append("volume fading vs 24h average")
    if p["bin_step"] < 80 and volatile:
        warnings.append(f"bin step {p['bin_step']} is tight for this volatility")

    return {
        "shape": shape, "side": side, "range_low_pct": round(low), "range_high_pct": round(high),
        "bins": bins, "why": why, "range_24h_pct": round(range_pct), "change_24h_pct": round(ch24, 1),
        "warnings": warnings,
    }


# ---------- chart ----------

def chart(address, watermark="@SinClair_0000", badge=None, advisor=None, out_png="chart.png", label="example", show_setup=True):
    """badge: optional fn(pool) -> (label, colour) drawn top-right, e.g. a verdict.
    advisor: optional fn(pool, candles) -> strategy dict that replaces the rule-of-thumb one (or None to keep it).
    out_png / label: where the image goes (other names skip chart_pool.json) and what the drawn range is called.
    show_setup=False leaves the range and the setup panel off (e.g. when the advice is to skip)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.patches import Rectangle

    p = summarize(get(f"{METEORA}/pools/{address}"))
    p["flow"] = dexscreener([address]).get(address)
    p["rugcheck"] = rugcheck(p["base_token"]["mint"])

    age = p["pool_age_hours"]
    if age < 7.5:  # young pool: 5m candles over its whole life (the API serves at most ~8h of 5m candles per call)
        tf, hours = "5m", max(age + 0.5, 1.5)
    elif age < 72:
        tf, hours = "30m", 48
    else:
        tf, hours = "1h", 96
    now = int(time.time())
    candles = get(f"{METEORA}/pools/{address}/ohlcv",
                  {"timeframe": tf, "start_time": int(now - hours * 3600), "end_time": now})["data"]
    if not candles:
        sys.exit("no candles for this pool")
    if not p["base_is_x"]:  # API prices are Y per X; flip so the chart is always base priced in quote
        candles = [dict(c, open=1 / c["open"], close=1 / c["close"], high=1 / c["low"], low=1 / c["high"]) for c in candles]

    s = strategy(p, candles)
    p["strategy"] = s
    p["last_close"] = candles[-1]["close"]          # entry reference, base priced in quote
    p["candle_tf"] = tf
    p["last_candle_ts"] = candles[-1]["timestamp"]
    if advisor:
        s = advisor(p, candles) or s
        p["strategy"] = s
    closes = [c["close"] for c in candles]
    last = closes[-1]
    r = rsi(closes)

    bg, panel, fg, dim, up, down, accent, band = "#0b0e14", "#11151d", "#e6edf3", "#7d8590", "#26a69a", "#ef5350", "#f5a623", "#3b82f6"
    show_rsi = sum(x is not None for x in r) >= 6
    show_vpvr = len(candles) >= 12
    fig = plt.figure(figsize=(12, 6.75), dpi=150, facecolor=bg)
    price_bottom = 0.37 if show_rsi else 0.235
    price_w = 0.50 if show_vpvr else 0.56
    ax = fig.add_axes([0.06, price_bottom, price_w, 0.87 - price_bottom], facecolor=bg)
    axp = fig.add_axes([0.06 + price_w, price_bottom, 0.06, 0.87 - price_bottom], facecolor=bg, sharey=ax)
    axv = fig.add_axes([0.06, price_bottom - 0.135, price_w, 0.12], facecolor=bg, sharex=ax)
    axr = fig.add_axes([0.06, 0.085, price_w, 0.13], facecolor=bg, sharex=ax)
    if not show_vpvr:
        axp.set_visible(False)
    if not show_rsi:
        axr.set_visible(False)

    w = 0.7
    for i, c in enumerate(candles):
        col = up if c["close"] >= c["open"] else down
        ax.plot([i, i], [c["low"], c["high"]], color=col, linewidth=0.9)
        lo, hi = sorted([c["open"], c["close"]])
        ax.add_patch(Rectangle((i - w / 2, lo), w, max(hi - lo, last * 0.002), color=col))
        axv.bar(i, c["volume"], width=w, color=col, alpha=0.55)
    ax.set_xlim(-1, len(candles) + 1)

    # example LP range
    lo_p, hi_p = last * (1 + s["range_low_pct"] / 100), last * (1 + s["range_high_pct"] / 100)
    if not show_setup:
        lo_p = hi_p = last
    else:
        ax.axhspan(lo_p, hi_p, color=band, alpha=0.13)
        ax.text(0.01, lo_p, f" {label} {s['shape']} range {s['range_low_pct']}% → {s['range_high_pct']:+}%",
                color=band, fontsize=8, va="bottom", ha="left", transform=ax.get_yaxis_transform())
    ax.axhline(last, color=accent, linestyle="--", linewidth=0.8)
    for price, tag, col in ((last, "now", accent), (lo_p, "range low", band))[:2 if show_setup else 1]:
        ax.annotate(f"{tag} {small_price(price)}", xy=(0.995, price), xycoords=("axes fraction", "data"),
                    fontsize=7.5, color=bg, weight="bold", va="center", ha="right", zorder=5,
                    bbox=dict(boxstyle="square,pad=0.25", fc=col, ec="none"))
    ymin = min(min(c["low"] for c in candles), lo_p) * 0.95
    ymax = max(max(c["high"] for c in candles), hi_p) * 1.04
    ax.set_ylim(ymin, ymax)

    # VPVR
    centers, vols = volume_profile(candles)
    if vols:
        height = (centers[1] - centers[0]) * 0.85 if len(centers) > 1 else 1
        poc = vols.index(max(vols))
        axp.barh(centers, vols, height=height, color=[accent if k == poc else "#3d4451" for k in range(len(vols))])
    axp.axis("off")
    axp.set_title("VPVR", color=dim, fontsize=7, pad=2)

    axr.plot(range(len(r)), [x if x is not None else float("nan") for x in r], color="#b388ff", linewidth=1)
    axr.axhline(70, color=down, linewidth=0.6, linestyle=":")
    axr.axhline(30, color=up, linewidth=0.6, linestyle=":")
    axr.set_ylim(0, 100)
    axr.set_yticks([30, 70])

    step = max(1, len(candles) // 6)
    ticks = list(range(0, len(candles), step))
    bottom = axr if show_rsi else axv
    bottom.set_xticks(ticks)
    fmt = "%H:%M" if tf == "5m" else "%d %b %H:%M"
    bottom.set_xticklabels([datetime.fromtimestamp(candles[i]["timestamp"], timezone.utc).strftime(fmt) for i in ticks])
    for a in (ax, axv, axr):
        a.tick_params(colors=dim, labelsize=7)
        for sp in a.spines.values():
            sp.set_color("#262c36")
        a.grid(color="#1b2029", linewidth=0.6)
    plt.setp(ax.get_xticklabels(), visible=False)
    if show_rsi:
        plt.setp(axv.get_xticklabels(), visible=False)
    ax.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: small_price(v)))
    axv.yaxis.set_major_formatter(matplotlib.ticker.FuncFormatter(lambda v, _: usd(v)))
    axv.locator_params(axis="y", nbins=3)
    axv.set_ylabel("volume", color=dim, fontsize=7)
    axr.set_ylabel(f"RSI {round(r[-1]) if r[-1] is not None else ''}", color=dim, fontsize=7)

    fl = p["flow"] or {}
    pc = fl.get("price_change_pct") or {}
    fig.text(0.06, 0.935, f"{p['name']}", color=fg, fontsize=18, weight="bold")
    fig.text(0.06, 0.895, f"Meteora DLMM · price in {p['quote_symbol']} · {tf} candles (UTC) · bin step {p['bin_step']} · base fee {p['base_fee_pct']}% · "
             f"{address[:6]}…{address[-4:]}", color=dim, fontsize=8.5)
    x = 0.33
    for label in ("h1", "h6", "h24"):
        v = pc.get(label)
        if v is None:
            continue
        fig.text(x, 0.935, f"{label[1:]}{'h'} {v:+.1f}%", color=up if v >= 0 else down, fontsize=11, weight="bold")
        x += 0.085

    bt, rc = p["base_token"], p["rugcheck"]
    t24, t1 = fl.get("txns_24h") or {}, fl.get("txns_1h") or {}
    age = f"{p['pool_age_hours'] / 24:.1f}d" if p["pool_age_hours"] >= 48 else f"{p['pool_age_hours']:.0f}h"
    sections = [
        ("POOL", [
            ("TVL", usd(p["tvl"]), None), ("24h volume", usd(p["volume_24h"]), None),
            ("24h fees", usd(p["fees_24h"]), None), ("fee / TVL 24h", f"{p['fee_tvl_pct_24h']}%", None),
            ("volume / TVL", f"{p['volume_to_tvl']}x", None), ("pool age", age, down if p["pool_age_hours"] < 24 else None),
        ]),
        ("FLOW", [
            ("24h buys / sells", f"{t24.get('buys', '–')} / {t24.get('sells', '–')}", None),
            ("1h buys / sells", f"{t1.get('buys', '–')} / {t1.get('sells', '–')}",
             down if t1.get("sells", 0) > 1.4 * max(t1.get("buys", 0), 1) else None),
            ("24h range", f"{s['range_24h_pct']}%", None),
        ]),
        ("TOKEN", [
            ("market cap", usd(bt["market_cap"]) if bt.get("market_cap") else "n/a", None),
            ("holders", f"{bt['holders']:,}" if bt.get("holders") else "n/a", None),
            ("freeze auth", "revoked" if bt.get("freeze_authority_disabled") else "ACTIVE",
             None if bt.get("freeze_authority_disabled") else down),
            ("rugcheck risks", "n/a" if "error" in rc else str(len(rc.get("risks", []))),
             down if rc.get("risks") else None),
            ("socials", " + ".join(k for k, v in (("site", fl.get("has_website")), ("X", fl.get("has_twitter"))) if v) or "none",
             None if fl.get("has_twitter") else down),
        ]),
        (f"{label.upper()} SETUP", [
            ("shape", s["shape"], band), ("side", s["side"].replace(" price", ""), band),
            ("range", f"{s['range_low_pct']}% → {s['range_high_pct']:+}%", band),
            ("bins", f"~{s['bins']}", band),
        ]),
    ][:None if show_setup else -1]
    fig.add_artist(Rectangle((0.665, 0.06), 0.315, 0.86, transform=fig.transFigure, color=panel, zorder=-1))
    y = 0.89
    for title, rows in sections:
        fig.text(0.68, y, title, color=accent, fontsize=8.5, weight="bold")
        y -= 0.034
        for k, v, col in rows:
            fig.text(0.68, y, k, color=dim, fontsize=8.5)
            fig.text(0.965, y, v, color=col or fg, fontsize=8.5, ha="right", weight="bold")
            y -= 0.031
        y -= 0.012
    if s["warnings"] and show_setup:
        fig.text(0.68, y, "⚠ " + " · ".join(s["warnings"][:3]), color=down, fontsize=7, wrap=True)

    fig.text(0.06, 0.025, (f"{label} setup for research, " if show_setup else "research, ") + "not financial advice · data: Meteora, DexScreener, RugCheck",
             color=dim, fontsize=7)
    if watermark:
        fig.text(0.98, 0.025, watermark, color=fg, fontsize=8, ha="right", weight="bold")
    if badge:
        label, col = badge(p)
        fig.text(0.98, 0.935, f" {label} ", color=bg, fontsize=12, weight="bold", ha="right",
                 bbox=dict(boxstyle="round,pad=0.35", fc=col, ec="none"))

    OUT.mkdir(exist_ok=True)
    fig.savefig(OUT / out_png, facecolor=bg)
    plt.close(fig)
    if out_png == "chart.png":
        (OUT / "chart_pool.json").write_text(json.dumps(p, indent=2) + "\n")
    print(f"chart -> out/{out_png} ({p['name']}, {len(candles)} {tf} candles)")
    print(f"strategy: {s['shape']}, {s['side']}, {s['range_low_pct']}%..{s['range_high_pct']:+}%, ~{s['bins']} bins; "
          f"warnings: {s['warnings']}")
    return p


def small_price(v):
    """Meteora-style small prices: 0.000001463 -> 0.0₅1463."""
    if v <= 0 or v >= 0.01:
        return f"{v:.4g}"
    digits = f"{v:.12f}".split(".")[1]
    zeros = len(digits) - len(digits.lstrip("0"))
    return f"0.0{str(zeros).translate(str.maketrans('0123456789', '₀₁₂₃₄₅₆₇₈₉'))}{digits[zeros:zeros + 4].rstrip('0') or '0'}"


def usd(v):
    v = float(v)
    for div, suf in ((1e9, "B"), (1e6, "M"), (1e3, "K")):
        if abs(v) >= div:
            return f"${v / div:.1f}{suf}"
    return f"${v:.0f}"


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "scan":
        scan()
    elif len(sys.argv) >= 3 and sys.argv[1] == "chart":
        chart(sys.argv[2])
    else:
        sys.exit(__doc__)
