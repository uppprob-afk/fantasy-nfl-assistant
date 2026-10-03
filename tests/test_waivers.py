from nfl_assistant import faab, waivers


def P(pos, ros, status=None):
    return {"position": pos, "ros": ros, "status": status}


def test_pool_takes_best_available_per_position_and_skips_long_term_out():
    proj = {"a": P("RB", 100), "b": P("RB", 120), "c": P("RB", 150, "IR"), "d": P("RB", 200), "e": P("WR", 90),
            "f": P("RB", 0)}
    out = waivers.pool(proj, rostered={"d"}, sizes={"RB": 2, "WR": 1})
    assert out == ["b", "a", "e"]


class StubValuer:
    """Team value = sum of ros, capped at 3 players (drops the lowest)."""
    def __init__(self, proj):
        self.proj = proj

    def value(self, pids):
        keep = sorted(pids, key=lambda p: -self.proj[p]["ros"])
        return {"score": sum(self.proj[p]["ros"] for p in keep[:3]), "dropped": keep[3:]}


def test_my_gain_cuts_weakest_and_swaps_kickers():
    proj = {"m1": P("RB", 100), "m2": P("WR", 80), "k1": P("K", 50), "fa": P("RB", 90), "k2": P("K", 70)}
    v = StubValuer(proj)
    g = waivers.my_gain(v, ["m1", "m2", "k1"], "fa", proj, n_weeks=10)
    assert g["gain"] == 40 and g["drop"] == ["k1"] and g["per_week"] == 4.0 and g["fit"] == "upgrade"
    k = waivers.my_gain(v, ["m1", "m2", "k1"], "k2", proj, n_weeks=10)
    assert k["gain"] == 20 and k["drop"] == ["k1"] and k["fit"] == "upgrade"


def test_fit_and_demand():
    assert [waivers.fit(x) for x in (2.0, 1.0, 0.2)] == ["upgrade", "depth", "none"]
    assert [waivers.demand(n) for n in (0, 1, 3)] == ["quiet", "warm", "hot"]


def test_bid_suggestion_level_override_and_context():
    market = {"RB": {"claims": 8, "bids_placed": 20, "bargain_bid": 2, "competitive_bid": 6, "safe_bid": 12}}
    s = faab.bid_suggestion("RB", market, remaining=50, demand="hot", level="bargain_bid", context="Useful depth")
    assert s["bid"] == 2 and s["level"] == "bargain_bid" and s["reason"].startswith("Useful depth: $2 would have won")
