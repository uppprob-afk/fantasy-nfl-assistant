"""Player cards: the key metrics shown on each roster row and its detail panel.

Headline = last 3 weeks (actual, league scoring from Sleeper) vs next 3 weeks
(projected), plus a weekly log, next-3 matchups, usage and value. Pure functions.
"""

import math
from statistics import mean, median

EASY, TOUGH = 1.05, 0.95
STAT_KEYS = ("pct", "targets", "receptions", "carries", "attempts", "partial", "opp", "finish",
             "pass_yd", "pass_td", "ints", "rush_yd", "rush_td", "rec_yd", "rec_td", "fum",
             "tgt_share", "ay_share", "wopr", "car_share")


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
                    "pct": g.get("pct") if g else None,
                    "finish": g.get("finish") if g else None, "opp": g.get("opp") if g else None})
    return out


def avg_played(weeks: list[dict]) -> float | None:
    """Average over weeks the player actually played and has league-scored points for."""
    vals = [w["pts"] for w in weeks if w["pts"] is not None and not w["bye"] and w["played"]]
    return round(mean(vals), 1) if vals else None


def finish_tiers(n_start: int) -> dict:
    """Finish thresholds for a position: boom = top half of starters, start = a starter-level
    week, bust = outside twice the number of starters."""
    return {"boom": max(1, math.ceil(n_start / 2)), "start": n_start, "bust": 2 * n_start}


def consistency(log: list[dict], tiers: dict) -> dict:
    """Weekly floor / ceiling and how often the player delivered a starter-level week.

    Uses weeks the player played with league-scored (Sleeper) points; finishes are positional
    ranks among every NFL player that week."""
    played = [g for g in log if not g.get("bye") and g.get("pts") is not None and g.get("finish") is not None]
    if not played:
        return {"games": 0}
    pts = [g["pts"] for g in played]
    fin = [g["finish"] for g in played]
    return {"games": len(played), "ppg": round(mean(pts), 1), "median": round(median(pts), 1),
            "floor": round(min(pts), 1), "ceiling": round(max(pts), 1),
            "best_finish": min(fin), "avg_finish": round(mean(fin)),
            "boom": sum(f <= tiers["boom"] for f in fin), "start": sum(f <= tiers["start"] for f in fin),
            "bust": sum(f > tiers["bust"] for f in fin)}


def opportunity(log: list[dict], pos_td_rate: float | None) -> dict:
    """Share of team opportunity and efficiency over full games this season, plus whether the
    touchdowns look sustainable for the volume (vs the league-wide rate at the position)."""
    full = [g for g in log if not g.get("partial") and (g.get("targets") or g.get("carries") or g.get("attempts"))]
    if not full:
        return {"games": 0}
    avg = lambda k: (round(mean(v), 3) if (v := [g[k] for g in full if g.get(k) is not None]) else None)
    touches = sum((g.get("carries") or 0) + (g.get("receptions") or 0) for g in full)
    opps = sum((g.get("carries") or 0) + (g.get("targets") or 0) for g in full)
    yards = sum((g.get("rush_yd") or 0) + (g.get("rec_yd") or 0) for g in full)
    tds = sum((g.get("rush_td") or 0) + (g.get("rec_td") or 0) for g in full)
    exp_tds = round(opps * pos_td_rate, 1) if pos_td_rate else None
    note = None
    if exp_tds is not None and opps >= 15:
        if tds - exp_tds >= 2:
            note = "hot"     # more TDs than the volume usually produces
        elif exp_tds - tds >= 1.5:
            note = "due"     # fewer TDs than the volume usually produces
    return {"games": len(full), "tgt_share": avg("tgt_share"), "ay_share": avg("ay_share"), "wopr": avg("wopr"),
            "car_share": avg("car_share"), "touches_pg": round(touches / len(full), 1),
            "yds_per_touch": round(yards / touches, 1) if touches else None,
            "pass_yd_pg": round(mean(g.get("pass_yd") or 0 for g in full), 1),
            "tds": tds, "exp_tds": exp_tds, "td_note": note}


def schedule_ahead(p: dict) -> list[dict]:
    """Every remaining regular-season week plus the fantasy playoff weeks."""
    out = []
    for src, playoff in ((p.get("weekly") or {}, False), (p.get("playoff_weeks") or {}, True)):
        for w in sorted(src):
            x = src[w]
            out.append({"week": w, "playoff": playoff, "bye": bool(x.get("bye")),
                        "pts": round(x.get("pts", 0.0), 1), "opp": x.get("opp"), "home": x.get("home"),
                        "matchup": None if x.get("bye") else matchup_label(x.get("mult"))})
    return out


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
               flags: dict[str, str], starters: dict[str, int] | None = None) -> dict:
    """Everything the roster row + detail panel need for one player."""
    log = (p or {}).get("log", [])
    byes = team_bye_weeks(sched, (p or {}).get("team"))
    last = last_weeks(sleeper_pts, log, completed, byes)
    card = {"last3": last, "last3_avg": avg_played(last)}
    season_pts = [sleeper_pts[w] for w in completed if w in sleeper_pts]
    by_week = {g["week"]: g for g in log}
    card["log"] = [{"week": w, "pts": sleeper_pts.get(w), "bye": w in byes,
                    **({k: by_week[w].get(k) for k in STAT_KEYS} if w in by_week else {})}
                   for w in completed]
    pos = (p or {}).get("position")
    tiers = finish_tiers((starters or {}).get(pos, 24)) if pos else None
    card["tiers"] = tiers
    card["consistency"] = consistency(card["log"], tiers) if tiers else {"games": 0}
    card["season"] = {"pts": round(sum(season_pts), 1) if season_pts else None,
                      "games": sum(1 for w in completed if w in by_week or sleeper_pts.get(w))}
    if not p:
        card.update({"next3": [], "next3_avg": None, "trend": None, "usage": {"games": 0}, "value": None,
                     "opportunity": {"games": 0}, "schedule": []})
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
    card["opportunity"] = opportunity(log, p.get("pos_td_per_touch")) if pos in ("RB", "WR", "TE", "QB") else {"games": 0}
    card["schedule"] = schedule_ahead(p)
    rank, count = ranks.get(pid, (None, None))
    card["value"] = {"rate": p["rate"], "sd": p["sd"], "ros": p["ros"], "confidence": p["confidence"],
                     "vor": round(p["ros"] - repl.get(p["position"], 0.0) * n_weeks, 1),
                     "rank": rank, "rank_of": count, "byes": p["byes"], "flag": flags.get(pid),
                     "prior_ppg": p.get("prior_ppg"), "partial_weeks": p.get("partial_weeks", [])}
    return card
