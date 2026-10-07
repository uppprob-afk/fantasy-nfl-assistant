"""Self-assessment and learning for the projection model.

1. Backtest (honest): for every completed week this season, rebuild each relevant player's
   projection using only what was known before kickoff - games before that week, the
   official injury report for that week (so players listed Out / Doubtful / Questionable are
   included, scoring 0 if they sat), Vegas lines, Sleeper rankings when a snapshot exists -
   and compare with what they scored (nflverse stats under league scoring).
2. Tune: try alternative settings (globally, then per position) on that track record; adopt
   them only when clearly better on enough games, and only if re-learning without each of the
   last few weeks still beats the starting settings on that unseen week (rolling check).
   Per-position bias / range-width corrections are shrunk toward "no change" and capped.
3. Ranges: learn the real, lopsided spread of results (actual / projected) per position and
   projection level - floor (10th), range (16th-84th) and ceiling (90th percentile).
4. Live ledger: the projections the dashboard actually showed are saved each run and scored
   once the games are played - the honest scorecard.

Pure functions except the small ledger / history file helpers at the bottom.
"""

import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

from . import projections as pj
from . import roles
from .factors import practice_bucket, weather_multiplier

# Settings the tuner may try (the starting values are always included).
GRID = {
    "usage_blend": (0.2, 0.35, 0.5, 0.65, 0.8),
    "prior_weight": (0.25, 0.4, 0.5, 0.65, 0.8, 1.0),
    "baseline_games": (1, 1.5, 2, 3, 4),
    "matchup": (0.25, 0.4, 0.5, 0.6, 0.75),     # applied to both vegas_damping and dvp_damping
    "recency": (1.0, 0.95, 0.9, 0.85, 0.8, 0.7),
    "partial_weight": (0.0, 0.25, 0.5, 0.75, 1.0),
    "rank_prior": (0.0, 0.25, 0.5, 0.75, 1.0),
    "script_rb": (0.0, 0.02, 0.04, 0.06, 0.1),
    "script_pass": (0.0, 0.02, 0.04, 0.06),
    "qb_change": (0.0, 0.5, 1.0),
    "weather_strength": (0.0, 0.25, 0.5, 0.75, 1.0),
    "role_blend": (0.0, 0.15, 0.3, 0.5, 0.75),
}
POS_KEYS = ("usage_blend", "prior_weight", "baseline_games", "recency", "partial_weight", "rank_prior",
            "role_blend", "weather_strength", "matchup")
MIN_GAMES_TO_TUNE = 300       # games in the backtest before any setting can change
MIN_POS_GAMES = 150           # games at a position before it gets its own settings
MIN_IMPROVEMENT = 0.005       # adopt new global settings only if they cut the error by 0.5%+ (the rolling check on unseen weeks is the main safeguard)
MIN_POS_IMPROVEMENT = 0.02    # ...and per-position ones by 2%+
CV_WEEKS = 3                  # rolling check: re-learn without each of the last 3 weeks
SHRINK_GAMES = 150            # pseudo-games of "no correction" for bias / range-width
BIAS_CAP = (0.9, 1.1)
SD_CAP = (0.75, 1.4)
QUANTILES = (0.10, 0.16, 0.50, 0.84, 0.90)
Q_SHRINK = 40                 # pseudo-games of the position-wide spread for each level band
RELEVANT_MULTIPLE = 2         # backtest players ranked within 2x the league's starters at the position
OUT_STATUSES = ("Questionable", "Doubtful", "Out")


