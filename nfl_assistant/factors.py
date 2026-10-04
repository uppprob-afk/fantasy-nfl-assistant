"""Learned game-day factors: injury designations and weather / venue.

Both are estimated from nflverse history (last season + this season) and shrunk toward a
neutral starting value, so thin evidence changes little. Pure functions; run.py downloads
the injury reports and weather forecasts.

Injuries: for each official game-status report (Questionable / Doubtful / Out), what share
of the player's normal points did he actually produce that week (0 if he didn't play)? Split
by Friday practice participation, because "Questionable, full practice" and "Questionable,
did not practice" are very different.

Weather / venue: per position, how players score relative to their own season average in
domes, outdoors, high wind (15+ mph) and freezing (32F or below) games.
"""

from collections import defaultdict
from statistics import mean

# Starting values (also the fallback): expected share of normal points this week.
DEFAULT_AVAILABILITY = {"Questionable": 0.85, "Doubtful": 0.25, "Out": 0.0}
AVAIL_SHRINK = 25          # pseudo-games at the starting value
WEATHER_SHRINK = 150
WEATHER_CAP = (0.85, 1.15)
WINDY_MPH = 15
COLD_F = 32
MIN_GAMES_FOR_AVG = 4
STATUSES = ("Questionable", "Doubtful", "Out")
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")


def practice_bucket(text: str | None) -> str:
    t = (text or "").lower()
    if "did not participate" in t:
        return "dnp"
    if "limited" in t:
        return "limited"
    if "full" in t:
        return "full"
    return ""


def _season_means(logs: dict[str, list[dict]]) -> dict[tuple, tuple[float, int]]:
    """(player key, season) -> (mean points over full games, number of games)."""
    acc = defaultdict(list)
    for key, games in logs.items():
        for g in games:
            if not g.get("partial"):
                acc[(key, g["season"])].append(g["pts"])
    return {k: (mean(v), len(v)) for k, v in acc.items()}


def learn_availability(reports: list[dict], logs: dict[str, list[dict]]) -> dict:
    """Learned availability table: "<status>|<practice>" and "<status>" -> share of normal points,
    plus the evidence behind each (games, played share)."""
    means = _season_means(logs)
    by_week = {(key, g["season"], g["week"]): g for key, games in logs.items() for g in games}
    acc = defaultdict(lambda: [0.0, 0.0, 0, 0])     # actual, expected, games, played
    for r in reports:
        status = r.get("report_status")
        if status not in STATUSES or r.get("game_type", "REG") != "REG" or r.get("position") not in POSITIONS:
            continue
        key, season, week = r.get("gsis_id"), str(r.get("season")), int(r.get("week") or 0)
        m = means.get((key, season))
        if not m or m[1] < MIN_GAMES_FOR_AVG or m[0] < 3:
            continue                                  # need a normal level to compare against
        g = by_week.get((key, season, week))
        # leave this week out of his normal level
        normal = (m[0] * m[1] - (g["pts"] if g and not g.get("partial") else 0)) / (m[1] - (1 if g and not g.get("partial") else 0))
        actual = g["pts"] if g else 0.0
        for k in (status, f"{status}|{practice_bucket(r.get('practice_status'))}"):
            a = acc[k]
            a[0] += actual; a[1] += normal; a[2] += 1; a[3] += bool(g)
    out = {}
    for k, (act, exp, n, played) in acc.items():
        start = DEFAULT_AVAILABILITY[k.split("|")[0]]
        ratio = act / exp if exp else start
        out[k] = {"share": round(max(0.0, min(1.1, (n * ratio + AVAIL_SHRINK * start) / (n + AVAIL_SHRINK))), 3),
                  "games": n, "played": round(played / n, 3) if n else None}
    for k, v in DEFAULT_AVAILABILITY.items():
        out.setdefault(k, {"share": v, "games": 0, "played": None})
    return out


def current_practice(reports: list[dict], season: str, week: int) -> dict[str, dict]:
    """gsis id -> {"status", "practice"} from this week's official report (if published)."""
    out = {}
    for r in reports:
        if str(r.get("season")) == str(season) and int(r.get("week") or 0) == week and r.get("gsis_id"):
            out[r["gsis_id"]] = {"status": r.get("report_status") or None,
                                 "practice": practice_bucket(r.get("practice_status"))}
    return out


def condition(game: dict | None) -> str | None:
    """Venue / weather bucket for a game: dome, wind, cold, outdoor (None = unknown)."""
    if not game:
        return None
    roof = game.get("roof") or ""
    if roof in ("dome", "closed"):
        return "dome"
    if roof in ("outdoors", "open"):
        wind, temp = game.get("wind"), game.get("temp")
        if wind is not None and wind >= WINDY_MPH:
            return "wind"
        if temp is not None and temp <= COLD_F:
            return "cold"
        return "outdoor"
    return None


