"""Stage 5: a compact Markdown brief to paste into Claude for the weekly "NFL update".

Built only from data the pipeline has already fetched and checked, so the analysis
starts from verified facts. Pure function, no network.
"""

CHECK_LABEL = {"verified": "✓", "unverified": "UNVERIFIED", "not_checked": "–"}


def _f(n, d=1) -> str:
    return "–" if n is None else f"{n:.{d}f}"


def _who(row: dict) -> str:
    return row.get("label") or row.get("username") or "?"


def _player_line(p: dict, slot: str) -> str:
    inj = f" **{p['injury_status']}**" if p.get("injury_status") else ""
    chk = CHECK_LABEL.get((p.get("check") or {}).get("status"), "–")
    return (f"| {slot} | {p['name']}{inj} | {p['position']} {p['team']} | {_f(p.get('points'))} | "
            f"{_f(p.get('avg'))} | {p.get('games', 0)} | {chk} |")


def outlook_section(o: dict) -> list[str]:
    """This week's projection, start/sit calls, playoff odds and bye-heavy weeks."""
    out = []
    names = o.get("names", {})
    nm = lambda pid: names.get(pid, {}).get("name", pid)
    mine = next((m for m in o.get("matchups", []) if m["is_mine"]), None)
    out.append(f"## Projections (week {o['week']})")
    if mine:
        a, b = mine["teams"]
        out.append(f"- My matchup: {_f(a['mean'])} vs {_f(b['mean'])} ({b['team_name']}), "
                   f"win chance about {round(20 * a['win_prob']) * 5}% ({mine['confidence']} confidence)")
    for r in o.get("start_sit", []):
        if r["verdict"] in ("swap", "close", "problem"):
            alt = f" vs {nm(r['alt'])} {_f(r.get('alt_pts'))}" if r.get("alt") else ""
            out.append(f"- Start/sit [{r['verdict']}] {r['slot']}: {nm(r['starter'])} {_f(r['starter_pts'])}{alt}. {r['why']}")
    po = o.get("playoffs", {})
    me = next((t for t in po.get("teams", []) if t["is_mine"]), None)
    if me:
        out.append(f"- Playoff odds: {me['odds_text']} (win this week {me['if_win_text']}, lose {me['if_lose_text']}); "
                   f"projected {_f(me['proj_wins'])} wins; top {o['playoff_teams']} qualify ({po['confidence']} confidence, "
                   f"{po['sims']:,} simulations)")
        out.append("- League odds: " + ", ".join(f"{t['label']} {t['odds_text']}" for t in po["teams"]))
    for k in po.get("key_games", [])[:4]:
        if k["mine"]:
            me_a = k["a"] == o["my_roster_id"]
            opp = k["b_team"] if me_a else k["a_team"]
            w, l = (k["if_a_text"], k["if_b_text"]) if me_a else (k["if_b_text"], k["if_a_text"])
            out.append(f"- Key game: week {k['week']} vs {opp} (win {w} / lose {l})")
    lu = o.get("lineups", {}).get(str(o["my_roster_id"]), {})
    if lu:
        weak = sorted(lu.items(), key=lambda kv: kv[1]["total"])[:2]
        for w, v in weak:
            if v["byes"]:
                out.append(f"- Weak week {w}: projected {_f(v['total'])} with byes for "
                           + ", ".join(nm(p) for p in v["byes"]))
    out.append("")
    return out


