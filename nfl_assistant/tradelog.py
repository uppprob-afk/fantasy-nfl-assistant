"""League trade report card: who is winning each trade made this season.

Each side of a trade is scored on what it actually got:
- points the players it received have scored in its starting lineup since the trade (Sleeper's
  league-scored matchup points; bench points don't count), plus
- their rest-of-season value now (projected points above a free agent at the position), but only
  for players still on that roster; a player since dropped or traded on adds nothing more.
FAAB and draft picks are listed but not scored.

The first time a trade is seen, every player's rest-of-season value is saved (`remember_values`),
so later trades also show "value when made". Trades made before this was added get the value at
first sight, flagged as late. Pure functions apart from the small history file.
"""

import json
from pathlib import Path

WIN_MARGIN = 8.0          # points: a smaller gap between the sides is "even so far"


def trade_key(tx: dict) -> str:
    """Stable id for a trade (Sleeper's transaction id when present)."""
    if tx.get("transaction_id"):
        return str(tx["transaction_id"])
    return f"{tx.get('leg')}:{tx.get('status_updated')}:{','.join(sorted(tx.get('adds') or {}))}"


def completed_trades(txs: list[dict]) -> list[dict]:
    return [t for t in txs if t.get("type") == "trade" and t.get("status") == "complete"]


def sides(tx: dict) -> list[dict]:
    """Per roster: players received and given, FAAB and draft picks in / out."""
    out = []
    for rid in tx.get("roster_ids") or []:
        got = sorted(p for p, r in (tx.get("adds") or {}).items() if r == rid)
        gave = sorted(p for p, r in (tx.get("drops") or {}).items() if r == rid)
        faab = sum(b.get("amount", 0) for b in tx.get("waiver_budget") or [] if b.get("receiver") == rid) \
            - sum(b.get("amount", 0) for b in tx.get("waiver_budget") or [] if b.get("sender") == rid)
        picks = [f"{p.get('season')} round {p.get('round')}" for p in tx.get("draft_picks") or [] if p.get("owner_id") == rid]
        out.append({"rid": rid, "got": got, "gave": gave, "faab": faab, "picks": picks})
    return out


def started_points(matchups: dict, weeks: list[int], rid: int, pid: str) -> tuple[float, int]:
    """Points `pid` scored in roster `rid`'s starting lineup over `weeks`, and how many starts."""
    pts, n = 0.0, 0
    for w in weeks:
        entry = next((m for m in matchups.get(w) or [] if m.get("roster_id") == rid), None)
        if entry and pid in (entry.get("starters") or []):
            pts += float((entry.get("players_points") or {}).get(pid) or 0)
            n += 1
    return round(pts, 1), n


def ros_value(pid: str, proj: dict, repl: dict, n_weeks: int) -> float:
    """Rest-of-season points above a free agent (never below 0: you'd just drop him)."""
    p = proj.get(pid)
    if not p:
        return 0.0
    return round(max(0.0, p["ros"] - repl.get(p["position"], 0.0) * n_weeks), 1)


def remember_values(path: Path, txs: list[dict], proj: dict, repl: dict, n_weeks: int, week: int) -> dict:
    """Save each player's value the first time a trade is seen; returns the whole file."""
    data = json.loads(path.read_text()) if path.exists() else {}
    changed = False
    for tx in completed_trades(txs):
        k = trade_key(tx)
        if k in data:
            continue
        data[k] = {"seen_week": week, "late": week > (tx.get("leg") or week) + 1,
                   "values": {p: ros_value(p, proj, repl, n_weeks) for p in (tx.get("adds") or {})}}
        changed = True
    if changed:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return data


def report(txs: list[dict], matchups: dict, completed: list[int], proj: dict, repl: dict, n_weeks: int,
           rosters: list[dict], names: dict, positions: dict, then: dict | None = None) -> dict:
    """Every completed trade, newest first, with each side's score and who's ahead, plus a
    per-team summary (trades made, net points won)."""
    on = {r["roster_id"]: set(r.get("players") or []) for r in rosters}
    then = then or {}
    trades, net, made = [], {}, {}
    for tx in sorted(completed_trades(txs), key=lambda t: (t.get("leg") or 0, t.get("status_updated") or 0), reverse=True):
        week = tx.get("leg") or 0
        since = [w for w in completed if w >= week]
        saved = then.get(trade_key(tx)) or {}
        ss = []
        for s in sides(tx):
            got = []
            for pid in s["got"]:
                pts, n = started_points(matchups, since, s["rid"], pid)
                still = pid in on.get(s["rid"], set())
                got.append({"id": pid, "name": names.get(pid, pid), "pos": positions.get(pid), "pts": pts, "starts": n,
                            "ros": ros_value(pid, proj, repl, n_weeks) if still else 0.0, "still": still,
                            "then": (saved.get("values") or {}).get(pid)})
            total = round(sum(g["pts"] + g["ros"] for g in got), 1)
            ss.append({**s, "got": got, "total": total})
            made[s["rid"]] = made.get(s["rid"], 0) + 1
        best = max(ss, key=lambda x: x["total"]) if ss else None
        others = [x["total"] for x in ss if x is not best]
        margin = round(best["total"] - max(others), 1) if best and others else 0.0
        for x in ss:
            rest = [y["total"] for y in ss if y is not x]
            net[x["rid"]] = round(net.get(x["rid"], 0.0) + x["total"] - (max(rest) if rest else 0.0), 1)
        trades.append({"key": trade_key(tx), "week": week, "sides": ss, "margin": margin,
                       "winner": best["rid"] if best and margin >= WIN_MARGIN else None,
                       "late_value": bool(saved.get("late")), "has_then": bool(saved)})
    return {"trades": trades, "summary": {str(r): {"made": made.get(r, 0), "net": net.get(r, 0.0)} for r in made},
            "win_margin": WIN_MARGIN}
