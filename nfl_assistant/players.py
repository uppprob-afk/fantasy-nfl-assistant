"""Player helpers: display names, injury labels, IR eligibility."""

# Sleeper's injury designation -> the league setting that allows it on IR.
# "IR" itself is always allowed. Anything not listed here (e.g. PUP) is not allowed.
IR_SETTING_FOR_STATUS = {
    "Out": "reserve_allow_out",
    "Doubtful": "reserve_allow_doubtful",
    "Sus": "reserve_allow_sus",
    "COV": "reserve_allow_cov",
    "NA": "reserve_allow_na",
    "DNR": "reserve_allow_dnr",
}


def ir_allowed_statuses(league_settings: dict) -> set[str]:
    """Which injury designations this league lets you put on IR."""
    allowed = {"IR"}
    for status, setting in IR_SETTING_FOR_STATUS.items():
        if league_settings.get(setting):
            allowed.add(status)
    return allowed


def is_ir_eligible(player: dict | None, allowed: set[str]) -> bool:
    return bool(player) and (player.get("injury_status") or "") in allowed


def player_name(player: dict | None, player_id: str = "") -> str:
    if not player:
        return f"Unknown ({player_id})"
    if player.get("position") == "DEF":
        return f"{player.get('first_name', '')} {player.get('last_name', '')}".strip() or player_id
    return (player.get("full_name")
            or f"{player.get('first_name', '')} {player.get('last_name', '')}".strip()
            or player_id)


def find_player(name: str, players: dict) -> str | None:
    """Player id for a name typed in config.yaml (case/punctuation-insensitive).
    Prefers players currently on an NFL team, then the most relevant (search_rank)."""
    def norm(s):
        return "".join(c for c in (s or "").lower() if c.isalnum())
    want = norm(name)
    hits = [pid for pid, p in players.items() if norm(player_name(p, pid)) == want]
    hits.sort(key=lambda pid: (not players[pid].get("team"), players[pid].get("search_rank") or 10**9))
    return hits[0] if hits else None


def player_brief(player_id: str, players: dict) -> dict:
    """The small set of fields the site needs for a player."""
    p = players.get(player_id)
    return {
        "id": player_id,
        "name": player_name(p, player_id),
        "position": (p or {}).get("position") or "?",
        "team": (p or {}).get("team") or "FA",
        "injury_status": (p or {}).get("injury_status") or None,
        "injury_body_part": (p or {}).get("injury_body_part") or None,
    }


SNAPSHOT_FIELDS = ("full_name", "first_name", "last_name", "position", "team", "status",
                   "injury_status", "injury_body_part", "injury_notes", "depth_chart_order",
                   "depth_chart_position", "gsis_id", "search_rank", "years_exp")
FANTASY_POSITIONS = {"QB", "RB", "WR", "TE", "K", "DEF"}


def slim_players(players: dict, keep_ids: set[str] = frozenset()) -> dict:
    """Small version of players/nfl for snapshots: fantasy-relevant players on an NFL
    team, plus anyone in keep_ids (e.g. rostered players). Used to diff runs later."""
    out = {}
    for pid, p in players.items():
        if pid in keep_ids or (p.get("team") and p.get("position") in FANTASY_POSITIONS
                               and p.get("active", True)):
            out[pid] = {k: p.get(k) for k in SNAPSHOT_FIELDS if p.get(k) is not None}
    return out
