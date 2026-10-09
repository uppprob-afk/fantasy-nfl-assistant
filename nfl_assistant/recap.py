"""Weekly recap: what happened in the last completed week, for you and the league.

Uses Sleeper matchup points (league scoring), the projections the dashboard showed before
kickoff (projection ledger), pre-game matchup projections / win chances and power ranks
saved while each week was in progress (small history files), waiver claims, trades, roles
and the model's live scorecard. Pure functions except the history file helpers at the bottom.
"""

import json
from pathlib import Path

from . import lineups

BOOM_MIN = 8.0          # pts over projection that counts as a boom / under as a bust
ROLE_SWING = 0.15       # share change vs normal that counts as a role change


def _pairs(entries: list[dict]) -> list[tuple[dict, dict]]:
    by = {}
    for m in entries:
        if m.get("matchup_id") is not None:
            by.setdefault(m["matchup_id"], []).append(m)
    return [tuple(v) for v in by.values() if len(v) == 2]


def optimal_points(entry: dict, positions: dict[str, str], slots: list[str]) -> tuple[float, list]:
    """Best possible lineup from that week's roster with actual points."""
    pts = {p: float(v or 0) for p, v in (entry.get("players_points") or {}).items()}
    total, lineup = lineups.best_lineup(list(pts), positions, pts, slots)
    return round(total, 2), lineup


