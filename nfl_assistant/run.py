"""Run the whole pipeline:  uv run python -m nfl_assistant.run"""

import csv
import io
import json
import math
import sys
from collections import defaultdict
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from . import brief, cards, dashboard, faab, factors, lab, league, lineups, model, nflverse, outlook, projections, roles, scanner, teams, tendencies, trades, waivers
from .config import ROOT, ConfigError, load_config
from .output import write_site_data, write_snapshot
from .players import find_player, ir_allowed_statuses, player_brief, player_name, slim_players
from .sleeper import SleeperClient


class PipelineError(Exception):
    pass


def say(msg: str) -> None:
    print(msg, flush=True)


# --- fetch ------------------------------------------------------------------
def fetch(client: SleeperClient, cfg: dict) -> dict:
    league_id = cfg["league"]["league_id"]
    say("Fetching league data from Sleeper...")
    state = client.state()
    league = client.league(league_id)
    if not league:
        raise PipelineError(f"league {league_id} not found on Sleeper. Check config.yaml.")
    me = client.user(cfg["me"]["username"])
    if not me:
        raise PipelineError(f"Sleeper user '{cfg['me']['username']}' not found.")
    rosters = client.rosters(league_id)
    users = client.users(league_id)
    my_roster = next((r for r in rosters if r.get("owner_id") == me["user_id"]
                      or me["user_id"] in (r.get("co_owners") or [])), None)
    if not my_roster:
        raise PipelineError(f"'{me['display_name']}' doesn't own a roster in this league.")

    settings = league["settings"]
    start = settings.get("start_week", 1)
    current_week = max(int(state.get("display_week") or state.get("week") or 1), 1)
    if state.get("season") != league.get("season"):
        current_week = start  # league season hasn't started yet
    last_scored = int(settings.get("last_scored_leg") or current_week - 1)
    weeks = range(start, current_week + 1)

    matchups = {w: client.matchups(league_id, w) for w in weeks}
    reg_end = int(settings.get("playoff_week_start") or 15) - 1
    future = {w: client.matchups(league_id, w) for w in range(current_week + 1, reg_end + 1)}
    transactions = {w: client.transactions(league_id, w) for w in weeks}
    say("Fetching trending players...")
    trending = {"add": client.trending("add", 48, 60), "drop": client.trending("drop", 48, 60)}
    say("Loading the NFL player database (cached, at most one download per run)...")
    players = client.players()
    say(f"  Season {league['season']}, week {current_week}; {last_scored} week(s) completed.")
    return {"state": state, "league": league, "me": me, "rosters": rosters, "users": users,
            "my_roster": my_roster, "current_week": current_week,
            "completed_weeks": list(range(start, last_scored + 1)),
            "matchups": matchups, "future_matchups": future, "transactions": transactions, "trending": trending,
            "players": players}


# --- stage 1 ----------------------------------------------------------------
def build_dashboard(ctx: dict, cfg: dict, managers: dict, cache_dir, now) -> dict:
    league, players, my_roster = ctx["league"], ctx["players"], ctx["my_roster"]
    settings, completed = league["settings"], ctx["completed_weeks"]
    warnings = dashboard.check_settings(league, cfg.get("expected_settings", {}))
    present = {m["username"] for m in managers.values()}
    for username in cfg.get("nicknames", {}):
        if username not in present:
            warnings.append(f"Nickname configured for '{username}', but no such manager is in the league.")

    points = dashboard.weekly_points({w: m for w, m in ctx["matchups"].items() if w in completed})
    say("Cross-checking my players' points against nflverse...")
    try:
        url = cfg["crosscheck"]["nflverse_url"].format(season=league["season"])
        rows = nflverse.parse_rows(nflverse.download_weekly(url, cache_dir))
        checks = nflverse.crosscheck(list(my_roster.get("players") or []), players, points, completed,
                                     rows, league["scoring_settings"], cfg["crosscheck"]["tolerance_points"])
    except Exception as exc:  # second source down shouldn't stop the dashboard
        warnings.append(f"Couldn't load nflverse stats for the cross-check ({exc}). Points shown are Sleeper's only.")
        checks = {}
    played = {pid: set(c["played_weeks"]) for pid, c in checks.items()}

    ir_allowed = ir_allowed_statuses(settings)
    reserve_slots = settings.get("reserve_slots", 0)
    budget = settings.get("waiver_budget", 0)

    def view(r):
        return dashboard.roster_view(r, players, points, completed, league["roster_positions"],
                                     ir_allowed, reserve_slots, played)

    my_view = view(my_roster)
    for row in my_view["starters"] + my_view["bench"] + my_view["ir"]:
        if row.get("id"):
            row["check"] = checks.get(row["id"], {"status": "not_checked"})
    all_rosters = []
    for r in sorted(ctx["rosters"], key=lambda r: r["roster_id"]):
        v = my_view if r is my_roster else view(r)
        all_rosters.append({**managers[r["roster_id"]], **v, "is_mine": r is my_roster})

    return {
        "generated_at": now.isoformat(timespec="minutes"),
        "league": {"id": league["league_id"], "name": league["name"], "season": league["season"],
                   "current_week": ctx["current_week"], "completed_weeks": completed,
                   "roster_positions": league["roster_positions"], "faab_budget": budget,
                   "ppr": league["scoring_settings"].get("rec", 0),
                   "ir_allowed": sorted(ir_allowed), "reserve_slots": reserve_slots},
        "me": {**managers[my_roster["roster_id"]], **my_view},
        "standings": dashboard.standings(ctx["rosters"], managers, budget),
        "matchups": {"week": ctx["current_week"],
                     "pairs": dashboard.matchup_pairs(ctx["matchups"].get(ctx["current_week"], []),
                                                      managers, my_roster["roster_id"])},
        "rosters": all_rosters,
        "warnings": warnings,
        "_checks": checks,
        "_points": points,
    }


