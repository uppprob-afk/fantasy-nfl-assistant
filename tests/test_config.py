import pytest

from nfl_assistant.config import ConfigError, apply_env, load_config, parse_nicknames, parse_targets


def write(tmp_path, text):
    p = tmp_path / "config.yaml"
    p.write_text(text)
    return p


def test_parse_nicknames_and_targets():
    assert parse_nicknames("a=Al, b = Bee ,bad,c=") == {"a": "Al", "b": "Bee"}
    assert parse_targets("Player One; Player Two;;") == ["Player One", "Player Two"]


def test_env_overrides_file(tmp_path):
    p = write(tmp_path, 'league: {league_id: "1"}\nme: {username: file_user}\ntimezone: UTC\n')
    cfg = load_config(p, env={"LEAGUE_ID": " 999 ", "SLEEPER_USERNAME": "env_user",
                              "LEAGUE_TIMEZONE": "Australia/Melbourne", "NICKNAMES": "x=Ex",
                              "TARGETS": "A B;C D"})
    assert cfg["league"]["league_id"] == "999" and cfg["me"]["username"] == "env_user"
    assert cfg["timezone"] == "Australia/Melbourne" and cfg["nicknames"] == {"x": "Ex"}
    assert cfg["targets"] == ["A B", "C D"]


def test_empty_env_values_are_ignored():
    cfg = apply_env({"league": {"league_id": "1"}}, {"LEAGUE_ID": ""})
    assert cfg["league"]["league_id"] == "1"


def test_missing_league_or_user_is_a_clear_error(tmp_path):
    with pytest.raises(ConfigError, match="league ID"):
        load_config(write(tmp_path, 'league: {league_id: ""}\nme: {username: u}\n'), env={})
    with pytest.raises(ConfigError, match="username"):
        load_config(write(tmp_path, 'league: {league_id: "1"}\nme: {username: ""}\n'), env={})


def test_optional_sections_default_empty(tmp_path):
    cfg = load_config(write(tmp_path, 'league: {league_id: 123}\nme: {username: u}\n'), env={})
    assert cfg["league"]["league_id"] == "123"
    assert cfg["nicknames"] == {} and cfg["expected_settings"] == {} and cfg["targets"] == []


def test_example_config_is_valid_once_filled(tmp_path):
    from nfl_assistant.config import ROOT
    text = (ROOT / "config.example.yaml").read_text()
    cfg = load_config(write(tmp_path, text), env={"LEAGUE_ID": "1", "SLEEPER_USERNAME": "u"})
    assert cfg["api"]["base_url"].startswith("https://api.sleeper.app")
