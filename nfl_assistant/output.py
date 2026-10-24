"""Write site data files and dated snapshots."""

import json
import shutil
from datetime import date, timedelta
from pathlib import Path


def write_site_data(site_data_dir: Path, name: str, obj) -> None:
    """Write <name>.json and <name>.js. The .js version lets site/index.html load the data
    with a <script> tag, which works when the page is opened straight from disk."""
    site_data_dir.mkdir(parents=True, exist_ok=True)
    text = json.dumps(obj, separators=(",", ":"), ensure_ascii=False)   # compact: ~35% smaller for phones
    (site_data_dir / f"{name}.json").write_text(text + "\n", encoding="utf-8")
    (site_data_dir / f"{name}.js").write_text(
        f"window.NFL_DATA = window.NFL_DATA || {{}};\nwindow.NFL_DATA[{json.dumps(name)}] = {text};\n",
        encoding="utf-8")


def write_snapshot(snapshot_dir: Path, name: str, obj) -> None:
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    (snapshot_dir / f"{name}.json").write_text(
        json.dumps(obj, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def prune(obj):
    """Drop None values (recursively) to keep large payloads small; the site treats a
    missing field like null."""
    if isinstance(obj, dict):
        return {k: prune(v) for k, v in obj.items() if v is not None}
    if isinstance(obj, list):
        return [prune(v) for v in obj]
    return obj


def prune_snapshots(snap_root: Path, today: str, first_gamedays: list[str], keep_days: int = 14) -> list[str]:
    """Delete old dated snapshots, keeping what later runs read: everything from the last
    `keep_days` days, and for older days only players.json from the last snapshot before each
    week's first game (the model's backtest uses Sleeper's rankings as of then). Returns the
    deleted paths (relative to `snap_root`)."""
    if not snap_root.exists():
        return []
    cutoff = (date.fromisoformat(today) - timedelta(days=keep_days)).isoformat()
    dates = sorted(d.name for d in snap_root.iterdir() if d.is_dir())
    with_players = [d for d in dates if (snap_root / d / "players.json").exists()]
    needed = {max(before) for g in first_gamedays if (before := [d for d in with_players if d < g])}
    gone = []
    for d in dates:
        if d >= cutoff:
            continue
        folder = snap_root / d
        if d in needed:
            for f in folder.iterdir():
                if f.name != "players.json":
                    f.unlink()
                    gone.append(f"{d}/{f.name}")
        else:
            shutil.rmtree(folder)
            gone.append(d)
    return gone

