"""Stage 2 calculations: FAAB spend, waiver log, market prices, bargain bids, trending FAs.

Sleeper's transactions include failed waiver claims with their bids, so for each
claim we can see the competing bids and the "clearing price" (the lowest bid that
would have won: runner-up bid + 1, or the league minimum if nobody else bid).
"""

from collections import defaultdict
from datetime import datetime, timezone
from statistics import mean, median

from .players import player_brief

OUTBID_NOTE = "claimed by another owner"


def _bid(tx: dict) -> int:
    return int((tx.get("settings") or {}).get("waiver_bid") or 0)


def _date(ms) -> str | None:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).date().isoformat() if ms else None


def _was_outbid(tx: dict) -> bool:
    return OUTBID_NOTE in ((tx.get("metadata") or {}).get("notes") or "")


# --- waiver log -------------------------------------------------------------
def waiver_log(transactions: list[dict], players: dict, managers: dict, min_bid: int = 0) -> list[dict]:
    """One row per successful waiver claim, newest first.

    Claims for the same player processed in the same waiver run (same status_updated)
    are competitors. Failed claims that lost to roster limits etc. are counted
    separately as `invalid_bids` and don't set the clearing price.
    """
    claims = defaultdict(list)
    for tx in transactions:
        if tx.get("type") != "waiver":
            continue
        for pid in (tx.get("adds") or {}):
            claims[(pid, tx.get("status_updated"))].append(tx)

    rows = []
    for (pid, _), txs in claims.items():
        winners = [t for t in txs if t.get("status") == "complete"]
        if not winners:
            continue
        win = winners[0]
        rivals = [t for t in txs if t is not win and t.get("status") == "failed"]
        outbid = sorted((_bid(t) for t in rivals if _was_outbid(t)), reverse=True)
        bid = _bid(win)
        runner_up = outbid[0] if outbid else None
        if runner_up is None:
            clearing = min_bid
        elif runner_up == bid:
            clearing = bid  # tie, won on waiver priority
        else:
            clearing = runner_up + 1
        roster_id = win["roster_ids"][0]
        drops = [player_brief(d, players) for d in (win.get("drops") or {})]
        rows.append({
            "week": win.get("leg"),
            "date": _date(win.get("status_updated")),
            "processed": win.get("status_updated"),
            "player": player_brief(pid, players),
            "bid": bid,
            "roster_id": roster_id,
            "winner": managers[roster_id]["label"],
            "competing_bids": len(outbid),
            "invalid_bids": len(rivals) - len(outbid),
            "runner_up_bid": runner_up,
            "clearing_price": clearing,
            "overpay": max(bid - clearing, 0),
            "dropped": drops,
        })
    rows.sort(key=lambda r: (r["processed"] or 0, -r["bid"]), reverse=True)
    return rows


def other_moves(transactions: list[dict], players: dict, managers: dict) -> list[dict]:
    """Free-agent pickups, trades and commissioner moves (newest first)."""
    out = []
    for tx in transactions:
        if tx.get("type") == "waiver" or tx.get("status") != "complete":
            continue
        moves = []
        for rid in tx.get("roster_ids") or []:
            moves.append({
                "manager": managers[rid]["label"], "roster_id": rid,
                "added": [player_brief(p, players) for p, r in (tx.get("adds") or {}).items() if r == rid],
                "dropped": [player_brief(p, players) for p, r in (tx.get("drops") or {}).items() if r == rid],
            })
        out.append({"type": tx["type"], "week": tx.get("leg"), "date": _date(tx.get("status_updated")),
                    "processed": tx.get("status_updated"), "moves": moves,
                    "faab": tx.get("waiver_budget") or []})
    out.sort(key=lambda r: r["processed"] or 0, reverse=True)
    return out


# --- per-manager FAAB -------------------------------------------------------
def manager_faab(transactions: list[dict], rosters: list[dict], managers: dict, budget: int,
                 log: list[dict]) -> tuple[list[dict], list[str]]:
    """FAAB spent / remaining / claims per manager, plus warnings if our totals
    disagree with Sleeper's waiver_budget_used."""
    stats = {r["roster_id"]: {"spent": 0, "claims": 0, "failed_bids": 0, "fa_adds": 0,
                              "traded_in": 0, "traded_out": 0, "overpaid": 0} for r in rosters}
    for row in log:
        s = stats[row["roster_id"]]
        s["spent"] += row["bid"]
        s["claims"] += 1
        s["overpaid"] += row["overpay"]
    for tx in transactions:
        if tx.get("type") == "waiver" and tx.get("status") == "failed":
            stats[tx["roster_ids"][0]]["failed_bids"] += 1
        elif tx.get("type") == "free_agent" and tx.get("status") == "complete":
            for rid in set((tx.get("adds") or {}).values()):
                stats[rid]["fa_adds"] += 1
        if tx.get("status") == "complete":
            for wb in tx.get("waiver_budget") or []:
                stats[wb["sender"]]["traded_out"] += wb["amount"]
                stats[wb["receiver"]]["traded_in"] += wb["amount"]

    rows, warnings = [], []
    for r in rosters:
        rid = r["roster_id"]
        s = stats[rid]
        sleeper_used = (r.get("settings") or {}).get("waiver_budget_used", 0)
        if sleeper_used != s["spent"]:
            warnings.append(f"FAAB check: {managers[rid]['label']} spent ${s['spent']} in the transaction log "
                            f"but Sleeper says ${sleeper_used}. Using Sleeper's figure.")
        remaining = budget - sleeper_used + s["traded_in"] - s["traded_out"]
        rows.append({**managers[rid], **s, "spent": sleeper_used, "remaining": remaining,
                     "pct_left": round(100 * remaining / budget) if budget else 0})
    rows.sort(key=lambda x: -x["remaining"])
    return rows, warnings


