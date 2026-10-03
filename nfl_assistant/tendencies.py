"""Manager tendencies for FAAB: bidding habits and likely rivals for a player.

Built from every waiver bid this season (won, outbid and invalid), each team's FAAB
left, and next week's optimal lineups (to judge who actually needs a player).
Pure functions, no network. Samples are small early in the season, so labels are
only given once a manager has placed enough bids, and counts are shown, not rates.
"""

from collections import Counter, defaultdict
from statistics import median

from .lineups import FLEX_ELIGIBLE

MIN_BIDS_FOR_STYLE = 3
NEARLY_OUT_SHARE = 0.15   # <= 15% of the season budget left


def bids_by_manager(transactions: list[dict], players: dict) -> dict[int, list[dict]]:
    """roster_id -> every waiver bid they placed (won, outbid or invalid)."""
    out = defaultdict(list)
    for tx in transactions:
        if tx.get("type") != "waiver" or tx.get("status") not in ("complete", "failed"):
            continue
        notes = ((tx.get("metadata") or {}).get("notes") or "")
        outcome = "won" if tx["status"] == "complete" else (
            "outbid" if "claimed by another owner" in notes else "invalid")
        for pid in (tx.get("adds") or {}):
            out[tx["roster_ids"][0]].append({
                "player": pid, "position": (players.get(pid) or {}).get("position") or "?",
                "bid": int((tx.get("settings") or {}).get("waiver_bid") or 0), "outcome": outcome,
                "week": tx.get("leg")})
    return dict(out)


def profiles(bids: dict[int, list[dict]], faab_rows: list[dict], log: list[dict], budget: int) -> dict[int, dict]:
    """Per-manager bidding profile. faab_rows = faab.manager_faab rows; log = faab.waiver_log."""
    all_bids = [b["bid"] for bs in bids.values() for b in bs]
    league_median = median(all_bids) if all_bids else 0
    overpay = defaultdict(list)
    for row in log:
        overpay[row["roster_id"]].append(row["overpay"])
    out = {}
    for m in faab_rows:
        rid = m["roster_id"]
        bs = bids.get(rid, [])
        amounts = [b["bid"] for b in bs]
        by_pos = defaultdict(list)
        for b in bs:
            by_pos[b["position"]].append(b["bid"])
        typical = median(amounts) if amounts else None
        if len(bs) < MIN_BIDS_FOR_STYLE:
            style = "not enough bids yet"
        elif league_median and typical >= 1.5 * league_median:
            style = "big spender"
        elif typical <= 0.5 * league_median:
            style = "stingy"
        else:
            style = "middle of the pack"
        remaining = m["remaining"]
        out[rid] = {
            "roster_id": rid, "label": m["label"], "username": m["username"], "nickname": m.get("nickname"),
            "team_name": m["team_name"], "remaining": remaining, "spent": m["spent"],
            "nearly_out": remaining <= max(NEARLY_OUT_SHARE * budget, 0),
            "bids": len(bs), "won": sum(b["outcome"] == "won" for b in bs),
            "outbid": sum(b["outcome"] == "outbid" for b in bs),
            "invalid": sum(b["outcome"] == "invalid" for b in bs),
            "fa_adds": m.get("fa_adds", 0),
            "typical_bid": typical, "max_bid": max(amounts) if amounts else None,
            "overpaid_total": sum(overpay[rid]), "overpaid_claims": sum(1 for x in overpay[rid] if x > 0),
            "positions": dict(Counter(b["position"] for b in bs).most_common()),
            "typical_by_pos": {p: median(v) for p, v in by_pos.items()},
            "style": style, "active": bool(bs) or m.get("fa_adds", 0) > 0,
            "waiver_position": m.get("waiver_position"),
        }
    return out


def upgrade_for(player_pts: float, position: str, lineup: list[dict]) -> float | None:
    """How much a player would add over the weakest starter they'd replace (None if no eligible slot)."""
    eligible = [x["pts"] for x in lineup
                if x["slot"] == position or position in FLEX_ELIGIBLE.get(x["slot"], set())]
    return round(player_pts - min(eligible), 1) if eligible else None


