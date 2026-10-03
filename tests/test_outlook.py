import math

import pytest

from nfl_assistant import outlook as O

SLOTS = ["QB", "RB", "WR", "FLEX"]


def P(pos, rate, sd=6.0, weeks=(5, 6), bye=(), avail=None, conf="medium", se=2.0):
    weekly = {}
    for w in weeks:
        if w in bye:
            weekly[w] = {"pts": 0.0, "bye": True}
        else:
            a = (avail or {}).get(w, 1.0)
            weekly[w] = {"pts": rate * a, "bye": False, "avail": a, "opp": "BUF", "home": True}
    return {"position": pos, "rate": rate, "sd": sd, "se": se, "weekly": weekly, "confidence": conf}


def test_player_week_played_bye_and_questionable():
    p = P("WR", 10, avail={5: 0.85})
    m, v, todo = O.player_week(p, 5)
    assert todo and m == pytest.approx(8.5)
    assert v == pytest.approx(0.85 * 36 + 0.85 * 0.15 * 100)    # spread + may-not-play risk
    assert O.player_week(p, 7) == (0.0, 0.0, False)              # not in weekly = already played
    assert O.player_week(P("WR", 10, bye=(5,)), 5) == (0.0, 0.0, True)
    assert O.player_week(None, 5) == (0.0, 0.0, False)


def test_team_week_mixes_actual_and_projected():
    proj = {"a": P("QB", 20, weeks=(6,)), "b": P("RB", 10)}       # a already played week 5
    t = O.team_week(["a", "b", "0"], {"a": 31.5}, proj, 5)
    assert t["played_pts"] == 31.5 and t["projected_pts"] == 10.0 and t["mean"] == 41.5
    assert t["sd"] == 6.0
    assert [r["status"] for r in t["players"]] == ["played", "projected", "empty"]


def test_win_probability():
    a, b = {"mean": 110, "sd": 20}, {"mean": 100, "sd": 20}
    assert O.win_probability(a, b) == pytest.approx(O.phi(10 / math.sqrt(800)))
    assert O.win_probability(b, a) == pytest.approx(1 - O.win_probability(a, b))
    assert O.win_probability({"mean": 90, "sd": 0}, {"mean": 80, "sd": 0}) == 1.0


def test_start_sit_verdicts():
    proj = {"q": P("QB", 20), "q2": P("QB", 30), "r": P("RB", 15), "r2": P("RB", 14),
            "w": P("WR", 18), "w2": P("WR", 5), "f": P("RB", 9, bye=(5,))}
    starters = ["q", "r", "w", "f"]
    roster = starters + ["q2", "r2", "w2"]
    rows = {r["slot"]: r for r in O.start_sit(starters, roster, proj, 5, SLOTS)}
    assert rows["QB"]["verdict"] == "swap" and rows["QB"]["alt"] == "q2"
    assert rows["RB"]["verdict"] == "close" and rows["RB"]["alt"] == "r2"
    assert rows["WR"]["verdict"] == "keep"
    assert rows["FLEX"]["verdict"] == "problem"                  # starter on bye
    order = [r["verdict"] for r in O.start_sit(starters, roster, proj, 5, SLOTS)]
    assert order[0] == "problem"


def test_start_sit_skips_locked_starters():
    proj = {"q": P("QB", 20, weeks=(6,)), "q2": P("QB", 30)}
    assert O.start_sit(["q"], ["q", "q2"], proj, 5, ["QB"]) == []


def test_optimal_week_uses_bench_on_bye():
    proj = {"q": P("QB", 20, bye=(6,)), "q2": P("QB", 12), "r": P("RB", 10), "w": P("WR", 9), "w2": P("WR", 8)}
    ow = O.optimal_week(list(proj), proj, 6, SLOTS)
    assert {x["slot"]: x["id"] for x in ow["lineup"]}["QB"] == "q2"
    assert ow["byes"] == ["q"] and ow["total"] == 12 + 10 + 9 + 8


def test_simulate_clear_favourite_and_conditionals():
    standings = {1: {"wins": 3, "losses": 0, "pf": 360}, 2: {"wins": 0, "losses": 3, "pf": 240},
                 3: {"wins": 2, "losses": 1, "pf": 300}, 4: {"wins": 1, "losses": 2, "pf": 280}}
    sched = {5: [(1, 2), (3, 4)], 6: [(1, 3), (2, 4)]}
    means = {1: 130, 2: 80, 3: 110, 4: 100}
    dist = {(t, w): (means[t], 15) for t in means for w in (5, 6)}
    sim = O.simulate(standings, sched, dist, {t: 2 for t in means}, playoff_teams=2, n=4000, seed=1)
    odds = {t: sim["made"].get(t, 0) / sim["n"] for t in means}
    assert odds[1] > 0.95 and odds[2] < 0.05
    assert sum(odds.values()) == pytest.approx(2.0)
    assert sum(sim["avg_wins"].values()) == pytest.approx(6 + 4)   # 6 wins so far + 4 games left
    if_a, if_b = O.conditional_odds(sim, (5, 3, 4), 3)
    assert if_a > if_b                                              # team 3 better off winning
    keys = O.key_games(sim, 3)
    assert keys[0]["mine"] and all(k["swing"] >= 0 for k in keys)


def test_simulate_is_reproducible():
    standings = {1: {"wins": 1, "losses": 0, "pf": 100}, 2: {"wins": 0, "losses": 1, "pf": 90}}
    dist = {(t, 5): (100, 20) for t in (1, 2)}
    a = O.simulate(standings, {5: [(1, 2)]}, dist, {}, 1, n=500, seed=7)
    b = O.simulate(standings, {5: [(1, 2)]}, dist, {}, 1, n=500, seed=7)
    assert a["made"] == b["made"]


def test_tiebreak_is_points_for():
    standings = {1: {"wins": 1, "losses": 0, "pf": 200}, 2: {"wins": 1, "losses": 0, "pf": 100}}
    sim = O.simulate(standings, {}, {}, {}, 1, n=10, seed=0)
    assert sim["made"] == {1: 10}


@pytest.mark.parametrize("p,conf,text", [
    (0.573, "low", "55%"), (0.573, "high", "57%"), (0.004, "low", "<1%"), (0.995, "medium", ">99%"),
    (0.02, "low", "<5%"), (0.97, "low", "95%"), (0.98, "low", ">95%")])
def test_round_odds(p, conf, text):
    assert O.round_odds(p, conf) == text


def test_matchup_confidence():
    proj = {"a": P("QB", 20, conf="low"), "b": P("RB", 10, conf="medium")}
    assert O.matchup_confidence(["a", "b"], proj, 5) == "low"
    proj["a"]["confidence"] = "medium"
    assert O.matchup_confidence(["a", "b"], proj, 5) == "medium"
