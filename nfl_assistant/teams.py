"""NFL team views: depth charts, how each position group produces vs the league, the
offensive environment, and each player's role (weekly share of team volume, job security).

Depth chart order comes from Sleeper (current); weekly usage from nflverse game logs (league
scoring). Pure functions.
"""

from collections import defaultdict
from statistics import mean, median

POSITIONS = ("QB", "RB", "WR", "TE", "K")
SHARE_KIND = {"QB": "snap", "RB": "carry", "WR": "target", "TE": "target", "K": None}
DEPTH_SHOWN = {"QB": 2, "RB": 4, "WR": 5, "TE": 3, "K": 1}
TREND = 0.07          # share change (recent vs season) that counts as rising / losing work
LIMITED_SNAPS = 0.7   # under 70% of his usual snap share this season = left early / limited


def team_week_totals(logs: dict[str, list[dict]], season: str) -> dict[tuple, dict]:
    """(team, week) -> pass attempts, carries, targets and fantasy points by position."""
    out = defaultdict(lambda: {"attempts": 0.0, "carries": 0.0, "targets": 0.0, "pts": defaultdict(float)})
    for games in logs.values():
        for g in games:
            if g["season"] != season or not g.get("team"):
                continue
            t = out[(g["team"], g["week"])]
            if g.get("position") == "QB":
                t["attempts"] += g.get("attempts") or 0
            t["carries"] += g.get("carries") or 0
            t["targets"] += g.get("targets") or 0
            if g.get("position") in POSITIONS:
                t["pts"][g["position"]] += g["pts"]
    return out


def _rank(values: dict[str, float], high_first: bool = True) -> dict[str, int]:
    order = sorted(values, key=lambda k: -values[k] if high_first else values[k])
    return {k: i + 1 for i, k in enumerate(order)}


def position_strength(totals: dict[tuple, dict], def_logs: dict[str, list[dict]], sched: dict,
                      season: str) -> dict:
    """Per position: each team's fantasy points per game produced (offence) and allowed
    (defence), with league ranks and the median. DEF = team defence points scored."""
    produced = defaultdict(lambda: defaultdict(list))
    allowed = defaultdict(lambda: defaultdict(list))
    for (team, week), t in totals.items():
        opp = (sched.get(week, {}).get(team) or {}).get("opp")
        for pos in POSITIONS:
            produced[pos][team].append(t["pts"].get(pos, 0.0))
            if opp:
                allowed[pos][opp].append(t["pts"].get(pos, 0.0))
    for team, games in def_logs.items():
        for g in games:
            if g["season"] == season:
                produced["DEF"][team].append(g["pts"])
    out = {}
    for pos in POSITIONS + ("DEF",):
        off = {t: round(mean(v), 1) for t, v in produced[pos].items() if v}
        dfn = {t: round(mean(v), 1) for t, v in allowed[pos].items() if v}
        out[pos] = {"ppg": off, "rank": _rank(off), "median": round(median(off.values()), 1) if off else None,
                    "allowed": dfn, "allowed_rank": _rank(dfn), "allowed_median": round(median(dfn.values()), 1) if dfn else None}
    return out


def offence(totals: dict[tuple, dict], games: list[dict], sched: dict, season: str, next_week: int) -> dict:
    """Per team: plays, pass attempts and carries per game, pass rate, points per game, and
    the Vegas implied total for the next game (when lines exist)."""
    vol = defaultdict(list)
    for (team, week), t in totals.items():
        vol[team].append(t)
    pts = defaultdict(list)
    for g in games:
        if g.get("season") != str(season) or g.get("game_type") != "REG" or (g.get("home_score") or "") == "":
            continue
        pts[g["home_team"]].append(float(g["home_score"]))
        pts[g["away_team"]].append(float(g["away_score"]))
    out = {}
    for team, rows in vol.items():
        att = mean(r["attempts"] for r in rows)
        car = mean(r["carries"] for r in rows)
        nxt = sched.get(next_week, {}).get(team) or {}
        out[team] = {"games": len(rows), "plays_pg": round(att + car, 1), "pass_pg": round(att, 1),
                     "rush_pg": round(car, 1), "pass_rate": round(att / (att + car), 3) if att + car else None,
                     "points_pg": round(mean(pts[team]), 1) if pts.get(team) else None,
                     "next_opp": nxt.get("opp"), "next_home": nxt.get("home"),
                     "implied_next": round(nxt["implied"], 1) if nxt.get("implied") else None}
    ranks = {k: _rank({t: v[k] for t, v in out.items() if v.get(k) is not None})
             for k in ("plays_pg", "points_pg", "pass_rate")}
    for team, v in out.items():
        v["ranks"] = {k: r.get(team) for k, r in ranks.items()}
    return out


