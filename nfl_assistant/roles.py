"""Role-based projections: team volume x player's share x efficiency, and who inherits the
work when a teammate misses.

- Opportunity games: weeks a player's share was inflated because a teammate ahead of him
  in the role (higher normal share at the same position) didn't play or left early. They're
  left out of his normal role, so one fluky week doesn't make a backup a starter.
- Role rate: team carries / targets per game x his normal carry / target share x his points
  per carry / target (pulled toward the position average).
- Inheritance: learned from every game last season and this season where a regular missed
  time: what share of his vacated work went to the next man up (the rest is spread across
  the others in proportion to their normal shares).

Pure functions.
"""

from collections import defaultdict
from statistics import mean, median

SHARE_KEY = {"RB": "car_share", "WR": "tgt_share", "TE": "tgt_share"}
REGULAR = {"RB": 0.35, "WR": 0.15, "TE": 0.12}     # normal share that makes a player a regular
DEFAULT_TAKE = {"RB": 0.6, "WR": 0.35, "TE": 0.5}   # starting share of vacated work for the next man
DEFAULT_GROUP = {"RB": 0.8, "WR": 0.6, "TE": 0.6}  # ...and for everyone below him who's still there
TAKE_SHRINK = 15                                   # pseudo-events at the starting value
K_CARRIES, K_TARGETS = 40, 25                      # efficiency shrinkage (carries / targets)
VOLUME_SHRINK = 2                                  # pseudo-games of league-average team volume


def _groups(logs: dict[str, list[dict]]) -> dict[tuple, dict[str, list[dict]]]:
    """(season, team, position) -> player key -> games, for RB / WR / TE."""
    out = defaultdict(lambda: defaultdict(list))
    for key, games in logs.items():
        for g in games:
            if g.get("position") in SHARE_KEY and g.get("team"):
                out[(g["season"], g["team"], g["position"])][key].append(g)
    return out


def _median_share(games: list[dict], sk: str) -> float:
    vals = [g.get(sk) or 0.0 for g in games if not g.get("partial")]
    return median(vals) if vals else 0.0


def mark_opportunity(logs: dict[str, list[dict]]) -> None:
    """Set g["opp_game"] on every RB / WR / TE game: True when a teammate with a higher normal
    share at the position (and 2+ full games that season) sat or left early that week."""
    for games in logs.values():
        for g in games:
            g["opp_game"] = False
    for (season, team, pos), players in _groups(logs).items():
        sk = SHARE_KEY[pos]
        med = {k: _median_share(v, sk) for k, v in players.items()}
        regular = {k for k, v in players.items() if sum(not g.get("partial") for g in v) >= 2}
        weeks = {k: {g["week"]: g for g in v} for k, v in players.items()}
        for k, games in players.items():
            ahead = [a for a in regular if a != k and med[a] > med[k]]
            for g in games:
                for a in ahead:
                    ga = weeks[a].get(g["week"])
                    if ga is None or ga.get("partial"):
                        g["opp_game"] = True
                        break


def team_volume(logs: dict[str, list[dict]], season: str, before_week: int | None = None) -> dict[str, dict]:
    """team -> average carries and targets per game this season (shrunk toward the league)."""
    tot = defaultdict(lambda: defaultdict(lambda: [0.0, 0.0]))
    for games in logs.values():
        for g in games:
            if g["season"] != season or not g.get("team") or (before_week and g["week"] >= before_week):
                continue
            t = tot[g["team"]][g["week"]]
            t[0] += g.get("carries") or 0
            t[1] += g.get("targets") or 0
    per = {team: (mean(c for c, _ in w.values()), mean(t for _, t in w.values()), len(w)) for team, w in tot.items()}
    if not per:
        return {}
    lc, lt = mean(v[0] for v in per.values()), mean(v[1] for v in per.values())
    k = VOLUME_SHRINK
    return {team: {"carries": (c * n + lc * k) / (n + k), "targets": (t * n + lt * k) / (n + k), "games": n}
            for team, (c, t, n) in per.items()}


def role_components(games: list[dict], season: str, position: str, team: str | None,
                    volume: dict[str, dict], usage: dict) -> dict | None:
    """Normal-role shares, efficiency and the resulting points per game (None if no role data)."""
    if position not in SHARE_KEY or not team or team not in volume:
        return None
    this = [g for g in games if g["season"] == season and not g.get("partial") and not g.get("opp_game")]
    if not this:
        return None
    u = usage.get(position) or {}
    carries = sum(g.get("carries") or 0 for g in this)
    targets = sum(g.get("targets") or 0 for g in this)
    rush = sum((g.get("parts") or {}).get("rush", 0.0) for g in this)
    rec = sum((g.get("parts") or {}).get("rec", 0.0) for g in this)
    e_car = (rush + K_CARRIES * u.get("per_carry", 0.0)) / (carries + K_CARRIES)
    e_tgt = (rec + K_TARGETS * u.get("per_target", 0.0)) / (targets + K_TARGETS)
    s_car = mean(g.get("car_share") or 0.0 for g in this)
    s_tgt = mean(g.get("tgt_share") or 0.0 for g in this)
    v = volume[team]
    return {"car_share": round(s_car, 4), "tgt_share": round(s_tgt, 4), "e_car": round(e_car, 4),
            "e_tgt": round(e_tgt, 4), "carries": round(v["carries"], 2), "targets": round(v["targets"], 2),
            "n": len(this), "rate": round(v["carries"] * s_car * e_car + v["targets"] * s_tgt * e_tgt, 3)}


