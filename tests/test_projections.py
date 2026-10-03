import pytest

from nfl_assistant import projections as P

SCORING = {"pass_yd": 0.04, "pass_td": 4, "pass_int": -2, "rush_yd": 0.1, "rush_td": 6, "rec": 1,
           "rec_yd": 0.1, "rec_td": 6, "fum_lost": -2, "sack": 1, "int": 2, "fum_rec": 2, "def_td": 6,
           "safe": 2, "ff": 1, "blk_kick": 2, "st_td": 6, "pts_allow_0": 10, "pts_allow_1_6": 7,
           "pts_allow_7_13": 4, "pts_allow_14_20": 1, "pts_allow_21_27": 0, "pts_allow_28_34": -1,
           "pts_allow_35p": -4}


def game(home, away, week, season="2026", hs="", as_="", spread="", total=""):
    return {"season": season, "game_type": "REG", "week": str(week), "home_team": home, "away_team": away,
            "home_score": hs, "away_score": as_, "spread_line": spread, "total_line": total, "gameday": "2026-10-11"}


def log(week, pts, pct=0.8, season="2026", pos="WR", team="KC", targets=0.0, carries=0.0, attempts=0.0):
    return {"season": season, "week": week, "team": team, "position": pos, "pts": pts, "pct": pct,
            "targets": targets, "carries": carries, "attempts": attempts,
            "parts": {"pass": 0.0, "rush": 0.0, "rec": pts}, "partial": False}


# --- schedule ----------------------------------------------------------------
def test_schedule_implied_totals_team_codes_and_byes():
    games = [game("KC", "LA", 5, spread="3", total="47"), game("BUF", "MIA", 5, hs="24", as_="20"),
             game("KC", "BUF", 6)]
    s = P.schedule(games, "2026")
    assert s[5]["KC"]["implied"] == 25.0 and s[5]["LAR"]["implied"] == 22.0   # LA -> LAR
    assert s[5]["LAR"]["opp"] == "KC" and s[5]["LAR"]["opp_implied"] == 25.0
    assert s[5]["BUF"]["played"] and not s[5]["KC"]["played"]
    assert s[6]["KC"]["implied"] is None
    assert "LAR" not in s[6] and "MIA" not in s[6]                              # byes
    assert P.unplayed_weeks(s, "BUF", [5, 6]) == [6]
    assert P.unplayed_weeks(s, "MIA", [5, 6]) == [6]                            # bye week stays (0 pts)


# --- partial games -------------------------------------------------------------
def test_partial_game_flagged_against_own_normal():
    games = [log(1, 20, 0.85), log(2, 18, 0.9), log(3, 4, 0.25), log(4, 22, 0.88)]
    P.mark_partial(games)
    assert [g["partial"] for g in games] == [False, False, True, False]


def test_two_recent_low_games_are_a_role_change_unless_injured():
    games = [log(1, 20, 0.85), log(2, 18, 0.9), log(3, 6, 0.3), log(4, 5, 0.3)]
    P.mark_partial(games)
    assert not any(g["partial"] for g in games)
    P.mark_partial(games, injured=True)
    assert [g["partial"] for g in games] == [False, False, True, True]


def test_part_time_players_are_not_judged_on_snaps():
    games = [log(1, 5, 0.2), log(2, 5, 0.25), log(3, 2, 0.05)]
    P.mark_partial(games)
    assert not any(g["partial"] for g in games)


def test_missing_snap_data_is_never_partial():
    games = [log(1, 20, None), log(2, 2, None)]
    P.mark_partial(games)
    assert not any(g["partial"] for g in games)


# --- defence points ------------------------------------------------------------
def test_def_logs_scores_team_defence():
    rows = [{"season": "2026", "season_type": "REG", "week": "1", "team": "PIT", "def_sacks": "2.5",
             "def_interceptions": "1", "fumble_recovery_opp": "1", "def_fumbles_forced": "1", "def_tds": "1"},
            {"season": "2026", "season_type": "REG", "week": "1", "team": "PIT", "def_sacks": "1.5"}]
    games = [game("PIT", "CLE", 1, hs="27", as_="13")]
    d = P.def_logs(rows, games, SCORING)
    # 4 sacks + 2 (int) + 2 (fum rec) + 1 (ff) + 6 (td) + 4 (13 allowed)
    assert d["PIT"][0]["pts"] == 19.0
    assert d["CLE"][0]["pts"] == 0.0                     # 27 allowed, no stats


