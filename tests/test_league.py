import json

import pytest

from nfl_assistant import league

MB = {1: [{"roster_id": 1, "matchup_id": 1, "points": 120}, {"roster_id": 2, "matchup_id": 1, "points": 100},
          {"roster_id": 3, "matchup_id": 2, "points": 110}, {"roster_id": 4, "matchup_id": 2, "points": 90}],
      2: [{"roster_id": 1, "matchup_id": 1, "points": 95}, {"roster_id": 3, "matchup_id": 1, "points": 130},
          {"roster_id": 2, "matchup_id": 2, "points": 105}, {"roster_id": 4, "matchup_id": 2, "points": 104}]}


def test_weekly_scores_results_and_medians():
    weekly, med = league.weekly_scores(MB, [1, 2])
    assert weekly[1] == [{"week": 1, "pts": 120.0, "opp": 2, "opp_pts": 100.0, "result": "W"},
                         {"week": 2, "pts": 95.0, "opp": 3, "opp_pts": 130.0, "result": "L"}]
    assert med == {1: 105.0, 2: 104.5}


def test_all_play_and_luck():
    weekly, _ = league.weekly_scores(MB, [1, 2])
    ap = league.all_play(weekly)
    # team 1: week 1 beats all 3; week 2 (95) beats nobody -> 3-3, expected 1 win, actual 1
    assert (ap[1]["w"], ap[1]["l"]) == (3, 3) and ap[1]["luck"] == 0.0
    # team 2: wk1 100 beats 90 (1-2); wk2 105 beats 95, 104 (2-1) -> 3-3 expected 1, actual 1 (wk2 W)
    assert ap[2]["actual_wins"] == 1 and ap[2]["expected_wins"] == 1.0
    # team 4: wk1 beats nobody, wk2 104 beats 95 -> 1-5, expected 1/3, actual 0 -> unlucky
    assert ap[4]["luck"] == pytest.approx(-0.33, abs=0.01)


def test_power_rankings_blend_and_weights():
    rows, w = league.power_rankings({1: 130, 2: 100, 3: 115}, {1: 100, 2: 130, 3: 115}, {1: 0.9, 2: 0.9, 3: 0.9}, 0)
    assert w == {"actual": 0.0, "projected": 0.9, "efficiency": 0.1}
    assert [r["roster_id"] for r in rows] == [2, 3, 1]          # week 0: projection only
    rows, w = league.power_rankings({1: 130, 2: 100, 3: 115}, {1: 100, 2: 130, 3: 115}, {1: 0.9, 2: 0.9, 3: 0.9}, 15)
    assert w["actual"] > w["projected"] and [r["roster_id"] for r in rows][0] == 1   # late season: results count more
    assert rows[0]["rank"] == 1


def test_odds_history_appends_and_replaces_same_day(tmp_path):
    p = tmp_path / "h.json"
    league.update_odds_history(p, "2026-10-03T19:00+10:00", 4, {1: 0.6})
    league.update_odds_history(p, "2026-10-03T21:00+10:00", 4, {1: 0.62})
    h = league.update_odds_history(p, "2026-10-06T19:00+11:00", 5, {1: 0.7})
    assert [x["odds"]["1"] for x in h] == [0.62, 0.7]
    assert json.loads(p.read_text()) == h
