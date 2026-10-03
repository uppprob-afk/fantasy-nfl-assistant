from nfl_assistant import dashboard, nflverse


def test_compute_points_full_ppr(league, nflverse_rows):
    s = league["scoring_settings"]
    qb_w1, rb_w1 = nflverse_rows[0], nflverse_rows[2]
    assert nflverse.compute_points(qb_w1, s) == 18.0   # 250*.04 + 2*4 - 2 + 20*.1
    assert nflverse.compute_points(rb_w1, s) == 15.5   # 5.5 + 6 + 3 rec + 3.0 yds - 2 fumble


def test_compute_points_kicker(league, nflverse_rows):
    assert nflverse.compute_points(nflverse_rows[6], league["scoring_settings"]) == 9.0  # 2x40-49, 1 miss, 2 XP


def test_norm_name_strips_suffixes_and_punctuation():
    assert nflverse.norm_name("Randy Back Jr.") == "randy back"
    assert nflverse.norm_name("Amon-Ra St. Brown") == "amon ra st brown"
    assert nflverse.norm_name("Ka'imi Fairbairn") == "kaimi fairbairn"


def test_match_player_by_gsis_name_and_team(players, nflverse_rows):
    _, by_gsis, by_name = nflverse.index_rows(nflverse_rows)
    assert nflverse.match_player(players["qb1"], by_gsis, by_name) == "00-0000001"   # gsis with stray space
    assert nflverse.match_player(players["rb1"], by_gsis, by_name) == "00-0000002"   # "Jr." suffix
    assert nflverse.match_player(players["rb2"], by_gsis, by_name) == "00-0000004"   # same name, team decides
    assert nflverse.match_player(players["wr2"], by_gsis, by_name) is None


def test_crosscheck_statuses(league, players, matchups_by_week, nflverse_rows):
    pts = dashboard.weekly_points(matchups_by_week)
    ids = ["qb1", "rb1", "wr1", "rb2", "PIT", "wr2", "k1"]
    res = nflverse.crosscheck(ids, players, pts, [1, 2], nflverse_rows, league["scoring_settings"])

    assert res["qb1"]["status"] == "unverified"      # Sleeper 42.5 vs nflverse 40.5
    assert res["qb1"]["diff"] == 2.0
    assert res["qb1"]["week_diffs"] == {"1": {"sleeper": 20.0, "nflverse": 18.0}}
    assert res["rb1"]["status"] == "verified" and res["rb1"]["played_weeks"] == [1]
    assert res["wr1"]["status"] == "verified"
    assert res["rb2"]["status"] == "unverified" and res["rb2"]["diff"] == 4.0
    assert res["PIT"]["status"] == "not_checked" and "defences" in res["PIT"]["reason"]
    assert res["wr2"]["status"] == "not_checked" and "match" in res["wr2"]["reason"]
    assert res["k1"]["status"] == "verified"


def test_crosscheck_tolerance_boundary(league, players, nflverse_rows):
    # exactly 1 point off is still verified; more than 1 is unverified
    pts = {"qb1": {1: 19.0, 2: 22.5}}
    assert nflverse.crosscheck(["qb1"], players, pts, [1, 2], nflverse_rows,
                               league["scoring_settings"])["qb1"]["status"] == "verified"
    pts = {"qb1": {1: 19.01, 2: 22.5}}
    assert nflverse.crosscheck(["qb1"], players, pts, [1, 2], nflverse_rows,
                               league["scoring_settings"])["qb1"]["status"] == "unverified"


def test_crosscheck_skips_weeks_nflverse_hasnt_published(league, players, nflverse_rows):
    pts = {"qb1": {1: 18.0, 2: 22.5, 3: 30.0}}   # week 3 not in nflverse file yet
    res = nflverse.crosscheck(["qb1"], players, pts, [1, 2, 3], nflverse_rows, league["scoring_settings"])
    assert res["qb1"]["weeks"] == [1, 2] and res["qb1"]["status"] == "verified"


def test_crosscheck_waits_for_teams_nflverse_hasnt_updated(league, players, nflverse_rows):
    # Week 2 rows exist for BAL/SEA/CAR, but drop BAL's: as if BAL played Monday night
    rows = [r for r in nflverse_rows if not (r["team"] == "BAL" and r["week"] == "2")]
    pts = {"qb1": {1: 18.0, 2: 22.5}}
    res = nflverse.crosscheck(["qb1"], players, pts, [1, 2], rows, league["scoring_settings"])["qb1"]
    assert res["weeks"] == [1] and res["pending_weeks"] == [2] and res["status"] == "verified"


def test_crosscheck_counts_zero_when_team_played_but_player_had_no_stats(league, players, nflverse_rows):
    # SEA played week 1 (no rows for wr1, but give SEA a row via another player)
    rows = nflverse_rows + [dict(nflverse_rows[3], player_id="00-0000077", week="1",
                                 player_display_name="Someone Else")]
    pts = {"wr1": {1: 5.0, 2: 12.0}}
    res = nflverse.crosscheck(["wr1"], players, pts, [1, 2], rows, league["scoring_settings"])["wr1"]
    assert res["weeks"] == [1, 2] and res["status"] == "unverified" and res["diff"] == 5.0