def rivals(position: str, player_pts: float, my_rid: int, profs: dict[int, dict],
           lineups: dict[int, list[dict]], my_waiver: int | None, hot: bool = False) -> dict:
    """Who's likely to bid on a player and roughly what it'll take to win.

    Likely:   would start for them (upgrade > 1 pt) or they've chased the position,
              plus they're active and have at least $5 left (or the player is hot).
    Possible: a smaller upgrade or some history, and budget left.
    """
    rows = []
    for rid, p in profs.items():
        if rid == my_rid:
            continue
        up = upgrade_for(player_pts, position, lineups.get(rid, []))
        chased = p["positions"].get(position, 0)
        reasons = []
        if up is not None and up > 0:
            reasons.append(f"would start for them (+{up:.1f} pts)")
        if chased:
            reasons.append(f"bid on {position}s {chased}×")
        if p["nearly_out"]:
            reasons.append(f"only ${p['remaining']} left")
        if not p["active"]:
            reasons.append("hasn't made a move yet")
        if p["remaining"] <= 0:
            tier = "unlikely"
        elif (up or -99) > 1 and p["active"] and (p["remaining"] >= 5 or hot):
            tier = "likely"
        elif ((up or -99) > -2 or chased) and (p["active"] or hot):
            tier = "possible"
        else:
            tier = "unlikely"
        if hot and tier == "possible" and (up or -99) > 0:
            tier = "likely"
        typical = p["typical_by_pos"].get(position, p["typical_bid"])
        rows.append({"roster_id": rid, "label": p["label"], "tier": tier, "upgrade": up,
                     "typical": typical, "max": p["max_bid"], "remaining": p["remaining"],
                     "wins_ties": my_waiver is not None and p.get("waiver_position") is not None
                     and my_waiver < p["waiver_position"],
                     "reasons": reasons})
    order = {"likely": 0, "possible": 1, "unlikely": 2}
    rows.sort(key=lambda r: (order[r["tier"]], -(r["upgrade"] or -99)))
    likely = [r for r in rows if r["tier"] == "likely"]
    possible = [r for r in rows if r["tier"] == "possible"]
    return {"likely": likely, "possible": possible, "unlikely": [r for r in rows if r["tier"] == "unlikely"],
            "estimate": estimate(likely, possible, hot)}


def estimate(likely: list[dict], possible: list[dict], hot: bool) -> dict | None:
    """Rough bid to win: beat the likely rivals' typical bid (low) or biggest bid (high).

    A hot player with no clear 'likely' rival is based on the 'possible' rivals instead,
    because managers chase trending players for upside, not projections. A 'possible'
    rival who has bid much more before is listed separately as a wildcard.
    """
    basis_rows, basis = likely, "likely"
    if not basis_rows and hot:
        basis_rows, basis = possible, "possible"
    if not basis_rows:
        return None
    with_history = [r for r in basis_rows if r["typical"] is not None]
    if not with_history:
        return {"low": None, "high": None, "wildcard": None,
                "basis": f"{len(basis_rows)} {basis} rival(s), none with bid history yet"}
    low = int(max(min(r["typical"], r["remaining"]) for r in with_history)) + 1
    high = max(low, int(max(min(r["max"], r["remaining"]) for r in with_history)) + 1)
    wild = max((r for r in possible if r["max"] is not None and r not in basis_rows),
               key=lambda r: min(r["max"], r["remaining"]), default=None)
    wildcard = None
    if wild and min(wild["max"], wild["remaining"]) >= high:
        wildcard = {"label": wild["label"], "max": min(wild["max"], wild["remaining"])}
    return {"low": low, "high": high, "wildcard": wildcard,
            "basis": f"{len(with_history)} {basis} rival(s) with bid history: low beats their typical bid, "
                     f"high beats their biggest"}
