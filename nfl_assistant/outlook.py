"""Matchup projections, start/sit help, weekly optimal lineups and playoff odds.

Built on the shared projections (projections.py) and lineup builder (lineups.py).
Pure functions, no network. Randomness uses a seeded generator so the same data
always gives the same numbers.
"""

import math
import random
from collections import defaultdict

from .lineups import FLEX_ELIGIBLE, best_lineup

N_SIMS = 10_000


def phi(z: float) -> float:
    return 0.5 * (1 + math.erf(z / math.sqrt(2)))


def player_week(p: dict | None, week: int) -> tuple[float, float, bool]:
    """(mean, variance, still_to_play) for one player in one week.

    Spread scales with the projection (matchup and availability); a player who may
    sit (Questionable etc.) adds the variance of playing vs not playing.
    """
    if not p:
        return 0.0, 0.0, False
    wk = p["weekly"].get(week)
    if wk is None:
        return 0.0, 0.0, False          # game already played (or no game)
    if wk.get("bye") or wk["pts"] <= 0:
        return 0.0, 0.0, True
    avail = wk.get("avail", 1.0)
    full = wk["pts"] / avail if avail else 0.0
    sd = p["sd"] * (full / p["rate"]) if p["rate"] else p["sd"]
    var = avail * sd ** 2 + avail * (1 - avail) * full ** 2
    return wk["pts"], var, True


def team_week(starters: list[str], actual: dict[str, float], proj: dict, week: int) -> dict:
    """Projected score for a set lineup: actual points for players who've played, projections for the rest."""
    mean = var = 0.0
    done = live = 0.0
    rows = []
    for pid in starters:
        if not pid or pid == "0":
            rows.append({"id": None, "pts": 0.0, "status": "empty"})
            continue
        m, v, todo = player_week(proj.get(pid), week)
        if todo:
            mean += m
            var += v
            live += m
            rows.append({"id": pid, "pts": round(m, 1), "sd": round(math.sqrt(v), 1), "status": "projected"})
        else:
            a = float(actual.get(pid, 0.0))
            done += a
            rows.append({"id": pid, "pts": round(a, 1), "status": "played"})
    return {"mean": round(done + mean, 1), "sd": round(math.sqrt(var), 1), "played_pts": round(done, 1),
            "projected_pts": round(live, 1), "players": rows}


def win_probability(a: dict, b: dict) -> float:
    sd = math.sqrt(a["sd"] ** 2 + b["sd"] ** 2)
    if sd == 0:
        return 1.0 if a["mean"] > b["mean"] else 0.0 if a["mean"] < b["mean"] else 0.5
    return phi((a["mean"] - b["mean"]) / sd)


def matchup_confidence(starters: list[str], proj: dict, week: int) -> str:
    """Low if a big share of the projected points comes from low-confidence projections."""
    total = low = 0.0
    for pid in starters:
        p = proj.get(pid)
        m, _, todo = player_week(p, week)
        if todo:
            total += m
            if p["confidence"] == "low":
                low += m
    if total == 0:
        return "high"  # all games played
    share = low / total
    return "low" if share > 0.3 else "medium" if share > 0.1 or not any(
        (proj.get(pid) or {}).get("confidence") == "high" for pid in starters) else "high"


def start_sit(starters: list[str], roster: list[str], proj: dict, week: int, slots: list[str]) -> list[dict]:
    """For each of my starters still to play, the best eligible bench alternative.

    Uses the chance the bench player outscores the starter this week:
    'swap' >= 60%, 'close' 40-60%, 'keep' < 40%, or 'problem' (starter on a bye /
    not expected to play).
    """
    bench = [p for p in roster if p not in starters]
    out = []
    for slot, pid in zip(slots, starters):
        if not pid or pid == "0":
            continue
        sm, sv, s_todo = player_week(proj.get(pid), week)
        if not s_todo:
            continue  # locked: already played
        ok = FLEX_ELIGIBLE.get(slot, {slot})
        options = []
        for b in bench:
            bp = proj.get(b)
            if not bp or bp["position"] not in ok:
                continue
            bm, bv, b_todo = player_week(bp, week)
            if b_todo and bm > 0:
                options.append((bm, bv, b))
        wk = (proj.get(pid) or {}).get("weekly", {}).get(week, {})
        problem = wk.get("bye") or sm == 0
        if not options:
            if problem:
                out.append({"slot": slot, "starter": pid, "starter_pts": sm, "alt": None, "verdict": "problem",
                            "why": "On a bye or not expected to play, and no eligible bench player."})
            continue
        bm, bv, best = max(options)
        diff = bm - sm
        spread = math.sqrt(sv + bv)
        p_alt = phi(diff / spread) if spread else (1.0 if diff > 0 else 0.0)
        pct = f"{5 * round(20 * p_alt)}%"
        if problem:
            verdict, why = "problem", "Starter is on a bye or not expected to play."
        elif p_alt >= 0.6:
            verdict, why = "swap", f"The bench option outscores the starter about {pct} of the time."
        elif p_alt >= 0.4:
            verdict, why = "close", f"Coin flip: the bench option wins about {pct} of the time. Go with the latest news."
        else:
            verdict, why = "keep", f"The bench option outscores the starter only about {pct} of the time."
        out.append({"slot": slot, "starter": pid, "starter_pts": round(sm, 1), "starter_sd": round(math.sqrt(sv), 1),
                    "alt": best, "alt_pts": round(bm, 1), "alt_sd": round(math.sqrt(bv), 1),
                    "diff": round(diff, 1), "p_alt": round(p_alt, 3), "verdict": verdict, "why": why})
    order = {"problem": 0, "swap": 1, "close": 2, "keep": 3}
    out.sort(key=lambda r: order[r["verdict"]])
    return out


