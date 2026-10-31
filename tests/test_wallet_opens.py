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
