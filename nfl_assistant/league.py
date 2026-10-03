"""League-wide views: weekly scores, all-play record and luck, power rankings, odds history.

Scores come only from Sleeper matchups (league scoring). Pure functions except the
small odds-history file helpers at the bottom.
"""

import json
from pathlib import Path
from statistics import mean, median, pstdev


def weekly_scores(matchups_by_week: dict[int, list[dict]], completed: list[int]) -> tuple[dict, dict]:
    """(roster_id -> [{week, pts, opp, opp_pts, result}], week -> league median score)."""
    teams: dict[int, list] = {}
    medians = {}
    for w in completed:
        entries = matchups_by_week.get(w, [])
        pts = {m["roster_id"]: round(float(m.get("points") or 0), 2) for m in entries}
        if pts:
            medians[w] = round(median(pts.values()), 2)
        by_match: dict = {}
        for m in entries:
            if m.get("matchup_id") is not None:
                by_match.setdefault(m["matchup_id"], []).append(m["roster_id"])
        opp = {}
        for ids in by_match.values():
            if len(ids) == 2:
                opp[ids[0]], opp[ids[1]] = ids[1], ids[0]
        for rid, p in pts.items():
            o = opp.get(rid)
            op = pts.get(o) if o is not None else None
            result = None if op is None else ("W" if p > op else "L" if p < op else "T")
            teams.setdefault(rid, []).append({"week": w, "pts": p, "opp": o, "opp_pts": op, "result": result})
    return teams, medians


def all_play(weekly: dict[int, list]) -> dict[int, dict]:
    """Record if every team played every other team each week, expected wins and luck.

    expected wins = all-play win share x games played; luck = actual wins - expected wins.
    """
    by_week: dict[int, dict] = {}
    for rid, games in weekly.items():
        for g in games:
            by_week.setdefault(g["week"], {})[rid] = g["pts"]
    out = {}
    for rid, games in weekly.items():
        w = l = t = 0
        for g in games:
            for other, p in by_week[g["week"]].items():
                if other == rid:
                    continue
                if g["pts"] > p:
                    w += 1
                elif g["pts"] < p:
                    l += 1
                else:
                    t += 1
        n = w + l + t
        pct = (w + 0.5 * t) / n if n else 0.0
        played = [g for g in games if g["result"]]
        actual = sum(1 for g in played if g["result"] == "W") + 0.5 * sum(1 for g in played if g["result"] == "T")
        expected = pct * len(played)
        out[rid] = {"w": w, "l": l, "t": t, "pct": round(pct, 3), "expected_wins": round(expected, 2),
                    "actual_wins": actual, "luck": round(actual - expected, 2)}
    return out


def _z(values: dict) -> dict:
    vals = list(values.values())
    sd = pstdev(vals) if len(vals) > 1 else 0
    m = mean(vals) if vals else 0
    return {k: (v - m) / sd if sd else 0.0 for k, v in values.items()}


def power_rankings(actual_ppw: dict[int, float], projected_ppw: dict[int, float],
                   efficiency: dict[int, float | None], weeks_played: int) -> tuple[list[dict], dict]:
    """Blend of points so far, projected strength and lineup efficiency.

    The weight on results so far grows as the season goes on: actual = 0.9 x n/(n+5),
    projected = 0.9 - actual, efficiency = 0.1 (n = weeks played).
    """
    ids = [r for r in actual_ppw if r in projected_ppw]
    w_act = 0.9 * weeks_played / (weeks_played + 5)
    w_proj = 0.9 - w_act
    za = _z({r: actual_ppw[r] for r in ids})
    zp = _z({r: projected_ppw[r] for r in ids})
    ze = _z({r: efficiency.get(r) or 0.0 for r in ids})
    rows = [{"roster_id": r, "score": round(w_act * za[r] + w_proj * zp[r] + 0.1 * ze[r], 3),
             "actual": actual_ppw[r], "projected": projected_ppw[r], "efficiency": efficiency.get(r)}
            for r in ids]
    rows.sort(key=lambda x: -x["score"])
    for i, row in enumerate(rows, 1):
        row["rank"] = i
    return rows, {"actual": round(w_act, 3), "projected": round(w_proj, 3), "efficiency": 0.1}


# --- playoff odds history (one entry per run, kept in data/) ------------------------
def update_odds_history(path: Path, at: str, week: int, odds: dict[int, float], keep: int = 60) -> list[dict]:
    """Append this run's odds (replacing an entry from the same day) and return the history."""
    hist = json.loads(path.read_text()) if path.exists() else []
    day = at[:10]
    hist = [h for h in hist if h["at"][:10] != day]
    hist.append({"at": at, "week": week, "odds": {str(k): round(v, 3) for k, v in odds.items()}})
    hist = hist[-keep:]
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(hist, indent=1) + "\n")
    return hist
