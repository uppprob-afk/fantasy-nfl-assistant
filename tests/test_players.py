from nfl_assistant.players import ir_allowed_statuses, is_ir_eligible, player_name, slim_players


def test_ir_only_allowed_by_default(league):
    assert ir_allowed_statuses(league["settings"]) == {"IR"}


def test_ir_allows_out_and_doubtful_when_league_enables_them():
    allowed = ir_allowed_statuses({"reserve_allow_out": 1, "reserve_allow_doubtful": 1})
    assert allowed == {"IR", "Out", "Doubtful"}


def test_out_player_not_eligible_when_league_disallows_out(players):
    allowed = ir_allowed_statuses({"reserve_allow_out": 0})
    assert not is_ir_eligible(players["rb1"], allowed)      # Out
    assert not is_ir_eligible(players["rb3"], allowed)      # Doubtful
    assert is_ir_eligible(players["wr2"], allowed)          # IR
    assert not is_ir_eligible(players["qb1"], allowed)      # healthy
    assert not is_ir_eligible(None, allowed)


def test_player_name_handles_defences_and_unknowns(players):
    assert player_name(players["PIT"]) == "Pittsburgh Steelers"
    assert player_name(players["qb1"]) == "Quinn Back"
    assert player_name(None, "999") == "Unknown (999)"


def test_slim_players_keeps_rostered_and_fantasy_positions():
    players = {
        "a": {"full_name": "A", "position": "WR", "team": "KC", "injury_status": "Out", "extra": 1},
        "b": {"full_name": "B", "position": "OL", "team": "KC"},
        "c": {"full_name": "C", "position": "WR", "team": None},
        "d": {"full_name": "D", "position": "LB", "team": None},
    }
    slim = slim_players(players, keep_ids={"d"})
    assert set(slim) == {"a", "d"}
    assert slim["a"] == {"full_name": "A", "position": "WR", "team": "KC", "injury_status": "Out"}


def test_find_player_by_name_prefers_active_relevant():
    from nfl_assistant.players import find_player
    players = {
        "1": {"full_name": "Josh Allen", "position": "QB", "team": "BUF", "search_rank": 5},
        "2": {"full_name": "Josh Allen", "position": "LB", "team": "JAX", "search_rank": 900},
        "3": {"full_name": "Amon-Ra St. Brown", "position": "WR", "team": "DET", "search_rank": 3},
        "4": {"full_name": "Old Guy", "position": "WR", "team": None},
    }
    assert find_player("josh allen", players) == "1"
    assert find_player("Amon Ra St Brown", players) == "3"
    assert find_player("Old Guy", players) == "4"
    assert find_player("Nobody", players) is None
