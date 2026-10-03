import json
from pathlib import Path

import pytest

from nfl_assistant import dashboard, faab

FIX = Path(__file__).parent / "fixtures"


@pytest.fixture
def txs():
    return json.loads((FIX / "transactions.json").read_text())


@pytest.fixture
def managers(users, rosters):
    return dashboard.manager_lookup(users, rosters, {"rival_one": "R1"})


@pytest.fixture
def log(txs, players, managers):
    return faab.waiver_log(txs, players, managers)


def by_player(log, pid):
    return next(r for r in log if r["player"]["id"] == pid)


def test_contested_claim_clearing_price_and_overpay(log):
    r = by_player(log, "wr1")
    assert r["bid"] == 20 and r["roster_id"] == 1
    assert r["competing_bids"] == 2          # the $12 and $5 outbid claims
    assert r["invalid_bids"] == 1            # $30 bid failed on roster size, not price
    assert r["runner_up_bid"] == 12
    assert r["clearing_price"] == 13         # runner-up + $1
    assert r["overpay"] == 7
    assert [d["id"] for d in r["dropped"]] == ["rb3"]


def test_tie_won_on_priority_has_no_overpay(log):
    r = by_player(log, "rb2")
    assert r["runner_up_bid"] == 8 and r["clearing_price"] == 8 and r["overpay"] == 0


def test_uncontested_claim_clears_at_min_bid(txs, players, managers):
    r = by_player(faab.waiver_log(txs, players, managers, min_bid=1), "PIT")
    assert r["competing_bids"] == 0 and r["clearing_price"] == 1 and r["overpay"] == 2


def test_log_is_newest_first(log):
    assert [r["week"] for r in log] == [2, 2, 1, 1]


def test_manager_faab_totals_and_warnings(txs, rosters, managers, log):
    rows, warnings = faab.manager_faab(txs, rosters, managers, 100, log)
    me = next(r for r in rows if r["roster_id"] == 1)
    r1 = next(r for r in rows if r["roster_id"] == 2)
    # Fixture rosters say Sleeper used 26 (me) / 41 (R1) vs 20 / 8 in our log -> warned
    assert len(warnings) == 3 and any("R1 (rival_one)" in w for w in warnings)
    assert me["spent"] == 26                       # Sleeper's figure wins
    assert me["remaining"] == 100 - 26 + 5         # +$5 FAAB received in trade
    assert r1["remaining"] == 100 - 41 - 5
    assert me["claims"] == 1 and me["failed_bids"] == 1 and me["fa_adds"] == 1 and me["overpaid"] == 7
    assert r1["claims"] == 2 and r1["failed_bids"] == 1


def test_manager_faab_no_warning_when_totals_match(txs, rosters, managers, log):
    for r, used in zip(rosters, (20, 8, 3, 0)):
        r["settings"]["waiver_budget_used"] = used
    _, warnings = faab.manager_faab(txs, rosters, managers, 100, log)
    assert warnings == []


def test_bid_for_win_rate():
    assert faab.bid_for_win_rate([0, 0, 5, 13], 0.5) == 0
    assert faab.bid_for_win_rate([0, 0, 5, 13], 0.75) == 5
    assert faab.bid_for_win_rate([0, 0, 5, 13], 1.0) == 13
    assert faab.bid_for_win_rate([], 0.5) is None


def test_bid_to_beat():
    assert faab.bid_to_beat([5, 12, 20, 30], 0.5) == 13      # beats 5 and 12
    assert faab.bid_to_beat([5, 12, 20, 30], 0.75) == 21
    assert faab.bid_to_beat([5, 12, 20, 30], 1.0) == 31
    assert faab.bid_to_beat([], 0.5) is None


def test_all_bids_includes_losing_and_invalid(txs, players):
    b = faab.all_bids(txs, players)
    assert sorted(b["WR"]) == [5, 12, 20, 30]
    assert len(b["ALL"]) == 8


def test_market_prices(txs, players, log):
    m = faab.market_prices(log, faab.all_bids(txs, players))
    assert m["WR"]["claims"] == 1 and m["WR"]["avg_winning_bid"] == 20
    assert m["WR"]["bargain_bid"] == 13 and m["WR"]["competitive_bid"] == 13 and m["WR"]["safe_bid"] == 21
    assert m["ALL"]["claims"] == 4
    assert m["ALL"]["median_winning_bid"] == 5.5
    assert m["ALL"]["contested_pct"] == 50
    assert m["ALL"]["total_overpaid"] == 7 + 0 + 3 + 0


def test_bid_suggestion_scales_with_demand(txs, players, log):
    m = faab.market_prices(log, faab.all_bids(txs, players))
    quiet = faab.bid_suggestion("WR", m, 100, "quiet")
    hot = faab.bid_suggestion("WR", m, 100, "hot")
    assert quiet["bid"] == 13 and hot["bid"] == 21 and quiet["basis"] == "WR"
    assert "Small sample" in hot["reason"]
    # falls back to league-wide history for a position with no claims
    assert faab.bid_suggestion("K", m, 100)["basis"] == "all positions"
    # never suggests more than I have left
    assert faab.bid_suggestion("WR", m, 10, "hot")["bid"] == 10
    assert faab.bid_suggestion("WR", {}, 100)["bid"] is None


def test_comparable_claims(log):
    assert faab.comparable_claims("WR", log) == [
        {"name": "Wade Receiver", "week": 1, "bid": 20, "clearing_price": 13, "competing_bids": 2}]


def test_trending_free_agents_filters_rostered(players):
    trending = [{"player_id": "qb1", "count": 900}, {"player_id": "k1", "count": 500},
                {"player_id": "nobody", "count": 400}]
    out = faab.trending_free_agents(trending, rostered={"qb1"}, players=players)
    assert [p["id"] for p in out] == ["k1"] and out[0]["count"] == 500


def test_other_moves_includes_trades_and_fa(txs, players, managers):
    moves = faab.other_moves(txs, players, managers)
    assert [m["type"] for m in moves] == ["trade", "free_agent"]
    trade = moves[0]
    assert {m["roster_id"] for m in trade["moves"]} == {1, 2}
    assert trade["faab"] == [{"sender": 2, "receiver": 1, "amount": 5}]
