"""Shared projection engine: what each player should score per game from here on.

Used by trade values, matchup projections, optimal weekly lineups and playoff odds.
Pure functions, no network. Inputs are nflverse weekly stats (re-scored with the
league's own scoring), nflverse snap counts and the nflverse schedule (byes, Vegas lines).

The model, in plain English:
  rate = blend of a position baseline, last season's per-game points (weighted down,
         halved again for players who changed teams) and this season's per-game points
         (half actual, half "expected from usage" to even out touchdown luck).
         Games where a player barely played (snap share well below normal, e.g. hurt
         early) are left out.
  week = rate x matchup adjustment x availability; 0 on a bye.
Every projection carries a game-to-game spread (sd) and a confidence label.
"""

import math
from collections import defaultdict
from statistics import mean, median

from . import roles
from .factors import weather_multiplier
from .nflverse import compute_points, index_rows, match_player, norm_name

TEAM_FROM_NFLVERSE = {"LA": "LAR"}
# Per-game fields kept on each player's game log (cards / detail panel).
LOG_KEYS = ("week", "pts", "pct", "targets", "carries", "receptions", "attempts", "partial", "opp", "finish",
            "pass_yd", "pass_td", "ints", "rush_yd", "rush_td", "rec_yd", "rec_td", "fum",
            "tgt_share", "ay_share", "wopr", "car_share")
SKILL = ("QB", "RB", "WR", "TE")
POSITIONS = ("QB", "RB", "WR", "TE", "K", "DEF")

PRIOR_SEASON_WEIGHT = 0.5    # a game last season counts as half a game this season
PRIOR_SEASON_CAP = 17
TEAM_CHANGE_FACTOR = 0.5     # last season matters less after a team change
BASELINE_GAMES = 2           # pseudo-games at the position baseline
USAGE_BLEND = 0.5            # this season = 50% actual, 50% expected-from-usage
PARTIAL_SNAP_RATIO = 0.6     # < 60% of own normal snap share = partial game
VEGAS_DAMPING = 0.5
DVP_SHRINK_GAMES = 8
DVP_DAMPING = 0.5
OFFENSE_STATUS_OUT = {"IR", "PUP", "Sus", "NA", "DNR", "COV"}

# Tunable settings (model.tune adjusts them from the season's track record; these are the
# starting values). bias / sd_scale are per-position multipliers on the rate and spread.
DEFAULT_PARAMS = {
    "prior_weight": PRIOR_SEASON_WEIGHT, "usage_blend": USAGE_BLEND, "baseline_games": BASELINE_GAMES,
    "vegas_damping": VEGAS_DAMPING, "dvp_damping": DVP_DAMPING,
    "recency": 1.0,            # each week older a this-season game counts x this much (1 = all equal)
    "weather_strength": 0.0,   # how much of the learned venue/weather effects to apply (0-1)
    "availability": None,      # learned injury table (factors.learn_availability); None = fixed defaults
    "weather": None,           # learned venue/weather factors (factors.learn_weather)
    "role_blend": 0.0,         # weight on the role projection (team volume x share x efficiency)
    "partial_weight": 0.0,     # how much a partial game counts (scaled to a full game per snap)
    "rank_prior": 0.5,         # starting point for low-data players: share from Sleeper's player ranking
    "script_rb": 0.0,          # game script: RB points change per 7 pts of expected winning margin
    "script_pass": 0.0,        # ... and QB / WR / TE points (opposite direction)
    "qb_change": 0.0,          # how much of the learned backup-QB effect to apply
    "qb_factor": None,         # learned: teammates' points when the usual QB doesn't start
    "quantiles": None,         # learned floor / range / ceiling multipliers by position and level
    "by_pos": {},              # per-position overrides of any setting above
    "inherit": None,           # learned share of a missing teammate's work the next man gets
    "bias": {pos: 1.0 for pos in POSITIONS}, "sd_scale": {pos: 1.0 for pos in POSITIONS},
}


def pp(P: dict, key: str, position: str | None):
    """A setting for one position (per-position override if learned, else the global value)."""
    return ((P.get("by_pos") or {}).get(position) or {}).get(key, P[key])


def params_or_default(params: dict | None) -> dict:
    out = {**DEFAULT_PARAMS, **(params or {})}
    out["bias"] = {**DEFAULT_PARAMS["bias"], **((params or {}).get("bias") or {})}
    out["sd_scale"] = {**DEFAULT_PARAMS["sd_scale"], **((params or {}).get("sd_scale") or {})}
    return out


def sleeper_team(team: str | None) -> str | None:
    return TEAM_FROM_NFLVERSE.get(team, team) if team else team


def _n(row: dict, col: str) -> float:
    try:
        return float(row.get(col) or 0)
    except ValueError:
        return 0.0


# --- schedule ---------------------------------------------------------------
def schedule(games: list[dict], season: str) -> dict[int, dict[str, dict]]:
    """week -> team -> {opp, home, played, gameday, implied} for the regular season.

    implied = Vegas implied team total from spread_line (home margin) and total_line,
    when nflverse has lines for the game (usually only played games and the next week).
    """
    out: dict[int, dict[str, dict]] = defaultdict(dict)
    for g in games:
        if g.get("season") != str(season) or g.get("game_type") != "REG":
            continue
        week = int(g["week"])
        home, away = sleeper_team(g["home_team"]), sleeper_team(g["away_team"])
        played = (g.get("home_score") or "") != ""
        spread, total = g.get("spread_line"), g.get("total_line")
        imp_home = imp_away = None
        if spread not in (None, "") and total not in (None, ""):
            s, t = float(spread), float(total)
            imp_home, imp_away = (t + s) / 2, (t - s) / 2
        num = lambda k: float(g[k]) if g.get(k) not in (None, "") else None
        base = {"played": played, "gameday": g.get("gameday"), "gametime": g.get("gametime"),
                "roof": g.get("roof") or None, "wind": num("wind"), "temp": num("temp"),
                "neutral": g.get("location") == "Neutral", "stadium": g.get("stadium")}
        margin = float(spread) if spread not in (None, "") else None
        out[week][home] = {**base, "opp": away, "home": True, "implied": imp_home, "margin": margin,
                           "opp_implied": imp_away}
        out[week][away] = {**base, "opp": home, "home": False, "implied": imp_away,
                           "margin": -margin if margin is not None else None,
                           "opp_implied": imp_home}
    return dict(out)


