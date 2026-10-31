"""Watch public Meteora positions for new opens by the tracked wallets."""
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

WALLETS = (
    "Df2ExMUPPwMvhoGBXHJwracqo627WPmCgqAoi536ZLu9",
    "FehDPJwU9mAVmv2epKLWNwHBV7bCSBSNCzMmWhmjv6Ce",
    "8D1mjoT37ivcHH1jnxz5R5yxgv2MQHw4YP6HgpffjJPP",
    "FEFB58KCL1AszT3qV2ToKmWoHUhrRKBHS6jLcai4st4Z",
    "2DjfP3UCLyKm2TKjbXRoL7Psz5am3mJepcW2WQnxfktv",
    "7aDHQU46WtuADqbRZZmeojXAmZfNit55Uj4TiQNpwrkc",
    "BBRQTNHRKJgbXKcRrr7c9NNj6KAD9sc83Lw9ce9TVUfb",
    "EuPt2FBxWGRRf5vyX2UTauXYXYmjFnBqTwC4LkDh4kwK",
)
ROOT = Path(__file__).resolve().parent
STATE = ROOT / "out" / "wallet_opens_state.json"


def api(path, params):
    import pool_watch as w
    url = w.DATAPI + path + "?" + urlencode(params)
    for attempt in range(3):
        try:
            result = w.get(url)
            time.sleep(float(os.getenv("WALLET_POLL_SLEEP_SEC", "0.15")))
            return result or {}
        except Exception:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def open_pools(wallet):
    """Only count positions returned by status=open; avoid mistaking closed history for a current hold."""
    held = set()
    for page in range(1, 11):
        portfolio = api("/portfolio", {"user": wallet, "page": page, "page_size": 25, "days_back": 7})
        for item in portfolio.get("pools") or []:
            pool = item.get("poolAddress")
            if not pool:
                continue
            for n in range(1, 11):
                data = api(f"/positions/{pool}/pnl", {"user": wallet, "status": "open", "page": n,
                                                       "page_size": 100, "days_back": 7})
                if data.get("positions"):
                    held.add(pool)
                if not data.get("hasNext"):
                    break
        if not portfolio.get("hasNext"):
            break
    return held


def diff_openings(previous, current, now, window_h=2):
    events = {p: {w: t for w, t in times.items() if now - t <= window_h * 3600}
              for p, times in previous.get("events", {}).items()}
    for wallet, pools in current.items():
        for pool in pools - set(previous.get("held", {}).get(wallet, [])):
            events.setdefault(pool, {})[wallet] = now
    events = {p: v for p, v in events.items() if v}
    alerted = previous.get("alerted", {})
    fresh = [(p, len(v)) for p, v in events.items() if len(v) >= 2 and p not in alerted]
    return {"held": {w: sorted(v) for w, v in current.items()}, "events": events,
            "alerted": {**{p: t for p, t in alerted.items() if now - t < 86400},
                        **{p: now for p, _ in fresh}}}, fresh


def poll(dry=False):
    import pool_watch as w
    now = time.time()
    old = json.loads(STATE.read_text()) if STATE.exists() else None
    current = {}
    for wallet in WALLETS:
        current[wallet] = open_pools(wallet)
        if dry:
            print(f"tracked wallet …{wallet[-4:]}: {len(current[wallet])} open pool(s)")
    if old is None:
        new = {"held": {a: sorted(b) for a, b in current.items()}, "events": {}, "alerted": {}}
        fresh = []
        print("wallet tracker baseline saved; no alerts", flush=True)
    else:
        new, fresh = diff_openings(old, current, now, float(os.getenv("WALLET_OPEN_WINDOW_H", "2")))
    STATE.parent.mkdir(exist_ok=True)
    STATE.write_text(json.dumps(new))
    for pool, count in fresh:
        try:
            p = w.research_pool(pool)
            mint = (p.get("base_token") or {}).get("mint")
            if not mint:
                raise ValueError("research returned no token mint")
            w.log_alert(p, mint, posted=False, origin=f"wallets: {count} of 8 opened")
            print(f"wallet alert {p['name']} ({count} of 8) -> AI trader", flush=True)
        except Exception as e:
            print(f"wallet alert failed for {pool}: {e}", flush=True)
            new["alerted"].pop(pool, None)
            STATE.write_text(json.dumps(new))
