"""Team defence projections, led by how many points the opponent is expected to score.

Defence scores are mostly luck (turnovers, return touchdowns), so the only signal that held up
when tested on games it hadn't seen was the opponent's expected points: Vegas' implied team
total when a line is posted, otherwise an estimate from both teams' scoring this season. A
defence's own sacks / takeaways / past fantasy points added noise, not accuracy (tested on
2025 -> 2026), so they aren't used.

    expected allowed  -> expected points-allowed tier score (league scoring, a spread of
                         outcomes around the expected total)
    projection        =  a + b x that tier score

a and b are fitted each run on every played game with a Vegas line (last season and this
one); `a` carries the average sacks / turnovers / touchdowns. Pure functions, no network.
"""

import math
from collections import defaultdict

PA_SD = 8.0               # points: spread of a team's actual score around its implied total
PRIOR_WEIGHT = 0.5        # last season's games count half in the no-line estimate
STRENGTH_GAMES = 10       # pseudo-games of league-average scoring in that estimate
HOME_EDGE = 1.0           # points: a home offence scores about this much more than its average
MIN_FIT_GAMES = 100       # played games with a line before a and b are fitted (else defaults)
TIERS = ((0, "pts_allow_0"), (6, "pts_allow_1_6"), (13, "pts_allow_7_13"), (20, "pts_allow_14_20"),
         (27, "pts_allow_21_27"), (34, "pts_allow_28_34"))


def tier_points(allowed: int, scoring: dict) -> float:
    return next((scoring.get(k, 0) for lim, k in TIERS if allowed <= lim), scoring.get("pts_allow_35p", 0))


def expected_tier(allowed: float, scoring: dict, sd: float = PA_SD) -> float:
    """Average points-allowed score if the opponent scores around `allowed` (normal spread,
    whole points from 0 to 69)."""
    ws = [math.exp(-0.5 * ((a - allowed) / sd) ** 2) for a in range(70)]
    return sum(w * tier_points(a, scoring) for a, w in zip(range(70), ws)) / sum(ws)


def results(games: list[dict], seasons: tuple[str, ...]) -> list[dict]:
    """Played regular-season games as one row per team: points scored / allowed and the
    opponent's Vegas implied total (None without a line)."""
    from .projections import sleeper_team
    out = []
    for g in games:
        if g.get("season") not in seasons or g.get("game_type") != "REG" or (g.get("home_score") or "") == "":
            continue
        spread, total = g.get("spread_line"), g.get("total_line")
        imp_h = imp_a = None
        if spread not in (None, "") and total not in (None, ""):
            s, t = float(spread), float(total)
            imp_h, imp_a = (t + s) / 2, (t - s) / 2
        home, away = sleeper_team(g["home_team"]), sleeper_team(g["away_team"])
        hs, as_ = int(g["home_score"]), int(g["away_score"])
        week = int(g["week"])
        out.append({"season": g["season"], "week": week, "team": home, "opp": away, "home": True,
                    "scored": hs, "allowed": as_, "opp_implied": imp_a})
        out.append({"season": g["season"], "week": week, "team": away, "opp": home, "home": False,
                    "scored": as_, "allowed": hs, "opp_implied": imp_h})
    return out


def _before(rows: list[dict], season: str, week: int | None) -> list[dict]:
    """Rows from earlier seasons, and this season before `week` (None = all of it)."""
    return [r for r in rows if r["season"] < season or (r["season"] == season and (week is None or r["week"] < week))]


def strength(rows: list[dict], season: str, week: int | None = None) -> dict:
    """{avg, off: team -> points scored per game, def: team -> points allowed per game},
    shrunk toward the league average; last season's games count half."""
    rows = [r for r in _before(rows, season, week) if r["season"] >= str(int(season) - 1)]
    if not rows:
        return {"avg": None, "off": {}, "def": {}}
    avg = sum(r["scored"] for r in rows) / len(rows)
    tot = defaultdict(lambda: [0.0, 0.0, 0.0])          # team -> [weight, scored, allowed]
    for r in rows:
        w = 1.0 if r["season"] == season else PRIOR_WEIGHT
        t = tot[r["team"]]
        t[0] += w
        t[1] += w * r["scored"]
        t[2] += w * r["allowed"]
    k = STRENGTH_GAMES
    return {"avg": avg, "off": {t: (v[1] + k * avg) / (v[0] + k) for t, v in tot.items()},
            "def": {t: (v[2] + k * avg) / (v[0] + k) for t, v in tot.items()}}


def estimate_allowed(team: str, opp: str, home: bool, st: dict) -> float | None:
    """Points `opp` should score against `team` without a Vegas line: their scoring plus how
    much `team` usually allows, relative to the league average, and home field."""
    avg = st.get("avg")
    if avg is None:
        return None
    return st["off"].get(opp, avg) + st["def"].get(team, avg) - avg + (-HOME_EDGE if home else HOME_EDGE)


def expected_allowed(team: str, game: dict, st: dict) -> tuple[float | None, str]:
    """(expected points allowed, "vegas" | "estimate")."""
    if game.get("opp_implied") is not None:
        return game["opp_implied"], "vegas"
    return estimate_allowed(team, game["opp"], bool(game.get("home")), st), "estimate"


def fit(dlogs: dict[str, list[dict]], rows: list[dict], scoring: dict, season: str,
        week: int | None = None) -> dict:
    """a, b in `points = a + b x expected tier score`, least squares over played games with a
    Vegas line (last season and this season before `week`)."""
    pts = {(g["season"], g["week"], team): g["pts"] for team, logs in dlogs.items() for g in logs}
    xs, ys = [], []
    for r in _before(rows, season, week):
        if r["opp_implied"] is None or r["season"] < str(int(season) - 1):
            continue
        y = pts.get((r["season"], r["week"], r["team"]))
        if y is not None:
            xs.append(expected_tier(r["opp_implied"], scoring))
            ys.append(y)
    if len(xs) < MIN_FIT_GAMES:
        return {"a": 5.5, "b": 1.0, "games": len(xs)}
    n, mx, my = len(xs), sum(xs) / len(xs), sum(ys) / len(ys)
    vx = sum((x - mx) ** 2 for x in xs)
    b = sum((x - mx) * (y - my) for x, y in zip(xs, ys)) / vx if vx else 1.0
    return {"a": round(my - b * mx, 3), "b": round(b, 3), "games": n}


def points(allowed: float | None, scoring: dict, f: dict) -> float | None:
    """Projected defence points for a game where the opponent should score `allowed`."""
    if allowed is None:
        return None
    return max(0.0, f["a"] + f["b"] * expected_tier(allowed, scoring))
