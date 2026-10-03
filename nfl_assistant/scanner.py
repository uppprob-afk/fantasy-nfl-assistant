"""Stage 3: injury and opportunity scanner.

Compares this run's player data and rosters against the previous run's snapshot and
reports only what changed: injury status, depth chart (starter gained/lost), NFL team,
and players newly available in the league. Pure functions, no network.
"""

from .players import is_ir_eligible, player_brief

SKILL = {"QB", "RB", "WR", "TE"}
# Rough order of severity for injury designations (None = healthy).
SEVERITY = {None: 0, "Questionable": 1, "Doubtful": 2, "Out": 3, "IR": 4, "PUP": 4,
            "Sus": 4, "NA": 4, "COV": 3, "DNR": 4}
MISSING_TIME = {"Doubtful", "Out", "IR", "PUP", "Sus", "NA", "COV", "DNR"}
RELEVANT_RANK = 300


def _status(p: dict | None) -> str | None:
    return (p or {}).get("injury_status") or None


def is_depth_starter(p: dict | None) -> bool:
    return bool(p) and p.get("depth_chart_order") == 1 and p.get("position") in SKILL


def relevant_ids(players: dict, rostered: set[str]) -> set[str]:
    """Players worth watching: rostered, top-2 on an NFL depth chart, or highly ranked."""
    out = set(rostered)
    for pid, p in players.items():
        if not p.get("team") or p.get("position") not in SKILL | {"K", "DEF"}:
            continue
        if (p.get("depth_chart_order") or 99) <= 2 or (p.get("search_rank") or 10**9) <= RELEVANT_RANK:
            out.add(pid)
    return out


def diff_players(prev: dict, curr: dict, watch: set[str]) -> list[dict]:
    """Changes between two player dicts for watched players."""
    changes = []
    for pid in sorted(watch):
        old, new = prev.get(pid), curr.get(pid)
        if old is None or new is None:
            continue  # brand-new or vanished ids: nothing to compare
        s_old, s_new = _status(old), _status(new)
        if s_old != s_new:
            worse = SEVERITY.get(s_new, 1) > SEVERITY.get(s_old, 1)
            changes.append({"id": pid, "kind": "injury", "old": s_old, "new": s_new,
                            "direction": "worse" if worse else "better"})
        if (old.get("team") or None) != (new.get("team") or None):
            changes.append({"id": pid, "kind": "team", "old": old.get("team"), "new": new.get("team")})
        if new.get("position") in SKILL and is_depth_starter(old) != is_depth_starter(new):
            changes.append({"id": pid, "kind": "depth", "old": old.get("depth_chart_order"),
                            "new": new.get("depth_chart_order"),
                            "direction": "promoted" if is_depth_starter(new) else "demoted"})
    return changes


def newly_available(prev_rosters: list[dict], curr_rosters: list[dict]) -> dict[str, int]:
    """player_id -> roster_id that dropped them, for players now on no league roster."""
    now = {pid for r in curr_rosters for pid in (r.get("players") or [])}
    out = {}
    for r in prev_rosters:
        for pid in r.get("players") or []:
            if pid not in now:
                out[pid] = r["roster_id"]
    return out


def backups(injured_id: str, players: dict, rostered: set[str]) -> list[str]:
    """Free agents directly behind an injured player on the NFL depth chart."""
    p = players.get(injured_id) or {}
    if not p.get("team") or not p.get("depth_chart_position"):
        return []
    order = p.get("depth_chart_order") or 1
    out = [pid for pid, q in players.items()
           if q.get("team") == p["team"] and q.get("depth_chart_position") == p["depth_chart_position"]
           and (q.get("depth_chart_order") or 99) == order + 1 and pid not in rostered
           and pid != injured_id]
    return out


def describe(change: dict, name: str) -> str:
    k, old, new = change["kind"], change.get("old"), change.get("new")
    if k == "injury":
        if new is None:
            return f"{name} is no longer on the injury report (was {old})."
        return f"{name} is now {new}" + (f" (was {old})." if old else ".")
    if k == "team":
        if not new:
            return f"{name} was released by {old}."
        return f"{name} moved from {old or 'free agency'} to {new}."
    if k == "depth":
        return (f"{name} is now the starter on the depth chart." if change["direction"] == "promoted"
                else f"{name} is no longer listed as the starter (now #{new or '?'}).")
    if k == "available":
        return f"{name} was dropped by {old} and is now available (likely on waivers first)."
    return name


