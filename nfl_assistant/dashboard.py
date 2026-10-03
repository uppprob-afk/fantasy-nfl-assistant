"""Stage 1 calculations: settings check, season points, standings, rosters, matchups.

All functions here are pure (no network) so they can be tested with sample data.
Fantasy points come ONLY from matchups `players_points` (league scoring).
"""

from .players import is_ir_eligible, player_brief

WAIVER_TYPES = {0: "rolling", 1: "reverse standings", 2: "faab"}


# --- settings check ---------------------------------------------------------
def check_settings(league: dict, expected: dict) -> list[str]:
    """Compare real league settings with config.yaml's expected_settings."""
    s = league.get("settings", {})
    positions = league.get("roster_positions", [])
    actual = {
        "num_teams": league.get("total_rosters") or s.get("num_teams"),
        "qb_slots": positions.count("QB") + positions.count("SUPER_FLEX"),
        "ppr": league.get("scoring_settings", {}).get("rec", 0),
        "waiver_type": WAIVER_TYPES.get(s.get("waiver_type"), str(s.get("waiver_type"))),
        "faab_budget": s.get("waiver_budget"),
    }
    warnings = []
    for key, want in expected.items():
        got = actual.get(key)
        if got is not None and got != want:
            warnings.append(f"Setting '{key}' is {got!r} on Sleeper, but config.yaml expects {want!r}.")
    return warnings


# --- managers ---------------------------------------------------------------
def manager_lookup(users: list[dict], rosters: list[dict], nicknames: dict) -> dict[int, dict]:
    """roster_id -> {username, nickname, team_name, label}."""
    by_user = {u["user_id"]: u for u in users}
    out = {}
    for r in rosters:
        u = by_user.get(r.get("owner_id"), {})
        username = u.get("display_name") or "Unowned"
        nick = nicknames.get(username)
        team = (u.get("metadata") or {}).get("team_name") or username
        out[r["roster_id"]] = {
            "roster_id": r["roster_id"],
            "username": username,
            "nickname": nick,
            "label": f"{nick} ({username})" if nick else username,
            "team_name": team.strip(),
            "user_id": r.get("owner_id"),
        }
    return out


# --- points -----------------------------------------------------------------
def weekly_points(matchups_by_week: dict[int, list[dict]]) -> dict[str, dict[int, float]]:
    """player_id -> {week: points}, from every roster's players_points."""
    out: dict[str, dict[int, float]] = {}
    for week, entries in matchups_by_week.items():
        for m in entries:
            for pid, pts in (m.get("players_points") or {}).items():
                out.setdefault(pid, {})[int(week)] = float(pts or 0)
    return out


def season_summary(weeks: dict[int, float], completed_weeks: list[int],
                   played_weeks: set[int] = frozenset()) -> dict:
    """Total, games and average over completed weeks.

    A game counts if the player scored non-zero points that week, or a second
    source (nflverse) says they played. Weeks the player wasn't on any roster
    have no league-scored points and are not counted.
    """
    pts = {w: weeks[w] for w in completed_weeks if w in weeks}
    games = {w for w, p in pts.items() if p != 0} | (set(pts) & set(played_weeks))
    total = round(sum(pts.values()), 2)
    return {
        "points": total,
        "games": len(games),
        "avg": round(total / len(games), 2) if games else 0.0,
        "weekly": {str(w): pts[w] for w in sorted(pts)},
    }


# --- standings --------------------------------------------------------------
def _pts(settings: dict, key: str) -> float:
    return round(settings.get(key, 0) + settings.get(f"{key}_decimal", 0) / 100, 2)


def standings(rosters: list[dict], managers: dict, budget: int) -> list[dict]:
    rows = []
    for r in rosters:
        s = r.get("settings", {})
        used = s.get("waiver_budget_used", 0)
        rows.append({
            **managers[r["roster_id"]],
            "wins": s.get("wins", 0), "losses": s.get("losses", 0), "ties": s.get("ties", 0),
            "points_for": _pts(s, "fpts"), "points_against": _pts(s, "fpts_against"),
            "waiver_position": s.get("waiver_position"),
            "faab_used": used, "faab_remaining": budget - used,
        })
    rows.sort(key=lambda x: (-x["wins"], -x["ties"], -x["points_for"]))
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows


# --- rosters ----------------------------------------------------------------
def roster_view(roster: dict, players: dict, points: dict, completed_weeks: list[int],
                roster_positions: list[str], ir_allowed: set[str], reserve_slots: int,
                played: dict[str, set[int]] | None = None) -> dict:
    """Starters (with slot), bench and IR for one roster, with season points."""
    played = played or {}

    def enrich(pid):
        brief = player_brief(pid, players)
        brief.update(season_summary(points.get(pid, {}), completed_weeks, played.get(pid, set())))
        brief["ir_eligible"] = is_ir_eligible(players.get(pid), ir_allowed)
        return brief

    slots = [p for p in roster_positions if p not in ("BN", "IR", "TAXI")]
    starters_ids = roster.get("starters") or []
    reserve = roster.get("reserve") or []
    taxi = roster.get("taxi") or []
    starters = []
    for slot, pid in zip(slots, starters_ids):
        row = enrich(pid) if pid and pid != "0" else {"id": None, "name": "Empty", "position": slot}
        row["slot"] = slot
        starters.append(row)
    taken = set(starters_ids) | set(reserve) | set(taxi)
    bench = [enrich(pid) for pid in (roster.get("players") or []) if pid not in taken]
    bench.sort(key=lambda x: -x["avg"])
    ir = [enrich(pid) for pid in reserve]

    ir_open = max(reserve_slots - len(reserve), 0)
    notes = []
    for row in starters + bench:
        if row.get("id") and row["ir_eligible"]:
            if ir_open:
                notes.append(f"{row['name']} is designated IR and can move to your open IR slot.")
            else:
                notes.append(f"{row['name']} is IR-eligible, but your IR slot is full.")
    for row in ir:
        if not row["ir_eligible"]:
            notes.append(f"{row['name']} is in an IR slot but is now '{row['injury_status'] or 'healthy'}', "
                         "which this league doesn't allow on IR. Sleeper may lock your roster moves until fixed.")
    for row in starters:
        if row.get("id") and row.get("injury_status") in ("Out", "IR", "Doubtful", "Sus"):
            notes.append(f"Starter {row['name']} ({row['slot']}) is {row['injury_status']}; consider benching.")

    return {"roster_id": roster["roster_id"], "starters": starters, "bench": bench, "ir": ir,
            "ir_slots": reserve_slots, "ir_open": ir_open, "notes": notes}


# --- matchups ---------------------------------------------------------------
def matchup_pairs(entries: list[dict], managers: dict, my_roster_id: int) -> list[dict]:
    groups: dict = {}
    for m in entries:
        if m.get("matchup_id") is None:
            continue
        groups.setdefault(m["matchup_id"], []).append(m)
    out = []
    for mid, teams in sorted(groups.items()):
        teams.sort(key=lambda t: t["roster_id"] != my_roster_id)  # mine first
        sides = [{**managers[t["roster_id"]], "points": round(t.get("points") or 0, 2)} for t in teams]
        out.append({"matchup_id": mid, "is_mine": any(t["roster_id"] == my_roster_id for t in teams),
                    "teams": sides})
    out.sort(key=lambda x: not x["is_mine"])
    return out