# --- market prices ----------------------------------------------------------
def bid_for_win_rate(clearing_prices: list[int], rate: float) -> int | None:
    """Lowest whole-dollar bid that would have won at least `rate` of these past claims."""
    if not clearing_prices:
        return None
    prices = sorted(clearing_prices)
    for bid in range(prices[0], prices[-1] + 1):
        if sum(p <= bid for p in prices) / len(prices) >= rate:
            return bid
    return prices[-1]


def bid_to_beat(rival_bids: list[int], share: float) -> int | None:
    """Lowest whole-dollar bid strictly above `share` of past bids (what rivals offer)."""
    if not rival_bids:
        return None
    bids = sorted(rival_bids)
    for bid in range(0, bids[-1] + 2):
        if sum(b < bid for b in bids) / len(bids) >= share:
            return bid
    return bids[-1] + 1


def all_bids(transactions: list[dict], players: dict) -> dict[str, list[int]]:
    """Every waiver bid placed (won or lost), by position. Shows what rivals are willing to pay."""
    out = defaultdict(list)
    for tx in transactions:
        if tx.get("type") != "waiver" or tx.get("status") not in ("complete", "failed"):
            continue
        for pid in (tx.get("adds") or {}):
            pos = (players.get(pid) or {}).get("position") or "?"
            out[pos].append(_bid(tx))
            out["ALL"].append(_bid(tx))
    return out


def market_prices(log: list[dict], bids_by_pos: dict[str, list[int]]) -> dict:
    """Per position: average / median winning bid plus three bid levels.

    bargain     wins 50% of past claims at what it actually took (clearing price):
                fine for players nobody else is chasing.
    competitive beats 50% of all bids rivals have placed at this position.
    safe        beats 75% of all bids rivals have placed.
    """
    by_pos = defaultdict(list)
    for row in log:
        by_pos[row["player"]["position"]].append(row)
    by_pos["ALL"] = list(log)
    out = {}
    for pos, rows in by_pos.items():
        bids = [r["bid"] for r in rows]
        clear = [r["clearing_price"] for r in rows]
        rival = bids_by_pos.get(pos, bids)
        out[pos] = {
            "claims": len(rows),
            "bids_placed": len(rival),
            "avg_winning_bid": round(mean(bids), 1),
            "median_winning_bid": median(bids),
            "max_winning_bid": max(bids),
            "median_clearing_price": median(clear),
            "contested_pct": round(100 * sum(r["competing_bids"] > 0 for r in rows) / len(rows)),
            "bargain_bid": bid_for_win_rate(clear, 0.5),
            "competitive_bid": bid_to_beat(rival, 0.5),
            "safe_bid": bid_to_beat(rival, 0.75),
            "total_overpaid": sum(r["overpay"] for r in rows),
        }
    return out


def comparable_claims(position: str, log: list[dict], limit: int = 5) -> list[dict]:
    """Most expensive claims at a position this season: 'what players like this went for'."""
    rows = [r for r in log if r["player"]["position"] == position]
    rows.sort(key=lambda r: -r["bid"])
    return [{"name": r["player"]["name"], "week": r["week"], "bid": r["bid"],
             "clearing_price": r["clearing_price"], "competing_bids": r["competing_bids"]}
            for r in rows[:limit]]


DEMAND_LEVEL = {"hot": "safe_bid", "warm": "competitive_bid", "quiet": "bargain_bid"}


def bid_suggestion(position: str, market: dict, remaining: int, demand: str = "quiet",
                   min_sample: int = 1, level: str | None = None, context: str | None = None) -> dict:
    """Bargain-first bid suggestion: the lowest level likely to win given expected demand.

    Uses the position's history if it has `min_sample`+ claims, otherwise league-wide.
    `level` overrides the level picked from demand; `context` replaces the demand wording.
    """
    m, basis = market.get(position), position
    if not m or m["claims"] < min_sample:
        m, basis = market.get("ALL"), "all positions"
    if not m:
        return {"bid": None, "demand": demand, "basis": None, "levels": {},
                "reason": "No waiver history yet."}
    levels = {k: min(m[k], remaining) for k in ("bargain_bid", "competitive_bid", "safe_bid")}
    level = level or DEMAND_LEVEL[demand]
    bid = levels[level]
    why = {
        "hot": f"heavily trending, so expect rivals: ${bid} beats 75% of the {m['bids_placed']} bids placed",
        "warm": f"some interest: ${bid} beats half of the {m['bids_placed']} bids placed",
        "quiet": f"little competition expected: ${bid} would have won half of past claims at what they actually cost",
    }[demand]
    if context:
        why = context + ": " + {
            "safe_bid": f"${bid} beats 75% of the {m['bids_placed']} bids placed",
            "competitive_bid": f"${bid} beats half of the {m['bids_placed']} bids placed",
            "bargain_bid": f"${bid} would have won half of past claims at what they actually cost",
        }[level]
    small = " Small sample, so treat as a rough guide." if m["claims"] < 6 else ""
    return {"bid": bid, "demand": demand, "basis": basis, "levels": levels, "level": level,
            "reason": f"{why} ({basis}, {m['claims']} claims).{small}"}


# --- trending ---------------------------------------------------------------
def trending_free_agents(trending: list[dict], rostered: set[str], players: dict,
                         limit: int = 10) -> list[dict]:
    out = []
    for t in trending:
        pid = t.get("player_id")
        p = players.get(pid)
        if not p or pid in rostered or not p.get("team"):
            continue
        out.append({**player_brief(pid, players), "count": t.get("count", 0)})
        if len(out) >= limit:
            break
    return out