# --- game logs --------------------------------------------------------------
def _snap_index(snaps: list[dict]) -> dict[tuple, float]:
    idx = {}
    for s in snaps:
        if s.get("game_type", "REG") != "REG":
            continue
        try:
            pct = float(s.get("offense_pct") or 0)
        except ValueError:
            continue
        idx[(s["season"], int(s["week"]), sleeper_team(s["team"]), norm_name(s["player"]))] = pct
    return idx


def component_points(row: dict, scoring: dict) -> dict[str, float]:
    """Split a stat line's points into passing / rushing / receiving parts (for usage rates)."""
    g = lambda k: scoring.get(k, 0)
    return {
        "pass": g("pass_yd") * _n(row, "passing_yards") + g("pass_td") * _n(row, "passing_tds")
                + g("pass_int") * _n(row, "passing_interceptions"),
        "rush": g("rush_yd") * _n(row, "rushing_yards") + g("rush_td") * _n(row, "rushing_tds"),
        "rec": g("rec") * _n(row, "receptions") + g("rec_yd") * _n(row, "receiving_yards")
               + g("rec_td") * _n(row, "receiving_tds"),
    }


def game_logs(rows: list[dict], snaps: list[dict], scoring: dict) -> dict[str, list[dict]]:
    """nflverse player_id -> list of games with points, snap share and usage."""
    snap_idx = _snap_index(snaps)
    team_carries: dict[tuple, float] = defaultdict(float)
    for r in rows:
        team_carries[(r["season"], r["week"], r.get("team"))] += _n(r, "carries")
    logs: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        if r.get("season_type", "REG") != "REG":
            continue
        team = sleeper_team(r.get("team"))
        name = norm_name(r.get("player_display_name") or r.get("player_name"))
        logs[r["player_id"]].append({
            "season": r["season"], "week": int(r["week"]), "team": team,
            "position": r.get("position"), "pts": compute_points(r, scoring),
            "pct": snap_idx.get((r["season"], int(r["week"]), team, name)),
            "targets": _n(r, "targets"), "carries": _n(r, "carries"), "receptions": _n(r, "receptions"),
            "attempts": _n(r, "attempts"), "parts": component_points(r, scoring),
            "opp": sleeper_team(r.get("opponent_team")),
            "pass_yd": _n(r, "passing_yards"), "pass_td": _n(r, "passing_tds"),
            "ints": _n(r, "passing_interceptions"),
            "rush_yd": _n(r, "rushing_yards"), "rush_td": _n(r, "rushing_tds"),
            "rec_yd": _n(r, "receiving_yards"), "rec_td": _n(r, "receiving_tds"),
            "fum": _n(r, "rushing_fumbles_lost") + _n(r, "receiving_fumbles_lost") + _n(r, "sack_fumbles_lost"),
            "tgt_share": round(_n(r, "target_share"), 3) or None, "ay_share": round(_n(r, "air_yards_share"), 3) or None,
            "wopr": round(_n(r, "wopr"), 3) or None,
            "car_share": (round(_n(r, "carries") / team_carries[(r["season"], r["week"], r.get("team"))], 3)
                          if team_carries[(r["season"], r["week"], r.get("team"))] else None),
        })
    for games in logs.values():
        games.sort(key=lambda x: (x["season"], x["week"]))
        mark_partial(games)
    return dict(logs)


def mark_partial(games: list[dict], injured: bool = False) -> None:
    """Flag games where the player barely played compared with their own normal.

    If the two most recent games are both low, treat it as a new (smaller) role
    rather than an injury and keep them, unless the player currently has an injury
    designation (then low games are most likely injury-limited).
    """
    pcts = [g["pct"] for g in games if g["pct"] is not None]
    for g in games:
        g["partial"] = False
    if len(pcts) < 3:
        return
    # judge against this season's normal once there are 3+ games (roles change year to year)
    latest = games[-1]["season"] if games else None
    this = [g["pct"] for g in games if g["season"] == latest and g["pct"] is not None]
    normal = median(this) if len(this) >= 3 else median(pcts)
    if normal < 0.3:
        return  # part-time player: snap share too noisy to judge
    low = [g["pct"] is not None and g["pct"] < PARTIAL_SNAP_RATIO * normal for g in games]
    role_change = len(games) >= 2 and low[-1] and low[-2] and not injured
    for g, is_low in zip(games, low):
        g["partial"] = is_low and not (role_change and g in games[-2:])