# --- stage 2 ----------------------------------------------------------------
def build_faab(ctx: dict, cfg: dict, managers: dict, now) -> dict:
    league, players, rosters = ctx["league"], ctx["players"], ctx["rosters"]
    settings = league["settings"]
    budget = settings.get("waiver_budget", 0)
    txs = [t for week in sorted(ctx["transactions"]) for t in ctx["transactions"][week]]
    log = faab.waiver_log(txs, players, managers, settings.get("waiver_bid_min", 0))
    per_manager, warnings = faab.manager_faab(txs, rosters, managers, budget, log)
    market = faab.market_prices(log, faab.all_bids(txs, players))
    my_id = ctx["my_roster"]["roster_id"]
    my_left = next(m["remaining"] for m in per_manager if m["roster_id"] == my_id)

    rostered = {pid for r in rosters for pid in (r.get("players") or [])}
    trending_adds = faab.trending_free_agents(ctx["trending"]["add"], rostered, players)
    trending_drops = faab.trending_free_agents(ctx["trending"]["drop"], rostered, players)
    for i, p in enumerate(trending_adds):
        p["suggestion"] = faab.bid_suggestion(p["position"], market, my_left, "hot" if i < 5 else "warm")

    targets = []
    for name in cfg.get("targets") or []:
        pid = find_player(name, players)
        if not pid:
            warnings.append(f"Target '{name}' wasn't found in Sleeper's player list. Check the spelling in config.yaml.")
            continue
        p = player_brief(pid, players)
        owner = next((managers[r["roster_id"]]["label"] for r in rosters if pid in (r.get("players") or [])), None)
        p.update({"rostered_by": owner,
                  "suggestion": faab.bid_suggestion(p["position"], market, my_left, "warm"),
                  "comparables": faab.comparable_claims(p["position"], log)})
        targets.append(p)

    return {
        "generated_at": now.isoformat(timespec="minutes"),
        "budget": budget, "min_bid": settings.get("waiver_bid_min", 0), "my_roster_id": my_id,
        "my_remaining": my_left,
        "managers": per_manager,
        "waiver_log": log,
        "other_moves": faab.other_moves(txs, players, managers),
        "market": market,
        "targets": targets,
        "trending_adds": trending_adds,
        "trending_drops": trending_drops,
        "warnings": warnings,
    }


# --- stage 3 ----------------------------------------------------------------
def load_previous(snap_root: Path) -> dict | None:
    """The most recent saved snapshot (read before this run overwrites today's)."""
    if not snap_root.exists():
        return None
    for d in sorted((p for p in snap_root.iterdir() if p.is_dir()), reverse=True):
        if (d / "players.json").exists() and (d / "rosters.json").exists():
            meta = json.loads((d / "meta.json").read_text()) if (d / "meta.json").exists() else {}
            return {"date": d.name, "generated_at": meta.get("generated_at", d.name),
                    "players": json.loads((d / "players.json").read_text()),
                    "rosters": json.loads((d / "rosters.json").read_text())}
    return None


def season_table(points: dict, completed: list[int]) -> dict[str, dict]:
    """player_id -> {points, games, avg} over completed weeks (league scoring)."""
    return {pid: {k: v for k, v in dashboard.season_summary(w, completed).items() if k != "weekly"}
            for pid, w in points.items()}


def build_scanner(ctx: dict, prev: dict | None, managers: dict, dash: dict, faab_data: dict,
                  season: dict, news_path: Path, now) -> dict:
    run_at = now.isoformat(timespec="minutes")
    log = json.loads(news_path.read_text()) if news_path.exists() else []
    if prev is None:
        result = {"my_players": [], "other_starters": [], "free_agents": [], "motivated_buyers": []}
    else:
        result = scanner.scan(prev["players"], ctx["players"], prev["rosters"], ctx["rosters"],
                              ctx["my_roster"]["roster_id"], managers, set(dash["league"]["ir_allowed"]),
                              dash["me"]["ir_open"], season)
        for row in result["free_agents"]:
            demand = "hot" if row["kind"] == "backup" else "warm"
            row["suggestion"] = faab.bid_suggestion(row["position"], faab_data["market"],
                                                    faab_data["my_remaining"], demand)
    new_items = scanner.news_items(result, run_at)
    cutoff = (now - timedelta(days=7)).isoformat(timespec="minutes")
    recent = [n for n in log if n["seen"] >= cutoff]
    keep = (now - timedelta(days=60)).isoformat(timespec="minutes")
    news_path.parent.mkdir(parents=True, exist_ok=True)
    news_path.write_text(json.dumps([n for n in log if n["seen"] >= keep] + new_items, indent=1) + "\n")
    return {
        "generated_at": run_at,
        "baseline": prev and prev["generated_at"],
        "first_run": prev is None,
        **result,
        "recent": sorted(recent, key=lambda n: n["seen"], reverse=True),
    }


# --- stage 4 ----------------------------------------------------------------
def recent_buyers(scan: dict) -> list[dict]:
    """Motivated buyers from this run plus trade openings logged in the last 7 days."""
    buyers = {(b["roster_id"], b["position"]): b for b in scan["motivated_buyers"]}
    for n in scan["recent"]:
        if n.get("section") == "other_starters" and (n.get("action") or "").startswith("Trade opening"):
            key = (n["roster_id"], n["position"])
            buyers.setdefault(key, {"roster_id": n["roster_id"], "manager": n["manager"],
                                    "position": n["position"], "player": n["name"],
                                    "status": n.get("new"), "seen": n["seen"]})
    return list(buyers.values())


def load_nflverse(cfg: dict, season: str, cache_dir: Path) -> dict:
    """Stats (this + last season), snap counts (both) and the schedule, cached on disk."""
    pc = cfg["projections"]
    prior = str(int(season) - 1)
    long = pc.get("prior_season_cache_hours", 168)
    get = lambda url, hours=6: nflverse.parse_rows(nflverse.download_weekly(url, cache_dir, hours))
    stats_url = cfg["crosscheck"]["nflverse_url"]
    return {"this": get(stats_url.format(season=season)),
            "prior": get(stats_url.format(season=prior), long),
            "snaps": get(pc["snaps_url"].format(season=prior), long) + get(pc["snaps_url"].format(season=season)),
            "games": list(csv.DictReader(io.StringIO(nflverse.download_weekly(pc["schedule_url"], cache_dir)))),
            "injuries": _optional_rows(pc.get("injuries_url", INJURIES_URL), [prior, season], cache_dir, long)}


