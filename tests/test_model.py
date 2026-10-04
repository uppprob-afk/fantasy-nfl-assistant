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
    assert ev["games"] == 2 and ev["partial_games_excluded"] == 1
    assert ev["bias"] == -2.0 and ev["mae"] == 2.0 and ev["naive_mae"] == 2.0
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
