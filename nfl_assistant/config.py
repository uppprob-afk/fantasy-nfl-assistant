"""Load settings: config.yaml (git-ignored) or config.example.yaml, then environment overrides.

Environment variables (used by GitHub Actions repository variables) win over the file:
  LEAGUE_ID, SLEEPER_USERNAME, LEAGUE_TIMEZONE,
  NICKNAMES  "username=Nick,other=Nick2"
  TARGETS    "Player One;Player Two"
"""

import os
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent


class ConfigError(Exception):
    pass


def parse_nicknames(text: str) -> dict[str, str]:
    out = {}
    for part in (text or "").split(","):
        if "=" in part:
            user, nick = part.split("=", 1)
            if user.strip() and nick.strip():
                out[user.strip()] = nick.strip()
    return out


def parse_targets(text: str) -> list[str]:
    return [t.strip() for t in (text or "").split(";") if t.strip()]


def apply_env(cfg: dict, env: dict) -> dict:
    """Override file settings with environment variables (empty values are ignored)."""
    if env.get("LEAGUE_ID"):
        cfg.setdefault("league", {})["league_id"] = env["LEAGUE_ID"].strip()
    if env.get("SLEEPER_USERNAME"):
        cfg.setdefault("me", {})["username"] = env["SLEEPER_USERNAME"].strip()
    if env.get("LEAGUE_TIMEZONE"):
        cfg["timezone"] = env["LEAGUE_TIMEZONE"].strip()
    if env.get("NICKNAMES"):
        cfg["nicknames"] = parse_nicknames(env["NICKNAMES"])
    if env.get("TARGETS"):
        cfg["targets"] = parse_targets(env["TARGETS"])
    return cfg


def load_config(path: Path | str | None = None, env: dict | None = None) -> dict:
    if path is None:
        path = ROOT / "config.yaml"
        if not Path(path).exists():
            path = ROOT / "config.example.yaml"
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f) or {}
    cfg = apply_env(cfg, os.environ if env is None else env)
    cfg["nicknames"] = cfg.get("nicknames") or {}
    cfg["expected_settings"] = cfg.get("expected_settings") or {}
    cfg["targets"] = cfg.get("targets") or []
    if not str(cfg.get("league", {}).get("league_id") or "").strip():
        raise ConfigError("No league ID set. Copy config.example.yaml to config.yaml and fill in "
                          "league.league_id, or set the LEAGUE_ID environment variable.")
    if not str(cfg.get("me", {}).get("username") or "").strip():
        raise ConfigError("No Sleeper username set. Fill in me.username in config.yaml, "
                          "or set the SLEEPER_USERNAME environment variable.")
    cfg["league"]["league_id"] = str(cfg["league"]["league_id"])
    return cfg
