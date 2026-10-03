"""Second source for verifying points: nflverse weekly player stats.

We recompute each player's points from nflverse raw stats using the league's own
scoring_settings, then compare with Sleeper's players_points. Season totals that
differ by more than the tolerance are labelled "unverified" (a soft flag).
"""

import csv
import io
import re
import time
from pathlib import Path

import httpx

# Sleeper scoring key -> function(nflverse row) giving the stat count.
def _n(row, col):
    try:
        return float(row.get(col) or 0)
    except ValueError:
        return 0.0


STAT_MAP = {
    "pass_yd": lambda r: _n(r, "passing_yards"),
    "pass_td": lambda r: _n(r, "passing_tds"),
    "pass_int": lambda r: _n(r, "passing_interceptions"),
    "pass_2pt": lambda r: _n(r, "passing_2pt_conversions"),
    "rush_yd": lambda r: _n(r, "rushing_yards"),
    "rush_td": lambda r: _n(r, "rushing_tds"),
    "rush_2pt": lambda r: _n(r, "rushing_2pt_conversions"),
    "rec": lambda r: _n(r, "receptions"),
    "rec_yd": lambda r: _n(r, "receiving_yards"),
    "rec_td": lambda r: _n(r, "receiving_tds"),
    "rec_2pt": lambda r: _n(r, "receiving_2pt_conversions"),
    "fum_lost": lambda r: _n(r, "fumbles_lost_total") or (
        _n(r, "sack_fumbles_lost") + _n(r, "rushing_fumbles_lost") + _n(r, "receiving_fumbles_lost")),
    "st_td": lambda r: _n(r, "special_teams_tds"),
    "fum_rec_td": lambda r: _n(r, "fumble_recovery_tds"),
    # kicking
    "fgm_0_19": lambda r: _n(r, "fg_made_0_19"),
    "fgm_20_29": lambda r: _n(r, "fg_made_20_29"),
    "fgm_30_39": lambda r: _n(r, "fg_made_30_39"),
    "fgm_40_49": lambda r: _n(r, "fg_made_40_49"),
    "fgm_50_59": lambda r: _n(r, "fg_made_50_59"),
    "fgm_60p": lambda r: _n(r, "fg_made_60_"),
    "fgmiss": lambda r: _n(r, "fg_att") - _n(r, "fg_made"),
    "xpm": lambda r: _n(r, "pat_made"),
    "xpmiss": lambda r: _n(r, "pat_att") - _n(r, "pat_made"),
}


def download_weekly(url: str, cache_dir: Path, max_age_hours: float = 6) -> str:
    """Download the season's weekly CSV (cached; one polite request)."""
    cache = cache_dir / Path(url).name
    if cache.exists() and time.time() - cache.stat().st_mtime < max_age_hours * 3600:
        return cache.read_text(encoding="utf-8")
    for attempt in range(4):
        try:
            resp = httpx.get(url, follow_redirects=True, timeout=60)
            resp.raise_for_status()
            break
        except httpx.HTTPError:
            if attempt == 3:
                raise
            time.sleep(2 ** attempt)
    cache.parent.mkdir(parents=True, exist_ok=True)
    cache.write_text(resp.text, encoding="utf-8")
    return resp.text


def parse_rows(csv_text: str) -> list[dict]:
    return [r for r in csv.DictReader(io.StringIO(csv_text)) if r.get("season_type", "REG") == "REG"]


def compute_points(row: dict, scoring: dict) -> float:
    return round(sum(scoring.get(key, 0) * fn(row) for key, fn in STAT_MAP.items()), 2)


_SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")


def norm_name(name: str) -> str:
    name = re.sub(r"[^a-z ]", "", (name or "").lower().replace("-", " "))
    return " ".join(_SUFFIX.sub("", name).split())