def build(week: int, matchups: list[dict], teams: dict[int, dict], my_rid: int, slots: list[str],
          positions: dict[str, str], names: dict[str, str], ledger: dict, pregame: dict, state: dict,
          odds_history: list[dict], waiver_log: list[dict], other_moves: list[dict], roles: dict,
          rostered: dict[str, int], statuses: dict[str, str | None], model_week: dict | None,
          model_changes: list[dict]) -> dict:
    """Recap for `week` (completed). teams = roster_id -> {team_name, label}."""
    name = lambda pid: names.get(pid, pid)
    pre = pregame.get(str(week)) or {}
    scores = {m["roster_id"]: round(float(m.get("points") or 0), 2) for m in matchups}
    ranked = sorted(scores, key=lambda r: -scores[r])
    rank = {r: 1 + sum(scores[o] > scores[r] for o in scores) for r in scores}
    n = len(scores)

    # --- every game
    games = []
    for a, b in _pairs(matchups):
        pa, pb = scores[a["roster_id"]], scores[b["roster_id"]]
        win, lose = (a, b) if pa >= pb else (b, a)
        wp = (pre.get(str(win["roster_id"])) or {}).get("win_prob")
        games.append({"winner": win["roster_id"], "loser": lose["roster_id"], "w_pts": scores[win["roster_id"]],
                      "l_pts": scores[lose["roster_id"]], "margin": round(abs(pa - pb), 2), "tie": pa == pb,
                      "winner_pregame": wp,
                      "w_proj": (pre.get(str(win["roster_id"])) or {}).get("mean"),
                      "l_proj": (pre.get(str(lose["roster_id"])) or {}).get("mean")})
    games.sort(key=lambda g: g["margin"])
    upsets = [g for g in games if g["winner_pregame"] is not None and g["winner_pregame"] < 0.5]
    wins = [g for g in games if not g["tie"]]
    highlights = {
        "top": {"rid": ranked[0], "pts": scores[ranked[0]]} if ranked else None,
        "low": {"rid": ranked[-1], "pts": scores[ranked[-1]]} if ranked else None,
        "closest": games[0] if games else None,
        "blowout": games[-1] if games else None,
        "upset": min(upsets, key=lambda g: g["winner_pregame"]) if upsets else None,
        "luckiest_win": max(wins, key=lambda g: rank[g["winner"]]) if wins else None,
        "unluckiest_loss": min(wins, key=lambda g: rank[g["loser"]]) if wins else None,
    }
    for k in ("luckiest_win", "unluckiest_loss"):
        g = highlights[k]
        if g:
            rid = g["winner"] if k == "luckiest_win" else g["loser"]
            highlights[k] = {**g, "rank": rank[rid], "beaten": n - rank[rid]}

    # --- power movers (power ranks saved during week W vs during week W+1)
    p0, p1 = (state.get(str(week)) or {}).get("power") or {}, (state.get(str(week + 1)) or {}).get("power") or {}
    movers = sorted(({"rid": int(r), "from": p0[r], "to": p1[r], "change": p0[r] - p1[r]} for r in p1 if r in p0 and p0[r] != p1[r]),
                    key=lambda x: -abs(x["change"]))[:4]

    # --- my week
    mine = next((m for m in matchups if m["roster_id"] == my_rid), None)
    my = None
    if mine:
        g = next((x for x in games if my_rid in (x["winner"], x["loser"])), None)
        opp = (g["loser"] if g and g["winner"] == my_rid else g["winner"]) if g else None
        won = bool(g and g["winner"] == my_rid and not g["tie"])
        calls = []
        for pid in [p for p in (mine.get("starters") or []) if p and p != "0"]:
            e = ledger.get(f"{pid}:{week}")
            act = float((mine.get("players_points") or {}).get(pid) or 0)
            if e:
                calls.append({"id": pid, "name": name(pid), "pos": positions.get(pid), "proj": e["pts"], "actual": round(act, 1),
                              "diff": round(act - e["pts"], 1)})
        calls.sort(key=lambda c: -c["diff"])
        opt, best = optimal_points(mine, positions, slots)
        started = set(mine.get("starters") or [])
        benched = [p for _, p in best if p not in started]
        pre_odds = next((h for h in reversed(odds_history) if h["week"] == week), None)
        post_odds = next((h for h in reversed(odds_history) if h["week"] == week + 1), None)
        mp = pre.get(str(my_rid)) or {}
        my = {"pts": scores.get(my_rid), "opp": opp, "opp_pts": scores.get(opp) if opp else None, "won": won,
              "tie": bool(g and g["tie"]), "margin": g["margin"] if g else None, "rank": rank.get(my_rid),
              "proj": mp.get("mean"), "win_prob": mp.get("win_prob"),
              "booms": [c for c in calls if c["diff"] > 0][:3], "busts": [c for c in reversed(calls) if c["diff"] < 0][:3],
              "optimal": opt, "left_on_bench": round(opt - (scores.get(my_rid) or 0), 2),
              "should_have_started": [{"id": p, "name": name(p), "pts": round(float((mine.get("players_points") or {}).get(p) or 0), 1)} for p in benched],
              "optimal_would_win": bool(opp and not won and opt > (scores.get(opp) or 0)),
              "odds_before": (pre_odds or {}).get("odds", {}).get(str(my_rid)),
              "odds_after": (post_odds or {}).get("odds", {}).get(str(my_rid))}

    # --- players league-wide: booms / busts vs pre-game projection (rostered players)
    rows = []
    for m in matchups:
        for pid, v in (m.get("players_points") or {}).items():
            e = ledger.get(f"{pid}:{week}")
            if e and e["pts"] >= 5:
                rows.append({"id": pid, "name": name(pid), "pos": positions.get(pid), "owner": m["roster_id"],
                             "proj": e["pts"], "actual": round(float(v or 0), 1), "diff": round(float(v or 0) - e["pts"], 1),
                             "started": pid in (m.get("starters") or [])})
    booms = sorted([r for r in rows if r["diff"] >= BOOM_MIN], key=lambda r: -r["diff"])[:6]
    busts = sorted([r for r in rows if r["diff"] <= -BOOM_MIN], key=lambda r: r["diff"])[:6]

    # --- role changes this week (rostered players)
    role_moves = []
    for pid, r in roles.items():
        if pid not in rostered:
            continue
        wk = next((w for w in r.get("weeks") or [] if w["week"] == week), None)
        if not wk or wk.get("share") is None or r.get("share") is None or wk.get("partial"):
            continue
        d = wk["share"] - r["share"]
        if abs(d) >= ROLE_SWING:
            role_moves.append({"id": pid, "name": r["name"], "team": r["team"], "pos": r["pos"], "owner": rostered[pid],
                               "share": wk["share"], "normal": r["share"], "kind": r.get("kind"),
                               "opportunity": bool(wk.get("opportunity")), "up": d > 0, "label": r.get("label")})
    role_moves.sort(key=lambda x: -abs(x["share"] - x["normal"]))

    # --- injuries that matter next week: players who started this week and now carry a designation
    starters = {p: m["roster_id"] for m in matchups for p in (m.get("starters") or []) if p and p != "0"}
    injuries = [{"id": p, "name": name(p), "pos": positions.get(p), "owner": rid, "status": statuses.get(p)}
                for p, rid in starters.items() if statuses.get(p) in ("Questionable", "Doubtful", "Out", "IR", "PUP", "Sus")]
    injuries.sort(key=lambda x: (x["owner"] != my_rid, x["status"] == "Questionable"))

    # --- waivers processed after this week, trades
    claims = [r for r in waiver_log if r.get("week") == week + 1]
    claims.sort(key=lambda r: -r["bid"])
    trades = [t for t in other_moves if t.get("type") == "trade" and t.get("week") in (week, week + 1)]

    return {"week": week, "my_roster_id": my_rid, "teams": {str(k): v for k, v in teams.items()},
            "scores": {str(k): v for k, v in scores.items()}, "ranks": {str(k): v for k, v in rank.items()},
            "games": games, "highlights": highlights, "movers": movers, "mine": my,
            "booms": booms, "busts": busts, "roles": role_moves[:8], "injuries": injuries[:12],
            "claims": claims, "trades": trades, "model": model_week, "model_changes": model_changes,
            "has_pregame": bool(pre)}


# --- small history files (kept in data/, persisted by the private repo) -------------------
def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def _save(path: Path, obj: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(obj, indent=0, sort_keys=True) + "\n")


def save_pregame(path: Path, week: int, matchups: list[dict]) -> dict:
    """Pre-game projection and win chance per team for `week`, refreshed on every run until
    that matchup has points on the board (so the last pre-kickoff numbers are kept)."""
    data = _load(path)
    wk = data.setdefault(str(week), {})
    for m in matchups:
        a, b = m["teams"]
        if (a.get("played_pts") or 0) == 0 and (b.get("played_pts") or 0) == 0:
            for t, o in ((a, b), (b, a)):
                wk[str(t["roster_id"])] = {"mean": t["mean"], "sd": t["sd"], "win_prob": t["win_prob"], "opp": o["roster_id"]}
    _save(path, data)
    return data


def save_state(path: Path, week: int, power: list[dict]) -> dict:
    """Power ranks as of each week (overwritten while the week runs)."""
    data = _load(path)
    data[str(week)] = {"power": {str(r["roster_id"]): r["rank"] for r in power}}
    _save(path, data)
    return data


def save_recap(path: Path, recap: dict) -> dict:
    data = _load(path)
    data[str(recap["week"])] = recap
    _save(path, data)
    return data
