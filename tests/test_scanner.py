import copy

import pytest

from nfl_assistant import dashboard, scanner

ALLOWED = {"IR"}


@pytest.fixture
def managers(users, rosters):
    return dashboard.manager_lookup(users, rosters, {"rival_one": "R1"})


@pytest.fixture
def depth_players(players):
    """Fixture players plus NFL depth charts for a couple of teams."""
    p = copy.deepcopy(players)
    p["qb2"] = {"full_name": "Quentin Two", "position": "QB", "team": "KC",
                "depth_chart_position": "QB", "depth_chart_order": 1}
    p["rb4"] = {"full_name": "Rex Starter", "position": "RB", "team": "DET",
                "depth_chart_position": "RB", "depth_chart_order": 1}
    p["rb5"] = {"full_name": "Benny Backup", "position": "RB", "team": "DET",
                "depth_chart_position": "RB", "depth_chart_order": 2}
    p["rb6"] = {"full_name": "Third Stringer", "position": "RB", "team": "DET",
                "depth_chart_position": "RB", "depth_chart_order": 3}
    p["wr9"] = {"full_name": "Freddie Agent", "position": "WR", "team": "MIA",
                "depth_chart_position": "LWR", "depth_chart_order": 2}
    return p


def run_scan(prev, curr, rosters, managers, prev_rosters=None, ir_open=1, season=None):
    return scanner.scan(prev, curr, prev_rosters or rosters, rosters, 1, managers,
                        ALLOWED, ir_open, season or {})


def test_no_changes_means_no_news(depth_players, rosters, managers):
    res = run_scan(depth_players, copy.deepcopy(depth_players), rosters, managers)
    assert res == {"my_players": [], "other_starters": [], "free_agents": [], "motivated_buyers": []}


def test_my_player_injury_ir_eligible(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["qb1"]["injury_status"] = "IR"
    res = run_scan(depth_players, curr, rosters, managers)
    [row] = res["my_players"]
    assert row["text"] == "Quinn Back is now IR."
    assert row["direction"] == "worse"
    assert row["action"].startswith("Eligible for IR: move them")


def test_my_player_out_not_ir_eligible(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["rb2"]["injury_status"] = "Out"
    [row] = run_scan(depth_players, curr, rosters, managers)["my_players"]
    assert "isn't IR-eligible" in row["action"] and "move" not in row["action"]


def test_ir_slot_full_message(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["qb1"]["injury_status"] = "IR"
    [row] = run_scan(depth_players, curr, rosters, managers, ir_open=0)["my_players"]
    assert row["action"] == "Eligible for IR, but your IR slot is full."


def test_recovery_is_reported_as_better(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["rb1"]["injury_status"] = None          # was Out
    [row] = run_scan(depth_players, curr, rosters, managers)["my_players"]
    assert row["direction"] == "better" and "no longer on the injury report" in row["text"]
    assert "action" not in row


def test_other_starter_injury_is_trade_opening_and_backup_surfaces(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["rb4"]["injury_status"] = "Out"          # R1's starting RB, DET RB1
    res = run_scan(depth_players, curr, rosters, managers, season={"rb5": {"avg": 4.2}})
    [row] = res["other_starters"]
    assert row["manager"] == "R1 (rival_one)" and row["action"].startswith("Trade opening")
    assert res["motivated_buyers"] == [{"roster_id": 2, "manager": "R1 (rival_one)",
                                        "team_name": "R1's Team", "position": "RB",
                                        "player": "Rex Starter", "status": "Out"}]
    [fa] = res["free_agents"]
    assert fa["id"] == "rb5" and fa["kind"] == "backup"   # only the next man up, not RB3
    assert fa["text"] == "Benny Backup is next up behind Rex Starter, who is now Out."
    assert fa["avg"] == 4.2


def test_questionable_starter_is_news_but_not_trade_opening(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["rb4"]["injury_status"] = "Questionable"
    res = run_scan(depth_players, curr, rosters, managers)
    assert len(res["other_starters"]) == 1 and "action" not in res["other_starters"][0]
    assert res["motivated_buyers"] == [] and res["free_agents"] == []


def test_other_teams_bench_players_are_ignored(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["te1"]["injury_status"] = "Out"          # on R1's IR, not a starter
    assert run_scan(depth_players, curr, rosters, managers)["other_starters"] == []


def test_free_agent_promoted_to_starter(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["wr9"]["depth_chart_order"] = 1
    [fa] = run_scan(depth_players, curr, rosters, managers)["free_agents"]
    assert fa["id"] == "wr9" and fa["direction"] == "promoted"
    assert fa["text"] == "Freddie Agent is now the starter on the depth chart."


def test_team_change(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["wr1"]["team"] = "NYJ"
    [row] = run_scan(depth_players, curr, rosters, managers)["my_players"]
    assert row["kind"] == "team" and row["text"] == "Wade Receiver moved from SEA to NYJ."
    curr["wr1"]["team"] = None
    [row] = run_scan(depth_players, curr, rosters, managers)["my_players"]
    assert row["text"] == "Wade Receiver was released by SEA."


def test_newly_available_after_drop(depth_players, rosters, managers):
    prev_rosters = copy.deepcopy(rosters)
    rosters[1]["players"].remove("wr4")
    res = run_scan(depth_players, depth_players, rosters, managers, prev_rosters=prev_rosters,
                   season={"wr4": {"avg": 9.5}})
    [fa] = res["free_agents"]
    assert fa["id"] == "wr4" and fa["kind"] == "available"
    assert "dropped by R1 (rival_one)" in fa["text"]


def test_free_agents_sorted_by_average(depth_players, rosters, managers):
    prev_rosters = copy.deepcopy(rosters)
    rosters[1]["players"] = [p for p in rosters[1]["players"] if p not in ("wr3", "wr4")]
    res = run_scan(depth_players, depth_players, rosters, managers, prev_rosters=prev_rosters,
                   season={"wr3": {"avg": 3.0}, "wr4": {"avg": 9.5}})
    assert [f["id"] for f in res["free_agents"]] == ["wr4", "wr3"]


def test_relevant_ids_filters_noise():
    players = {
        "a": {"position": "RB", "team": "KC", "depth_chart_order": 2},
        "b": {"position": "RB", "team": "KC", "depth_chart_order": 4, "search_rank": 900},
        "c": {"position": "WR", "team": "KC", "depth_chart_order": 5, "search_rank": 50},
        "d": {"position": "LB", "team": "KC", "depth_chart_order": 1},
        "e": {"position": "WR", "team": None, "depth_chart_order": 1},
    }
    assert scanner.relevant_ids(players, rostered={"e"}) == {"a", "c", "e"}


def test_news_items_tag_section_and_time(depth_players, rosters, managers):
    curr = copy.deepcopy(depth_players)
    curr["qb1"]["injury_status"] = "Questionable"
    items = scanner.news_items(run_scan(depth_players, curr, rosters, managers), "2026-10-06T19:00+11:00")
    assert [(i["section"], i["seen"]) for i in items] == [("my_players", "2026-10-06T19:00+11:00")]
