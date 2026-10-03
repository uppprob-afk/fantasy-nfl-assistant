import pytest

from nfl_assistant.brief import build_brief


def player(pid, name, pos, team, slot=None, status=None, check="verified", reason=None, ir=False):
    p = {"id": pid, "name": name, "position": pos, "team": team, "injury_status": status,
         "injury_body_part": "Knee" if status else None, "points": 30.0, "avg": 10.0, "games": 3,
         "ir_eligible": ir, "check": {"status": check, "reason": reason}}
    if slot:
        p["slot"] = slot
    return p


@pytest.fixture
def parts():
    me = {"roster_id": 1, "team_name": "My Team", "label": "my_username", "username": "my_username",
          "starters": [player("a", "Alpha", "QB", "BAL", "QB"),
                       player("b", "Bravo", "RB", "DAL", "RB", status="Out",
                              check="unverified", reason="Sleeper has 30, nflverse 27.")],
          "bench": [player("c", "Charlie", "WR", "SEA")],
          "ir": [player("d", "Delta", "TE", "LV", status="IR", ir=True)],
          "notes": ["Starter Bravo (RB) is Out; consider benching."]}
    dash = {
        "generated_at": "2026-10-06T19:00+11:00",
        "league": {"id": "123", "season": "2026", "current_week": 5, "completed_weeks": [1, 2, 3, 4],
                   "roster_positions": ["QB", "RB", "FLEX", "BN", "BN"], "faab_budget": 100,
                   "ppr": 1.0, "ir_allowed": ["IR"], "reserve_slots": 1},
        "me": me,
        "standings": [
            {"roster_id": 2, "rank": 1, "team_name": "Their Team", "label": "R1 (rival_one)", "wins": 4,
             "losses": 0, "ties": 0, "points_for": 500.0, "points_against": 400.0, "waiver_position": 9},
            {"roster_id": 1, "rank": 2, "team_name": "My Team", "label": "my_username", "wins": 3,
             "losses": 1, "ties": 0, "points_for": 480.0, "points_against": 420.0, "waiver_position": 5},
        ],
        "matchups": {"week": 5, "pairs": [{"is_mine": True, "teams": [
            {"team_name": "My Team", "label": "my_username", "points": 0},
            {"team_name": "Their Team", "label": "R1 (rival_one)", "points": 0}]}]},
        "warnings": [],
    }
    faab = {"budget": 100, "my_roster_id": 1,
            "managers": [{"roster_id": 1, "label": "my_username", "remaining": 74, "claims": 1, "overpaid": 8},
                         {"roster_id": 2, "label": "R1 (rival_one)", "remaining": 59, "claims": 2, "overpaid": 0}],
            "market": {"ALL": {"claims": 3, "median_winning_bid": 10, "contested_pct": 33},
                       "RB": {"claims": 2, "median_winning_bid": 12, "bargain_bid": 0,
                              "competitive_bid": 9, "safe_bid": 15}},
            "targets": [], "warnings": [],
            "trending_adds": [{"id": "x", "name": "Xray", "position": "RB", "team": "NYJ", "count": 5000,
                               "suggestion": {"bid": 15}}]}
    scan = {"first_run": False, "baseline": "2026-10-03T19:00+10:00",
            "my_players": [{"text": "Bravo is now Out.", "action": "Bench them."}],
            "other_starters": [], "free_agents": [
                {"id": "y", "name": "Yankee", "position": "RB", "team": "DET", "text": "...",
                 "reason": "Backup to Rex (Out).", "suggestion": {"bid": 16}}]}
    trades = {"ideas": [{"team_name": "Their Team", "manager": "R1 (rival_one)",
                         "give": [{"name": "Charlie", "position": "WR", "rate": 10.0}],
                         "get": [{"name": "Zulu", "position": "RB", "rate": 12.0}],
                         "my_gain": 15.0, "their_gain": 10.0, "balance": "balanced", "confidence": "medium"}],
              "sell_high": [{"name": "Charlie", "position": "WR", "manager": "my_username", "actual_ppg": 18.0,
                             "rate": 10.0, "expected_ppg": 11.0}],
              "buy_low": [], "trades_closed": False,
              "buyers": [], "teams": [{"is_mine": True, "vs_median": {"QB": 1.0, "RB": -2.0},
                                       "needs": ["RB"], "surplus": ["WR"]}]}
    return dash, faab, scan, trades


def test_brief_has_all_sections(parts):
    md = build_brief(*parts)
    for heading in ("# NFL update brief: My Team (week 5, 2026)", "## League settings", "## Standings",
                    "## This week (week 5)", "## My roster (3-1, rank 2)", "## Injuries on my roster",
                    "## New since last run", "## FAAB", "## Top waiver ideas", "## Top trade ideas"):
        assert heading in md


def test_brief_flags_verification_and_ir_rules(parts):
    md = build_brief(*parts)
    assert "| QB | Alpha | QB BAL | 30.0 | 10.0 | 3 | ✓ |" in md
    assert "Bravo **Out**" in md and "| UNVERIFIED |" in md
    assert "UNVERIFIED Bravo: Sleeper has 30, nflverse 27." in md
    assert "Bravo (RB DAL): Out (Knee), not IR-eligible here" in md
    assert "Delta (TE LV): IR (Knee), IR-eligible" in md
    assert "IR allowed only for: IR" in md and "Full PPR" in md


def test_brief_lists_news_waivers_and_trades(parts):
    md = build_brief(*parts)
    assert "- [My players] Bravo is now Out. → Bench them." in md
    assert md.index("Yankee") < md.index("Xray")          # scanner opportunities before trending
    assert "Yankee (RB DET): bid $16, Backup to Rex (Out)." in md
    assert "Xray (RB NYJ): bid $15, trending (5,000 adds/48h)" in md
    assert ("give Charlie (WR, 10.0/wk proj) for Zulu (RB, 12.0/wk proj). Me +15 pts ROS, them +10 "
            "(balanced, medium confidence)") in md
    assert "Sell high (mine): Charlie (WR, my_username): 18.0 ppg so far vs 10.0 projected (usage suggests 11.0)." in md
    assert "needs RB; spare WR" in md
    assert "**(me)**" in md


def test_brief_first_run_and_no_news(parts):
    dash, faab, scan, trades = parts
    assert "First scan: baseline saved" in build_brief(dash, faab, {**scan, "first_run": True}, trades)
    quiet = {**scan, "my_players": [], "free_agents": []}
    assert "Nothing new since 2026-10-03T19:00+10:00." in build_brief(dash, faab, quiet, trades)
