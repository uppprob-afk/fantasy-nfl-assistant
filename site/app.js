/* Fantasy NFL Assistant: renders the data written by the Python pipeline.
   Data arrives via <script> tags as window.NFL_DATA.<name> so the page works from file://. */
(function () {
  "use strict";
  const DATA = window.NFL_DATA || {};
  const D = DATA.dashboard;

  // ---------- helpers ----------
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const num = (n, d = 1) => (n == null ? "–" : Number(n).toFixed(d));
  const $ = (id) => document.getElementById(id);

  function injuryChip(p) {
    if (!p.injury_status) return "";
    const cls = p.injury_status === "Questionable" ? "q" : "inj";
    const title = p.injury_body_part ? ` title="${esc(p.injury_body_part)}"` : "";
    return `<span class="chip ${cls}"${title}>${esc(p.injury_status)}</span>`;
  }
  function checkChip(p) {
    const c = p.check;
    if (!c) return "";
    if (c.status === "unverified")
      return `<span class="chip unv" title="${esc(c.reason)}">unverified</span>`;
    if (c.status === "verified")
      return `<span class="chip ok" title="Matches nflverse stats (within 1 pt)">✓</span>`;
    return "";
  }
  function managerName(m) {
    return m.nickname
      ? `${esc(m.username)} <span class="chip nick">${esc(m.nickname)}</span>`
      : esc(m.username);
  }

  // ---------- player row: last 3 vs next 3, tap for details ----------
  const CARDS = (D && D.cards) || {};

  // ---------- holds (stashed players) and quick actions ----------
  let HOLDS = new Set((() => { try { return JSON.parse(localStorage.getItem("holds") || "[]"); } catch (e) { return []; } })());
  const isHeld = (pid) => HOLDS.has(pid);
  const ownerOf = (pid) => (DATA.lab && DATA.lab.players[pid] ? DATA.lab.players[pid].o : undefined);
  const myRid = () => (DATA.lab ? DATA.lab.my_roster_id : D && D.me.roster_id);
  function actionButtons(pid) {
    const o = ownerOf(pid);
    if (o === undefined) return "";
    if (o === myRid()) {
      return `<button type="button" class="mini" data-act="shop" data-pid="${esc(pid)}">Shop in Trade Lab</button>
        <button type="button" class="mini ${isHeld(pid) ? "on" : ""}" data-act="hold" data-pid="${esc(pid)}"
          title="Held players are never suggested for trades, cuts or drops">${isHeld(pid) ? "Held ✓" : "Hold (stash)"}</button>`;
    }
    if (o === null) return `<button type="button" class="mini" data-act="plan-add" data-pid="${esc(pid)}">Plan pickup</button>`;
    return `<button type="button" class="mini" data-act="trade-for" data-pid="${esc(pid)}">Trade for in Lab</button>`;
  }
  const one = (n) => (n == null ? "–" : Number(n).toFixed(1));
  const POS_ABBR = { QB: "QB", RB: "RB", WR: "WR", TE: "TE", K: "K", DEF: "DEF" };

  // Finish tier for a positional finish: boom (top half of starters), start, mid, bust.
  function tierOf(c, finish) {
    const t = c.tiers;
    if (!t || finish == null) return "none";
    return finish <= t.boom ? "boom" : finish <= t.start ? "start" : finish <= t.bust ? "mid" : "bust";
  }
  const MU_MARK = { easy: `<span class="mk easy" title="Easy matchup">▲</span>`, tough: `<span class="mk tough" title="Tough matchup">▼</span>` };
  const oppLabel = (w) => (w.bye ? "BYE" : `${w.home === false ? "@" : ""}${w.opp || ""}`);

  // Last 3 as finish pills (points + positional finish, coloured by tier); next 3 as matchups.
  function pills(c, pos) {
    const ab = POS_ABBR[pos] || pos || "";
    const past = c.last3.map((w) => {
      if (w.bye) return `<span class="pill none"><b>bye</b><i>W${w.week}</i></span>`;
      if (!w.played && w.pts == null) return `<span class="pill none"><b>–</b><i>W${w.week} DNP</i></span>`;
      const pts = (w.pts == null ? (w.calc != null ? "≈" + one(w.calc) : "n/r") : one(w.pts)) + (w.partial ? "*" : "");
      return `<span class="pill f-${tierOf(c, w.finish)}" title="Week ${w.week}${w.opp ? " vs " + esc(w.opp) : ""}"><b>${pts}</b><i>${
        w.finish ? ab + w.finish : "W" + w.week}</i></span>`;
    }).join("");
    const next = c.next3.map((w) => w.bye
      ? `<span class="pill nx none"><b>bye</b><i>W${w.week}</i></span>`
      : `<span class="pill nx ${w.matchup !== "neutral" ? "mu-" + w.matchup : ""}" title="Week ${w.week}: ${w.matchup} matchup"><b>${one(w.pts)}${MU_MARK[w.matchup] || ""}</b><i>${esc(oppLabel(w))}</i></span>`).join("");
    const arrow = { up: `<span class="trend up">▲</span>`, down: `<span class="trend down">▼</span>` }[c.trend] || "";
    return `<div class="pills">
      <div class="pl-row"><span class="pl-k">Last 3</span><div class="pl-set">${past}</div><span class="pl-avg">${one(c.last3_avg)}<small>avg</small></span></div>
      <div class="pl-row"><span class="pl-k">Next 3</span><div class="pl-set">${next}</div><span class="pl-avg">${arrow}${one(c.next3_avg)}<small>proj</small></span></div>
    </div>`;
  }

  const pct = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
  const tileHtml = (k, v, sub, cls) => `<div class="tile ${cls || ""}"><div class="k">${k}</div><div class="v">${v}</div>${sub ? `<div class="s">${sub}</div>` : ""}</div>`;

  // ---------- NFL teams: links, role section, team sheet ----------
  const TM = DATA.teams;
  const teamLink = (t) => (TM && t && TM.depth && TM.depth[t]
    ? `<button type="button" class="tlink" data-act="team" data-team="${esc(t)}" title="${esc((TM.names || {})[t] || t)} depth chart">${esc(t)}</button>` : esc(t || ""));
  const LABEL_CLS = { "Locked in": "balanced", "Starter": "balanced", "Lead role": "balanced", "Rising": "balanced",
    "Committee": "q", "One injury away": "ok-style", "Losing work": "lopsided", "Depth": "", "Unproven": "", "Backup": "" };
  const roleChip = (label) => `<span class="chip ${LABEL_CLS[label] || ""}">${esc(label)}</span>`;
  const KIND_TXT = { carry: "of RB carries", target: "of targets", snap: "of snaps" };
  function roleSection(c) {
    const r = c.role;
    if (!r) return "";
    const ordinalPos = r.order ? `${esc(r.pos)}${r.order}` : esc(r.pos);
    const weeks = (r.weeks || []).slice(-6).map((w) => `<span class="pill ${w.opportunity ? "f-start" : w.partial ? "none" : "f-mid"}" title="Week ${w.week}${
        w.partial ? ": left early / limited" : w.opportunity ? ": someone ahead of him left early or sat" : ""}"><b>${w.share == null ? "–" : Math.round(100 * w.share) + "%"}${w.partial ? "*" : w.opportunity ? "↑" : ""}</b><i>W${w.week}${w.snap != null ? " · " + Math.round(100 * w.snap) + "% sn" : ""}</i></span>`).join("");
    return `<div class="pd-sec"><div class="pd-h">Role · ${teamLink(r.team)} depth chart</div>
      <div>${roleChip(r.label)} <b>${ordinalPos}</b>${r.ahead && r.ahead.length ? ` behind ${r.ahead.map(esc).join(", ")}` : ""}${r.behind && r.behind.length ? ` · ahead of ${r.behind.map(esc).join(", ")}` : ""}</div>
      <div class="subtle" style="margin:4px 0 8px">${esc(r.reason)}</div>
      ${weeks ? `<div class="pd-h" style="margin-bottom:4px">Share ${KIND_TXT[r.kind] || ""} by week</div><div class="role-weeks">${weeks}</div>
      <div class="subtle">* left early or limited snaps · ↑ someone ahead of him left early or sat (an opportunity, not his normal role). Normal-role weeks drive the label.</div>` : ""}</div>`;
  }

  function teamSheet(t) {
    const S = TM.strength, O = (TM.offence || {})[t] || {}, D2 = TM.depth[t] || {};
    const tier = (rank) => (rank <= 8 ? "f-start" : rank > 24 ? "f-bust" : "f-mid");
    const ord = (n) => (n ? ordinal(n) : "–");
    const rows = ["QB", "RB", "WR", "TE", "K", "DEF"].filter((pos) => S[pos]).map((pos) => {
      const x = S[pos], ppg = x.ppg[t], rk = x.rank[t], al = x.allowed[t], ark = x.allowed_rank[t];
      const vs = ppg != null && x.median != null ? ppg - x.median : null;
      return `<tr><td><b>${pos}</b></td><td>${ppg != null ? num(ppg) : "–"}<div class="subtle" style="font-size:11px">${vs != null ? `${vs >= 0 ? "+" : ""}${num(vs)} vs median` : ""}</div></td>
        <td><span class="fin ${rk ? tier(rk) : ""}">${ord(rk)}</span></td>
        <td>${pos === "DEF" || al == null ? "–" : num(al)}</td><td>${pos === "DEF" || !ark ? "–" : `<span class="fin ${tier(ark)}">${ord(ark)}</span>`}</td></tr>`;
    }).join("");
    const owner = (o) => (o == null ? `<span class="subtle">free agent</span>` : o === D.me.team_name ? `<b>you</b>` : esc(o));
    const depth = ["QB", "RB", "WR", "TE", "K"].filter((pos) => D2[pos] && D2[pos].length).map((pos) => `<div class="pd-h" style="margin-top:14px">${pos}</div>
      <div class="dc">${D2[pos].map((r) => `<div class="dc-row"><span class="dc-o">${r.order || "–"}</span>
        <div class="dc-n"><div><b>${esc(r.name)}</b>${r.status ? ` <span class="chip ${r.status === "Questionable" ? "q" : "inj"}">${esc(r.status)}</span>` : ""} ${roleChip(r.label)}</div>
          <div class="subtle">${r.share != null && r.kind ? `${Math.round(100 * r.share)}% ${KIND_TXT[r.kind]}` : ""}${r.ppg != null ? `${r.share != null && r.kind ? " · " : ""}${num(r.ppg)} pts/g` : ""} · ${owner(r.owner)}</div></div></div>`).join("")}</div>`).join("");
    return `<div class="subtle">${O.points_pg != null ? `<b>${num(O.points_pg)}</b> pts/g (${ord(O.ranks && O.ranks.points_pg)})` : ""}${
        O.plays_pg != null ? ` · <b>${num(O.plays_pg)}</b> plays/g (${ord(O.ranks && O.ranks.plays_pg)})` : ""}${
        O.pass_rate != null ? ` · pass rate ${Math.round(100 * O.pass_rate)}%` : ""}${
        O.next_opp ? ` · week ${esc(TM.week)}: ${O.next_home ? "vs" : "@"} ${esc(O.next_opp)}${O.implied_next ? `, expected ${num(O.implied_next)} pts` : ""}` : ""}</div>
      <h2 style="font-size:1rem;margin-top:14px">Fantasy production by position</h2>
      <div class="card table-wrap"><table class="named"><thead><tr><th>Pos</th><th>Scores /g</th><th>Rank</th><th>Allows</th><th>Rank</th></tr></thead><tbody>${rows}</tbody></table></div>
      <p class="subtle">Points per game this season (league scoring) produced by the position group, ranked 1–32. "Allows" = what their defence gives up to that position (1st = allows the most, so the best matchup).</p>
      <h2 style="font-size:1rem">Depth chart</h2>${depth}`;
  }
  function openTeam(t) {
    if (!TM || !TM.depth[t]) return;
    $("team-title").textContent = `${(TM.names || {})[t] || t}`;
    $("team-body").innerHTML = teamSheet(t);
    const d = $("team-sheet");
    if (d.showModal) d.showModal(); else d.setAttribute("open", "");
  }
  function teamsTable(sortPos) {
    const S = TM.strength, keys = Object.keys(TM.depth).sort();
    const sorted = keys.slice().sort((a, b) => (S[sortPos].rank[a] || 99) - (S[sortPos].rank[b] || 99));
    const cell = (pos, t) => { const r = S[pos] && S[pos].rank[t]; return r ? `<span class="fin ${r <= 8 ? "f-start" : r > 24 ? "f-bust" : "f-mid"}">${r}</span>` : "–"; };
    return `<div class="card table-wrap"><table class="named"><thead><tr><th>Team</th><th>QB</th><th>RB</th><th>WR</th><th>TE</th><th class="hide-xs">Pts/g</th></tr></thead>
      <tbody>${sorted.map((t) => `<tr class="team-row" data-act="team" data-team="${esc(t)}"><td class="team-cell"><div class="t">${esc(t)}</div><div class="m">${esc((TM.names || {})[t] || "")}</div></td>
        <td>${cell("QB", t)}</td><td>${cell("RB", t)}</td><td>${cell("WR", t)}</td><td>${cell("TE", t)}</td>
        <td class="hide-xs">${TM.offence[t] && TM.offence[t].points_pg != null ? num(TM.offence[t].points_pg) : "–"}</td></tr>`).join("")}</tbody></table></div>
      <p class="subtle">League rank (1–32) of each team's fantasy points per game at the position this season. Tap a team for its depth chart.</p>`;
  }

  const PRACTICE = { dnp: "didn't practice", limited: "limited practice", full: "full practice" };
  function wxText(wx) {
    if (!wx) return "";
    if (wx.roof === "dome" || wx.roof === "closed") return "indoors";
    const bits = [];
    if (wx.wind != null) bits.push(`${Math.round(wx.wind)} mph wind`);
    if (wx.temp != null) bits.push(`${Math.round(wx.temp)}°F`);
    return (wx.roof === "open" ? "open roof" : "outdoors") + (bits.length ? ` · ${bits.join(", ")}${wx.forecast ? " forecast" : ""}` : "");
  }
  function gameDayNote(c) {
    const v = c.value, nx = (c.next3 || []).find((w) => !w.bye);
    const notes = [];
    if (v && v.status && ["Questionable", "Doubtful", "Out"].includes(v.status) && nx) {
      const A = MD && MD.learned && MD.learned.params && MD.learned.params.availability;
      const row = A && ((v.practice && A[`${v.status}|${v.practice}`] && A[`${v.status}|${v.practice}`].games >= 20 && A[`${v.status}|${v.practice}`]) || A[v.status]);
      notes.push(`<b>${esc(v.status)}</b>${v.practice ? ` (${PRACTICE[v.practice] || esc(v.practice)})` : ""}: ${row
        ? `players listed like this have played ${row.played != null ? Math.round(100 * row.played) + "% of the time and" : ""} produced ${Math.round(100 * row.share)}% of their normal points (${row.games} cases), so this week's projection is ${Math.round(100 * (nx.avail ?? 1))}% of normal.`
        : `this week's projection is ${Math.round(100 * (nx.avail ?? 1))}% of normal.`}`);
    }
    if (nx && nx.wx) {
      const t = wxText(nx.wx), m = nx.wx.mult;
      if (t) notes.push(`Next game ${t}${m && Math.abs(m - 1) >= 0.01 ? ` (${m > 1 ? "+" : "−"}${Math.round(100 * Math.abs(m - 1))}% for conditions)` : ""}.`);
    }
    return notes.length ? `<div class="pd-sec"><div class="pd-h">Game day</div>${notes.map((n) => `<div>${n}</div>`).join("")}</div>` : "";
  }

  function detailPanel(p, c) {
    const v = c.value, u = c.usage, k = c.consistency || {}, o = c.opportunity || {};
    const pos = p.position, ab = POS_ABBR[pos] || pos;
    const isQB = pos === "QB", isKD = pos === "K" || pos === "DEF";
    let html = `<div class="pd">`;

    // headline tiles
    const tiles = [];
    if (k.games) tiles.push(tileHtml("Season", `${one(k.ppg)}<small>/g</small>`, `${k.games} game${k.games > 1 ? "s" : ""}`));
    if (k.games) tiles.push(tileHtml("Avg finish", `${ab}${k.avg_finish}`, `best ${ab}${k.best_finish}`));
    if (v) tiles.push(tileHtml("Projected", `${one(v.rate)}<small>/wk</small>`, `${one(Math.max(v.rate - v.sd, 0))}–${one(v.rate + v.sd)}`));
    if (v && v.rank) tiles.push(tileHtml("ROS rank", `${ab}${v.rank}`, `${Math.round(v.ros)} pts · ${v.vor >= 0 ? "+" : ""}${Math.round(v.vor)} vs FA`));
    if (tiles.length) html += `<div class="tiles head">${tiles.join("")}</div>`;

    html += gameDayNote(c);
    html += roleSection(c);

    // consistency & ceiling
    if (k.games) {
      const t = c.tiers;
      html += `<div class="pd-sec"><div class="pd-h">Consistency &amp; ceiling</div>
        <div class="tiles">${tileHtml("Best week", one(k.ceiling))}${tileHtml("Median", one(k.median))}${tileHtml("Worst week", one(k.floor))}</div>
        <div class="fin-bar" role="img" aria-label="${k.boom} boom, ${k.start - k.boom} starter, ${k.games - k.start - k.bust} middling, ${k.bust} bust weeks">${
          [["boom", k.boom], ["start", k.start - k.boom], ["mid", k.games - k.start - k.bust], ["bust", k.bust]]
            .filter(([, n]) => n > 0).map(([cl, n]) => `<span class="f-${cl}" style="flex:${n}"></span>`).join("")}</div>
        <div class="fin-legend"><span><i class="sw f-boom"></i>Boom ${k.boom} <small>(top ${t.boom})</small></span>
          <span><i class="sw f-start"></i>Starter ${k.start - k.boom} <small>(${t.boom + 1}–${t.start})</small></span>
          <span><i class="sw f-mid"></i>Middling ${k.games - k.start - k.bust}</span>
          <span><i class="sw f-bust"></i>Bust ${k.bust} <small>(outside ${t.bust})</small></span></div>
        <div class="subtle">Starter-level (top ${t.start} ${ab}) in <b>${k.start} of ${k.games}</b> weeks. Finish = rank among every ${ab} that week, league scoring.</div></div>`;
    }

    // opportunity & efficiency
    if (!isKD && (o.games || (u && u.games))) {
      const t = [];
      if (u && u.snap_pct != null) t.push(tileHtml("Snaps", `${u.snap_pct}%`, `last ${u.games}`));
      if (isQB) {
        if (u && u.attempts) t.push(tileHtml("Att/g", one(u.attempts)));
        if (o.pass_yd_pg) t.push(tileHtml("Pass yd/g", Math.round(o.pass_yd_pg)));
        if (u && u.carries) t.push(tileHtml("Rush/g", one(u.carries)));
      } else {
        if (o.tgt_share != null) t.push(tileHtml("Tgt share", pct(o.tgt_share), u && u.targets ? `${one(u.targets)} tgt/g` : ""));
        if (o.ay_share != null && pos !== "RB") t.push(tileHtml("Air-yd share", pct(o.ay_share)));
        if (o.wopr != null && pos !== "RB") t.push(tileHtml("WOPR", (o.wopr).toFixed(2)));
        if (o.car_share) t.push(tileHtml("Carry share", pct(o.car_share), u && u.carries ? `${one(u.carries)} car/g` : ""));
        if (o.touches_pg) t.push(tileHtml("Touches/g", one(o.touches_pg)));
        if (o.yds_per_touch != null) t.push(tileHtml("Yds/touch", one(o.yds_per_touch)));
      }
      if (o.exp_tds != null && !isQB) t.push(tileHtml("TDs", `${o.tds}`, `~${one(o.exp_tds)} expected`, o.td_note === "hot" ? "warn" : o.td_note === "due" ? "good" : ""));
      const notes = [];
      if (o.td_note === "hot") notes.push(`More touchdowns than this volume usually brings (${o.tds} vs ~${one(o.exp_tds)}), so expect some cooling.`);
      if (o.td_note === "due") notes.push(`Fewer touchdowns than this volume usually brings (${o.tds} vs ~${one(o.exp_tds)}), so there's upside.`);
      if (u && u.actual_ppg != null && u.expected_ppg != null) notes.push(`Scoring <b>${one(u.actual_ppg)}</b>/g vs <b>${one(u.expected_ppg)}</b>/g that this usage usually produces${
        u.actual_ppg - u.expected_ppg > 3 ? " (running hot)" : u.expected_ppg - u.actual_ppg > 3 ? " (running cold)" : ""}.`);
      html += `<div class="pd-sec"><div class="pd-h">Opportunity &amp; efficiency <span class="subtle">· full games this season</span></div>
        <div class="tiles">${t.join("")}</div>${notes.map((n) => `<div class="subtle" style="margin-top:6px">${n}</div>`).join("")}</div>`;
    }

    // game log
    const cols = isQB
      ? [["Att", (g) => g.attempts], ["Yds", (g) => g.pass_yd], ["TD", (g) => g.pass_td], ["Int", (g) => g.ints], ["Car", (g) => g.carries], ["RuYd", (g) => g.rush_yd], ["RuTD", (g) => g.rush_td]]
      : pos === "RB"
      ? [["Snap", (g) => g.pct != null ? pct(g.pct) : null], ["Car", (g) => g.carries], ["Yds", (g) => g.rush_yd], ["Tgt", (g) => g.targets], ["Rec", (g) => g.receptions], ["ReYd", (g) => g.rec_yd], ["TD", (g) => g.rush_td != null ? (g.rush_td || 0) + (g.rec_td || 0) : null]]
      : isKD ? []
      : [["Snap", (g) => g.pct != null ? pct(g.pct) : null], ["Tgt", (g) => g.targets], ["Rec", (g) => g.receptions], ["Yds", (g) => g.rec_yd], ["TD", (g) => g.rec_td], ["Tgt%", (g) => g.tgt_share != null ? pct(g.tgt_share) : null]];
    const cell = (x) => (x == null ? "–" : typeof x === "number" ? Math.round(x * 10) / 10 : x);
    html += `<div class="pd-sec"><div class="pd-h">Game log</div>
      <div class="table-wrap"><table class="log"><thead><tr><th>Wk</th><th>Opp</th><th>Pts</th><th>Finish</th>${cols.map(([h]) => `<th>${h}</th>`).join("")}</tr></thead><tbody>${
      c.log.slice().reverse().map((g) => g.bye
        ? `<tr class="partial"><td>${g.week}</td><td>bye</td><td colspan="${2 + cols.length}"></td></tr>`
        : `<tr${g.partial ? ' class="partial"' : ""}><td>${g.week}</td><td>${esc(g.opp || "–")}</td>
          <td><b>${g.pts == null ? (g.calc != null ? "≈" + one(g.calc) : "n/r") : one(g.pts)}</b>${g.partial ? "*" : ""}</td>
          <td>${g.finish ? `<span class="fin f-${tierOf(c, g.finish)}">${ab}${g.finish}</span>` : "–"}</td>
          ${cols.map(([, f]) => `<td>${cell(f(g))}</td>`).join("")}</tr>`).join("")}</tbody></table></div>
      <div class="subtle">Newest first. * partial game (snap share well below normal, e.g. hurt early). ${c.log.some((g) => g.pts == null && g.calc != null) ? "≈ = not on a league roster that week, so calculated from NFL stats with your league's scoring." : "n/r = not on a league roster that week."}</div></div>`;

    // schedule ahead
    if (c.schedule && c.schedule.length) {
      const wk = (w) => `<div class="sch ${w.bye ? "bye" : w.matchup && w.matchup !== "neutral" ? "mu-" + w.matchup : ""}">
        <div class="w">W${w.week}</div><div class="o">${esc(oppLabel(w))}</div><div class="p">${w.bye ? "–" : one(w.pts)}${MU_MARK[w.matchup] || ""}</div>${
        w.wx && (w.wx.roof === "dome" || w.wx.roof === "closed") ? `<div class="wxs">indoors</div>` : w.wx && w.wx.wind != null && w.wx.wind >= 15 ? `<div class="wxs">${Math.round(w.wx.wind)} mph</div>` : ""}</div>`;
      const reg = c.schedule.filter((w) => !w.playoff), po = c.schedule.filter((w) => w.playoff);
      html += `<div class="pd-sec"><div class="pd-h">Schedule ahead <span class="subtle">· projected pts, ▲ easy ▼ tough</span></div>
        <div class="sched">${reg.map(wk).join("")}</div>
        ${po.length ? `<div class="pd-h" style="margin-top:10px">Fantasy playoffs</div><div class="sched po">${po.map(wk).join("")}</div>` : ""}
        ${c.next3.some((w) => w.source === "vegas") ? `<div class="subtle">Next game uses Vegas lines; later weeks use opponent strength.</div>` : ""}</div>`;
    }

    // value
    if (v) {
      html += `<div class="pd-sec"><div class="pd-h">Value ${confChip(v.confidence)}${v.flag ? ` <span class="chip ${v.flag === "sell-high" ? "hot" : "ok-style"}">${esc(v.flag)}</span>` : ""}</div>
        <div>${ab}${v.rank} of ${v.rank_of} by rest-of-season projection · ${v.vor >= 0 ? "+" : ""}${Math.round(v.vor)} pts vs a free-agent replacement.</div>
        <div class="subtle">${v.byes.length ? `Bye: week ${v.byes.join(", ")}. ` : ""}${v.prior_ppg != null ? `Last season ${one(v.prior_ppg)}/g. ` : ""}See Trades → How values work.</div></div>`;
    }
    html += `<div class="acts">${actionButtons(p.id)}<button type="button" class="mini" data-act="ask" data-kind="player" data-pid="${esc(p.id)}">Ask Claude</button></div>`;
    return html + `</div>`;
  }

  function playerRow(p, slot) {
    if (!p.id) {
      return `<div class="prow"><span class="slot ${esc(slot)}">${esc(slot)}</span>
        <div class="pname muted">Empty slot</div><div></div></div>`;
    }
    const label = slot || p.position;
    const cls = slot === "BN" || slot === "IR" ? slot : (slot || p.position);
    const c = CARDS[p.id];
    const reason = p.check && p.check.status === "unverified"
      ? `<div class="pmeta" style="color:var(--warn)">${esc(p.check.reason)}</div>` : "";
    const irNote = slot !== "IR" && p.ir_eligible ? `<span class="chip q">IR-eligible</span>` : "";
    if (!c) {
      return `<div class="prow"><span class="slot ${esc(cls)}">${esc(label)}</span>
        <div><div class="pname">${esc(p.name)}${injuryChip(p)}${irNote}${checkChip(p)}</div>
        <div class="pmeta">${esc(p.position)} · ${esc(p.team)}</div>${reason}</div>
        <div class="pnums"><div class="big">${num(p.avg)}</div><div class="small">per game</div></div></div>`;
    }
    const v = c.value;
    const rank = v && v.rank ? ` · ${POS_ABBR[p.position] || p.position}${v.rank}` : "";
    return `<details class="prow-d" data-pid="${esc(p.id)}"><summary class="prow prow-card">
      <span class="slot ${esc(cls)}">${esc(label)}</span>
      <div class="pmain">
        <div class="pname">${esc(p.name)}${injuryChip(p)}${irNote}${checkChip(p)}</div>
        <div class="pmeta">${teamLink(p.team)}${rank}${v ? ` · ${esc(v.confidence)} conf` : ""}${v && v.flag && !isHeld(p.id) ? ` · <span class="flag">${esc(v.flag)}</span>` : ""}${isHeld(p.id) ? ` · <span class="held">held</span>` : ""}</div>
        ${reason}
      </div>
      <div class="pnums proj">${v ? `<div class="big">${one(v.rate)}</div><div class="small">proj/wk</div>` : ""}</div>
      ${pills(c, p.position)}
    </summary>${detailPanel(p, c)}</details>`;
  }

  function rosterCards(r) {
    let html = `<h2>Starters</h2><div class="card">${r.starters.map((p) => playerRow(p, p.slot)).join("")}</div>`;
    html += `<h2>Bench</h2><div class="card">${
      r.bench.length ? r.bench.map((p) => playerRow(p, "BN")).join("") : `<div class="empty">No bench players.</div>`}</div>`;
    html += `<h2>IR <span class="muted" style="font-weight:400;font-size:.85rem">(${r.ir.length}/${r.ir_slots} used)</span></h2>
      <div class="card">${r.ir.length ? r.ir.map((p) => playerRow(p, "IR")).join("") : `<div class="empty">IR slot empty.</div>`}</div>`;
    return html;
  }

  // ---------- tabs ----------
  // ---------- FAAB ----------
  const F = DATA.faab;
  const money = (n) => (n == null ? "–" : "$" + (Number.isInteger(n) ? n : Number(n).toFixed(1)));
  const pnames = (list) => list.map((p) => esc(p.name)).join(", ");

  function rivalsBlock(p) {
    const r = p.rivals;
    if (!r) return "";
    const who = (x) => `<b>${esc(x.label)}</b>${x.upgrade != null && x.upgrade > 0 ? ` (+${num(x.upgrade)} pts)` : ""}${
      x.typical != null ? `, usually ${money(x.typical)}` : ", no bids yet"}${x.wins_ties ? " · you win ties" : ""}`;
    const likely = r.likely.length ? r.likely.map(who).join("; ") : "none clear";
    const e = r.estimate;
    let est = "";
    if (e && e.low != null) {
      est = `<div><b>Rivals suggest ${e.low === e.high ? money(e.low) : `${money(e.low)}–${money(e.high)}`}</b>
        <span class="subtle">(${esc(e.basis)})</span></div>`;
      if (e.wildcard) est += `<div class="subtle">Wildcard: ${esc(e.wildcard.label)} has bid up to ${money(e.wildcard.max)} before.</div>`;
    } else if (e) {
      est = `<div class="subtle">${esc(e.basis)}.</div>`;
    }
    const proj = p.proj_week != null
      ? `<div class="subtle">Projects ${num(p.proj_week)} pts in week ${esc(F.tendencies.week)}${p.proj_week === 0 ? " (bye or not expected to play)" : ""} (${num(p.proj_rate)}/wk rest of season, ${esc(p.proj_confidence)} confidence).</div>` : "";
    return `<div class="rivals">${proj}
      <div>Likely rivals: ${likely}</div>
      ${r.possible.length ? `<div class="subtle">Possible: ${r.possible.map((x) => esc(x.label)).join(", ")}</div>` : ""}
      ${est}</div>`;
  }

  function bidCard(p) {
    const s = p.suggestion || {};
    const L = s.levels || {};
    const on = { quiet: "bargain_bid", warm: "competitive_bid", hot: "safe_bid" }[s.demand];
    const lvl = (k, label) => L[k] == null ? "" : `<span class="level ${k === on ? "on" : ""}">${label} ${money(L[k])}</span>`;
    const heat = p.count != null
      ? `<span class="chip ${s.demand === "hot" ? "hot" : "warm"}">${Number(p.count).toLocaleString()} adds</span>` : "";
    const owner = p.rostered_by ? `<div class="subtle" style="color:var(--warn)">Already rostered by ${esc(p.rostered_by)}</div>` : "";
    const comps = p.comparables && p.comparables.length
      ? `<div class="subtle">Similar claims: ${p.comparables.map((c) => `${esc(c.name)} ${money(c.bid)} (needed ${money(c.clearing_price)})`).join(" · ")}</div>` : "";
    return `<div class="bid-card">
      <div class="bid-head">
        <div><span class="pname">${esc(p.name)}</span>${injuryChip(p)} ${heat}
          <div class="pmeta">${esc(p.position)} · ${esc(p.team)}</div></div>
        <div class="bid-amt">${s.bid == null ? "–" : money(s.bid)}</div>
      </div>
      <div class="levels">${lvl("bargain_bid", "Bargain")}${lvl("competitive_bid", "Competitive")}${lvl("safe_bid", "Safe")}</div>
      ${owner}<div class="acts">${actionButtons(p.id)}</div>
      <details class="why"><summary>Why ${s.bid == null ? "this bid" : money(s.bid)}?</summary>
        <div class="subtle" style="margin-top:6px">${esc(s.reason || "")}</div>${comps}${rivalsBlock(p)}</details>
    </div>`;
  }

  const FIT = { upgrade: ["Upgrade", "balanced"], depth: ["Depth", "ok-style"], none: ["Bench only", ""] };
  function waiverCard(p) {
    const s = p.suggestion || {}, L = s.levels || {}, c = CARDS[p.id];
    const lvl = (k, label) => L[k] == null ? "" : `<span class="level ${k === s.level ? "on" : ""}">${label} ${money(L[k])}</span>`;
    const r = p.rivals || {}, likely = (r.likely || []).length, ties = (r.likely || []).filter((x) => x.wins_ties).length;
    const [fitLabel, fitCls] = FIT[p.fit] || FIT.none;
    const impact = p.fit === "none"
      ? `Wouldn't improve your lineup right now`
      : `Adds <b>${p.gain_per_week >= 0 ? "+" : ""}${num(p.gain_per_week)}</b>/wk to you (${p.gain >= 0 ? "+" : ""}${num(p.gain, 0)} rest of season)`;
    const cut = p.drop && p.drop.length ? ` · you'd cut ${p.drop.map((d) => esc(d.name)).join(", ")}` : "";
    return `<details class="wv" data-pid="${esc(p.id)}"><summary class="wv-sum">
        <div class="wv-head">
          <div class="pname">${esc(p.name)}${injuryChip(p)} <span class="chip ${fitCls}">${fitLabel}</span>${p.trending ? ` <span class="chip warm" title="Sleeper-wide adds, last 48h">trending</span>` : ""}</div>
          <div class="pmeta">${esc(p.position)} · ${teamLink(p.team)}${p.pos_rank ? ` · ${esc(p.position)}${p.pos_rank} rest of season` : ""} · ${num(p.proj_rate)}/wk proj · ${esc(p.proj_confidence)} conf</div>
          <div class="wv-impact">${impact}${cut}</div>
        </div>
        <div class="bid-amt">${s.bid == null ? "–" : money(s.bid)}<small>bid</small></div>
        ${c ? `<div class="wv-pills">${pills(c, p.position)}</div>` : ""}
        <div class="wv-riv subtle">${likely ? `${likely} likely rival${likely === 1 ? "" : "s"}${ties ? ` · you win ties vs ${ties}` : ""}` : "No likely rivals"} <span class="chev">▸</span></div>
      </summary>
      <div class="pd">
        <div class="pd-sec"><div class="pd-h">Bid</div>
          <div class="levels">${lvl("bargain_bid", "Bargain")}${lvl("competitive_bid", "Competitive")}${lvl("safe_bid", "Safe")}</div>
          <div class="subtle" style="margin-top:6px">${esc(s.reason || "")}</div>${rivalsBlock(p)}</div>
      </div>
      ${c ? detailPanel(p, c) : `<div class="pd"><div class="acts">${actionButtons(p.id)}</div></div>`}
    </details>`;
  }

  function availableList(view) {
    const all = F.available || [];
    if (!all.length) return `<div class="card"><div class="empty">No waiver data yet. Run an update.</div></div>`;
    let rows, note = "";
    if (view === "best") {
      rows = all.filter((p) => p.fit !== "none").slice(0, 12);
      if (!rows.length) {
        rows = all.slice(0, 5);
        note = `<p class="subtle">No available player would improve your lineup right now. These come closest.</p>`;
      }
    } else {
      rows = all.filter((p) => p.position === view).slice().sort((a, b) => b.ros - a.ros);
    }
    return note + `<div class="card">${rows.map(waiverCard).join("") || `<div class="empty">No available ${esc(view)}s with projections.</div>`}</div>`;
  }

  function tendencyCard(t) {
    const styleCls = { "big spender": "hot", stingy: "ok-style", "middle of the pack": "conf" }[t.style] || "conf";
    const pos = Object.entries(t.positions).map(([k, v]) => `<span class="level">${esc(k)} ×${v}</span>`).join("");
    return `<div class="bid-card ${t.roster_id === F.my_roster_id ? "mine-bg" : ""}">
      <div class="bid-head"><div><span class="pname">${managerName(t)}</span>
        <div class="pmeta">${esc(t.team_name)} · waiver #${esc(t.waiver_position ?? "–")}</div></div>
        <span class="chip ${styleCls}">${esc(t.style)}</span></div>
      <div class="subtle" style="margin-top:4px">
        <b>${money(t.remaining)}</b> left${t.nearly_out ? ` <span class="chip inj">nearly out</span>` : ""} ·
        ${t.bids} bid${t.bids === 1 ? "" : "s"} (${t.won} won, ${t.outbid} outbid, ${t.invalid} invalid) · ${t.fa_adds} free-agent pickup${t.fa_adds === 1 ? "" : "s"}</div>
      ${t.bids ? `<div class="subtle">Typical bid ${money(t.typical_bid)}, biggest ${money(t.max_bid)} · overpaid ${money(t.overpaid_total)} across ${t.overpaid_claims} claim${t.overpaid_claims === 1 ? "" : "s"}</div>` : ""}
      ${pos ? `<div class="levels">${pos}</div>` : ""}
    </div>`;
  }

  function renderFaab() {
    if (!F) { $("tab-faab").innerHTML = `<div class="empty">No FAAB data yet.</div>`; return; }
    const me = F.managers.find((m) => m.roster_id === F.my_roster_id) || {};
    let html = `<div class="stats">
      <div class="stat"><div class="v">${money(me.remaining)}</div><div class="l">My FAAB left</div></div>
      <div class="stat"><div class="v">${me.claims}</div><div class="l">Claims won</div></div>
      <div class="stat"><div class="v">${money(me.overpaid)}</div><div class="l">Overpaid</div></div>
    </div>`;

    // bid ideas: available players ranked by what they'd add to my team, by position
    html += `<h2>Bid ideas</h2>
      <p class="lead-text">Available players ranked by what they'd add to <b>your</b> lineup for the rest of the season (same maths as the
      Trade Lab, measured against your actual roster, cutting your weakest player if you're full). The bid comes from who else in
      your league would start them and what those managers usually pay. <b>Bargain</b> = what past claims actually took ·
      <b>Competitive</b> = beats half of rivals' bids · <b>Safe</b> = beats 75%. Suggestions, not advice.</p>
      ${segHtml("faab-pos", [["best", "Best for you"], ["QB", "QB"], ["RB", "RB"], ["WR", "WR"], ["TE", "TE"], ["K", "K"], ["DEF", "DEF"]], store.get("faabPos", "best"))}
      <div id="faab-list"></div>`;
    const ideas = (F.targets || []).map(bidCard).join("");
    if (ideas) html += `<h2>My targets</h2><div class="card">${ideas}</div>`;
    // manager tendencies
    if (F.tendencies) {
      html += `<h2>Manager tendencies</h2><p class="lead-text">Everyone's bidding habits this season. Counts, not percentages, because
        samples are small. A style is only given after ${esc(F.tendencies.min_bids_for_style)}+ bids.
        You're waiver #${esc(F.tendencies.my_waiver_position ?? "–")}, so you win tied bids against anyone with a higher number.</p>
        <div class="card">${F.tendencies.profiles.map(tendencyCard).join("")}</div>
        <details class="recent"><summary>How rivals are predicted</summary><div class="card card-pad subtle">
        <p><b>Likely</b> rival: the player would start for them next week by more than 1 point (from their projected optimal lineup,
        byes included), they've been active, and they have at least $5 left. Hot players also count anyone they'd improve.
        <b>Possible</b>: a smaller upgrade or they've bid on the position before.</p>
        <p><b>Rivals suggest</b>: beat the likely rivals' typical bid (low) or their biggest bid (high), capped at what they have left.
        For trending players with no clear likely rival it uses the possible rivals, because managers chase hype.
        Compare it with the market levels above. When they disagree, the market levels have more data behind them.</p></div></details>`;
    }

    // per manager
    const rows = F.managers.map((m) => `<tr class="${m.roster_id === F.my_roster_id ? "mine" : ""}">
      <td class="team-cell"><div class="t">${managerName(m)}</div>
        <div class="bar"><span style="width:${m.pct_left}%"></span></div></td>
      <td class="hide-sm">${money(m.spent)}</td><td><b>${money(m.remaining)}</b></td>
      <td>${m.claims}</td><td class="hide-sm">${m.failed_bids}</td><td>${money(m.overpaid)}</td>
    </tr>`).join("");
    html += `<h2>FAAB by manager</h2><div class="card table-wrap"><table class="named">
      <thead><tr><th>Manager</th><th class="hide-sm">Spent</th><th>Left</th><th>Won</th><th class="hide-sm">Lost</th><th title="Paid above the lowest winning bid">Over</th></tr></thead>
      <tbody>${rows}</tbody></table></div>
      <p class="subtle">Over = total paid above what was needed to win (runner-up bid + $1).</p>`;

    // market prices
    const order = ["QB", "RB", "WR", "TE", "K", "DEF", "ALL"];
    const mrows = order.filter((p) => F.market[p]).map((p) => {
      const m = F.market[p];
      return `<tr><td><b>${p === "ALL" ? "All" : p}</b> <span class="subtle">${m.claims} won · ${m.contested_pct}% contested</span></td>
        <td>${money(m.avg_winning_bid)}</td><td>${money(m.median_winning_bid)}</td>
        <td>${money(m.bargain_bid)}</td><td class="hide-sm">${money(m.competitive_bid)}</td><td class="hide-sm">${money(m.safe_bid)}</td></tr>`;
    }).join("");
    html += `<h2>Market prices</h2><div class="card table-wrap"><table class="named">
      <thead><tr><th>Position</th><th>Avg</th><th>Median</th><th>Bargain</th><th class="hide-sm">Compet.</th><th class="hide-sm">Safe</th></tr></thead>
      <tbody>${mrows || `<tr><td colspan="6">No claims yet.</td></tr>`}</tbody></table></div>`;

    // waiver log
    const log = F.waiver_log.map((r) => `<div class="log-row ${r.roster_id === F.my_roster_id ? "mine" : ""}">
      <div class="log-top">
        <div><span class="pname">${esc(r.player.name)}</span> <span class="pmeta">${esc(r.player.position)} · ${esc(r.player.team)}</span></div>
        <div class="bid-amt" style="font-size:1.05rem">${money(r.bid)}</div>
      </div>
      <div class="subtle">Wk ${r.week} · won by ${esc(r.winner)} ·
        ${r.competing_bids ? `${r.competing_bids} rival bid${r.competing_bids > 1 ? "s" : ""} (top ${money(r.runner_up_bid)})` : "uncontested"}
        ${r.invalid_bids ? ` · ${r.invalid_bids} invalid bid${r.invalid_bids > 1 ? "s" : ""}` : ""}
        ${r.overpay ? ` · <span style="color:var(--warn)">overpaid ${money(r.overpay)}</span>` : ""}
        ${r.dropped.length ? ` · dropped ${pnames(r.dropped)}` : ""}</div>
    </div>`).join("");
    html += `<h2>Waiver log</h2><div class="card">${log || `<div class="empty">No waiver claims yet.</div>`}</div>
      <p class="subtle">"Invalid" bids failed for roster reasons (e.g. too many players), not because they were outbid.</p>`;

    // other moves
    const moves = F.other_moves.slice(0, 25).map((t) => `<div class="log-row">
      <div class="subtle">Wk ${t.week} · ${t.type === "free_agent" ? "Free agent" : t.type === "trade" ? "<b>Trade</b>" : esc(t.type)}</div>
      ${t.moves.map((m) => `<div>${esc(m.manager)}: ${m.added.length ? `<span style="color:var(--good)">+ ${pnames(m.added)}</span>` : ""}
        ${m.dropped.length ? `<span class="muted">− ${pnames(m.dropped)}</span>` : ""}</div>`).join("")}
    </div>`).join("");
    html += `<h2>Other moves</h2><div class="card">${moves || `<div class="empty">None yet.</div>`}</div>`;

    // trending drops
    html += `<h2>Trending drops <span class="muted" style="font-weight:400;font-size:.85rem">(free agents here)</span></h2>
      <div class="card">${F.trending_drops.length ? F.trending_drops.map((p) => `<div class="log-row">
        <span class="pname">${esc(p.name)}</span>${injuryChip(p)} <span class="pmeta">${esc(p.position)} · ${esc(p.team)} · ${Number(p.count).toLocaleString()} drops</span></div>`).join("")
        : `<div class="empty">None.</div>`}</div>`;

    $("tab-faab").innerHTML = html;
    const drawList = (v) => { $("faab-list").innerHTML = availableList(v); };
    wireSeg("faab-pos", "faabPos", drawList);
    drawList(store.get("faabPos", "best"));
  }

  // ---------- News (scanner) ----------
  const S = DATA.scanner;
  const KIND = { injury: "Injury", team: "Team change", depth: "Depth chart", available: "Dropped", backup: "Opportunity" };

  function newsItem(n, showSection) {
    const tagCls = n.direction || "";
    const tag = `${KIND[n.kind] || n.kind}${n.direction ? " · " + n.direction : ""}`;
    const who = n.manager ? ` · ${esc(n.manager)}` : "";
    const sect = showSection ? ` · ${{ my_players: "My team", other_starters: "Other teams", free_agents: "Free agent" }[n.section] || ""}` : "";
    const stats = n.games ? ` · ${num(n.avg)}/g` : "";
    const action = n.action
      ? `<div class="act ${n.action.startsWith("Trade") ? "" : "warn"}">${esc(n.action)}</div>` : "";
    const bid = n.suggestion && n.suggestion.bid != null
      ? `<div class="act">Bid idea: <b>${money(n.suggestion.bid)}</b> · <span class="subtle">${esc(n.suggestion.reason)}</span></div>` : "";
    return `<div class="news">
      <div class="tag ${esc(tagCls)}">${esc(tag)}${sect}</div>
      <div><span class="pname">${esc(n.name)}</span>${injuryChip(n)} <span class="pmeta">${esc(n.position)} · ${teamLink(n.team)}${who}${stats}</span></div>
      <div class="txt">${esc(n.text)}</div>${action}${bid}${n.rivals && F && F.tendencies ? rivalsBlock(n) : ""}
      ${n.id && actionButtons(n.id) ? `<div class="acts">${actionButtons(n.id)}</div>` : ""}
    </div>`;
  }

  function newsSection(title, items, empty) {
    return `<h2>${title}</h2><div class="card">${
      items.length ? items.map((n) => newsItem(n)).join("") : `<div class="empty">${empty}</div>`}</div>`;
  }

  function renderNews() {
    if (!S) { $("tab-news").innerHTML = `<div class="empty">No scanner data yet.</div>`; return; }
    let html = "";
    if (S.first_run) {
      html += `<div class="alert">First scan: a baseline was saved. From the next run on, this tab shows what changed since the previous run.</div>`;
    } else {
      html += `<p class="lead-text" style="margin-top:12px">New since the last run (${esc(new Date(S.baseline).toLocaleString())}). Old news isn't repeated.</p>`;
    }
    html += newsSection("My players", S.my_players, "Nothing new on your roster.");
    html += newsSection("Other teams' starters", S.other_starters, "No changes to other teams' starters.");
    if (S.motivated_buyers.length) {
      html += `<p class="subtle">Motivated buyers: ${S.motivated_buyers.map((b) =>
        `${esc(b.manager)} (lost ${esc(b.position)} ${esc(b.player)})`).join(" · ")}</p>`;
    }
    html += newsSection("Free agents worth a look", S.free_agents, "No new free-agent opportunities.");
    const older = (S.recent || []).filter((n) => n.seen !== S.generated_at);
    if (older.length) {
      html += `<details class="recent"><summary>Earlier this week (${older.length})</summary>
        <div class="card">${older.map((n) => newsItem(n, true)).join("")}</div></details>`;
    }
    $("tab-news").innerHTML = html;
    const count = S.my_players.length + S.other_starters.length + S.free_agents.length;
    if (count) document.querySelector('#tabs button[data-tab="waivers"]').insertAdjacentHTML("beforeend", `<span class="badge">${count}</span>`);
  }

  // ---------- Trades ----------
  const T = DATA.trades;
  const signed = (n) => (n > 0 ? "+" : "") + num(n);

  function confChip(level) {
    return level ? `<span class="conf-t ${esc(level)}" title="How much data backs this number">${esc(level)} conf.</span>` : "";
  }

  function projMeta(p) {
    const range = p.sd != null ? ` (${num(Math.max(p.rate - p.sd, 0), 0)}–${num(p.rate + p.sd, 0)} typical)` : "";
    return `${esc(p.position)} · ${esc(p.team)} · <b>${num(p.rate)}</b>/wk proj${range}`;
  }

  // Full-width player details (same content as the roster cards) for the Trades tab.
  function playerExpand(p) {
    const c = CARDS[p.id];
    if (!c) return `<div class="empty">No details for this player yet.</div>`;
    return `<div class="xp-head"><div><span class="pname">${esc(p.name)}</span>${injuryChip(p)}
        <div class="pmeta">${esc(p.position)} · ${teamLink(p.team)}${p.manager ? ` · ${esc(p.manager)}` : ""}</div></div>
      <div class="pnums proj">${c.value ? `<div class="big">${one(c.value.rate)}</div><div class="small">proj/wk</div>` : ""}</div></div>
      ${pills(c, p.position)}${detailPanel(p, c)}`;
  }

  function tradePlayers(list) {
    return list.map((p) => `<div class="tp${CARDS[p.id] ? "" : " no-card"}" data-pid="${esc(p.id)}" role="button" tabindex="0"
      aria-label="Show details for ${esc(p.name)}"><div class="pl">${esc(p.name)}${injuryChip(p)}${CARDS[p.id] ? ` <span class="chev">▸</span>` : ""}</div>
      <div class="pmeta">${esc(p.position)} · ${esc(p.team)} · <b>${num(p.rate)}</b>/wk · ROS ${num(p.ros, 0)}${
        p.confidence === "low" ? ` ${confChip("low")}` : ""}</div></div>`).join("");
  }

  function tradeCard(t) {
    const cls = t.balance.startsWith("balanced") ? "balanced" : t.balance.startsWith("favours") ? "favours" : "lopsided";
    const n = T.weeks.length || 1;
    return `<div class="trade has-detail">
      <div class="trade-head">
        <div><span class="pname">${esc(t.team_name)}</span> <span class="pmeta">${esc(t.manager)}</span></div>
        <span><span class="chip ${cls}">${esc(t.balance)}</span> ${confChip(t.confidence)}</span>
      </div>
      <div class="swap">
        <div><div class="col-label">You give</div>${tradePlayers(t.give)}</div>
        <div class="arrow">⇄</div>
        <div><div class="col-label">You get</div>${tradePlayers(t.get)}</div>
      </div>
      <div class="gains"><span class="gain me">You ${signed(t.my_gain)} pts ROS (${signed(t.my_gain / n)}/wk)</span>
        <span class="gain">Them ${signed(t.their_gain)} pts</span></div>
      <div class="trade-detail" hidden></div>
      <button type="button" class="btn secondary lab-open" data-partner="${t.roster_id}"
        data-give="${esc(t.give.map((p) => p.id).join(","))}" data-get="${esc(t.get.map((p) => p.id).join(","))}">Open in Trade Lab</button>
      <details><summary>Why this trade?</summary><ul>${t.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></details>
    </div>`;
  }

  function buySellRow(r, verb) {
    const body = CARDS[r.id] ? `<div class="xp-body">${playerExpand(r)}</div>` : "";
    return `<details class="trade bs-d"${body ? "" : " data-empty"}><summary>
      <div class="trade-head"><div><span class="pname">${esc(r.name)}</span> <span class="pmeta">${esc(r.position)} · ${esc(r.team)} · ${esc(r.manager)}</span>${body ? ` <span class="chev">▸</span>` : ""}</div>
        <span>${confChip(r.confidence)} <button type="button" class="mini" data-act="${r.roster_id === T.my_roster_id ? "shop" : "trade-for"}" data-pid="${esc(r.id)}">${r.roster_id === T.my_roster_id ? "Shop" : "Trade for"}</button></span></div>
      <div class="subtle" style="margin-top:4px">Scoring <b>${num(r.actual_ppg)}</b>/g in ${r.games_this} full game(s); projection <b>${num(r.rate)}</b>/wk.
        Usage alone suggests ${r.expected_ppg != null ? num(r.expected_ppg) : "–"}/g${r.prior_ppg != null ? `, last season ${num(r.prior_ppg)}/g` : ""}.
        ${verb}</div></summary>${body}</details>`;
  }

  function valuesTable(rows) {
    return `<div class="card table-wrap"><table class="named">
      <thead><tr><th>Player</th><th>Proj/wk</th><th>ROS</th><th title="Rest-of-season points above a free-agent replacement">vs repl.</th><th class="hide-sm">Conf.</th></tr></thead>
      <tbody>${rows.map((v) => `<tr class="${v.roster_id === T.my_roster_id ? "mine" : ""}${CARDS[v.id] ? " tp-row" : ""}" data-pid="${esc(v.id)}"
          ${CARDS[v.id] ? 'tabindex="0" role="button"' : ""}>
        <td class="team-cell"><div class="t">${esc(v.name)}${injuryChip(v)}${CARDS[v.id] ? ` <span class="chev">▸</span>` : ""}</div>
          <div class="m">${esc(v.position)} · ${esc(v.team)} · ${esc(v.manager)}${v.byes && v.byes.length ? ` · bye wk ${v.byes.join(", ")}` : ""}</div></td>
        <td>${num(v.rate)}</td><td>${num(v.ros, 0)}</td>
        <td class="${v.vor > 0 ? "up" : "down"}">${v.vor >= 0 ? "+" : ""}${num(v.vor, 0)}</td>
        <td class="hide-sm">${esc(v.confidence)}</td></tr>`).join("")}</tbody></table></div>`;
  }

  function renderTrades() {
    if (!T) { $("tab-trades").innerHTML = `<div class="empty">No trade data yet.</div>`; return; }
    const n = T.weeks.length;
    let html = "";
    if (T.trades_closed) {
      html += `<div class="alert">The trade deadline (week ${esc(T.trade_deadline)}) has passed. Values are still shown for reference.</div>`;
    }
    html += `<p class="disclaimer">Suggestions, not advice · rest-of-season projections (weeks ${esc(T.weeks[0])}–${esc(T.weeks[n - 1])}).</p>`;
    if (T.trade_deadline && !T.trades_closed) {
      const left = T.trade_deadline - T.current_week;
      html += `<div class="status-note">Trade deadline: <b>week ${esc(T.trade_deadline)}</b> (${left <= 0 ? "this week" : `${left} week${left === 1 ? "" : "s"} away`}).</div>`;
    }

    html += `<h2>Trade ideas</h2><p class="lead-text">Each idea improves <b>both</b> teams' projected optimal lineups for every remaining week
      (byes included), counting only points above free-agent level, with injury cover and roster limits (the side receiving
      two players must cut someone). Ranked by benefit to you; lopsided ones last.</p>`;
    const heldIn = (t) => t.give.some((p) => isHeld(p.id)) || ((t.my_moves || {}).drop || []).some(isHeld);
    const ideas = T.ideas.filter((t) => !heldIn(t));
    const hiddenIdeas = T.ideas.length - ideas.length;
    html += `<div class="card">${ideas.length ? ideas.map(tradeCard).join("") : `<div class="empty">No mutually beneficial trades found right now.</div>`}</div>`;
    if (hiddenIdeas) html += `<p class="subtle">${hiddenIdeas} idea${hiddenIdeas === 1 ? "" : "s"} hidden because they'd offer or cut a player you're holding.</p>`;

    html += `<h2>Sell high</h2><p class="lead-text">Your players scoring well above what their usage and track record support.</p>
      <div class="card">${T.sell_high.filter((r) => !isHeld(r.id)).length ? T.sell_high.filter((r) => !isHeld(r.id)).map((r) => buySellRow(r, "Worth shopping while the numbers look great.")).join("")
        : `<div class="empty">None of your players are clearly overperforming.</div>`}</div>`;
    html += `<h2>Buy low</h2><p class="lead-text">Other teams' players scoring well below their projection. Their managers may undervalue them.</p>
      <div class="card">${T.buy_low.length ? T.buy_low.map((r) => buySellRow(r, "Could be cheaper now than they're worth.")).join("")
        : `<div class="empty">No clear buy-low targets.</div>`}</div>`;

    html += `<h2>Motivated buyers</h2>`;
    if (T.buyers.length) {
      html += `<div class="card">${T.buyers.map((b) => `<div class="trade has-detail">
        <div><span class="pname">${esc(b.manager)}</span> <span class="pmeta">just lost ${esc(b.position)} ${esc(b.player)} (${esc(b.status)})</span></div>
        <div class="subtle" style="margin-top:4px">${b.my_options.length
          ? `Players you could pitch: ${b.my_options.filter((p) => !isHeld(p.id)).map((p) => `<button type="button" class="tp tp-chip" data-pid="${esc(p.id)}">${esc(p.name)}
              <span class="subtle">${num(p.rate)}/wk</span> <span class="chev">▸</span></button>
              <button type="button" class="mini" data-act="pitch" data-pid="${esc(p.id)}" data-partner="${b.roster_id}">Pitch</button>`).join(" ")}`
          : `You have no bench ${esc(b.position)} to offer.`}</div><div class="trade-detail" hidden></div></div>`).join("")}</div>`;
    } else {
      html += `<div class="card"><div class="empty">No team has lost a starter to injury since recent runs. Check back after the next scan.</div></div>`;
    }

    const mine = T.values.filter((v) => v.roster_id === T.my_roster_id);
    html += `<h2>Player values: my team</h2>${valuesTable(mine)}`;
    html += `<details class="recent"><summary>Player values: top 25 in the league</summary>${valuesTable(T.values.slice(0, 25))}</details>`;
    html += `<p class="subtle">Replacement level (avg of the best 3 free agents, pts/wk): ${
      Object.entries(T.replacement).map(([k, v]) => `${esc(k)} ${num(v)}`).join(" · ")}.</p>`;

    html += `<h2>Team strength vs league median</h2>
      <div class="seg" id="str-seg" role="tablist">
        <button type="button" data-view="past">Season so far</button>
        <button type="button" data-view="proj">Projected</button>
        <button type="button" data-view="partners">Partners</button>
      </div><div id="str-body"></div>`;

    html += `<details class="recent"><summary>How values work</summary><div class="card card-pad subtle">
      <p><b>Per-week projection</b> = a blend of a position baseline (by depth chart role), <b>last season</b> (each game counts half,
      halved again after a team change) and <b>this season</b> (half actual points, half what the player's targets, carries and
      pass attempts are usually worth, which evens out touchdown luck). Games where a player barely played (snap share well
      below their normal, e.g. hurt early) are left out.</p>
      <p><b>Each week</b> then adjusts for byes (0), injury designation (Questionable 85%, Doubtful 25%, Out 0 this week,
      IR-type out 4+ weeks), and the opponent: next week uses Vegas implied team totals, later weeks a heavily dampened
      defence-vs-position factor (±10% max).</p>
      <p><b>ROS</b> = projected points over the remaining regular-season weeks. <b>vs repl.</b> subtracts what the best free
      agents at the position would score, which makes positions comparable. <b>Typical range</b> = ±1 game-to-game spread.</p>
      <p><b>Confidence</b>: <i>high</i> needs 4+ full games this season plus a solid history; <i>low</i> means mostly baseline
      (rookies, little data). Sources: nflverse stats re-scored with league scoring (they match Sleeper exactly for checked
      players), nflverse snap counts and schedule.</p></div></details>`;
    $("tab-trades").innerHTML = html;
    wireTradeDetails();
    renderStrength(store.get("strengthView", "past"));
    $("str-seg").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      store.set("strengthView", b.dataset.view);
      renderStrength(b.dataset.view);
    }));
    $("tab-trades").querySelectorAll(".lab-open").forEach((b) => b.addEventListener("click", () =>
      openInLab(b.dataset.partner, b.dataset.give.split(","), b.dataset.get.split(","))));
  }

  function renderStrength(view) {
    const cols = ["QB", "RB", "WR", "TE", "FLEX"];
    const H = T.history || { teams: [], weeks: 0, median: {} };
    if (view === "past" && !H.teams.length) view = "proj";
    $("str-seg").querySelectorAll("button").forEach((b) => b.setAttribute("aria-pressed", String(b.dataset.view === view)));
    const cells = (vs) => cols.map((c) => {
      const v = vs[c];
      return `<td class="${v > 1 ? "up" : v < -1 ? "down" : ""}${c === "FLEX" ? " hide-sm" : ""}">${signed(v)}</td>`;
    }).join("");
    const head = (last) => `<thead><tr><th>Team</th>${cols.map((c) => `<th${c === "FLEX" ? ' class="hide-sm"' : ""}>${c}</th>`).join("")}<th class="hide-sm">${last}</th></tr></thead>`;
    const weakest = (vs) => cols.filter((c) => c !== "FLEX" && vs[c] < -1).sort((a, b) => vs[a] - vs[b]);
    let html = "";
    if (view === "past") {
      const rows = H.teams.map((t) => `<tr class="${t.is_mine ? "mine" : ""}">
        <td class="team-cell"><div class="t">${esc(t.team_name)}</div><div class="m">${managerName(t)}</div>
          <div class="m">${t.efficiency != null ? `started <b>${Math.round(100 * t.efficiency)}%</b> of best possible` : ""}${
            weakest(t.vs_median).length ? ` · weakest ${esc(weakest(t.vs_median).join("/"))}` : ""}</div></td>
        ${cells(t.vs_median)}<td class="hide-sm"><b>${num(t.actual)}</b></td></tr>`).join("");
      html = `<p class="lead-text">Actual points per week from each position in the lineups teams really started
        (weeks 1–${esc(H.weeks)}), compared with the median team. ${H.weeks < 5 ? `Only ${esc(H.weeks)} week${H.weeks === 1 ? "" : "s"} played, so treat as a rough guide.` : ""}</p>
        <div class="card table-wrap"><table class="named">${head("Pts/wk")}<tbody>${rows}</tbody></table></div>
        <p class="subtle">Median: ${cols.map((c) => `${c} ${num(H.median[c])}`).join(" · ")} pts/wk.
          "Started X% of best possible" = actual starters' points vs the best lineup they could have set each week (in hindsight).
          Managers who leave points on the bench may undervalue depth or value a simpler roster.</p>`;
    } else if (view === "proj") {
      const rows = T.teams.map((t) => `<tr class="${t.is_mine ? "mine" : ""}">
        <td class="team-cell"><div class="t">${esc(t.team_name)}</div><div class="m">${managerName(t)}</div>
          <div class="m">${t.needs.length ? `needs <b>${esc(t.needs.join("/"))}</b>` : "no clear needs"}${t.surplus.length ? ` · spare ${esc(t.surplus.join("/"))}` : ""}</div></td>
        ${cells(t.vs_median)}<td class="hide-sm"><b>${num(t.per_week)}</b></td></tr>`).join("");
      html = `<p class="lead-text">Average projected points per week from each position in the optimal weekly lineups
        (rest of season, byes included).</p>
        <div class="card table-wrap"><table class="named">${head("Proj/wk")}<tbody>${rows}</tbody></table></div>
        <p class="subtle">Median: ${cols.map((c) => `${c} ${num(T.median[c])}`).join(" · ")} pts/wk.
          Lineup slots: ${esc(T.slots.join(", "))}. "Spare" = a bench player who'd start for the median team.</p>`;
    } else {
      const odds = {};
      if (O) O.playoffs.teams.forEach((t) => { odds[t.roster_id] = t; });
      const rec = {};
      D.standings.forEach((s) => { rec[s.roster_id] = s; });
      const past = {};
      H.teams.forEach((t) => { past[t.roster_id] = t; });
      const mySpare = (T.teams.find((x) => x.is_mine) || { surplus: [] }).surplus;
      const fitScore = (t) => t.needs.filter((pos) => mySpare.includes(pos)).length;
      const rows = T.teams.filter((t) => !t.is_mine)
        .sort((a, b) => (fitScore(b) - fitScore(a)) || ((odds[b.roster_id] || {}).odds || 0) - ((odds[a.roster_id] || {}).odds || 0))
        .map((t) => {
        const o = odds[t.roster_id], r = rec[t.roster_id], h = past[t.roster_id] || {};
        const made = (T.history && T.history.trades_made && T.history.trades_made[String(t.roster_id)]) || 0;
        const stance = !o ? "" : o.odds >= 0.6 ? "contender: may pay for help now" : o.odds <= 0.2 ? "long shot: may sell veterans" : "in the mix";
        const fits = t.needs.filter((pos) => (T.teams.find((x) => x.is_mine) || { surplus: [] }).surplus.includes(pos));
        return `<tr><td class="team-cell"><div class="t">${esc(t.team_name)}</div><div class="m">${managerName(t)}</div>
            <div class="m">${t.needs.length ? `needs <b>${esc(t.needs.join("/"))}</b>` : "no clear needs"}${t.surplus.length ? ` · spare ${esc(t.surplus.join("/"))}` : ""}${
              fits.length ? ` · <span style="color:var(--good)">your spare ${esc(fits.join("/"))} fits</span>` : ""}</div>
            <div class="m">${esc(stance)}${h.efficiency != null ? ` · starts ${Math.round(100 * h.efficiency)}% of best` : ""}</div></td>
          <td>${r ? `${r.wins}–${r.losses}` : "–"}</td><td><b>${o ? esc(o.odds_text) : "–"}</b></td><td>${made}</td></tr>`;
      }).join("");
      html = `<p class="lead-text">Who to talk to: what each team needs (projected), whether they're chasing the playoffs,
        and how often they trade.</p>
        <div class="card table-wrap"><table class="named"><thead><tr><th>Team</th><th>W–L</th><th>Playoffs</th><th title="Trades completed this season">Trades</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
        <p class="subtle">Sorted by fit (they need what you can spare), then playoff odds. Contenders (60%+ playoff odds) tend to pay for help now; long shots (20% or less) may sell. Managers who have
          already traded this season are likelier to deal. "Your spare fits" = they need a position where you have bench depth.</p>`;
    }
    $("str-body").innerHTML = html;
  }

  function tradePlayerLookup() {
    const byId = {};
    const add = (p, extra) => { if (p && p.id && !byId[p.id]) byId[p.id] = Object.assign({}, p, extra || {}); };
    T.values.forEach((v) => add(v));
    T.ideas.forEach((t) => t.give.concat(t.get).forEach((p) => add(p)));
    T.buyers.forEach((b) => b.my_options.forEach((p) => add(p)));
    return byId;
  }

  function wireTradeDetails() {
    wireExpanders($("tab-trades"), (pid) => tradePlayerLookup()[pid]);
  }

  function wireExpanders(root, find) {
    const toggle = (el) => {
      const pid = el.dataset.pid;
      const p = find(pid);
      if (!p || !CARDS[pid]) return;
      if (el.classList.contains("tp-row")) {           // values table: detail row underneath
        const next = el.nextElementSibling;
        if (next && next.classList.contains("detail-row")) { next.remove(); el.classList.remove("open"); return; }
        el.insertAdjacentHTML("afterend", `<tr class="detail-row"><td colspan="5"><div class="xp-body">${playerExpand(p)}</div></td></tr>`);
        el.classList.add("open");
        return;
      }
      const box = el.closest(".has-detail");            // trade idea / buyer: full-width panel
      const panel = box && box.querySelector(".trade-detail");
      if (!panel) return;
      const same = !panel.hidden && panel.dataset.pid === pid;
      box.querySelectorAll(".tp.open").forEach((x) => x.classList.remove("open"));
      if (same) { panel.hidden = true; panel.innerHTML = ""; panel.dataset.pid = ""; return; }
      panel.innerHTML = playerExpand(p);
      panel.dataset.pid = pid;
      panel.hidden = false;
      el.classList.add("open");
    };
    root.addEventListener("click", (e) => {
      const el = e.target.closest(".tp, .tp-row");
      if (el && root.contains(el)) toggle(el);
    });
    root.addEventListener("keydown", (e) => {
      if (e.key !== "Enter" && e.key !== " ") return;
      const el = e.target.closest(".tp, .tp-row");
      if (el && !el.matches("button")) { e.preventDefault(); toggle(el); }
    });
  }

  // ---------- Matchups (projections) ----------
  const O = DATA.outlook;

  function pctText(p, conf) {
    if (p == null) return "–";
    const pct = 100 * p;
    if (pct < 1) return "<1%";
    if (pct > 99) return ">99%";
    const step = conf === "high" ? 1 : 5;
    const r = Math.round(pct / step) * step;
    return r <= 0 ? `<${step}%` : r >= 100 ? `>${100 - step}%` : `${r}%`;
  }
  const nm = (pid) => (O && O.names[pid]) || { name: pid, position: "?", team: "" };
  const range = (mean, sd) => `${num(Math.max(mean - sd, 0), 0)}–${num(mean + sd, 0)}`;

  function winBar(a, b, conf) {
    const pa = Math.round(100 * a.win_prob);
    return `<div class="winbar" role="img" aria-label="Win chance ${pctText(a.win_prob, conf)}">
      <span style="width:${pa}%"></span></div>
      <div class="winbar-labels"><span>${pctText(a.win_prob, conf)}</span><span>${pctText(b.win_prob, conf)}</span></div>`;
  }

  function startSitRow(r) {
    const s = nm(r.starter), a = r.alt ? nm(r.alt) : null;
    const label = { swap: "Consider swapping", close: "Close call", keep: "Keep", problem: "Fix this" }[r.verdict];
    const cls = { swap: "swap", close: "close", keep: "keep", problem: "problem" }[r.verdict];
    return `<div class="trade">
      <div class="trade-head"><div><span class="slot ${esc(r.slot)}" style="display:inline-block;width:44px">${esc(r.slot)}</span>
        <span class="pname">${esc(s.name)}</span> <span class="pmeta">${num(r.starter_pts)} proj</span></div>
        <span class="chip ss ${cls}">${label}</span></div>
      ${a ? `<div class="subtle" style="margin-top:4px">vs <b>${esc(a.name)}</b> ${num(r.alt_pts)} proj${injuryChip(a)}. ${esc(r.why)}</div>`
          : `<div class="subtle" style="margin-top:4px">${esc(r.why)}</div>`}
    </div>`;
  }

  // ---------- Home + League ----------
  const LG = DATA.league;
  const recBy = {};
  (D ? D.standings : []).forEach((s) => { recBy[s.roster_id] = s; });
  const record = (s) => `${s.wins}–${s.losses}${s.ties ? "–" + s.ties : ""}`;

  function segHtml(id, options, current) {
    return `<div class="seg" id="${id}" role="tablist">${options.map(([v, label]) =>
      `<button type="button" data-view="${v}" aria-pressed="${v === current}">${label}</button>`).join("")}</div>`;
  }
  function wireSeg(id, key, draw) {
    $(id).querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      store.set(key, b.dataset.view);
      $(id).querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      draw(b.dataset.view);
    }));
  }

  function oddsSeries(rid) {
    return ((LG && LG.odds_history) || []).map((h) => ({ at: h.at, week: h.week, v: h.odds[String(rid)] }))
      .filter((x) => x.v != null);
  }
  function sparkline(rid) {
    const s = oddsSeries(rid);
    if (s.length < 2) return "";
    const W = 72, H = 22, n = s.length;
    const pts = s.map((x, i) => [2 + (W - 4) * i / (n - 1), H - 2 - (H - 4) * x.v]);
    const title = s.map((x) => `${x.at.slice(5, 10)}: ${Math.round(100 * x.v)}%`).join(" · ");
    return `<svg class="spark" width="${W}" height="${H}" viewBox="0 0 ${W} ${H}" role="img" aria-label="Playoff odds trend"><title>${esc(title)}</title>
      <polyline points="${pts.map((p) => p.map((v) => v.toFixed(1)).join(",")).join(" ")}" fill="none" stroke="var(--accent)" stroke-width="2" stroke-linejoin="round" stroke-linecap="round"/>
      <circle cx="${pts[n - 1][0].toFixed(1)}" cy="${pts[n - 1][1].toFixed(1)}" r="3" fill="var(--accent)" stroke="var(--surface)" stroke-width="1.5"/></svg>`;
  }
  function oddsDelta(rid) {
    const s = oddsSeries(rid);
    if (s.length < 2) return "";
    const d = Math.round(100 * (s[s.length - 1].v - s[s.length - 2].v));
    return d === 0 ? `<span class="muted">no change</span>` : `<span class="${d > 0 ? "up" : "down"}">${d > 0 ? "▲" : "▼"} ${Math.abs(d)}</span>`;
  }

  function matchupCard(m) {
    const [a, b] = m.teams;
    const side = (t, right) => `<div class="side" ${right ? 'style="text-align:right"' : ""}>
      <div class="score">${num(t.mean)}</div>
      <div class="pname">${esc(t.team_name)}</div>
      <div class="pmeta">${esc(recBy[t.roster_id] ? record(recBy[t.roster_id]) : "")} · likely ${range(t.mean, t.sd)}</div></div>`;
    const details = `<details class="mu-detail"${m.is_mine && store.get("muOpen", false) ? " open" : ""}><summary>Lineups side by side</summary>${sideBySide(a, b)}</details>`;
    return `<div class="card ${m.is_mine ? "mine" : ""}">
      ${m.is_mine ? `<div class="mine-label">Week ${esc(O.week)} · your matchup</div>` : ""}
      <div class="mu">${side(a)}<div class="vs">vs</div>${side(b, true)}</div>
      <div style="padding:0 14px 12px">${winBar(a, b, m.confidence)}</div>${details}</div>`;
  }

  // Both starting lineups slot by slot; the higher score in each row is emphasised.
  function sideBySide(a, b) {
    const cell = (r, right) => {
      if (!r || !r.id) return `<div class="vsg-name${right ? " r" : ""}"><div class="n muted">Empty</div></div>`;
      const p = nm(r.id);
      const st = p.injury_status ? ` · <span style="color:var(--${p.injury_status === "Questionable" ? "warn" : "bad"})">${esc(p.injury_status)}</span>` : "";
      return `<div class="vsg-name${right ? " r" : ""}"><div class="n">${esc(p.name)}</div><div class="t">${esc(p.team)}${st}</div></div>`;
    };
    const pts = (r, win) => {
      if (!r || !r.id) return `<div class="vsg-pts">–</div>`;
      const sub = r.status === "played" ? "final" : `±${num(r.sd, 0)}`;
      return `<div class="vsg-pts${win ? " win" : ""}">${num(r.pts)}<span class="s">${sub}</span></div>`;
    };
    const rows = O.slots.map((slot, i) => {
      const ra = a.players[i], rb = b.players[i];
      const pa = ra && ra.id ? ra.pts : -1, pb = rb && rb.id ? rb.pts : -1;
      return `<div class="vsg-row">${cell(ra)}${pts(ra, pa > pb)}<div class="vsg-slot">${esc(slot)}</div>${pts(rb, pb > pa)}${cell(rb, true)}</div>`;
    }).join("");
    return `<div class="vsg">
      <div class="vsg-row vsg-head"><div>${esc(a.team_name)}</div><div></div><div></div><div></div><div class="r" style="text-align:right">${esc(b.team_name)}</div></div>
      ${rows}
      <div class="vsg-row vsg-total"><div class="vsg-name"><div class="n">Projected</div></div>
        <div class="vsg-pts${a.mean > b.mean ? " win" : ""}">${num(a.mean)}</div><div class="vsg-slot">TOT</div>
        <div class="vsg-pts${b.mean > a.mean ? " win" : ""}">${num(b.mean)}</div><div class="vsg-name r"><div class="n" style="text-align:right">Projected</div></div></div>
    </div>`;
  }

  function keyRow(k) {
    const meIsA = k.a === O.my_roster_id;
    if (k.mine) {
      const opp = meIsA ? k.b_team : k.a_team;
      return `<div class="trade"><div class="pname">Week ${esc(k.week)} vs ${esc(opp)}</div>
        <div class="subtle">Win → <b>${esc(meIsA ? k.if_a_text : k.if_b_text)}</b> · Lose → <b>${esc(meIsA ? k.if_b_text : k.if_a_text)}</b></div></div>`;
    }
    return `<div class="trade"><div class="pname">Week ${esc(k.week)}: ${esc(k.a_team)} vs ${esc(k.b_team)}</div>
      <div class="subtle">If ${esc(k.a_team)} wins → you're <b>${esc(k.if_a_text)}</b> · if ${esc(k.b_team)} wins → <b>${esc(k.if_b_text)}</b></div></div>`;
  }

  function lineupsHtml() {
    return `<p class="lead-text">Your best projected lineup for every remaining regular-season week, byes and injuries included.</p>
      <div class="weekchips" id="lu-weeks">${O.weeks.map((w, i) => `<button type="button" data-w="${w}" aria-pressed="${i === 0}">Wk ${w}</button>`).join("")}</div>
      <div id="lu-body"></div><div class="card table-wrap" style="margin-top:12px" id="lu-season"></div>`;
  }
  function wireLineups(rid) {
    let week = O.weeks[0];
    const draw = () => {
      const lw = O.lineups[String(rid)][String(week)];
      const byes = lw.byes.map((p) => esc(nm(p).name)).join(", ");
      $("lu-body").innerHTML = `<div class="card">${lw.lineup.map((x) => {
        const p = nm(x.id);
        return `<div class="prow"><span class="slot ${esc(x.slot)}">${esc(x.slot)}</span>
          <div><div class="pname">${esc(p.name)}${injuryChip(p)}</div>
          <div class="pmeta">${esc(p.team)}${x.opp ? ` ${x.home ? "vs" : "@"} ${esc(x.opp)}` : " · bye"}</div></div>
          <div class="pnums"><div class="big">${num(x.pts)}</div></div></div>`;
      }).join("")}
        <div class="prow" style="grid-template-columns:1fr auto"><div class="pname">Projected total <span class="subtle">likely ${range(lw.total, lw.sd)}</span></div>
          <div class="pnums"><div class="big">${num(lw.total)}</div></div></div></div>
        ${byes ? `<p class="subtle">On bye: ${byes}</p>` : ""}
        ${week === O.week ? `<p class="subtle">Week ${esc(week)} is in progress: players whose games are done aren't included.</p>` : ""}`;
      const max = Math.max(...O.weeks.map((w) => O.lineups[String(rid)][String(w)].total));
      $("lu-season").innerHTML = `<table class="named"><thead><tr><th>Week</th><th>Proj</th><th>Byes</th></tr></thead><tbody>${
        O.weeks.map((w) => {
          const l2 = O.lineups[String(rid)][String(w)];
          return `<tr><td>Wk ${w}</td><td>${num(l2.total)} <span class="bar" style="display:inline-block;width:60px;vertical-align:middle"><span style="width:${Math.round(100 * l2.total / max)}%"></span></span></td>
            <td>${l2.byes.length ? l2.byes.map((p) => esc(nm(p).name)).join(", ") : "–"}</td></tr>`;
        }).join("")}</tbody></table>`;
    };
    document.querySelectorAll("#lu-weeks button").forEach((b) => b.addEventListener("click", () => {
      week = Number(b.dataset.w);
      document.querySelectorAll("#lu-weeks button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      draw();
    }));
    draw();
  }

  function renderHome() {
    const me = D.me;
    const st = recBy[me.roster_id] || {};
    const po = O ? O.playoffs.teams.find((t) => t.is_mine) : null;
    const mine = O ? O.matchups.find((m) => m.is_mine) : null;
    let html = `<div class="stats">
      <div class="stat"><div class="v">${record(st)}</div><div class="l">Record · #${st.rank}</div></div>
      <div class="stat"><div class="v">${po ? esc(po.odds_text) : "–"} ${po ? sparkline(me.roster_id) : ""}</div>
        <div class="l">Playoff odds ${po ? oddsDelta(me.roster_id) : ""}</div></div>
      <div class="stat"><div class="v">$${st.faab_remaining}</div><div class="l">FAAB left</div></div>
    </div>`;
    if (mine) {
      html += matchupCard(mine);
      if (po && po.if_win_text) html += `<p class="subtle" style="margin:-4px 0 12px">Playoff odds if you win this week <b>${esc(po.if_win_text)}</b> · if you lose <b>${esc(po.if_lose_text)}</b> · projected ${num(po.proj_wins)} wins.</p>`;
    }
    const alerts = (me.notes || []).slice();
    if (O) O.start_sit.filter((r) => r.verdict === "problem" || r.verdict === "swap").forEach((r) =>
      alerts.push(`${r.verdict === "problem" ? "Lineup problem" : "Consider a swap"} at ${r.slot}: ${nm(r.starter).name}${r.alt ? ` vs ${nm(r.alt).name}` : ""}. See Start/sit.`));
    if (alerts.length) html += `<div class="alert"><strong>Heads up</strong><ul>${alerts.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`;

    const view = store.get("homeView", "roster");
    html += segHtml("home-seg", O ? [["roster", "Roster"], ["startsit", "Start/sit"], ["lineups", "Weekly lineups"]] : [["roster", "Roster"]], view);
    html += `<div id="home-body"></div>`;
    if (O) {
      const mineK = O.playoffs.key_games.filter((k) => k.mine);
      html += `<h2>Games that matter most</h2><div class="card">${mineK.map(keyRow).join("") || `<div class="empty">No games left.</div>`}</div>
        <p class="subtle">Your playoff odds depending on each result. Other teams' key games are in League → Playoff race.</p>`;
    }
    html += `<details class="recent"><summary>How these numbers work</summary><div class="card card-pad subtle">
      <p><b>Projected score</b> = points already scored this week (final) + each remaining starter's projection (see Trades → How values work).
      "Likely" is ±1 standard deviation, the range a team lands in about two weeks in three.</p>
      <p><b>Win chance</b> compares both projected scores and their week-to-week spread, including the chance a Questionable player sits.
      <b>Playoff odds</b> come from simulating the rest of the season ${O ? Number(O.playoffs.sims).toLocaleString() : ""} times on the real schedule
      (ranking: wins, then points for). Percentages are rounded to the nearest 5% until confidence is high. The small line shows how
      your odds have moved across updates.</p>
      <p><b>Start/sit</b> shows how often the best eligible bench player would outscore your starter this week. Above 60%: consider swapping.</p></div></details>`;
    $("tab-home").innerHTML = html;

    const draw = (v) => {
      const body = $("home-body");
      if (v === "startsit" && O) {
        body.innerHTML = `<p class="lead-text">Your set lineup vs the best bench option at each slot. Players whose games have started are locked.</p>
          <div class="card">${O.start_sit.length ? O.start_sit.map(startSitRow).join("") : `<div class="empty">Nothing to decide: all your games have started.</div>`}</div>`;
      } else if (v === "lineups" && O) {
        body.innerHTML = lineupsHtml();
        wireLineups(me.roster_id);
      } else {
        body.innerHTML = rosterCards(me) + `<p class="muted" style="font-size:.8rem">Last 3 = points each week (league scoring, from Sleeper) and where that ranked at the position
          (dark green = boom, light green = starter-level, red = bust). Next 3 = projected points per game (green/red outline = easy/tough matchup).
          Tap a player for details. ✓ = matches nflverse stats within 1 pt.
          IR allowed for: ${esc(D.league.ir_allowed.join(", "))}.</p>`;
      }
    };
    wireSeg("home-seg", "homeView", draw);
    draw(view);
  }

  // Weekly scores: one row per team, recent weeks as score pills (score + that week's league
  // rank, coloured by rank, with W/L); tap a team for every game, schedule luck and consistency.
  const ordinal = (n) => n + (n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th");
  function weeklyStats() {
    const ids = Object.keys(LG.weekly);
    const rankOf = {};          // week -> rid -> rank (ties share the better rank)
    const teamsIn = {};
    LG.weeks.forEach((w) => {
      const pts = ids.map((rid) => [rid, (LG.weekly[rid].find((g) => g.week === w) || {}).pts]).filter(([, p]) => p != null);
      teamsIn[w] = pts.length;
      rankOf[w] = {};
      pts.forEach(([rid, p]) => { rankOf[w][rid] = 1 + pts.filter(([, q]) => q > p).length; });
    });
    const sd = (xs) => { const m = xs.reduce((a, b) => a + b, 0) / xs.length; return Math.sqrt(xs.reduce((a, x) => a + (x - m) ** 2, 0) / xs.length); };
    const st = {};
    ids.forEach((rid) => {
      const g = LG.weekly[rid].slice().sort((x, y) => x.week - y.week);
      const pts = g.map((x) => x.pts), pa = g.filter((x) => x.opp_pts != null).map((x) => x.opp_pts);
      st[rid] = { games: g, avg: pts.length ? pts.reduce((a, b) => a + b, 0) / pts.length : 0,
        high: pts.length ? Math.max(...pts) : null, low: pts.length ? Math.min(...pts) : null,
        pa: pa.length ? pa.reduce((a, b) => a + b, 0) / pa.length : null, sd: pts.length > 1 ? sd(pts) : null,
        above: g.filter((x) => x.pts >= LG.medians[String(x.week)]).length };
    });
    const rankBy = (key, desc) => { const r = {}; const v = ids.filter((i) => st[i][key] != null).sort((x, y) => desc ? st[y][key] - st[x][key] : st[x][key] - st[y][key]); v.forEach((i, k) => { r[i] = k + 1; }); return r; };
    const sds = ids.map((i) => st[i].sd).filter((x) => x != null).sort((a, b) => a - b);
    return { st, rankOf, teamsIn, avgRank: rankBy("avg", true), paRank: rankBy("pa", true), sdMedian: sds.length ? sds[Math.floor(sds.length / 2)] : null, n: ids.length };
  }

  function weeklyChart() {
    if (!LG || !LG.weeks.length) return "";
    const W = weeklyStats();
    const show = LG.weeks.slice(-4);
    const tier = (rank, n) => (rank === 1 ? "f-boom" : rank <= 3 ? "f-start" : rank > n - 3 ? "f-bust" : "f-mid");
    const pill = (rid, g) => {
      const r = W.rankOf[g.week][rid], n = W.teamsIn[g.week];
      return `<span class="pill ${tier(r, n)}" title="Week ${g.week}: ${num(g.pts)}, ${ordinal(r)} of ${n}${g.result ? " · " + g.result : ""}"><b>${num(g.pts)}</b><i>${ordinal(r)}${g.result ? " · " + g.result : ""}</i></span>`;
    };
    const order = D.standings.map((s) => String(s.roster_id));
    const rows = order.filter((rid) => W.st[rid]).map((rid) => {
      const s = recBy[rid], t = W.st[rid], a = (LG.all_play || {})[rid];
      const recent = show.map((w) => { const g = t.games.find((x) => x.week === w); return g ? pill(rid, g) : `<span class="pill none"><b>–</b><i>W${w}</i></span>`; }).join("");
      const steady = t.sd == null || W.sdMedian == null ? "" : t.sd <= W.sdMedian ? "steady" : "boom-or-bust";
      const paTxt = t.pa == null ? "–" : `${num(t.pa)}<small>/wk</small>`;
      const paSub = t.pa == null ? "" : `${ordinal(W.paRank[rid])} most of ${W.n}${W.paRank[rid] <= 3 ? " · tough draw" : W.paRank[rid] > W.n - 3 ? " · easy draw" : ""}`;
      const games = t.games.slice().reverse().map((g) => {
        const r = W.rankOf[g.week][rid], n = W.teamsIn[g.week];
        const opp = g.opp != null && recBy[g.opp] ? recBy[g.opp].team_name : "";
        const margin = g.opp_pts != null ? g.pts - g.opp_pts : null;
        return `<div class="ws-game"><div><b>W${g.week}</b> ${opp ? `vs ${esc(opp)}` : ""}
            <div class="subtle">${ordinal(r)} of ${n} · would have beaten ${n - r} of ${n - 1}</div></div>
          <div class="sc">${num(g.pts)}${g.opp_pts != null ? ` – ${num(g.opp_pts)}` : ""}</div>
          <div>${g.result ? `<span class="chip ${g.result === "W" ? "balanced" : g.result === "L" ? "lopsided" : ""}">${g.result}${margin != null ? ` ${margin >= 0 ? "+" : ""}${num(margin)}` : ""}</span>` : ""}</div></div>`;
      }).join("");
      return `<details class="ws ${rid === String(D.me.roster_id) ? "mine-bg" : ""}" data-rid="${rid}"><summary class="ws-row">
          <div class="ws-head"><div class="t">${esc(s.team_name)} <span class="chev">▸</span></div>
            <div class="m">${esc(record(s))} · high ${num(t.high)} · low ${num(t.low)}</div></div>
          <div class="ws-avg"><b>${num(t.avg)}</b><small>/wk · ${ordinal(W.avgRank[rid])}</small></div>
          <div class="ws-pills" style="grid-template-columns:repeat(${show.length}, minmax(0, 1fr))">${recent}</div>
        </summary>
        <div class="pd">
          <div class="tiles head">
            ${tileHtml("Scoring", `${num(t.avg)}<small>/wk</small>`, `${ordinal(W.avgRank[rid])} of ${W.n} · above median ${t.above}/${t.games.length}`)}
            ${tileHtml("Points against", paTxt, paSub)}
            ${a ? tileHtml("All-play", `${a.w}–${a.l}${a.t ? "–" + a.t : ""}`, `luck ${a.luck >= 0 ? "+" : ""}${num(a.luck)} wins`, a.luck >= 1 ? "warn" : a.luck <= -1 ? "good" : "") : ""}
            ${t.sd != null ? tileHtml("Consistency", `±${num(t.sd)}`, steady) : ""}
          </div>
          <div class="pd-sec"><div class="pd-h">Every game</div>${games}</div>
        </div></details>`;
    }).join("");
    return `<h2>Weekly scores</h2>
      <p class="lead-text">Each pill is a week's score and where it ranked in the league that week (green = top 3, red = bottom 3), with the result.
        Tap a team for every game, how many teams each score would have beaten, points against (schedule luck) and consistency.</p>
      <div class="card ws-card"><div class="ws-weeks" style="grid-template-columns:repeat(${show.length}, minmax(0, 1fr))">${show.map((w) => `<span>Wk ${w}</span>`).join("")}</div>${rows}</div>`;
  }

  function renderLeague() {
    const view = store.get("leagueView", "standings");
    let html = segHtml("league-seg", [["standings", "Standings"], ["race", "Playoff race"], ["power", "Power"]].concat(TM ? [["nfl", "NFL teams"]] : []), view)
      + `<div id="league-body"></div>`;
    html += weeklyChart();
    if (O) html += `<h2>Week ${esc(O.week)} matchups</h2>${O.matchups.map(matchupCard).join("")}`;
    html += `<details class="recent"><summary>How these work</summary><div class="card card-pad subtle">
      <p><b>All-play</b> = your record if you'd played every other team every week. <b>Luck</b> = actual wins minus the wins
      your all-play rate would give you: positive = winning more than your scores deserve.</p>
      <p><b>Power rankings</b> blend points scored per week so far, projected points per week (rest of season) and lineup
      efficiency. Results so far count more as the season goes on${LG && LG.power_weights ? ` (now ${Math.round(100 * LG.power_weights.actual)}% results,
      ${Math.round(100 * LG.power_weights.projected)}% projection, ${Math.round(100 * LG.power_weights.efficiency)}% efficiency)` : ""}.</p>
      <p><b>Playoff race</b> odds come from 10,000 simulated seasons; the trend line shows how odds moved across updates.</p></div></details>`;
    $("tab-league").innerHTML = html;

    const draw = (v) => {
      const body = $("league-body");
      if (v === "nfl" && TM) {
        const pos = store.get("nflSort", "RB");
        body.innerHTML = segHtml("nfl-sort", [["QB", "QB"], ["RB", "RB"], ["WR", "WR"], ["TE", "TE"]], pos) + `<div id="nfl-table" style="margin-top:12px">${teamsTable(pos)}</div>`;
        wireSeg("nfl-sort", "nflSort", (p2) => { $("nfl-table").innerHTML = teamsTable(p2); });
        return;
      }
      if (v === "race" && O) {
        const P = O.playoffs;
        const seed = {};
        P.teams.forEach((t) => { seed[t.roster_id] = t; });
        body.innerHTML = `<div class="card table-wrap"><table class="named">
          <thead><tr><th>Team</th><th>W–L</th><th title="Projected final wins">Proj W</th><th>Playoffs</th><th class="hide-sm">Trend</th><th class="hide-sm">Win / lose wk ${esc(O.week)}</th></tr></thead>
          <tbody>${P.teams.map((t) => `<tr class="${t.is_mine ? "mine" : ""}">
            <td class="team-cell"><div class="t">${esc(t.team_name)}</div><div class="m">${managerName(t)} · #1 seed ${Math.round(100 * t.seed1)}%</div></td>
            <td>${record(t)}</td><td>${num(t.proj_wins)}</td>
            <td><b>${esc(t.odds_text)}</b><div class="oddsbar"><span style="width:${Math.round(100 * t.odds)}%"></span></div></td>
            <td class="hide-sm">${sparkline(t.roster_id) || "–"} ${oddsDelta(t.roster_id)}</td>
            <td class="hide-sm">${esc(t.if_win_text || "–")} / ${esc(t.if_lose_text || "–")}</td></tr>`).join("")}</tbody></table></div>
          <p class="subtle">Top ${esc(O.playoff_teams)} make the playoffs. ${confChip(P.confidence)} odds rounded while data is thin.</p>
          <h2>Other games to watch</h2><div class="card">${P.key_games.filter((k) => !k.mine).map(keyRow).join("") || `<div class="empty">No other game moves your odds much.</div>`}</div>`;
      } else if (v === "power" && LG) {
        const stRank = {};
        D.standings.forEach((s) => { stRank[s.roster_id] = s.rank; });
        body.innerHTML = `<div class="card table-wrap"><table class="named">
          <thead><tr><th>#</th><th>Team</th><th>Pts/wk</th><th>Proj/wk</th><th class="hide-sm">Efficiency</th><th title="Power rank vs standings rank">vs ladder</th></tr></thead>
          <tbody>${LG.power.map((r) => {
            const s = recBy[r.roster_id], diff = stRank[r.roster_id] - r.rank;
            return `<tr class="${r.roster_id === D.me.roster_id ? "mine" : ""}"><td>${r.rank}</td>
              <td class="team-cell"><div class="t">${esc(s.team_name)}</div><div class="m">${managerName(s)} · ${record(s)}</div></td>
              <td>${num(r.actual)}</td><td>${num(r.projected)}</td><td class="hide-sm">${r.efficiency != null ? Math.round(100 * r.efficiency) + "%" : "–"}</td>
              <td class="${diff > 0 ? "up" : diff < 0 ? "down" : ""}">${diff > 0 ? `▲${diff}` : diff < 0 ? `▼${-diff}` : "="}</td></tr>`;
          }).join("")}</tbody></table></div>
          <p class="subtle">▲ = better than their ladder position suggests (unlucky so far); ▼ = ladder flatters them.</p>`;
      } else {
        const ap = (LG && LG.all_play) || {};
        body.innerHTML = `<div class="card table-wrap"><table class="named standings">
          <thead><tr><th>Team</th><th>W–L</th><th class="hide-sm">PF</th><th class="hide-sm">PA</th><th title="Record vs every team every week">All-play</th><th title="Actual wins minus all-play expected wins">Luck</th><th class="hide-sm" title="Waiver priority (FAAB tiebreak)">Waiver</th></tr></thead>
          <tbody>${D.standings.map((s) => {
            const a = ap[String(s.roster_id)];
            return `<tr class="${s.roster_id === D.me.roster_id ? "mine" : ""} tp-row team-row" data-rid="${s.roster_id}" tabindex="0" role="button">
              <td class="team-cell"><div class="t">${s.rank}. ${esc(s.team_name)} <span class="chev">▸</span></div><div class="m">${managerName(s)}</div></td>
              <td>${record(s)}</td><td class="hide-sm">${num(s.points_for)}</td><td class="hide-sm">${num(s.points_against)}</td>
              <td>${a ? `${a.w}–${a.l}` : "–"}</td>
              <td class="${a && a.luck > 0.5 ? "up" : a && a.luck < -0.5 ? "down" : ""}">${a ? (a.luck > 0 ? "+" : "") + a.luck.toFixed(1) : "–"}</td>
              <td class="hide-sm">${s.waiver_position ?? "–"}</td></tr>`;
          }).join("")}</tbody></table></div>
          <p class="subtle">Tap a team to see its roster. Waiver = Sleeper's waiver priority (1 wins tied FAAB bids).</p>`;
        body.querySelectorAll("tr.team-row").forEach((tr) => {
          const toggle = () => {
            const next = tr.nextElementSibling;
            if (next && next.classList.contains("detail-row")) { next.remove(); tr.classList.remove("open"); return; }
            const r = D.rosters.find((x) => x.roster_id === Number(tr.dataset.rid));
            tr.insertAdjacentHTML("afterend", `<tr class="detail-row"><td colspan="7"><div class="xp-body">${rosterCards(r)}</div></td></tr>`);
            tr.classList.add("open");
          };
          tr.addEventListener("click", (e) => { if (!e.target.closest(".detail-row")) toggle(); });
          tr.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); toggle(); } });
        });
      }
    };
    wireSeg("league-seg", "leagueView", draw);
    draw(view);
  }

  // ---------- Trade Lab ----------
  let ENGINE = null;
  const engine = () => {
    if (!ENGINE && DATA.lab && window.NFLLab) { ENGINE = window.NFLLab.create(DATA.lab); ENGINE.setHolds([...HOLDS]); }
    return ENGINE;
  };
  const POS_ORDER = ["QB", "RB", "WR", "TE", "K", "DEF"];
  const store = {
    get(k, d) { try { const v = localStorage.getItem(k); return v ? JSON.parse(v) : d; } catch (e) { return d; } },
    set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch (e) { /* private mode etc. */ } },
  };
  let labState = store.get("labState", null);

  function labPlayer(pid) {
    const r = DATA.lab.players[pid];
    const owner = r.o != null ? DATA.lab.rosters[String(r.o)] : null;
    return { id: pid, name: r.n, position: r.p, team: r.t, injury_status: r.s, manager: owner ? owner.label : "Free agent" };
  }

  function sortPids(pids) {
    const P = DATA.lab.players;
    return pids.slice().sort((a, b) => (POS_ORDER.indexOf(P[a].p) - POS_ORDER.indexOf(P[b].p)) || (P[b].r - P[a].r));
  }

  function pickChips(pids, chosen, side) {
    const P = DATA.lab.players;
    return sortPids(pids).map((pid) => {
      const r = P[pid];
      return `<button type="button" class="pick ${chosen.includes(pid) ? "on" : ""}" data-side="${side}" data-pid="${esc(pid)}"
        aria-pressed="${chosen.includes(pid)}"><span class="slot ${esc(r.p)}">${esc(r.p)}</span>
        <span class="pick-name">${esc(r.n)}${r.s ? ` <span class="chip ${r.s === "Questionable" ? "q" : "inj"}">${esc(r.s)}</span>` : ""}</span>
        <span class="pick-val">${num(r.r)}</span></button>`;
    }).join("");
  }

  function deltaCell(x, digits = 1) {
    const cls = x > 0.05 ? "up" : x < -0.05 ? "down" : "";
    return `<td class="${cls}">${x > 0 ? "+" : ""}${Number(x).toFixed(digits)}</td>`;
  }

  function oddsLine(label, pair, conf) {
    const d = Math.round(100 * (pair[1] - pair[0]));
    return `<div class="odds-row"><span>${label}</span><span><b>${pctText(pair[0], conf)}</b> → <b>${pctText(pair[1], conf)}</b>
      <span class="${d > 0 ? "up" : d < 0 ? "down" : "muted"}" title="change in percentage points">(${d > 0 ? "+" : ""}${d})</span></span></div>`;
  }

  const VERDICT = {
    "balanced": "Both teams improve by a similar amount, so this is a realistic offer.",
    "favours you": "You gain more than they do. It could still be accepted, especially if it fills a need for them.",
    "lopsided (tough sell)": "You gain far more than they do. Expect a no unless they value something the numbers don't.",
    "they'd likely decline": "Their lineup gets worse, so they'd likely decline.",
    "favours them": "This makes your team worse over the rest of the season.",
    "bad for both": "Neither team's projected lineup improves.",
  };

  function renderLabResult(res) {
    const L = DATA.lab, E = engine(), P = L.players;
    const conf = L.confidence;
    const name = (pid) => esc(P[pid].n);
    const cls = res.balance.startsWith("balanced") ? "balanced" : (res.balance.startsWith("favours you") ? "favours" : "lopsided");
    const tile = (pid) => {
      const r = P[pid];
      return `<div class="tp" data-pid="${esc(pid)}" role="button" tabindex="0"><div class="pl">${esc(r.n)}${
        r.s ? ` <span class="chip ${r.s === "Questionable" ? "q" : "inj"}">${esc(r.s)}</span>` : ""}${CARDS[pid] ? ` <span class="chev">▸</span>` : ""}</div>
        <div class="pmeta">${esc(r.p)} · ${esc(r.t)} · <b>${num(r.r)}</b>/wk (${num(Math.max(r.r - r.sd, 0), 0)}–${num(r.r + r.sd, 0)})</div>
        <div class="pmeta">ROS ${num(r.ros, 0)} · ${E.vor(pid) >= 0 ? "+" : ""}${num(E.vor(pid), 0)} vs repl. ${confChip(r.c)}</div></div>`;
    };
    const notes = [];
    const names = (ids) => ids.map((p) => P[p] ? P[p].n : p).join(", ");
    if (res.moves.me.drop.length) notes.push(`You'd cut ${names(res.moves.me.drop)} to make room. Counted in the value.`);
    if (res.moves.them.drop.length) notes.push(`They'd cut ${names(res.moves.them.drop)} to make room. Counted in their value.`);
    res.flagged.forEach((pid) => notes.push(`${P[pid].n} has little trade value here (kicker/defence, long-term injury or no games yet).`));
    const whyHtml = `<div class="pd-h" style="margin-top:12px">Why</div><ul class="tight">${
      res.reasons.concat(notes).map((r) => `<li>${esc(r)}</li>`).join("") || "<li>No positional need is filled either way; the change comes from overall projected points.</li>"}</ul>`;
    let html = `<div class="card card-pad">
      <div class="trade-head"><span class="chip ${cls}">${esc(res.balance)}</span>${confChip(res.confidence)}</div>
      <div class="gains" style="margin:8px 0"><span class="gain me">You ${signed(res.gainMe)} pts ROS (${signed(res.perWeekMe)}/wk)</span>
        <span class="gain">Them ${signed(res.gainThem)} pts</span></div>
      <div class="subtle">${esc(VERDICT[res.balance] || "")}</div>${whyHtml}${
        ""}<div class="acts"><button type="button" class="mini" data-act="improve">Optimise this deal</button><button type="button" class="mini" data-act="ask" data-kind="trade">Ask Claude</button>${
        labState.offers && labState.offers.offers.length > 1 ? `<button type="button" class="mini" data-act="jump-offers">See other suggested offers ↓</button>` : ""}</div>
        <div id="lab-improve"></div></div>`;
    html += `<h2>Players in the deal</h2><div class="card card-pad has-detail"><div class="swap">
      <div><div class="col-label">You give</div>${res.give.map(tile).join("")}</div><div class="arrow">⇄</div>
      <div><div class="col-label">You get</div>${res.get.map(tile).join("")}</div></div>
      <div class="trade-detail" hidden></div></div>`;


    html += `<h2>Playoff odds</h2><div class="card card-pad">
      ${oddsLine("You", res.odds.me, conf)}${oddsLine(esc(L.rosters[res.them].team_name), res.odds.them, conf)}
      <div class="subtle">Projected wins: you ${num(res.odds.meWins[0])} → ${num(res.odds.meWins[1])} ·
        them ${num(res.odds.themWins[0])} → ${num(res.odds.themWins[1])}. Bracketed numbers are the change in percentage points (calculated before rounding). Same simulated seasons
        before and after, so the change is the trade, not luck.</div></div>`;

    const lc = res.lineupChange;
    const list = (ids) => ids.length ? ids.map(name).join(", ") : "no change";
    html += `<h2>Lineup in week ${esc(lc.week)}</h2><div class="card card-pad">
      <div><b>You:</b> start ${list(lc.me.in)}${lc.me.out.length ? `; out of the lineup: ${list(lc.me.out)}` : ""}</div>
      <div><b>Them:</b> start ${list(lc.them.in)}${lc.them.out.length ? `; out of the lineup: ${list(lc.them.out)}` : ""}</div></div>`;

    const dealByes = res.give.concat(res.get).flatMap((pid) => P[pid].b.map((w) => [w, pid]));
    html += `<h2>Week by week</h2><div class="card table-wrap"><table class="named">
      <thead><tr><th>Week</th><th>You</th><th>Them</th><th class="hide-sm">Your proj</th></tr></thead><tbody>${
      res.weekly.map((w) => {
        const byes = dealByes.filter(([wk]) => wk === w.week).map(([, pid]) => name(pid));
        return `<tr><td>Wk ${w.week}${byes.length ? ` <span class="subtle">bye: ${byes.join(", ")}</span>` : ""}</td>
          ${deltaCell(w.me)}${deltaCell(w.them)}<td class="hide-sm">${num(w.meAfter)}</td></tr>`;
      }).join("")}</tbody></table></div>
      <p class="subtle">Change in each team's expected points per week (best lineup, byes, injury cover and roster-spot moves),
        so the rows add up to the headline gain.</p>`;

    const keys = ["QB", "RB", "WR", "TE", "FLEX"];
    const pm0 = res.before.profiles[res.me], pm1 = res.after.profiles[res.me];
    const pt0 = res.before.profiles[res.them], pt1 = res.after.profiles[res.them];
    html += `<h2>Positional strength (pts/wk)</h2><div class="card table-wrap"><table class="named">
      <thead><tr><th>Pos</th><th>You</th><th>Δ</th><th>Them</th><th>Δ</th></tr></thead><tbody>${
      keys.map((k) => `<tr><td><b>${k}</b></td><td>${num(pm1.strength[k])}</td>${deltaCell(pm1.strength[k] - pm0.strength[k])}
        <td>${num(pt1.strength[k])}</td>${deltaCell(pt1.strength[k] - pt0.strength[k])}</tr>`).join("")}</tbody></table></div>
      <p class="subtle">Your needs before: ${esc(pm0.needs.join(", ") || "none")} → after: ${esc(pm1.needs.join(", ") || "none")}.
        Theirs: ${esc(pt0.needs.join(", ") || "none")} → ${esc(pt1.needs.join(", ") || "none")}.</p>`;


    return html;
  }

  function renderTradeLab() {
    const host = $("tab-lab");
    const L = DATA.lab, E = engine();
    if (!L || !E) { host.innerHTML = `<div class="empty">Trade Lab needs the latest data. Run an update.</div>`; return; }
    const me = String(L.my_roster_id);
    const others = Object.keys(L.rosters).filter((t) => t !== me);
    if (!labState || !L.rosters[labState.partner]) labState = { partner: others[0], give: [], get: [] };
    const mine = E.rosterOf(me), theirs = E.rosterOf(labState.partner);
    labState.give = labState.give.filter((p) => mine.includes(p));
    labState.get = labState.get.filter((p) => theirs.includes(p));
    store.set("labState", labState);

    const opts = others.map((t) => `<option value="${t}" ${t === String(labState.partner) ? "selected" : ""}>${
      esc(L.rosters[t].team_name)}: ${esc(L.rosters[t].label)}</option>`).join("");
    const check = E.selfCheck();
    host.innerHTML = `<h2>Trade Lab</h2><p class="lead-text">Build any trade and see what it does to both teams for the rest of the season.
      Numbers update as you tap. Suggestions, not advice.</p>
      ${check.ok ? "" : `<div class="alert">Heads up: the in-browser maths differs from the last update by ${num(check.maxDiff)} pts. Refresh after the next update.</div>`}
      <label class="subtle" for="lab-partner">Trade with</label>
      <select id="lab-partner">${opts}</select>
      <div class="lab-cols">
        <div><div class="col-label">You give (${labState.give.length})</div><div class="picks">${pickChips(mine, labState.give, "give")}</div></div>
        <div><div class="col-label">You get (${labState.get.length})</div><div class="picks">${pickChips(theirs, labState.get, "get")}</div></div>
      </div>
      <div class="lab-actions"><button type="button" class="btn" id="lab-suggest" ${(labState.give.length > 0) !== (labState.get.length > 0) ? "" : "disabled"}>Suggest offers</button>
        <button type="button" class="btn secondary" id="lab-clear">Clear</button></div>
      <p class="subtle">Pick only who you want (or only who you're shopping) and tap <b>Suggest offers</b>. Numbers on the right are projected pts/week.</p>
      <div id="lab-result">${labState.give.length && labState.get.length ? `<div class="empty">Calculating…</div>`
        : labState.offers || labState.give.length || labState.get.length ? "" : `<div class="empty">Pick at least one player on each side.</div>`}</div>
      <div id="lab-offers">${labState.offers ? offersHtml(labState.offers) : ""}</div>
      <details class="recent"><summary>How the Trade Lab works</summary><div class="card card-pad subtle">
        <p>Each team's value is its best projected lineup for every remaining regular-season week (byes and known injuries
        included), the same maths as the Trades tab. Two adjustments make uneven trades fair:</p>
        <p><b>Free-agent floor:</b> every lineup spot is worth at least what the best free agent at that position would score,
        because any team can pick one up. So only points <i>above</i> free-agent level count: two "fine" players aren't
        automatically worth one star, and a throw-in who wouldn't beat a free agent adds nothing.</p>
        <p><b>Roster spots:</b> a team that ends up over the ${DATA.lab.roster_size}-player limit cuts its least valuable player
        (the side receiving two players in a 2-for-1 pays for that).</p>
        <p><b>Injury cover:</b> every starter has about a ${Math.round(100 * DATA.lab.absence_rate)}% chance of missing any given
        week beyond what's known today. The expected cost is what you'd lose after covering with your best eligible bench
        player or a free agent. So depth is worth exactly what it would cover, no more.</p>
        <p>Playoff odds come from simulating the rest of the season on the real schedule before and after the trade,
        using the same random seasons both times and the same weekly points as the trade value (so odds and gains agree).
        That's why the "before" odds can differ slightly from the Playoffs tab, which uses each team's lineup exactly as it
        stands. Odds are rounded while confidence is ${esc(L.confidence)}.</p>
        <p>Positional strength compares projected points per week from each position with the league median.</p></div></details>`;

    $("lab-partner").addEventListener("change", (e) => { labState = { partner: e.target.value, give: labState.give, get: [] }; renderTradeLab(); });
    $("lab-clear").addEventListener("click", () => { labState = { partner: labState.partner, give: [], get: [] }; renderTradeLab(); });
    $("lab-suggest").addEventListener("click", () => runSuggestions());
    wireOffers();
    if (labState.autoSuggest) { labState.autoSuggest = false; runSuggestions(); }
    host.querySelectorAll(".pick").forEach((b) => b.addEventListener("click", () => {
      const list = labState[b.dataset.side];
      const i = list.indexOf(b.dataset.pid);
      if (i >= 0) list.splice(i, 1); else list.push(b.dataset.pid);
      renderTradeLab();
    }));
    if (labState.give.length && labState.get.length) {
      setTimeout(() => {
        const res = E.evaluateTrade(labState.partner, labState.give, labState.get);
        $("lab-result").innerHTML = renderLabResult(res);
        wireExpanders($("lab-result"), (pid) => labPlayer(pid));
      }, 30);
    }
  }

  function offersHtml(o) {
    const P = DATA.lab.players, R = DATA.lab.rosters;
    const who = labState.get.length ? labState.get : labState.give;
    const subject = who.map((p) => esc(P[p].n)).join(" + ");
    if (!o.offers.length) {
      return `<h2>Suggested offers</h2><div class="card"><div class="empty">No realistic offer found for ${subject}.
        Every deal of similar value either costs you points or doesn't help the other team${labState.get.length ? "" : " — they may simply be worth more to you than in a trade"}.</div></div>`;
    }
    const names = (ids) => ids.map((p) => esc(P[p].n)).join(" + ");
    const same = (a, b) => a.length === b.length && a.every((p) => b.includes(p));
    const isLoaded = (x) => String(x.partner) === String(labState.partner) && same(x.give, labState.give) && same(x.get, labState.get);
    const showing = labState.give.length && labState.get.length;
    return `<h2>${showing ? "Other suggested offers" : "Suggested offers"}</h2>
      <p class="subtle">${o.anyAcceptable
        ? "Deals of similar value where you don't lose points and they gain, fairest first."
        : "Nothing of similar value helps both teams right now. These come closest: they don't cost you, but the other team would lose a little, so expect to negotiate."}</p>
      <div class="card">${o.offers.map((x, i) => {
        const cls = x.gainThem <= 0 ? "lopsided" : x.balance.startsWith("balanced") ? "balanced" : x.balance.startsWith("favours you") ? "favours" : "lopsided";
        const label = x.gainThem <= 0 ? "close — needs a sweetener" : x.balance;
        const shape = `${x.give.length}-for-${x.get.length}`;
        return `<div class="trade offer"><div class="trade-head"><div class="pname">${esc(R[x.partner].team_name)}</div><span class="chip ${cls}">${esc(label)}</span></div>
          <div class="subtle" style="margin:4px 0 8px">Give <b>${names(x.give)}</b> · get <b>${names(x.get)}</b>
            <br>${shape}${x.fits && x.fits.length ? " · " + esc(x.fits.join(" · ")) : ""}</div>
          <div class="gains"><span class="gain me">You ${signed(x.gainMe)}</span><span class="gain">Them ${signed(x.gainThem)}</span>
            ${isLoaded(x) ? `<span class="mini on">Showing above</span>` : `<button type="button" class="mini" data-offer="${i}">Load</button>`}</div></div>`;
      }).join("")}</div>`;
  }

  let IMPROVE = null;
  function runImprove() {
    const P = DATA.lab.players;
    const box = $("lab-improve");
    IMPROVE = engine().improveTrade(labState.partner, labState.give, labState.get);
    const n = (p) => `<b>${esc(P[p].n)}</b>`;
    const say = (e) => {
      const bits = [];
      const added = (side) => e.added.filter(([sd]) => sd === side).map(([, p]) => p);
      const removed = (side) => e.removed.filter(([sd]) => sd === side).map(([, p]) => p);
      for (const side of ["give", "get"]) {
        const a = added(side), r = removed(side);
        const list = (ids) => ids.map(n).join(" + ");
        if (a.length && r.length) bits.push(side === "give" ? `offer ${list(a)} instead of ${list(r)}` : `ask for ${list(a)} instead of ${list(r)}`);
        else if (a.length) bits.push(side === "give" ? `add ${list(a)} to your side` : `also ask for ${list(a)}`);
        else if (r.length) bits.push(side === "give" ? `keep ${list(r)}` : `drop ${list(r)} from your ask`);
      }
      const t = bits.join(", and ");
      return t.charAt(0).toUpperCase() + t.slice(1) + ".";
    };
    const row = (e, i, tag) => `<div class="edit"><div class="pd-h">${esc(tag)}</div><div>${say(e)}</div>
      <div class="gains"><span class="gain me">You ${signed(e.gainMe)}</span><span class="gain">Them ${signed(e.gainThem)}</span>
        <button type="button" class="mini" data-act="apply-edit" data-i="${i}">Apply</button></div></div>`;
    const c = IMPROVE.current;
    let html = "";
    if (IMPROVE.edits.length) {
      html = `<p class="subtle">${IMPROVE.acceptable ? "This already works for both teams. It could be better:" :
        c.gainMe < 0 ? "As built, this costs you points. Ways to fix it:" : "As built, they'd likely say no. Ways to fix it:"}</p>`
        + IMPROVE.edits.map((e, i) => row(e, i, e.tag)).join("");
    } else if (IMPROVE.acceptable) {
      html = `<p class="subtle">Already about as good as it gets: no tweak of up to two players improves it for you without costing them.</p>`;
    } else if (IMPROVE.closest) {
      html = `<p class="subtle">No tweak of up to two players (keeping ${n(IMPROVE.core[0])} and ${n(IMPROVE.core[1])}) makes this work for both teams. The closest:</p>`
        + row(IMPROVE.closest, IMPROVE.edits.length, "Closest") + `<p class="subtle">Try <b>Suggest offers</b> with just the player you want.</p>`;
    } else {
      html = `<p class="subtle">No tweak of up to two players gets this to a deal that doesn't cost you. Try <b>Suggest offers</b> with just the player you want.</p>`;
    }
    box.innerHTML = `<div class="improve">${html}</div>`;
  }

  function wireOffers() {
    const box = $("lab-offers");
    if (!box) return;
    box.querySelectorAll("[data-offer]").forEach((b) => b.addEventListener("click", () => {
      const x = labState.offers.offers[Number(b.dataset.offer)];
      labState = Object.assign({}, labState, { partner: x.partner, give: x.give.slice(), get: x.get.slice() });
      store.set("labState", labState);
      renderTradeLab();
      const r = $("lab-result");
      if (r) setTimeout(() => r.scrollIntoView({ block: "start", behavior: "smooth" }), 60);
    }));
  }

  function runSuggestions() {
    const E = engine();
    $("lab-offers").innerHTML = `<div class="card"><div class="empty">Searching trades…</div></div>`;
    setTimeout(() => {
      const res = labState.get.length
        ? E.suggestOffers({ get: labState.get, partner: labState.partner })
        : E.suggestOffers({ give: labState.give, partner: labState.shopAll ? null : labState.partner });
      labState.offers = res;
      store.set("labState", labState);
      $("lab-offers").innerHTML = offersHtml(res);
      wireOffers();
    }, 30);
  }

  function openInLab(partner, give, get, opts) {
    labState = { partner: String(partner), give: give.slice(), get: get.slice(),
      autoSuggest: !!(opts && opts.suggest), shopAll: !!(opts && opts.shopAll), offers: null };
    store.set("labState", labState);
    selectTab("lab");
    renderTradeLab();
    window.scrollTo(0, 0);
  }

  function defaultDrop(pids) {
    const L = DATA.lab, E = engine(), P = L.players;
    const size = pids.filter((p) => !(L.rosters[String(L.my_roster_id)].reserve || []).includes(p)).length;
    if (size < L.roster_size) return null;
    const isKD = (p) => (P[p].p === "K" || P[p].p === "DEF" ? 1 : 0);
    const cands = pids.filter((p) => P[p] && !isHeld(p)).sort((a, b) => (isKD(a) - isKD(b)) || (E.vor(a) - E.vor(b)));
    return cands[0] || null;
  }

  function planPickup(pid) {
    const L = DATA.lab;
    if (!plan || !L.weeks.includes(plan.week)) plan = planDefaults();
    if (!plan.moves.some((m) => m.add === pid)) {
      plan.moves.push({ add: pid, drop: defaultDrop(planRoster(L.current_week + 1)) });
      plan.lineups = {};
    }
    plan.week = L.weeks.includes(L.current_week + 1) ? L.current_week + 1 : plan.week;
    store.set("plannerState", plan);
    selectTab("planner");
    renderPlanner();
  }

  function toggleHold(pid) {
    if (HOLDS.has(pid)) HOLDS.delete(pid); else HOLDS.add(pid);
    store.set("holds", [...HOLDS]);
    if (ENGINE) ENGINE.setHolds([...HOLDS]);
    // Re-draw, keeping open player panels open and the page where it was.
    const open = [...document.querySelectorAll("#tab-home details.prow-d[open]")].map((d) => d.dataset.pid);
    const y = window.scrollY;
    renderHome(); renderTrades(); renderTradeLab(); renderPlanner();
    open.forEach((id) => { const d = document.querySelector(`#tab-home details.prow-d[data-pid="${CSS.escape(id)}"]`); if (d) d.open = true; });
    window.scrollTo(0, y);
  }

  // ---------- Planner ----------
  const FLEXP = { FLEX: ["RB", "WR", "TE"], WRRB_FLEX: ["RB", "WR"], REC_FLEX: ["WR", "TE"], SUPER_FLEX: ["QB", "RB", "WR", "TE"] };
  let plan = store.get("plannerState", null);

  function planDefaults() {
    const L = DATA.lab;
    return { week: L.weeks.includes(L.current_week + 1) ? L.current_week + 1 : L.weeks[0], moves: [], lineups: {} };
  }

  function phiJs(z) {   // standard normal CDF
    const t = 1 / (1 + 0.2316419 * Math.abs(z));
    const d = 0.3989423 * Math.exp(-z * z / 2);
    const p = d * t * (0.3193815 + t * (-0.3565638 + t * (1.781478 + t * (-1.821256 + t * 1.330274))));
    return z > 0 ? 1 - p : p;
  }

  function planRoster(week) {
    const L = DATA.lab, E = engine();
    let pids = E.rosterOf(L.my_roster_id);
    if (week > L.current_week) {
      plan.moves.forEach((m) => { pids = pids.filter((p) => p !== m.drop); if (!pids.includes(m.add)) pids.push(m.add); });
    }
    return pids;
  }

  function eligible(slot, pid) {
    const pos = DATA.lab.players[pid] && DATA.lab.players[pid].p;
    return (FLEXP[slot] || [slot]).includes(pos);
  }

  /* The lineup shown for a week: saved edits if still valid, else Sleeper's set lineup
     (this week) or the best projected lineup (future weeks). Returns pids aligned with slots. */
  function planLineup(week) {
    const L = DATA.lab, E = engine();
    const pids = planRoster(week);
    const w = L.weeks.indexOf(week);
    const saved = plan.lineups[String(week)];
    if (saved && saved.length === L.slots.length
        && saved.every((pid, i) => !pid || (pids.includes(pid) && eligible(L.slots[i], pid)))
        && new Set(saved.filter(Boolean)).size === saved.filter(Boolean).length) return saved.slice();
    if (week === L.current_week && L.this_week[String(L.my_roster_id)]) {
      const set = L.this_week[String(L.my_roster_id)].starters.map((p) => (p && p !== "0" && pids.includes(p) ? p : null));
      if (set.length === L.slots.length) return set;
    }
    const best = E.lineup(pids, w).lineup;
    const out = L.slots.map(() => null);
    const used = new Set();
    best.forEach(([slot, pid]) => {
      const i = L.slots.findIndex((s, j) => s === slot && !out[j]);
      if (i >= 0) { out[i] = pid; used.add(pid); }
    });
    return out;
  }

  function weekPts(pid, week) {
    const L = DATA.lab, r = L.players[pid], w = L.weeks.indexOf(week);
    if (!r) return { pts: 0, v: 0, locked: false };
    if (week === L.current_week && r.a != null) return { pts: r.a, v: 0, locked: true };
    return { pts: r.w[w], v: r.v[w], locked: false };
  }

  function lineupStats(lineup, week) {
    let mean = 0, v = 0;
    lineup.forEach((pid) => { if (pid) { const x = weekPts(pid, week); mean += x.pts; v += x.v; } });
    return { mean, sd: Math.sqrt(v) };
  }

  /* Best lineup for the week, keeping players whose games are already over in place. */
  function bestLineup(week) {
    const L = DATA.lab;
    const pids = planRoster(week);
    const current = planLineup(week);
    const out = L.slots.map((s, i) => (current[i] && weekPts(current[i], week).locked ? current[i] : null));
    const used = new Set(out.filter(Boolean));
    const pool = pids.filter((p) => !used.has(p) && !weekPts(p, week).locked)
      .sort((a, b) => weekPts(b, week).pts - weekPts(a, week).pts);
    const order = L.slots.map((s, i) => [s, i]).sort((a, b) => ((a[0] in FLEXP) - (b[0] in FLEXP)) || a[1] - b[1]);
    order.forEach(([slot, i]) => {
      if (out[i]) return;
      const pick = pool.find((p) => !used.has(p) && eligible(slot, p));
      if (pick) { out[i] = pick; used.add(pick); }
    });
    return out;
  }

  function opponentFor(week) {
    const L = DATA.lab, me = L.my_roster_id;
    const g = (L.schedule[String(week)] || []).find(([a, b]) => a === me || b === me);
    return g ? String(g[0] === me ? g[1] : g[0]) : null;
  }

  function renderPlanner() {
    const host = $("tab-planner");
    const L = DATA.lab, E = engine();
    if (!L || !E) { host.innerHTML = `<div class="empty">Planner needs the latest data. Run an update.</div>`; return; }
    if (!plan || !L.weeks.includes(plan.week)) plan = Object.assign(planDefaults(), plan && { moves: plan.moves || [], lineups: {} });
    const P = L.players, me = String(L.my_roster_id), conf = L.confidence;
    // drop moves that no longer make sense (player gone from free agency or my roster)
    const base = E.rosterOf(me);
    plan.moves = plan.moves.filter((m) => P[m.add] && P[m.add].o == null && (!m.drop || base.includes(m.drop)));
    store.set("plannerState", plan);

    const week = plan.week, w = L.weeks.indexOf(week);
    const lineup = planLineup(week);
    const roster = planRoster(week);
    const stats = lineupStats(lineup, week);
    const best = lineupStats(bestLineup(week), week);
    const opp = opponentFor(week);
    let oppStats = null;
    if (opp) {
      oppStats = week === L.current_week && L.this_week[opp] ? { mean: L.this_week[opp].mean, sd: L.this_week[opp].sd }
        : (() => { const lu = E.lineup(E.rosterOf(opp), w); return { mean: lu.total, sd: lu.sd }; })();
    }
    const winP = oppStats ? phiJs((stats.mean - oppStats.mean) / Math.sqrt(stats.sd ** 2 + oppStats.sd ** 2 || 1)) : null;
    const left = best.mean - stats.mean;

    const chips = L.weeks.map((wk) => `<button type="button" data-w="${wk}" aria-pressed="${wk === week}">${wk === L.current_week ? "This wk" : `Wk ${wk}`}</button>`).join("");
    let html = `<h2>Planner</h2><p class="lead-text">Forecast your lineup for any week: swap bench players in, or plan waiver
      pickups and see the effect on the week, the season and your playoff odds. Your plan is saved on this device.</p>
      <div class="weekchips" id="pl-weeks">${chips}</div>`;

    html += `<div class="card card-pad">
      <div class="trade-head"><div class="pname">Week ${week}${opp ? ` vs ${esc(L.rosters[opp].team_name)}` : ""}</div>${winP != null ? `<span class="chip ${winP >= 0.5 ? "balanced" : "lopsided"}">${pctText(winP, conf)} to win</span>` : ""}</div>
      <div class="stats" style="margin:8px 0 4px">
        <div class="stat"><div class="v">${num(stats.mean)}</div><div class="l">Your lineup</div></div>
        <div class="stat"><div class="v">${num(best.mean)}</div><div class="l">Best possible</div></div>
        <div class="stat"><div class="v">${oppStats ? num(oppStats.mean) : "–"}</div><div class="l">Opponent</div></div>
      </div>
      <div class="subtle">Likely ${num(Math.max(stats.mean - stats.sd, 0), 0)}–${num(stats.mean + stats.sd, 0)}.
        ${left > 0.5 ? `<b style="color:var(--warn)">${num(left)} pts left on the bench.</b> <button type="button" class="btn secondary" id="pl-best" style="padding:4px 10px;font-size:.8rem">Use best lineup</button>`
          : "This is your best projected lineup."}
        ${week === L.current_week ? " Players whose games are over are locked." : ""}</div></div>`;

    // lineup slots
    const inLineup = new Set(lineup.filter(Boolean));
    html += `<h2>Lineup</h2><div class="card">${L.slots.map((slot, i) => {
      const pid = lineup[i];
      const x = pid ? weekPts(pid, week) : null;
      const options = roster.filter((p) => eligible(slot, p) && !weekPts(p, week).locked)
        .sort((a, b) => weekPts(b, week).pts - weekPts(a, week).pts)
        .map((p) => `<option value="${esc(p)}" ${p === pid ? "selected" : ""}>${esc(P[p].n)} · ${num(weekPts(p, week).pts)}${P[p].op[w] === "BYE" ? " (bye)" : ""}</option>`).join("");
      const opTxt = pid ? (P[pid].op[w] || "") : "";
      return `<div class="prow pl-row"><span class="slot ${esc(slot)}">${esc(slot)}</span>
        <div>${x && x.locked ? `<div class="pname">${esc(P[pid].n)} <span class="subtle">final</span></div>`
          : `<select class="pl-slot" data-i="${i}" aria-label="${esc(slot)} slot">${pid ? "" : `<option value="">Empty</option>`}${options}</select>`}
          <div class="pmeta">${pid ? `${esc(P[pid].p)} · ${esc(P[pid].t)}${opTxt ? ` · ${opTxt === "BYE" ? "<b style='color:var(--bad)'>BYE</b>" : esc(opTxt)}` : ""}${P[pid].s ? ` · <span style="color:var(--warn)">${esc(P[pid].s)}</span>` : ""}` : "No eligible player"}</div></div>
        <div class="pnums"><div class="big">${x ? num(x.pts) : "–"}</div></div></div>`;
    }).join("")}</div>`;

    const bench = roster.filter((p) => !inLineup.has(p)).sort((a, b) => weekPts(b, week).pts - weekPts(a, week).pts);
    html += `<h2>Bench</h2><div class="card">${bench.map((p) => {
      const x = weekPts(p, week), added = plan.moves.some((m) => m.add === p) && week > L.current_week;
      return `<div class="prow"><span class="slot BN">BN</span><div><div class="pname">${esc(P[p].n)}${added ? ` <span class="chip ok-style">planned add</span>` : ""}</div>
        <div class="pmeta">${esc(P[p].p)} · ${esc(P[p].t)}${P[p].op[w] ? ` · ${esc(P[p].op[w])}` : ""}${P[p].s ? ` · ${esc(P[p].s)}` : ""}</div></div>
        <div class="pnums"><div class="big">${x.locked ? num(x.pts) : num(x.pts)}</div><div class="small">${x.locked ? "final" : "proj"}</div></div></div>`;
    }).join("") || `<div class="empty">No bench players.</div>`}</div>`;

    // waiver planning
    const size = base.filter((p) => !(L.rosters[me].reserve || []).includes(p)).length + plan.moves.filter((m) => !m.drop).length;
    html += `<h2>Plan waiver pickups</h2>
      <p class="lead-text">Moves apply from week ${L.current_week + 1}, after waivers process. ${size < L.roster_size ? `You have ${L.roster_size - size} open roster spot(s).` : "Your roster is full, so each add needs a drop."}</p>`;
    if (plan.moves.length) {
      html += `<div class="card">${plan.moves.map((m, i) => `<div class="prow" style="grid-template-columns:minmax(0,1fr) auto">
        <div><span style="color:var(--good)">+ ${esc(P[m.add].n)}</span> <span class="pmeta">${esc(P[m.add].p)} · ${num(P[m.add].r)}/wk</span>
          ${m.drop ? `<br><span class="muted">− ${esc(P[m.drop].n)}</span> <span class="pmeta">${num(P[m.drop].r)}/wk</span>` : ""}</div>
        <button type="button" class="btn secondary pl-undo" data-i="${i}" style="padding:4px 10px;font-size:.8rem">Remove</button></div>`).join("")}</div>`;
    }
    const fas = Object.keys(P).filter((p) => P[p].o == null && !plan.moves.some((m) => m.add === p));
    html += `<div class="pl-search"><input type="search" id="pl-q" placeholder="Search free agents" aria-label="Search free agents">
      <div class="weekchips" id="pl-pos">${["All", "QB", "RB", "WR", "TE", "K", "DEF"].map((x) => `<button type="button" data-pos="${x}" aria-pressed="${x === "All"}">${x}</button>`).join("")}</div></div>
      <div class="card" id="pl-fas"></div>`;

    // season impact
    const moved = plan.moves.length > 0;
    const edited = Object.keys(plan.lineups).length > 0;
    if (moved || edited) {
      const rows = [];
      let total = 0;
      L.weeks.forEach((wk, j) => {
        const b0 = E.lineup(E.rosterOf(me), j).total;
        const p1 = wk > L.current_week ? E.lineup(planRoster(wk), j).total : b0;
        total += p1 - b0;
        rows.push({ wk, b0, p1, d: p1 - b0 });
      });
      const odds0 = E.simulate({}, { n: 3000 });
      const over = {};
      Object.keys(plan.lineups).forEach((wk) => {
        const s = lineupStats(planLineup(Number(wk)), Number(wk));
        if (Number(wk) !== L.current_week) over[`${me}|${wk}`] = s;
      });
      const odds1 = E.simulate({ [me]: planRoster(L.current_week + 1) }, { n: 3000, weekOverrides: over });
      const d = Math.round(100 * (odds1[me].odds - odds0[me].odds));
      html += `<h2>Season impact</h2><div class="card card-pad">
        <div class="odds-row"><span>Rest of season</span><span class="${total > 0 ? "up" : total < 0 ? "down" : ""}"><b>${total > 0 ? "+" : ""}${num(total)}</b> pts (best lineups)</span></div>
        <div class="odds-row"><span>Playoff odds</span><span><b>${pctText(odds0[me].odds, conf)}</b> → <b>${pctText(odds1[me].odds, conf)}</b>
          <span class="${d > 0 ? "up" : d < 0 ? "down" : "muted"}">(${d > 0 ? "+" : ""}${d})</span></span></div>
        <div class="subtle">Your saved lineup edits are included in the odds. Bracketed number = change in percentage points.</div></div>
        <div class="card table-wrap"><table class="named"><thead><tr><th>Week</th><th>Now</th><th>Plan</th><th>Δ</th></tr></thead><tbody>${
        rows.map((r) => `<tr><td>Wk ${r.wk}</td><td>${num(r.b0)}</td><td>${num(r.p1)}</td>${deltaCell(r.d)}</tr>`).join("")}</tbody></table></div>`;
    }
    html += `<div class="lab-actions"><button type="button" class="btn secondary" id="pl-reset">Reset plan</button>
      <span class="subtle">Clears planned pickups and lineup edits.</span></div>
      <details class="recent"><summary>How the Planner works</summary><div class="card card-pad subtle">
      <p>Projections are the same as everywhere else in the dashboard (byes and injury designations included). This week starts
      from your actual Sleeper lineup; future weeks start from your best projected lineup.</p>
      <p>Win chance compares your lineup's projected score and spread with your opponent's (their actual lineup this week,
      their best projected lineup in later weeks). Planned pickups count from next week. Nothing here changes your real
      Sleeper team.</p></div></details>`;
    host.innerHTML = html;

    // wiring
    host.querySelectorAll("#pl-weeks button").forEach((b) => b.addEventListener("click", () => { plan.week = Number(b.dataset.w); renderPlanner(); }));
    host.querySelectorAll(".pl-slot").forEach((sel) => sel.addEventListener("change", () => {
      const i = Number(sel.dataset.i), pid = sel.value;
      const cur = planLineup(week);
      const j = cur.indexOf(pid);
      const prev = cur[i];
      cur[i] = pid || null;
      if (j >= 0 && j !== i) cur[j] = prev && eligible(L.slots[j], prev) ? prev : null;
      plan.lineups[String(week)] = cur;
      store.set("plannerState", plan);
      renderPlanner();
    }));
    const bestBtn = $("pl-best");
    if (bestBtn) bestBtn.addEventListener("click", () => { plan.lineups[String(week)] = bestLineup(week); store.set("plannerState", plan); renderPlanner(); });
    host.querySelectorAll(".pl-undo").forEach((b) => b.addEventListener("click", () => { plan.moves.splice(Number(b.dataset.i), 1); renderPlanner(); }));
    $("pl-reset").addEventListener("click", () => { plan = planDefaults(); plan.week = week; store.set("plannerState", plan); renderPlanner(); });

    let posFilter = "All";
    const drawFAs = () => {
      const q = ($("pl-q").value || "").toLowerCase();
      const list = fas.filter((p) => (posFilter === "All" || P[p].p === posFilter) && (!q || P[p].n.toLowerCase().includes(q)))
        .sort((a, b) => P[b].r - P[a].r).slice(0, 15);
      // weakest skill players first (so the default drop is the least valuable); K/DEF last
      const isKD = (p) => (P[p].p === "K" || P[p].p === "DEF" ? 1 : 0);
      const dropOpts = planRoster(L.current_week + 1).slice()
        .sort((a, b) => (isHeld(a) - isHeld(b)) || (isKD(a) - isKD(b)) || (E.vor(a) - E.vor(b)))
        .map((p) => `<option value="${esc(p)}">${esc(P[p].n)} (${esc(P[p].p)} · ${num(P[p].r)}/wk)${isHeld(p) ? " · held" : ""}</option>`).join("");
      $("pl-fas").innerHTML = list.map((p) => `<div class="fa-row"><div class="prow" style="grid-template-columns:44px minmax(0,1fr) auto">
        <span class="slot ${esc(P[p].p)}">${esc(P[p].p)}</span>
        <div><div class="pname">${esc(P[p].n)}${P[p].s ? ` <span class="chip ${P[p].s === "Questionable" ? "q" : "inj"}">${esc(P[p].s)}</span>` : ""}</div>
          <div class="pmeta">${esc(P[p].t)} · <b>${num(P[p].r)}</b>/wk · ROS ${num(P[p].ros, 0)} · ${esc(P[p].c)} conf${P[p].b.length ? ` · bye ${P[p].b.join(", ")}` : ""}</div>
          <div class="pmeta">Next: ${L.weeks.slice(Math.max(w, L.weeks.indexOf(L.current_week + 1)), Math.max(w, L.weeks.indexOf(L.current_week + 1)) + 3)
            .map((wk) => { const k = L.weeks.indexOf(wk); return `wk ${wk} ${P[p].op[k] === "BYE" ? "bye" : num(P[p].w[k])}`; }).join(" · ")}</div></div>
        <button type="button" class="btn secondary fa-add" data-pid="${esc(p)}" style="padding:4px 10px;font-size:.8rem">Add</button></div>
        <div class="fa-drop" hidden><label class="subtle">Drop</label><select class="fa-drop-sel">${size < L.roster_size ? `<option value="">Nobody (open spot)</option>` : ""}${dropOpts}</select>
          <button type="button" class="btn fa-confirm" data-pid="${esc(p)}" style="padding:6px 12px;font-size:.82rem">Plan it</button></div></div>`).join("")
        || `<div class="empty">No free agents match.</div>`;
      $("pl-fas").querySelectorAll(".fa-add").forEach((b) => b.addEventListener("click", () => {
        const box = b.closest(".fa-row").querySelector(".fa-drop"); box.hidden = !box.hidden;
      }));
      $("pl-fas").querySelectorAll(".fa-confirm").forEach((b) => b.addEventListener("click", () => {
        const drop = b.parentElement.querySelector(".fa-drop-sel").value || null;
        plan.moves.push({ add: b.dataset.pid, drop });
        plan.lineups = {};          // lineups change with the roster; start from best again
        store.set("plannerState", plan);
        renderPlanner();
      }));
    };
    $("pl-q").addEventListener("input", drawFAs);
    host.querySelectorAll("#pl-pos button").forEach((b) => b.addEventListener("click", () => {
      posFilter = b.dataset.pos;
      host.querySelectorAll("#pl-pos button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      drawFAs();
    }));
    drawFAs();
  }

  // ---------- Brief ----------
  // ---------- Model: how accurate projections have been, and what the model learned ----------
  const MD = DATA.model;
  function renderModel() {
    const host = $("tab-model");
    if (!MD) { host.innerHTML = `<div class="empty">No model report yet. Run an update.</div>`; return; }
    const bt = MD.backtest || {}, bd = MD.backtest_default || {}, L = MD.learned || {}, live = MD.live || {};
    const pctTxt = (x) => (x == null ? "–" : Math.round(100 * x) + "%");
    const better = bt.naive_mae ? 1 - bt.mae / bt.naive_mae : null;
    let html = `<h2>How accurate are the projections?</h2>
      <p class="lead-text">Every update re-runs the model for each completed week this season using only what was known before kickoff,
      then compares it with what players actually scored (${bt.games || 0} player-games so far, fantasy-relevant players only, full games).
      "In range" = the score landed inside the projected range; about 68% is right for a well-calibrated range.</p>`;
    if (!bt.games) {
      html += `<div class="card"><div class="empty">No completed weeks to check yet.</div></div>`;
    } else {
      html += `<div class="tiles head">
        ${tileHtml("Avg miss", `${num(bt.mae)}<small> pts</small>`, `per player-game`)}
        ${tileHtml("vs a simple guess", better == null ? "–" : `${better >= 0 ? "" : "−"}${Math.abs(Math.round(100 * better))}%<small> ${better >= 0 ? "better" : "worse"}</small>`, `guess = season avg so far (${num(bt.naive_mae)})`, better > 0 ? "good" : "warn")}
        ${tileHtml("In range", pctTxt(bt.coverage), "target ~68%", Math.abs(bt.coverage - 0.68) > 0.08 ? "warn" : "")}
        ${tileHtml("Bias", `${bt.bias >= 0 ? "+" : ""}${num(bt.bias)}`, bt.bias > 0.5 ? "projects a bit high" : bt.bias < -0.5 ? "projects a bit low" : "about right")}
      </div>
      <div class="card table-wrap" style="margin-top:12px"><table class="named"><thead><tr><th>Position</th><th>Games</th><th>Avg miss</th><th>Bias</th><th>In range</th><th class="hide-sm">Simple guess</th></tr></thead>
        <tbody>${Object.entries(bt.by_position || {}).map(([pos, v]) => `<tr><td><b>${esc(pos)}</b></td><td>${v.games}</td><td>${num(v.mae)}</td>
          <td>${v.bias >= 0 ? "+" : ""}${num(v.bias)}</td><td>${pctTxt(v.coverage)}</td><td class="hide-sm">${num(v.naive_mae)}</td></tr>`).join("")}</tbody></table></div>
      <div class="card table-wrap" style="margin-top:12px"><table class="named"><thead><tr><th>Week</th><th>Games</th><th>Avg miss</th><th>In range</th><th class="hide-sm">Simple guess</th></tr></thead>
        <tbody>${Object.entries(bt.by_week || {}).map(([w, v]) => `<tr><td>Wk ${esc(w)}</td><td>${v.games}</td><td>${num(v.mae)}</td><td>${pctTxt(v.coverage)}</td><td class="hide-sm">${num(v.naive_mae)}</td></tr>`).join("")}</tbody></table></div>`;
    }

    // what it learned
    const fmt = (c) => {
      if (c.key.startsWith("bias.")) { const d = Math.round(100 * (c.to - 1)); return `${esc(c.label)}: ${d > 0 ? d + "% higher" : -d + "% lower"}`; }
      if (c.key.startsWith("sd.")) { const d = Math.round(100 * (c.to - 1)); return `${esc(c.key.slice(3))} ranges ${d > 0 ? d + "% wider" : -d + "% narrower"}`; }
      return `${esc(c.label)}: ${c.from} → ${c.to}`;
    };
    const v = L.validation;
    html += `<h2>What it has learned</h2><div class="card card-pad">
      <div>${esc(L.reason || "")}</div>
      ${L.changed && L.changed.length ? `<ul class="tight" style="margin-top:8px">${L.changed.map((c) => `<li>${fmt(c)}</li>`).join("")}</ul>` : ""}
      ${bd.mae && bt.mae && L.changed && L.changed.length ? `<div class="subtle" style="margin-top:6px">Avg miss with the starting settings: ${num(bd.mae)} → with what it learned: ${num(bt.mae)} (in range ${pctTxt(bd.coverage)} → ${pctTxt(bt.coverage)}).</div>` : ""}
      ${v ? `<div class="subtle" style="margin-top:6px">Checked on week ${esc(v.week)}, which it didn't learn from: ${num(v.default_mae)} → ${num(v.learned_mae)} avg miss, so the changes ${v.passed ? "are switched on" : "were not trusted and are switched off"}.</div>` : ""}
    </div>`;
    const A = L.params && L.params.availability;
    if (A) {
      const rowA = (k, label) => A[k] && A[k].games ? `<tr><td>${label}</td><td>${A[k].played != null ? Math.round(100 * A[k].played) + "%" : "–"}</td><td><b>${Math.round(100 * A[k].share)}%</b></td><td>${A[k].games}</td></tr>` : "";
      html += `<h2>Injury designations</h2><p class="lead-text">Learned from last season's and this season's official injury reports: how often players
        with each designation actually played, and the share of their normal points they produced (counting 0 when they sat). Used for this week's projections.</p>
        <div class="card table-wrap"><table class="named"><thead><tr><th>Listed as</th><th>Played</th><th>Normal pts</th><th>Cases</th></tr></thead><tbody>
        ${rowA("Questionable|full", "Questionable · full practice")}${rowA("Questionable|limited", "Questionable · limited")}${rowA("Questionable|dnp", "Questionable · didn't practice")}
        ${rowA("Questionable", "Questionable (all)")}${rowA("Doubtful", "Doubtful")}${rowA("Out", "Out")}</tbody></table></div>
        <p class="subtle">Started from 85% / 25% / 0%, pulled toward those as if 25 cases agreed. A practice split is used once it has 20+ cases.</p>`;
    }
    const WX = L.params && L.params.weather;
    if (WX) {
      const f = (x) => { const d = Math.round(100 * (x - 1)); return `<span class="${d > 0 ? "up" : d < 0 ? "down" : "muted"}">${d > 0 ? "+" : ""}${d}%</span>`; };
      html += `<h2>Weather &amp; venue</h2><p class="lead-text">How each position scores vs its own average indoors, outdoors, in 15+ mph wind and at 32°F or colder
        (wind and cold compared with calm outdoor games). Forecasts come from Open-Meteo for games in the next 7 days.</p>
        <div class="card table-wrap"><table class="named"><thead><tr><th>Pos</th><th>Indoors</th><th>Outdoors</th><th>Windy</th><th>Freezing</th></tr></thead><tbody>
        ${Object.entries(WX).map(([pos, x]) => `<tr><td><b>${esc(pos)}</b></td><td>${f(x.dome)}</td><td>${f(x.outdoor)}</td><td>${f(x.wind)}</td><td>${f(x.cold)}</td></tr>`).join("")}</tbody></table></div>
        <p class="subtle">Currently applied at <b>${Math.round(100 * (L.params.weather_strength || 0))}%</b> strength: the learner only turns this up when it improves accuracy on this season's games${
          (L.params.weather_strength || 0) === 0 ? ", which it hasn't yet" : ""}. Recency: each older game counts ${L.params.recency === 1 ? "the same as the latest (no fade yet)" : `${Math.round(100 * L.params.recency)}% as much as the week after it`}.</p>`;
    }
    if (MD.history && MD.history.length > 1) {
      html += `<details class="recent"><summary>Week by week</summary><div class="card">${MD.history.slice().reverse().map((h) => `<div class="prow" style="display:block">
        <b>Week ${esc(h.week)}</b> <span class="subtle">· avg miss ${num(h.mae)} on ${h.games} games · in range ${pctTxt(h.coverage)}</span>
        <div class="subtle">${h.changed.length ? h.changed.map(fmt).join(" · ") : "starting settings"}</div></div>`).join("")}</div></details>`;
    }

    // live scorecard
    html += `<h2>Live scorecard</h2><p class="lead-text">What the dashboard actually showed before each game (injury news included), scored once the games are played.
      Players who didn't play count as 0, because that's what you'd have got.</p>`;
    if (!live.games) {
      html += `<div class="card"><div class="empty">Starts filling in after this week's games: each update saves the projections you see, and the next update after kickoff scores them.</div></div>`;
    } else {
      const mine = new Set(MD.my_players || []);
      const rows = (live.rows_last_week || []).filter((r) => mine.has(r.id)).sort((a, b) => b.pts - a.pts);
      const row = (r) => `<tr><td>${esc(r.name)} <span class="subtle">${esc(r.pos)}</span></td><td>${num(r.pts)}</td><td>${num(r.actual)}</td>
        <td class="${r.error > 0 ? "down" : "up"}">${r.error > 0 ? "−" : "+"}${num(Math.abs(r.error))}</td><td>${r.inside ? "✓" : ""}</td></tr>`;
      html += `<div class="tiles head">${tileHtml("Avg miss", `${num(live.mae)}<small> pts</small>`, `${live.games} player-games`)}
        ${tileHtml("In range", pctTxt(live.coverage), "target ~68%")}${tileHtml("Bias", `${live.bias >= 0 ? "+" : ""}${num(live.bias)}`, "")}</div>
        ${rows.length ? `<h2 style="font-size:1rem">Your players, week ${esc(live.last_week)}</h2><div class="card table-wrap"><table class="named">
          <thead><tr><th>Player</th><th>Proj</th><th>Scored</th><th>vs proj</th><th>In range</th></tr></thead><tbody>${rows.map(row).join("")}</tbody></table></div>` : ""}
        <h2 style="font-size:1rem">Biggest misses, week ${esc(live.last_week)}</h2><div class="card table-wrap"><table class="named">
          <thead><tr><th>Player</th><th>Proj</th><th>Scored</th><th>vs proj</th><th>In range</th></tr></thead><tbody>${(live.biggest_misses || []).map(row).join("")}</tbody></table></div>`;
    }
    html += `<details class="recent"><summary>How the learning works</summary><div class="card card-pad subtle">
      <p><b>Track record.</b> For every completed week, each fantasy-relevant player's projection is rebuilt with only the games before that week
      and compared with what he scored (league scoring). Partial games (hurt early) are left out.</p>
      <p><b>What it can adjust.</b> How much to trust usage vs actual points, last season vs this season, the pull toward a typical player at the
      position, and how strongly matchups count. It tries a small set of alternatives and switches only if the average miss drops by at least
      ${Math.round(100 * MD.settings.min_improvement)}% over at least ${MD.settings.min_games} games. It also corrects each position for running high or low and for
      ranges that are too narrow or wide, pulled toward "no change" as if ${MD.settings.shrink_games} games said so, and capped (±10% points, ranges −25% to +40%).</p>
      <p><b>Safety check.</b> Learned settings are re-learned without the latest week and tested on it. If they do worse there than the
      starting settings, they're switched off. Everything is recalculated from scratch each update, so a bad week can't permanently skew it.</p>
      <p><b>Live scorecard</b> is separate and honest: it scores exactly what the dashboard showed you, injuries and all.</p></div></details>`;
    host.innerHTML = html;
  }

  const B = DATA.brief;

  function renderBrief() {
    if (!B) { $("tab-brief").innerHTML = `<div class="empty">No brief yet.</div>`; return; }
    $("tab-brief").innerHTML = `<p class="lead-text" style="margin-top:12px">A compact, verified summary to paste into Claude
      for the weekly NFL update.</p>
      <div class="brief-bar">
        <button class="btn" id="copy-brief" type="button">Copy brief</button>
        <a class="btn secondary" href="data/claude_brief.md" download>Download .md</a>
        <span class="subtle" id="copy-status"></span>
      </div>
      <pre class="brief" id="brief-text">${esc(B.markdown)}</pre>`;
    $("copy-brief").addEventListener("click", async () => {
      const status = $("copy-status");
      try {
        await navigator.clipboard.writeText(B.markdown);
        status.textContent = "Copied ✓";
      } catch (e) {
        // file:// or older browsers: select the text so it can be copied manually
        const range = document.createRange();
        range.selectNodeContents($("brief-text"));
        const sel = getSelection();
        sel.removeAllRanges();
        sel.addRange(range);
        status.textContent = "Text selected. Press ⌘C / long-press to copy.";
      }
    });
  }

  // ---------- Ask Claude: package the relevant data as a message for the Claude app ----------
  // (no API: shares via the phone's share sheet, or copies to paste into Claude)
  const pnm = (pid) => (DATA.lab && DATA.lab.players[pid] ? DATA.lab.players[pid].n : (CARDS[pid] && CARDS[pid].name) || pid);
  const ownerText = (pid) => {
    const o = ownerOf(pid);
    return o === undefined ? "" : o === myRid() ? "on my team" : o === null ? "free agent" : `owned by ${DATA.lab.rosters[String(o)].team_name}`;
  };
  function playerText(pid) {
    const c = CARDS[pid], L = DATA.lab, r = L && L.players[pid];
    const pos = r ? r.p : "", ab = POS_ABBR[pos] || pos;
    const lines = [`### ${pnm(pid)} (${pos}${r ? ", " + r.t : ""}) - ${ownerText(pid)}${r && r.s ? `, status: ${r.s}` : ""}${isHeld(pid) ? ", I'm holding (stashing) him" : ""}`];
    if (!c) return lines.concat(["No player card available."]).join("\n");
    const v = c.value, k = c.consistency || {}, o = c.opportunity || {}, u = c.usage || {};
    if (v) lines.push(`Projection: ${one(v.rate)} pts/wk (typical range ${one(Math.max(v.rate - v.sd, 0))}-${one(v.rate + v.sd)}), ${Math.round(v.ros)} pts rest of season, ${ab}${v.rank} of ${v.rank_of}, ${v.vor >= 0 ? "+" : ""}${Math.round(v.vor)} vs a free-agent replacement, ${v.confidence} confidence${v.flag ? `, flagged ${v.flag}` : ""}. Byes: ${v.byes.join(", ") || "none left"}.`);
    const pts = (g) => (g.pts != null ? one(g.pts) : g.calc != null ? "~" + one(g.calc) : "n/a");
    lines.push("Recent weeks: " + c.log.slice(-6).map((g) => g.bye ? `W${g.week} bye` : `W${g.week} ${g.opp ? "vs " + g.opp + " " : ""}${pts(g)} pts${g.finish ? ` (${ab}${g.finish})` : ""}${g.partial ? " partial game" : ""}`).join("; "));
    if (k.games) lines.push(`Consistency: ${k.ppg}/g, best ${k.ceiling}, median ${k.median}, worst ${k.floor}; boom ${k.boom}, starter-level ${k.start} of ${k.games}, bust ${k.bust} (starter-level = top ${c.tiers.start} ${ab}).`);
    const opp = [];
    if (u.snap_pct != null) opp.push(`${u.snap_pct}% snaps`);
    if (o.tgt_share != null) opp.push(`${Math.round(100 * o.tgt_share)}% target share`);
    if (o.car_share) opp.push(`${Math.round(100 * o.car_share)}% carry share`);
    if (o.wopr != null) opp.push(`WOPR ${o.wopr.toFixed(2)}`);
    if (o.touches_pg) opp.push(`${o.touches_pg} touches/g`);
    if (o.yds_per_touch != null) opp.push(`${o.yds_per_touch} yds/touch`);
    if (o.exp_tds != null) opp.push(`${o.tds} TDs vs ~${o.exp_tds} expected from volume`);
    if (u.actual_ppg != null && u.expected_ppg != null) opp.push(`scoring ${one(u.actual_ppg)}/g vs ${one(u.expected_ppg)}/g usage-based`);
    if (opp.length) lines.push("Usage: " + opp.join(", ") + ".");
    if (c.role) lines.push(`Role: ${c.role.pos}${c.role.order || ""} for ${c.role.team}${c.role.ahead && c.role.ahead.length ? " behind " + c.role.ahead.join(", ") : ""} - ${c.role.label} (${c.role.reason}) Weekly share: ${(c.role.weeks || []).map((w) => `W${w.week} ${w.share == null ? "-" : Math.round(100 * w.share) + "%"}${w.partial ? " (left early)" : w.opportunity ? " (opportunity: player ahead left/sat)" : ""}`).join(", ")}.`);
    if (v && v.status) lines.push(`Injury: ${v.status}${v.practice ? ", " + (PRACTICE[v.practice] || v.practice) : ""}.`);
    const nx = (c.next3 || []).find((w) => !w.bye);
    if (nx && nx.wx && wxText(nx.wx)) lines.push(`Next game conditions: ${wxText(nx.wx)}.`);
    if (c.schedule && c.schedule.length) lines.push("Schedule ahead (projected): " + c.schedule.map((w) => w.bye ? `W${w.week} bye` : `W${w.week}${w.playoff ? " (playoffs)" : ""} ${w.home === false ? "@" : "vs "}${w.opp} ${one(w.pts)}${w.matchup && w.matchup !== "neutral" ? " " + w.matchup : ""}`).join("; "));
    const wv = F && (F.available || []).find((x) => x.id === pid);
    if (wv) {
      const r2 = wv.rivals || {};
      lines.push(`Waiver view: adds ${wv.gain_per_week >= 0 ? "+" : ""}${wv.gain_per_week} pts/wk to my lineup (${wv.gain} rest of season, fit: ${wv.fit})${wv.drop.length ? `, I'd cut ${wv.drop.map((d) => d.name).join(", ")}` : ""}. Suggested bid $${wv.suggestion.bid} (${wv.suggestion.reason}) Likely rival bidders: ${(r2.likely || []).map((x) => x.label).join(", ") || "none"}. My FAAB left: $${F.my_remaining}.`);
    }
    return lines.join("\n");
  }
  function rosterText() {
    const me = D.me;
    const row = (p, slot) => p.id ? `- ${slot}: ${p.name} (${p.position}, ${p.team})${p.injury_status ? " " + p.injury_status : ""}${CARDS[p.id] ? ` - last 3 avg ${one(CARDS[p.id].last3_avg)}, next 3 proj ${one(CARDS[p.id].next3_avg)}` : ""}${isHeld(p.id) ? " [held]" : ""}` : `- ${slot}: empty`;
    return ["## My roster", ...me.starters.map((p) => row(p, p.slot)), ...me.bench.map((p) => row(p, "BN")), ...me.ir.map((p) => row(p, "IR"))].join("\n");
  }
  function tradeText() {
    const E = engine(), L = DATA.lab;
    if (!labState || !labState.give.length || !labState.get.length) return "";
    const res = E.evaluateTrade(labState.partner, labState.give, labState.get);
    const team = L.rosters[String(res.them)].team_name;
    const pct = (x) => Math.round(100 * x) + "%";
    const lines = [`## Trade I'm considering with ${team}`,
      `I give: ${res.give.map(pnm).join(", ")}. I get: ${res.get.map(pnm).join(", ")}.`,
      `Dashboard verdict: ${res.balance}. Rest-of-season value change: me ${signed(res.gainMe)} pts (${signed(res.perWeekMe)}/wk), them ${signed(res.gainThem)} pts. Confidence: ${res.confidence}.`,
      `Playoff odds: me ${pct(res.odds.me[0])} -> ${pct(res.odds.me[1])}, them ${pct(res.odds.them[0])} -> ${pct(res.odds.them[1])}.`,
      "Reasons: " + (res.reasons.join(" ") || "none listed"),
      `Lineup week ${res.lineupChange.week}: I start ${res.lineupChange.me.in.map(pnm).join(", ") || "no change"}; they start ${res.lineupChange.them.in.map(pnm).join(", ") || "no change"}.`,
      "Week by week (my change / their change): " + res.weekly.map((w) => `W${w.week} ${signed(w.me)}/${signed(w.them)}`).join(", "),
      (res.moves.me.drop.length ? `I'd have to cut ${res.moves.me.drop.map(pnm).join(", ")}. ` : "") + (res.moves.them.drop.length ? `They'd cut ${res.moves.them.drop.map(pnm).join(", ")}.` : ""),
      "", "## Players in the deal", ...res.give.concat(res.get).map(playerText)];
    return lines.join("\n");
  }
  function waiversText() {
    const best = (F && F.available || []).filter((p) => p.fit !== "none").slice(0, 10);
    const top = best.length ? best : (F && F.available || []).slice(0, 8);
    return [`## Waiver options (my FAAB left: $${F ? F.my_remaining : "?"}, waiver #${F && F.tendencies ? F.tendencies.my_waiver_position : "?"})`,
      ...top.map((p) => `- ${p.name} (${p.position}, ${p.team}${p.injury_status ? ", " + p.injury_status : ""}): adds ${p.gain_per_week >= 0 ? "+" : ""}${p.gain_per_week}/wk to me (fit ${p.fit})${p.drop.length ? `, cut ${p.drop.map((d) => d.name).join(", ")}` : ""}; proj ${one(p.proj_rate)}/wk; suggested bid $${p.suggestion.bid}; likely rivals ${(p.rivals && p.rivals.likely || []).length}`)].join("\n");
  }
  const ASK = {
    player: { about: (pid) => `About ${pnm(pid)}`, chips: (pid) => ownerOf(pid) === myRid()
        ? ["Start, hold, trade or drop him?", "Is he a sell-high?", "How worried should I be about his schedule?"]
        : ownerOf(pid) === null ? ["Should I pick him up, and what should I bid?", "Who on my roster would he replace?"]
        : ["Should I try to trade for him? What would it cost?", "Is he a buy-low?"],
      body: (pid) => playerText(pid) },
    trade: { about: () => "About the trade in the Lab", chips: () => ["Should I make this trade?", "What would you change to make it better for me?", "Would they accept it?"],
      body: () => tradeText() },
    waivers: { about: () => "About waivers and FAAB", chips: () => ["Who should I bid on this week, and how much?", "Should I save my FAAB?"],
      body: () => waiversText() },
    general: { about: () => "About my team and league", chips: () => ["What should I do this week?", "Who should I start?", "What's my biggest weakness?"],
      body: () => "" },
  };
  let askState = null;
  function askMessage() {
    const q = $("ask-q").value.trim() || ASK[askState.kind].chips(askState.pid)[0];
    const parts = [`My question: ${q}`, "",
      "Context: I play in a Sleeper fantasy football league. Use the data below from my dashboard (league scoring; projections are the dashboard's own model; '~' = calculated from NFL stats because the player wasn't on a league roster). Be specific and say if something you'd need isn't here.", ""];
    const body = ASK[askState.kind].body(askState.pid);
    if (body) parts.push(body, "");
    if (askState.kind !== "general") parts.push(rosterText(), "");
    else parts.push(rosterText(), "");
    if (B && B.markdown) parts.push("## League brief", B.markdown);
    return parts.join("\n");
  }
  function refreshAskPreview() {
    const text = askMessage();
    $("ask-preview").textContent = text;
    $("ask-size").textContent = `What gets sent (${Math.round(text.length / 100) / 10} KB of your league data)`;
  }
  function openAsk(kind, pid) {
    if (!kind) {
      const visible = [...document.querySelectorAll(".tab-panel")].find((s) => !s.hidden);
      const id = visible ? visible.id.replace("tab-", "") : "";
      kind = id === "lab" && labState && labState.give.length && labState.get.length ? "trade" : id === "faab" ? "waivers" : "general";
    }
    askState = { kind, pid };
    const A = ASK[kind];
    $("ask-about").textContent = A.about(pid);
    $("ask-q").value = "";
    $("ask-q").placeholder = A.chips(pid)[0];
    $("ask-chips").innerHTML = A.chips(pid).map((c) => `<button type="button" class="mini" data-chip="${esc(c)}">${esc(c)}</button>`).join("");
    $("ask-status").textContent = "";
    $("ask-share").hidden = !navigator.share;
    refreshAskPreview();
    const dlg = $("ask");
    if (dlg.showModal) dlg.showModal(); else dlg.setAttribute("open", "");
  }
  function setupAsk() {
    $("ask-btn").addEventListener("click", () => openAsk());
    $("ask-q").addEventListener("input", refreshAskPreview);
    $("ask-chips").addEventListener("click", (e) => {
      const c = e.target.closest("[data-chip]");
      if (c) { $("ask-q").value = c.dataset.chip; refreshAskPreview(); }
    });
    $("ask-share").addEventListener("click", async () => {
      try { await navigator.share({ text: askMessage() }); $("ask-status").textContent = "Sent. Pick Claude in the share menu if you haven't."; }
      catch (e) { if (e && e.name !== "AbortError") $("ask-status").textContent = "Sharing didn't work here. Use Copy instead."; }
    });
    $("ask-copy").addEventListener("click", async () => {
      try {
        await navigator.clipboard.writeText(askMessage());
        $("ask-status").innerHTML = `Copied ✓ Paste it into a new chat in the Claude app${navigator.share ? "" : ` or <a href="https://claude.ai/new" target="_blank" rel="noopener">claude.ai</a>`}.`;
      } catch (e) {
        const pre = $("ask-preview");
        pre.closest("details").open = true;
        const range = document.createRange(); range.selectNodeContents(pre);
        const sel = getSelection(); sel.removeAllRanges(); sel.addRange(range);
        $("ask-status").textContent = "Text selected. Press ⌘C / long-press to copy.";
      }
    });
  }

  // ---------- shell ----------
  // Five sections in the bottom bar; some hold sub-tabs switched by a segmented control.
  const SECTIONS = {
    home: [["home", "Home"]],
    league: [["league", "League"]],
    waivers: [["faab", "Bids & FAAB"], ["news", "News"]],
    trades: [["trades", "Ideas"], ["lab", "Trade Lab"]],
    more: [["planner", "Planner"], ["model", "Model"], ["brief", "Brief"], ["more", "Settings"]],
  };
  const lastSub = {};
  function sectionOf(name) {
    if (SECTIONS[name]) return name;
    return Object.keys(SECTIONS).find((sec) => SECTIONS[sec].some(([t]) => t === name)) || "home";
  }
  // `exact` = a sub-tab was picked directly (some sub-tabs share their section's name,
  // e.g. "trades" = Ideas, so the name alone would jump back to the last sub-tab).
  function selectTab(name, exact) {
    const sec = sectionOf(name);
    const sub = SECTIONS[name] && !exact ? (lastSub[sec] || SECTIONS[sec][0][0]) : name;
    lastSub[sec] = sub;
    document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === sec)));
    document.querySelectorAll(".tab-panel").forEach((s) => { s.hidden = s.id !== "tab-" + sub; });
    const subs = SECTIONS[sec];
    $("subnav").innerHTML = subs.length > 1 ? `<div class="seg" role="tablist">${subs.map(([t, label]) =>
      `<button type="button" data-sub="${t}" aria-pressed="${t === sub}">${label}</button>`).join("")}</div>` : "";
    $("subnav").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.sub, true)));
    if (location.hash.slice(1) !== sub) {
      try { history.replaceState(null, "", "#" + sub); } catch (e) { /* file:// may block */ }
    }
    window.scrollTo(0, 0);
  }

  // Explanations are tucked behind an ⓘ next to the heading they belong to.
  function tidyExplanations(root) {
    root.querySelectorAll("p.lead-text:not([data-tidy])").forEach((p) => {
      p.dataset.tidy = "1";
      const h = p.previousElementSibling;
      if (!h || h.tagName !== "H2") return;
      const btn = document.createElement("button");
      btn.type = "button"; btn.className = "info-btn"; btn.textContent = "i";
      btn.setAttribute("aria-label", "What is this?"); btn.setAttribute("aria-expanded", "false");
      h.appendChild(btn);
      p.classList.remove("lead-text"); p.classList.add("info-body"); p.hidden = true;
      btn.addEventListener("click", () => {
        p.hidden = !p.hidden;
        btn.setAttribute("aria-expanded", String(!p.hidden));
      });
    });
  }

  function renderMore() {
    const saved = (() => { try { return localStorage.getItem("theme"); } catch (e) { return null; } })() || "auto";
    $("tab-more").innerHTML = `<h2>Settings</h2><div class="card">
        <div class="set-row"><div>Appearance</div><div class="seg" id="theme-seg">${[["auto", "Auto"], ["light", "Light"], ["dark", "Dark"]]
          .map(([v, l]) => `<button type="button" data-theme="${v}" aria-pressed="${v === saved}">${l}</button>`).join("")}</div></div>
        <div class="set-row"><div>Data<div class="subtle">Updated ${D ? esc(new Date(D.generated_at).toLocaleString()) : "–"}</div></div>
          <button type="button" class="btn secondary" id="more-reload">Reload</button></div>
        <div class="set-row"><div>Sources<div class="subtle">Sleeper API (league data, points) · nflverse (stats, snaps, schedule, Vegas lines)</div></div></div>
      </div>
      <p class="subtle">Suggestions throughout are heuristics, not advice.</p>`;
    $("theme-seg").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => {
      const v = b.dataset.theme;
      if (v === "auto") delete document.documentElement.dataset.theme; else document.documentElement.dataset.theme = v;
      try { if (v === "auto") localStorage.removeItem("theme"); else localStorage.setItem("theme", v); } catch (e) { /* ignore */ }
      $("theme-seg").querySelectorAll("button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
    }));
    $("more-reload").addEventListener("click", () => location.reload());
  }

  function setupTheme() {
    let saved = null;
    try { saved = localStorage.getItem("theme"); } catch (e) { /* ignore */ }
    if (saved === "light" || saved === "dark") document.documentElement.dataset.theme = saved;
  }

  // ---------- installable app ----------
  function setupApp() {
    // Offline support needs a real web address (https or localhost), not a file opened from disk.
    if ("serviceWorker" in navigator && location.protocol !== "file:") {
      navigator.serviceWorker.register("sw.js").catch(() => { /* optional */ });
    }
    let deferred = null;
    window.addEventListener("beforeinstallprompt", (e) => {   // Android / desktop Chrome
      e.preventDefault();
      deferred = e;
      $("install-btn").hidden = false;
    });
    $("install-btn").addEventListener("click", async () => {
      if (!deferred) return;
      deferred.prompt();
      await deferred.userChoice;
      deferred = null;
      $("install-btn").hidden = true;
    });
    window.addEventListener("appinstalled", () => { $("install-btn").hidden = true; });
    $("refresh-btn").addEventListener("click", () => location.reload());
  }

  async function isOffline() {
    if (!navigator.onLine) return true;
    if (location.protocol === "file:") return false;
    try {
      await fetch(`data/dashboard.json?ping=${Date.now()}`, { method: "HEAD", cache: "no-store" });
      return false;
    } catch (e) {
      return true;
    }
  }

  // "Updated 3h ago" in the header; amber when stale (over a day on an NFL game day, else 4 days)
  function agoText(ms) {
    const m = Math.round(ms / 60000);
    if (m < 1) return "just now";
    if (m < 60) return `${m} min ago`;
    const h = Math.round(m / 60);
    if (h < 24) return `${h}h ago`;
    const d = Math.floor(h / 24);
    return d === 1 ? "yesterday" : `${d} days ago`;
  }
  function showUpdated() {
    const el = $("updated-at");
    if (!el || !D || !D.generated_at) return;
    const at = new Date(D.generated_at), age = Date.now() - at.getTime();
    let gameDay = false;
    try { gameDay = ["Thu", "Sun", "Mon"].includes(new Intl.DateTimeFormat("en-US", { weekday: "short", timeZone: "America/New_York" }).format(new Date())); } catch (e) { /* old browser */ }
    const stale = age > (gameDay ? 1 : 4) * 86400000;
    el.textContent = `Updated ${agoText(age)}`;
    el.className = stale ? "stale" : "";
    el.title = at.toLocaleString();
  }

  async function showStatus(generatedAt) {
    const notes = [];
    if (await isOffline()) {
      notes.push(`<div class="status-note offline">You're offline. Showing the last update you loaded.</div>`);
    }
    const days = generatedAt ? (Date.now() - new Date(generatedAt).getTime()) / 86400000 : 0;
    if (days >= 4) {
      notes.push(`<div class="status-note">This data is ${Math.floor(days)} days old. Run an update for fresh numbers.</div>`);
    }
    $("status").innerHTML = notes.join("");
  }

  document.addEventListener("click", (e) => {
    const b = e.target.closest("[data-act]");
    if (!b) return;
    e.preventDefault(); e.stopPropagation();
    const pid = b.dataset.pid, act = b.dataset.act;
    if (act === "trade-for") openInLab(ownerOf(pid), [], [pid], { suggest: true });
    else if (act === "shop") openInLab((labState && labState.partner) || Object.keys(DATA.lab.rosters).find((t) => Number(t) !== myRid()), [pid], [], { suggest: true, shopAll: true });
    else if (act === "pitch") openInLab(b.dataset.partner, [pid], [], { suggest: true });
    else if (act === "plan-add") planPickup(pid);
    else if (act === "hold") toggleHold(pid);
    else if (act === "ask") openAsk(b.dataset.kind, pid);
    else if (act === "team") openTeam(b.dataset.team);
    else if (act === "improve") runImprove();
    else if (act === "apply-edit") {
      const e = IMPROVE.edits.concat(IMPROVE.closest || [])[Number(b.dataset.i)];
      labState = Object.assign({}, labState, { give: e.give.slice(), get: e.get.slice() });
      store.set("labState", labState);
      renderTradeLab();
      setTimeout(() => { const r = $("lab-result"); if (r) r.scrollIntoView({ block: "start", behavior: "smooth" }); }, 60);
    }
    else if (act === "jump-offers") $("lab-offers").scrollIntoView({ block: "start", behavior: "smooth" });
  }, true);

  setupTheme();
  setupAsk();
  setupApp();
  window.addEventListener("online", () => showStatus(D && D.generated_at));
  window.addEventListener("offline", () => showStatus(D && D.generated_at));
  if (!D) {
    $("subtitle").textContent = "No data yet. Run: uv run python -m nfl_assistant.run";
    return;
  }
  $("team-name").textContent = D.me.team_name;
  $("subtitle").innerHTML = `${esc(D.league.name)} · Week ${esc(D.league.current_week)} · <span id="updated-at"></span>`;
  showUpdated();
  setInterval(showUpdated, 60000);
  const warnings = [].concat(D.warnings || [], (F && F.warnings) || []);
  if (warnings.length) {
    $("warnings").innerHTML = `<div class="alert"><strong>Warnings</strong><ul>${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
  }
  showStatus(D.generated_at);

  renderHome(); renderLeague(); renderNews(); renderFaab(); renderTrades(); renderTradeLab(); renderPlanner(); renderModel(); renderBrief(); renderMore();
  tidyExplanations(document);
  new MutationObserver(() => tidyExplanations(document.querySelector("main"))).observe(document.querySelector("main"), { childList: true, subtree: true });
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  // old bookmarks: My Team / Standings / Matchups / Playoffs / Rosters moved into Home and League
  const MOVED = { team: "home", matchups: "home", standings: "league", playoffs: "league", rosters: "league" };
  const initial = MOVED[location.hash.slice(1)] || location.hash.slice(1);
  const known = Object.values(SECTIONS).flat().map(([t]) => t).concat(Object.keys(SECTIONS));
  selectTab(known.includes(initial) ? initial : "home");
  window.addEventListener("hashchange", () => {
    const h = MOVED[location.hash.slice(1)] || location.hash.slice(1);
    if (known.includes(h)) selectTab(h, true);
  });
})();
