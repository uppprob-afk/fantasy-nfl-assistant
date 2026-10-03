from nfl_assistant import lab, trades

SLOTS = ["QB", "RB", "WR", "FLEX"]
WEEKS = [4, 5]


def P(pos, rate, status=None, bye=(), played=(), conf="medium", gt=3, gp=10):
    weekly = {}
    for w in WEEKS:
        if w in played:
            continue                                   # game already played: not in weekly
        weekly[w] = {"pts": 0.0, "bye": True} if w in bye else {"pts": float(rate), "bye": False, "avail": 1.0,
                                                                 "opp": "BUF", "home": w % 2 == 0}
    return {"position": pos, "team": "KC", "status": status, "rate": rate, "sd": 5.0, "se": 1.5,
            "confidence": conf, "weekly": weekly, "byes": list(bye), "games_this": gt, "games_prior": gp,
            "ros": sum(x["pts"] for x in weekly.values()), "actual_ppg": None, "expected_ppg": None}


def test_lab_players_align_weeks_and_zero_byes_and_played():
    proj = {"a": P("WR", 10, bye=(5,)), "b": P("RB", 8, played=(4,))}
    out = lab.lab_players(proj, WEEKS, {"a": {"name": "Al"}}, {"a": 1}, {"b": 21.5})
    assert out["a"]["w"] == [10.0, 0.0] and out["a"]["v"][1] == 0.0 and out["a"]["v"][0] == 25.0
    assert out["b"]["w"] == [0.0, 8.0] and out["b"]["a"] == 21.5
    assert out["a"]["n"] == "Al" and out["b"]["n"] == "b" and out["a"]["o"] == 1 and out["b"]["o"] is None
    assert out["a"]["ros"] == 10.0
    assert out["a"]["op"] == ["BUF", "BYE"] and out["b"]["op"] == ["", "@BUF"]


def test_tradeable_matches_trades_rule():
    recs = {"ok": P("WR", 10), "ir": P("WR", 10, status="IR"), "k": P("K", 9), "new": P("WR", 9, gt=0, gp=0)}
    compact = lab.lab_players(recs, WEEKS, {}, {}, {})
    for pid, p in recs.items():
        assert lab.tradeable(compact[pid]) == trades.tradeable(pid, recs)


def test_build_lab_data_includes_pipeline_check_scores():
    proj = {"q": P("QB", 20), "r": P("RB", 10), "w": P("WR", 9), "w2": P("WR", 7), "x": P("WR", 5)}
    rosters = [{"roster_id": 1, "players": ["q", "r", "w", "w2"], "reserve": [], "settings": {"waiver_position": 3}},
               {"roster_id": 2, "players": ["x"], "reserve": [], "settings": {}}]
    managers = {1: {"label": "me", "team_name": "Mine"}, 2: {"label": "them", "team_name": "Theirs"}}
    this_week = {1: {"mean": 50.0, "sd": 9.0, "starters": ["q", "r", "w", "w2"], "actual": {"r": 12.0}},
                 2: {"mean": 5.0, "sd": 2.0, "starters": ["x"], "actual": {}}}
    d = lab.build_lab_data(proj, WEEKS, SLOTS, rosters, managers, {}, {1: {"wins": 1}, 2: {"wins": 0}},
                           {4: [(1, 2)]}, this_week, 1, 1, "low", {"WR": 5.0}, 13, 4)
    assert d["check_scores"]["1"] == trades.Valuer(proj, WEEKS, SLOTS).value(["q", "r", "w", "w2"])["score"]
    assert d["rosters"]["1"]["players"] == ["q", "r", "w", "w2"] and d["rosters"]["1"]["waiver_position"] == 3
    assert d["schedule"] == {"4": [[1, 2]]} and d["this_week"]["1"]["mean"] == 50.0
    assert d["players"]["r"]["a"] == 12.0 and d["roster_size"] == 13
