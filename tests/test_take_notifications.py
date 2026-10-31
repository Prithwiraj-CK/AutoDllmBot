import take_notifications as n


def test_mint_card_dedupe_and_material_change():
    old = {"t": 1000, "action": "skip", "vol": 10000, "fee": 0.1}
    assert not n.should_post(old, "skip", 15000, 0.15, 2000)
    assert n.should_post(old, "enter", 10000, 0.1, 2000)
    assert n.should_post(old, "skip", 20000, 0.1, 2000)
    assert n.should_post(old, "skip", 10000, 0.2, 2000)
    assert n.should_post(old, "skip", 10000, 0.1, 1000 + 86400)


def test_digest_keeps_latest_per_mint():
    rows = [{"mint": "a", "name": "A-SOL", "why": "old", "age_h": 10, "vol_1h": 10000},
            {"mint": "a", "name": "A-SOL", "why": "new", "age_h": 11, "vol_1h": 12000}]
    assert len(n.digest_lines(rows)) == 1
    assert "new" in n.digest_lines(rows)[0]
