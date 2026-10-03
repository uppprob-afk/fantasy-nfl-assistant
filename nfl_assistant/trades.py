"""Trade finder built on rest-of-season projections.

A team's value = the sum, over every remaining regular-season week, of its optimal
lineup's projected points (so byes and injuries are handled week by week), plus a
small credit for bench depth (injury insurance beyond what's known today).
A trade is suggested only if it raises both teams' values. Pure functions, no network.
"""

from itertools import combinations
from statistics import median

from .lineups import best_lineup, lineup_slots  # noqa: F401  (lineup_slots re-exported)

SKILL = ("QB", "RB", "WR", "TE")
LONG_TERM_OUT = {"IR", "PUP", "Sus", "NA", "DNR", "COV"}
DEPTH_WEIGHT = 0.1   # share of the best bench players' rest-of-season points credited
DEPTH_COUNT = 3


class Valuer:
    """Fast rest-of-season team values from per-player weekly projections."""

    def __init__(self, proj: dict[str, dict], weeks: list[int], slots: list[str]):
        self.weeks = weeks
        self.slots = slots
        self.position = {pid: p["position"] for pid, p in proj.items()}
        self.week_pts = {w: {pid: p["weekly"].get(w, {}).get("pts", 0.0) for pid, p in proj.items()}
                         for w in weeks}
        self.ros = {pid: p["ros"] for pid, p in proj.items()}

    def lineups(self, pids: list[str]) -> dict[int, tuple[float, list]]:
        known = [p for p in pids if p in self.position]
        return {w: best_lineup(known, self.position, self.week_pts[w], self.slots) for w in self.weeks}

    def value(self, pids: list[str]) -> dict:
        weekly = self.lineups(pids)
        lineup_total = sum(t for t, _ in weekly.values())
        used = {p for _, lu in weekly.values() for _, p in lu}
        # bench = players who'd start in fewer than half the remaining weeks
        starts = {p: sum(1 for _, lu in weekly.values() if any(q == p for _, q in lu)) for p in pids}
        bench = sorted((self.ros.get(p, 0.0) for p in pids
                        if self.position.get(p) in SKILL and starts.get(p, 0) < len(self.weeks) / 2),
                       reverse=True)
        depth = DEPTH_WEIGHT * sum(bench[:DEPTH_COUNT])
        return {"score": round(lineup_total + depth, 1), "lineup_total": round(lineup_total, 1),
                "weekly": weekly, "used": used}


def team_profile(pids: list[str], valuer: Valuer) -> dict:
    """Average weekly strength by position (from the optimal weekly lineups) and depth."""
    v = valuer.value(pids)
    n = max(len(valuer.weeks), 1)
    strength = {pos: 0.0 for pos in SKILL}
    strength["FLEX"] = 0.0
    for w, (_, lineup) in v["weekly"].items():
        for slot, pid in lineup:
            key = slot if slot in strength else ("FLEX" if slot not in ("K", "DEF") else None)
            if key:
                strength[key] += valuer.week_pts[w][pid] / n
    starters_now = {p for _, p in v["weekly"][valuer.weeks[0]][1]} if valuer.weeks else set()
    depth = {}
    for pos in SKILL:
        bench = sorted((valuer.ros[p] / n for p in pids
                        if p in valuer.position and valuer.position[p] == pos and p not in starters_now),
                       reverse=True)
        depth[pos] = round(bench[0], 2) if bench else 0.0
    return {"score": v["score"], "lineup_total": v["lineup_total"],
            "per_week": round(v["lineup_total"] / n, 2),
            "strength": {k: round(x, 2) for k, x in strength.items()}, "depth": depth,
            "weekly": {w: {"total": t, "lineup": lu} for w, (t, lu) in v["weekly"].items()}}


def league_profiles(rosters: list[dict], valuer: Valuer, need_margin: float = 1.0) -> dict[int, dict]:
    """Profiles for every team plus needs/surplus versus the league median (pts per week)."""
    slots = valuer.slots
    profiles = {r["roster_id"]: team_profile(r.get("players") or [], valuer) for r in rosters}
    rows = list(profiles.values())
    med = {k: median(p["strength"][k] for p in rows) for k in rows[0]["strength"]}
    per_slot = {pos: med[pos] / (slots.count(pos) or 1) for pos in SKILL}
    for p in profiles.values():
        p["vs_median"] = {k: round(p["strength"][k] - med[k], 2) for k in med}
        p["needs"] = sorted((k for k in SKILL if p["vs_median"][k] < -need_margin and slots.count(k)),
                            key=lambda k: p["vs_median"][k])
        p["surplus"] = [k for k in SKILL if p["depth"][k] >= per_slot[k] > 0]
        p["median"] = {k: round(x, 2) for k, x in med.items()}
    return profiles


def tradeable(pid: str, proj: dict) -> bool:
    p = proj.get(pid)
    return bool(p) and p["position"] in SKILL and p["status"] not in LONG_TERM_OUT \
        and (p["games_this"] > 0 or p["games_prior"] >= 4)


