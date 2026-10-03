import pytest

from nfl_assistant import cards


def proj(rate=12.0, sd=6.0, weekly=None, log=None, pos="WR", ros=None, team="KC", **extra):
    weekly = weekly or {5: {"pts": 12.0, "avail": 1.0, "mult": 1.08, "source": "vegas", "opp": "BUF", "home": True},
                        6: {"pts": 0.0, "bye": True},
                        7: {"pts": 10.2, "avail": 0.85, "mult": 0.94, "source": "opponent", "opp": "DEN", "home": False},
                        8: {"pts": 12.0, "avail": 1.0, "mult": 1.0, "opp": "LV", "home": True}}
    p = {"rate": rate, "sd": sd, "weekly": weekly, "log": log or [], "position": pos, "team": team,
         "ros": ros if ros is not None else sum(x["pts"] for x in weekly.values()), "confidence": "medium",
         "byes": [w for w, x in weekly.items() if x.get("bye")], "actual_ppg": 15.0, "expected_ppg": 11.0,
         "prior_ppg": 10.5, "partial_weeks": []}
    p.update(extra)
    return p


SCHED = {1: {"KC": {}}, 2: {"KC": {}}, 3: {"BUF": {}}, 4: {"KC": {}}}     # KC bye in week 3


def test_matchup_label():
    assert cards.matchup_label(1.08) == "easy" and cards.matchup_label(0.9) == "tough"
    assert cards.matchup_label(1.0) == "neutral" and cards.matchup_label(None) == "neutral"


def test_team_bye_weeks():
    assert cards.team_bye_weeks(SCHED, "KC") == {3}
    assert cards.team_bye_weeks(SCHED, None) == set()


def test_last_weeks_flags_and_average():
    log = [{"week": 2, "pct": 0.2, "partial": True}, {"week": 4, "pct": 0.8, "partial": False}]
    weeks = cards.last_weeks({2: 3.0, 4: 18.0}, log, [1, 2, 3, 4], {3}, n=3)
    assert [w["week"] for w in weeks] == [2, 3, 4]
    assert weeks[0]["partial"] and weeks[1]["bye"] and weeks[2]["played"]
    assert cards.avg_played(weeks) == pytest.approx(10.5)        # bye week excluded
    # didn't play and not rostered -> excluded from the average
    weeks = cards.last_weeks({4: 20.0}, [{"week": 4}], [2, 3, 4], set())
    assert cards.avg_played(weeks) == 20.0
    assert cards.avg_played([]) is None


def test_next_weeks_ranges_byes_and_matchups():
    nxt = cards.next_weeks(proj())
    assert [w["week"] for w in nxt] == [5, 6, 7]
    assert nxt[0] == {"week": 5, "bye": False, "pts": 12.0, "low": 6.0, "high": 18.0, "opp": "BUF", "home": True,
                      "avail": 1.0, "matchup": "easy", "source": "vegas"}
    assert nxt[1] == {"week": 6, "bye": True, "pts": 0.0}
    assert nxt[2]["matchup"] == "tough" and nxt[2]["avail"] == 0.85


def test_usage_skips_partial_games_unless_all_partial():
    log = [{"week": 1, "pct": 0.9, "targets": 8, "receptions": 6, "carries": 0, "attempts": 0, "partial": False},
           {"week": 2, "pct": 0.2, "targets": 1, "receptions": 1, "carries": 0, "attempts": 0, "partial": True},
           {"week": 3, "pct": 0.8, "targets": 10, "receptions": 7, "carries": 1, "attempts": 0, "partial": False}]
    u = cards.usage(log)
    assert u["games"] == 2 and u["snap_pct"] == 85 and u["targets"] == 9.0 and not u["partial_only"]
    u2 = cards.usage([log[1]])
    assert u2["games"] == 1 and u2["partial_only"]
    assert cards.usage([]) == {"games": 0}


def test_position_ranks():
    p = {"a": proj(ros=100), "b": proj(ros=150), "c": proj(ros=90, pos="RB")}
    r = cards.position_ranks(p)
    assert r["b"] == (1, 2) and r["a"] == (2, 2) and r["c"] == (1, 1)