def def_logs(rows: list[dict], games: list[dict], scoring: dict) -> dict[str, list[dict]]:
    """Team defence fantasy points per game, built from defensive player stats + final scores.

    Checked against Sleeper's DEF points for 2026 weeks 1-3: exact for most team-weeks.
    """
    agg: dict[tuple, dict] = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if r.get("season_type", "REG") != "REG":
            continue
        a = agg[(r["season"], int(r["week"]), sleeper_team(r["team"]))]
        a["sack"] += _n(r, "def_sacks")
        a["int"] += _n(r, "def_interceptions")
        a["fum_rec"] += _n(r, "fumble_recovery_opp")
        a["ff"] += _n(r, "def_fumbles_forced")
        a["def_td"] += _n(r, "def_tds")
        a["safe"] += _n(r, "def_safeties")
        a["blk_kick"] += _n(r, "def_fg_blocks") + _n(r, "def_punt_blocks") + _n(r, "def_pat_blocks")
        a["st_td"] += _n(r, "special_teams_tds")
    tiers = [(0, "pts_allow_0"), (6, "pts_allow_1_6"), (13, "pts_allow_7_13"), (20, "pts_allow_14_20"),
             (27, "pts_allow_21_27"), (34, "pts_allow_28_34")]

    def tier_pts(allowed: int) -> float:
        return next((scoring.get(k, 0) for lim, k in tiers if allowed <= lim), scoring.get("pts_allow_35p", 0))

    out: dict[str, list[dict]] = defaultdict(list)
    for g in games:
        if g.get("game_type") != "REG" or (g.get("home_score") or "") == "":
            continue
        week = int(g["week"])
        for team, allowed, opp in ((g["home_team"], g["away_score"], g["away_team"]),
                                   (g["away_team"], g["home_score"], g["home_team"])):
            t = sleeper_team(team)
            stats = agg.get((g["season"], week, t), {})
            pts = sum(scoring.get(k, 0) * v for k, v in stats.items()) + tier_pts(int(allowed))
            out[t].append({"season": g["season"], "week": week, "team": t, "position": "DEF",
                           "pts": round(pts, 2), "pct": None, "partial": False,
                           "opp": sleeper_team(opp)})
    for logs in out.values():
        logs.sort(key=lambda x: (x["season"], x["week"]))
    return dict(out)


def assign_finishes(*log_sets: dict[str, list[dict]]) -> None:
    """Add each game's positional finish (1 = most points at that position that week, league
    scoring, every NFL player) as g["finish"]."""
    by_slot: dict[tuple, list] = defaultdict(list)
    for logs in log_sets:
        for games in logs.values():
            for g in games:
                if g.get("position"):
                    by_slot[(g["season"], g["week"], g["position"])].append(g)
    for games in by_slot.values():
        games.sort(key=lambda g: -g["pts"])
        for i, g in enumerate(games, 1):
            g["finish"] = i


def td_per_touch(logs: dict[str, list[dict]], season: str) -> dict[str, float]:
    """Position -> touchdowns per touch (targets + carries) this season, league-wide."""
    tot: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    for games in logs.values():
        for g in games:
            if g["season"] == season and g.get("position") in SKILL:
                t = tot[g["position"]]
                t[0] += g.get("rush_td", 0) + g.get("rec_td", 0)
                t[1] += g.get("targets", 0) + g.get("carries", 0)
    return {pos: round(td / touch, 4) for pos, (td, touch) in tot.items() if touch}


# --- league-wide rates ------------------------------------------------------
def usage_values(logs: dict[str, list[dict]], season: str) -> dict[str, dict[str, float]]:
    """Average fantasy points per target / carry / pass attempt by position (one season)."""
    tot = defaultdict(lambda: defaultdict(float))
    for games in logs.values():
        for g in games:
            if g["season"] != season or g["partial"] or g["position"] not in SKILL:
                continue
            t = tot[g["position"]]
            t["rec_pts"] += g["parts"]["rec"]; t["targets"] += g["targets"]
            t["rush_pts"] += g["parts"]["rush"]; t["carries"] += g["carries"]
            t["pass_pts"] += g["parts"]["pass"]; t["attempts"] += g["attempts"]
    out = {}
    for pos, t in tot.items():
        out[pos] = {"per_target": t["rec_pts"] / t["targets"] if t["targets"] else 0.0,
                    "per_carry": t["rush_pts"] / t["carries"] if t["carries"] else 0.0,
                    "per_attempt": t["pass_pts"] / t["attempts"] if t["attempts"] else 0.0}
    return out


def expected_points(game: dict, usage: dict) -> float | None:
    """Points a game 'should' have scored from its usage at league-average efficiency."""
    u = usage.get(game["position"])
    if not u:
        return None
    return (game["targets"] * u["per_target"] + game["carries"] * u["per_carry"]
            + game["attempts"] * u["per_attempt"])


def position_baselines(logs: dict[str, list[dict]], season: str, starters: dict[str, int]) -> dict[str, dict]:
    """Per position: a baseline rate (median of the fantasy-starter tier last season)
    and the typical game-to-game spread (coefficient of variation)."""
    per_pos = defaultdict(list)
    for games in logs.values():
        full = [g for g in games if g["season"] == season and not g["partial"]]
        if len(full) >= 6:
            pts = [g["pts"] for g in full]
            per_pos[full[-1]["position"]].append((mean(pts), pts))
    out = {}
    for pos, players in per_pos.items():
        players.sort(key=lambda x: -x[0])
        top = players[: max(starters.get(pos, 10), 5)]
        cvs = [(sum((p - m) ** 2 for p in pts) / (len(pts) - 1)) ** 0.5 / m
               for m, pts in top if m > 1]
        out[pos] = {"baseline": median(m for m, _ in top), "cv": median(cvs) if cvs else 0.6}
    return out


