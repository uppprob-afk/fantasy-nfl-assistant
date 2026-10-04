"""Self-assessment and learning for the projection model.

1. Backtest: for every completed week this season, rebuild each relevant player's projection
   using only games played before that week, and compare with what they scored
   (nflverse stats under league scoring, so every player is measured the same way).
2. Tune: try alternative settings on that track record and adopt them only when they're
   clearly better on enough games (otherwise keep the defaults). Per-position bias and
   range-width corrections are shrunk toward "no change" and capped.
3. Live ledger: the projections the dashboard actually showed (injuries included) are saved
   each run and scored once the games are played - the honest scorecard.

Pure functions except the small ledger / history file helpers at the bottom.
"""

import json
import math
from collections import defaultdict
from itertools import product
from pathlib import Path
from statistics import mean

from . import projections as pj

# Settings the tuner may try (the defaults are always included).
GRID = {
    "usage_blend": (0.3, 0.5, 0.7),
    "prior_weight": (0.3, 0.5, 0.75),
    "baseline_games": (1, 2, 4),
    "matchup": (0.25, 0.5, 0.75),      # applied to both vegas_damping and dvp_damping
}
MIN_GAMES_TO_TUNE = 300       # full games in the backtest before any setting can change
MIN_IMPROVEMENT = 0.015       # adopt new settings only if they cut the error by 1.5%+
SHRINK_GAMES = 150            # pseudo-games of "no correction" for bias / range-width
BIAS_CAP = (0.9, 1.1)
SD_CAP = (0.75, 1.4)
RELEVANT_MULTIPLE = 2         # backtest players ranked within 2x the league's starters at the position


# --- backtest -----------------------------------------------------------------------
def backtest_records(rows_prior: list[dict], rows_this: list[dict], snaps: list[dict], games: list[dict],
                     scoring: dict, season: str, starters: dict[str, int], weeks: list[int]) -> list[dict]:
    """One record per relevant player-game in `weeks` (completed weeks this season), holding
    the projection components as of kickoff and the actual result."""
    prior_season = str(int(season) - 1)
    logs = pj.game_logs(rows_prior + rows_this, snaps, scoring)
    dlogs = pj.def_logs(rows_prior + rows_this, games, scoring)
    sched = pj.schedule(games, season)
    usage = pj.usage_values(logs, prior_season)
    base_logs = {**logs, **{f"DEF:{t}": v for t, v in dlogs.items()}}
    bases = pj.position_baselines(base_logs, prior_season, starters)
    avg_imp = pj.average_implied(sched)
    everyone = {**logs, **{f"DEF:{t}": v for t, v in dlogs.items()}}
    out = []
    for w in weeks:
        before = {k: [g for g in v if g["season"] != season or g["week"] < w] for k, v in logs.items()}
        dvp = pj.defence_vs_position(before, sched, season)
        cands = []
        for key, plogs in everyone.items():
            g = next((x for x in plogs if x["season"] == season and x["week"] == w), None)
            if not g or g.get("position") not in pj.POSITIONS:
                continue
            pos = g["position"]
            prev = [x for x in plogs if x["season"] != season or x["week"] < w]
            if not prev:
                continue            # no history at all: can't judge the model fairly
            game = sched.get(w, {}).get(g["team"])
            if not game:
                continue
            c = pj.rate_components(prev, season, prior_season, pos, g["team"], bases.get(pos, {}), usage, 1)
            source, raw = pj.matchup_raw(pos, game, dvp, avg_imp)
            naive = c["actual"] if c["actual"] is not None else (c["r_prior"] if c["n_prior"] else None)
            cands.append({"week": w, "key": key, "pos": pos, "comp": c, "source": source, "raw": raw,
                          "actual": round(g["pts"], 2), "partial": bool(g.get("partial")), "naive": naive})
        # keep the fantasy-relevant players (by default-settings projection) at each position
        by_pos = defaultdict(list)
        for r in cands:
            by_pos[r["pos"]].append((pj.rate_from(r["comp"])["rate"], r))
        for pos, rows in by_pos.items():
            rows.sort(key=lambda x: -x[0])
            out += [r for _, r in rows[: RELEVANT_MULTIPLE * starters.get(pos, 12)]]
    return out


def project(rec: dict, params: dict | None) -> tuple[float, float]:
    """(projected points, spread) for a backtest record under `params`."""
    r = pj.rate_from(rec["comp"], params)
    return r["rate"] * pj.multiplier_from(rec["pos"], rec["source"], rec["raw"], params), r["sd"]


# --- scoring ------------------------------------------------------------------------
def evaluate(records: list[dict], params: dict | None = None) -> dict:
    """Accuracy on full games: mean absolute error, bias (projected - actual), share of
    results inside the projected range (+-1 sd; ~68% is well calibrated), vs a naive
    'season average so far' guess, plus per-position and per-week breakdowns."""
    full = [r for r in records if not r["partial"]]
    if not full:
        return {"games": 0}

    def stats(rows):
        errs, inside, naive = [], 0, []
        for r in rows:
            p, sd = project(r, params)
            errs.append(p - r["actual"])
            inside += abs(p - r["actual"]) <= sd
            if r["naive"] is not None:
                naive.append(abs(r["naive"] - r["actual"]))
        n = len(rows)
        return {"games": n, "mae": round(mean(abs(e) for e in errs), 2), "bias": round(mean(errs), 2),
                "coverage": round(inside / n, 3),
                "naive_mae": round(mean(naive), 2) if naive else None}

    out = stats(full)
    out["partial_games_excluded"] = len(records) - len(full)
    by_pos, by_week = defaultdict(list), defaultdict(list)
    for r in full:
        by_pos[r["pos"]].append(r)
        by_week[r["week"]].append(r)
    out["by_position"] = {k: stats(v) for k, v in sorted(by_pos.items())}
    out["by_week"] = {k: stats(v) for k, v in sorted(by_week.items())}
    return out