def optimal_week(roster: list[str], proj: dict, week: int, slots: list[str]) -> dict:
    """Best projected lineup for one week, with byes listed."""
    position = {p: proj[p]["position"] for p in roster if p in proj}
    pts = {p: proj[p]["weekly"].get(week, {}).get("pts", 0.0) for p in position}
    total, lineup = best_lineup(list(position), position, pts, slots)
    byes = [p for p in position if proj[p]["weekly"].get(week, {}).get("bye")]
    var = sum(player_week(proj[p], week)[1] for _, p in lineup)
    return {"total": round(total, 1), "sd": round(math.sqrt(var), 1),
            "lineup": [{"slot": s, "id": p, "pts": round(pts[p], 1),
                        "opp": proj[p]["weekly"].get(week, {}).get("opp"),
                        "home": proj[p]["weekly"].get(week, {}).get("home")} for s, p in lineup],
            "byes": byes}


# --- playoff odds ----------------------------------------------------------------
def team_strength_sd(roster: list[str], proj: dict, slots: list[str], week: int) -> float:
    """Uncertainty in a team's *true* weekly level (projection error, shared across weeks)."""
    lineup = optimal_week(roster, proj, week, slots)["lineup"]
    return math.sqrt(sum((proj[x["id"]].get("se") or 0) ** 2 for x in lineup))


def simulate(standings: dict[int, dict], schedule: dict[int, list[tuple[int, int]]],
             week_dist: dict[tuple[int, int], tuple[float, float]], strength_sd: dict[int, float],
             playoff_teams: int, n: int = N_SIMS, seed: int = 0) -> dict:
    """Monte Carlo the rest of the regular season.

    standings: roster_id -> {wins, losses, ties, pf}
    schedule:  week -> [(roster_a, roster_b)]
    week_dist: (roster_id, week) -> (mean, sd) projected score
    Ranking: wins (ties count half), then points for (Sleeper's default tiebreak).
    Returns per-team playoff counts and per-game conditional counts for my leverage.
    """
    rng = random.Random(seed)
    teams = list(standings)
    games = [(w, a, b) for w in sorted(schedule) for a, b in schedule[w]]
    made = defaultdict(int)
    seed1 = defaultdict(int)
    wins_total = defaultdict(float)
    # per game: counts of (made playoffs | a won) etc. for every team
    cond = {g: {"a_won": 0, "made_if_a": defaultdict(int), "made_if_b": defaultdict(int)} for g in games}
    for _ in range(n):
        bias = {t: rng.gauss(0, strength_sd.get(t, 0)) for t in teams}
        w = {t: standings[t]["wins"] + 0.5 * standings[t].get("ties", 0) for t in teams}
        pf = {t: standings[t]["pf"] for t in teams}
        results = []
        for g in games:
            wk, a, b = g
            ma, sa = week_dist[(a, wk)]
            mb, sb = week_dist[(b, wk)]
            sa_ = ma + bias[a] + rng.gauss(0, sa)
            sb_ = mb + bias[b] + rng.gauss(0, sb)
            pf[a] += sa_
            pf[b] += sb_
            a_won = sa_ > sb_
            w[a if a_won else b] += 1
            results.append(a_won)
        ranked = sorted(teams, key=lambda t: (-w[t], -pf[t]))
        top = set(ranked[:playoff_teams])
        seed1[ranked[0]] += 1
        for t in teams:
            wins_total[t] += w[t]
            if t in top:
                made[t] += 1
        for g, a_won in zip(games, results):
            c = cond[g]
            c["a_won"] += a_won
            bucket = c["made_if_a"] if a_won else c["made_if_b"]
            for t in top:
                bucket[t] += 1
    return {"n": n, "made": dict(made), "seed1": dict(seed1),
            "avg_wins": {t: wins_total[t] / n for t in teams}, "games": games, "cond": cond}


def conditional_odds(sim: dict, game: tuple, team: int) -> tuple[float | None, float | None]:
    """(odds for `team` if side A wins, if side B wins)."""
    c = sim["cond"][game]
    a_n, b_n = c["a_won"], sim["n"] - c["a_won"]
    return (c["made_if_a"].get(team, 0) / a_n if a_n else None,
            c["made_if_b"].get(team, 0) / b_n if b_n else None)


def key_games(sim: dict, team: int, limit: int = 4) -> list[dict]:
    """Remaining games whose result swings `team`'s playoff odds most:
    the top `limit` of my own games plus the top `limit` between other teams."""
    out = []
    for g in sim["games"]:
        if_a, if_b = conditional_odds(sim, g, team)
        if if_a is None or if_b is None:
            continue
        out.append({"week": g[0], "a": g[1], "b": g[2], "if_a": if_a, "if_b": if_b,
                    "swing": abs(if_a - if_b), "mine": team in (g[1], g[2])})
    out.sort(key=lambda x: -x["swing"])
    others = [g for g in out if not g["mine"] and g["swing"] >= 0.03]
    return [g for g in out if g["mine"]][:limit] + others[:limit]


def round_odds(p: float, confidence: str) -> str:
    """Display odds without false precision: nearest 5% when confidence is low/medium."""
    pct = 100 * p
    if pct < 1:
        return "<1%"
    if pct > 99:
        return ">99%"
    step = 5 if confidence in ("low", "medium") else 1
    r = int(step * round(pct / step))
    if r == 0:
        return f"<{step}%"
    if r == 100:
        return f">{100 - step}%"
    return f"{r}%"
