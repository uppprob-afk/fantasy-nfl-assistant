from nfl_assistant import recap

SLOTS = ["QB", "RB", "WR"]
POS = {"q1": "QB", "r1": "RB", "r2": "RB", "w1": "WR", "w2": "WR", "q2": "QB", "r3": "RB", "w3": "WR"}


def m(rid, mid, pts, starters, ppts):
    return {"roster_id": rid, "matchup_id": mid, "points": pts, "starters": starters, "players": list(ppts), "players_points": ppts}


def week():
    return [m(1, 1, 30.0, ["q1", "r1", "w1"], {"q1": 10.0, "r1": 5.0, "w1": 15.0, "r2": 12.0}),   # benched r2 (12) over r1 (5)
            m(2, 1, 35.0, ["q2", "r3", "w2"], {"q2": 15.0, "r3": 10.0, "w2": 10.0}),
            m(3, 2, 50.0, ["w3"], {"w3": 50.0}), m(4, 2, 40.0, [], {})]


def build(pregame=None, state=None):
    teams = {i: {"team_name": f"T{i}", "label": f"M{i}"} for i in (1, 2, 3, 4)}
    ledger = {"w1:4": {"pts": 8.0}, "r1:4": {"pts": 12.0}, "q1:4": {"pts": 10.0}, "w3:4": {"pts": 20.0}}
    odds = [{"week": 4, "odds": {"1": 0.5}}, {"week": 5, "odds": {"1": 0.4}}]
    roles = {"w3": {"name": "W3", "team": "KC", "pos": "WR", "kind": "target", "share": 0.2, "label": "Lead role",
                    "weeks": [{"week": 4, "share": 0.4, "partial": False, "opportunity": True}]}}
    return recap.build(4, week(), teams, 1, SLOTS, POS, {}, ledger, pregame or {}, state or {}, odds,
                       [{"week": 5, "bid": 7, "player": {"name": "X"}}, {"week": 4, "bid": 3}],
                       [{"type": "trade", "week": 5, "moves": []}], roles, {"w3": 3, "q1": 1},
                       {"r1": "Questionable"}, {"mae": 5.0}, [])


def test_my_week_result_calls_and_bench():
    r = build()
    my = r["mine"]
    assert my["won"] is False and my["opp"] == 2 and my["margin"] == 5.0 and my["rank"] == 4
    assert my["optimal"] == 37.0 and my["left_on_bench"] == 7.0 and my["optimal_would_win"]
    assert [x["name"] for x in my["should_have_started"]] == ["r2"]
    assert my["booms"][0]["id"] == "w1" and my["busts"][0]["id"] == "r1"
    assert (my["odds_before"], my["odds_after"]) == (0.5, 0.4)


def test_league_highlights_and_luck():
    r = build(pregame={"4": {"2": {"win_prob": 0.3, "mean": 25}, "1": {"win_prob": 0.7, "mean": 31}}})
    h = r["highlights"]
    assert h["top"]["rid"] == 3 and h["low"]["rid"] == 1
    assert h["upset"]["winner"] == 2 and h["upset"]["winner_pregame"] == 0.3
    assert h["luckiest_win"]["winner"] == 2 and h["unluckiest_loss"]["loser"] == 4
    assert r["has_pregame"] and r["games"][0]["margin"] == 5.0


def test_players_waivers_trades_and_roles():
    r = build()
    assert r["booms"][0]["id"] == "w3" and r["booms"][0]["diff"] == 30.0
    assert [c["bid"] for c in r["claims"]] == [7]                       # waivers processed after week 4
    assert len(r["trades"]) == 1 and r["roles"][0]["opportunity"] and r["roles"][0]["up"]
    assert r["injuries"][0]["name"] == "r1" and r["model"] == {"mae": 5.0}


def test_power_movers_and_history_files(tmp_path):
    r = build(state={"4": {"power": {"1": 3, "2": 1}}, "5": {"power": {"1": 1, "2": 2}}})
    assert r["movers"][0] == {"rid": 1, "from": 3, "to": 1, "change": 2}
    p = tmp_path / "pre.json"
    mk = lambda pa, pb: [{"teams": [{"roster_id": 1, "mean": 100, "sd": 20, "win_prob": 0.6, "played_pts": pa},
                                    {"roster_id": 2, "mean": 90, "sd": 20, "win_prob": 0.4, "played_pts": pb}]}]
    recap.save_pregame(p, 5, mk(0, 0))
    d = recap.save_pregame(p, 5, [{"teams": [{**t, "mean": 1} for t in mk(10, 0)[0]["teams"]]}])  # game started: keep pre-game
    assert d["5"]["1"]["mean"] == 100 and d["5"]["2"]["opp"] == 1
    assert recap.save_recap(tmp_path / "r.json", {"week": 4, "x": 1})["4"]["x"] == 1