INJURIES_URL = "https://github.com/nflverse/nflverse-data/releases/download/injuries/injuries_{season}.csv"


def _optional_rows(url: str, seasons: list[str], cache_dir: Path, long_hours: float) -> list[dict]:
    """Rows for each season; a missing file (e.g. not published yet) is skipped, not fatal."""
    out = []
    for i, s in enumerate(seasons):
        try:
            out += nflverse.parse_rows(nflverse.download_weekly(url.format(season=s), cache_dir,
                                                                long_hours if i == 0 else 6))
        except Exception as exc:  # noqa: BLE001 - optional data
            say(f"  (skipped {url.format(season=s)}: {exc})")
    return out


def fetch_forecasts(sched: dict, today: str, cache_dir: Path) -> dict:
    """(week, team) -> {wind, temp, precip} at kickoff for outdoor games in the next 7 days."""
    out = {}
    for w, home, day, hour in factors.games_needing_forecast(sched, today):
        lat, lon = factors.STADIUMS[home]
        try:
            payload = json.loads(nflverse.download_weekly(factors.FORECAST_URL.format(lat=lat, lon=lon), cache_dir, 3))
        except Exception as exc:  # noqa: BLE001 - forecasts are optional
            say(f"  (no forecast for {home}: {exc})")
            continue
        fc = factors.forecast_at(payload, day, hour)
        if fc:
            out[(w, home)] = fc
            out[(w, sched[w][home]["opp"])] = fc
    return out


def starter_counts(teams: int, slots: list[str]) -> dict[str, int]:
    """How many players at each position start league-wide in a typical week (flex split RB/WR)."""
    flex = sum(s in lineups.FLEX_ELIGIBLE for s in slots)
    return {"QB": teams * slots.count("QB") + 2, "RB": int(teams * (slots.count("RB") + flex / 2)),
            "WR": int(teams * (slots.count("WR") + flex / 2)), "TE": teams * slots.count("TE"),
            "K": teams * max(slots.count("K"), 1), "DEF": teams * max(slots.count("DEF"), 1)}


def build_model(ctx: dict, nfl: dict) -> dict:
    """Backtest the projection model on this season's completed weeks and learn settings."""
    league = ctx["league"]
    slots = lineups.lineup_slots(league["roster_positions"])
    starters = starter_counts(league.get("total_rosters") or 10, slots)
    season = league["season"]
    prior = str(int(season) - 1)
    rows = nfl["prior"] + nfl["this"]
    logs = projections.game_logs(rows, nfl["snaps"], league["scoring_settings"])
    dlogs = projections.def_logs(rows, nfl["games"], league["scoring_settings"])
    scheds = {s: projections.schedule(nfl["games"], s) for s in (prior, season)}
    base = {"availability": factors.learn_availability(nfl.get("injuries") or [], logs),
            "weather": factors.learn_weather({**logs, **{f"DEF:{t}": v for t, v in dlogs.items()}}, scheds),
            "inherit": roles.learn_take(logs)}
    records = model.backtest_records(nfl["prior"], nfl["this"], nfl["snaps"], nfl["games"],
                                     league["scoring_settings"], season, starters, ctx["completed_weeks"])
    learned = model.learn(records, base)
    return {"records": records, "learned": learned,
            "backtest": model.evaluate(records, learned["params"]),
            "backtest_default": model.evaluate(records, None)}


def build_projections(ctx: dict, nfl: dict, params: dict | None = None, today: str | None = None,
                      cache_dir: Path | None = None) -> tuple[dict, list[int], list[str]]:
    """Projections for rostered players, relevant free agents and every defence."""
    league, players = ctx["league"], ctx["players"]
    slots = lineups.lineup_slots(league["roster_positions"])
    teams = league.get("total_rosters") or 10
    reg_end = int(league["settings"].get("playoff_week_start") or 15) - 1
    weeks = list(range(ctx["current_week"], reg_end + 1))
    starters = starter_counts(teams, slots)
    rostered = {pid for r in ctx["rosters"] for pid in (r.get("players") or [])}
    candidates = set(rostered) | {
        pid for pid, p in players.items()
        if p.get("team") and p.get("position") in projections.POSITIONS
        and (p.get("position") == "DEF" or (p.get("depth_chart_order") or 99) <= 3
             or (p.get("search_rank") or 10**9) <= 400)}
    proj = projections.build(players, candidates, nfl["prior"], nfl["this"], nfl["snaps"], nfl["games"],
                             league["scoring_settings"], league["season"], weeks, starters,
                             playoff_weeks(league["settings"]), params,
                             factors.current_practice(nfl.get("injuries") or [], league["season"], ctx["current_week"]),
                             fetch_forecasts(projections.schedule(nfl["games"], league["season"]), today, cache_dir)
                             if today and cache_dir else {})
    return proj, weeks, slots


def playoff_weeks(settings: dict) -> list[int]:
    """Fantasy playoff weeks from Sleeper settings (round type 1 = two-week final,
    2 = every round is two weeks). NFL regular season ends in week 18."""
    start = int(settings.get("playoff_week_start") or 15)
    rounds = max(1, math.ceil(math.log2(max(int(settings.get("playoff_teams") or 4), 2))))
    kind = int(settings.get("playoff_round_type") or 0)
    n = rounds * 2 if kind == 2 else rounds + 1 if kind == 1 else rounds
    return [w for w in range(start, start + n) if w <= 18]


def roster_limit(league: dict) -> int:
    """Active roster size (starters + bench; IR and taxi slots don't count)."""
    return sum(1 for s in league["roster_positions"] if s not in ("IR", "TAXI"))


