from nfl_assistant import model, roles
from nfl_assistant import projections as pj


def test_mix_range_puts_the_chance_he_sits_at_zero():
    q = [5.0, 7.0, 12.0, 18.0, 21.0]
    assert pj.mix_range(q, 1.0) == q
    assert pj.mix_range(q, 0.0) == [0.0] * 5
    mixed = pj.mix_range(q, 0.7)                 # 30% he sits: the 10th and 16th percentiles are 0
    assert mixed[:2] == [0.0, 0.0] and 0 < mixed[2] < q[2] and mixed[4] <= q[4]


def week(pts, avail=1.0):
    return {"pts": pts, "bye": False, "avail": avail}


def qb(team, rate, weekly):
    return {"position": "QB", "team": team, "rate": rate, "sd": 6.0, "weekly": weekly, "playoff_weeks": {}}


def test_backup_qbs_projected_by_their_chance_to_start():
    players = {"s": {"depth_chart_order": 1}, "b": {"depth_chart_order": 2}, "c": {"depth_chart_order": 3}}
    proj = {"s": qb("KC", 20.0, {5: week(20.0), 6: week(0.0, avail=0.0)}),       # starter out in week 6
            "b": qb("KC", 15.0, {5: week(15.0), 6: week(15.0)}),
            "c": qb("KC", 12.0, {5: week(12.0), 6: week(12.0)})}
    pj.apply_qb_depth(proj, players, {"backup_start": 0.1})
    assert proj["s"]["weekly"][5]["pts"] == 20.0 and "backup" not in proj["s"]
    assert proj["b"]["weekly"][5]["pts"] == 1.5 and proj["b"]["weekly"][5]["start"] == 0.1
    assert proj["b"]["weekly"][6]["pts"] == 15.0                                  # next man up starts
    assert proj["c"]["weekly"][5]["pts"] == 0.3                                   # third string: a quarter of the rate
    assert proj["b"]["rate_if_starts"] == 15.0 and proj["b"]["rate"] < 15.0


def test_no_depth_chart_leaves_qbs_alone():
    proj = {"a": qb("NYJ", 18.0, {5: week(18.0)}), "b": qb("NYJ", 14.0, {5: week(14.0)})}
    pj.apply_qb_depth(proj, {}, {"backup_start": 0.1})
    assert proj["b"]["weekly"][5]["pts"] == 14.0


def g(season, week, team, att):
    return {"season": season, "week": week, "team": team, "position": "QB", "attempts": att}


def test_learn_backup_start_counts_surprise_starts_only():
    logs = {"usual": [g("2026", w, "KC", 35) for w in (1, 2, 3, 5)],
            "backup": [g("2026", 4, "KC", 30), g("2026", 6, "KC", 30)]}
    reports = [{"season": "2026", "week": 6, "gsis_id": "usual", "report_status": "Out"}]   # week 6 was expected
    out = roles.learn_backup_start(logs, reports, start=0.0)
    assert out["surprise_starts"] == 1 and out["team_weeks"] == 3          # weeks 3-5 (2 starts needed first; week 6 expected)


def test_live_scorecard_grades_the_range_the_dashboard_showed():
    led = {"a:5": {"id": "a", "week": 5, "pts": 10.0, "sd": 2.0, "q": [0.0, 0.0, 9.0, 16.0, 19.0]},
           "b:5": {"id": "b", "week": 5, "pts": 10.0, "sd": 2.0}}                # older entry: +-1 sd
    out = model.ledger_score(led, [5], {"a": {5: 15.0}, "b": {5: 15.0}})
    rows = {r["id"]: r for r in out["rows_last_week"]}
    assert rows["a"]["inside"] and rows["a"]["inside_fc"] and not rows["b"]["inside"]
    assert out["coverage"] == 0.5 and out["coverage_fc"] == 1.0
