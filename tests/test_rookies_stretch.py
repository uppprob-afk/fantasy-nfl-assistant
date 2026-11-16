from nfl_assistant import model
from nfl_assistant import projections as pj

COMP = {"position": "WR", "n_this": 0, "n_prior": 0, "team_changed": False, "baseline": 10.0,
        "r_prior": 0.0, "cv": 0.5, "actual": None, "expected": None, "rank_baseline": None}


def test_rookie_scale_lowers_only_the_generic_starting_point():
    plain = pj.rate_from(COMP)["rate"]
    low = pj.rate_from(COMP, {"rookie_scale": 0.5})["rate"]
    assert low == round(plain * 0.5, 2)
    veteran = {**COMP, "n_prior": 10, "r_prior": 10.0}
    assert pj.rate_from(veteran, {"rookie_scale": 0.5})["rate"] == pj.rate_from(veteran)["rate"]
    # Sleeper's ranking still counts in full for a highly ranked rookie
    ranked = {**COMP, "rank_baseline": 16.0}
    r = pj.rate_from(ranked, {"rookie_scale": 0.5, "rank_prior": 0.5})["rate"]
    assert r == round(0.5 * 5.0 + 0.5 * 16.0, 2)


def test_stretch_pivots_on_the_position_average():
    P = {"center": {"WR": 8.0}, "stretch": 0.5}
    vet = {**COMP, "n_prior": 1000, "r_prior": 12.0}          # rate ~12 (prior dominates)
    base = pj.rate_from(vet, {"center": {"WR": 8.0}})["rate"]
    squeezed = pj.rate_from(vet, P)["rate"]
    assert abs(squeezed - (8.0 + 0.5 * (base - 8.0))) < 0.02
    assert pj.rate_from(vet, {**P, "stretch": 0.0})["rate"] == 8.0
    assert pj.rate_from(vet, {"stretch": 0.5})["rate"] == pj.rate_from(vet)["rate"]   # no centre learned: unchanged


def test_centers_are_average_projections_per_position():
    recs = [{"pos": "WR", "comp": {**COMP, "n_prior": 1000, "r_prior": v}} for v in (6.0, 10.0)]
    c = model.centers(recs, None)
    assert abs(c["WR"] - 8.0) < 0.05