# --- usage ---------------------------------------------------------------------
def test_usage_values_and_expected_points():
    logs = {"a": [dict(log(1, 0, season="2025"), targets=10, parts={"pass": 0, "rush": 0, "rec": 20}),
                  dict(log(2, 0, season="2025"), targets=10, parts={"pass": 0, "rush": 0, "rec": 10})]}
    u = P.usage_values(logs, "2025")
    assert u["WR"]["per_target"] == 1.5
    assert P.expected_points(dict(log(3, 0), targets=8), u) == 12.0
    assert P.expected_points(dict(log(3, 0, pos="K")), u) is None


# --- rate ----------------------------------------------------------------------
BASE = {"baseline": 10.0, "cv": 0.5}


def test_rate_blends_baseline_prior_season_and_this_season():
    games = [log(w, 12.0, season="2025") for w in range(1, 11)] + [log(w, 20.0) for w in (1, 2)]
    r = P.player_rate(games, "2026", "2025", "WR", "KC", BASE, {}, depth_order=1)
    # baseline 8.5 x2, prior 12 x5 (10 games x 0.5), this 20 x2
    assert r["rate"] == round((2 * 8.5 + 5 * 12 + 2 * 20) / 9, 2)
    assert r["games_prior"] == 10 and r["games_this"] == 2 and r["confidence"] == "medium"


def test_team_change_halves_last_season():
    games = [log(w, 12.0, season="2025", team="NYJ") for w in range(1, 11)]
    r = P.player_rate(games, "2026", "2025", "WR", "KC", BASE, {}, depth_order=1)
    assert r["team_changed"] and r["rate"] == round((2 * 8.5 + 2.5 * 12) / 4.5, 2)


def test_partial_games_excluded_and_usage_blended():
    usage = {"WR": {"per_target": 2.0, "per_carry": 0.0, "per_attempt": 0.0}}
    games = [dict(log(1, 30.0), targets=5), dict(log(2, 1.0), partial=True)]
    r = P.player_rate(games, "2026", "2025", "WR", "KC", BASE, usage, depth_order=1)
    assert r["games_this"] == 1 and r["partial_weeks"] == [2]
    assert r["actual_ppg"] == 30.0 and r["expected_ppg"] == 10.0
    assert r["rate"] == round((2 * 8.5 + 1 * 20.0) / 3, 2)          # this season = (30 + 10) / 2
    assert r["confidence"] == "low"


def test_role_baseline_for_backups():
    assert P.role_baseline("QB", 2, 20.0) == 3.0
    assert P.role_baseline("RB", 2, 10.0) == 4.5
    assert P.role_baseline("WR", None, 10.0) == 1.5
    assert P.role_baseline("K", None, 8.0) == 8.0


def test_high_confidence_needs_four_games_this_season():
    games = [log(w, 10.0, season="2025") for w in range(1, 17)] + [log(w, 10.0) for w in range(1, 5)]
    r = P.player_rate(games, "2026", "2025", "WR", "KC", BASE, {}, depth_order=1)
    assert r["confidence"] == "high"
    assert r["sd"] > r["se"] > 0


# --- weekly --------------------------------------------------------------------
@pytest.mark.parametrize("status,ahead,expected", [
    (None, 0, 1.0), ("Questionable", 0, 0.85), ("Questionable", 1, 1.0), ("Doubtful", 0, 0.25),
    ("Out", 0, 0.0), ("Out", 1, 0.75), ("Out", 2, 1.0), ("IR", 3, 0.0), ("IR", 4, 0.5), ("Sus", 0, 0.0)])
def test_availability(status, ahead, expected):
    assert P.availability(status, ahead) == expected


