from nfl_assistant import advice

SS = [{"in": "a", "out": "b", "in_pts": 12.0, "out_pts": 10.0}]


def test_save_replaces_unlocked_advice_and_freezes_locked(tmp_path):
    path = tmp_path / "advice.json"
    advice.save(path, 5, SS, set(), [], [])
    d = advice.save(path, 5, [{"in": "c", "out": "d"}], set(), [], [])     # advice changed before kickoff
    assert list(d["5"]["startsit"]) == ["c>d"]
    d = advice.save(path, 5, [], {"c"}, [], [])                              # c has played: frozen
    assert list(d["5"]["startsit"]) == ["c>d"]
    d = advice.save(path, 5, [{"in": "e", "out": "f"}], {"c"}, [], [])
    assert set(d["5"]["startsit"]) == {"c>d", "e>f"}


def test_save_keeps_first_waiver_and_sell_flags(tmp_path):
    path = tmp_path / "advice.json"
    advice.save(path, 5, [], set(), [{"id": "w", "bid": 3, "drop": "x"}], [{"id": "s", "ppg": 20.0}])
    d = advice.save(path, 5, [], set(), [{"id": "w", "bid": 9, "drop": "y"}], [{"id": "s", "ppg": 25.0}])
    assert d["5"]["waivers"]["w"]["bid"] == 3 and d["5"]["sell"]["s"]["ppg"] == 20.0


def test_grade_scores_calls_and_whether_they_were_followed():
    history = {"5": {"startsit": {"a>b": {"in": "a", "out": "b"}, "c>d": {"in": "c", "out": "d"}},
                     "waivers": {"w": {"id": "w", "bid": 3, "drop": "x"}},
                     "sell": {"s": {"id": "s", "ppg": 20.0}}},
               "6": {"startsit": {"e>f": {"in": "e", "out": "f"}}, "waivers": {}, "sell": {}}}
    points = {"a": {5: 15.0}, "b": {5: 9.0}, "c": {5: 4.0}, "d": {5: 10.0},
              "w": {5: 12.0, 6: 8.0}, "x": {5: 6.0, 6: 6.0}, "s": {5: 11.0, 6: 13.0}}
    lineups = {5: {"a", "d"}}                                   # followed a>b, ignored c>d
    g = advice.grade(history, [5], points, lineups, {"a": "Al"})
    s = g["summary"]
    assert s["startsit"] == {"calls": 2, "right": 1, "followed": 1, "gained": 6.0, "missed": 0.0}
    a = next(x for x in g["startsit"] if x["in"] == "a")
    assert a["in_name"] == "Al" and a["right"] and a["followed"] and a["diff"] == 6.0
    assert g["waivers"][0]["ppg"] == 12.0 and g["waivers"][0]["drop_ppg"] == 6.0 and s["waivers"]["right"] == 1
    assert g["sell"][0]["after"] == 11.0 and s["sell"]["right"] == 1
    assert all(x["week"] == 5 for x in g["startsit"])           # week 6 isn't finished yet


def test_grade_counts_points_missed_by_ignoring_good_advice():
    history = {"5": {"startsit": {"a>b": {"in": "a", "out": "b"}}, "waivers": {}, "sell": {}}}
    g = advice.grade(history, [5], {"a": {5: 20.0}, "b": {5: 5.0}}, {5: {"b"}}, {})
    assert g["summary"]["startsit"]["missed"] == 15.0 and g["summary"]["startsit"]["gained"] == 0.0