def weekly_role(games: list[dict], season: str, position: str) -> list[dict]:
    """This season's games: share of team volume (carry share for RBs, target share for
    WR/TE, snaps for QBs), snap %, points, and the partial-game flag."""
    snaps = [g["pct"] for g in games if g["season"] == season and g.get("pct") is not None]
    usual = median(snaps) if len(snaps) >= 3 else None
    out = []
    for g in games:
        if g["season"] != season:
            continue
        kind = SHARE_KIND.get(position)
        share = g.get("car_share") if kind == "carry" else g.get("tgt_share") if kind == "target" else g.get("pct")
        out.append({"week": g["week"], "share": round(share, 3) if share is not None else None,
                    "tgt_share": g.get("tgt_share"), "snap": g.get("pct"), "pts": round(g["pts"], 1),
                    "partial": bool(g.get("partial")) or bool(usual and usual >= 0.3 and g.get("pct") is not None
                                                             and g["pct"] < LIMITED_SNAPS * usual)})
    return out


def opportunity_weeks(mine: list[dict], ahead: list[list[dict]]) -> set[int]:
    """Weeks where someone ahead on the depth chart left early or didn't play (so this
    player's share was inflated by opportunity, not role). Inputs are weekly_role rows."""
    played = {g["week"] for g in mine}
    out = set()
    for games in ahead:
        if not games:
            continue          # never played this season: not a regular ahead of him
        by_week = {g["week"]: g for g in games}
        for w in played:
            g = by_week.get(w)
            if g is None or g["partial"]:
                out.add(w)
    return out


def job_security(position: str, order: int | None, weeks: list[dict], opp_weeks: set[int],
                 starter_share: float | None) -> dict:
    """Label + reason from depth order, normal-role share level and trend."""
    if position == "K":
        return {"label": "Starter" if order == 1 else "Backup", "reason": "Team kicker." if order == 1 else "Not the kicker right now."}
    normal = [w for w in weeks if not w["partial"] and w["week"] not in opp_weeks and w["share"] is not None]
    if not normal:
        if order == 2 and position in ("QB", "RB", "TE"):
            return {"label": "One injury away", "reason": "#2 on the depth chart, no regular role yet."}
        if order and order >= 3:
            return {"label": "Depth", "reason": f"#{order} on the depth chart."}
        return {"label": "Unproven", "reason": "No regular-role games yet this season."}
    season = mean(w["share"] for w in normal)
    recent = mean(w["share"] for w in normal[-2:])
    pct = lambda x: f"{round(100 * x)}%"
    kind = {"carry": "of RB carries", "target": "of targets", "snap": "of snaps"}.get(SHARE_KIND[position], "")
    trend = recent - season
    if position == "QB":
        if order == 1 and season >= 0.9:
            return {"label": "Locked in", "reason": f"Starter, {pct(season)} {kind}."}
        if order == 1:
            return {"label": "Starter", "reason": f"Starter, {pct(season)} {kind}."}
        return {"label": "One injury away" if order == 2 else "Depth", "reason": f"Backup QB (#{order or '?'})."}
    lead, locked = (0.4, 0.6) if position == "RB" else (0.17, 0.24)
    if trend >= TREND and recent >= lead * 0.75:
        return {"label": "Rising", "reason": f"{pct(recent)} {kind} in the last 2 regular-role games vs {pct(season)} on the season."}
    if trend <= -TREND:
        return {"label": "Losing work", "reason": f"{pct(recent)} {kind} recently, down from {pct(season)}."}
    if season >= locked:
        return {"label": "Locked in", "reason": f"{pct(season)} {kind}, #{order or '?'} on the depth chart."}
    if season >= lead:
        return {"label": "Lead role", "reason": f"{pct(season)} {kind}."}
    if position == "RB" and order == 2 and starter_share and starter_share >= 0.5:
        return {"label": "One injury away", "reason": f"Backup to a back with {pct(starter_share)} of carries."}
    if season >= lead * 0.5:
        return {"label": "Committee", "reason": f"{pct(season)} {kind}: a shared role."}
    return {"label": "Depth", "reason": f"{pct(season)} {kind}."}