def learn_weather(logs: dict[str, list[dict]], scheds: dict[str, dict]) -> dict:
    """Per position: factor for dome, outdoor, wind and cold games vs the player's own season
    average. wind / cold are relative to outdoor games. scheds = season -> schedule()."""
    means = _season_means(logs)
    ratios = defaultdict(lambda: defaultdict(list))
    for key, games in logs.items():
        for g in games:
            pos = g.get("position")
            m = means.get((key, g["season"]))
            if pos not in POSITIONS or g.get("partial") or not m or m[1] < MIN_GAMES_FOR_AVG or m[0] < 3:
                continue
            game = (scheds.get(g["season"]) or {}).get(g["week"], {}).get(g.get("team"))
            c = condition(game)
            if c:
                r = g["pts"] / m[0]
                ratios[pos][c].append(r)
                ratios[pos]["all"].append(r)
                if c != "dome":
                    ratios[pos]["outdoor_all"].append(r)

    def shrunk(vals: list[float], ref: float) -> tuple[float, int]:
        if not vals or not ref:
            return 1.0, len(vals)
        f = mean(vals) / ref
        n = len(vals)
        return round(max(WEATHER_CAP[0], min(WEATHER_CAP[1], (n * f + WEATHER_SHRINK) / (n + WEATHER_SHRINK))), 3), n

    out = {}
    for pos in POSITIONS:
        r = ratios.get(pos, {})
        overall = mean(r["all"]) if r.get("all") else 1.0
        outdoor = mean(r["outdoor_all"]) if r.get("outdoor_all") else overall
        calm = r.get("outdoor", [])
        calm_avg = mean(calm) if calm else outdoor
        d, nd = shrunk(r.get("dome", []), overall)
        o, no = shrunk(r.get("outdoor_all", []), overall)
        w, nw = shrunk(r.get("wind", []), calm_avg)
        c, nc = shrunk(r.get("cold", []), calm_avg)
        out[pos] = {"dome": d, "outdoor": o, "wind": w, "cold": c,
                    "games": {"dome": nd, "outdoor": no, "wind": nw, "cold": nc}}
    return out


def weather_multiplier(position: str, game: dict | None, factors: dict | None, strength: float) -> float:
    """Multiplier for one game from the learned factors, scaled by `strength` (0 = ignore)."""
    if not factors or not strength or position not in factors:
        return 1.0
    f = factors[position]
    c = condition(game)
    if c is None:
        return 1.0
    m = f["dome"] if c == "dome" else f["outdoor"] * (f["wind"] if c == "wind" else f["cold"] if c == "cold" else 1.0)
    return 1 + strength * (m - 1)


# --- weather forecasts (Open-Meteo, free, no key) ------------------------------------------
# Home stadium coordinates by Sleeper team code (neutral-site games are skipped).
STADIUMS = {
    "ARI": (33.528, -112.263), "ATL": (33.755, -84.401), "BAL": (39.278, -76.623), "BUF": (42.774, -78.787),
    "CAR": (35.226, -80.853), "CHI": (41.862, -87.617), "CIN": (39.096, -84.516), "CLE": (41.506, -81.700),
    "DAL": (32.747, -97.095), "DEN": (39.744, -105.020), "DET": (42.340, -83.046), "GB": (44.501, -88.062),
    "HOU": (29.685, -95.411), "IND": (39.760, -86.164), "JAX": (30.324, -81.637), "KC": (39.049, -94.484),
    "LV": (36.091, -115.183), "LAC": (33.954, -118.339), "LAR": (33.954, -118.339), "MIA": (25.958, -80.239),
    "MIN": (44.974, -93.258), "NE": (42.091, -71.264), "NO": (29.951, -90.081), "NYG": (40.814, -74.075),
    "NYJ": (40.814, -74.075), "PHI": (39.901, -75.168), "PIT": (40.447, -80.016), "SF": (37.403, -121.970),
    "SEA": (47.595, -122.332), "TB": (27.976, -82.503), "TEN": (36.167, -86.771), "WAS": (38.908, -76.865),
}
FORECAST_URL = ("https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}"
                "&hourly=wind_speed_10m,temperature_2m,precipitation&wind_speed_unit=mph"
                "&temperature_unit=fahrenheit&timezone=America%2FNew_York&forecast_days=8")


def games_needing_forecast(sched: dict, today: str, days: int = 7) -> list[tuple[int, str, str, str]]:
    """(week, home team, game date, kickoff hour ET) for unplayed outdoor home games within `days`."""
    from datetime import date
    t0 = date.fromisoformat(today)
    out = []
    for w, teams in sched.items():
        for team, g in teams.items():
            if not g.get("home") or g.get("played") or g.get("neutral") or team not in STADIUMS:
                continue
            if (g.get("roof") or "") not in ("outdoors", "open") or not g.get("gameday"):
                continue
            ahead = (date.fromisoformat(g["gameday"]) - t0).days
            if 0 <= ahead <= days:
                out.append((w, team, g["gameday"], (g.get("gametime") or "13:00")[:2]))
    return out


def forecast_at(payload: dict, day: str, hour: str) -> dict | None:
    """Wind (mph), temperature (F) and precipitation (mm) at kickoff from an Open-Meteo response."""
    h = payload.get("hourly") or {}
    key = f"{day}T{hour}:00"
    if key not in (h.get("time") or []):
        return None
    i = h["time"].index(key)
    return {"wind": h["wind_speed_10m"][i], "temp": h["temperature_2m"][i], "precip": h["precipitation"][i]}