# --- backtest -----------------------------------------------------------------------
def backtest_records(rows_prior: list[dict], rows_this: list[dict], snaps: list[dict], games: list[dict],
                     scoring: dict, season: str, starters: dict[str, int], weeks: list[int],
                     reports: list[dict] | None = None, ranks_by_week: dict | None = None) -> list[dict]:
    """One record per relevant player and completed week, holding the projection components
    as of kickoff and the actual result. Players listed on that week's injury report who
    didn't play are included (actual 0); ranks_by_week = week -> nflverse id -> position rank
    (from a Sleeper snapshot taken before that week)."""
    prior_season = str(int(season) - 1)
    logs = pj.game_logs(rows_prior + rows_this, snaps, scoring)
    dlogs = pj.def_logs(rows_prior + rows_this, games, scoring)
    roles.mark_opportunity(logs)
    sched = pj.schedule(games, season)
    usage = pj.usage_values(logs, prior_season)
    base_logs = {**logs, **{f"DEF:{t}": v for t, v in dlogs.items()}}
    bases = pj.position_baselines(base_logs, prior_season, starters)
    avg_imp = pj.average_implied(sched)
    everyone = {**logs, **{f"DEF:{t}": v for t, v in dlogs.items()}}
    report = {}
    for r in reports or []:
        if str(r.get("season")) == str(season) and r.get("report_status") in OUT_STATUSES and r.get("gsis_id"):
            report[(r["gsis_id"], int(r.get("week") or 0))] = (r["report_status"], practice_bucket(r.get("practice_status")))
    out = []
    for w in weeks:
        before = {k: [g for g in v if g["season"] != season or g["week"] < w] for k, v in logs.items()}
        dvp = pj.defence_vs_position(before, sched, season)
        volume = roles.team_volume(logs, season, before_week=w)
        primary = pj.primary_qbs(logs, season, before_week=w)
        starter = {}                                   # team -> QB with most attempts this week
        for key, plogs in logs.items():
            for g in plogs:
                if g["season"] == season and g["week"] == w and g.get("position") == "QB" and (g.get("attempts") or 0) >= 10:
                    if g["team"] not in starter or g["attempts"] > starter[g["team"]][1]:
                        starter[g["team"]] = (key, g["attempts"])
        ranks = (ranks_by_week or {}).get(w) or {}
        tiers = pj.rank_tiers([(v[0], v[1], pj.established_ppg(before.get(k, []))) for k, v in ranks.items()]) if ranks else {}
        cands = []
        for key, plogs in everyone.items():
            prev = [x for x in plogs if x["season"] != season or x["week"] < w]
            if not prev:
                continue            # no history at all: can't judge the model fairly
            g = next((x for x in plogs if x["season"] == season and x["week"] == w), None)
            status, practice = report.get((key, w), (None, None))
            if g is None and status is None:
                continue            # didn't play and wasn't listed injured (cut, inactive...)
            team = g["team"] if g else prev[-1].get("team")
            pos = (g or prev[-1]).get("position")
            game = sched.get(w, {}).get(team)
            if pos not in pj.POSITIONS or not game:
                continue
            c = pj.rate_components(prev, season, prior_season, pos, team, bases.get(pos, {}), usage, 1, w)
            c["role"] = roles.role_components(prev, season, pos, team, volume, usage)
            if key in ranks:
                c["rank_baseline"] = pj.rank_baseline_for(pos, ranks[key][1], tiers)
            source, raw = pj.matchup_raw(pos, game, dvp, avg_imp)
            naive = c["actual"] if c["actual"] is not None else (c["r_prior"] if c["n_prior"] else None)
            qb_change = (pos in ("RB", "WR", "TE") and team in primary and team in starter
                         and starter[team][0] != primary[team])
            cands.append({"week": w, "key": key, "pos": pos, "comp": c, "source": source, "raw": raw,
                          "game": {k: game.get(k) for k in ("roof", "wind", "temp", "margin")},
                          "status": status, "practice": practice, "qb_change": qb_change,
                          "actual": round(g["pts"], 2) if g else 0.0, "played": g is not None,
                          "partial": bool(g and g.get("partial")), "naive": naive})
        # keep the fantasy-relevant players (by default-settings projection) at each position
        by_pos = defaultdict(list)
        for r in cands:
            by_pos[r["pos"]].append((pj.rate_from(r["comp"])["rate"], r))
        for pos, rows in by_pos.items():
            rows.sort(key=lambda x: -x[0])
            out += [r for _, r in rows[: RELEVANT_MULTIPLE * starters.get(pos, 12)]]
    return out