def history_view(ctx: dict, managers: dict, slots: list[str]) -> dict:
    """Season-so-far strength (actual started lineups) and trades made, per team."""
    position = {pid: p.get("position") for pid, p in ctx["players"].items() if p.get("position")}
    strength = trades.season_strength(ctx["matchups"], ctx["completed_weeks"], slots, position)
    txs = [t for week in sorted(ctx["transactions"]) for t in ctx["transactions"][week]]
    made = trades.trades_made(txs)
    my_rid = ctx["my_roster"]["roster_id"]
    teams = [{**managers[rid], **s, "trades": made.get(rid, 0), "is_mine": rid == my_rid}
             for rid, s in sorted(strength.items(), key=lambda kv: -kv[1]["actual"])]
    return {"weeks": len(ctx["completed_weeks"]), "teams": teams,
            "median": next(iter(strength.values()))["median"] if strength else {},
            "trades_made": {str(k): v for k, v in made.items()}}


def build_trades(ctx: dict, managers: dict, proj: dict, weeks: list[int], slots: list[str],
                 scan: dict, now) -> dict:
    players, rosters = ctx["players"], ctx["rosters"]
    my_rid = ctx["my_roster"]["roster_id"]
    rostered = {pid for r in rosters for pid in (r.get("players") or [])}
    owners = {pid: r["roster_id"] for r in rosters for pid in (r.get("players") or [])}
    repl = projections.replacement_rates(proj, rostered)
    valuer = trades.Valuer(proj, weeks, slots, roster_size=roster_limit(ctx["league"]),
                           reserve={p for r in rosters for p in (r.get("reserve") or [])}, repl=repl)
    profiles = trades.league_profiles(rosters, valuer)
    names = {pid: player_brief(pid, players)["name"] for pid in proj}

    def card(pid):
        p = proj.get(pid)
        out = player_brief(pid, players)
        if p:
            out.update({k: p[k] for k in ("rate", "sd", "confidence", "ros", "byes", "actual_ppg",
                                          "expected_ppg", "prior_ppg", "games_this", "games_prior",
                                          "partial_weeks", "team_changed")})
            out["vor"] = projections.value_over_replacement(p, repl, len(weeks))
        return out

    ideas = [trades.explain(t, proj, profiles, my_rid, names, managers[t["roster_id"]]["label"], len(weeks))
             for t in trades.find_trades(my_rid, rosters, proj, valuer, profiles)]
    for t in ideas:
        t["give"] = [card(p) for p in t["give"]]
        t["get"] = [card(p) for p in t["get"]]
        t["team_name"] = managers[t["roster_id"]]["team_name"]
    buyers = trades.pitches_for_buyers(recent_buyers(scan), my_rid, rosters, proj, profiles)
    for b in buyers:
        b["my_options"] = [card(p) for p in b["my_options"]]
    bs = projections.buy_sell(proj, owners, my_rid)
    for key in bs:
        bs[key] = [{**card(r["id"]), **r, "manager": managers[r["roster_id"]]["label"]} for r in bs[key][:8]]

    teams = []
    for rid, p in sorted(profiles.items(), key=lambda kv: -kv[1]["score"]):
        teams.append({**managers[rid], "per_week": p["per_week"], "ros_total": p["lineup_total"],
                      "strength": p["strength"], "vs_median": p["vs_median"], "depth": p["depth"],
                      "needs": p["needs"], "surplus": p["surplus"], "is_mine": rid == my_rid})
    values = sorted((dict(card(pid), roster_id=owners[pid], manager=managers[owners[pid]]["label"])
                     for pid in rostered if pid in proj), key=lambda r: -r["vor"])
    trade_deadline = ctx["league"]["settings"].get("trade_deadline")
    return {"generated_at": now.isoformat(timespec="minutes"), "my_roster_id": my_rid,
            "slots": slots, "weeks": weeks, "median": next(iter(profiles.values()))["median"],
            "replacement": repl, "teams": teams, "ideas": ideas, "buyers": buyers,
            "buy_low": bs["buy_low"], "sell_high": bs["sell_high"], "values": values,
            "trade_deadline": trade_deadline, "current_week": ctx["current_week"],
            "history": history_view(ctx, managers, slots),
            "trades_closed": bool(trade_deadline and ctx["current_week"] > int(trade_deadline))}


# --- part 2: matchups, start/sit, lineups, playoffs --------------------------------
def pairs_by_week(entries: list[dict]) -> list[tuple[int, int]]:
    groups = defaultdict(list)
    for m in entries:
        if m.get("matchup_id") is not None:
            groups[m["matchup_id"]].append(m["roster_id"])
    return [tuple(sorted(g)) for _, g in sorted(groups.items()) if len(g) == 2]


def sim_schedule(ctx: dict, weeks: list[int]) -> dict[int, list[tuple[int, int]]]:
    """Remaining regular-season pairings: this week plus future weeks from Sleeper."""
    cw = ctx["current_week"]
    sched = {cw: pairs_by_week(ctx["matchups"].get(cw, []))}
    for w, entries in ctx.get("future_matchups", {}).items():
        sched[w] = pairs_by_week(entries)
    return {w: g for w, g in sched.items() if w in weeks}


def sim_standings(rosters: list[dict]) -> dict[int, dict]:
    return {r["roster_id"]: {"wins": r["settings"].get("wins", 0), "losses": r["settings"].get("losses", 0),
                             "ties": r["settings"].get("ties", 0),
                             "pf": r["settings"].get("fpts", 0) + r["settings"].get("fpts_decimal", 0) / 100}
            for r in rosters}


