from nfl_assistant import defence, projections

SC = {"pts_allow_0": 10, "pts_allow_1_6": 7, "pts_allow_7_13": 4, "pts_allow_14_20": 1,
      "pts_allow_21_27": 0, "pts_allow_28_34": -1, "pts_allow_35p": -4}


def game(season, week, home, away, hs, as_, spread="", total=""):
    return {"season": season, "game_type": "REG", "week": str(week), "home_team": home, "away_team": away,
            "home_score": "" if hs is None else str(hs), "away_score": "" if as_ is None else str(as_),
            "spread_line": spread, "total_line": total}


def test_tiers_and_expected_tier_fall_as_opponents_score_more():
    assert defence.tier_points(0, SC) == 10 and defence.tier_points(17, SC) == 1 and defence.tier_points(40, SC) == -4
    low, mid, high = (defence.expected_tier(x, SC) for x in (14, 22, 30))
    assert low > mid > high
    assert -4 < high < 1 < low < 7


def test_results_and_implied_totals():
    rows = defence.results([game("2026", 1, "KC", "LV", 27, 10, "7", "45")], ("2026",))
    kc = next(r for r in rows if r["team"] == "KC")
    assert kc["allowed"] == 10 and kc["opp_implied"] == 19.0 and kc["home"]
    assert next(r for r in rows if r["team"] == "LV")["opp_implied"] == 26.0


def test_strength_and_estimate_use_both_teams_and_home_field():
    games = [game("2026", w, "KC", "LV", 30, 10) for w in (1, 2, 3)] + [game("2026", w, "NE", "NYJ", 20, 20) for w in (1, 2, 3)]
    st = defence.strength(defence.results(games, ("2026",)), "2026")
    weak_vs_good = defence.estimate_allowed("KC", "LV", True, st)       # LV offence scores little, KC allows little
    avg = defence.estimate_allowed("NE", "NYJ", True, st)
    assert weak_vs_good < avg
    assert defence.estimate_allowed("NE", "NYJ", False, st) == avg + 2 * defence.HOME_EDGE
    assert defence.strength([], "2026")["avg"] is None and defence.estimate_allowed("NE", "NYJ", True, {"avg": None}) is None


def test_expected_allowed_prefers_vegas():
    st = {"avg": 22.0, "off": {}, "def": {}}
    assert defence.expected_allowed("KC", {"opp": "LV", "home": True, "opp_implied": 17.5}, st) == (17.5, "vegas")
    assert defence.expected_allowed("KC", {"opp": "LV", "home": True, "opp_implied": None}, st) == (21.0, "estimate")


def test_fit_learns_from_lined_games_only_before_the_week():
    games, dlogs = [], {"KC": [], "LV": []}
    for w in range(1, 61):                       # KC holds LV low and scores big; lines agree
        allowed = 10 if w % 2 else 30
        games.append(game("2026", w, "KC", "LV", 24, allowed, "0", str(2 * allowed)))
        dlogs["KC"].append({"season": "2026", "week": w, "pts": defence.tier_points(allowed, SC) + 5})
        dlogs["LV"].append({"season": "2026", "week": w, "pts": defence.tier_points(24, SC) + 5})
    rows = defence.results(games, ("2026",))
    f = defence.fit(dlogs, rows, SC, "2026")
    assert f["games"] == 120 and f["b"] > 0.5
    assert defence.points(10, SC, f) > defence.points(30, SC, f) >= 0
    assert defence.fit(dlogs, rows, SC, "2026", week=5)["games"] == 8 and defence.points(None, SC, f) is None


def test_project_weeks_uses_the_defence_model():
    sched = {5: {"KC": {"opp": "LV", "home": True, "opp_implied": 14.0, "implied": 28.0, "margin": 14.0},
                 "LV": {"opp": "KC", "home": False, "opp_implied": 28.0, "implied": 14.0, "margin": -14.0}}}
    dm = {"fit": {"a": 5.0, "b": 1.0}, "strength": {"avg": 22.0, "off": {}, "def": {}}, "scoring": SC}
    kc = projections.project_weeks(7.0, "DEF", "KC", None, [5], 5, sched, {}, 21.0, None, dmodel=dm)[5]
    lv = projections.project_weeks(7.0, "DEF", "LV", None, [5], 5, sched, {}, 21.0, None, dmodel=dm)[5]
    assert kc["pts"] > 7.0 > lv["pts"] and kc["source"] == "vegas" and kc["allowed"] == 14.0
    assert kc["mult"] > 1 > lv["mult"]
