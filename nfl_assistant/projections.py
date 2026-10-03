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

from .nflverse import compute_points, index_rows, match_player, norm_name

TEAM_FROM_NFLVERSE = {"LA": "LAR"}
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
        base = {"played": played, "gameday": g.get("gameday")}
        out[week][home] = {**base, "opp": away, "home": True, "implied": imp_home,
                           "opp_implied": imp_away}
        out[week][away] = {**base, "opp": home, "home": False, "implied": imp_away,
                           "opp_implied": imp_home}
    return dict(out)


def all_teams(sched: dict) -> set[str]:
    return {t for teams in sched.values() for t in teams}


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
    normal = median(pcts)
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
        for team, allowed in ((g["home_team"], g["away_score"]), (g["away_team"], g["home_score"])):
            t = sleeper_team(team)
            stats = agg.get((g["season"], week, t), {})
            pts = sum(scoring.get(k, 0) * v for k, v in stats.items()) + tier_pts(int(allowed))
            out[t].append({"season": g["season"], "week": week, "team": t, "position": "DEF",
                           "pts": round(pts, 2), "pct": None, "partial": False})
    for logs in out.values():
        logs.sort(key=lambda x: (x["season"], x["week"]))
    return dict(out)


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


def player_rate(games: list[dict], season: str, prior_season: str, position: str,
                current_team: str | None, base: dict, usage: dict,
                depth_order: int | None = None) -> dict:
    """Rest-of-season points per game for one player, with spread and confidence."""
    prior = [g for g in games if g["season"] == prior_season and not g["partial"]]
    this = [g for g in games if g["season"] == season and not g["partial"]]
    partial = [g["week"] for g in games if g["season"] == season and g["partial"]]
    baseline = role_baseline(position, depth_order, base.get("baseline", 5.0))

    r_prior = mean(g["pts"] for g in prior) if prior else 0.0
    actual = mean(g["pts"] for g in this) if this else None
    xs = [expected_points(g, usage) for g in this]
    xs = [x for x in xs if x is not None]
    expected = mean(xs) if xs else None
    r_this = actual if expected is None or actual is None else (1 - USAGE_BLEND) * actual + USAGE_BLEND * expected

    team_changed = bool(prior and current_team and prior[-1]["team"] != current_team)
    w_prior = PRIOR_SEASON_WEIGHT * min(len(prior), PRIOR_SEASON_CAP) * (TEAM_CHANGE_FACTOR if team_changed else 1)
    w_this = len(this)
    k = BASELINE_GAMES
    rate = (k * baseline + w_prior * r_prior + w_this * (r_this or 0.0)) / (k + w_prior + w_this)

    effective = w_prior + w_this
    sd_game = base.get("cv", 0.6) * max(rate, 3.0)
    se = sd_game / math.sqrt(k + effective)
    if w_this >= 4 and effective >= 8:
        confidence = "high"
    elif effective >= 4:
        confidence = "medium"
    else:
        confidence = "low"
    return {"rate": round(rate, 2), "sd": round(math.sqrt(sd_game ** 2 + se ** 2), 2), "se": round(se, 2),
            "confidence": confidence, "games_prior": len(prior), "games_this": len(this),
            "partial_weeks": partial, "prior_ppg": round(r_prior, 2) if prior else None,
            "actual_ppg": round(actual, 2) if actual is not None else None,
            "expected_ppg": round(expected, 2) if expected is not None else None,
            "team_changed": team_changed, "baseline": round(baseline, 2)}


# --- weekly projection ------------------------------------------------------
def availability(status: str | None, weeks_ahead: int) -> float:
    """Expected share of a game played, from the current injury designation.

    weeks_ahead = 0 is the current/next game. IR-type designations: out at least the
    next 4 weeks, then a 50% chance of being back (return dates are unknown).
    """
    if status in OFFENSE_STATUS_OUT:
        return 0.0 if weeks_ahead < 4 else 0.5
    if status == "Out":
        return 0.0 if weeks_ahead == 0 else (0.75 if weeks_ahead == 1 else 1.0)
    if status == "Doubtful":
        return 0.25 if weeks_ahead == 0 else 1.0
    if status == "Questionable":
        return 0.85 if weeks_ahead == 0 else 1.0
    return 1.0


