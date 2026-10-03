"""Player cards: the key metrics shown on each roster row and its detail panel.

Headline = last 3 weeks (actual, league scoring from Sleeper) vs next 3 weeks
(projected), plus a weekly log, next-3 matchups, usage and value. Pure functions.
"""

from statistics import mean

EASY, TOUGH = 1.05, 0.95


def matchup_label(mult: float | None) -> str:
    if mult is None:
        return "neutral"
    return "easy" if mult >= EASY else "tough" if mult <= TOUGH else "neutral"


def team_bye_weeks(sched: dict, team: str | None) -> set[int]:
    """Weeks (within the schedule) where a team has no game."""
    if not team:
        return set()
    return {w for w, teams in sched.items() if team not in teams}


def last_weeks(sleeper_pts: dict[int, float], log: list[dict], completed: list[int], byes: set[int],
               n: int = 3) -> list[dict]:
    """The last n completed weeks: Sleeper points (None if the player wasn't on a league
    roster that week), plus bye / partial-game / didn't-play flags from nflverse."""
    by_week = {g["week"]: g for g in log}
    out = []
    for w in completed[-n:]:
        g = by_week.get(w)
        out.append({"week": w, "pts": sleeper_pts.get(w), "bye": w in byes,
                    "played": g is not None, "partial": bool(g and g.get("partial")),
                    "pct": g.get("pct") if g else None})
    return out


def avg_played(weeks: list[dict]) -> float | None:
    """Average over weeks the player actually played and has league-scored points for."""
    vals = [w["pts"] for w in weeks if w["pts"] is not None and not w["bye"] and w["played"]]
    return round(mean(vals), 1) if vals else None


def next_weeks(p: dict, n: int = 3) -> list[dict]:
    """The next n weeks still to play, with projected points, range and matchup."""
    out = []
    for w in sorted(p["weekly"])[:n]:
        x = p["weekly"][w]
        if x.get("bye"):
            out.append({"week": w, "bye": True, "pts": 0.0})
            continue
        full = x["pts"] / x["avail"] if x.get("avail") else 0.0
        sd = p["sd"] * (full / p["rate"]) if p["rate"] else p["sd"]
        out.append({"week": w, "bye": False, "pts": round(x["pts"], 1),
                    "low": round(max(x["pts"] - sd, 0), 1), "high": round(x["pts"] + sd, 1),
                    "opp": x.get("opp"), "home": x.get("home"), "avail": x.get("avail", 1.0),
                    "matchup": matchup_label(x.get("mult")), "source": x.get("source")})
    return out


def usage(log: list[dict], recent: int = 3) -> dict:
    """Usage over the most recent full games (partial games skipped, unless that's all there is)."""
    full = [g for g in log if not g.get("partial")][-recent:]
    partial_only = False
    if not full:
        full, partial_only = log[-recent:], True
    if not full:
        return {"games": 0}
    pcts = [g["pct"] for g in full if g.get("pct") is not None]
    avg = lambda k: round(mean(g.get(k) or 0 for g in full), 1)
    return {"games": len(full), "partial_only": partial_only, "snap_pct": round(100 * mean(pcts)) if pcts else None,
            "targets": avg("targets"), "receptions": avg("receptions"),
            "carries": avg("carries"), "attempts": avg("attempts")}


def position_ranks(proj: dict) -> dict[str, tuple[int, int]]:
    """player_id -> (rank, count) by rest-of-season projection within the position."""
    by_pos: dict[str, list] = {}
    for pid, p in proj.items():
        by_pos.setdefault(p["position"], []).append((p["ros"], pid))
    out = {}
    for pos, rows in by_pos.items():
        rows.sort(reverse=True)
        for i, (_, pid) in enumerate(rows, 1):
            out[pid] = (i, len(rows))
    return out


def build_card(pid: str, p: dict | None, sleeper_pts: dict[int, float], completed: list[int],
               sched: dict, ranks: dict, repl: dict[str, float], n_weeks: int,
               flags: dict[str, str]) -> dict:
    """Everything the roster row + detail panel need for one player."""
    log = (p or {}).get("log", [])
    byes = team_bye_weeks(sched, (p or {}).get("team"))
    last = last_weeks(sleeper_pts, log, completed, byes)
    card = {"last3": last, "last3_avg": avg_played(last)}
    season_pts = [sleeper_pts[w] for w in completed if w in sleeper_pts]
    by_week = {g["week"]: g for g in log}
    card["log"] = [{"week": w, "pts": sleeper_pts.get(w), "bye": w in byes,
                    **({k: by_week[w].get(k) for k in ("pct", "targets", "receptions", "carries",
                                                         "attempts", "partial")} if w in by_week else {})}
                   for w in completed]
    card["season"] = {"pts": round(sum(season_pts), 1) if season_pts else None,
                      "games": sum(1 for w in completed if w in by_week or sleeper_pts.get(w))}
    if not p:
        card.update({"next3": [], "next3_avg": None, "trend": None, "usage": {"games": 0}, "value": None})
        return card
    nxt = next_weeks(p)
    games = [x["pts"] for x in nxt if not x["bye"]]
    card["next3"] = nxt
    card["next3_avg"] = round(mean(games), 1) if games else None
    a, b = card["last3_avg"], card["next3_avg"]
    card["trend"] = None if a is None or b is None or a == 0 else (
        "up" if b > a * 1.15 else "down" if b < a * 0.85 else "flat")
    u = usage(log)
    u["actual_ppg"], u["expected_ppg"] = p.get("actual_ppg"), p.get("expected_ppg")
    card["usage"] = u
    rank, count = ranks.get(pid, (None, None))
    card["value"] = {"rate": p["rate"], "sd": p["sd"], "ros": p["ros"], "confidence": p["confidence"],
                     "vor": round(p["ros"] - repl.get(p["position"], 0.0) * n_weeks, 1),
                     "rank": rank, "rank_of": count, "byes": p["byes"], "flag": flags.get(pid),
                     "prior_ppg": p.get("prior_ppg"), "partial_weeks": p.get("partial_weeks", [])}
    return card
