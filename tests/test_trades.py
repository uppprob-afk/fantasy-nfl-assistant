import pytest

from nfl_assistant import trades

SLOTS = ["QB", "RB", "WR", "WR", "TE", "FLEX"]
WEEKS = [5, 6, 7]


def P(pos, rate, status=None, byes=(), conf="medium", games_this=3):
    weekly = {w: {"pts": 0.0 if w in byes else float(rate), "bye": w in byes} for w in WEEKS}
    return {"position": pos, "rate": rate, "status": status, "weekly": weekly, "byes": list(byes),
            "ros": sum(x["pts"] for x in weekly.values()), "confidence": conf,
            "games_this": games_this, "games_prior": 10}


@pytest.fixture
def league():
    """Team 1 (me): stacked at WR, weak RB. Team 2: stacked at RB, weak WR. Team 3: average."""
    proj = {
        "q1": P("QB", 20), "r1": P("RB", 8), "r1b": P("RB", 6),
        "w1": P("WR", 20), "w1b": P("WR", 18), "w1c": P("WR", 16), "t1": P("TE", 10),
        "q2": P("QB", 18), "r2": P("RB", 20), "r2b": P("RB", 18), "r2c": P("RB", 15),
        "w2": P("WR", 9), "w2b": P("WR", 7), "t2": P("TE", 9),
        "q3": P("QB", 19), "r3": P("RB", 12), "r3b": P("RB", 10), "w3": P("WR", 12),
        "w3b": P("WR", 11), "t3": P("TE", 9), "w3x": P("WR", 25, status="IR"),
    }
    rosters = [
        {"roster_id": 1, "players": ["q1", "r1", "r1b", "w1", "w1b", "w1c", "t1"]},
        {"roster_id": 2, "players": ["q2", "r2", "r2b", "r2c", "w2", "w2b", "t2"]},
        {"roster_id": 3, "players": ["q3", "r3", "r3b", "w3", "w3b", "t3", "w3x"]},
    ]
    valuer = trades.Valuer(proj, WEEKS, SLOTS)
    return {"proj": proj, "rosters": rosters, "valuer": valuer,
            "profiles": trades.league_profiles(rosters, valuer)}


def test_value_is_lineup_minus_injury_cover_cost(league):
    v = league["valuer"].value(league["rosters"][0]["players"])
    per_week = 20 + 8 + 20 + 18 + 10 + 16
    assert v["lineup_total"] == per_week * 3
    # each starter may miss (7%); cost = drop to best eligible bench (no repl set here)
    #   QB 20 -> nothing (0); RB 8 -> r1b 6; WR 20/18 -> nothing at WR on bench... w1c starts at FLEX
    #   TE 10 -> nothing; FLEX 16 -> r1b 6
    loss = trades.ABSENCE_RATE * ((20 - 0) + (8 - 6) + (20 - 0) + (18 - 0) + (10 - 0) + (16 - 6))
    assert v["score"] == round(3 * (per_week - loss), 1)
    assert v["dropped"] == []


def test_replacement_floor_and_cover():
    proj = {"q": P("QB", 12), "r": P("RB", 9), "w": P("WR", 15), "w2": P("WR", 7), "t": P("TE", 6),
            "f": P("RB", 4)}
    v = trades.Valuer(proj, WEEKS, SLOTS, repl={"QB": 16.0, "RB": 10.0, "WR": 8.0, "TE": 7.0})
    out = v.value(list(proj))
    # QB 12 < 16, RB 9 < 10, TE 6 < 7, WR2 7 < 8 -> floored; FLEX floor = max(RB, WR, TE) = 10
    # only WR 15 is above its floor: cost of absence = 7% x (15 - max(8, bench WR none -> floor 8))
    week = 16 + 10 + (15 - trades.ABSENCE_RATE * (15 - 8)) + 8 + 7 + 10
    assert out["score"] == round(3 * week, 1)


def test_bench_player_below_replacement_adds_nothing():
    base = {"q": P("QB", 20), "r": P("RB", 12), "w": P("WR", 15), "w2": P("WR", 12), "t": P("TE", 9),
            "f": P("WR", 11)}
    repl = {"QB": 15.0, "RB": 9.0, "WR": 9.0, "TE": 7.0}
    v = trades.Valuer(dict(base, scrub=P("RB", 4)), WEEKS, SLOTS, repl=repl)
    assert v.value(list(base))["score"] == v.value(list(base) + ["scrub"])["score"]


def test_roster_limit_cuts_least_valuable():
    proj = {"q": P("QB", 20), "r": P("RB", 12), "w": P("WR", 15), "w2": P("WR", 12), "t": P("TE", 9),
            "f": P("WR", 11), "low": P("RB", 3)}
    v = trades.Valuer(proj, WEEKS, SLOTS, roster_size=6, repl={"RB": 5.0})
    out = v.value(list(proj))
    assert out["dropped"] == ["low"] and "low" not in out["pids"]
    assert out["score"] == v.value([p for p in proj if p != "low"])["score"]


def test_reserve_players_do_not_count_toward_roster_limit():
    proj = {"q": P("QB", 20), "r": P("RB", 12), "hurt": P("RB", 15, status="IR")}
    v = trades.Valuer(proj, WEEKS, SLOTS, roster_size=2, reserve={"hurt"})
    assert v.value(list(proj))["dropped"] == []


def test_bye_week_is_covered_by_bench(league):
    proj = dict(league["proj"])
    proj["w1"] = P("WR", 20, byes=(6,))
    valuer = trades.Valuer(proj, WEEKS, SLOTS)
    weekly = valuer.lineups(league["rosters"][0]["players"])
    assert "w1" not in [p for _, p in weekly[6][1]]
    assert weekly[6][0] == weekly[5][0] - 20 + 6                  # r1b steps into FLEX


