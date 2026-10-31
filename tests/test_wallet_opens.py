import wallet_opens as w
from wallet_opens import diff_openings


def test_two_distinct_wallets_open_within_window():
    t = 10000
    first, alerts = diff_openings({"held": {"a": [], "b": []}, "events": {}, "alerted": {}},
                                  {"a": {"pool"}, "b": set()}, t)
    assert alerts == []
    second, alerts = diff_openings(first, {"a": {"pool"}, "b": {"pool"}}, t + 600)
    assert alerts == [("pool", 2)]
    _, alerts = diff_openings(second, {"a": {"pool"}, "b": {"pool"}}, t + 1200)
    assert alerts == []


def test_old_open_does_not_count():
    first = {"held": {"a": ["pool"], "b": []}, "events": {}, "alerted": {}}
    _, alerts = diff_openings(first, {"a": {"pool"}, "b": {"pool"}}, 10000)
    assert alerts == []


def test_open_filter_uses_is_closed_and_closed_at(monkeypatch):
    def fake(path, params):
        if path == "/portfolio":
            return {"pools": [{"poolAddress": "open"}, {"poolAddress": "closed"}], "hasNext": False}
        return {"positions": [{"isClosed": path.endswith("closed/pnl"), "closedAt": None}], "hasNext": False}
    monkeypatch.setattr(w, "api", fake)
    assert w.open_pools("wallet") == {"open"}