def build_outlook(ctx: dict, managers: dict, proj: dict, weeks: list[int], slots: list[str], now) -> dict:
    league, players, rosters = ctx["league"], ctx["players"], ctx["rosters"]
    my_rid = ctx["my_roster"]["roster_id"]
    cw = ctx["current_week"]
    roster_of = {r["roster_id"]: r.get("players") or [] for r in rosters}
    names = {}

    def name(pid):
        if pid not in names:
            b = player_brief(pid, players)
            names[pid] = {"name": b["name"], "position": b["position"], "team": b["team"],
                          "injury_status": b["injury_status"],
                          "confidence": (proj.get(pid) or {}).get("confidence")}
        return pid

    # this week: set lineups, live + projected
    this = {}
    for m in ctx["matchups"].get(cw, []):
        starters = m.get("starters") or []
        tw = outlook.team_week(starters, m.get("players_points") or {}, proj, cw)
        tw["confidence"] = outlook.matchup_confidence(starters, proj, cw)
        for row in tw["players"]:
            if row["id"]:
                name(row["id"])
        this[m["roster_id"]] = {**tw, "matchup_id": m.get("matchup_id"), "starters": starters}
    matchups = []
    for a, b in pairs_by_week(ctx["matchups"].get(cw, [])):
        if a not in this or b not in this:
            continue
        pa = outlook.win_probability(this[a], this[b])
        if b == my_rid:
            a, b, pa = b, a, 1 - pa
        conf = min(this[a]["confidence"], this[b]["confidence"], key=["low", "medium", "high"].index)
        matchups.append({"is_mine": a == my_rid, "confidence": conf,
                         "teams": [{**managers[a], **this[a], "win_prob": round(pa, 3)},
                                   {**managers[b], **this[b], "win_prob": round(1 - pa, 3)}]})
    matchups.sort(key=lambda x: not x["is_mine"])

    my_starters = this.get(my_rid, {}).get("starters", [])
    sit = outlook.start_sit(my_starters, roster_of[my_rid], proj, cw, slots)
    for r in sit:
        name(r["starter"])
        if r["alt"]:
            name(r["alt"])

    # optimal lineups for every remaining week, every team
    lineups_by_team = {}
    for rid, pids in roster_of.items():
        lineups_by_team[rid] = {}
        for w in weeks:
            ow = outlook.optimal_week(pids, proj, w, slots)
            for x in ow["lineup"]:
                name(x["id"])
            for b in ow["byes"]:
                name(b)
            lineups_by_team[rid][w] = ow

    # playoff odds
    sched = sim_schedule(ctx, weeks)
    dist = {}
    for rid in roster_of:
        for w in weeks:
            if w == cw and rid in this:
                dist[(rid, w)] = (this[rid]["mean"], this[rid]["sd"])
            else:
                ow = lineups_by_team[rid][w]
                dist[(rid, w)] = (ow["total"], ow["sd"])
    strength = {rid: outlook.team_strength_sd(pids, proj, slots, weeks[-1]) for rid, pids in roster_of.items()}
    standings = sim_standings(rosters)
    n_playoff = int(league["settings"].get("playoff_teams") or 4)
    seed = int(now.strftime("%Y%m%d"))
    sim = outlook.simulate(standings, sched, dist, strength, n_playoff, seed=seed)
    done = len(ctx["completed_weeks"])
    conf = "low" if done < 5 else "medium" if done < 9 else "high"
    this_games = [g for g in sim["games"] if g[0] == cw]
    teams = []
    for rid in roster_of:
        g = next((x for x in this_games if rid in (x[1], x[2])), None)
        if_win = if_lose = None
        if g:
            if_a, if_b = outlook.conditional_odds(sim, g, rid)
            if_win, if_lose = (if_a, if_b) if g[1] == rid else (if_b, if_a)
        odds = sim["made"].get(rid, 0) / sim["n"]
        teams.append({**managers[rid], **standings[rid], "odds": round(odds, 3),
                      "odds_text": outlook.round_odds(odds, conf),
                      "seed1": round(sim["seed1"].get(rid, 0) / sim["n"], 3),
                      "proj_wins": round(sim["avg_wins"][rid], 1),
                      "if_win": if_win, "if_lose": if_lose,
                      "if_win_text": outlook.round_odds(if_win, conf) if if_win is not None else None,
                      "if_lose_text": outlook.round_odds(if_lose, conf) if if_lose is not None else None,
                      "is_mine": rid == my_rid})
    teams.sort(key=lambda t: -t["odds"])
    keys = []
    for k in outlook.key_games(sim, my_rid):
        keys.append({**k, "a_label": managers[k["a"]]["label"], "b_label": managers[k["b"]]["label"],
                     "a_team": managers[k["a"]]["team_name"], "b_team": managers[k["b"]]["team_name"],
                     "if_a_text": outlook.round_odds(k["if_a"], conf), "if_b_text": outlook.round_odds(k["if_b"], conf)})
    return {"generated_at": now.isoformat(timespec="minutes"), "week": cw, "weeks": weeks,
            "reg_season_end": weeks[-1] if weeks else cw, "playoff_teams": n_playoff,
            "my_roster_id": my_rid, "slots": slots, "matchups": matchups, "start_sit": sit,
            "lineups": {str(rid): {str(w): v for w, v in ws.items()} for rid, ws in lineups_by_team.items()},
            "managers": {str(rid): managers[rid] for rid in roster_of},
            "playoffs": {"teams": teams, "key_games": keys, "sims": sim["n"], "confidence": conf,
                         "completed_weeks": done},
            "names": names}


# --- NFL teams: depth charts, position strength, roles ------------------------------
def build_teams(ctx: dict, nfl: dict, proj: dict, managers: dict, now) -> tuple[dict, dict]:
    """(teams page data, Sleeper id -> role) for all 32 teams."""
    league, players = ctx["league"], ctx["players"]
    season = league["season"]
    rows = nfl["prior"] + nfl["this"]
    logs = projections.game_logs(rows, nfl["snaps"], league["scoring_settings"])
    dlogs = projections.def_logs(rows, nfl["games"], league["scoring_settings"])
    sched = projections.schedule(nfl["games"], season)
    _, by_gsis, by_name = nflverse.index_rows(rows)
    relevant = {pid: p for pid, p in players.items() if p.get("team") and p.get("position") in teams.POSITIONS}
    ids = {pid: nid for pid, p in relevant.items() if (nid := nflverse.match_player(p, by_gsis, by_name))}
    owners = {pid: managers[r["roster_id"]]["team_name"] for r in ctx["rosters"] for pid in (r.get("players") or [])}
    totals = teams.team_week_totals(logs, season)
    depth, roles = teams.build(relevant, logs, ids, season, owners, proj)
    names = {t: player_name(players.get(t), t) for t in depth}
    next_week = min((w for w in sched if w >= ctx["current_week"]
                     and any(not g.get("played") for g in sched[w].values())), default=ctx["current_week"])
    return ({"generated_at": now.isoformat(timespec="minutes"), "week": next_week, "names": names,
             "offence": teams.offence(totals, nfl["games"], sched, season, next_week),
             "strength": teams.position_strength(totals, dlogs, sched, season), "depth": depth,
             "opportunities": teams.opportunities(proj, owners)}, roles)


