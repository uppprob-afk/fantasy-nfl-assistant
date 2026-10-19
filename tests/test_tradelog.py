from nfl_assistant import tradelog

TX = {"type": "trade", "status": "complete", "leg": 2, "status_updated": 10, "transaction_id": "t1",
      "roster_ids": [1, 2], "adds": {"a": 1, "b": 2}, "drops": {"a": 2, "b": 1},
      "waiver_budget": [{"sender": 2, "receiver": 1, "amount": 5}],
      "draft_picks": [{"season": "2027", "round": 3, "owner_id": 2, "previous_owner_id": 1}]}
PROJ = {"a": {"ros": 100.0, "position": "WR"}, "b": {"ros": 40.0, "position": "RB"}}
REPL = {"WR": 6.0, "RB": 5.0}
MATCHUPS = {
    2: [{"roster_id": 1, "starters": ["a"], "players_points": {"a": 20.0}}, {"roster_id": 2, "starters": [], "players_points": {"b": 9.0}}],
    3: [{"roster_id": 1, "starters": ["a"], "players_points": {"a": 15.0}}, {"roster_id": 2, "starters": ["b"], "players_points": {"b": 11.0}}],
}
ROSTERS = [{"roster_id": 1, "players": ["a"]}, {"roster_id": 2, "players": []}]


def test_sides_split_players_faab_and_picks():
    s = {x["rid"]: x for x in tradelog.sides(TX)}
    assert s[1]["got"] == ["a"] and s[1]["gave"] == ["b"] and s[1]["faab"] == 5
    assert s[2]["got"] == ["b"] and s[2]["faab"] == -5 and s[2]["picks"] == ["2027 round 3"]


def test_started_points_only_count_lineup_weeks():
    assert tradelog.started_points(MATCHUPS, [2, 3], 2, "b") == (11.0, 1)     # benched in week 2
    assert tradelog.started_points(MATCHUPS, [2, 3], 1, "a") == (35.0, 2)


def test_report_scores_sides_and_drops_players_no_longer_rostered():
    r = tradelog.report([TX], MATCHUPS, [2, 3], PROJ, REPL, 10, ROSTERS, {"a": "Al"}, {"a": "WR"})
    t = r["trades"][0]
    s = {x["rid"]: x for x in t["sides"]}
    assert s[1]["got"][0]["ros"] == 40.0 and s[1]["total"] == 75.0            # 35 started + (100 - 60)
    assert s[2]["got"][0]["ros"] == 0.0 and s[2]["total"] == 11.0             # b was dropped since
    assert t["winner"] == 1 and t["margin"] == 64.0
    assert r["summary"]["1"] == {"made": 1, "net": 64.0} and r["summary"]["2"]["net"] == -64.0


def test_close_trades_have_no_winner():
    proj = {"a": {"ros": 10.0, "position": "WR"}, "b": {"ros": 10.0, "position": "RB"}}
    rosters = [{"roster_id": 1, "players": ["a"]}, {"roster_id": 2, "players": ["b"]}]
    r = tradelog.report([TX], {}, [], proj, {}, 10, rosters, {}, {})
    assert r["trades"][0]["winner"] is None


def test_remember_values_saves_once_and_flags_late(tmp_path):
    path = tmp_path / "trade_values.json"
    d = tradelog.remember_values(path, [TX], PROJ, REPL, 10, week=5)
    assert d["t1"]["values"] == {"a": 40.0, "b": 0.0} and d["t1"]["late"] is True
    later = tradelog.remember_values(path, [TX], {"a": {"ros": 0.0, "position": "WR"}}, REPL, 10, week=6)
    assert later["t1"]["values"]["a"] == 40.0 and later["t1"]["seen_week"] == 5
    r = tradelog.report([TX], MATCHUPS, [2, 3], PROJ, REPL, 10, ROSTERS, {}, {}, then=later)
    a = next(g for s in r["trades"][0]["sides"] for g in s["got"] if g["id"] == "a")
    assert a["then"] == 40.0 and r["trades"][0]["late_value"] is True