def project(rec: dict, params: dict | None) -> tuple[float, float]:
    """(projected points, spread) for a backtest record under `params`, including that week's
    injury designation, matchup, weather, game script and QB situation."""
    P = pj.params_or_default(params)
    pos = rec["pos"]
    r = pj.rate_from(rec["comp"], P)
    m = pj.multiplier_from(pos, rec["source"], rec["raw"], P)
    m *= weather_multiplier(pos, rec.get("game"), P["weather"], pj.pp(P, "weather_strength", pos))
    m *= pj.script_multiplier(pos, rec.get("game"), P)
    if rec.get("qb_change") and P.get("qb_factor") and pos in P["qb_factor"]:
        m *= 1 + pj.pp(P, "qb_change", pos) * (P["qb_factor"][pos]["factor"] - 1)
    avail = pj.availability(rec.get("status"), 0, rec.get("practice"), P["availability"]) if rec.get("status") else 1.0
    return r["rate"] * m * avail, r["sd"] * (avail if avail < 1 else 1)


# --- scoring ------------------------------------------------------------------------
def evaluate(records: list[dict], params: dict | None = None) -> dict:
    """Accuracy over every record (injured / partial games included - what you'd really
    have got): mean absolute error, bias (projected - actual), share of results inside the
    projected range (16th-84th percentile when learned, else +-1 sd; ~68% is well calibrated)
    and inside floor-ceiling (10th-90th, ~80%), vs a naive 'season average so far' guess.
    Also full games only, and per-position / per-week breakdowns."""
    if not records:
        return {"games": 0}
    P = pj.params_or_default(params)

    def stats(rows):
        errs, inside, inside_fc, naive = [], 0, 0, []
        for r in rows:
            p, sd = project(r, P)
            errs.append(p - r["actual"])
            q = pj.quantile_points(r["pos"], p, P)
            if q:
                inside += q[1] <= r["actual"] <= q[3]
                inside_fc += q[0] <= r["actual"] <= q[4]
            else:
                inside += abs(p - r["actual"]) <= sd
            if r["naive"] is not None:
                naive.append(abs(r["naive"] - r["actual"]))
        n = len(rows)
        return {"games": n, "mae": round(mean(abs(e) for e in errs), 2), "bias": round(mean(errs), 2),
                "coverage": round(inside / n, 3), "coverage_fc": round(inside_fc / n, 3) if P.get("quantiles") else None,
                "naive_mae": round(mean(naive), 2) if naive else None}

    out = stats(records)
    full = [r for r in records if r.get("played", True) and not r["partial"]]
    out["full_games"] = stats(full) if full else {"games": 0}
    out["injured_or_partial"] = len(records) - len(full)
    by_pos, by_week = defaultdict(list), defaultdict(list)
    for r in records:
        by_pos[r["pos"]].append(r)
        by_week[r["week"]].append(r)
    out["by_position"] = {k: stats(v) for k, v in sorted(by_pos.items())}
    out["by_week"] = {k: stats(v) for k, v in sorted(by_week.items())}
    return out


def _mae(records: list[dict], params: dict) -> float:
    return mean(abs(project(r, params)[0] - r["actual"]) for r in records)


# --- learning -----------------------------------------------------------------------
def _with(params: dict, key: str, value, pos: str | None = None) -> dict:
    vals = {"vegas_damping": value, "dvp_damping": value} if key == "matchup" else {key: value}
    if pos is None:
        return {**params, **vals}
    by_pos = {k: dict(v) for k, v in (params.get("by_pos") or {}).items()}
    by_pos[pos] = {**by_pos.get(pos, {}), **vals}
    return {**params, "by_pos": by_pos}


