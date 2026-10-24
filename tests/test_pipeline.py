"""End-to-end: the whole update (`run.main`) on the saved sample league, with no network.

The sample league has 4 teams, a 4-week regular season and a 1-week final (weeks 1–4, 5). Each
case runs the full pipeline at a different point of the season and checks every site data file
is written: mid-season, the last regular-season week, the fantasy playoffs and after the season
(the playoff weeks once crashed the update because no regular-season weeks were left).
"""

import json
from datetime import date, timedelta
from pathlib import Path

import pytest

from nfl_assistant import config, nflverse, run

FIX = Path(__file__).parent / "fixtures"
SITE_FILES = ["dashboard", "faab", "scanner", "trades", "outlook", "lab", "league", "teams", "cards",
              "cards_more", "model", "recap", "brief"]
TEAMS = ["BAL", "DAL", "SEA", "CAR", "HOU", "NYJ", "PIT", "CHI", "GB", "LV", "KC", "BUF"]


def load(name):
    return json.loads((FIX / name).read_text())


def schedule_csv(current_week: int) -> str:
    """Every sample team plays every week 1–18; games before the current week have scores."""
    head = "season,game_type,week,gameday,gametime,away_team,home_team,away_score,home_score,location,roof,spread_line,total_line,stadium"
    rows, start = [head], date(2026, 9, 13)
    for w in range(1, 19):
        order = TEAMS[w % len(TEAMS):] + TEAMS[:w % len(TEAMS)]
        for i in range(0, len(order), 2):
            away, home = order[i], order[i + 1]
            score = "20,24" if w < current_week else ","
            rows.append(f"2026,REG,{w},{start + timedelta(days=7 * (w - 1))},13:00,{away},{home},{score},Home,dome,-3,44,Test Field")
    return "\n".join(rows) + "\n"


class FakeSleeper:
    """The Sleeper calls the pipeline makes, answered from tests/fixtures."""

    calls = 0

    def __init__(self, week: int):
        self.week = week

    def state(self):
        return {"season": "2026", "week": self.week, "display_week": self.week, "leg": self.week}

    def league(self, league_id):
        lg = load("league.json")
        lg["league_id"] = league_id
        lg["settings"].update({"playoff_week_start": 5, "playoff_teams": 2, "playoff_round_type": 0,
                               "last_scored_leg": min(self.week - 1, 5), "trade_deadline": 4})
        return lg

    def user(self, username):
        return next((u for u in load("users.json") if u["display_name"] == username), None)

    def rosters(self, league_id):
        return load("rosters.json")

    def users(self, league_id):
        return load("users.json")

    def matchups(self, league_id, week):
        if week > 5:
            return []
        base = load("matchups_w1.json" if week % 2 else "matchups_w2.json")
        starters = {r["roster_id"]: r.get("starters") or [] for r in load("rosters.json")}
        played = week < self.week
        return [{**m, "starters": starters[m["roster_id"]],
                 "points": m["points"] if played else 0.0,
                 "players_points": m["players_points"] if played else {}} for m in base]

    def transactions(self, league_id, week):
        return [t for t in load("transactions.json") if t.get("leg") == week]

    def trending(self, kind, hours, limit):
        return []

    def players(self):
        return load("players.json")


def fake_download(current_week):
    stats = (FIX / "nflverse_weekly.csv").read_text()
    header = stats.splitlines()[0] + "\n"

    def download(url, cache_dir, max_age_hours=6):
        if "snap_counts" in url:
            return "season,week,team,player,offense_pct\n"
        if "games.csv" in url:
            return schedule_csv(current_week)
        if "injuries" in url:
            return "season,week,gsis_id,report_status,practice_status,game_type,position\n"
        return stats if "2026" in url else header        # last season: no rows
    return download


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    def go(week: int) -> dict:
        cfg = config.load_config(config.ROOT / "config.example.yaml",
                                 env={"LEAGUE_ID": "123", "SLEEPER_USERNAME": "my_username", "LEAGUE_TIMEZONE": "UTC"})
        monkeypatch.setattr(run, "load_config", lambda: cfg)
        monkeypatch.setattr(run, "ROOT", tmp_path)
        monkeypatch.setattr(run, "SleeperClient", lambda *a, **k: FakeSleeper(week))
        monkeypatch.setattr(nflverse, "download_weekly", fake_download(week))
        monkeypatch.setattr(run, "fetch_forecasts", lambda *a, **k: {})
        assert run.main() == 0
        site = tmp_path / "site" / "data"
        out = {}
        for name in SITE_FILES:
            assert (site / f"{name}.json").exists() and (site / f"{name}.js").exists(), name
            out[name] = json.loads((site / f"{name}.json").read_text())
        return out
    return go


def test_mid_season(pipeline):
    d = pipeline(3)
    assert d["outlook"]["phase"] == "regular" and d["outlook"]["weeks"] == [3, 4]
    assert d["outlook"]["playoffs"]["sims"] > 0
    assert any(m["is_mine"] for m in d["outlook"]["matchups"])


def test_last_regular_season_week(pipeline):
    d = pipeline(4)
    assert d["outlook"]["phase"] == "regular" and d["outlook"]["weeks"] == [4]


def test_fantasy_playoffs(pipeline):
    d = pipeline(5)
    o = d["outlook"]
    assert o["phase"] == "playoffs" and o["weeks"] == [5]
    assert o["playoffs"]["settled"] and {t["odds_text"].split(" ")[0] for t in o["playoffs"]["teams"]} == {"In", "Out"}
    assert d["lab"]["weeks"] == [5]                         # the Lab and lineups look at the playoff week


def test_after_the_season(pipeline, tmp_path):
    d = pipeline(6)
    assert d["outlook"]["phase"] == "over" and d["outlook"]["weeks"] == []
    # a second run reads the first run's history (snapshots, ledgers) without trouble
    d2 = pipeline(6)
    assert d2["outlook"]["phase"] == "over"
