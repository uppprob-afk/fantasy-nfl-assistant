from nfl_assistant.output import prune_snapshots


def make(root, day, files=("players.json", "rosters.json", "meta.json")):
    d = root / day
    d.mkdir(parents=True)
    for f in files:
        (d / f).write_text("{}")


def test_keeps_recent_days_and_the_rankings_each_week_needs(tmp_path):
    for day in ["2026-09-01", "2026-09-09", "2026-09-10", "2026-09-16", "2026-09-30", "2026-10-15", "2026-10-20"]:
        make(tmp_path, day)
    # weeks start 2026-09-10 and 2026-09-17: the backtest reads the last snapshot before each
    gone = prune_snapshots(tmp_path, "2026-10-24", ["2026-09-10", "2026-09-17"])
    left = sorted(p.name for p in tmp_path.iterdir())
    assert left == ["2026-09-09", "2026-09-16", "2026-10-15", "2026-10-20"]
    assert [f.name for f in (tmp_path / "2026-09-09").iterdir()] == ["players.json"]      # just the rankings
    assert len(list((tmp_path / "2026-10-15").iterdir())) == 3                            # recent: untouched
    assert "2026-09-01" in gone and "2026-09-09/rosters.json" in gone


def test_nothing_to_do(tmp_path):
    assert prune_snapshots(tmp_path / "missing", "2026-10-24", []) == []
    make(tmp_path, "2026-10-20")
    assert prune_snapshots(tmp_path, "2026-10-24", ["2026-09-10"]) == []