def _mae(records: list[dict], params: dict) -> float:
    return mean(abs(project(r, params)[0] - r["actual"]) for r in records)


# --- learning -----------------------------------------------------------------------
def tune(records: list[dict]) -> dict:
    """Pick settings from the track record. Returns {params, changed, reason, ...}."""
    full = [r for r in records if not r["partial"]]
    defaults = pj.params_or_default(None)
    result = {"params": defaults, "changed": [], "games": len(full)}
    if len(full) < MIN_GAMES_TO_TUNE:
        result["reason"] = (f"Not enough games yet to change anything ({len(full)} of {MIN_GAMES_TO_TUNE} "
                            f"needed). Using the starting settings.")
        return result
    base_mae = _mae(full, defaults)
    best, best_mae = defaults, base_mae
    for ub, pw, bg, md in product(*GRID.values()):
        cand = {**defaults, "usage_blend": ub, "prior_weight": pw, "baseline_games": bg,
                "vegas_damping": md, "dvp_damping": md}
        m = _mae(full, cand)
        if m < best_mae - 1e-9:
            best, best_mae = cand, m
    params = dict(defaults)
    if best_mae <= base_mae * (1 - MIN_IMPROVEMENT):
        params = {**best}
    # per-position bias and range width, shrunk toward 1 and capped
    bias, sd_scale = {}, {}
    by_pos = defaultdict(list)
    for r in full:
        by_pos[r["pos"]].append(r)
    for pos, rows in by_pos.items():
        n = len(rows)
        proj = [project(r, params) for r in rows]
        tot_p, tot_a = sum(p for p, _ in proj), sum(r["actual"] for r in rows)
        ratio = tot_a / tot_p if tot_p > 0 else 1.0
        bias[pos] = round(min(BIAS_CAP[1], max(BIAS_CAP[0], (n * ratio + SHRINK_GAMES) / (n + SHRINK_GAMES))), 3)
        z2 = mean(((r["actual"] - p * bias[pos]) / (sd * bias[pos])) ** 2 for r, (p, sd) in zip(rows, proj) if sd > 0)
        width = math.sqrt(z2)
        sd_scale[pos] = round(min(SD_CAP[1], max(SD_CAP[0], (n * width + SHRINK_GAMES) / (n + SHRINK_GAMES))), 3)
    params["bias"] = {**defaults["bias"], **bias}
    params["sd_scale"] = {**defaults["sd_scale"], **sd_scale}
    final_mae = _mae(full, params)
    result.update({"params": params, "default_mae": round(base_mae, 3), "tuned_mae": round(final_mae, 3),
                   "improvement": round(1 - final_mae / base_mae, 4) if base_mae else 0.0,
                   "changed": changes(defaults, params)})
    result["reason"] = ("Settings adjusted from this season's results." if result["changed"]
                        else "Starting settings are still the best fit.")
    return result


LABELS = {
    "usage_blend": "Weight on usage (targets/carries) vs actual points this season",
    "prior_weight": "Weight of a last-season game vs a this-season game",
    "baseline_games": "Pull toward the typical player at the position (pseudo-games)",
    "vegas_damping": "Strength of Vegas-line matchup adjustments",
    "dvp_damping": "Strength of opponent-defence matchup adjustments",
}


def changes(old: dict, new: dict) -> list[dict]:
    """Plain-English list of settings that differ."""
    out = []
    for k, label in LABELS.items():
        if abs(new[k] - old[k]) > 1e-9:
            out.append({"key": k, "label": label, "from": old[k], "to": new[k]})
    for pos, v in new["bias"].items():
        if abs(v - 1) >= 0.01:
            out.append({"key": f"bias.{pos}", "label": f"{pos} projections scaled", "from": 1.0, "to": v})
    for pos, v in new["sd_scale"].items():
        if abs(v - 1) >= 0.03:
            out.append({"key": f"sd.{pos}", "label": f"{pos} projected ranges widened/narrowed", "from": 1.0, "to": v})
    return out


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
                             "confidence": p["confidence"], "source": x.get("source")}
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


def learn(records: list[dict]) -> dict:
    """Tune, then check the learned settings on the latest week (held out of the tuning).
    They're used only if they don't do worse than the starting settings on that unseen week
    (allowing 1% noise); otherwise the starting settings stay."""
    weeks = sorted({r["week"] for r in records})
    tuned = tune(records)
    defaults = pj.params_or_default(None)
    tuned["validation"] = None
    if tuned["changed"] and len(weeks) >= 2:
        train = [r for r in records if r["week"] < weeks[-1]]
        test = [r for r in records if r["week"] == weeks[-1] and not r["partial"]]
        held = tune(train)
        if test:
            d_mae, t_mae = _mae(test, defaults), _mae(test, held["params"])
            tuned["validation"] = {"week": weeks[-1], "games": len(test), "default_mae": round(d_mae, 3),
                                   "learned_mae": round(t_mae, 3), "passed": t_mae <= d_mae * 1.01}
            if not tuned["validation"]["passed"]:
                tuned.update({"params": defaults, "changed": [],
                              "reason": f"Learned settings didn't hold up on week {weeks[-1]} (unseen), "
                                        f"so the starting settings stay."})
    return tuned
