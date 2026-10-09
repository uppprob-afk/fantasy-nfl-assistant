"""Start/sit for the best chance to WIN this week (not just the most projected points).

Simulates the matchup thousands of times: each of my players' scores is drawn from his
learned, lopsided range (10th / 16th / 50th / 84th / 90th percentiles, so boom-or-bust
players really are swingier), players who already played are fixed at their actual points,
and the opponent's total is drawn from his projected mean / spread. All lineups are scored on
the same simulated weeks, so differences are the lineup, not luck. Starting from the
highest-projected lineup, it keeps any bench swap that raises the win chance. Pure functions.
"""

import random

from .lineups import FLEX_ELIGIBLE, best_lineup
from .outlook import player_week

SIMS = 3000
QUANT_P = (0.0, 0.10, 0.16, 0.50, 0.84, 0.90, 1.0)
MIN_GAIN = 0.004          # a swap must add 0.4 percentage points of win chance


def _knots(q: list[float]) -> list[float]:
    """Inverse-CDF knots from [p10, p16, p50, p84, p90], with tails extended."""
    p10, p16, p50, p84, p90 = q
    lo = max(0.0, p10 - 1.5 * max(p16 - p10, 0.5))
    hi = p90 + 3.0 * max(p90 - p84, 0.5)
    return [lo, p10, p16, p50, p84, p90, hi]


def draw(knots: list[float], u: float) -> float:
    for i in range(1, len(QUANT_P)):
        if u <= QUANT_P[i]:
            a, b = QUANT_P[i - 1], QUANT_P[i]
            return knots[i - 1] + (knots[i] - knots[i - 1]) * (u - a) / (b - a)
    return knots[-1]


def samples(p: dict | None, week: int, rng: random.Random, n: int) -> list[float] | None:
    """Simulated scores for one player this week (None = can't help: bye / out / no data)."""
    if not p:
        return None
    m, v, todo = player_week(p, week)
    if not todo or m <= 0:
        return None
    x = p["weekly"].get(week) or {}
    avail = x.get("avail", 1.0) or 0.0
    if x.get("q") and avail > 0:
        # the range already includes the chance he sits: scale back to a full game, then
        # apply the chance of sitting once
        k = _knots([v / avail for v in x["q"]])
        return [0.0 if avail < 1 and rng.random() > avail else draw(k, rng.random()) for _ in range(n)]
    sd = v ** 0.5
    return [max(0.0, rng.gauss(m, sd)) for _ in range(n)]


def plan(starters: list[str], roster: list[str], proj: dict, week: int, slots: list[str],
         actual: dict[str, float], opp_mean: float, opp_sd: float, seed: int = 7, n: int = SIMS) -> dict | None:
    """Best lineup for win chance, and the swaps from the lineup currently set in Sleeper."""
    rng = random.Random(seed)
    pos = {p: (proj.get(p) or {}).get("position") for p in roster}
    locked = {p for p in roster if proj.get(p) and not player_week(proj[p], week)[2]}   # already played
    sims = {}
    for p in roster:
        if p in locked:
            sims[p] = [float(actual.get(p, 0.0))] * n
        else:
            s = samples(proj.get(p), week, rng, n)
            if s:
                sims[p] = s
    opp = [rng.gauss(opp_mean, max(opp_sd, 1.0)) for _ in range(n)]
    means = {p: sum(v) / n for p, v in sims.items()}

    def totals(lineup: list[str]) -> list[float]:
        tot = [0.0] * n
        for p in lineup:
            if p in sims:
                tot = [a + b for a, b in zip(tot, sims[p])]
        return tot

    def share(tot: list[float]) -> float:
        return sum(1.0 if t > o else 0.5 if t == o else 0.0 for t, o in zip(tot, opp)) / n

    def win(lineup: list[str]) -> float:
        return share(totals(lineup))

    current = [p if p and p != "0" else None for p in starters][:len(slots)]
    current += [None] * (len(slots) - len(current))
    fixed = {i for i, p in enumerate(current) if p in locked}
    # start from the highest-projected lineup, keeping locked slots as they are
    free_slots = [s for i, s in enumerate(slots) if i not in fixed]
    pool = [p for p in sims if p not in locked and p in pos]
    _, best = best_lineup(pool, pos, means, free_slots)
    chosen = list(current)
    remaining = list(best)                    # (slot, pid) in the helper's order: match by slot name
    for i, slot in enumerate(slots):
        if i in fixed:
            continue
        j = next((k for k, (sl, _) in enumerate(remaining) if sl == slot), None)
        chosen[i] = remaining.pop(j)[1] if j is not None else None
    base_tot = totals(chosen)
    base = share(base_tot)
    for _ in range(4):                       # hill-climb: best single bench swap, repeat
        bench = [p for p in sims if p not in chosen and p not in locked]
        top = (0.0, None)
        for i, slot in enumerate(slots):
            if i in fixed:
                continue
            ok = FLEX_ELIGIBLE.get(slot, {slot})
            for b in bench:
                if pos.get(b) not in ok:
                    continue
                out = sims.get(chosen[i]) if chosen[i] else None
                tb = sims[b]
                trial_tot = [t - o + x for t, o, x in zip(base_tot, out, tb)] if out else [t + x for t, x in zip(base_tot, tb)]
                g = share(trial_tot) - base
                if g > top[0]:
                    top = (g, (i, b))
        if top[0] < MIN_GAIN:
            break
        i, b = top[1]
        chosen[i] = b
        base_tot = totals(chosen)
        base = share(base_tot)
    now = win(current)
    # describe it as who to start and who to sit (players may also move between slots);
    # each pair gets the win chance if you made just that swap
    starts = [p for p in chosen if p and p not in current]
    sits = [p for p in current if p and p not in chosen]
    changes = []
    for st in starts:
        options = [o for o in sits if pos.get(st) in FLEX_ELIGIBLE.get(slots[current.index(o)], {slots[current.index(o)]})]
        options.sort(key=lambda o: pos.get(o) != pos.get(st))
        o = options[0] if options else (sits[0] if sits else None)
        alone = None
        if o:
            sits.remove(o)
            trial = list(current)
            trial[current.index(o)] = st
            alone = round(win(trial), 3)
        changes.append({"in": st, "out": o, "in_pts": round(means.get(st, 0.0), 1),
                        "out_pts": round(means.get(o, 0.0), 1) if o else 0.0, "win_alone": alone})
    changes.sort(key=lambda c: -(c["win_alone"] or 0))
    my_mean = sum(means.get(p, 0.0) for p in chosen if p)
    return {"current_win": round(now, 3), "best_win": round(base, 3), "changes": changes,
            "lineup": [{"slot": s, "id": p} for s, p in zip(slots, chosen)],
            "mean_current": round(sum(means.get(p, 0.0) for p in current if p), 1), "mean_best": round(my_mean, 1),
            "style": "underdog" if my_mean < opp_mean else "favourite", "sims": n}
