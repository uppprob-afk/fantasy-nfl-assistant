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
  const one = (n) => (n == null ? "–" : Number(n).toFixed(1));
  const POS_ABBR = { QB: "QB", RB: "RB", WR: "WR", TE: "TE", K: "K", DEF: "DEF" };

  function strip(c) {
    const past = c.last3.map((w) => ({ v: w.pts, label: `W${w.week}`, kind: "past", w }));
    const next = c.next3.map((w) => ({ v: w.bye ? null : w.pts, label: w.bye ? "BYE" : `${w.home ? "" : "@"}${w.opp || ""}`,
      kind: "next", w }));
    const vals = past.concat(next).map((x) => x.v || 0);
    const scale = Math.max(25, ...vals);
    const cell = (x) => {
      let cls = `wbar ${x.kind}`, txt = x.v == null ? "–" : Math.round(x.v), h = x.v ? Math.max(6, Math.round(100 * x.v / scale)) : 0;
      if (x.kind === "past") {
        if (x.w.bye) { txt = "bye"; cls += " none"; }
        else if (!x.w.played && !x.v) { txt = "–"; cls += " none"; }
        else if (x.v == null) { txt = "n/r"; cls += " none"; }
        if (x.w.partial) { cls += " partial"; txt += "*"; }
      } else {
        if (x.w.bye) { txt = ""; cls += " none"; }
        if (x.w.matchup && x.w.matchup !== "neutral") cls += ` ${x.w.matchup}`;
      }
      return `<div class="cell"><div class="val">${esc(txt)}</div><div class="track"><span class="${cls}" style="height:${h}%"></span></div>
        <div class="lbl">${esc(x.label)}</div></div>`;
    };
    return `<div class="strip">${past.map(cell).join("")}<div class="divider"></div>${next.map(cell).join("")}</div>`;
  }

  function detailPanel(p, c) {
    const v = c.value, u = c.usage;
    let html = `<div class="pd">`;
    // next 3 matchups
    if (c.next3.length) {
      html += `<div class="pd-sec"><div class="pd-h">Next 3 weeks</div>${c.next3.map((w) => w.bye
        ? `<div class="pd-row"><span>Wk ${w.week}</span><span class="muted">Bye</span><span></span></div>`
        : `<div class="pd-row"><span>Wk ${w.week} ${w.home ? "vs" : "@"} ${esc(w.opp)}</span>
            <span><b>${one(w.pts)}</b> <span class="subtle">(${one(w.low)}–${one(w.high)})</span></span>
            <span>${w.matchup !== "neutral" ? `<span class="chip mu-${w.matchup}">${w.matchup}</span>` : ""}${
              w.avail < 1 ? ` <span class="chip q">${Math.round(100 * w.avail)}% to play</span>` : ""}</span></div>`).join("")}
        <div class="subtle">Range = typical game-to-game spread. Matchup from ${c.next3.some((w) => w.source === "vegas") ? "Vegas lines (next game) and " : ""}opponent strength.</div></div>`;
    }
    // weekly log
    const isQB = p.position === "QB";
    html += `<div class="pd-sec"><div class="pd-h">Game log <span class="subtle">· season ${one(c.season.pts)} pts in ${c.season.games} gp</span></div>
      <div class="table-wrap"><table class="log"><thead><tr><th>Wk</th><th>Pts</th><th>Snap</th>${isQB ? "<th>Att</th>" : "<th>Tgt</th><th>Rec</th>"}<th>Car</th></tr></thead><tbody>${
      c.log.map((g) => `<tr${g.partial ? ' class="partial"' : ""}><td>${g.week}</td>
        <td>${g.bye ? "bye" : g.pts == null ? "n/r" : one(g.pts)}${g.partial ? "*" : ""}</td>
        <td>${g.pct != null ? Math.round(100 * g.pct) + "%" : "–"}</td>
        ${isQB ? `<td>${g.attempts ?? "–"}</td>` : `<td>${g.targets ?? "–"}</td><td>${g.receptions ?? "–"}</td>`}
        <td>${g.carries ?? "–"}</td></tr>`).join("")}</tbody></table></div>
      <div class="subtle">* partial game (snap share well below normal, e.g. hurt early). n/r = not on a league roster that week.</div></div>`;
    // usage
    if (u && u.games) {
      const bits = [];
      if (u.snap_pct != null) bits.push(`<b>${u.snap_pct}%</b> snaps`);
      if (isQB) bits.push(`<b>${u.attempts}</b> att/g`);
      else if (p.position !== "K" && p.position !== "DEF") bits.push(`<b>${u.targets}</b> tgt/g`, `<b>${u.receptions}</b> rec/g`);
      if (u.carries) bits.push(`<b>${u.carries}</b> car/g`);
      const luck = u.actual_ppg != null && u.expected_ppg != null
        ? `<div>Scoring <b>${one(u.actual_ppg)}</b>/g vs <b>${one(u.expected_ppg)}</b>/g that usage usually produces${
            u.actual_ppg - u.expected_ppg > 3 ? " (running hot)" : u.expected_ppg - u.actual_ppg > 3 ? " (running cold)" : ""}.</div>` : "";
      html += `<div class="pd-sec"><div class="pd-h">Usage <span class="subtle">· last ${u.games} ${u.partial_only ? "(partial) " : "full "}game${u.games > 1 ? "s" : ""}</span></div>
        <div>${bits.join(" · ")}</div>${luck}</div>`;
    }
    // value
    if (v) {
      html += `<div class="pd-sec"><div class="pd-h">Value ${confChip(v.confidence)}${v.flag ? ` <span class="chip ${v.flag === "sell-high" ? "hot" : "ok-style"}">${esc(v.flag)}</span>` : ""}</div>
        <div><b>${one(v.rate)}</b>/wk projected (typically ${one(Math.max(v.rate - v.sd, 0))}–${one(v.rate + v.sd)})
          · <b>${Math.round(v.ros)}</b> pts rest of season</div>
        <div>${POS_ABBR[p.position] || p.position}${v.rank} of ${v.rank_of} by rest-of-season projection ·
          ${v.vor >= 0 ? "+" : ""}${Math.round(v.vor)} vs a free-agent replacement</div>
        <div class="subtle">${v.byes.length ? `Bye: week ${v.byes.join(", ")}. ` : ""}${v.prior_ppg != null ? `Last season ${one(v.prior_ppg)}/g. ` : ""}See Trades → How values work.</div></div>`;
    }
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
    const arrow = { up: `<span class="trend up">▲</span>`, down: `<span class="trend down">▼</span>`, flat: "" }[c.trend] || "";
    return `<details class="prow-d"><summary class="prow prow-card">
      <span class="slot ${esc(cls)}">${esc(label)}</span>
      <div class="pmain">
        <div class="pname">${esc(p.name)}${injuryChip(p)}${irNote}${checkChip(p)}</div>
        <div class="pmeta">${esc(p.team)}${rank}${v ? ` · ${esc(v.confidence)} conf` : ""}${v && v.flag ? ` · <span class="flag">${esc(v.flag)}</span>` : ""}</div>
        ${reason}
      </div>
      <div class="pnums l3n3">
        <div><div class="k">Last 3</div><div class="big">${one(c.last3_avg)}</div></div>
        <div><div class="k">Next 3</div><div class="big">${arrow}${one(c.next3_avg)}</div></div>
      </div>
      ${strip(c)}
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
  function renderTeam() {
    const me = D.me;
    const st = D.standings.find((s) => s.roster_id === me.roster_id) || {};
    let html = `<div class="stats">
      <div class="stat"><div class="v">${st.wins}–${st.losses}${st.ties ? "–" + st.ties : ""}</div><div class="l">Record · #${st.rank}</div></div>
      <div class="stat"><div class="v">${num(st.points_for)}</div><div class="l">Points for</div></div>
      <div class="stat"><div class="v">$${st.faab_remaining}</div><div class="l">FAAB left</div></div>
    </div>`;
    if (me.notes && me.notes.length) {
      html += `<div class="alert"><strong>Heads up</strong><ul>${me.notes.map((n) => `<li>${esc(n)}</li>`).join("")}</ul></div>`;
    }
    html += rosterCards(me);
    html += `<p class="muted" style="font-size:.8rem">Last 3 = average of the last three weeks the player played (league scoring, from Sleeper).
      Next 3 = projected average over the next three games; bars show each week (solid = actual, outlined = projected,
      green/red outline = easy/tough matchup). Tap a player for details. Season points weeks ${
      esc(D.league.completed_weeks.join(", "))}). ✓ = matches nflverse stats within 1 pt.
      IR allowed for: ${esc(D.league.ir_allowed.join(", "))}.</p>`;
    $("tab-team").innerHTML = html;
  }

  function renderStandings() {
    const rows = D.standings.map((s) => `<tr class="${s.roster_id === D.me.roster_id ? "mine" : ""}">
      <td>${s.rank}</td>
      <td class="team-cell"><div class="t">${esc(s.team_name)}</div><div class="m">${managerName(s)}</div></td>
      <td>${s.wins}–${s.losses}${s.ties ? "–" + s.ties : ""}</td>
      <td>${num(s.points_for)}</td>
      <td class="hide-sm">${num(s.points_against)}</td>
      <td>${s.waiver_position ?? "–"}</td>
    </tr>`).join("");
    $("tab-standings").innerHTML = `<h2>Standings</h2>
      <div class="card table-wrap"><table>
        <thead><tr><th>#</th><th>Team</th><th>W–L</th><th>PF</th><th class="hide-sm">PA</th><th title="Waiver priority (FAAB tiebreak)">Waiver</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p class="muted" style="font-size:.8rem">Waiver = Sleeper's current waiver priority, used to break tied FAAB bids (1 wins ties).</p>`;
  }

  function renderMatchupsBasic() {
    const m = D.matchups;
    const cards = m.pairs.map((p) => {
      const [a, b] = p.teams;
      const side = (t, other, right) => `<div class="side ${other && t.points > other.points ? "lead" : ""}">
          <div class="score">${num(t.points, 2)}</div>
          <div class="pname">${esc(t.team_name)}</div><div class="pmeta">${managerName(t)}</div></div>`;
      return `<div class="card ${p.is_mine ? "mine" : ""}">
        ${p.is_mine ? `<div class="mine-label">Your matchup</div>` : ""}
        <div class="mu">${side(a, b)}<div class="vs">vs</div>${b ? side(b, a, true) : "<div>Bye</div>"}</div>
      </div>`;
    }).join("");
    $("tab-matchups").innerHTML = `<h2>Week ${m.week} matchups</h2>${cards || `<div class="empty">No matchups yet.</div>`}
      <p class="muted" style="font-size:.8rem">Live scores as of the last data update.</p>`;
  }

  function renderRosters() {
    const opts = D.rosters.map((r) =>
      `<option value="${r.roster_id}" ${r.is_mine ? "selected" : ""}>${esc(r.team_name)}: ${esc(r.label)}</option>`).join("");
    $("tab-rosters").innerHTML = `<select id="roster-pick" aria-label="Choose a manager">${opts}</select><div id="roster-body"></div>`;
    const show = () => {
      const id = Number($("roster-pick").value);
      const r = D.rosters.find((x) => x.roster_id === id);
      $("roster-body").innerHTML = `<div class="muted" style="margin-bottom:-8px">${managerName(r)}</div>` + rosterCards(r);
    };
    $("roster-pick").addEventListener("change", show);
    show();
  }

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
      ? `<span class="chip ${s.demand === "hot" ? "hot" : "warm"}">${s.demand === "hot" ? "🔥 " : ""}${Number(p.count).toLocaleString()} adds</span>` : "";
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
      <div class="subtle" style="margin-top:4px">${esc(s.reason || "")}</div>${owner}${comps}
      ${rivalsBlock(p)}
    </div>`;
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

    // bid ideas
    const ideas = (F.targets || []).map(bidCard).join("");
    html += `<h2>Bid ideas</h2>
      <p class="lead-text">Suggestions, not advice. Each is the lowest bid likely to win given how much demand to expect.
      <b>Bargain</b> = what past claims actually took · <b>Competitive</b> = beats half of rivals' bids · <b>Safe</b> = beats 75%.</p>`;
    if (ideas) html += `<h2 style="margin-top:8px;font-size:.95rem">My targets</h2><div class="card">${ideas}</div>`;
    html += `<h2 style="margin-top:8px;font-size:.95rem">Trending free agents <span class="muted" style="font-weight:400">(Sleeper-wide adds, last 48h)</span></h2>
      <div class="card">${F.trending_adds.length ? F.trending_adds.map(bidCard).join("") : `<div class="empty">No trending free agents.</div>`}</div>`;
    if (!ideas) html += `<p class="subtle">Tip: add players you're eyeing under <code>targets:</code> in config.yaml to get a bid for them here.</p>`;

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
      <div><span class="pname">${esc(n.name)}</span>${injuryChip(n)} <span class="pmeta">${esc(n.position)} · ${esc(n.team)}${who}${stats}</span></div>
      <div class="txt">${esc(n.text)}</div>${action}${bid}${n.rivals && F && F.tendencies ? rivalsBlock(n) : ""}
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
    if (count) document.querySelector('#tabs button[data-tab="news"]').insertAdjacentHTML("beforeend", `<span class="badge">${count}</span>`);
  }

  // ---------- Trades ----------
  const T = DATA.trades;
  const signed = (n) => (n > 0 ? "+" : "") + num(n);

  function confChip(level) {
    return level ? `<span class="chip conf ${esc(level)}" title="How much data backs this number">${esc(level)}</span>` : "";
  }

  function projMeta(p) {
    const range = p.sd != null ? ` (${num(Math.max(p.rate - p.sd, 0), 0)}–${num(p.rate + p.sd, 0)} typical)` : "";
    return `${esc(p.position)} · ${esc(p.team)} · <b>${num(p.rate)}</b>/wk proj${range}`;
  }

  function tradePlayers(list) {
    return list.map((p) => `<div class="pl">${esc(p.name)}${injuryChip(p)}</div>
      <div class="pmeta">${projMeta(p)}</div>
      <div class="pmeta">ROS ${num(p.ros, 0)} pts · ${p.vor >= 0 ? "+" : ""}${num(p.vor, 0)} vs replacement ${confChip(p.confidence)}</div>`).join("");
  }

  function tradeCard(t) {
    const cls = t.balance.startsWith("balanced") ? "balanced" : t.balance.startsWith("favours") ? "favours" : "lopsided";
    const n = T.weeks.length || 1;
    return `<div class="trade">
      <div class="trade-head">
        <div><span class="pname">${esc(t.team_name)}</span> <span class="pmeta">${esc(t.manager)}</span></div>
        <span><span class="chip ${cls}">${esc(t.balance)}</span> ${confChip(t.confidence)}</span>
      </div>
      <div class="swap">
        <div><div class="col-label">You give</div>${tradePlayers(t.give)}</div>
        <div class="arrow">⇄</div>
        <div><div class="col-label">You get</div>${tradePlayers(t.get)}</div>
      </div>
      <div class="gains"><span class="gain me">You ${signed(t.my_gain)} pts ROS (~${num(t.my_gain / n)}/wk)</span>
        <span class="gain">Them ${signed(t.their_gain)} pts</span></div>
      <details><summary>Why this trade?</summary><ul>${t.reasons.map((r) => `<li>${esc(r)}</li>`).join("")}</ul></details>
    </div>`;
  }

  function buySellRow(r, verb) {
    return `<div class="trade">
      <div class="trade-head"><div><span class="pname">${esc(r.name)}</span> <span class="pmeta">${esc(r.position)} · ${esc(r.team)} · ${esc(r.manager)}</span></div>${confChip(r.confidence)}</div>
      <div class="subtle" style="margin-top:4px">Scoring <b>${num(r.actual_ppg)}</b>/g in ${r.games_this} full game(s); projection <b>${num(r.rate)}</b>/wk.
        Usage alone suggests ${r.expected_ppg != null ? num(r.expected_ppg) : "–"}/g${r.prior_ppg != null ? `, last season ${num(r.prior_ppg)}/g` : ""}.
        ${verb}</div></div>`;
  }

  function valuesTable(rows) {
    return `<div class="card table-wrap"><table class="named">
      <thead><tr><th>Player</th><th>Proj/wk</th><th>ROS</th><th title="Rest-of-season points above a free-agent replacement">vs repl.</th><th class="hide-sm">Conf.</th></tr></thead>
      <tbody>${rows.map((v) => `<tr class="${v.roster_id === T.my_roster_id ? "mine" : ""}">
        <td class="team-cell"><div class="t">${esc(v.name)}${injuryChip(v)}</div>
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
    html += `<div class="disclaimer">These are <b>suggestions, not advice</b>. Values are <b>rest-of-season projections</b>
      (weeks ${esc(T.weeks[0])}–${esc(T.weeks[n - 1])}), not points so far. Each shows a confidence level, so check it before acting.</div>`;

    html += `<h2>Trade ideas</h2><p class="lead-text">Each idea improves <b>both</b> teams' projected optimal lineups for every remaining week
      (byes included), plus a little credit for bench depth. Ranked by benefit to you; lopsided ones last.</p>`;
    html += `<div class="card">${T.ideas.length ? T.ideas.map(tradeCard).join("") : `<div class="empty">No mutually beneficial trades found right now.</div>`}</div>`;

    html += `<h2>Sell high</h2><p class="lead-text">Your players scoring well above what their usage and track record support.</p>
      <div class="card">${T.sell_high.length ? T.sell_high.map((r) => buySellRow(r, "Worth shopping while the numbers look great.")).join("")
        : `<div class="empty">None of your players are clearly overperforming.</div>`}</div>`;
    html += `<h2>Buy low</h2><p class="lead-text">Other teams' players scoring well below their projection. Their managers may undervalue them.</p>
      <div class="card">${T.buy_low.length ? T.buy_low.map((r) => buySellRow(r, "Could be cheaper now than they're worth.")).join("")
        : `<div class="empty">No clear buy-low targets.</div>`}</div>`;

    html += `<h2>Motivated buyers</h2>`;
    if (T.buyers.length) {
      html += `<div class="card">${T.buyers.map((b) => `<div class="trade">
        <div><span class="pname">${esc(b.manager)}</span> <span class="pmeta">just lost ${esc(b.position)} ${esc(b.player)} (${esc(b.status)})</span></div>
        <div class="subtle" style="margin-top:4px">${b.my_options.length
          ? `Players you could pitch: ${b.my_options.map((p) => `<b>${esc(p.name)}</b> (${num(p.rate)}/wk proj)`).join(", ")}`
          : `You have no bench ${esc(b.position)} to offer.`}</div></div>`).join("")}</div>`;
    } else {
      html += `<div class="card"><div class="empty">No team has lost a starter to injury since recent runs. Check back after the next scan.</div></div>`;
    }

    const mine = T.values.filter((v) => v.roster_id === T.my_roster_id);
    html += `<h2>Player values: my team</h2>${valuesTable(mine)}`;
    html += `<details class="recent"><summary>Player values: top 25 in the league</summary>${valuesTable(T.values.slice(0, 25))}</details>`;
    html += `<p class="subtle">Replacement level (avg of the best 3 free agents, pts/wk): ${
      Object.entries(T.replacement).map(([k, v]) => `${esc(k)} ${num(v)}`).join(" · ")}.</p>`;

    const cols = ["QB", "RB", "WR", "TE", "FLEX"];
    const rows = T.teams.map((t) => `<tr class="${t.is_mine ? "mine" : ""}">
      <td class="team-cell"><div class="t">${esc(t.team_name)}</div><div class="m">${managerName(t)}</div>
        <div class="m">${t.needs.length ? `needs <b>${esc(t.needs.join("/"))}</b>` : "no clear needs"}${t.surplus.length ? ` · spare ${esc(t.surplus.join("/"))}` : ""}</div></td>
      ${cols.map((c) => {
        const v = t.vs_median[c];
        return `<td class="${v > 1 ? "up" : v < -1 ? "down" : ""}${c === "FLEX" ? " hide-sm" : ""}">${signed(v)}</td>`;
      }).join("")}
      <td class="hide-sm"><b>${num(t.per_week)}</b></td></tr>`).join("");
    html += `<h2>Projected strength vs league median</h2>
      <p class="lead-text">Average projected points per week from each position in the optimal weekly lineups (green = strength, red = need).</p>
      <div class="card table-wrap"><table class="named">
        <thead><tr><th>Team</th>${cols.map((c) => `<th${c === "FLEX" ? ' class="hide-sm"' : ""}>${c}</th>`).join("")}<th class="hide-sm">Proj/wk</th></tr></thead>
        <tbody>${rows}</tbody></table></div>
      <p class="subtle">Median: ${cols.map((c) => `${c} ${num(T.median[c])}`).join(" · ")} pts/wk.
        Lineup slots: ${esc(T.slots.join(", "))}. "Spare" = a bench player who'd start for the median team.</p>`;

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

  function lineupRows(t) {
    return t.players.map((r) => {
      if (!r.id) return "";
      const p = nm(r.id);
      const tag = r.status === "played" ? `<span class="subtle">final</span>` : `<span class="subtle">proj ±${num(r.sd, 0)}</span>`;
      return `<div class="prow"><span class="slot ${esc(p.position)}">${esc(p.position)}</span>
        <div><div class="pname">${esc(p.name)}${injuryChip(p)}</div><div class="pmeta">${esc(p.team)}</div></div>
        <div class="pnums"><div class="big">${num(r.pts)}</div><div class="small">${tag}</div></div></div>`;
    }).join("");
  }

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

  function renderMatchups() {
    if (!O) return renderMatchupsBasic();
    let html = `<h2>Week ${esc(O.week)} matchups</h2>`;
    html += O.matchups.map((m) => {
      const [a, b] = m.teams;
      const side = (t, right) => `<div class="side" ${right ? 'style="text-align:right"' : ""}>
        <div class="score">${num(t.mean)}</div>
        <div class="subtle">likely ${range(t.mean, t.sd)}${t.played_pts ? ` · ${num(t.played_pts)} banked` : ""}</div>
        <div class="pname">${esc(t.team_name)}</div><div class="pmeta">${managerName(t)}</div></div>`;
      const details = m.is_mine ? `<details class="mu-detail"><summary>Player-by-player</summary>
          <div class="col-label" style="padding:8px 14px 0">${esc(a.team_name)}</div>${lineupRows(a)}
          <div class="col-label" style="padding:8px 14px 0">${esc(b.team_name)}</div>${lineupRows(b)}</details>` : "";
      return `<div class="card ${m.is_mine ? "mine" : ""}">
        ${m.is_mine ? `<div class="mine-label">Your matchup ${confChip(m.confidence)}</div>` : ""}
        <div class="mu">${side(a)}<div class="vs">vs</div>${side(b, true)}</div>
        <div style="padding:0 14px 12px">${winBar(a, b, m.confidence)}</div>${details}</div>`;
    }).join("");

    html += `<h2>Start / sit</h2><p class="lead-text">Your set lineup vs the best bench option at each slot. Players whose games have started are locked.</p>
      <div class="card">${O.start_sit.length ? O.start_sit.map(startSitRow).join("") : `<div class="empty">Nothing to decide: all your games have started.</div>`}</div>`;

    // optimal lineups by week
    const teamOpts = Object.entries(O.managers).map(([rid, m]) =>
      `<option value="${rid}" ${Number(rid) === O.my_roster_id ? "selected" : ""}>${esc(m.team_name)}: ${esc(m.label)}</option>`).join("");
    html += `<h2>Optimal lineups by week</h2><p class="lead-text">Best projected lineup for every remaining regular-season week, byes and injuries included.</p>
      <select id="lu-team" aria-label="Team">${teamOpts}</select>
      <div class="weekchips" id="lu-weeks">${O.weeks.map((w, i) => `<button type="button" data-w="${w}" aria-pressed="${i === 0}">Wk ${w}</button>`).join("")}</div>
      <div id="lu-body"></div>
      <div class="card table-wrap" style="margin-top:12px" id="lu-season"></div>`;

    html += `<details class="recent"><summary>How these numbers work</summary><div class="card card-pad subtle">
      <p><b>Projected score</b> = points already scored this week (final) + each remaining starter's projection (see Trades → How values work).
      "Likely" is ±1 standard deviation, the range a team lands in about two weeks in three.</p>
      <p><b>Win chance</b> compares the two projected scores using both teams' week-to-week spread, including the chance a Questionable player sits.
      Percentages are rounded to the nearest 5% until projections reach high confidence.</p>
      <p><b>Start/sit</b> shows how often the best eligible bench player would outscore your starter this week. Above 60%: consider swapping.
      40–60%: genuine coin flip.</p></div></details>`;
    $("tab-matchups").innerHTML = html;

    let week = O.weeks[0];
    const drawLineup = () => {
      const rid = $("lu-team").value;
      const lw = O.lineups[rid][String(week)];
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
      const totals = O.weeks.map((w) => O.lineups[rid][String(w)].total);
      const max = Math.max(...totals);
      $("lu-season").innerHTML = `<table class="named"><thead><tr><th>Week</th><th>Proj</th><th>Byes</th></tr></thead><tbody>${
        O.weeks.map((w) => {
          const lw2 = O.lineups[rid][String(w)];
          return `<tr><td>Wk ${w}</td><td>${num(lw2.total)} <span class="bar" style="display:inline-block;width:60px;vertical-align:middle"><span style="width:${Math.round(100 * lw2.total / max)}%"></span></span></td>
            <td>${lw2.byes.length ? lw2.byes.map((p) => esc(nm(p).name)).join(", ") : "–"}</td></tr>`;
        }).join("")}</tbody></table>`;
    };
    $("lu-team").addEventListener("change", drawLineup);
    document.querySelectorAll("#lu-weeks button").forEach((b) => b.addEventListener("click", () => {
      week = Number(b.dataset.w);
      document.querySelectorAll("#lu-weeks button").forEach((x) => x.setAttribute("aria-pressed", String(x === b)));
      drawLineup();
    }));
    drawLineup();
  }

  function renderPlayoffs() {
    if (!O) { $("tab-playoffs").innerHTML = `<div class="empty">No projections yet.</div>`; return; }
    const P = O.playoffs, conf = P.confidence;
    const me = P.teams.find((t) => t.is_mine);
    let html = `<div class="stats">
      <div class="stat"><div class="v">${esc(me.odds_text)}</div><div class="l">Playoff odds</div></div>
      <div class="stat"><div class="v">${esc(me.if_win_text || "–")}</div><div class="l">If I win wk ${esc(O.week)}</div></div>
      <div class="stat"><div class="v">${esc(me.if_lose_text || "–")}</div><div class="l">If I lose wk ${esc(O.week)}</div></div>
    </div>
    <p class="lead-text">Top ${esc(O.playoff_teams)} make the playoffs. Projected final record about ${num(me.proj_wins)} wins. ${confChip(conf)}</p>`;

    const keyRow = (k) => {
      const mine = k.mine;
      const meIsA = k.a === O.my_roster_id;
      const opp = mine ? (meIsA ? k.b_team : k.a_team) : null;
      const ifWin = mine ? (meIsA ? k.if_a_text : k.if_b_text) : null;
      const ifLose = mine ? (meIsA ? k.if_b_text : k.if_a_text) : null;
      return mine
        ? `<div class="trade"><div class="pname">Week ${esc(k.week)} vs ${esc(opp)}</div>
            <div class="subtle">Win → <b>${esc(ifWin)}</b> · Lose → <b>${esc(ifLose)}</b></div></div>`
        : `<div class="trade"><div class="pname">Week ${esc(k.week)}: ${esc(k.a_team)} vs ${esc(k.b_team)}</div>
            <div class="subtle">If ${esc(k.a_team)} wins → you're <b>${esc(k.if_a_text)}</b> · if ${esc(k.b_team)} wins → <b>${esc(k.if_b_text)}</b></div></div>`;
    };
    const mineK = P.key_games.filter((k) => k.mine), otherK = P.key_games.filter((k) => !k.mine);
    html += `<h2>Games that matter most to you</h2><div class="card">${mineK.map(keyRow).join("") || `<div class="empty">No games left.</div>`}</div>`;
    html += `<h2>Other games to watch</h2><p class="lead-text">Results between other teams that move your odds the most.</p>
      <div class="card">${otherK.map(keyRow).join("") || `<div class="empty">No other game moves your odds much.</div>`}</div>`;

    html += `<h2>Whole league</h2><div class="card table-wrap"><table class="named">
      <thead><tr><th>Team</th><th>W–L</th><th title="Projected final wins">Proj W</th><th>Playoffs</th><th class="hide-sm">Win / lose wk ${esc(O.week)}</th></tr></thead>
      <tbody>${P.teams.map((t) => `<tr class="${t.is_mine ? "mine" : ""}">
        <td class="team-cell"><div class="t">${esc(t.team_name)}</div><div class="m">${managerName(t)}</div></td>
        <td>${t.wins}–${t.losses}${t.ties ? "–" + t.ties : ""}</td><td>${num(t.proj_wins)}</td>
        <td><b>${esc(t.odds_text)}</b></td>
        <td class="hide-sm">${esc(t.if_win_text || "–")} / ${esc(t.if_lose_text || "–")}</td></tr>`).join("")}</tbody></table></div>`;

    html += `<details class="recent"><summary>How playoff odds work</summary><div class="card card-pad subtle">
      <p>The rest of the regular season (weeks ${esc(O.weeks[0])}–${esc(O.reg_season_end)}) is simulated ${Number(P.sims).toLocaleString()} times
      using the real schedule. Each simulated week, every team scores its projected optimal lineup (this week: its actual set
      lineup plus points already banked) plus random week-to-week variation.</p>
      <p>Each simulation also shifts every team's overall level a little, because projections themselves can be wrong. That
      keeps the odds from being overconfident, especially early. Ranking: wins, then points for (Sleeper's default tiebreak).</p>
      <p>With ${esc(P.completed_weeks)} week(s) played, confidence is <b>${esc(conf)}</b>, so odds are rounded to the nearest
      ${conf === "high" ? "1%" : "5%"}. They'll sharpen as the season goes on. Same data gives the same numbers (fixed random seed per day).</p>
    </div></details>`;
    $("tab-playoffs").innerHTML = html;
  }

  // ---------- Brief ----------
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

  // ---------- shell ----------
  function selectTab(name) {
    document.querySelectorAll("#tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
    document.querySelectorAll(".tab-panel").forEach((s) => { s.hidden = s.id !== "tab-" + name; });
    try { history.replaceState(null, "", "#" + name); } catch (e) { /* file:// may block */ }
  }

  function setupTheme() {
    const root = document.documentElement;
    let saved = null;
    try { saved = localStorage.getItem("theme"); } catch (e) { /* ignore */ }
    if (saved) root.dataset.theme = saved;
    $("theme-btn").addEventListener("click", () => {
      const dark = root.dataset.theme
        ? root.dataset.theme === "dark"
        : matchMedia("(prefers-color-scheme: dark)").matches;
      root.dataset.theme = dark ? "light" : "dark";
      try { localStorage.setItem("theme", root.dataset.theme); } catch (e) { /* ignore */ }
    });
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

  setupTheme();
  setupApp();
  window.addEventListener("online", () => showStatus(D && D.generated_at));
  window.addEventListener("offline", () => showStatus(D && D.generated_at));
  if (!D) {
    $("subtitle").textContent = "No data yet. Run: uv run python -m nfl_assistant.run";
    return;
  }
  $("team-name").textContent = D.me.team_name;
  $("subtitle").textContent = `${D.league.name} · Week ${D.league.current_week} · ${D.me.label}`;
  const warnings = [].concat(D.warnings || [], (F && F.warnings) || []);
  if (warnings.length) {
    $("warnings").innerHTML = `<div class="alert"><strong>Warnings</strong><ul>${warnings.map((w) => `<li>${esc(w)}</li>`).join("")}</ul></div>`;
  }
  showStatus(D.generated_at);
  $("footer").textContent = `Updated ${new Date(D.generated_at).toLocaleString()} · Data: Sleeper API, nflverse`;
  renderTeam(); renderNews(); renderStandings(); renderMatchups(); renderFaab(); renderTrades(); renderPlayoffs(); renderRosters(); renderBrief();
  document.querySelectorAll("#tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
  const initial = location.hash.slice(1);
  selectTab(document.querySelector(`#tabs button[data-tab="${initial}"]`) ? initial : "team");
})();