def match_player(sleeper_player: dict, by_gsis: dict, by_name: dict) -> str | None:
    """Find the nflverse player_id for a Sleeper player (gsis_id first, then name+position)."""
    gsis = (sleeper_player.get("gsis_id") or "").strip()
    if gsis and gsis in by_gsis:
        return gsis
    key = (norm_name(sleeper_player.get("full_name") or ""), sleeper_player.get("position"))
    candidates = by_name.get(key, [])
    if len(candidates) > 1:
        candidates = [c for c in candidates if c[1] == sleeper_player.get("team")] or candidates
    return candidates[0][0] if len(set(c[0] for c in candidates)) == 1 else None


def index_rows(rows: list[dict]):
    """Build lookups: weekly rows by nflverse id, plus id/name indexes for matching."""
    weekly: dict[str, dict[int, dict]] = {}
    by_name: dict[tuple, list] = {}
    for r in rows:
        pid = r["player_id"]
        weekly.setdefault(pid, {})[int(r["week"])] = r
        key = (norm_name(r.get("player_display_name") or r.get("player_name")), r.get("position"))
        entry = (pid, r.get("team"))
        if entry not in by_name.setdefault(key, []):
            by_name[key].append(entry)
    return weekly, {pid: True for pid in weekly}, by_name


def crosscheck(player_ids: list[str], players: dict, sleeper_points: dict[str, dict[int, float]],
               completed_weeks: list[int], rows: list[dict], scoring: dict,
               tolerance: float = 1.0) -> dict[str, dict]:
    """Compare Sleeper season points with nflverse-recomputed points, week by week.

    Only weeks that are completed, in Sleeper's matchups for the player, and covered by
    the nflverse file are compared. A week is skipped (not yet published) when nflverse
    has no rows for the player's NFL team that week, e.g. a Monday night game the
    nightly nflverse update hasn't picked up yet. Returns player_id -> result dict with `status`:
    verified | unverified | not_checked (DEF / no match / no weeks to compare).
    """
    weekly, by_gsis, by_name = index_rows(rows)
    teams_by_week: dict[int, set] = {}
    for r in rows:
        teams_by_week.setdefault(int(r["week"]), set()).add(r.get("team"))
    results = {}
    for pid in player_ids:
        p = players.get(pid) or {}
        sp = sleeper_points.get(pid, {})
        weeks = [w for w in completed_weeks if w in sp and w in teams_by_week]
        res = {"status": "not_checked", "sleeper": None, "nflverse": None, "diff": None,
               "weeks": weeks, "played_weeks": [], "reason": None, "week_diffs": {},
               "pending_weeks": []}
        if p.get("position") == "DEF":
            res["reason"] = "Team defences aren't in nflverse player stats."
        elif not weeks:
            res["reason"] = "No completed weeks on a league roster to compare yet."
        else:
            nid = match_player(p, by_gsis, by_name)
            if not nid:
                res["reason"] = "Couldn't match this player in nflverse."
            else:
                team = p.get("team")
                pending = [w for w in weeks if w not in weekly[nid] and team not in teams_by_week[w]]
                weeks = [w for w in weeks if w not in pending]
                res["weeks"], res["pending_weeks"] = weeks, pending
                s_total = n_total = 0.0
                for w in weeks:
                    row = weekly[nid].get(w)
                    n = compute_points(row, scoring) if row else 0.0
                    s_total += sp[w]
                    n_total += n
                    if abs(sp[w] - n) > 0.05:
                        res["week_diffs"][str(w)] = {"sleeper": sp[w], "nflverse": n}
                res["played_weeks"] = sorted(w for w in weekly[nid] if w in completed_weeks)
                res["sleeper"], res["nflverse"] = round(s_total, 2), round(n_total, 2)
                res["diff"] = round(s_total - n_total, 2)
                res["status"] = "verified" if abs(res["diff"]) <= tolerance else "unverified"
                if res["status"] == "unverified":
                    res["reason"] = (f"Sleeper has {res['sleeper']} pts, nflverse stats give "
                                     f"{res['nflverse']} (difference {res['diff']:+}).")
        results[pid] = res
    return results
