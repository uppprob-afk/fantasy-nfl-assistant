from nfl_assistant import outlook, trades


def test_simulate_records_seed_chances_and_wins_needed():
    standings = {1: {"wins": 3, "losses": 0, "pf": 300}, 2: {"wins": 0, "losses": 3, "pf": 200},
                 3: {"wins": 2, "losses": 1, "pf": 260}, 4: {"wins": 1, "losses": 2, "pf": 240}}
    schedule = {4: [(1, 2), (3, 4)], 5: [(1, 3), (2, 4)]}
    dist = {(t, w): (100.0, 15.0) for t in standings for w in (4, 5)}
    sim = outlook.simulate(standings, schedule, dist, {}, 2, n=2000, seed=1)
    assert all(abs(sum(c) - sim["n"]) == 0 for c in sim["seeds"].values())          # every sim ranks every team
    assert sim["seeds"][1][0] > sim["seeds"][2][0]                                     # the 3-0 team is #1 more often
    need_4 = outlook.wins_needed(sim["by_wins"][4], 2)
    assert need_4 in (1, 2) and outlook.wins_needed(sim["by_wins"][1], 2) == 0        # unbeaten team: in without another win
    assert outlook.wins_needed({0: [0, 50], 1: [0, 50]}, 1) is None                     # nothing gets them in


def test_lineup_decisions_count_bench_points_costly_weeks_and_lost_games():
    slots = ["QB", "WR"]
    position = {"q1": "QB", "q2": "QB", "w1": "WR", "w2": "WR"}
    matchups = {1: [
        {"roster_id": 1, "matchup_id": 1, "points": 20.0, "starters_points": [10.0, 10.0],
         "players_points": {"q1": 10.0, "q2": 25.0, "w1": 10.0, "w2": 3.0}},          # left 15 on the bench
        {"roster_id": 2, "matchup_id": 1, "points": 30.0, "starters_points": [15.0, 15.0],
         "players_points": {"q1": 15.0, "w1": 15.0}},
    ]}
    s = trades.season_strength(matchups, [1], slots, position)
    me = s[1]
    assert me["bench_left"] == 15.0 and me["costly_weeks"] == 1 and me["lost_by_lineup"] == 1   # 35 would have beaten 30
    assert s[2]["bench_left"] == 0.0 and s[2]["lost_by_lineup"] == 0