def test_matchup_multiplier_vegas_and_opponent():
    g = {"opp": "MIA", "implied": 27.5, "opp_implied": 17.5}
    m, src = P.matchup_multiplier("WR", g, {}, 22.5)
    assert src == "vegas" and m == pytest.approx(1 + 0.5 * (27.5 / 22.5 - 1))
    m, _ = P.matchup_multiplier("DEF", g, {}, 22.5)
    assert m == pytest.approx(1 + (22.5 - 17.5) / 22.5)
    g2 = {"opp": "MIA", "implied": None}
    assert P.matchup_multiplier("WR", g2, {("MIA", "WR"): 1.5}, 22.5) == (1.1, "opponent")   # capped
    assert P.matchup_multiplier("WR", g2, {}, 22.5) == (1.0, "neutral")


def test_project_weeks_byes_and_injuries():
    s = P.schedule([game("KC", "BUF", 5), game("KC", "BUF", 7), game("KC", "BUF", 9)], "2026")
    w = P.project_weeks(10.0, "WR", "KC", "IR", [5, 6, 7, 9], 5, s, {}, None)
    assert w[6] == {"pts": 0.0, "bye": True}
    assert w[5]["pts"] == 0.0 and w[7]["pts"] == 0.0            # IR: out at least 4 weeks
    assert w[9]["pts"] == 5.0                                     # then 50% chance back
    healthy = P.project_weeks(10.0, "WR", "KC", None, [5], 5, s, {}, None)
    assert healthy[5]["pts"] == 10.0 and healthy[5]["opp"] == "BUF"


# --- league-level --------------------------------------------------------------
def proj(pos, rate, ros=None, status=None, actual=None, games_this=3, expected=None):
    return {"position": pos, "rate": rate, "ros": ros if ros is not None else rate * 10, "status": status,
            "actual_ppg": actual, "games_this": games_this, "expected_ppg": expected, "confidence": "medium"}


def test_replacement_and_value_over_replacement():
    p = {"a": proj("WR", 15), "b": proj("WR", 9), "c": proj("WR", 8), "d": proj("WR", 7),
         "e": proj("WR", 20, status="IR"), "f": proj("WR", 30)}
    repl = P.replacement_rates(p, rostered={"f"})
    assert repl["WR"] == round((15 + 9 + 8) / 3, 2)            # injured FA ignored
    assert P.value_over_replacement(p["f"], repl, 10) == round(300 - repl["WR"] * 10, 1)


def test_buy_low_sell_high():
    p = {"mine_hot": proj("WR", 12, actual=20), "mine_ok": proj("WR", 12, actual=13),
         "their_cold": proj("RB", 14, actual=6), "their_ir": proj("RB", 14, actual=4, status="IR"),
         "their_k": proj("K", 9, actual=2), "few_games": proj("RB", 14, actual=3, games_this=1)}
    owners = {"mine_hot": 1, "mine_ok": 1, "their_cold": 2, "their_ir": 2, "their_k": 2, "few_games": 2}
    bs = P.buy_sell(p, owners, my_rid=1)
    assert [r["id"] for r in bs["sell_high"]] == ["mine_hot"]
    assert [r["id"] for r in bs["buy_low"]] == ["their_cold"]


def test_assign_finishes_ranks_within_position_and_week():
    from nfl_assistant.projections import assign_finishes
    logs = {"a": [{"season": "2026", "week": 1, "position": "WR", "pts": 10.0}],
            "b": [{"season": "2026", "week": 1, "position": "WR", "pts": 20.0},
                  {"season": "2026", "week": 2, "position": "WR", "pts": 5.0}]}
    dlogs = {"KC": [{"season": "2026", "week": 1, "position": "DEF", "pts": 7.0}]}
    assign_finishes(logs, dlogs)
    assert logs["b"][0]["finish"] == 1 and logs["a"][0]["finish"] == 2
    assert logs["b"][1]["finish"] == 1 and dlogs["KC"][0]["finish"] == 1


def test_td_per_touch_by_position():
    from nfl_assistant.projections import td_per_touch
    logs = {"a": [{"season": "2026", "position": "RB", "carries": 18, "targets": 2, "rush_td": 1, "rec_td": 0}],
            "b": [{"season": "2025", "position": "RB", "carries": 20, "targets": 0, "rush_td": 3}]}
    assert td_per_touch(logs, "2026") == {"RB": 0.05}