def build_brief(dash: dict, faab_data: dict, scan: dict, trade_data: dict, outlook: dict | None = None) -> str:
    lg, me = dash["league"], dash["me"]
    st = next(s for s in dash["standings"] if s["roster_id"] == me["roster_id"])
    out = []
    add = out.append

    add(f"# NFL update brief: {me['team_name']} (week {lg['current_week']}, {lg['season']})")
    add("")
    add(f"_Generated {dash['generated_at']} from the Sleeper API (league {lg['id']}). "
        "Fantasy points are Sleeper's league-scored `players_points` only; my players' season totals are "
        "cross-checked against nflverse stats (✓ = within 1 pt, UNVERIFIED = differs, – = not checkable). "
        "Suggestions below are computed heuristics, not advice._")
    add("")
    add("## League settings")
    add(f"- {len(dash['standings'])} teams, lineup: {', '.join(s for s in lg['roster_positions'] if s != 'BN')} "
        f"+ {lg['roster_positions'].count('BN')} bench")
    ppr = lg.get("ppr", 1.0)
    scoring = {1.0: "Full PPR", 0.5: "Half PPR", 0: "Standard (no PPR)"}.get(ppr, f"{ppr} pts per reception")
    add(f"- {scoring}, FAAB ${lg['faab_budget']} budget; IR slots: {lg['reserve_slots']} "
        f"(IR allowed only for: {', '.join(lg['ir_allowed'])})")
    add(f"- Completed weeks: {', '.join(map(str, lg['completed_weeks'])) or 'none'}")
    add("")

    add("## Standings")
    add("| # | Team (manager) | W-L | PF | PA | Waiver |")
    add("|---|---|---|---|---|---|")
    for s in dash["standings"]:
        mark = " **(me)**" if s["roster_id"] == me["roster_id"] else ""
        rec = f"{s['wins']}-{s['losses']}" + (f"-{s['ties']}" if s.get("ties") else "")
        add(f"| {s['rank']} | {s['team_name']} ({_who(s)}){mark} | {rec} | {_f(s['points_for'])} | "
            f"{_f(s['points_against'])} | {s['waiver_position']} |")
    add("")

    mine = next((m for m in dash["matchups"]["pairs"] if m["is_mine"]), None)
    if mine and len(mine["teams"]) == 2:
        a, b = mine["teams"]
        add(f"## This week (week {dash['matchups']['week']})")
        add(f"- {a['team_name']} {_f(a['points'], 2)} vs {b['team_name']} ({_who(b)}) {_f(b['points'], 2)} "
            "(live score at time of run)")
        add("")

    add(f"## My roster ({st['wins']}-{st['losses']}, rank {st['rank']})")
    add("| Slot | Player | Pos/Team | Season pts | PPG | GP | Check |")
    add("|---|---|---|---|---|---|---|")
    for p in me["starters"]:
        if p.get("id"):
            add(_player_line(p, p["slot"]))
    for p in me["bench"]:
        add(_player_line(p, "BN"))
    for p in me["ir"]:
        add(_player_line(p, "IR"))
    unverified = [p for p in me["starters"] + me["bench"] + me["ir"]
                  if (p.get("check") or {}).get("status") == "unverified"]
    for p in unverified:
        add(f"- UNVERIFIED {p['name']}: {p['check']['reason']}")
    for n in me.get("notes", []):
        add(f"- Note: {n}")
    add("")

    injured = [p for p in me["starters"] + me["bench"] + me["ir"] if p.get("id") and p.get("injury_status")]
    if outlook:
        out.extend(outlook_section(outlook))

    add("## Injuries on my roster")
    if injured:
        for p in injured:
            part = f" ({p['injury_body_part']})" if p.get("injury_body_part") else ""
            elig = "IR-eligible" if p.get("ir_eligible") else "not IR-eligible here"
            add(f"- {p['name']} ({p['position']} {p['team']}): {p['injury_status']}{part}, {elig}")
    else:
        add("- None")
    add("")

    add("## New since last run")
    if scan.get("first_run"):
        add("- First scan: baseline saved, no comparison yet.")
    else:
        any_news = False
        for key, title in (("my_players", "My players"), ("other_starters", "Other teams' starters"),
                           ("free_agents", "Free agents")):
            for n in scan.get(key, []):
                any_news = True
                extra = f" → {n['action']}" if n.get("action") else ""
                add(f"- [{title}] {n['text']}{extra}")
        if not any_news:
            add(f"- Nothing new since {scan.get('baseline')}.")
    add("")

    add("## FAAB")
    my = next(m for m in faab_data["managers"] if m["roster_id"] == faab_data["my_roster_id"])
    add(f"- Me: ${my['remaining']} left of ${faab_data['budget']} ({my['claims']} claims won, "
        f"${my['overpaid']} paid above clearing price)")
    add("- League: " + ", ".join(f"{_who(m)} ${m['remaining']}" for m in faab_data["managers"]))
    allm = faab_data["market"].get("ALL")
    if allm:
        add(f"- Market: {allm['claims']} claims, median winning bid ${allm['median_winning_bid']}, "
            f"{allm['contested_pct']}% contested")
    for pos in ("QB", "RB", "WR", "TE"):
        m = faab_data["market"].get(pos)
        if m:
            add(f"  - {pos}: median win ${m['median_winning_bid']}; bargain ${m['bargain_bid']} / "
                f"competitive ${m['competitive_bid']} / safe ${m['safe_bid']} ({m['claims']} claims)")
    add("")

    tend = faab_data.get("tendencies")
    if tend:
        styled = [t for t in tend["profiles"] if t["style"] != "not enough bids yet" and t["roster_id"] != faab_data["my_roster_id"]]
        if styled:
            add("- Bidding styles: " + ", ".join(f"{t['label']} {t['style']} (typical ${t['typical_bid']}, max ${t['max_bid']}, "
                                                  f"${t['remaining']} left)" for t in styled))
        quiet = [t["label"] for t in tend["profiles"] if t["bids"] == 0]
        if quiet:
            add(f"- No bids yet: {', '.join(quiet)}")
        out_ = [t["label"] for t in tend["profiles"] if t["nearly_out"]]
        if out_:
            add(f"- Nearly out of FAAB: {', '.join(out_)}")
        add(f"- My waiver priority: #{tend['my_waiver_position']} (wins tied bids vs higher numbers)")
    add("")
    add("## Top waiver ideas (bargain-first bids)")
    ideas = list(scan.get("free_agents", [])) + list(faab_data.get("targets", [])) \
        + list(faab_data.get("trending_adds", []))
    seen = set()
    shown = 0
    for p in ideas:
        if p["id"] in seen or p.get("rostered_by"):
            continue
        seen.add(p["id"])
        s = p.get("suggestion") or {}
        why = p.get("reason") or (f"trending ({p['count']:,} adds/48h)" if p.get("count") else "target")
        line = f"- {p['name']} ({p['position']} {p['team']}): bid ${s.get('bid', '–')}, {why}"
        r = p.get("rivals")
        if r:
            likely = ", ".join(x["label"] for x in r["likely"]) or "none clear"
            line += f"; likely rivals: {likely}"
            e = r.get("estimate")
            if e and e.get("low") is not None:
                line += f"; rivals suggest ${e['low']}" + (f"-${e['high']}" if e["high"] != e["low"] else "")
                if e.get("wildcard"):
                    line += f" (wildcard {e['wildcard']['label']} up to ${e['wildcard']['max']})"
        add(line)
        shown += 1
        if shown == 6:
            break
    if not shown:
        add("- None")
    add("")

    add("## Top trade ideas (rest-of-season projections)")
    if trade_data.get("trades_closed"):
        add(f"- Trade deadline (week {trade_data['trade_deadline']}) has passed.")
    for t in trade_data.get("ideas", [])[:3]:
        give = " + ".join(f"{p['name']} ({p['position']}, {_f(p.get('rate'))}/wk proj)" for p in t["give"])
        get = " + ".join(f"{p['name']} ({p['position']}, {_f(p.get('rate'))}/wk proj)" for p in t["get"])
        add(f"- With {t['team_name']} ({t['manager']}): give {give} for {get}. "
            f"Me +{t['my_gain']:.0f} pts ROS, them +{t['their_gain']:.0f} ({t['balance']}, "
            f"{t.get('confidence', '?')} confidence).")
    for key, label in (("sell_high", "Sell high (mine)"), ("buy_low", "Buy low")):
        for r in trade_data.get(key, [])[:3]:
            add(f"- {label}: {r['name']} ({r['position']}, {r.get('manager', '')}): {_f(r['actual_ppg'])} ppg so far "
                f"vs {_f(r['rate'])} projected (usage suggests {_f(r.get('expected_ppg'))}).")
    if not trade_data.get("ideas"):
        add("- None found.")
    for b in trade_data.get("buyers", []):
        opts = ", ".join(p["name"] for p in b["my_options"]) or "nothing on my bench"
        add(f"- Motivated buyer: {b['manager']} lost {b['position']} {b['player']} ({b['status']}); "
            f"I could offer {opts}.")
    myteam = next((t for t in trade_data.get("teams", []) if t["is_mine"]), None)
    if myteam:
        add(f"- My projected strength vs median (pts/week): " + ", ".join(f"{k} {v:+.1f}" for k, v in myteam["vs_median"].items())
            + f"; needs {', '.join(myteam['needs']) or 'none'}; spare {', '.join(myteam['surplus']) or 'none'}")
    add("")
    warnings = dash.get("warnings", []) + faab_data.get("warnings", [])
    if warnings:
        add("## Data warnings")
        for w in warnings:
            add(f"- {w}")
        add("")
    return "\n".join(out).rstrip() + "\n"