def defence_vs_position(logs: dict[str, list[dict]], sched: dict, season: str) -> dict[tuple, float]:
    """(defence team, position) -> shrunk multiplier on points allowed vs league average.

    Early in the season this is mostly 1.0 by design (shrunk toward average).
    """
    allowed = defaultdict(list)  # (def, pos) -> points per game allowed
    per_game = defaultdict(lambda: defaultdict(float))
    for games in logs.values():
        for g in games:
            if g["season"] != season or g["position"] not in POSITIONS or g["position"] == "DEF":
                continue
            opp = (sched.get(g["week"], {}).get(g["team"]) or {}).get("opp")
            if opp:
                per_game[(opp, g["position"])][g["week"]] += g["pts"]
    for key, weeks in per_game.items():
        allowed[key] = list(weeks.values())
    pos_avg = defaultdict(list)
    for (d, pos), vals in allowed.items():
        pos_avg[pos] += vals
    pos_mean = {pos: mean(v) for pos, v in pos_avg.items() if v}
    out = {}
    for (d, pos), vals in allowed.items():
        if not pos_mean.get(pos):
            continue
        ratio = mean(vals) / pos_mean[pos]
        n = len(vals)
        out[(d, pos)] = (n * ratio + DVP_SHRINK_GAMES) / (n + DVP_SHRINK_GAMES)
    return out


# --- per-player rate --------------------------------------------------------
# Share of the position baseline used for players with little history, by depth chart
# order. Backup QBs rarely play; every team starts one K and one DEF.
ROLE_FACTOR = {"QB": {1: 0.85, 2: 0.15}, "default": {1: 0.85, 2: 0.45, 3: 0.25}}
ROLE_FACTOR_OTHER = 0.15


def role_baseline(position: str, depth_order: int | None, baseline: float) -> float:
    if position in ("K", "DEF"):
        return baseline
    table = ROLE_FACTOR.get(position, ROLE_FACTOR["default"])
    return baseline * table.get(depth_order or 99, ROLE_FACTOR_OTHER)


PARTIAL_MIN_SNAPS = 0.2       # partial games count (scaled) only with 20%+ of snaps...
PARTIAL_MIN_FRACTION = 0.3    # ...and 30%+ of the player's normal snap share


def rate_components(games: list[dict], season: str, prior_season: str, position: str,
                    current_team: str | None, base: dict, usage: dict, depth_order: int | None = None,
                    as_of: int | None = None) -> dict:
    """Everything the rate formula needs, before any tunable setting is applied.
    as_of = the week being projected (for recency weighting of this season's games).
    this_games = (week, points, usage-expected points, fraction of a normal game, partial):
    full games count 1; partial games (left early) are scaled up to a full game per snap and
    carry their fraction as weight (used only if the learned partial_weight > 0)."""
    prior = [g for g in games if g["season"] == prior_season and not g["partial"]]
    season_games = [g for g in games if g["season"] == season and not g.get("opp_game")]
    this = [g for g in season_games if not g["partial"]]
    xs = [expected_points(g, usage) for g in this]
    this_games = [(g["week"], g["pts"], x, 1.0, False) for g, x in zip(this, xs)]
    snaps = [g["pct"] for g in this if g.get("pct")]
    normal = median(snaps) if snaps else None
    for g in season_games:
        if g["partial"] and normal and g.get("pct") and g["pct"] >= PARTIAL_MIN_SNAPS:
            frac = g["pct"] / normal
            if PARTIAL_MIN_FRACTION <= frac < 1:
                x = expected_points(g, usage)
                this_games.append((g["week"], g["pts"] / frac, x / frac if x is not None else None, round(frac, 3), True))
    xs = [x for x in xs if x is not None]
    return {"position": position, "baseline": role_baseline(position, depth_order, base.get("baseline", 5.0)),
            "rank_baseline": None, "cv": base.get("cv", 0.6), "n_prior": min(len(prior), PRIOR_SEASON_CAP),
            "games_prior": len(prior), "r_prior": mean(g["pts"] for g in prior) if prior else 0.0,
            "team_changed": bool(prior and current_team and prior[-1]["team"] != current_team),
            "n_this": len(this), "actual": mean(g["pts"] for g in this) if this else None,
            "expected": mean(xs) if xs else None,
            "partial_weeks": [g["week"] for g in games if g["season"] == season and g["partial"]],
            "this_games": this_games, "as_of": as_of if as_of is not None else max((g["week"] for g in this), default=0) + 1}


