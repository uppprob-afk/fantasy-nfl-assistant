"""Advice scorecard: did following the dashboard's advice actually win points?

Every run saves the advice it is showing (`save`), per week:
- start / sit: each "start X over Y" from the win-chance plan (or the slot-by-slot swaps when
  there's no plan). Advice whose players haven't played yet is replaced by the latest run's; once
  one of its players has played it is frozen, so what's graded is the last advice before kickoff.
- waivers: the top "upgrade" bid ideas and who you'd cut for them (frozen once the week is over).
- sell-high: players flagged as scoring above their usage, with their points per game so far.

`grade` scores it against what happened, using league-scored points per player per week
(Sleeper, or calculated from NFL stats for free agents):
- start / sit is right when the player we said to start outscored the one we said to sit;
  "followed" means he was actually in your lineup and the other wasn't.
- waiver adds: points per game since the advice vs the player you'd have cut.
- sell-high: points per game since the flag vs before it (did he cool off?).
Pure functions apart from the small history file.
"""

import json
from pathlib import Path


def _load(path: Path) -> dict:
    return json.loads(path.read_text()) if path.exists() else {}


def save(path: Path, week: int, startsit: list[dict], locked: set[str], waivers: list[dict], sell: list[dict]) -> dict:
    """Record this run's advice for `week`; returns the whole history."""
    data = _load(path)
    wk = data.setdefault(str(week), {"startsit": {}, "waivers": {}, "sell": {}})
    old = wk.get("startsit", {})
    keep = {k: v for k, v in old.items() if v["in"] in locked or (v["out"] and v["out"] in locked)}
    for s in startsit:
        k = f"{s['in']}>{s['out']}"
        if k not in keep:
            keep[k] = s
    wk["startsit"] = keep
    for w in waivers:
        wk["waivers"].setdefault(w["id"], w)
    for s in sell:
        wk["sell"].setdefault(s["id"], s)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, sort_keys=True) + "\n")
    return data


def _ppg(points: dict, pid: str, weeks: list[int]) -> tuple[float | None, int]:
    vals = [points[pid][w] for w in weeks if w in (points.get(pid) or {})]
    return (round(sum(vals) / len(vals), 1), len(vals)) if vals else (None, 0)


def grade(history: dict, completed: list[int], points: dict[str, dict[int, float]],
          lineups: dict[int, set[str]], names: dict) -> dict:
    """points: player -> {week: league points}; lineups: week -> my starters that week."""
    nm = lambda p: names.get(p, p)
    ss, wv, sl = [], [], []
    for wkey, adv in sorted(history.items(), key=lambda kv: int(kv[0])):
        w = int(wkey)
        if w not in completed:
            continue
        mine = lineups.get(w, set())
        for a in adv.get("startsit", {}).values():
            pin, pout = (points.get(a["in"]) or {}).get(w), (points.get(a["out"]) or {}).get(w) if a.get("out") else 0.0
            if pin is None and pout is None:
                continue
            pin, pout = pin or 0.0, pout or 0.0
            ss.append({"week": w, "in": a["in"], "out": a.get("out"), "in_name": nm(a["in"]), "out_name": nm(a.get("out")) if a.get("out") else None,
                       "in_pts": round(pin, 1), "out_pts": round(pout, 1), "diff": round(pin - pout, 1),
                       "right": pin > pout, "followed": a["in"] in mine and (not a.get("out") or a["out"] not in mine)})
        later = [x for x in completed if x >= w]
        for a in adv.get("waivers", {}).values():
            got, n = _ppg(points, a["id"], later)
            drop = a.get("drop")
            cut, _ = _ppg(points, drop, later) if drop else (None, 0)
            if got is None:
                continue
            wv.append({"week": w, "id": a["id"], "name": nm(a["id"]), "bid": a.get("bid"), "ppg": got, "games": n,
                       "drop": drop, "drop_name": nm(drop) if drop else None, "drop_ppg": cut,
                       "right": cut is None or got > cut})
        for a in adv.get("sell", {}).values():
            after, n = _ppg(points, a["id"], [x for x in completed if x >= w])
            if after is None or a.get("ppg") is None:
                continue
            sl.append({"week": w, "id": a["id"], "name": nm(a["id"]), "before": a["ppg"], "after": after, "games": n,
                       "right": after < a["ppg"]})
    fol = [x for x in ss if x["followed"]]
    ign = [x for x in ss if not x["followed"]]
    summary = {
        "startsit": {"calls": len(ss), "right": sum(x["right"] for x in ss),
                     "followed": len(fol), "gained": round(sum(x["diff"] for x in fol), 1),
                     "missed": round(sum(x["diff"] for x in ign if x["right"]), 1)},
        "waivers": {"calls": len(wv), "right": sum(x["right"] for x in wv)},
        "sell": {"calls": len(sl), "right": sum(x["right"] for x in sl)},
    }
    return {"summary": summary, "startsit": ss[::-1], "waivers": wv[::-1], "sell": sl[::-1],
            "first_week": min((int(k) for k in history), default=None)}