def _coordinate_search(records: list[dict], start: dict, keys, pos: str | None = None, passes: int = 2) -> tuple[dict, float]:
    best, best_mae = start, _mae(records, start)
    for _ in range(passes):
        improved = False
        for key in keys:
            for v in GRID[key]:
                cand = _with(best, key, v, pos)
                m = _mae(records, cand)
                if m < best_mae - 1e-9:
                    best, best_mae, improved = cand, m, True
        if not improved:
            break
    return best, best_mae


def tune(records: list[dict], base: dict | None = None) -> dict:
    """Pick settings from the track record. `base` carries the learned injury / weather /
    QB tables. Global settings first, then per-position overrides where a position has
    enough games and clearly benefits. Returns {params, changed, reason, ...}."""
    defaults = pj.params_or_default(base)
    result = {"params": defaults, "changed": [], "games": len(records)}
    if len(records) < MIN_GAMES_TO_TUNE:
        result["reason"] = (f"Not enough games yet to change anything ({len(records)} of {MIN_GAMES_TO_TUNE} "
                            f"needed). Using the starting settings.")
        return result
    base_mae = _mae(records, defaults)
    best, best_mae = _coordinate_search(records, defaults, list(GRID))
    params = dict(best) if best_mae <= base_mae * (1 - MIN_IMPROVEMENT) else dict(defaults)
    params["by_pos"] = {}
    by_pos = defaultdict(list)
    for r in records:
        by_pos[r["pos"]].append(r)
    for pos, rows in by_pos.items():
        if len(rows) < MIN_POS_GAMES:
            continue
        before = _mae(rows, params)
        cand, m = _coordinate_search(rows, params, POS_KEYS, pos, passes=1)
        if m <= before * (1 - MIN_POS_IMPROVEMENT):
            params["by_pos"][pos] = cand["by_pos"][pos]
    # per-position bias and range width, shrunk toward 1 and capped
    bias, sd_scale = {}, {}
    for pos, rows in by_pos.items():
        n = len(rows)
        proj = [project(r, params) for r in rows]
        tot_p, tot_a = sum(p for p, _ in proj), sum(r["actual"] for r in rows)
        ratio = tot_a / tot_p if tot_p > 0 else 1.0
        bias[pos] = round(min(BIAS_CAP[1], max(BIAS_CAP[0], (n * ratio + SHRINK_GAMES) / (n + SHRINK_GAMES))), 3)
        z = [((r["actual"] - p * bias[pos]) / (sd * bias[pos])) ** 2 for r, (p, sd) in zip(rows, proj) if sd > 0]
        width = math.sqrt(mean(z)) if z else 1.0
        sd_scale[pos] = round(min(SD_CAP[1], max(SD_CAP[0], (n * width + SHRINK_GAMES) / (n + SHRINK_GAMES))), 3)
    params["bias"] = {**defaults["bias"], **bias}
    params["sd_scale"] = {**defaults["sd_scale"], **sd_scale}
    final_mae = _mae(records, params)
    result.update({"params": params, "default_mae": round(base_mae, 3), "tuned_mae": round(final_mae, 3),
                   "improvement": round(1 - final_mae / base_mae, 4) if base_mae else 0.0,
                   "changed": changes(defaults, params)})
    result["reason"] = ("Settings adjusted from this season's results." if result["changed"]
                        else "Starting settings are still the best fit.")
    return result