def rate_from(c: dict, params: dict | None = None) -> dict:
    """Rate, spread and confidence from components and the (possibly learned) settings."""
    P = params_or_default(params)
    pos = c["position"]
    g = lambda key: pp(P, key, pos)
    rec, pw = g("recency"), g("partial_weight")
    rows = []
    for wk, pts, x, frac, partial in c.get("this_games") or []:
        w = (rec ** max(c["as_of"] - wk, 1) if rec < 1 else 1.0) * (pw * frac if partial else 1.0)
        if w > 0:
            rows.append((w, pts, x))
    if "this_games" not in c:                  # older / hand-built components: plain averages
        actual, expected, n_eff = c.get("actual"), c.get("expected"), float(c.get("n_this") or 0)
    elif rows:
        tot = sum(w for w, _, _ in rows)
        actual = sum(w * pts for w, pts, _ in rows) / tot
        wx = [(w, x) for w, _, x in rows if x is not None]
        expected = sum(w * x for w, x in wx) / sum(w for w, _ in wx) if wx else None
        n_eff = tot / rec if rec < 1 else tot          # last week's full game counts as 1
    else:
        actual, expected, n_eff = None, None, 0.0
    r_this = actual if expected is None or actual is None else (1 - g("usage_blend")) * actual + g("usage_blend") * expected
    w_prior = g("prior_weight") * c["n_prior"] * (TEAM_CHANGE_FACTOR if c["team_changed"] else 1)
    w_this = n_eff
    k = g("baseline_games")
    baseline = c["baseline"]
    if c.get("rank_baseline") is not None and g("rank_prior") > 0:
        baseline = (1 - g("rank_prior")) * baseline + g("rank_prior") * c["rank_baseline"]
    rate = (k * baseline + w_prior * c["r_prior"] + w_this * (r_this or 0.0)) / (k + w_prior + w_this)
    role = c.get("role")
    if role and g("role_blend") > 0:
        w_role = g("role_blend") * role["n"] / (role["n"] + 2)
        rate = (1 - w_role) * rate + w_role * role["rate"]
    rate *= P["bias"].get(pos, 1.0)
    effective = w_prior + w_this
    sd_game = c["cv"] * max(rate, 3.0)
    se = sd_game / math.sqrt(k + effective)
    sd = math.sqrt(sd_game ** 2 + se ** 2) * P["sd_scale"].get(pos, 1.0)
    if c["n_this"] >= 4 and effective >= 8:
        confidence = "high"
    elif effective >= 4:
        confidence = "medium"
    else:
        confidence = "low"
    return {"rate": round(rate, 2), "sd": round(sd, 2), "se": round(se, 2), "confidence": confidence}


def player_rate(games: list[dict], season: str, prior_season: str, position: str,
                current_team: str | None, base: dict, usage: dict,
                depth_order: int | None = None, params: dict | None = None, as_of: int | None = None,
                role: dict | None = None, rank_baseline: float | None = None) -> dict:
    """Rest-of-season points per game for one player, with spread and confidence."""
    c = rate_components(games, season, prior_season, position, current_team, base, usage, depth_order, as_of)
    c["role"] = role
    c["rank_baseline"] = rank_baseline
    r = rate_from(c, params)
    return {**r, "role": role, "rank_baseline": rank_baseline, "games_prior": c["games_prior"], "games_this": c["n_this"],
            "partial_weeks": c["partial_weeks"], "prior_ppg": round(c["r_prior"], 2) if c["games_prior"] else None,
            "actual_ppg": round(c["actual"], 2) if c["actual"] is not None else None,
            "expected_ppg": round(c["expected"], 2) if c["expected"] is not None else None,
            "team_changed": c["team_changed"], "baseline": round(c["baseline"], 2)}


# --- weekly projection ------------------------------------------------------
def availability(status: str | None, weeks_ahead: int, practice: str | None = None,
                 table: dict | None = None) -> float:
    """Expected share of a game played, from the current injury designation.

    weeks_ahead = 0 is the current/next game. IR-type designations: out at least the
    next 4 weeks, then a 50% chance of being back (return dates are unknown).
    """
    if status in OFFENSE_STATUS_OUT:
        return 0.0 if weeks_ahead < 4 else 0.5
    if table and weeks_ahead == 0 and status in ("Questionable", "Doubtful", "Out"):
        hit = table.get(f"{status}|{practice}") if practice else None
        if hit and hit.get("games", 0) >= 20:
            return hit["share"]
        if status in table:
            return table[status]["share"]
    if status == "Out":
        return 0.0 if weeks_ahead == 0 else (0.75 if weeks_ahead == 1 else 1.0)
    if status == "Doubtful":
        return 0.25 if weeks_ahead == 0 else 1.0
    if status == "Questionable":
        return 0.85 if weeks_ahead == 0 else 1.0
    return 1.0


def matchup_raw(position: str, game: dict, dvp: dict, avg_implied: float | None) -> tuple[str, float | None]:
    """(source, raw signal) before damping: Vegas implied-total ratio - 1 (DEF: opponent's,
    inverted), or defence-vs-position ratio - 1."""
    if game.get("implied") is not None and avg_implied:
        if position == "DEF":
            return "vegas", (avg_implied - game["opp_implied"]) / avg_implied
        return "vegas", game["implied"] / avg_implied - 1
    d = dvp.get((game["opp"], position))
    return ("neutral", None) if d is None else ("opponent", d - 1)


def multiplier_from(position: str, source: str, raw: float | None, params: dict | None = None) -> float:
    P = params_or_default(params)
    if source == "vegas":
        return max(0.75, min(1.25, 1 + (raw if position == "DEF" else pp(P, "vegas_damping", position) * raw)))
    if source == "opponent":
        return max(0.9, min(1.1, 1 + pp(P, "dvp_damping", position) * raw))
    return 1.0


def script_multiplier(position: str, game: dict | None, params: dict | None = None) -> float:
    """Game script: favourites run more, underdogs throw more. margin = Vegas expected winning
    margin for this team (only known when lines are posted)."""
    if not game or game.get("margin") is None:
        return 1.0
    P = params_or_default(params)
    m = max(-2.0, min(2.0, game["margin"] / 7))
    if position == "RB":
        return max(0.85, min(1.15, 1 + pp(P, "script_rb", position) * m))
    if position in ("QB", "WR", "TE"):
        return max(0.85, min(1.15, 1 - pp(P, "script_pass", position) * m))
    return 1.0


def matchup_multiplier(position: str, game: dict, dvp: dict, avg_implied: float | None,
                       params: dict | None = None) -> tuple[float, str]:
    """(multiplier, source). Vegas implied totals when available, else dampened defence-vs-position."""
    source, raw = matchup_raw(position, game, dvp, avg_implied)
    return multiplier_from(position, source, raw, params), source