# --- model scorecard (backtest + live ledger + what it learned) ----------------------
def build_model_page(ctx: dict, mdl: dict, proj: dict, points: dict, extra_ids: list[str], now,
                     data_dir: Path) -> dict:
    """Save this run's projections to the live ledger, score past ones, record the settings."""
    players = ctx["players"]
    rostered = {pid for r in ctx["rosters"] for pid in (r.get("players") or [])}
    ids = rostered | set(extra_ids)
    names = {pid: player_name(players.get(pid), pid) for pid in ids}
    led = model.ledger_update(data_dir / "projection_ledger.json", proj, names, ids)
    actual: dict[str, dict[int, float]] = {}
    for e in led.values():
        pid, w = e["id"], e["week"]
        if w in (points.get(pid) or {}):
            actual.setdefault(pid, {})[w] = points[pid][w]
        elif pid in proj:
            g = next((x for x in proj[pid]["log"] if x["week"] == w), None)
            actual.setdefault(pid, {})[w] = g["pts"] if g else 0.0
    live = model.ledger_score({k: e for k, e in led.items() if e["id"] in actual}, ctx["completed_weeks"], actual)
    hist = model.history_update(data_dir / "model_history.json", ctx["current_week"], now.isoformat(timespec="minutes"),
                                mdl["learned"], mdl["backtest"])
    learned = {k: v for k, v in mdl["learned"].items()}
    return {"generated_at": now.isoformat(timespec="minutes"), "my_roster_id": ctx["my_roster"]["roster_id"],
            "my_players": sorted(ctx["my_roster"].get("players") or []),
            "learned": learned, "defaults": projections.params_or_default(None),
            "backtest": mdl["backtest"], "backtest_default": mdl["backtest_default"],
            "live": live, "history": hist,
            "settings": {"min_games": model.MIN_GAMES_TO_TUNE, "min_improvement": model.MIN_IMPROVEMENT,
                         "shrink_games": model.SHRINK_GAMES}}


# --- waiver targets (ranked by what they add to my team) ----------------------------
def build_available(ctx: dict, proj: dict, weeks: list[int], slots: list[str], faab_data: dict) -> list[str]:
    """Best available players per position with the points each would add to my team.
    Stored as faab_data["available"]; returns their ids (they get player cards too)."""
    players, rosters = ctx["players"], ctx["rosters"]
    rostered = {pid for r in rosters for pid in (r.get("players") or [])}
    ids = waivers.pool(proj, rostered)
    valuer = trades.Valuer(proj, weeks, slots, roster_size=roster_limit(ctx["league"]),
                           reserve={p for r in rosters for p in (r.get("reserve") or [])})
    mine = list(ctx["my_roster"].get("players") or [])
    ranks = cards.position_ranks(proj)
    trending = {t.get("player_id"): t.get("count", 0) for t in ctx["trending"]["add"]}
    out = []
    for pid in ids:
        pr = proj[pid]
        g = waivers.my_gain(valuer, mine, pid, proj, len(weeks))
        out.append({**player_brief(pid, players), "proj_rate": pr["rate"], "ros": pr["ros"],
                    "proj_confidence": pr["confidence"], "pos_rank": ranks.get(pid, (None, None))[0],
                    "gain": g["gain"], "gain_per_week": g["per_week"], "fit": g["fit"],
                    "drop": [{"id": d, "name": player_name(players.get(d), d)} for d in g["drop"]],
                    "trending": trending.get(pid)})
    out.sort(key=lambda p: (-p["gain"], -p["ros"]))
    faab_data["available"] = out
    return ids


# --- part 3: manager tendencies ----------------------------------------------------
def build_tendencies(ctx: dict, faab_data: dict, proj: dict, outlook_data: dict, scan: dict) -> None:
    """Add manager bidding profiles and likely rivals to the FAAB (and scanner) data."""
    players, rosters = ctx["players"], ctx["rosters"]
    my_rid = ctx["my_roster"]["roster_id"]
    txs = [t for week in sorted(ctx["transactions"]) for t in ctx["transactions"][week]]
    bids = tendencies.bids_by_manager(txs, players)
    profs = tendencies.profiles(bids, faab_data["managers"], faab_data["waiver_log"], faab_data["budget"])
    for r in rosters:
        profs[r["roster_id"]]["waiver_position"] = (r.get("settings") or {}).get("waiver_position")
    weeks = outlook_data["weeks"]
    week = ctx["current_week"] + 1 if ctx["current_week"] + 1 in weeks else ctx["current_week"]
    lineups = {int(rid): v[str(week)]["lineup"] for rid, v in outlook_data["lineups"].items() if str(week) in v}
    my_waiver = profs[my_rid]["waiver_position"]

    def attach(p, hot):
        pr = proj.get(p["id"])
        if not pr:
            return
        pts = pr["weekly"].get(week, {}).get("pts", pr["rate"])
        p["proj_week"] = round(pts, 1)
        p["proj_rate"] = pr["rate"]
        p["proj_confidence"] = pr["confidence"]
        p["rivals"] = tendencies.rivals(p["position"], pts, my_rid, profs, lineups, my_waiver, hot)

    for i, p in enumerate(faab_data["trending_adds"]):
        attach(p, hot=i < 5)
    for p in faab_data["targets"]:
        if not p.get("rostered_by"):
            attach(p, hot=False)
    for p in scan.get("free_agents", []):
        attach(p, hot=p.get("kind") == "backup")
    min_bid = faab_data["min_bid"] or 0
    for p in faab_data.get("available", []):
        attach(p, hot=False)
        likely = len((p.get("rivals") or {}).get("likely", []))
        d = waivers.demand(likely)
        who = (f"would start for {likely} rival{'s' if likely != 1 else ''}" if likely else "no rival clearly needs them")
        args = (p["position"], faab_data["market"], faab_data["my_remaining"], d)
        if p["fit"] == "upgrade":
            sug = faab.bid_suggestion(*args, context=f"Upgrades your lineup by {p['gain_per_week']:+.1f} pts/wk and {who}")
        elif p["fit"] == "depth":
            contested = likely >= 2
            sug = faab.bid_suggestion(*args, level="competitive_bid" if contested else "bargain_bid",
                                      context=f"Useful depth for you (+{p['gain_per_week']:.1f} pts/wk, mostly bye and injury cover) and {who}"
                                              + ("; a mid-range bid gives you a fair shot without overpaying" if contested
                                                 else "; not worth a bidding war"))
        else:
            sug = {**faab.bid_suggestion(*args), "bid": min_bid, "level": None,
                   "reason": "Wouldn't improve your lineup right now, so the minimum bid (or a free pickup after waivers clear)."
                             + (f" Note: {who}." if likely else "")}
        p["suggestion"] = sug
    faab_data["tendencies"] = {
        "week": week, "my_waiver_position": my_waiver,
        "min_bids_for_style": tendencies.MIN_BIDS_FOR_STYLE,
        "profiles": sorted((v for k, v in profs.items()), key=lambda v: (v["roster_id"] != my_rid, -v["bids"])),
    }


