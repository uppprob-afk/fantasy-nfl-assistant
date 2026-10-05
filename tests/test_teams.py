from nfl_assistant import teams


def g(week, pts, pct, car_share=None, tgt_share=None, team="CHI", pos="RB", season="2026", **kw):
    return {"season": season, "week": week, "pts": pts, "pct": pct, "car_share": car_share, "tgt_share": tgt_share,
            "team": team, "position": pos, "partial": False, "attempts": 0, "carries": 10, "targets": 3, **kw}


def test_weekly_role_flags_left_early_against_this_seasons_normal():
    swift = [g(1, 32, .57, .46), g(2, 13, .68, .52), g(3, 11, .69, .57), g(4, 7, .35, .28)]
    rows = teams.weekly_role(swift, "2026", "RB")
    assert [r["partial"] for r in rows] == [False, False, False, True]
    assert rows[0]["share"] == 0.46


def test_opportunity_week_when_player_ahead_left_early_or_sat():
    swift = teams.weekly_role([g(1, 32, .57, .46), g(2, 13, .68, .52), g(3, 11, .69, .57), g(4, 7, .35, .28)], "2026", "RB")
    mona = teams.weekly_role([g(w, 8, .35, .28) for w in (1, 2, 3)] + [g(4, 28, .54, .56), g(5, 9, .3, .3)], "2026", "RB")
    assert teams.opportunity_weeks(mona, [swift]) == {4, 5}       # week 4 left early, week 5 no game
    assert teams.opportunity_weeks(mona, [[]]) == set()             # never-played "starter" ignored


def test_job_security_ignores_opportunity_spike():
    weeks = [{"week": w, "share": s, "partial": False} for w, s in ((1, .26), (2, .32), (3, .29), (4, .62))]
    out = teams.job_security("RB", 2, weeks, {4}, starter_share=0.52)
    assert out["label"] == "One injury away"
    rising = teams.job_security("RB", 2, weeks, set(), starter_share=0.52)
    assert rising["label"] == "Rising"


def test_job_security_labels():
    w = lambda *s: [{"week": i + 1, "share": x, "partial": False} for i, x in enumerate(s)]
    assert teams.job_security("RB", 1, w(.66, .6, .7, .68), set(), None)["label"] == "Locked in"
    assert teams.job_security("WR", 1, w(.2, .19, .2, .18), set(), None)["label"] == "Lead role"
    assert teams.job_security("WR", 2, w(.28, .27, .12, .11), set(), None)["label"] == "Losing work"
    assert teams.job_security("QB", 1, w(1, 1, .98), set(), None)["label"] == "Locked in"
    assert teams.job_security("QB", 3, [], set(), None)["label"] == "Depth"
    assert teams.job_security("TE", 2, [], set(), None)["label"] == "One injury away"
    assert teams.job_security("K", 1, [], set(), None)["label"] == "Starter"


def test_position_strength_ranks_and_median():
    logs = {"a": [g(1, 20, .9, team="CHI"), g(2, 10, .9, team="CHI")], "b": [g(1, 5, .9, team="DET")],
            "c": [g(1, 12, .9, team="GB")]}
    totals = teams.team_week_totals(logs, "2026")
    sched = {1: {"CHI": {"opp": "DET"}, "DET": {"opp": "CHI"}, "GB": {"opp": "MIN"}}, 2: {"CHI": {"opp": "GB"}}}
    s = teams.position_strength(totals, {}, sched, "2026")["RB"]
    assert s["ppg"] == {"CHI": 15.0, "DET": 5.0, "GB": 12.0} and s["rank"]["CHI"] == 1 and s["median"] == 12.0
    assert s["allowed"]["DET"] == 20.0 and s["allowed_rank"]["DET"] == 1


def test_offence_volume_and_ranks():
    logs = {"qb": [g(1, 20, 1, pos="QB", attempts=35, carries=3, targets=0)],
            "rb": [g(1, 15, .7, carries=20, targets=4)]}
    totals = teams.team_week_totals(logs, "2026")
    games = [{"season": "2026", "game_type": "REG", "home_team": "CHI", "away_team": "DET", "home_score": "24", "away_score": "17"}]
    sched = {2: {"CHI": {"opp": "GB", "home": True, "implied": 23.5}}}
    o = teams.offence(totals, games, sched, "2026", 2)["CHI"]
    assert o["pass_pg"] == 35 and o["rush_pg"] == 23 and o["plays_pg"] == 58 and o["points_pg"] == 24.0
    assert o["next_opp"] == "GB" and o["implied_next"] == 23.5 and o["ranks"]["plays_pg"] == 1