def learn_take(logs: dict[str, list[dict]]) -> dict[str, dict]:
    """Per position: share of a missing regular's work that went to the next man up."""
    acc, grp = defaultdict(list), defaultdict(list)
    for (season, team, pos), players in _groups(logs).items():
        sk = SHARE_KEY[pos]
        med = {k: _median_share(v, sk) for k, v in players.items()}
        full = {k: sum(not g.get("partial") for g in v) for k, v in players.items()}
        weeks = {k: {g["week"]: g for g in v} for k, v in players.items()}
        team_weeks = {w for v in weeks.values() for w in v}
        for a in players:
            if full[a] < 2 or med[a] < REGULAR[pos]:
                continue
            for w in team_weeks:
                ga = weeks[a].get(w)
                if ga is not None and not ga.get("partial"):
                    continue
                vacated = med[a] - ((ga.get(sk) or 0.0) if ga else 0.0)
                rec = [k for k in players if k != a and w in weeks[k] and full[k] >= 2 and med[k] < med[a]]
                if vacated <= 0.05 or not rec:
                    continue
                nxt = max(rec, key=lambda k: med[k])
                gain = (weeks[nxt][w].get(sk) or 0.0) - med[nxt]
                acc[pos].append(max(0.0, min(1.0, gain / vacated)))
                total = sum((weeks[k][w].get(sk) or 0.0) - med[k] for k in rec)
                grp[pos].append(max(0.0, min(1.0, total / vacated)))
    out = {}
    for pos, start in DEFAULT_TAKE.items():
        vals, gv = acc.get(pos, []), grp.get(pos, [])
        n = len(vals)
        take = (sum(vals) + TAKE_SHRINK * start) / (n + TAKE_SHRINK)
        group = (sum(gv) + TAKE_SHRINK * DEFAULT_GROUP[pos]) / (n + TAKE_SHRINK)
        out[pos] = {"take": round(take, 3), "group": round(max(group, take), 3), "events": n}
    return out


def redistribute(group: list[dict], vacated_from: dict, take: float, group_take: float) -> dict[str, tuple[float, float]]:
    """Extra (carry share, target share) per teammate when `vacated_from` (availability `avail`)
    misses part of a game. Work only flows down: to teammates with a smaller normal share. The
    next man gets `take` of it, the others below share `group_take - take` in proportion to
    their normal shares; the rest goes to players outside the group (call-ups, other positions)."""
    out = {}
    miss = 1 - vacated_from["avail"]
    key = "car_share" if vacated_from["pos"] == "RB" else "tgt_share"
    rec = [p for p in group if p["id"] != vacated_from["id"] and p["avail"] >= 0.5 and p[key] < vacated_from[key]]
    if miss <= 0 or not rec:
        return out
    rec.sort(key=lambda p: -p[key])
    rest = rec[1:]
    total = sum(p[key] for p in rest) or 1.0
    for kind in ("car_share", "tgt_share"):
        vac = miss * vacated_from[kind]
        for i, p in enumerate(rec):
            part = vac * (take if i == 0 else max(0.0, group_take - take) * p[key] / total)
            c, t = out.get(p["id"], (0.0, 0.0))
            out[p["id"]] = (c + part, t) if kind == "car_share" else (c, t + part)
    return out


QB_SHRINK = 60               # pseudo-games of "no effect"
QB_CAP = (0.7, 1.05)


def learn_qb_change(logs: dict[str, list[dict]]) -> dict[str, dict]:
    """RB / WR / TE points when the team's usual QB (most attempts that season, 2+ starts)
    didn't start, relative to the player's average with the usual QB. Per position, shrunk
    toward no effect and capped."""
    starts = defaultdict(dict)                    # (season, team) -> week -> starting QB
    att = defaultdict(lambda: defaultdict(float))
    for key, games in logs.items():
        for g in games:
            if g.get("position") == "QB" and g.get("team"):
                a = g.get("attempts") or 0
                att[(g["season"], g["team"])][key] += a
                cur = starts[(g["season"], g["team"])].get(g["week"])
                if a >= 10 and (cur is None or a > cur[1]):
                    starts[(g["season"], g["team"])][g["week"]] = (key, a)
    primary = {}
    for st, a in att.items():
        top = max(a, key=a.get)
        if sum(1 for k, _ in starts[st].values() if k == top) >= 2:
            primary[st] = top
    acc = defaultdict(lambda: [0.0, 0.0, 0])
    for key, games in logs.items():
        by_st = defaultdict(list)
        for g in games:
            if g.get("position") in ("RB", "WR", "TE") and not g.get("partial") and g.get("team"):
                by_st[(g["season"], g["team"])].append(g)
        for st, gs in by_st.items():
            if st not in primary:
                continue
            usual = [g for g in gs if (starts[st].get(g["week"]) or (None,))[0] == primary[st]]
            other = [g for g in gs if g["week"] in starts[st] and starts[st][g["week"]][0] != primary[st]]
            if len(usual) < 3 or not other:
                continue
            normal = mean(g["pts"] for g in usual)
            if normal < 3:
                continue
            a = acc[gs[0]["position"]]
            a[0] += sum(g["pts"] for g in other); a[1] += normal * len(other); a[2] += len(other)
    out = {}
    for pos in ("RB", "WR", "TE"):
        act, exp, n = acc.get(pos, [0.0, 0.0, 0])
        ratio = act / exp if exp else 1.0
        out[pos] = {"factor": round(max(QB_CAP[0], min(QB_CAP[1], (n * ratio + QB_SHRINK) / (n + QB_SHRINK))), 3), "games": n}
    return out