def test_league_profiles_find_needs_and_surplus(league):
    prof = league["profiles"]
    assert "RB" in prof[1]["needs"] and "WR" in prof[2]["needs"]
    assert prof[1]["vs_median"]["WR"] > 0 and prof[2]["vs_median"]["RB"] > 0
    assert "RB" in prof[2]["surplus"]
    assert prof[3]["depth"]["WR"] == 0                            # IR player is worth 0 now


def test_find_trades_mutual_benefit(league):
    ideas = trades.find_trades(1, league["rosters"], league["proj"], league["valuer"], league["profiles"])
    assert ideas
    top = ideas[0]
    assert top["roster_id"] == 2
    assert {league["proj"][p]["position"] for p in top["give"]} == {"WR"}
    assert "RB" in {league["proj"][p]["position"] for p in top["get"]}
    for t in ideas:
        assert t["my_gain"] >= 5 and t["their_gain"] > 0
        assert "w3x" not in t["get"]


def test_find_trades_dedupes_players_per_partner(league):
    ideas = trades.find_trades(1, league["rosters"], league["proj"], league["valuer"], league["profiles"],
                               max_per_team=5)
    for rid in {t["roster_id"] for t in ideas}:
        got = [p for t in ideas if t["roster_id"] == rid for p in t["get"]]
        assert len(got) == len(set(got))


def test_tradeable_rules(league):
    proj = league["proj"]
    assert trades.tradeable("w1", proj)
    assert not trades.tradeable("w3x", proj)                      # IR
    proj["k"] = dict(P("K", 9))
    assert not trades.tradeable("k", proj)
    proj["rook"] = dict(P("WR", 9), games_this=0, games_prior=0)
    assert not trades.tradeable("rook", proj)


def test_lopsided_trades_rank_last():
    ideas = [{"my_gain": 30.0, "their_gain": 2.0}, {"my_gain": 10.0, "their_gain": 9.0}]
    ideas.sort(key=lambda t: (trades._lopsided(t), -t["my_gain"]))
    assert ideas[0]["my_gain"] == 10.0


def test_explain_reasons_balance_and_confidence(league):
    t = {"roster_id": 2, "give": ["w1c"], "get": ["r2c"], "my_gain": 20.0, "their_gain": 15.0}
    names = {p: p for p in league["proj"]}
    league["proj"]["r2c"]["confidence"] = "low"
    out = trades.explain(t, league["proj"], league["profiles"], 1, names, "R1", 3)
    assert out["balance"] == "balanced" and out["confidence"] == "low"
    text = " ".join(out["reasons"])
    assert "Your RB starters project" in text and "R1's WR starters project" in text
    assert "you +20 pts (~6.7/wk), R1 +15 pts" in text
    out2 = trades.explain({**t, "their_gain": 3.0}, league["proj"], league["profiles"], 1, names, "R1", 3)
    assert out2["balance"] == "lopsided (tough sell)"


def test_pitches_for_buyers(league):
    league["rosters"][0]["players"].append("w9")
    league["proj"]["w9"] = P("WR", 9)
    valuer = trades.Valuer(league["proj"], WEEKS, SLOTS)
    prof = trades.league_profiles(league["rosters"], valuer)
    buyers = [{"roster_id": 3, "manager": "X", "position": "WR", "player": "w3x", "status": "IR"}]
    out = trades.pitches_for_buyers(buyers, 1, league["rosters"], league["proj"], prof)
    assert out[0]["my_options"] == ["w9"]


def test_season_strength_actual_and_efficiency():
    slots = ["QB", "RB", "WR", "FLEX"]
    position = {"q": "QB", "r": "RB", "r2": "RB", "w": "WR", "w2": "WR"}
    mb = {1: [{"roster_id": 1, "starters": ["q", "r", "w", "w2"], "starters_points": [20, 10, 15, 5],
               "players_points": {"q": 20, "r": 10, "r2": 12, "w": 15, "w2": 5}},
              {"roster_id": 2, "starters": ["q", "r", "w", "w2"], "starters_points": [10, 10, 10, 10],
               "players_points": {"q": 10, "r": 10, "w": 10, "w2": 10}}],
          2: [{"roster_id": 1, "starters": ["q", "r", "w", "r2"], "starters_points": [20, 10, 15, 12],
               "players_points": {"q": 20, "r": 10, "r2": 12, "w": 15, "w2": 5}},
              {"roster_id": 2, "starters": ["q", "r", "w", "w2"], "starters_points": [10, 10, 10, 10],
               "players_points": {"q": 10, "r": 10, "w": 10, "w2": 10}}]}
    s = trades.season_strength(mb, [1, 2], slots, position)
    me = s[1]
    assert me["weeks"] == 2 and me["per_week"]["QB"] == 20 and me["per_week"]["FLEX"] == 8.5
    assert me["actual"] == 53.5 and me["optimal"] == 57.0            # week 1 benched r2 (12) for w2 (5)
    assert me["efficiency"] == round(107 / 114, 3)
    assert s[2]["efficiency"] == 1.0
    assert me["vs_median"]["QB"] == 5.0 and s[2]["vs_median"]["QB"] == -5.0   # median of two = midpoint


def test_trades_made_counts_completed_trades():
    txs = [{"type": "trade", "status": "complete", "roster_ids": [1, 2]},
           {"type": "trade", "status": "failed", "roster_ids": [1, 3]},
           {"type": "waiver", "status": "complete", "roster_ids": [1]}]
    assert trades.trades_made(txs) == {1: 1, 2: 1}
