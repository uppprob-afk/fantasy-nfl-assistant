"""Make a shareable copy of the built site with league-identifying names replaced.

    uv run python -m nfl_assistant.anonymize [output_dir]     (default: demo/)

Manager usernames, team names, nicknames, the league name and the league ID are swapped
for neutral placeholders ("Manager A", "Team Alpha", ...). NFL player names are public
and kept. Useful for screenshots and demos; the original site/ is not touched.
"""

import json
import re
import shutil
import sys
from pathlib import Path

from .config import ROOT

TEAM_NAMES = ["Alpha", "Bravo", "Charlie", "Delta", "Echo", "Foxtrot", "Golf", "Hotel", "India",
              "Juliet", "Kilo", "Lima", "Mike", "November", "Oscar", "Papa", "Quebec", "Romeo",
              "Sierra", "Tango"]


def build_mapping(dashboard: dict) -> dict[str, str]:
    """Real string -> placeholder, from the dashboard's standings and league info."""
    mapping = {}
    for i, s in enumerate(sorted(dashboard["standings"], key=lambda x: x["roster_id"])):
        letter = chr(ord("A") + i) if i < 26 else str(i)
        mapping[s["username"]] = f"Manager {letter}"
        if s.get("team_name") and s["team_name"] != s["username"]:
            mapping[s["team_name"]] = f"Team {TEAM_NAMES[i % len(TEAM_NAMES)]}"
        if s.get("nickname"):
            mapping[s["nickname"]] = f"Nick {letter}"
    lg = dashboard.get("league", {})
    if lg.get("name"):
        mapping[lg["name"]] = "Demo League"
    if lg.get("id"):
        mapping[str(lg["id"])] = "000000000000000000"
    return mapping


def anonymize_text(text: str, mapping: dict[str, str]) -> str:
    """Replace whole-word occurrences, longest first (so a label like 'Nick (username)' is handled cleanly)."""
    for real in sorted(mapping, key=len, reverse=True):
        pattern = r"(?<![\w])" + re.escape(real) + r"(?![\w])"
        text = re.sub(pattern, mapping[real].replace("\\", r"\\"), text)
    return text


def main(argv: list[str]) -> int:
    out = Path(argv[1]) if len(argv) > 1 else ROOT / "demo"
    src = ROOT / "site"
    dash_path = src / "data" / "dashboard.json"
    if not dash_path.exists():
        print("No site data yet. Run: uv run python -m nfl_assistant.run")
        return 1
    mapping = build_mapping(json.loads(dash_path.read_text(encoding="utf-8")))
    if out.exists():
        shutil.rmtree(out)
    shutil.copytree(src, out)
    for f in (out / "data").iterdir():
        if f.suffix in (".json", ".js", ".md"):
            f.write_text(anonymize_text(f.read_text(encoding="utf-8"), mapping), encoding="utf-8")
    print(f"Anonymized copy written to {out} ({len(mapping)} names replaced). Open {out}/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
