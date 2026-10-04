from nfl_assistant import factors
from nfl_assistant import projections as pj


def g(season, week, pts, team="KC", pos="WR", partial=False):
    return {"season": season, "week": week, "pts": pts, "team": team, "position": pos, "partial": partial}


def test_practice_bucket():
    assert factors.practice_bucket("Did Not Participate In Practice") == "dnp"
    assert factors.practice_bucket("Limited Participation in Practice") == "limited"
    assert factors.practice_bucket("Full Participation in Practice") == "full"
    assert factors.practice_bucket(None) == ""


def test_learn_availability_counts_sitting_as_zero_and_shrinks():
    # normal level 10 (weeks 1-4); questionable in week 5 (played, 6 pts) and week 6 (sat)
    logs = {"p1": [g("2025", w, 10.0) for w in range(1, 5)] + [g("2025", 5, 6.0)]}
    reports = [{"season": "2025", "week": 5, "gsis_id": "p1", "position": "WR", "report_status": "Questionable",
                "practice_status": "Limited Participation in Practice", "game_type": "REG"},
               {"season": "2025", "week": 6, "gsis_id": "p1", "position": "WR", "report_status": "Questionable",
                "practice_status": "Did Not Participate In Practice", "game_type": "REG"}]
    t = factors.learn_availability(reports, logs)
    q = t["Questionable"]
    assert q["games"] == 2 and q["played"] == 0.5
    # raw share = 6 / (10 + 9.2) ~ 0.31, shrunk toward 0.85 with 25 pseudo-cases
    assert 0.75 < q["share"] < 0.85
    assert t["Questionable|limited"]["games"] == 1 and t["Doubtful"]["games"] == 0


def test_availability_uses_learned_table_for_this_week_only():
    table = {"Questionable": {"share": 0.6, "games": 200}, "Questionable|full": {"share": 0.8, "games": 30},
             "Questionable|dnp": {"share": 0.3, "games": 5}}
    assert pj.availability("Questionable", 0, "full", table) == 0.8
    assert pj.availability("Questionable", 0, "dnp", table) == 0.6       # too few cases: falls back
    assert pj.availability("Questionable", 1, "full", table) == 1.0      # later weeks unchanged
    assert pj.availability("Questionable", 0) == 0.85                    # no table: starting value


def test_condition_buckets():
    assert factors.condition({"roof": "dome"}) == "dome"
    assert factors.condition({"roof": "outdoors", "wind": 20, "temp": 50}) == "wind"
    assert factors.condition({"roof": "outdoors", "wind": 5, "temp": 20}) == "cold"
    assert factors.condition({"roof": "open", "wind": None, "temp": None}) == "outdoor"
    assert factors.condition({"roof": None}) is None and factors.condition(None) is None


def test_weather_multiplier_scales_with_strength():
    f = {"WR": {"dome": 1.05, "outdoor": 0.98, "wind": 0.9, "cold": 1.0}}
    windy = {"roof": "outdoors", "wind": 20}
    assert factors.weather_multiplier("WR", windy, f, 0.0) == 1.0
    assert abs(factors.weather_multiplier("WR", windy, f, 1.0) - 0.98 * 0.9) < 1e-9
    assert abs(factors.weather_multiplier("WR", {"roof": "dome"}, f, 0.5) - 1.025) < 1e-9


def test_learn_weather_finds_wind_effect():
    logs = {}
    sched = {"2025": {}}
    for i in range(40):
        team = f"T{i}"
        games = []
        for w in range(1, 9):
            windy = w <= 4
            sched["2025"].setdefault(w, {})[team] = {"roof": "outdoors", "wind": 20 if windy else 3, "temp": 60}
            games.append(g("2025", w, 7.0 if windy else 13.0, team))
        logs[team] = games
    out = factors.learn_weather(logs, sched)["WR"]
    assert out["wind"] < 0.9 and out["games"]["wind"] == 160


def test_forecast_parsing_and_game_selection():
    payload = {"hourly": {"time": ["2026-10-11T13:00", "2026-10-11T16:00"], "wind_speed_10m": [12.0, 18.5],
                          "temperature_2m": [55.0, 50.0], "precipitation": [0.0, 1.2]}}
    assert factors.forecast_at(payload, "2026-10-11", "16") == {"wind": 18.5, "temp": 50.0, "precip": 1.2}
    assert factors.forecast_at(payload, "2026-10-12", "13") is None
    sched = {6: {"KC": {"home": True, "played": False, "roof": "outdoors", "gameday": "2026-10-11", "gametime": "16:25", "opp": "BUF"},
                 "BUF": {"home": False, "played": False, "roof": "outdoors", "gameday": "2026-10-11", "opp": "KC"},
                 "DET": {"home": True, "played": False, "roof": "dome", "gameday": "2026-10-11", "opp": "GB"}},
             9: {"KC": {"home": True, "played": False, "roof": "outdoors", "gameday": "2026-11-01", "opp": "LV"}}}
    assert factors.games_needing_forecast(sched, "2026-10-06") == [(6, "KC", "2026-10-11", "16")]


def test_recency_weights_recent_games_more():
    c = pj.rate_components([g("2026", 1, 2.0), g("2026", 2, 2.0), g("2026", 3, 20.0)], "2026", "2025", "WR",
                           "KC", {"baseline": 10.0, "cv": 0.5}, {}, 1, as_of=4)
    flat = pj.rate_from(c)["rate"]
    recent = pj.rate_from(c, {"recency": 0.6})["rate"]
    assert recent > flat
