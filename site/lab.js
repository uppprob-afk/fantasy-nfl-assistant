/* Trade Lab + Planner engine. Pure calculations, no DOM, so results can be checked.

   Mirrors the Python pipeline (lineups.py, trades.py, outlook.py): optimal lineup per week
   (dedicated slots first, then flex), team value = sum of weekly optimal lineups + a small
   credit for the best bench players, needs/surplus vs the league median, and a seeded
   Monte Carlo of the rest of the season. Data comes from window.NFL_DATA.lab. */
(function () {
  "use strict";
  const FLEX = { FLEX: ["RB", "WR", "TE"], WRRB_FLEX: ["RB", "WR"], REC_FLEX: ["WR", "TE"],
    SUPER_FLEX: ["QB", "RB", "WR", "TE"] };

  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6D2B79F5) >>> 0;
      let t = a;
      t = Math.imul(t ^ (t >>> 15), t | 1);
      t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  function create(L) {
    const P = L.players;
    const slotOrder = L.slots.map((s, i) => [s, i])
      .sort((a, b) => ((a[0] in FLEX) - (b[0] in FLEX)) || a[1] - b[1]).map((x) => x[0]);
    const nW = L.weeks.length;
    const skill = new Set(L.skill);
    const ltOut = new Set(L.long_term_out);
    const wi = (week) => L.weeks.indexOf(week);
    const round = (x, d) => Math.round(x * 10 ** d) / 10 ** d;

    function lineup(pids, w) {
      const pool = pids.filter((p) => P[p]).map((p, i) => [p, P[p].w[w], i])
        .sort((a, b) => (b[1] - a[1]) || (a[2] - b[2])).map((x) => x[0]);
      const used = new Set();
      const out = [];
      for (const slot of slotOrder) {
        const ok = FLEX[slot] || [slot];
        const pick = pool.find((p) => !used.has(p) && ok.includes(P[p].p));
        if (pick) { used.add(pick); out.push([slot, pick]); }
      }
      const total = round(out.reduce((s, [, p]) => s + P[p].w[w], 0), 2);
      const variance = out.reduce((s, [, p]) => s + P[p].v[w], 0);
      return { total, sd: Math.sqrt(variance), lineup: out };
    }

    function value(pids) {
      const weekly = L.weeks.map((_, w) => lineup(pids, w));
      const lineupTotal = weekly.reduce((s, x) => s + x.total, 0);
      const starts = {};
      weekly.forEach((x) => x.lineup.forEach(([, p]) => { starts[p] = (starts[p] || 0) + 1; }));
      const bench = pids.filter((p) => P[p] && skill.has(P[p].p) && (starts[p] || 0) < nW / 2)
        .map((p) => P[p].ros).sort((a, b) => b - a);
      const depth = L.depth_weight * bench.slice(0, L.depth_count).reduce((s, x) => s + x, 0);
      return { score: round(lineupTotal + depth, 1), lineupTotal: round(lineupTotal, 1), weekly, starts };
    }

    function profile(pids) {
      const v = value(pids);
      const strength = { QB: 0, RB: 0, WR: 0, TE: 0, FLEX: 0 };
      v.weekly.forEach((wk, w) => wk.lineup.forEach(([slot, p]) => {
        const key = slot in strength ? slot : (slot in FLEX ? "FLEX" : null);
        if (key) strength[key] += P[p].w[w] / nW;
      }));
      const now = new Set(v.weekly[0] ? v.weekly[0].lineup.map(([, p]) => p) : []);
      const depth = {};
      for (const pos of L.skill) {
        const b = pids.filter((p) => P[p] && P[p].p === pos && !now.has(p)).map((p) => P[p].ros / nW)
          .sort((a, c) => c - a);
        depth[pos] = b.length ? b[0] : 0;
      }
      return { value: v, strength, depth };
    }

    function strengthSd(pids) {
      const lu = lineup(pids, nW - 1).lineup;
      return Math.sqrt(lu.reduce((s, [, p]) => s + (P[p].se || 0) ** 2, 0));
    }

    function rosterOf(rid) { return L.rosters[String(rid)].players.slice(); }

    /* Monte Carlo of the remaining season. rosters: {rid: [pids]} overrides; weekOverrides:
       {"rid|week": {mean, sd}} replaces a team's distribution for one week. */
    function simulate(rosters, opts) {
      const o = Object.assign({ n: 4000, seed: 20261003, weekOverrides: {} }, opts || {});
      const teams = Object.keys(L.rosters);
      const dist = {};
      const sdBias = {};
      for (const t of teams) {
        const pids = rosters[t] || rosterOf(t);
        sdBias[t] = strengthSd(pids);
        L.weeks.forEach((week, w) => {
          const key = `${t}|${week}`;
          if (o.weekOverrides[key]) { dist[key] = o.weekOverrides[key]; return; }
          if (week === L.current_week && L.this_week[t]) {
            dist[key] = { mean: L.this_week[t].mean, sd: L.this_week[t].sd };
          } else {
            const lu = lineup(pids, w);
            dist[key] = { mean: lu.total, sd: lu.sd };
          }
        });
      }
      const games = [];
      Object.keys(L.schedule).map(Number).sort((a, b) => a - b)
        .forEach((week) => L.schedule[String(week)].forEach(([a, b]) => games.push([week, String(a), String(b)])));
      const rand = mulberry32(o.seed);
      let spare = null;
      const gauss = () => {
        if (spare !== null) { const s = spare; spare = null; return s; }
        let u = 0, v = 0;
        while (u === 0) u = rand();
        v = rand();
        const r = Math.sqrt(-2 * Math.log(u));
        spare = r * Math.sin(2 * Math.PI * v);
        return r * Math.cos(2 * Math.PI * v);
      };
      const made = {}, wins = {}, seed1 = {};
      teams.forEach((t) => { made[t] = 0; wins[t] = 0; seed1[t] = 0; });
      for (let i = 0; i < o.n; i++) {
        const bias = {}, w = {}, pf = {};
        for (const t of teams) {
          bias[t] = gauss() * sdBias[t];
          const st = L.standings[t];
          w[t] = st.wins + 0.5 * (st.ties || 0);
          pf[t] = st.pf;
        }
        for (const [week, a, b] of games) {
          const da = dist[`${a}|${week}`], db = dist[`${b}|${week}`];
          const sa = da.mean + bias[a] + gauss() * da.sd;
          const sb = db.mean + bias[b] + gauss() * db.sd;
          pf[a] += sa; pf[b] += sb;
          w[sa > sb ? a : b] += 1;
        }
        const ranked = teams.slice().sort((x, y) => (w[y] - w[x]) || (pf[y] - pf[x]));
        ranked.slice(0, L.playoff_teams).forEach((t) => { made[t] += 1; });
        seed1[ranked[0]] += 1;
        teams.forEach((t) => { wins[t] += w[t]; });
      }
      const out = {};
      teams.forEach((t) => { out[t] = { odds: made[t] / o.n, wins: wins[t] / o.n, seed1: seed1[t] / o.n }; });
      return out;
    }

    function tradeableRec(r) {
      return skill.has(r.p) && !ltOut.has(r.s) && (r.gt > 0 || r.gp >= 4);
    }

    function leagueProfiles(overrides) {
      const out = {};
      for (const t of Object.keys(L.rosters)) out[t] = profile((overrides && overrides[t]) || rosterOf(t));
      const keys = ["QB", "RB", "WR", "TE", "FLEX"];
      const median = {};
      for (const k of keys) {
        const vals = Object.values(out).map((p) => p.strength[k]).sort((a, b) => a - b);
        const m = vals.length;
        median[k] = m % 2 ? vals[(m - 1) / 2] : (vals[m / 2 - 1] + vals[m / 2]) / 2;
      }
      for (const p of Object.values(out)) {
        p.vsMedian = {};
        for (const k of keys) p.vsMedian[k] = p.strength[k] - median[k];
        p.needs = L.skill.filter((k) => p.vsMedian[k] < -1 && L.slots.includes(k))
          .sort((a, b) => p.vsMedian[a] - p.vsMedian[b]);
        p.surplus = L.skill.filter((k) => {
          const per = median[k] / (L.slots.filter((s) => s === k).length || 1);
          return per > 0 && p.depth[k] >= per;
        });
      }
      return { profiles: out, median };
    }

    /* Full breakdown of a trade between me and `partner`. */
    function evaluateTrade(partner, give, get, opts) {
      const me = String(L.my_roster_id), them = String(partner);
      const mine0 = rosterOf(me), theirs0 = rosterOf(them);
      const mine1 = mine0.filter((p) => !give.includes(p)).concat(get);
      const theirs1 = theirs0.filter((p) => !get.includes(p)).concat(give);
      const before = leagueProfiles();
      const after = leagueProfiles({ [me]: mine1, [them]: theirs1 });
      const gainMe = round(after.profiles[me].value.score - before.profiles[me].value.score, 1);
      const gainThem = round(after.profiles[them].value.score - before.profiles[them].value.score, 1);
      const weekly = L.weeks.map((week, w) => ({
        week,
        me: round(after.profiles[me].value.weekly[w].total - before.profiles[me].value.weekly[w].total, 1),
        them: round(after.profiles[them].value.weekly[w].total - before.profiles[them].value.weekly[w].total, 1),
        meAfter: after.profiles[me].value.weekly[w].total,
        themAfter: after.profiles[them].value.weekly[w].total,
      }));
      const nextIdx = Math.min(L.weeks.indexOf(L.current_week + 1) >= 0 ? L.weeks.indexOf(L.current_week + 1) : 0, nW - 1);
      const startersAt = (prof) => new Set(prof.value.weekly[nextIdx].lineup.map(([, p]) => p));
      const changes = (b, a) => ({ in: [...a].filter((p) => !b.has(p)), out: [...b].filter((p) => !a.has(p)) });
      const lineupChange = {
        week: L.weeks[nextIdx],
        me: changes(startersAt(before.profiles[me]), startersAt(after.profiles[me])),
        them: changes(startersAt(before.profiles[them]), startersAt(after.profiles[them])),
      };
      const sims = (opts && opts.sims) || 4000;
      const odds0 = simulate({}, { n: sims });
      const odds1 = simulate({ [me]: mine1, [them]: theirs1 }, { n: sims });
      const ratio = gainMe ? gainThem / gainMe : 1;
      const lopsided = gainThem < 0.25 * gainMe;
      let balance;
      if (gainMe <= 0 && gainThem <= 0) balance = "bad for both";
      else if (gainMe <= 0) balance = "favours them";
      else if (gainThem <= 0) balance = "they'd likely decline";
      else balance = ratio >= 0.6 ? "balanced" : lopsided ? "lopsided (tough sell)" : "favours you";
      const conf = ["low", "medium", "high"];
      const confidence = give.concat(get).map((p) => P[p].c).sort((a, b) => conf.indexOf(a) - conf.indexOf(b))[0] || "low";
      const sizeAfter = (pids, rid) => pids.filter((p) => !(L.rosters[rid].reserve || []).includes(p)).length;
      const reasons = [];
      const pb = before.profiles[me], tb = before.profiles[them];
      const posOf = (list) => [...new Set(list.map((p) => P[p].p))];
      posOf(get).forEach((pos) => { if (pb.needs.includes(pos)) reasons.push(`Fills your ${pos} need (${(-pb.vsMedian[pos]).toFixed(1)} pts/wk below median).`); });
      posOf(give).forEach((pos) => {
        if (tb.needs.includes(pos)) reasons.push(`Fills their ${pos} need (${(-tb.vsMedian[pos]).toFixed(1)} pts/wk below median).`);
        if (pb.surplus.includes(pos)) reasons.push(`You have ${pos} depth to spare.`);
      });
      posOf(get).forEach((pos) => { if (tb.surplus.includes(pos)) reasons.push(`They have ${pos} depth to spare.`); });
      const flagged = give.concat(get).filter((p) => !tradeableRec(P[p]));
      return {
        me, them, give, get, gainMe, gainThem, perWeekMe: round(gainMe / nW, 1), balance, confidence,
        weekly, lineupChange, reasons, flagged,
        before, after,
        odds: { me: [odds0[me].odds, odds1[me].odds], them: [odds0[them].odds, odds1[them].odds],
                meWins: [odds0[me].wins, odds1[me].wins], themWins: [odds0[them].wins, odds1[them].wins] },
        rosterSize: { me: sizeAfter(mine1, me), them: sizeAfter(theirs1, them), max: L.roster_size },
      };
    }

    function vor(pid) {
      const r = P[pid];
      return round(r.ros - (L.replacement[r.p] || 0) * nW, 1);
    }

    /* Check the browser maths against the pipeline's own team values. */
    function selfCheck() {
      const diffs = Object.keys(L.check_scores).map((t) => Math.abs(value(rosterOf(t)).score - L.check_scores[t]));
      return { ok: diffs.every((d) => d < 0.5), maxDiff: Math.max(...diffs) };
    }

    return { lineup, value, profile, simulate, evaluateTrade, leagueProfiles, rosterOf, tradeable: tradeableRec,
      vor, selfCheck, weekIndex: wi, players: P };
  }

  window.NFLLab = { create, mulberry32 };
})();
