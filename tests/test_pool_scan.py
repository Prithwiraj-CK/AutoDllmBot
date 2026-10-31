import time

import pool_watch as w


def pool(quote=w.SOL_MINT, age=100, step=200, vol=9000, v30=3000, fee=0.1):
    return {"address": "pool", "token_x": {"address": "token", "freeze_authority_disabled": True},
            "token_y": {"address": quote}, "pool_config": {"bin_step": step, "base_fee_pct": 1},
            "created_at": (time.time() - age * 3600) * 1000, "tvl": 20000,
            "volume": {"1h": vol, "30m": v30, "24h": 300000}, "fee_tvl_ratio": {"1h": fee}}


def test_steady_profile_accepts_wider_bins_and_usd(monkeypatch):
    monkeypatch.setattr(w, "get", lambda _: {"data": [{"close": 1, "high": 1.4, "low": 0.9}] * 25})
    assert w.scan_profile(pool())[0] == "steady pool"
    assert w.scan_profile(pool(quote=next(iter(w.QUOTES - {w.SOL_MINT}))))[0] == "steady pool"


def test_steady_profile_rejects_fading_flow_and_young_age(monkeypatch):
    monkeypatch.setattr(w, "get", lambda _: {"data": [{"close": 1, "high": 1.4, "low": 0.9}] * 25})
    assert w.scan_profile(pool(v30=100)) is None
    assert w.scan_profile(pool(age=20)) is None


def test_steady_profile_rejects_falling_price(monkeypatch):
    cs = [{"close": 1, "high": 1.4, "low": 0.9}] * 24 + [{"close": 0.7, "high": 0.8, "low": 0.6}]
    monkeypatch.setattr(w, "get", lambda _: {"data": cs})
    assert w.scan_profile(pool()) is None