def learn_quantiles(records: list[dict], params: dict) -> dict:
    """Per position: projection-level bands (thirds) and, for each, the 10th / 16th / 50th /
    84th / 90th percentile of actual / projected, pulled toward the position-wide spread."""
    P = pj.params_or_default({**params, "quantiles": None})
    by_pos = defaultdict(list)
    for r in records:
        p = project(r, P)[0]
        if p >= 1:
            by_pos[r["pos"]].append((p, r["actual"] / p))

    def qs(vals):
        v = sorted(vals)
        return [v[min(len(v) - 1, int(q * len(v)))] for q in QUANTILES]

    out = {}
    for pos, rows in by_pos.items():
        if len(rows) < 30:
            continue
        ps = sorted(p for p, _ in rows)
        edges = [ps[len(ps) // 3], ps[2 * len(ps) // 3]]
        pooled = qs([x for _, x in rows])
        bands, refs = [], []
        for i in range(3):
            lo = edges[i - 1] if i else -1
            hi = edges[i] if i < 2 else 1e9
            band = [(p, x) for p, x in rows if lo < p <= hi]
            vals = [x for _, x in band]
            own = qs(vals) if len(vals) >= 10 else pooled
            n = len(vals)
            bands.append([round((n * a + Q_SHRINK * b) / (n + Q_SHRINK), 3) for a, b in zip(own, pooled)])
            refs.append(round(sorted(p for p, _ in band)[len(band) // 2], 2) if band else None)
        out[pos] = {"edges": [round(e, 2) for e in edges], "q": bands, "ref": refs, "games": len(rows)}
    return out


LABELS = {
    "usage_blend": "Weight on usage (targets/carries) vs actual points this season",
    "prior_weight": "Weight of a last-season game vs a this-season game",
    "baseline_games": "Pull toward the starting point for each player (pseudo-games)",
    "vegas_damping": "Strength of Vegas-line matchup adjustments",
    "dvp_damping": "Strength of opponent-defence matchup adjustments",
    "recency": "How much each older game this season still counts (1 = all equal)",
    "weather_strength": "How much of the learned weather / venue effects to apply",
    "role_blend": "Weight on the role projection (team volume x share x efficiency)",
    "partial_weight": "How much a partial game counts (scaled to a full game per snap)",
    "rank_prior": "Weight on Sleeper's player ranking in the starting point",
    "script_rb": "Game script: RB change per 7 pts of expected winning margin",
    "script_pass": "Game script: QB / WR / TE change per 7 pts of expected margin (opposite)",
    "qb_change": "How much of the backup-QB effect to apply",
}


def changes(old: dict, new: dict) -> list[dict]:
    """Plain-English list of settings that differ."""
    out = []
    for k, label in LABELS.items():
        if abs(new[k] - old[k]) > 1e-9:
            out.append({"key": k, "label": label, "from": old[k], "to": new[k]})
    for pos, over in (new.get("by_pos") or {}).items():
        for k, v in over.items():
            if k in LABELS and abs(v - new[k]) > 1e-9:
                out.append({"key": f"{pos}.{k}", "label": f"{pos}: {LABELS[k][0].lower()}{LABELS[k][1:]}", "from": new[k], "to": v})
    for pos, v in new["bias"].items():
        if abs(v - 1) >= 0.01:
            out.append({"key": f"bias.{pos}", "label": f"{pos} projections scaled", "from": 1.0, "to": v})
    for pos, v in new["sd_scale"].items():
        if abs(v - 1) >= 0.03:
            out.append({"key": f"sd.{pos}", "label": f"{pos} projected ranges widened/narrowed", "from": 1.0, "to": v})
    return out


def learn(records: list[dict], base: dict | None = None) -> dict:
    """Tune, then a rolling check: for each of the last few weeks, re-learn without it and
    test on it. The learned settings are used only if, added up over those unseen weeks, they
    beat the starting settings. Then learn the ranges."""
    weeks = sorted({r["week"] for r in records})
    tuned = tune(records, base)
    defaults = pj.params_or_default(base)
    tuned["validation"] = None
    if tuned["changed"] and len(weeks) >= 2:
        folds, d_sum, t_sum, n = [], 0.0, 0.0, 0
        for w in weeks[-CV_WEEKS:]:
            train = [r for r in records if r["week"] < w]
            test = [r for r in records if r["week"] == w]
            if not test or len({r["week"] for r in train}) < 1:
                continue
            held = tune(train, base)
            d, t = _mae(test, defaults), _mae(test, held["params"])
            folds.append({"week": w, "games": len(test), "default_mae": round(d, 3), "learned_mae": round(t, 3)})
            d_sum += d * len(test); t_sum += t * len(test); n += len(test)
        if n:
            passed = t_sum < d_sum
            tuned["validation"] = {"weeks": [f["week"] for f in folds], "games": n, "folds": folds,
                                   "default_mae": round(d_sum / n, 3), "learned_mae": round(t_sum / n, 3), "passed": passed,
                                   "week": folds[-1]["week"]}
            if not passed:
                tuned.update({"params": dict(defaults), "changed": [],
                              "reason": "Learned settings didn't hold up on recent weeks they hadn't seen, "
                                        "so the starting settings stay."})
    tuned["params"]["quantiles"] = learn_quantiles(records, tuned["params"])
    return tuned


# --- live ledger (what the dashboard actually showed) ------------------------------------
def ledger_update(path: Path, proj: dict[str, dict], names: dict[str, str], ids: set[str]) -> dict:
    """Save each player's projection for their next unplayed game (overwritten every run
    until it's played, so the last pre-game projection is what gets scored)."""
    led = json.loads(path.read_text()) if path.exists() else {}
    for pid in ids:
        p = proj.get(pid)
        if not p:
            continue
        nxt = next(((w, x) for w, x in sorted(p["weekly"].items()) if not x.get("bye")), None)
        if not nxt:
            continue
        w, x = nxt
        sd = p["sd"] * (x["pts"] / p["rate"]) if p["rate"] else p["sd"]
        led[f"{pid}:{w}"] = {"id": pid, "week": w, "name": names.get(pid, pid), "pos": p["position"],
                             "pts": round(x["pts"], 1), "sd": round(sd, 1), "status": p.get("status"),
                             "confidence": p["confidence"], "source": x.get("source"),
                             "practice": p.get("practice"), "avail": x.get("avail"), "wx": x.get("wx")}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(led, indent=0, sort_keys=True) + "\n")
    return led


def ledger_score(led: dict, completed: list[int], actual: dict[str, dict[int, float]]) -> dict:
    """Score saved projections for completed weeks. actual = pid -> week -> points
    (Sleeper's when on a league roster, else calculated). Missing = didn't play (scored 0)."""
    rows = []
    for e in led.values():
        if e["week"] not in completed:
            continue
        a = (actual.get(e["id"]) or {}).get(e["week"])
        rows.append({**e, "actual": round(a or 0.0, 1), "error": round(e["pts"] - (a or 0.0), 1),
                     "inside": abs(e["pts"] - (a or 0.0)) <= e["sd"]})
    if not rows:
        return {"games": 0}
    by_week = defaultdict(list)
    for r in rows:
        by_week[r["week"]].append(r)
    summ = lambda rs: {"games": len(rs), "mae": round(mean(abs(r["error"]) for r in rs), 2),
                       "bias": round(mean(r["error"] for r in rs), 2),
                       "coverage": round(sum(r["inside"] for r in rs) / len(rs), 3)}
    last = max(by_week)
    misses = sorted(by_week[last], key=lambda r: -abs(r["error"]))[:8]
    return {**summ(rows), "by_week": {w: summ(v) for w, v in sorted(by_week.items())},
            "last_week": last, "biggest_misses": misses, "rows_last_week": by_week[last]}


def history_update(path: Path, week: int, at: str, tuned: dict, backtest: dict) -> list[dict]:
    """One entry per week: the settings in use and how accurate they were (for the trend)."""
    hist = json.loads(path.read_text()) if path.exists() else []
    hist = [h for h in hist if h["week"] != week]
    hist.append({"week": week, "at": at, "params": tuned["params"], "changed": tuned["changed"],
                 "games": backtest.get("games", 0), "mae": backtest.get("mae"), "coverage": backtest.get("coverage"),
                 "naive_mae": backtest.get("naive_mae")})
    hist.sort(key=lambda h: h["week"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hist, indent=1) + "\n")
    return hist


