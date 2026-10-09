from nfl_assistant import startsit

SLOTS = ["WR"]


def wk(pts, q, avail=1.0):
    return {"weekly": {5: {"pts": pts, "q": q, "avail": avail, "bye": False}}, "position": "WR", "sd": 5.0, "rate": pts}


def proj():
    # same projection (10), different shape: steady vs boom-or-bust
    return {"steady": wk(10.0, [8.0, 8.5, 10.0, 11.5, 12.0]), "boom": wk(10.0, [1.0, 2.0, 8.0, 20.0, 26.0])}


def test_underdog_starts_the_high_ceiling_player():
    p = startsit.plan(["steady"], ["steady", "boom"], proj(), 5, SLOTS, {}, opp_mean=18.0, opp_sd=2.0, n=4000)
    assert p["style"] == "underdog" and p["best_win"] > p["current_win"]
    assert p["changes"][0]["in"] == "boom" and p["changes"][0]["out"] == "steady"


def test_favourite_keeps_the_steady_player():
    p = startsit.plan(["boom"], ["steady", "boom"], proj(), 5, SLOTS, {}, opp_mean=4.0, opp_sd=1.0, n=4000)
    assert p["style"] == "favourite" and p["changes"][0]["in"] == "steady"


def test_no_change_when_lineup_is_already_best():
    p = startsit.plan(["steady"], ["steady", "boom"], proj(), 5, SLOTS, {}, opp_mean=4.0, opp_sd=1.0, n=4000)
    assert p["changes"] == [] and p["best_win"] == p["current_win"]


def test_draw_follows_the_quantiles():
    k = startsit._knots([2.0, 4.0, 10.0, 20.0, 25.0])
    assert startsit.draw(k, 0.5) == 10.0 and startsit.draw(k, 0.1) == 2.0 and startsit.draw(k, 0.9) == 25.0
    assert startsit.draw(k, 0.0) >= 0.0 and startsit.draw(k, 1.0) > 25.0
