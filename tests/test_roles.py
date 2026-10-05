from nfl_assistant import projections as pj
from nfl_assistant import roles


def g(week, car_share, carries=10, targets=2, tgt_share=0.05, pos="RB", team="CHI", season="2026", partial=False, rush=6.0, rec=2.0):
    return {"season": season, "week": week, "team": team, "position": pos, "car_share": car_share, "tgt_share": tgt_share,
            "carries": carries, "targets": targets, "partial": partial, "parts": {"rush": rush, "rec": rec, "pass": 0.0}, "pct": 0.5}


def chicago():
    swift = [g(1, .5), g(2, .55), g(3, .55), g(4, .28, partial=True)]
    mona = [g(1, .28), g(2, .3), g(3, .28), g(4, .56)]
    return {"swift": swift, "mona": mona}


def test_opportunity_game_when_player_ahead_leaves_early():
    logs = chicago()
    roles.mark_opportunity(logs)
    assert [x["opp"] for x in logs["mona"]] == [False, False, False, True]
    assert not any(x["opp"] for x in logs["swift"])


def test_role_components_skip_opportunity_games():
    logs = chicago()
    roles.mark_opportunity(logs)
    vol = {"CHI": {"carries": 30.0, "targets": 32.0, "games": 4}}
    usage = {"RB": {"per_carry": 0.6, "per_target": 1.4}}
    r = roles.role_components(logs["mona"], "2026", "RB", "CHI", vol, usage)
    assert r["n"] == 3 and abs(r["car_share"] - 0.2867) < 1e-3
    assert r["rate"] > 0 and roles.role_components(logs["mona"], "2026", "QB", "CHI", vol, usage) is None


def test_team_volume_shrinks_and_respects_cutoff():
    logs = {"a": [g(1, .5, carries=40, targets=30, team="CHI"), g(2, .5, carries=20, targets=30, team="CHI")],
            "b": [g(1, .5, carries=20, targets=30, team="DET")]}
    v = roles.team_volume(logs, "2026")
    assert v["CHI"]["games"] == 2 and 25 < v["CHI"]["carries"] < 30
    assert roles.team_volume(logs, "2026", before_week=2)["CHI"]["games"] == 1


def test_learn_take_from_absences():
    logs = {"a": [g(w, .6) for w in (1, 2, 3)], "b": [g(w, .3) for w in (1, 2, 3)] + [g(4, .7)],
            "c": [g(w, .1) for w in (1, 2, 3)] + [g(4, .2)]}
    t = roles.learn_take(logs)["RB"]
    assert t["events"] == 1                       # "a" sat week 4
    raw_take = (0.7 - 0.3) / 0.6                  # 0.67, shrunk toward 0.6 with 15 pseudo-events
    assert abs(t["take"] - (raw_take + 15 * 0.6) / 16) < 1e-3
    assert t["group"] >= t["take"]


def test_redistribute_only_flows_down():
    group = [{"id": "a", "pos": "RB", "avail": 0.0, "car_share": .6, "tgt_share": .1},
             {"id": "b", "pos": "RB", "avail": 1.0, "car_share": .3, "tgt_share": .05},
             {"id": "c", "pos": "RB", "avail": 1.0, "car_share": .1, "tgt_share": .02}]
    out = roles.redistribute(group, group[0], take=0.5, group_take=0.8)
    assert abs(out["b"][0] - 0.3) < 1e-9 and abs(out["c"][0] - 0.18) < 1e-9      # 0.5 x .6 ; 0.3 x .6
    assert roles.redistribute(group, {**group[2], "avail": 0.0}, 0.5, 0.8) == {}   # nobody below "c"


def test_apply_inheritance_boosts_backup_and_sets_contingency():
    role = lambda cs: {"car_share": cs, "tgt_share": 0.05, "e_car": 0.6, "e_tgt": 1.4, "n": 3, "rate": 0}
    wk = lambda avail: {5: {"pts": 10.0 * avail, "bye": False, "avail": avail, "mult": 1.0}}
    proj = {"s": {"name": "Swift", "team": "CHI", "position": "RB", "rate": 15.0, "role": role(.55), "weekly": wk(0.0)},
            "m": {"name": "Monangai", "team": "CHI", "position": "RB", "rate": 8.0, "role": role(.29), "weekly": wk(1.0)}}
    pj.apply_inheritance(proj, {"CHI": {"carries": 30.0, "targets": 32.0}}, None)
    m = proj["m"]
    assert m["weekly"][5]["pts"] > 10.0 and m["weekly"][5]["inherit"][0]["from"] == "Swift"
    assert m["contingency"]["if_out"] == "Swift" and m["contingency"]["rate"] > 8.0
    assert "contingency" not in proj["s"]


def test_mark_partial_uses_this_seasons_normal():
    games = [{"season": "2025", "pct": 0.5} for _ in range(8)] + [{"season": "2026", "pct": p} for p in (.68, .69, .57, .35)]
    pj.mark_partial(games)
    assert games[-1]["partial"] and not games[-2]["partial"]