def project_weeks(rate: float, position: str, team: str | None, status: str | None,
                  weeks: list[int], first_week: int, sched: dict, dvp: dict,
                  avg_implied: float | None, params: dict | None = None,
                  practice: str | None = None) -> dict[int, dict]:
    """week -> {pts, bye, mult, source, avail, wx} for the given (unplayed) weeks."""
    P = params_or_default(params)
    out = {}
    for w in weeks:
        game = sched.get(w, {}).get(team) if team else None
        if not game:
            out[w] = {"pts": 0.0, "bye": True}
            continue
        mult, source = matchup_multiplier(position, game, dvp, avg_implied, params)
        wxm = weather_multiplier(position, game, P["weather"], pp(P, "weather_strength", position))
        scr = script_multiplier(position, game, P)
        avail = availability(status, w - first_week, practice, P["availability"])
        pts = round(rate * mult * wxm * scr * avail, 2)
        out[w] = {"pts": pts, "bye": False, "mult": round(mult, 3), "script": round(scr, 3),
                  "q": quantile_points(position, pts, P),
                  "source": source, "avail": avail, "opp": game["opp"], "home": game["home"],
                  "wx": {"roof": game.get("roof"), "wind": game.get("wind"), "temp": game.get("temp"),
                         "forecast": bool(game.get("forecast")), "mult": round(wxm, 3)}}
    return out


def quantile_points(position: str, pts: float, params: dict | None) -> list[float] | None:
    """[p10, p16, p50, p84, p90] points around a projection from the learned, lopsided
    distribution of actual / projected at this position and projection level."""
    Q = ((params or {}).get("quantiles") or {}).get(position)
    if not Q or not pts or pts <= 0:
        return None
    i = sum(pts > e for e in Q["edges"])
    ref = (Q.get("ref") or [None] * 3)[i]
    # above the band's typical projection, swings shrink in proportion (elite players are steadier
    # relative to their projection than the band average)
    k = math.sqrt(ref / pts) if ref and pts > ref else 1.0
    return [round(max(0.0, pts * (1 + (m - 1) * k)), 1) for m in Q["q"][i]]


def unplayed_weeks(sched: dict, team: str | None, weeks: list[int]) -> list[int]:
    """Weeks whose game for this team hasn't been played yet (bye weeks included)."""
    return [w for w in weeks if not (sched.get(w, {}).get(team) or {}).get("played")]


def average_implied(sched: dict) -> float | None:
    vals = [g["implied"] for teams in sched.values() for g in teams.values() if g.get("implied")]
    return mean(vals) if vals else None


# --- everything -------------------------------------------------------------
def build(players: dict, candidate_ids: set[str], rows_prior: list[dict], rows_this: list[dict],
          snaps: list[dict], games: list[dict], scoring: dict, season: str,
          weeks: list[int], starters_per_pos: dict[str, int],
          playoff_weeks: list[int] | None = None, params: dict | None = None,
          practice: dict[str, dict] | None = None, forecasts: dict | None = None) -> dict[str, dict]:
    """Projections for every candidate Sleeper player: rate, spread, confidence, weekly points.

    weeks = remaining regular-season weeks to project (games already played are skipped
    per team, so a Friday run only projects players who haven't played yet this week).
    """
    prior_season = str(int(season) - 1)
    logs = game_logs(rows_prior + rows_this, snaps, scoring)
    dlogs = def_logs(rows_prior + rows_this, games, scoring)
    roles.mark_opportunity(logs)
    assign_finishes(logs, dlogs)
    td_rates = td_per_touch(logs, season)
    sched = schedule(games, season)
    for (w, team), fc in (forecasts or {}).items():     # weather forecasts for upcoming games
        if team in sched.get(w, {}):
            sched[w][team].update({**fc, "forecast": True})
    usage = usage_values(logs, prior_season)
    volume = roles.team_volume(logs, season)
    base_logs = {**logs, **{f"DEF:{t}": v for t, v in dlogs.items()}}
    bases = position_baselines(base_logs, prior_season, starters_per_pos)
    dvp = defence_vs_position(logs, sched, season)
    avg_imp = average_implied(sched)
    _, by_gsis, by_name = index_rows(rows_prior + rows_this)
    first_week = weeks[0] if weeks else 0
    pos_rank = sleeper_pos_ranks(players)
    nid_of = {pid: match_player(players.get(pid) or {}, by_gsis, by_name) for pid in candidate_ids
              if (players.get(pid) or {}).get("position") in SKILL}
    tiers = rank_tiers([(players[pid]["position"], pos_rank.get(pid), established_ppg(logs.get(nid, [])))
                        for pid, nid in nid_of.items() if nid])

    out = {}
    for pid in candidate_ids:
        p = players.get(pid) or {}
        pos, team = p.get("position"), p.get("team")
        if pos not in POSITIONS or not team:
            continue
        nid = None
        if pos == "DEF":
            plogs = dlogs.get(pid, [])
        else:
            nid = match_player(p, by_gsis, by_name)
            plogs = logs.get(nid, []) if nid else []
        prac = (practice or {}).get(nid, {}).get("practice") if nid else None
        status = p.get("injury_status") or None
        if pos != "DEF":
            mark_partial(plogs, injured=status is not None)
        role = roles.role_components(plogs, season, pos, team, volume, usage)
        r = player_rate(plogs, season, prior_season, pos, team, bases.get(pos, {}), usage,
                        p.get("depth_chart_order"), params, first_week, role,
                        rank_baseline_for(pos, pos_rank.get(pid), tiers))
        r["nid"] = nid
        todo = unplayed_weeks(sched, team, weeks)
        weekly = project_weeks(r["rate"], pos, team, status, todo, first_week, sched, dvp, avg_imp, params, prac)
        log_this = [{k: g.get(k) for k in LOG_KEYS} for g in plogs if g["season"] == season]
        po = project_weeks(r["rate"], pos, team, status, unplayed_weeks(sched, team, playoff_weeks or []),
                           first_week, sched, dvp, avg_imp, params)
        r.update({"id": pid, "name": p.get("full_name") or pid, "position": pos, "team": team, "status": status,
                  "practice": prac, "weekly": weekly,
                  "log": log_this, "playoff_weeks": po, "pos_td_per_touch": td_rates.get(pos),
                  "ros": round(sum(x["pts"] for x in weekly.values()), 1),
                  "byes": [w for w, x in weekly.items() if x.get("bye")]})
        out[pid] = r
    apply_inheritance(out, volume, params)
    apply_qb_change(out, logs, players, season, params)
    P = params_or_default(params)
    for r in out.values():                     # ranges after all adjustments
        r["q"] = quantile_points(r["position"], r["rate"], P)
        for src in (r.get("weekly") or {}, r.get("playoff_weeks") or {}):
            for x in src.values():
                if not x.get("bye"):
                    x["q"] = quantile_points(r["position"], x["pts"], P)
    return out


