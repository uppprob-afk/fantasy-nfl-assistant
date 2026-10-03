"""Data for the in-browser Trade Lab and Planner (site/lab.js does the maths live).

Compact per-player weekly projections and variances, rosters, schedule and standings,
plus Python-computed team values so the browser can check it agrees with the pipeline.
Pure functions, no network.
"""

from .outlook import player_week
from .trades import DEPTH_COUNT, DEPTH_WEIGHT, LONG_TERM_OUT, SKILL, Valuer


def lab_players(proj: dict, weeks: list[int], names: dict[str, dict], owners: dict[str, int],
                actual_now: dict[str, float]) -> dict[str, dict]:
    """player_id -> compact record. w/v = projected points / variance per week (aligned with
    `weeks`; a bye or an already-played game is 0)."""
    out = {}
    for pid, p in proj.items():
        w, v = [], []
        for wk in weeks:
            m, var, todo = player_week(p, wk)
            w.append(round(m, 2) if todo else 0.0)
            v.append(round(var, 2) if todo else 0.0)
        info = names.get(pid, {})
        out[pid] = {
            "n": info.get("name", pid), "p": p["position"], "t": p["team"], "s": p.get("status"),
            "r": p["rate"], "sd": p["sd"], "se": p.get("se", 0.0), "c": p["confidence"], "ros": p["ros"],
            "w": w, "v": v, "b": p.get("byes", []), "o": owners.get(pid),
            "gt": p.get("games_this", 0), "gp": p.get("games_prior", 0),
            "ap": p.get("actual_ppg"), "ep": p.get("expected_ppg"),
            "a": actual_now.get(pid),   # points already scored this week (game played)
        }
    return out


def tradeable(rec: dict) -> bool:
    """Same rule as trades.tradeable, on the compact record."""
    return rec["p"] in SKILL and rec["s"] not in LONG_TERM_OUT and (rec["gt"] > 0 or rec["gp"] >= 4)


def build_lab_data(proj: dict, weeks: list[int], slots: list[str], rosters: list[dict], managers: dict,
                   names: dict[str, dict], standings: dict[int, dict], schedule: dict[int, list],
                   this_week: dict[int, dict], my_rid: int, playoff_teams: int, confidence: str,
                   repl: dict[str, float], roster_size: int, current_week: int) -> dict:
    owners = {pid: r["roster_id"] for r in rosters for pid in (r.get("players") or [])}
    actual_now = {}
    for t in this_week.values():
        actual_now.update(t.get("actual", {}))
    valuer = Valuer(proj, weeks, slots)
    return {
        "weeks": weeks, "current_week": current_week, "slots": slots, "my_roster_id": my_rid,
        "roster_size": roster_size, "playoff_teams": playoff_teams, "confidence": confidence,
        "depth_weight": DEPTH_WEIGHT, "depth_count": DEPTH_COUNT, "skill": list(SKILL),
        "long_term_out": sorted(LONG_TERM_OUT), "replacement": repl,
        "players": lab_players(proj, weeks, names, owners, actual_now),
        "rosters": {str(r["roster_id"]): {
            "players": [pid for pid in (r.get("players") or []) if pid in proj],
            "reserve": r.get("reserve") or [],
            "label": managers[r["roster_id"]]["label"], "team_name": managers[r["roster_id"]]["team_name"],
            "waiver_position": (r.get("settings") or {}).get("waiver_position"),
        } for r in rosters},
        "standings": {str(k): v for k, v in standings.items()},
        "schedule": {str(w): [list(g) for g in games] for w, games in schedule.items()},
        "this_week": {str(k): {"mean": v["mean"], "sd": v["sd"], "starters": v["starters"]}
                      for k, v in this_week.items()},
        # Python's own team values, so the browser can confirm its maths matches.
        "check_scores": {str(r["roster_id"]): valuer.value(r.get("players") or [])["score"] for r in rosters},
    }
