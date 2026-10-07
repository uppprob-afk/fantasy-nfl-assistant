import json

from nfl_assistant import model
from nfl_assistant import projections as pj


def comp(pos="WR", r_prior=10.0, actual=10.0, n_this=3):
    return {"position": pos, "baseline": 10.0, "cv": 0.5, "n_prior": 10, "games_prior": 10, "r_prior": r_prior,
            "team_changed": False, "n_this": n_this, "actual": actual, "expected": actual, "partial_weeks": []}


def rec(actual, week=1, pos="WR", partial=False, **kw):
    return {"week": week, "key": f"{pos}{week}{actual}", "pos": pos, "comp": comp(pos, **kw), "source": "neutral",
            "raw": None, "actual": actual, "partial": partial, "naive": 10.0}


def test_rate_from_defaults_match_player_rate():
    games = [{"season": "2025", "week": w, "pts": 12.0, "partial": False, "team": "KC", "position": "WR",
              "targets": 8, "carries": 0, "receptions": 5, "attempts": 0} for w in range(1, 9)]
    games += [{"season": "2026", "week": 1, "pts": 20.0, "partial": False, "team": "KC", "position": "WR",
               "targets": 10, "carries": 0, "receptions": 7, "attempts": 0}]
    usage = {"WR": {"per_target": 1.5, "per_carry": 0.0, "per_attempt": 0.0}}
    base = {"baseline": 10.0, "cv": 0.5}
    a = pj.player_rate(games, "2026", "2025", "WR", "KC", base, usage, 1)
    c = pj.rate_components(games, "2026", "2025", "WR", "KC", base, usage, 1)
    assert pj.rate_from(c)["rate"] == a["rate"] and pj.rate_from(c)["sd"] == a["sd"]


def test_bias_and_sd_scale_apply():
    c = comp()
    base = pj.rate_from(c)
    tuned = pj.rate_from(c, {"bias": {"WR": 0.9}, "sd_scale": {"WR": 1.2}})
    assert tuned["rate"] == round(base["rate"] * 0.9, 2)
    assert tuned["sd"] > base["sd"] * 1.05


def test_multiplier_damping_is_tunable():
    assert pj.multiplier_from("WR", "opponent", 0.1) == 1.05
    assert pj.multiplier_from("WR", "opponent", 0.1, {"dvp_damping": 1.0}) == 1.1
    assert pj.multiplier_from("WR", "neutral", None) == 1.0


def test_evaluate_reports_error_bias_and_coverage():
    recs = [rec(10.0), rec(14.0), rec(4.0, partial=True)]
    ev = model.evaluate(recs)
    # every game counts (partial ones too, that's what you'd have got); full games separately
    assert ev["games"] == 3 and ev["injured_or_partial"] == 1
    assert ev["mae"] == round((0 + 4 + 6) / 3, 2) and ev["bias"] == round((0 - 4 + 6) / 3, 2)
    assert ev["full_games"]["games"] == 2 and ev["full_games"]["mae"] == 2.0 and ev["full_games"]["naive_mae"] == 2.0
    assert set(ev["by_position"]) == {"WR"} and set(ev["by_week"]) == {1}


def test_tune_waits_for_enough_games():
    t = model.tune([rec(8.0)] * 10)
    assert t["changed"] == [] and "Not enough games" in t["reason"]


def test_tune_learns_a_shrunk_capped_bias():
    # everyone projects 10 but scores 8: the bias moves toward 0.8, shrunk, never below the cap
    recs = [rec(8.0, week=1 + i % 3) for i in range(600)]
    t = model.tune(recs)
    b = t["params"]["bias"]["WR"]
    assert model.BIAS_CAP[0] <= b < 1.0
    assert any(c["key"] == "bias.WR" for c in t["changed"])
    assert t["params"]["bias"]["RB"] == 1.0


def test_learn_keeps_defaults_when_validation_fails():
    # weeks 1-2 run low (learn a lower bias); week 3 runs high, so the learned bias does worse there
    recs = [rec(7.0, week=w) for w in (1, 2) for _ in range(300)] + [rec(12.0, week=3) for _ in range(300)]
    out = model.learn(recs)
    assert out["validation"] and not out["validation"]["passed"]
    assert out["changed"] == [] and out["params"]["bias"]["WR"] == 1.0