def scan(prev_players: dict, curr_players: dict, prev_rosters: list[dict], curr_rosters: list[dict],
         my_roster_id: int, managers: dict, ir_allowed: set[str], ir_open: int,
         season: dict[str, dict]) -> dict:
    """Build the three scanner sections from two runs' data.

    season: player_id -> season summary ({points, games, avg}) for ranking free agents.
    """
    rostered = {pid for r in curr_rosters for pid in (r.get("players") or [])}
    owner = {pid: r["roster_id"] for r in curr_rosters for pid in (r.get("players") or [])}
    starters = {pid: r["roster_id"] for r in curr_rosters for pid in (r.get("starters") or []) if pid != "0"}
    watch = relevant_ids(curr_players, rostered) | relevant_ids(prev_players, set())
    changes = diff_players(prev_players, curr_players, watch)

    def item(change, **extra):
        brief = player_brief(change["id"], curr_players)
        brief.update(season.get(change["id"], {}))
        return {**brief, **change, "text": describe(change, brief["name"]), **extra}

    mine, others, free = [], [], {}
    buyers: dict[tuple, dict] = {}

    for c in changes:
        pid = c["id"]
        rid = owner.get(pid)
        if rid == my_roster_id:
            row = item(c)
            if c["kind"] == "injury" and c["direction"] == "worse":
                if is_ir_eligible(curr_players.get(pid), ir_allowed):
                    row["action"] = ("Eligible for IR: move them there to free a roster spot."
                                     if ir_open else "Eligible for IR, but your IR slot is full.")
                elif c["new"] in MISSING_TIME:
                    row["action"] = (f"{c['new']} isn't IR-eligible in this league. Bench them "
                                     "if they're in your lineup.")
            mine.append(row)
        elif rid is not None and pid in starters:
            row = item(c, manager=managers[rid]["label"], roster_id=rid)
            if c["kind"] == "injury" and c["direction"] == "worse" and c["new"] in MISSING_TIME:
                pos = row["position"]
                row["action"] = (f"Trade opening: {managers[rid]['label']} just lost their starting "
                                 f"{pos} and may need a replacement.")
                buyers[(rid, pos)] = {"roster_id": rid, "manager": managers[rid]["label"],
                                      "team_name": managers[rid]["team_name"], "position": pos,
                                      "player": row["name"], "status": c["new"]}
            others.append(row)

        # opportunities for free agents
        if rid is None and c["kind"] == "depth" and c["direction"] == "promoted":
            free.setdefault(pid, item(c, reason="Promoted to starter on the depth chart."))
        if c["kind"] == "injury" and c["direction"] == "worse" and c["new"] in MISSING_TIME \
                and is_depth_starter(curr_players.get(pid)):
            injured_name = player_brief(pid, curr_players)["name"]
            for b in backups(pid, curr_players, rostered):
                bc = {"id": b, "kind": "backup", "old": None, "new": None}
                row = item(bc, reason=f"Backup to {injured_name} ({c['new']}).")
                row["text"] = f"{row['name']} is next up behind {injured_name}, who is now {c['new']}."
                free.setdefault(b, row)

    for pid, rid in newly_available(prev_rosters, curr_rosters).items():
        if pid in rostered:
            continue
        c = {"id": pid, "kind": "available", "old": managers.get(rid, {}).get("label", "a team"), "new": None}
        row = item(c, reason="Just dropped in our league.")
        free.setdefault(pid, row)

    free_list = sorted(free.values(), key=lambda r: -(r.get("avg") or 0))
    return {"my_players": mine, "other_starters": others, "free_agents": free_list,
            "motivated_buyers": list(buyers.values())}


def news_items(result: dict, run_at: str) -> list[dict]:
    """Flatten a scan into log entries tagged with the run time and section."""
    out = []
    for section in ("my_players", "other_starters", "free_agents"):
        for row in result[section]:
            out.append({**row, "section": section, "seen": run_at})
    return out