# --- league views (Home + League tabs) ----------------------------------------------
def build_league(ctx: dict, trade_data: dict, outlook_data: dict, now, data_dir: Path) -> dict:
    weekly, medians = league.weekly_scores(ctx["matchups"], ctx["completed_weeks"])
    ap = league.all_play(weekly)
    hist = {t["roster_id"]: t for t in trade_data["history"]["teams"]}
    power, weights = league.power_rankings(
        {rid: t["actual"] for rid, t in hist.items()},
        {t["roster_id"]: t["per_week"] for t in trade_data["teams"]},
        {rid: t.get("efficiency") for rid, t in hist.items()}, len(ctx["completed_weeks"]))
    odds = {t["roster_id"]: t["odds"] for t in outlook_data["playoffs"]["teams"]}
    history = league.update_odds_history(data_dir / "odds_history.json", now.isoformat(timespec="minutes"),
                                         ctx["current_week"], odds)
    return {"generated_at": now.isoformat(timespec="minutes"), "my_roster_id": ctx["my_roster"]["roster_id"],
            "weeks": ctx["completed_weeks"],
            "weekly": {str(k): v for k, v in weekly.items()}, "medians": {str(k): v for k, v in medians.items()},
            "all_play": {str(k): v for k, v in ap.items()}, "power": power, "power_weights": weights,
            "odds_history": history}


# --- trade lab / planner data ------------------------------------------------------
def build_lab(ctx: dict, managers: dict, proj: dict, weeks: list[int], slots: list[str],
              outlook_data: dict, trade_data: dict) -> dict:
    this_week = {}
    for m in outlook_data["matchups"]:
        for t in m["teams"]:
            this_week[t["roster_id"]] = {
                "mean": t["mean"], "sd": t["sd"], "starters": t["starters"],
                "actual": {r["id"]: r["pts"] for r in t["players"] if r["id"] and r["status"] == "played"}}
    names = {pid: {"name": player_brief(pid, ctx["players"])["name"]} for pid in proj}
    roster_size = roster_limit(ctx["league"])
    return lab.build_lab_data(proj, weeks, slots, ctx["rosters"], managers, names,
                              sim_standings(ctx["rosters"]), sim_schedule(ctx, weeks), this_week,
                              ctx["my_roster"]["roster_id"], outlook_data["playoff_teams"],
                              outlook_data["playoffs"]["confidence"], trade_data["replacement"],
                              roster_size, ctx["current_week"])


# --- player cards ----------------------------------------------------------------
def build_cards(ctx: dict, proj: dict, points: dict, weeks: list[int], nfl: dict, trade_data: dict,
                extra: list[str] | None = None) -> dict:
    """player_id -> card (last 3 / next 3 weeks, log, usage, value) for every rostered player
    plus `extra` (the waiver pool)."""
    sched = projections.schedule(nfl["games"], ctx["league"]["season"])
    ranks = cards.position_ranks(proj)
    flags = {r["id"]: "sell-high" for r in trade_data.get("sell_high", [])}
    flags.update({r["id"]: "buy-low" for r in trade_data.get("buy_low", [])})
    rostered = {pid for r in ctx["rosters"] for pid in (r.get("players") or [])}
    league = ctx["league"]
    starters = starter_counts(league.get("total_rosters") or 10, lineups.lineup_slots(league["roster_positions"]))
    return {pid: cards.build_card(pid, proj.get(pid), points.get(pid, {}), ctx["completed_weeks"], sched,
                                  ranks, trade_data["replacement"], len(weeks), flags, starters)
            for pid in rostered | set(extra or [])}