def test_build_card_headline_trend_and_value():
    p = proj(log=[{"week": w, "pct": 0.8, "partial": False, "targets": 7} for w in (1, 2, 4)])
    c = cards.build_card("x", p, {1: 20.0, 2: 18.0, 4: 22.0}, [1, 2, 3, 4], SCHED, {"x": (4, 50)},
                         {"WR": 9.0}, 4, {"x": "sell-high"})
    assert c["last3_avg"] == 20.0                                   # weeks 2, 4 (3 = bye)
    assert c["next3_avg"] == pytest.approx((12.0 + 10.2) / 2, abs=0.05)
    assert c["trend"] == "down"
    assert c["season"] == {"pts": 60.0, "games": 3}
    v = c["value"]
    assert v["rank"] == 4 and v["flag"] == "sell-high" and v["vor"] == round(p["ros"] - 36, 1)
    assert [g["week"] for g in c["log"]] == [1, 2, 3, 4] and c["log"][2]["bye"]


def test_build_card_without_projection():
    c = cards.build_card("x", None, {1: 5.0}, [1], {}, {}, {}, 4, {})
    assert c["value"] is None and c["next3"] == [] and c["last3_avg"] is None


def test_finish_tiers():
    assert cards.finish_tiers(30) == {"boom": 15, "start": 30, "bust": 60}
    assert cards.finish_tiers(1)["boom"] == 1


def test_consistency_counts_starter_and_boom_weeks():
    tiers = cards.finish_tiers(24)   # boom <= 12, start <= 24, bust > 48
    log = [{"week": 1, "pts": 30.0, "finish": 3}, {"week": 2, "pts": 12.0, "finish": 30},
           {"week": 3, "pts": 4.0, "finish": 70}, {"week": 4, "pts": None, "bye": True},
           {"week": 5, "pts": 18.0, "finish": 20}]
    c = cards.consistency(log, tiers)
    assert c["games"] == 4 and c["floor"] == 4.0 and c["ceiling"] == 30.0
    assert (c["boom"], c["start"], c["bust"]) == (1, 2, 1)
    assert c["best_finish"] == 3 and c["ppg"] == 16.0
    assert cards.consistency([], tiers) == {"games": 0}


def test_opportunity_flags_unsustainable_touchdowns():
    log = [{"targets": 8, "receptions": 6, "carries": 0, "rec_yd": 80, "rec_td": 2, "tgt_share": 0.3},
           {"targets": 9, "receptions": 7, "carries": 0, "rec_yd": 90, "rec_td": 1, "tgt_share": 0.2},
           {"targets": 2, "receptions": 1, "carries": 0, "rec_yd": 5, "partial": True}]
    o = cards.opportunity(log, pos_td_rate=0.04)   # 17 targets -> 0.7 expected TDs, scored 3
    assert o["games"] == 2 and o["tds"] == 3 and o["exp_tds"] == 0.7
    assert o["td_note"] == "hot" and o["tgt_share"] == 0.25
    assert o["yds_per_touch"] == round(170 / 13, 1)
    assert cards.opportunity([], 0.04) == {"games": 0}


def test_schedule_ahead_marks_playoff_weeks():
    p = {"weekly": {5: {"pts": 12.0, "opp": "KC", "home": True, "mult": 1.1}, 6: {"pts": 0.0, "bye": True}},
         "playoff_weeks": {15: {"pts": 10.0, "opp": "BUF", "home": False, "mult": 0.9}}}
    s = cards.schedule_ahead(p)
    assert [x["week"] for x in s] == [5, 6, 15]
    assert s[0]["matchup"] == "easy" and s[1]["bye"] and s[1]["matchup"] is None
    assert s[2]["playoff"] and s[2]["matchup"] == "tough"


def test_calculated_points_only_when_sleeper_has_none():
    log = [{"week": 1, "pts": 12.34, "finish": 20}, {"week": 2, "pts": 8.0, "finish": 40}]
    last = cards.last_weeks({2: 9.5}, log, [1, 2], set())
    assert last[0]["pts"] is None and last[0]["calc"] == 12.3
    assert last[1]["pts"] == 9.5 and last[1]["calc"] is None
    assert cards.avg_played(last) == round((12.3 + 9.5) / 2, 1)
