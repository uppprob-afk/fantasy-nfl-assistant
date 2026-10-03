import csv
import json
from pathlib import Path

import pytest

FIX = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIX / name).read_text())


@pytest.fixture
def league():
    return load("league.json")


@pytest.fixture
def users():
    return load("users.json")


@pytest.fixture
def rosters():
    return load("rosters.json")


@pytest.fixture
def players():
    return load("players.json")


@pytest.fixture
def matchups_by_week():
    return {1: load("matchups_w1.json"), 2: load("matchups_w2.json")}


@pytest.fixture
def nflverse_rows():
    with open(FIX / "nflverse_weekly.csv") as f:
        return list(csv.DictReader(f))
