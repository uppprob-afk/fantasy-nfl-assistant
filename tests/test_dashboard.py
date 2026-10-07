from nfl_assistant import dashboard
from nfl_assistant.players import ir_allowed_statuses

NICKS = {"rival_one": "R1", "rival_two": "R2"}
EXPECTED = {"num_teams": 4, "qb_slots": 1, "ppr": 1.0, "waiver_type": "faab", "faab_budget": 100}


def test_settings_match_gives_no_warnings(league):
    assert dashboard.check_settings(league, EXPECTED) == []


def test_settings_mismatch_warns(league):
    league["scoring_settings"]["rec"] = 0.5
    league["roster_positions"].append("SUPER_FLEX")
    warnings = dashboard.check_settings(league, EXPECTED)
    assert len(warnings) == 2
    assert any("ppr" in w for w in warnings) and any("qb_slots" in w for w in warnings)


def test_manager_lookup_nicknames_and_team_names(users, rosters):
    m = dashboard.manager_lookup(users, rosters, NICKS)
    assert m[2]["label"] == "R1 (rival_one)"
    assert m[2]["team_name"] == "R1's Team"          # trailing space stripped
    assert m[3]["team_name"] == "rival_two"          # no team name -> username
    assert m[3]["nickname"] == "R2"
    assert m[1]["label"] == "my_username"


def test_weekly_points_collects_all_rosters(matchups_by_week):
    pts = dashboard.weekly_points(matchups_by_week)
    assert pts["qb1"] == {1: 20.0, 2: 22.5}
    assert pts["rb3"] == {2: 4.0}
    assert pts["k1"] == {1: 9.0}


def test_season_summary_counts_games_sensibly():
    # zero-point week with no evidence of playing doesn't count as a game
    s = dashboard.season_summary({1: 0.0, 2: 12.0}, [1, 2])
    assert s == {"points": 12.0, "games": 1, "avg": 12.0, "weekly": {"1": 0.0, "2": 12.0}}
    # ...but does if nflverse says they played
    assert dashboard.season_summary({1: 0.0, 2: 12.0}, [1, 2], {1, 2})["games"] == 2
    # the in-progress week is excluded
    assert dashboard.season_summary({1: 10.0, 3: 5.0}, [1, 2])["points"] == 10.0
    assert dashboard.season_summary({}, [1, 2])["avg"] == 0.0


def test_standings_order_and_faab(users, rosters):
    m = dashboard.manager_lookup(users, rosters, NICKS)
    rows = dashboard.standings(rosters, m, budget=100)
    assert [r["roster_id"] for r in rows] == [2, 3, 1, 4]   # wins, then points for
    me = next(r for r in rows if r["roster_id"] == 1)
    assert me["points_for"] == 200.5
    assert me["points_against"] == 190.05
    assert me["faab_remaining"] == 74
    assert me["rank"] == 3 and me["waiver_position"] == 3


def test_roster_view_slots_bench_ir_and_notes(league, rosters, players, matchups_by_week):
    pts = dashboard.weekly_points(matchups_by_week)
    allowed = ir_allowed_statuses(league["settings"])
    v = dashboard.roster_view(rosters[0], players, pts, [1, 2], league["roster_positions"], allowed, 1)
    assert [s["slot"] for s in v["starters"]] == ["QB", "RB", "WR", "FLEX", "DEF"]
    assert v["starters"][0]["points"] == 42.5 and v["starters"][0]["avg"] == 21.25
    assert {b["id"] for b in v["bench"]} == {"wr2", "rb3"}
    assert v["ir_open"] == 1
    notes = " ".join(v["notes"])
    assert "Will Hurt is designated IR and can move" in notes
    assert "Rob Doubt" not in notes                       # Doubtful isn't IR-eligible here
    assert "Randy Back Jr. (RB) is Out" in notes


def test_roster_view_flags_ineligible_player_in_ir_slot(league, rosters, players):
    allowed = ir_allowed_statuses(league["settings"])
    v = dashboard.roster_view(rosters[1], players, {}, [1, 2], league["roster_positions"], allowed, 1)
    assert [p["id"] for p in v["ir"]] == ["te1"]
    assert any("Tim Endy is in an IR slot" in n for n in v["notes"])


def test_roster_view_empty_slots(league, rosters, players):
    v = dashboard.roster_view(rosters[2], players, {}, [1], league["roster_positions"], {"IR"}, 1)
    assert v["starters"][1] == {"id": None, "name": "Empty", "position": "RB", "slot": "RB"}


def test_matchup_pairs_puts_mine_first(users, rosters, matchups_by_week):
    m = dashboard.manager_lookup(users, rosters, NICKS)
    pairs = dashboard.matchup_pairs(matchups_by_week[2], m, my_roster_id=1)
    assert pairs[0]["is_mine"] and pairs[0]["teams"][0]["roster_id"] == 1
    assert pairs[0]["teams"][1]["roster_id"] == 3
    assert sum(p["is_mine"] for p in pairs) == 1


def test_playoff_weeks_from_settings():
    from nfl_assistant.run import playoff_weeks
    assert playoff_weeks({"playoff_week_start": 15, "playoff_teams": 4}) == [15, 16]
    assert playoff_weeks({"playoff_week_start": 15, "playoff_teams": 6}) == [15, 16, 17]
    assert playoff_weeks({"playoff_week_start": 15, "playoff_teams": 4, "playoff_round_type": 1}) == [15, 16, 17]
    assert playoff_weeks({"playoff_week_start": 16, "playoff_teams": 8, "playoff_round_type": 2}) == [16, 17, 18]


def test_prune_drops_nulls_and_output_is_compact(tmp_path):
    import json
    from nfl_assistant.output import prune, write_site_data
    assert prune({"a": None, "b": [1, {"c": None, "d": 2}], "e": {"f": None}}) == {"b": [1, {"d": 2}], "e": {}}
    write_site_data(tmp_path, "x", {"k": [1, 2]})
    assert (tmp_path / "x.json").read_text().strip() == '{"k":[1,2]}'
    assert json.loads((tmp_path / "x.json").read_text()) == {"k": [1, 2]}
