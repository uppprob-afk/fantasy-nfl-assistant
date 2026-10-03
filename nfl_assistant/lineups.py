"""Optimal lineups from projections, week by week (byes and injuries included).

Shared by the trade finder, matchup projections and playoff simulations.
"""

FLEX_ELIGIBLE = {
    "FLEX": {"RB", "WR", "TE"},
    "WRRB_FLEX": {"RB", "WR"},
    "REC_FLEX": {"WR", "TE"},
    "SUPER_FLEX": {"QB", "RB", "WR", "TE"},
}


def lineup_slots(roster_positions: list[str]) -> list[str]:
    return [s for s in roster_positions if s not in ("BN", "IR", "TAXI")]


def best_lineup(pids: list[str], position: dict[str, str], pts: dict[str, float],
                slots: list[str]) -> tuple[float, list[tuple[str, str]]]:
    """Highest-scoring lineup for one week.

    Fill dedicated slots with the best player at that position, then flex slots with
    the best remaining eligible player. With nested flex eligibility this greedy order
    is optimal. Players projected at 0 (bye, injured) are only used if nobody else fits.
    """
    pool = sorted((p for p in pids if p in pts), key=lambda p: -pts[p])
    used, assigned = set(), []
    for slot in sorted(slots, key=lambda s: s in FLEX_ELIGIBLE):
        ok = FLEX_ELIGIBLE.get(slot, {slot})
        pick = next((p for p in pool if p not in used and position.get(p) in ok), None)
        if pick:
            used.add(pick)
            assigned.append((slot, pick))
    return round(sum(pts[p] for _, p in assigned), 2), assigned


def weekly_lineups(pids: list[str], proj: dict[str, dict], weeks: list[int],
                   slots: list[str]) -> dict[int, dict]:
    """week -> {total, lineup: [(slot, pid)], empty: [slots nobody can fill]}."""
    position = {p: proj[p]["position"] for p in pids if p in proj}
    out = {}
    for w in weeks:
        pts = {p: proj[p]["weekly"].get(w, {}).get("pts", 0.0) for p in position}
        total, lineup = best_lineup(list(position), position, pts, slots)
        filled = [s for s, p in lineup if pts[p] > 0]
        empty = list(slots)
        for s in filled:
            empty.remove(s)
        out[w] = {"total": total, "lineup": lineup, "empty": empty}
    return out