# --- Sleeper ranking as a starting point for low-data players ----------------------
RANK_TIERS = (3, 6, 12, 18, 24, 36, 48, 64, 96, 10 ** 6)


def sleeper_pos_ranks(players: dict) -> dict[str, int]:
    """Sleeper id -> rank at his position by Sleeper's player ranking (search_rank),
    among players on an NFL team."""
    by_pos = defaultdict(list)
    for pid, p in players.items():
        sr = p.get("search_rank")
        if p.get("team") and p.get("position") in SKILL and sr is not None and sr < 9_000_000:
            by_pos[p["position"]].append((sr, pid))
    out = {}
    for rows in by_pos.values():
        rows.sort()
        for i, (_, pid) in enumerate(rows, 1):
            out[pid] = i
    return out


def established_ppg(games: list[dict], min_games: int = 6) -> float | None:
    """Points per full game over the last 16 full games (None if fewer than min_games)."""
    full = [g["pts"] for g in games if not g.get("partial")][-16:]
    return mean(full) if len(full) >= min_games else None


def rank_tiers(entries: list[tuple]) -> dict[str, list[tuple[int, float]]]:
    """Per position: (max rank, median points per game of established players in that rank band)."""
    by = defaultdict(lambda: defaultdict(list))
    for pos, rank, ppg in entries:
        if rank is None or ppg is None:
            continue
        band = next(t for t in RANK_TIERS if rank <= t)
        by[pos][band].append(ppg)
    out = {}
    for pos, bands in by.items():
        rows, last = [], None
        for t in RANK_TIERS:
            if len(bands.get(t, [])) >= 3:
                last = median(bands[t])
            if last is not None:
                rows.append((t, round(last, 2)))
        out[pos] = rows
    return out


def rank_baseline_for(position: str, rank: int | None, tiers: dict) -> float | None:
    if rank is None or position not in tiers:
        return None
    return next((v for t, v in tiers[position] if rank <= t), None)


# --- backup QB starting ------------------------------------------------------------
def primary_qbs(logs: dict[str, list[dict]], season: str, before_week: int | None = None) -> dict[str, str]:
    """team -> nflverse id of the QB with the most pass attempts this season (2+ starts)."""
    att, starts = defaultdict(lambda: defaultdict(float)), defaultdict(lambda: defaultdict(int))
    for key, games in logs.items():
        for g in games:
            if g["season"] == season and g.get("position") == "QB" and (before_week is None or g["week"] < before_week):
                att[g["team"]][key] += g.get("attempts") or 0
                if (g.get("attempts") or 0) >= 15:
                    starts[g["team"]][key] += 1
    return {t: max(a, key=a.get) for t, a in att.items() if starts[t][max(a, key=a.get)] >= 2}


def apply_qb_change(proj: dict[str, dict], logs: dict, players: dict, season: str, params: dict | None) -> None:
    """When a team's usual QB isn't expected to start in a week (out / not first on the depth
    chart), scale its RB / WR / TE projections by the learned backup-QB effect."""
    P = params_or_default(params)
    factor = P.get("qb_factor") or {}
    if not factor:
        return
    primary = primary_qbs(logs, season)
    pid_of_nid = {r.get("nid"): pid for pid, r in proj.items() if r.get("nid")}
    depth1 = {p.get("team"): pid for pid, p in players.items()
              if p.get("position") == "QB" and p.get("depth_chart_order") == 1 and p.get("team")}
    for pid, r in proj.items():
        pos, team = r["position"], r["team"]
        strength = pp(P, "qb_change", pos)
        if pos not in factor or not strength or team not in primary:
            continue
        qb_pid = pid_of_nid.get(primary[team])
        qb = proj.get(qb_pid) if qb_pid else None
        demoted = qb is None or qb["team"] != team or depth1.get(team) not in (None, qb_pid)
        m = 1 + strength * (factor[pos]["factor"] - 1)
        for src in (r.get("weekly") or {}, r.get("playoff_weeks") or {}):
            for w, x in src.items():
                if x.get("bye"):
                    continue
                qx = (qb or {}).get("weekly", {}).get(w) or ((qb or {}).get("playoff_weeks") or {}).get(w) or {}
                if demoted or qx.get("avail", 1.0) < 0.5:
                    x["pts"] = round(x["pts"] * m, 2)
                    x["qb_change"] = {"usual": (players.get(qb_pid) or {}).get("full_name") if qb_pid else None,
                                      "mult": round(m, 3)}
        r["ros"] = round(sum(x["pts"] for x in (r.get("weekly") or {}).values()), 1)


