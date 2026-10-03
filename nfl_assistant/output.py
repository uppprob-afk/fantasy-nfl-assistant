"""Write site data files and dated snapshots."""

import json
from pathlib import Path


def write_site_data(site_data_dir: Path, name: str, obj) -> None:
    """Write <name>.json and <name>.js. The .js version lets site/index.html load the data
    with a <script> tag, which works when the page is opened straight from disk."""
    site_data_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, indent=1, ensure_ascii=False)
    (site_data_dir / f"{name}.json").write_text(text + "\n", encoding="utf-8")
    (site_data_dir / f"{name}.js").write_text(
        f"window.NFL_DATA = window.NFL_DATA || {{}};\nwindow.NFL_DATA[{json.dumps(name)}] = {text};\n",
        encoding="utf-8")


def write_snapshot(snapshot_dir: Path, name: str, obj) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{name}.json").write_text(
        json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