# --- main -------------------------------------------------------------------
def main() -> int:
    try:
        cfg = load_config()
    except ConfigError as exc:
        say(f"ERROR: {exc}")
        return 1
    now = datetime.now(ZoneInfo(cfg.get("timezone") or "UTC"))
    api = cfg["api"]
    cache_dir = ROOT / "data" / "cache"
    site_data = ROOT / "site" / "data"
    snap_dir = ROOT / "data" / "snapshots" / now.strftime("%Y-%m-%d")
    client = SleeperClient(api["base_url"], api["delay_seconds"], api["max_retries"],
                           api["timeout_seconds"], cache_dir)
    try:
        ctx = fetch(client, cfg)
    except PipelineError as exc:
        say(f"ERROR: {exc}")
        return 1
    managers = dashboard.manager_lookup(ctx["users"], ctx["rosters"], cfg.get("nicknames", {}))

    dash = build_dashboard(ctx, cfg, managers, cache_dir, now)
    checks = dash.pop("_checks")
    points = dash.pop("_points")
    say("Building FAAB and transactions tracker...")
    faab_data = build_faab(ctx, cfg, managers, now)
    say("Scanning for injuries and opportunities since the last run...")
    prev = load_previous(snap_dir.parent)
    season = season_table(points, ctx["completed_weeks"])
    scan = build_scanner(ctx, prev, managers, dash, faab_data, season,
                         ROOT / "data" / "news_log.json", now)
    say("Building projections from nflverse stats, snap counts and the schedule...")
    nfl = load_nflverse(cfg, ctx["league"]["season"], cache_dir)
    say("Checking how accurate the projections have been and learning from it...")
    mdl = build_model(ctx, nfl)
    proj, proj_weeks, slots = build_projections(ctx, nfl, mdl["learned"]["params"], now.date().isoformat(), cache_dir)
    say("Looking for trade ideas...")
    trade_data = build_trades(ctx, managers, proj, proj_weeks, slots, scan, now)
    pool_ids = build_available(ctx, proj, proj_weeks, slots, faab_data)
    # cards for every projected player (rostered, waiver pool and the rest) - player search uses them
    all_cards = build_cards(ctx, proj, points, proj_weeks, nfl, trade_data, list(set(pool_ids) | set(proj)))
    say("Building NFL depth charts and team strength...")
    teams_data, roles = build_teams(ctx, nfl, proj, managers, now)
    for pid, card in all_cards.items():
        if pid in roles:
            card["role"] = {k: v for k, v in roles[pid].items() if k not in ("id", "owner", "proj")}
        if pid in proj and proj[pid].get("contingency") and card.get("role"):
            card["role"]["contingency"] = proj[pid]["contingency"]
    say("Projecting matchups and simulating the season...")
    outlook_data = build_outlook(ctx, managers, proj, proj_weeks, slots, now)
    lab_data = build_lab(ctx, managers, proj, proj_weeks, slots, outlook_data, trade_data)
    league_data = build_league(ctx, trade_data, outlook_data, now, ROOT / "data")
    say("Profiling manager bidding habits...")
    build_tendencies(ctx, faab_data, proj, outlook_data, scan)

    write_site_data(site_data, "dashboard", dash)
    write_site_data(site_data, "faab", faab_data)
    write_site_data(site_data, "scanner", scan)
    write_site_data(site_data, "trades", trade_data)
    write_site_data(site_data, "outlook", outlook_data)
    write_site_data(site_data, "lab", lab_data)
    write_site_data(site_data, "league", league_data)
    write_site_data(site_data, "teams", teams_data)
    write_site_data(site_data, "cards", all_cards)
    write_site_data(site_data, "model", build_model_page(ctx, mdl, proj, points, pool_ids, now, ROOT / "data"))
    brief_md = brief.build_brief(dash, faab_data, scan, trade_data, outlook_data)
    (site_data / "claude_brief.md").write_text(brief_md, encoding="utf-8")
    write_site_data(site_data, "brief", {"generated_at": now.isoformat(timespec="minutes"), "markdown": brief_md})

    write_snapshot(snap_dir, "meta", {"generated_at": now.isoformat(timespec="minutes")})
    write_snapshot(snap_dir, "state", ctx["state"])
    write_snapshot(snap_dir, "league", ctx["league"])
    write_snapshot(snap_dir, "rosters", ctx["rosters"])
    write_snapshot(snap_dir, "users", ctx["users"])
    write_snapshot(snap_dir, "matchups", {str(w): m for w, m in ctx["matchups"].items()})
    write_snapshot(snap_dir, "transactions", {str(w): t for w, t in ctx["transactions"].items()})
    write_snapshot(snap_dir, "trending", ctx["trending"])
    rostered = {pid for r in ctx["rosters"] for pid in (r.get("players") or [])}
    write_snapshot(snap_dir, "players", slim_players(ctx["players"], rostered))
    write_snapshot(snap_dir, "crosscheck", checks)
    write_snapshot(snap_dir, "projections", {pid: {k: p[k] for k in ("rate", "sd", "confidence", "ros")}
                                             for pid, p in proj.items()})

    say(f"\nDone. {client.calls} Sleeper API calls. Snapshot saved to {snap_dir.relative_to(ROOT)}/")
    say(f"My team: {dash['me']['team_name']} ({dash['me']['label']})")
    unverified = [pid for pid, c in checks.items() if c["status"] == "unverified"]
    n_ver = sum(1 for c in checks.values() if c["status"] == "verified")
    say(f"Cross-check: {n_ver} verified, {len(unverified)} unverified.")
    say(f"FAAB: ${faab_data['my_remaining']} left; {len(faab_data['waiver_log'])} waiver claims logged this season.")
    if scan["first_run"]:
        say("Scanner: first run, so this one just saves a baseline to compare against next time.")
    else:
        say(f"Scanner (since {scan['baseline']}): {len(scan['my_players'])} on my team, "
            f"{len(scan['other_starters'])} other starters, {len(scan['free_agents'])} free agents.")
    me_po = next(t for t in outlook_data["playoffs"]["teams"] if t["is_mine"])
    my_mu = next((m for m in outlook_data["matchups"] if m["is_mine"]), None)
    if my_mu:
        say(f"This week: {round(100 * my_mu['teams'][0]['win_prob'])}% to win "
            f"({my_mu['teams'][0]['mean']} vs {my_mu['teams'][1]['mean']}).")
    say(f"Playoff odds: {me_po['odds_text']} (if win {me_po['if_win_text']}, if lose {me_po['if_lose_text']}).")
    say(f"Trades: {len(trade_data['ideas'])} ideas, {len(trade_data['buyers'])} motivated buyer(s).")
    for w in dash["warnings"] + faab_data["warnings"]:
        say(f"WARNING: {w}")
    say("Claude brief written to site/data/claude_brief.md")
    say("Open site/index.html to view.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