def apply_inheritance(proj: dict[str, dict], volume: dict, params: dict | None) -> None:
    """When a teammate at the same position is out (availability < 1 in a week), hand his
    normal share to the others (learned split) and add the extra points to their week.
    Also store each player's "if the man ahead misses" rate as r["contingency"]."""
    P = params_or_default(params)
    take = {pos: (P["inherit"] or {}).get(pos, {}).get("take", roles.DEFAULT_TAKE[pos]) for pos in roles.SHARE_KEY}
    group_take = {pos: (P["inherit"] or {}).get(pos, {}).get("group", roles.DEFAULT_GROUP[pos]) for pos in roles.SHARE_KEY}
    groups = defaultdict(list)
    for pid, r in proj.items():
        if r.get("role") and r["position"] in roles.SHARE_KEY:
            groups[(r["team"], r["position"])].append(pid)
    for (team, pos), pids in groups.items():
        if len(pids) < 2 or team not in volume:
            continue
        v = volume[team]
        def extra_pts(pid, dc, dt):
            ro = proj[pid]["role"]
            return (v["carries"] * dc * ro["e_car"] + v["targets"] * dt * ro["e_tgt"]) * P["bias"].get(pos, 1.0)
        member = lambda pid, avail: {"id": pid, "pos": pos, "avail": avail, "car_share": proj[pid]["role"]["car_share"],
                                     "tgt_share": proj[pid]["role"]["tgt_share"]}
        weeks = {w for pid in pids for w in list(proj[pid]["weekly"]) + list(proj[pid].get("playoff_weeks") or {})}
        for w in sorted(weeks):
            src = lambda pid: proj[pid]["weekly"].get(w) or (proj[pid].get("playoff_weeks") or {}).get(w)
            rows = {pid: src(pid) for pid in pids if src(pid) and not src(pid).get("bye")}
            group = [member(pid, x.get("avail", 1.0)) for pid, x in rows.items()]
            for a in group:
                if a["avail"] >= 1:
                    continue
                for pid, (dc, dt) in roles.redistribute(group, a, take[pos], group_take[pos]).items():
                    x = rows[pid]
                    add = extra_pts(pid, dc, dt) * x.get("mult", 1.0) * (x.get("wx") or {}).get("mult", 1.0) * x.get("avail", 1.0)
                    if add >= 0.05:
                        x["pts"] = round(x["pts"] + add, 2)
                        x.setdefault("inherit", []).append({"from": proj[a["id"]]["name"], "pts": round(add, 1)})
        # contingency: if the teammate with the biggest share misses a whole game
        key = "car_share" if pos == "RB" else "tgt_share"
        lead = max(pids, key=lambda pid: proj[pid]["role"][key])
        if proj[lead]["role"][key] < roles.REGULAR[pos]:
            continue
        gained = roles.redistribute([member(pid, 1.0) for pid in pids if pid != lead] + [member(lead, 0.0)],
                                    member(lead, 0.0), take[pos], group_take[pos])
        for pid, (dc, dt) in gained.items():
            proj[pid]["contingency"] = {"if_out": proj[lead]["name"], "id": lead,
                                        "rate": round(proj[pid]["rate"] + extra_pts(pid, dc, dt), 1)}
    for r in proj.values():
        if r.get("weekly"):
            r["ros"] = round(sum(x["pts"] for x in r["weekly"].values()), 1)


def replacement_rates(proj: dict[str, dict], rostered: set[str], top_n: int = 3) -> dict[str, float]:
    """Replacement level per position: average rate of the best few free agents."""
    out = {}
    for pos in POSITIONS:
        fas = sorted((p["rate"] for pid, p in proj.items()
                      if p["position"] == pos and pid not in rostered and p["status"] not in OFFENSE_STATUS_OUT),
                     reverse=True)
        out[pos] = round(mean(fas[:top_n]), 2) if fas else 0.0
    return out


def value_over_replacement(p: dict, repl: dict[str, float], n_weeks: int) -> float:
    """Rest-of-season points above what a free agent at the position would give."""
    return round(p["ros"] - repl.get(p["position"], 0.0) * n_weeks, 1)


def buy_sell(proj: dict[str, dict], owners: dict[str, int], my_rid: int,
             min_gap: float = 3.0, min_games: int = 2) -> dict[str, list[dict]]:
    """Players whose results so far differ a lot from their projection.

    Sell high: my players scoring well above projection. Buy low: other teams' players
    scoring well below it. Gap must be >= max(min_gap, 25% of the projection).
    """
    buy, sell = [], []
    for pid, p in proj.items():
        rid = owners.get(pid)
        if rid is None or p["actual_ppg"] is None or p["games_this"] < min_games \
                or p["position"] in ("K", "DEF") or p["status"] in OFFENSE_STATUS_OUT:
            continue
        gap = round(p["actual_ppg"] - p["rate"], 2)
        if abs(gap) < max(min_gap, 0.25 * p["rate"]):
            continue
        row = {"id": pid, "roster_id": rid, "gap": gap, "rate": p["rate"], "actual_ppg": p["actual_ppg"],
               "expected_ppg": p["expected_ppg"], "confidence": p["confidence"]}
        if gap > 0 and rid == my_rid:
            sell.append(row)
        elif gap < 0 and rid != my_rid:
            buy.append(row)
    buy.sort(key=lambda r: r["gap"])
    sell.sort(key=lambda r: -r["gap"])
    return {"buy_low": buy, "sell_high": sell}