def matchup_multiplier(position: str, game: dict, dvp: dict, avg_implied: float | None) -> tuple[float, str]:
    """(multiplier, source). Vegas implied totals when available, else dampened defence-vs-position."""
    if game.get("implied") is not None and avg_implied:
        if position == "DEF":
            m = 1 + (avg_implied - game["opp_implied"]) / avg_implied
        else:
            m = 1 + VEGAS_DAMPING * (game["implied"] / avg_implied - 1)
        return max(0.75, min(1.25, m)), "vegas"
    d = dvp.get((game["opp"], position))
    if d is None:
        return 1.0, "neutral"
    return max(0.9, min(1.1, 1 + DVP_DAMPING * (d - 1))), "opponent"


def project_weeks(rate: float, position: str, team: str | None, status: str | None,
                  weeks: list[int], first_week: int, sched: dict, dvp: dict,
                  avg_implied: float | None) -> dict[int, dict]:
    """week -> {pts, bye, mult, source, avail} for the given (unplayed) weeks."""
    out = {}
    for w in weeks:
        game = sched.get(w, {}).get(team) if team else None
        if not game:
            out[w] = {"pts": 0.0, "bye": True}
            continue
        mult, source = matchup_multiplier(position, game, dvp, avg_implied)
        avail = availability(status, w - first_week)
        out[w] = {"pts": round(rate * mult * avail, 2), "bye": False, "mult": round(mult, 3),
                  "source": source, "avail": avail, "opp": game["opp"], "home": game["home"]}
    return out


def unplayed_weeks(sched: dict, team: str | None, weeks: list[int]) -> list[int]:
    """Weeks whose game for this team hasn't been played yet (bye weeks included)."""
    return [w for w in weeks if not (sched.get(w, {}).get(team) or {}).get("played")]


def average_implied(sched: dict) -> float | None:
    vals = [g["implied"] for teams in sched.values() for g in teams.values() if g.get("implied")]
    return mean(vals) if vals else None


# --- everything -------------------------------------------------------------
def build(players: dict, candidate_ids: set[str], rows_prior: list[dict], rows_this: list[dict],
          snaps: list[dict], games: list[dict], scoring: dict, season: str,
          weeks: list[int], starters_per_pos: dict[str, int]) -> dict[str, dict]:
    """Projections for every candidate Sleeper player: rate, spread, confidence, weekly points.

    weeks = remaining regular-season weeks to project (games already played are skipped
    per team, so a Friday run only projects players who haven't played yet this week).
    """
    prior_season = str(int(season) - 1)
    logs = game_logs(rows_prior + rows_this, snaps, scoring)
    dlogs = def_logs(rows_prior + rows_this, games, scoring)
    sched = schedule(games, season)
    usage = usage_values(logs, prior_season)
    base_logs = {**logs, **{f"DEF:{t}": v for t, v in dlogs.items()}}
    bases = position_baselines(base_logs, prior_season, starters_per_pos)
    dvp = defence_vs_position(logs, sched, season)
    avg_imp = average_implied(sched)
    _, by_gsis, by_name = index_rows(rows_prior + rows_this)
    first_week = weeks[0] if weeks else 0

    out = {}
    for pid in candidate_ids:
        p = players.get(pid) or {}
        pos, team = p.get("position"), p.get("team")
        if pos not in POSITIONS or not team:
            continue
        if pos == "DEF":
            plogs = dlogs.get(pid, [])
        else:
            nid = match_player(p, by_gsis, by_name)
            plogs = logs.get(nid, []) if nid else []
        status = p.get("injury_status") or None
        if pos != "DEF":
            mark_partial(plogs, injured=status is not None)
        r = player_rate(plogs, season, prior_season, pos, team, bases.get(pos, {}), usage,
                        p.get("depth_chart_order"))
        todo = unplayed_weeks(sched, team, weeks)
        weekly = project_weeks(r["rate"], pos, team, status, todo, first_week, sched, dvp, avg_imp)
        log_this = [{k: g.get(k) for k in ("week", "pts", "pct", "targets", "carries", "receptions",
                                            "attempts", "partial")}
                    for g in plogs if g["season"] == season]
        r.update({"id": pid, "position": pos, "team": team, "status": status, "weekly": weekly,
                  "log": log_this,
                  "ros": round(sum(x["pts"] for x in weekly.values()), 1),
                  "byes": [w for w, x in weekly.items() if x.get("bye")]})
        out[pid] = r
    return out


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