def build(players: dict, logs: dict[str, list[dict]], nflverse_id: dict[str, str], season: str,
          owners: dict[str, str], proj: dict[str, dict]) -> tuple[dict, dict]:
    """(teams -> position -> depth chart rows, player id -> role) for every NFL team.

    nflverse_id maps Sleeper id -> nflverse id; owners maps Sleeper id -> league team name."""
    by_team = defaultdict(lambda: defaultdict(list))
    for pid, p in players.items():
        pos, team = p.get("position"), p.get("team")
        if not team or pos not in POSITIONS:
            continue
        order = p.get("depth_chart_order")
        has_games = any(g["season"] == season for g in logs.get(nflverse_id.get(pid), []))
        if order is None and not has_games:
            continue
        # WRs are listed per slot (left / right / slot), so several share order 1: break ties
        # by projection
        by_team[team][pos].append((order or 99, -((proj.get(pid) or {}).get("rate") or 0.0), pid))
    depth, roles = {}, {}
    for team, groups in by_team.items():
        depth[team] = {}
        for pos, rows in groups.items():
            rows.sort()
            pids = [pid for _, _, pid in rows]
            games = {pid: [g for g in logs.get(nflverse_id.get(pid), []) if g["season"] == season] for pid in pids}
            wk = {pid: weekly_role(games[pid], season, pos) for pid in pids}
            starter_weeks = wk[pids[0]] if pids else []
            starter_normal = [w["share"] for w in starter_weeks if not w["partial"] and w["share"] is not None]
            starter_share = mean(starter_normal) if starter_normal else None
            out_rows = []
            for i, pid in enumerate(pids):
                p = players[pid]
                weeks = wk[pid]
                opp = opportunity_weeks(weeks, [wk[a] for a in pids[:i]]) if i else set()
                for w in weeks:
                    w["opportunity"] = w["week"] in opp
                order = p.get("depth_chart_order")
                sec = job_security(pos, order, weeks, opp, starter_share if i else None)
                normal = [w["share"] for w in weeks if w["share"] is not None and not w["partial"] and not w["opportunity"]]
                row = {"id": pid, "name": p.get("full_name") or pid, "order": order, "status": p.get("injury_status"),
                       "owner": owners.get(pid), "ppg": round(mean(w["pts"] for w in weeks if not w["partial"]), 1)
                       if any(not w["partial"] for w in weeks) else None,
                       "share": round(mean(normal), 3) if normal else None, "kind": SHARE_KIND.get(pos),
                       "proj": (proj.get(pid) or {}).get("rate"), "label": sec["label"], "reason": sec["reason"],
                       "contingency": (proj.get(pid) or {}).get("contingency")}
                out_rows.append(row)
                roles[pid] = {**row, "team": team, "pos": pos, "weeks": weeks,
                              "ahead": [players[a].get("full_name") for a in pids[:i]][-2:],
                              "behind": [players[b].get("full_name") for b in pids[i + 1:i + 3]]}
            depth[team][pos] = out_rows[: max(DEPTH_SHOWN.get(pos, 3), sum(1 for r in out_rows if r["order"]))][:6]
    return depth, roles


def opportunities(proj: dict[str, dict], owners: dict[str, str], min_gain: float = 2.5) -> list[dict]:
    """Players whose next game is boosted because a teammate is out (biggest boost first)."""
    out = []
    for pid, p in proj.items():
        nxt = next(((w, x) for w, x in sorted(p.get("weekly", {}).items()) if not x.get("bye")), None)
        if not nxt or not nxt[1].get("inherit"):
            continue
        w, x = nxt
        gain = sum(i["pts"] for i in x["inherit"])
        if gain < min_gain:
            continue
        out.append({"id": pid, "name": p.get("name", pid), "team": p["team"], "pos": p["position"], "week": w,
                    "from": [i["from"] for i in x["inherit"]], "gain": round(gain, 1), "pts": round(x["pts"], 1),
                    "normal": round(x["pts"] - gain, 1), "owner": owners.get(pid)})
    out.sort(key=lambda o: -o["gain"])
    return out