def find_trades(my_rid: int, rosters: list[dict], proj: dict, valuer: Valuer, profiles: dict,
                max_per_team: int = 3, min_gain: float = 5.0, max_total: int = 15,
                pool_size: int = 9) -> list[dict]:
    """1-for-1 and 2-for-1 (both directions) trades that raise both teams' values.

    Gains are rest-of-season projected points. Ranked by my gain, lopsided offers last;
    each player I'd receive appears once per partner. 2-player packages are built from
    each side's `pool_size` most valuable tradeable players to keep the search fast.
    """
    by_id = {r["roster_id"]: r.get("players") or [] for r in rosters}
    mine = by_id[my_rid]
    my_pool = sorted((p for p in mine if tradeable(p, proj)), key=lambda p: -proj[p]["ros"])
    my_base = profiles[my_rid]["score"]
    ideas = []
    for rid, theirs in by_id.items():
        if rid == my_rid:
            continue
        their_pool = sorted((p for p in theirs if tradeable(p, proj)), key=lambda p: -proj[p]["ros"])
        their_base = profiles[rid]["score"]
        shapes = ([((a,), (b,)) for a in my_pool for b in their_pool]
                  + [(pair, (b,)) for pair in combinations(my_pool[:pool_size], 2) for b in their_pool]
                  + [((a,), pair) for a in my_pool for pair in combinations(their_pool[:pool_size], 2)])
        found = []
        for give, get in shapes:
            me_new = valuer.value([p for p in mine if p not in give] + list(get))["score"]
            me_gain = round(me_new - my_base, 1)
            if me_gain < min_gain:
                continue
            them_new = valuer.value([p for p in theirs if p not in get] + list(give))["score"]
            them_gain = round(them_new - their_base, 1)
            if them_gain > 0:
                found.append({"roster_id": rid, "give": list(give), "get": list(get),
                              "my_gain": me_gain, "their_gain": them_gain})
        found.sort(key=lambda t: (_lopsided(t), -t["my_gain"], -t["their_gain"],
                                  len(t["give"]) + len(t["get"])))
        picked, seen = [], set()
        for t in found:
            if seen & set(t["get"]):
                continue
            seen |= set(t["get"])
            picked.append(t)
            if len(picked) == max_per_team:
                break
        ideas += picked
    ideas.sort(key=lambda t: (_lopsided(t), -t["my_gain"], -t["their_gain"]))
    return ideas[:max_total]


def _lopsided(trade: dict) -> bool:
    return trade["their_gain"] < 0.25 * trade["my_gain"]


def explain(trade: dict, proj: dict, profiles: dict, my_rid: int, names: dict, manager: str,
            n_weeks: int) -> dict:
    """Plain-English reasoning, a balance label and an overall confidence for a trade idea."""
    me, them = profiles[my_rid], profiles[trade["roster_id"]]

    def desc(pid):
        p = proj[pid]
        return f"{names[pid]} ({p['position']}, {p['rate']:.1f}/wk projected, {p['confidence']} confidence)"

    give_pos = {proj[p]["position"] for p in trade["give"]}
    get_pos = {proj[p]["position"] for p in trade["get"]}
    reasons = [f"You give {', '.join(desc(p) for p in trade['give'])} for "
               f"{', '.join(desc(p) for p in trade['get'])}."]
    for pos in sorted(get_pos):
        if pos in me["needs"]:
            reasons.append(f"Your {pos} starters project {abs(me['vs_median'][pos]):.1f} pts/week below the league median.")
    for pos in sorted(give_pos):
        if pos in them["needs"]:
            reasons.append(f"{manager}'s {pos} starters project {abs(them['vs_median'][pos]):.1f} pts/week below the league median.")
        if pos in me["surplus"]:
            reasons.append(f"You have {pos} depth to spare on your bench.")
    for pos in sorted(get_pos):
        if pos in them["surplus"]:
            reasons.append(f"{manager} has {pos} depth to spare.")
    byes = sorted({w for p in trade["get"] for w in proj[p]["byes"]})
    if byes:
        reasons.append(f"Incoming bye week(s): {', '.join(map(str, byes))}, already counted in the weekly lineups.")
    reasons.append(f"Rest of season ({n_weeks} weeks): you +{trade['my_gain']:.0f} pts "
                   f"(~{trade['my_gain'] / max(n_weeks, 1):.1f}/wk), {manager} +{trade['their_gain']:.0f} pts.")
    if len(trade["give"]) != len(trade["get"]):
        who = manager if len(trade["give"]) > len(trade["get"]) else "You"
        reasons.append(f"{who} would need to drop a bench player to make room.")

    ratio = trade["their_gain"] / trade["my_gain"] if trade["my_gain"] else 1
    balance = ("balanced" if ratio >= 0.6 else "favours you" if not _lopsided(trade)
               else "lopsided (tough sell)")
    levels = {"low": 0, "medium": 1, "high": 2}
    conf = min((proj[p]["confidence"] for p in trade["give"] + trade["get"]), key=levels.get)
    return {**trade, "manager": manager, "reasons": reasons, "balance": balance, "confidence": conf}


def pitches_for_buyers(buyers: list[dict], my_rid: int, rosters: list[dict], proj: dict,
                       profiles: dict) -> list[dict]:
    """For each motivated buyer, my non-starters at the position they just lost."""
    weeks = sorted(profiles[my_rid]["weekly"])
    starters_now = {p for _, p in profiles[my_rid]["weekly"][weeks[0]]["lineup"]} if weeks else set()
    mine = next(r.get("players") or [] for r in rosters if r["roster_id"] == my_rid)
    out = []
    for b in buyers:
        if b["roster_id"] == my_rid:
            continue
        options = sorted((p for p in mine if p not in starters_now and tradeable(p, proj)
                          and proj[p]["position"] == b["position"]), key=lambda p: -proj[p]["ros"])
        out.append({**b, "my_options": options})
    return out
