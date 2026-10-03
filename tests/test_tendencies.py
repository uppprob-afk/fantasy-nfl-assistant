import json
from pathlib import Path

import pytest

from nfl_assistant import dashboard, faab, tendencies as T

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def txs():
    return json.loads((FIX / "transactions.json").read_text())


@pytest.fixture
def profs(txs, users, rosters, players):
    managers = dashboard.manager_lookup(users, rosters, {"rival_one": "R1"})
    log = faab.waiver_log(txs, players, managers)
    rows, _ = faab.manager_faab(txs, rosters, managers, 100, log)
    bids = T.bids_by_manager(txs, players)
    out = T.profiles(bids, rows, log, 100)
    for rid, wp in {1: 3, 2: 4, 3: 1, 4: 2}.items():
        out[rid]["waiver_position"] = wp
    return out


def test_bids_by_manager_outcomes(txs, players):
    b = T.bids_by_manager(txs, players)
    assert [(x["player"], x["bid"], x["outcome"]) for x in b[1]] == [("wr1", 20, "won"), ("rb2", 8, "outbid")]
    assert [x["outcome"] for x in b[4]] == ["invalid"]
    assert b[3][0]["position"] == "WR" and b[3][1]["position"] == "DEF"


def test_profiles_counts_and_style(profs):
    me = profs[1]
    assert (me["bids"], me["won"], me["outbid"], me["invalid"]) == (2, 1, 1, 0)
    assert me["typical_bid"] == 14 and me["max_bid"] == 20
    assert me["overpaid_total"] == 7 and me["overpaid_claims"] == 1
    assert me["positions"] == {"WR": 1, "RB": 1}
    assert me["style"] == "not enough bids yet"                       # needs 3+ bids
    r1 = profs[2]
    assert r1["bids"] == 3 and r1["style"] != "not enough bids yet" and r1["active"]


def test_style_labels():
    rows = [{"roster_id": i, "label": str(i), "username": str(i), "team_name": "t", "remaining": 50,
             "spent": 50, "fa_adds": 0} for i in (1, 2, 3)]
    bids = {1: [{"bid": 30, "position": "RB", "outcome": "won"}] * 3,
            2: [{"bid": 1, "position": "RB", "outcome": "outbid"}] * 3,
            3: [{"bid": 10, "position": "WR", "outcome": "won"}] * 3}
    p = T.profiles(bids, rows, [], 100)
    assert (p[1]["style"], p[2]["style"], p[3]["style"]) == ("big spender", "stingy", "middle of the pack")


def test_nearly_out_flag():
    rows = [{"roster_id": 1, "label": "a", "username": "a", "team_name": "t", "remaining": 12, "spent": 88}]
    assert T.profiles({}, rows, [], 100)[1]["nearly_out"]


def test_upgrade_for_uses_eligible_slots():
    lineup = [{"slot": "RB", "pts": 12.0}, {"slot": "WR", "pts": 9.0}, {"slot": "FLEX", "pts": 8.0},
              {"slot": "QB", "pts": 20.0}]
    assert T.upgrade_for(10.0, "RB", lineup) == 2.0          # replaces the FLEX
    assert T.upgrade_for(10.0, "QB", lineup) == -10.0
    assert T.upgrade_for(10.0, "K", lineup) is None


def lineup(rb_pts):
    return [{"slot": "QB", "pts": 20.0}, {"slot": "RB", "pts": rb_pts}, {"slot": "WR", "pts": 12.0},
            {"slot": "FLEX", "pts": max(rb_pts, 9.0)}]


def test_rivals_tiers_and_estimate(profs):
    lineups = {2: lineup(4.0), 3: lineup(15.0), 4: lineup(15.0)}
    r = T.rivals("RB", 12.0, 1, profs, lineups, my_waiver=3)
    likely = {x["roster_id"]: x for x in r["likely"]}
    assert set(likely) == {2}                                   # R1: big upgrade, active, has money
    assert likely[2]["upgrade"] == 8.0                          # replaces their 4-pt RB
    assert likely[2]["wins_ties"]                               # my waiver 3 beats their 4
    assert {x["roster_id"] for x in r["unlikely"]} >= {4}       # never bid, no upgrade
    e = r["estimate"]
    assert e["low"] == int(profs[2]["typical_bid"]) + 1 and e["high"] >= e["low"]


def test_hot_player_uses_possible_rivals(profs):
    lineups = {2: lineup(15.0), 3: lineup(15.0), 4: lineup(15.0)}
    quiet = T.rivals("WR", 10.0, 1, profs, lineups, 3, hot=False)
    hot = T.rivals("WR", 10.0, 1, profs, lineups, 3, hot=True)
    assert quiet["likely"] == [] and quiet["estimate"] is None
    assert hot["estimate"] is not None and "possible" in hot["estimate"]["basis"]


def test_broke_manager_is_unlikely(profs):
    profs[2]["remaining"] = 0
    r = T.rivals("RB", 30.0, 1, profs, {2: lineup(4.0)}, 3)
    assert 2 in {x["roster_id"] for x in r["unlikely"]}


def test_wildcard_flagged():
    likely = [{"label": "A", "typical": 5, "max": 8, "remaining": 50}]
    possible = [{"label": "B", "typical": 20, "max": 40, "remaining": 30}]
    e = T.estimate(likely, possible, hot=False)
    assert (e["low"], e["high"]) == (6, 9)
    assert e["wildcard"] == {"label": "B", "max": 30}            # capped at what they have left
