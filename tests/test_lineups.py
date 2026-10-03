from nfl_assistant.lineups import best_lineup, lineup_slots, weekly_lineups

SLOTS = ["QB", "RB", "WR", "WR", "TE", "FLEX"]


def test_lineup_slots_drop_bench_and_ir():
    assert lineup_slots(["QB", "RB", "FLEX", "K", "DEF", "BN", "BN", "IR"]) == ["QB", "RB", "FLEX", "K", "DEF"]


def test_best_lineup_fills_flex_with_best_remaining():
    pos = {"q": "QB", "r1": "RB", "r2": "RB", "w1": "WR", "w2": "WR", "w3": "WR", "t": "TE"}
    pts = {"q": 20, "r1": 15, "r2": 9, "w1": 14, "w2": 13, "w3": 12, "t": 8}
    total, lineup = best_lineup(list(pos), pos, pts, SLOTS)
    assert dict((s, p) for s, p in lineup if s != "WR")["FLEX"] == "w3"
    assert total == 20 + 15 + 14 + 13 + 8 + 12


def test_weekly_lineups_handle_byes_and_empty_slots():
    proj = {
        "q": {"position": "QB", "weekly": {5: {"pts": 20}, 6: {"pts": 0, "bye": True}}},
        "q2": {"position": "QB", "weekly": {5: {"pts": 15}, 6: {"pts": 14}}},
        "r": {"position": "RB", "weekly": {5: {"pts": 10}, 6: {"pts": 10}}},
    }
    out = weekly_lineups(list(proj), proj, [5, 6], ["QB", "RB", "TE"])
    assert out[5]["total"] == 30 and dict(out[5]["lineup"])["QB"] == "q"
    assert out[6]["total"] == 24 and dict(out[6]["lineup"])["QB"] == "q2"     # backup covers the bye
    assert out[5]["empty"] == ["TE"]