def test_ledger_saves_next_game_and_scores_it(tmp_path):
    proj = {"p1": {"position": "WR", "rate": 10.0, "sd": 5.0, "status": None, "confidence": "high",
                   "weekly": {4: {"pts": 0.0, "bye": True}, 5: {"pts": 11.0, "source": "vegas"}}}}
    path = tmp_path / "ledger.json"
    led = model.ledger_update(path, proj, {"p1": "Player One"}, {"p1"})
    assert list(led) == ["p1:5"] and led["p1:5"]["pts"] == 11.0 and led["p1:5"]["sd"] == 5.5
    assert json.loads(path.read_text())["p1:5"]["name"] == "Player One"
    s = model.ledger_score(led, [5], {"p1": {5: 20.0}})
    assert s["games"] == 1 and s["mae"] == 9.0 and s["coverage"] == 0.0 and s["last_week"] == 5
    assert model.ledger_score(led, [4], {})["games"] == 0


def test_history_replaces_same_week(tmp_path):
    path = tmp_path / "h.json"
    tuned = {"params": pj.params_or_default(None), "changed": []}
    model.history_update(path, 4, "a", tuned, {"games": 10, "mae": 6.0})
    h = model.history_update(path, 4, "b", tuned, {"games": 12, "mae": 5.5})
    assert len(h) == 1 and h[0]["at"] == "b" and h[0]["mae"] == 5.5



def test_project_applies_injury_script_and_qb_change():
    base = rec(10.0)
    p0, _ = model.project(base, None)
    hurt = {**base, "status": "Questionable", "practice": "limited"}
    assert abs(model.project(hurt, None)[0] - p0 * 0.85) < 1e-6           # starting availability
    fav = {**base, "game": {"margin": 7.0}}
    assert model.project(fav, {"script_pass": 0.05})[0] < p0               # favourites throw less
    qb = {**base, "qb_change": True}
    P = {"qb_factor": {"WR": {"factor": 0.9, "games": 100}}, "qb_change": 1.0}
    assert abs(model.project(qb, P)[0] - p0 * 0.9) < 1e-6


def test_per_position_setting_overrides_global():
    c = comp(actual=20.0)
    glob_ = pj.rate_from(c, {"usage_blend": 0.5})["rate"]
    assert pj.rate_from(c, {"usage_blend": 0.5, "by_pos": {"RB": {"baseline_games": 10}}})["rate"] == glob_
    assert pj.rate_from(c, {"usage_blend": 0.5, "by_pos": {"WR": {"baseline_games": 10}}})["rate"] < glob_


def test_partial_games_count_per_snap_when_enabled():
    games = [{"season": "2026", "week": w, "pts": 10.0, "pct": 0.8, "partial": False, "team": "KC", "position": "WR",
              "targets": 6, "carries": 0, "receptions": 4, "attempts": 0} for w in (1, 2, 3)]
    games.append({"season": "2026", "week": 4, "pts": 8.0, "pct": 0.4, "partial": True, "team": "KC", "position": "WR",
                  "targets": 3, "carries": 0, "receptions": 2, "attempts": 0})
    c = pj.rate_components(games, "2026", "2025", "WR", "KC", {"baseline": 10.0, "cv": 0.5}, {}, 1, 5)
    part = [g for g in c["this_games"] if g[4]]
    assert part == [(4, 16.0, None, 0.5, True)]                            # 8 pts on half his snaps = 16
    assert pj.rate_from(c, {"partial_weight": 1.0})["rate"] > pj.rate_from(c)["rate"]


def test_learn_quantiles_are_lopsided_and_banded():
    recs = [rec(a, week=1 + i % 3) for i, a in enumerate([2, 5, 7, 8, 9, 10, 11, 12, 20, 30] * 10)]
    q = model.learn_quantiles(recs, pj.params_or_default(None))["WR"]
    lo, mid, hi = q["q"][0][0], q["q"][0][2], q["q"][0][4]
    assert lo < mid < hi and (hi - mid) > (mid - lo)                        # longer upside tail
    assert len(q["edges"]) == 2 and q["games"] == 100
    pts = pj.quantile_points("WR", 10.0, {"quantiles": {"WR": q}})
    assert len(pts) == 5 and pts[0] < 10 < pts[4]


def test_rank_tiers_and_baseline():
    tiers = pj.rank_tiers([("WR", r, 20 - r / 2) for r in range(1, 30)])
    assert pj.rank_baseline_for("WR", 2, tiers) > pj.rank_baseline_for("WR", 25, tiers)
    assert pj.rank_baseline_for("WR", None, tiers) is None and pj.rank_baseline_for("QB", 1, tiers) is None
    c = comp(n_this=0, actual=None)
    c["n_prior"], c["rank_baseline"] = 0, 18.0
    assert pj.rate_from(c, {"rank_prior": 1.0})["rate"] > pj.rate_from(c, {"rank_prior": 0.0})["rate"]
