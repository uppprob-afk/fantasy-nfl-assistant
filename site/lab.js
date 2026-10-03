/* Trade Lab + Planner engine. Pure calculations, no DOM, so results can be checked.

   Mirrors the Python pipeline (lineups.py, trades.py, outlook.py): optimal lineup per week
   (dedicated slots first, then flex), team value = sum of weekly optimal lineups with every
   slot worth at least free-agent replacement level, minus the expected cost of unexpected
   absences (after the best bench / replacement cover), with rosters cut to the league size,
   needs/surplus vs the league median, and a seeded
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

    const absence = L.absence_rate;
    const reserveAll = new Set(L.reserve_all || []);
    let holds = new Set();   // players the user is stashing: never auto-cut, never offered
    const floor = L.floor || {};
    const byPid = (x, y) => (x < y ? -1 : x > y ? 1 : 0);

    /* Expected points in week w: every slot worth at least the free-agent replacement
       level, minus the expected cost of unexpected absences after the best cover. */
    function weekValue(pids, w, lu) {
      const starters = new Set(lu.map(([, p]) => p));
      const bench = pids.filter((p) => P[p] && !starters.has(p));
      const remaining = lu.slice();
      let total = 0;
      for (const slot of L.slots) {
        const i = remaining.findIndex(([s]) => s === slot);
        const fl = floor[slot] || 0;
        if (i < 0) { total += fl; continue; }
        const pid = remaining.splice(i, 1)[0][1];
        const pts = P[pid].w[w];
        if (pts <= fl) { total += fl; continue; }
        const ok = FLEX[slot] || [slot];
        const cover = Math.max(fl, ...bench.filter((b) => ok.includes(P[b].p)).map((b) => P[b].w[w]));
        total += pts - absence * (pts - cover);
      }
      return total;
    }

    function rawValue(pids) {
      const weekly = L.weeks.map((_, w) => lineup(pids, w));
      const expected = weekly.map((x, w) => weekValue(pids, w, x.lineup));
      return { score: expected.reduce((s, x) => s + x, 0), lineupTotal: weekly.reduce((s, x) => s + x.total, 0),
        weekly, expected };
    }

    /* Team value after cutting down to the league's roster size if needed. */
    function value(pids) {
      pids = pids.slice();
      const dropped = [];
      const active = (ps) => ps.filter((p) => !reserveAll.has(p));
      if (L.roster_size) {
        while (active(pids).length > L.roster_size) {
          let cands = active(pids).filter((p) => (!P[p] || skill.has(P[p].p)) && !holds.has(p))
            .sort((x, y) => ((P[x] ? P[x].ros : 0) - (P[y] ? P[y].ros : 0)) || byPid(x, y)).slice(0, L.drop_candidates);
          if (!cands.length) cands = active(pids).slice(-1);
          let best = null, bestScore = -Infinity;
          for (const c of cands) {
            const sc = rawValue(pids.filter((p) => p !== c)).score;
            if (sc > bestScore || (sc === bestScore && byPid(c, best) > 0)) { best = c; bestScore = sc; }
          }
          pids = pids.filter((p) => p !== best);
          dropped.push(best);
        }
      }
      const v = rawValue(pids);
      return { score: round(v.score, 1), lineupTotal: round(v.lineupTotal, 1), weekly: v.weekly,
        expected: v.expected, pids, dropped };
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
      pids = v.pids;
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
    function rosterAll(rid) { const r = L.rosters[String(rid)]; return (r.all || r.players).slice(); }

    /* Monte Carlo of the remaining season. rosters: {rid: [pids]} overrides; weekOverrides:
       {"rid|week": {mean, sd}} replaces a team's distribution for one week.
       mode "lineup" (default, matches the Playoffs tab) uses each roster's best lineup as is;
       mode "value" uses the same expected weekly points as the trade value (free-agent floor,
       injury cover, roster limit), so trade odds agree with trade gains. */
    function simulate(rosters, opts) {
      const o = Object.assign({ n: 4000, seed: 20261003, weekOverrides: {}, mode: "lineup" }, opts || {});
      const teams = Object.keys(L.rosters);
      const dist = {};
      const sdBias = {};
      for (const t of teams) {
        const pids = rosters[t] || (o.mode === "value" ? rosterAll(t) : rosterOf(t));
        sdBias[t] = strengthSd(pids);
        const val = o.mode === "value" ? value(pids) : null;
        L.weeks.forEach((week, w) => {
          const key = `${t}|${week}`;
          if (o.weekOverrides[key]) { dist[key] = o.weekOverrides[key]; return; }
          if (week === L.current_week && L.this_week[t]) {
            dist[key] = { mean: L.this_week[t].mean, sd: L.this_week[t].sd };
          } else {
            const lu = lineup(val ? val.pids : pids, w);
            dist[key] = { mean: val ? val.expected[w] : lu.total, sd: lu.sd };
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

    function balanceOf(gainMe, gainThem) {
      if (gainMe <= 0 && gainThem <= 0) return "bad for both";
      if (gainMe <= 0) return "favours them";
      if (gainThem <= 0) return "they'd likely decline";
      if (gainThem / gainMe >= 0.6) return "balanced";
      return gainThem < 0.25 * gainMe ? "lopsided (tough sell)" : "favours you";
    }

    /* Find packages both teams would accept.
       Buy mode (get set, partner = their owner): what to give, 1 or 2 of my players.
       Shop mode (give set): what to ask for, 1 or 2 players, from one partner or every team.
       Ranked by my gain; held players are never offered. */
    /* Realistic offers around a fixed player: `get` (players I want from `partner`) or
       `give` (players I'm shopping, to `partner` or every team). Searches 1-for-1, 2-for-1,
       1-for-2 and 2-for-2 deals of similar total value (like-for-like), keeps only ones where
       I don't lose value and they gain, and ranks fair deals that fill a lineup gap first.
       If nothing helps both, returns near-misses (they'd lose under 3 pts) instead. */
    function suggestOffers(o) {
      const me = String(L.my_roster_id);
      const get = o.get || [], give = o.give || [];
      const nPool = o.poolSize || 8, limit = o.limit || 6;
      const byRos = (x, y) => P[y].ros - P[x].ros;
      const ros = (ids) => ids.reduce((t, p) => t + Math.max(P[p].ros, 0), 0);
      const pairs = (arr) => { const r = []; for (let i = 0; i < arr.length; i++) for (let j = i + 1; j < arr.length; j++) r.push([arr[i], arr[j]]); return r; };
      const mineAll = rosterAll(me);
      const myPool = rosterOf(me).filter((p) => tradeableRec(P[p]) && !holds.has(p) && !give.includes(p)).sort(byRos);
      const partners = o.partner ? [String(o.partner)] : Object.keys(L.rosters).filter((t) => t !== me);
      const profs = leagueProfiles().profiles;
      const myBase = value(mineAll).score;
      const winWin = [], close = [];
      let searched = 0;
      for (const t of partners) {
        const theirsAll = rosterAll(t);
        const theirPool = rosterOf(t).filter((p) => tradeableRec(P[p]) && !get.includes(p)).sort(byRos);
        const theirBase = value(theirsAll).score;
        const shapes = [];
        if (get.length && !give.length) {
          const mine = myPool.slice(0, nPool + 4), extra = theirPool.slice(0, nPool);
          mine.forEach((x) => shapes.push([[x], get]));
          pairs(myPool.slice(0, nPool)).forEach((pr) => shapes.push([pr, get]));
          if (get.length === 1) {
            mine.forEach((x) => extra.forEach((c) => shapes.push([[x], [get[0], c]])));
            pairs(myPool.slice(0, nPool)).forEach((pr) => extra.forEach((c) => shapes.push([pr, [get[0], c]])));
          }
        } else if (give.length && !get.length) {
          const theirs = theirPool.slice(0, nPool + 4), extra = myPool.slice(0, nPool);
          theirs.forEach((y) => shapes.push([give, [y]]));
          pairs(theirPool.slice(0, nPool)).forEach((pr) => shapes.push([give, pr]));
          if (give.length === 1) {
            extra.forEach((m) => theirs.forEach((y) => shapes.push([[give[0], m], [y]])));
            extra.forEach((m) => pairs(theirPool.slice(0, nPool)).forEach((pr) => shapes.push([[give[0], m], pr])));
          }
        } else if (give.length && get.length) {
          shapes.push([give, get]);
        }
        const needs = profs[t].needs, myNeeds = profs[me].needs;
        for (const [g, r] of shapes) {
          const rg = ros(g), rr = ros(r);
          if (!rg || !rr || rr / rg > 1.5 || rr / rg < 0.67) continue;     // like-for-like value only
          searched++;
          const gainMe = round(value(mineAll.filter((p) => !g.includes(p)).concat(r)).score - myBase, 1);
          if (gainMe < 0) continue;                                         // never a losing deal for me
          const gainThem = round(value(theirsAll.filter((p) => !r.includes(p)).concat(g)).score - theirBase, 1);
          if (gainThem <= -3) continue;
          const fits = [];
          [...new Set(g.map((p) => P[p].p))].forEach((pos) => { if (needs.includes(pos)) fits.push(`fills their ${pos} gap`); });
          [...new Set(r.map((p) => P[p].p))].forEach((pos) => { if (myNeeds.includes(pos)) fits.push(`fills your ${pos} gap`); });
          const x = { partner: t, give: g, get: r, gainMe, gainThem, balance: balanceOf(gainMe, gainThem), fits,
            score: Math.min(gainMe, gainThem) * (1 + 0.5 * fits.length) + 0.1 * (gainMe + gainThem) };
          (gainThem > 0 ? winWin : close).push(x);
        }
      }
      const lop = (x) => x.gainThem < 0.25 * x.gainMe;
      winWin.sort((a, b) => lop(a) - lop(b) || b.score - a.score || b.gainMe - a.gainMe);
      close.sort((a, b) => b.gainThem - a.gainThem || b.gainMe - a.gainMe);
      const pool = winWin.length ? winWin : close;
      // Variety: at most two per team, and skip versions that only add a throw-in
      // (contain a kept offer with gains within 0.5 of it).
      const kept = [], perTeam = {};
      const sub = (a, b) => a.every((p) => b.includes(p));
      for (const x of pool) {
        if (kept.length >= (winWin.length ? limit : 3)) break;
        if ((perTeam[x.partner] || 0) >= (o.partner ? limit : 2)) continue;
        const dup = kept.some((k) => k.partner === x.partner && sub(k.give, x.give) && sub(k.get, x.get)
          && Math.abs(k.gainMe - x.gainMe) <= 0.5 && Math.abs(k.gainThem - x.gainThem) <= 0.5);
        if (dup) continue;
        kept.push(x);
        perTeam[x.partner] = (perTeam[x.partner] || 0) + 1;
      }
      return { offers: kept, anyAcceptable: winWin.length > 0, searched };
    }

    /* Adjustments to a trade I've built, keeping its core (the most valuable player on each
       side never moves). Tries every version within two changes (add, remove or swap a
       supporting player, sides of 1-3 players) and returns the best few that I don't lose on
       and they gain from: smallest fix, best for me, fairest. If none, the closest. */
    function improveTrade(partner, give, get, o) {
      o = o || {};
      const me = String(L.my_roster_id), t = String(partner);
      const mineAll = rosterAll(me), theirsAll = rosterAll(t);
      const myBase = value(mineAll).score, theirBase = value(theirsAll).score;
      const byRos = (x, y) => P[y].ros - P[x].ros;
      const coreG = give.slice().sort(byRos)[0], coreR = get.slice().sort(byRos)[0];
      const n = o.poolSize || 10;
      const extrasG = [...new Set(give.filter((p) => p !== coreG).concat(rosterOf(me).filter((p) => tradeableRec(P[p]) && !holds.has(p) && p !== coreG).sort(byRos).slice(0, n)))];
      const extrasR = [...new Set(get.filter((p) => p !== coreR).concat(rosterOf(t).filter((p) => tradeableRec(P[p]) && p !== coreR).sort(byRos).slice(0, n)))];
      const upTo2 = (arr) => { const r = [[]]; arr.forEach((x, i) => { r.push([x]); for (let j = i + 1; j < arr.length; j++) r.push([x, arr[j]]); }); return r; };
      const diff = (a, b) => a.filter((p) => !b.includes(p)).length + b.filter((p) => !a.includes(p)).length;
      const score = (g, r) => {
        const gainMe = round(value(mineAll.filter((p) => !g.includes(p)).concat(r)).score - myBase, 1);
        const gainThem = round(value(theirsAll.filter((p) => !r.includes(p)).concat(g)).score - theirBase, 1);
        return { gainMe, gainThem, balance: balanceOf(gainMe, gainThem) };
      };
      const cur = score(give, get);
      const sides = (core, extras, now) => upTo2(extras).map((x) => [core].concat(x)).map((g) => ({ ids: g, d: diff(g, now) })).filter((x) => x.d <= 2);
      const Gs = sides(coreG, extrasG, give), Rs = sides(coreR, extrasR, get);
      const all = [];
      for (const g of Gs) for (const r of Rs) {
        const changes = g.d + r.d;
        if (!changes || changes > 2) continue;
        all.push(Object.assign({ give: g.ids, get: r.ids, changes,
          added: g.ids.filter((p) => !give.includes(p)).map((p) => ["give", p]).concat(r.ids.filter((p) => !get.includes(p)).map((p) => ["get", p])),
          removed: give.filter((p) => !g.ids.includes(p)).map((p) => ["give", p]).concat(get.filter((p) => !r.ids.includes(p)).map((p) => ["get", p])) },
          score(g.ids, r.ids)));
      }
      const curOk = cur.gainMe >= 0 && cur.gainThem > 0;
      const fair = (e) => Math.min(e.gainMe, e.gainThem);
      // only versions that work for both and actually improve on what's there
      const ok = all.filter((e) => e.gainMe >= 0 && e.gainThem > 0
        && (!curOk || e.gainMe > cur.gainMe + 0.5 || fair(e) > fair(cur) + 0.5));
      const picks = [];
      const take = (e, tag) => { if (e && !picks.some((x) => x.give.join() === e.give.join() && x.get.join() === e.get.join())) picks.push(Object.assign({ tag }, e)); };
      if (ok.length) {
        const ones = ok.filter((e) => e.changes === 1);
        if (ones.length) take(ones.slice().sort((a, b) => fair(b) + 0.3 * b.gainMe - fair(a) - 0.3 * a.gainMe)[0], curOk ? "One change" : "Smallest fix");
        take(ok.slice().sort((a, b) => b.gainMe - a.gainMe || b.gainThem - a.gainThem)[0], curOk ? "More for you, still a yes for them" : "Best for you that works for both");
        take(ok.slice().sort((a, b) => fair(b) - fair(a) || a.changes - b.changes)[0], "Fairest");
      }
      const closest = ok.length || curOk ? null : all.filter((e) => e.gainMe >= 0).sort((a, b) => b.gainThem - a.gainThem || a.changes - b.changes)[0] || null;
      return { current: cur, acceptable: curOk, edits: picks, closest, core: [coreG, coreR], searched: all.length };
    }

    function tradeableRec(r) {
      return skill.has(r.p) && !ltOut.has(r.s) && (r.gt > 0 || r.gp >= 4);
    }

    function leagueProfiles(overrides) {
      const out = {};
      for (const t of Object.keys(L.rosters)) out[t] = profile((overrides && overrides[t]) || rosterAll(t));
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
      const mine0 = rosterAll(me), theirs0 = rosterAll(them);
      const mine1 = mine0.filter((p) => !give.includes(p)).concat(get);
      const theirs1 = theirs0.filter((p) => !get.includes(p)).concat(give);
      const before = leagueProfiles();
      const after = leagueProfiles({ [me]: mine1, [them]: theirs1 });
      const gainMe = round(after.profiles[me].value.score - before.profiles[me].value.score, 1);
      const gainThem = round(after.profiles[them].value.score - before.profiles[them].value.score, 1);
      const weekly = L.weeks.map((week, w) => ({
        week,
        me: round(after.profiles[me].value.expected[w] - before.profiles[me].value.expected[w], 1),
        them: round(after.profiles[them].value.expected[w] - before.profiles[them].value.expected[w], 1),
        meAfter: after.profiles[me].value.expected[w],
        themAfter: after.profiles[them].value.expected[w],
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
      const odds0 = simulate({}, { n: sims, mode: "value" });
      const odds1 = simulate({ [me]: mine1, [them]: theirs1 }, { n: sims, mode: "value" });
      const balance = balanceOf(gainMe, gainThem);
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
        moves: { me: { drop: after.profiles[me].value.dropped }, them: { drop: after.profiles[them].value.dropped } },
      };
    }

    function vor(pid) {
      const r = P[pid];
      return round(r.ros - (L.replacement[r.p] || 0) * nW, 1);
    }

    /* Check the browser maths against the pipeline's own team values. */
    function selfCheck() {
      const diffs = Object.keys(L.check_scores).map((t) => Math.abs(value(rosterAll(t)).score - L.check_scores[t]));
      return { ok: diffs.every((d) => d < 0.5), maxDiff: Math.max(...diffs) };
    }

    return { lineup, value, rawValue, profile, simulate, evaluateTrade, suggestOffers, improveTrade, leagueProfiles, rosterOf, rosterAll, tradeable: tradeableRec,
      setHolds: (ids) => { holds = new Set(ids || []); }, holds: () => holds,
      vor, selfCheck, weekIndex: wi, players: P };
  }

  window.NFLLab = { create, mulberry32 };
})();
