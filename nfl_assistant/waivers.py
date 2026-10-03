"""Waiver targets ranked by what they'd add to *my* team (not Sleeper-wide trending adds).

Pool = the best available (unrostered) players at each position by rest-of-season projection.
Gain = my team value with the player minus without, over the remaining regular season, using
trades.Valuer with no free-agent floor (so it's measured against my actual roster) and the
roster limit (the weakest player is cut if needed). Kickers and defences replace my weakest
one at the position. Pure functions.
"""

from .projections import OFFENSE_STATUS_OUT

POOL_SIZE = {"QB": 10, "RB": 15, "WR": 15, "TE": 10, "K": 6, "DEF": 8}
SWAP_POSITIONS = ("K", "DEF")
UPGRADE_GAIN = 1.5    # pts/week: a real lineup upgrade
DEPTH_GAIN = 0.5      # pts/week: useful bye / injury cover; below this, depth only


def pool(proj: dict[str, dict], rostered: set[str], sizes: dict[str, int] | None = None) -> list[str]:
    """Best available players per position by rest-of-season points (long-term out excluded)."""
    sizes = sizes or POOL_SIZE
    out = []
    for pos, n in sizes.items():
        cands = [pid for pid, p in proj.items() if p["position"] == pos and pid not in rostered
                 and p.get("status") not in OFFENSE_STATUS_OUT and p["ros"] > 0]
        cands.sort(key=lambda pid: -proj[pid]["ros"])
        out += cands[:n]
    return out


def my_gain(valuer, mine: list[str], pid: str, proj: dict[str, dict], n_weeks: int) -> dict:
    """Points added to my team over the rest of the season by adding `pid` (and who goes)."""
    base = valuer.value(mine)["score"]
    pos = proj[pid]["position"]
    same = [p for p in mine if p in proj and proj[p]["position"] == pos]
    if pos in SWAP_POSITIONS and same:
        out = min(same, key=lambda p: proj[p]["ros"])
        after = valuer.value([p for p in mine if p != out] + [pid])
        dropped = [out]
    else:
        after = valuer.value(mine + [pid])
        dropped = after["dropped"]
    gain = round(after["score"] - base, 1)
    return {"gain": gain, "per_week": round(gain / n_weeks, 1) if n_weeks else 0.0,
            "drop": dropped, "fit": fit(gain / n_weeks if n_weeks else 0.0)}


def fit(per_week: float) -> str:
    return "upgrade" if per_week >= UPGRADE_GAIN else "depth" if per_week >= DEPTH_GAIN else "none"


def demand(likely_rivals: int) -> str:
    """Expected competition from how many rivals the player would clearly start for."""
    return "hot" if likely_rivals >= 2 else "warm" if likely_rivals == 1 else "quiet"
