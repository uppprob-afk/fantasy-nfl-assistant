from nfl_assistant.lineups import best_lineup, lineup_slots

SLOTS = ["QB", "RB", "WR", "WR", "TE", "FLEX"]


def test_lineup_slots_drop_bench_and_ir():
    assert lineup_slots(["QB", "RB", "FLEX", "K", "DEF", "BN", "BN", "IR"]) == ["QB", "RB", "FLEX", "K", "DEF"]


def test_best_lineup_fills_flex_with_best_remaining():
    pos = {"q": "QB", "r1": "RB", "r2": "RB", "w1": "WR", "w2": "WR", "w3": "WR", "t": "TE"}
    pts = {"q": 20, "r1": 15, "r2": 9, "w1": 14, "w2": 13, "w3": 12, "t": 8}
    total, lineup = best_lineup(list(pos), pos, pts, SLOTS)
    assert dict((s, p) for s, p in lineup if s != "WR")["FLEX"] == "w3"
    assert total == 20 + 15 + 14 + 13 + 8 + 12
