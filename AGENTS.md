# AGENTS.md: Fantasy NFL Assistant

Instructions for AI coding agents (Claude Code, Codex) working in this repo.
`CLAUDE.md` just points here; keep this file as the single source of truth and update it
as the project grows.

## Project overview

A generic fantasy football assistant for any **Sleeper** league. A Python pipeline fetches
league data, verifies points against a second source, builds projections, and writes
JSON for a static site in `site/`. Nothing about a specific league lives in the repo:
the league is configured in a git-ignored `config.yaml` or via environment variables
(GitHub Actions repository variables).

**Never commit league data or league-identifying details** (league IDs, usernames,
team names, nicknames, snapshots, generated `site/data/`, screenshots of a real league).
Use `python -m nfl_assistant.anonymize` to make shareable copies, and neutral names
(e.g. `rival_one`, "Team Alpha") in tests and docs.

## Tech choices

- Python 3.11+ managed by **uv**; **httpx**; **PyYAML**; **pytest**.
- Site: plain HTML + CSS + vanilla JS, **no framework, no build step**. Must work from
  `file://`, so the pipeline writes each data file twice: `site/data/<name>.json` and
  `site/data/<name>.js` (sets `window.NFL_DATA.<name>`), loaded with `<script>` tags.
- Mobile-first, automatic dark mode (`prefers-color-scheme`) plus a toggle.

## Commands

```bash
cp config.example.yaml config.yaml          # first time: fill in league_id + username
uv run python -m nfl_assistant.run          # run the whole pipeline
uv run pytest                               # offline tests (tests/fixtures/)
uv run python -m nfl_assistant.anonymize    # anonymised copy of the site in demo/
open site/index.html
```

`Update Dashboard.command` (macOS) does run + open on double-click, and works from a
symlinked shortcut (it resolves its own path with `readlink -f`).

## Configuration

`config.py` loads `config.yaml` if present, else `config.example.yaml`, then applies env
overrides: `LEAGUE_ID`, `SLEEPER_USERNAME`, `LEAGUE_TIMEZONE`, `NICKNAMES`
(`user=Nick,user2=Nick2`), `TARGETS` (`Player One;Player Two`). Missing league ID or
username raises `ConfigError` with a clear message. `expected_settings` is optional.

## Layout

```
config.example.yaml       template (config.yaml is git-ignored)
nfl_assistant/
  run.py                  entry point: fetch → build each tab → write
  config.py               config file + env overrides
  sleeper.py              polite Sleeper API client + players cache
  nflverse.py             nflverse download, PPR recompute, cross-check
  players.py              names, injury, IR eligibility, name lookup
  dashboard.py            standings, rosters, season points
  faab.py                 waiver log, clearing prices, market prices, bid ideas
  roles.py                opportunity games, team volume x share x efficiency, learned share inheritance
  scanner.py              diff vs previous snapshot (injuries, depth, teams, drops)
  projections.py          rest-of-season projection engine (rate, spread, confidence, weekly)
  lineups.py              optimal weekly lineups (byes/injuries handled)
  trades.py               trade values (ROS optimal lineups) + mutual-benefit trade ideas
  outlook.py              win chances, start/sit, weekly lineups, playoff simulation
  teams.py                NFL teams: depth charts, position strength vs league, offence, roles / job security
  tendencies.py           manager FAAB habits + likely rivals / bid-to-win
  cards.py                player cards: last/next 3, finishes, consistency, opportunity, game log, schedule, value
  lab.py                  compact data for the in-browser Trade Lab (site/lab.js)
  model.py                self-assessment: backtest, accuracy, learned settings, live ledger
  waivers.py              waiver targets: best available per position, points each adds to my team
  league.py               weekly scores vs median, all-play + luck, power rankings, odds history
  brief.py                Markdown brief for pasting into an AI assistant
  anonymize.py            shareable copy of the site with league names replaced
  output.py               site data + snapshot writers
site/                     static site (index.html, styles.css, app.js, data/ git-ignored)
data/                     git-ignored: snapshots/, news_log.json, odds_history.json, cache/
tests/                    pytest + tests/fixtures/ (neutral sample data)
.github/workflows/update.yml   tests always; pipeline + Pages only if LEAGUE_ID var set
```

## Data rules (must follow)

- Public Sleeper API only (`https://api.sleeper.app/v1/...`, no auth): `state/nfl`,
  `league/{id}`, `/rosters`, `/users`, `/matchups/{week}`, `/transactions/{week}`,
  `/traded_picks`, `players/nfl`, `players/nfl/trending/add|drop`.
- `players/nfl` (~15MB) at most once per run, cached 1h in `data/cache/`.
- **Displayed fantasy points come only from matchups `players_points` / `starters_points`.**
  Never use Sleeper's undocumented stats or projections endpoints. One labelled exception:
  a week where the player wasn't on any league roster has no Sleeper points, so cards show
  nflverse stats re-scored with league scoring as `calc`, always prefixed "≈" (free agents).
- Projections are built from free nflverse data: weekly stats re-scored with the league's
  scoring (verified to match Sleeper), snap counts, and `nflverse/nfldata` games.csv
  (byes, Vegas lines). No paid services, no scraping.
- Cross-check my players' season points vs nflverse; > 1 pt off = "unverified" (soft label).
- IR eligibility from league settings (`reserve_allow_*`); never suggest IR otherwise.
- Be polite to APIs: delays, retries with backoff.
- Warn (don't crash) when league settings differ from `expected_settings`.
- Show uncertainty honestly: confidence labels, ranges, odds rounded to 5% until 9+ weeks.

## Model notes

- **Points/season**: season stats cover weeks up to `last_scored_leg`; only weeks a player
  was on some league roster (that's all `players_points` has). Games = non-zero weeks or
  an nflverse stat row. Sleeper `gsis_id` is often missing → match nflverse by normalised
  name + position (team breaks ties). nflverse updates nightly: a week is only
  cross-checked once nflverse has rows for the player's team (`pending_weeks`).
- **FAAB**: transactions include failed claims. Same player + same `status_updated` =
  same waiver run. "claimed by another owner" = outbid; other failures = invalid bid.
  Clearing price = runner-up + $1 (tie = same bid; uncontested = `waiver_bid_min`).
  Bargain = wins 50% of past claims at clearing price; competitive = beats 50% of all
  bids at the position; safe = beats 75%. Capped at my remaining FAAB.
- **Scanner**: baseline = newest snapshot folder, read before today's is overwritten.
  Watches rostered players, NFL depth order <= 2, or search_rank <= 300. Missing-time
  designations on another team's starter → trade opening + motivated buyer.
- **Projections**: rate = (2 × role baseline + 0.5 × last-season games [×0.5 after a team
  change, cap 17] × last-season PPG + this-season games × (50% actual + 50% usage-expected
  PPG)) / total weight. Partial games (snap share < 60% of own median; two latest low =
  role change unless currently injured) excluded. Weekly = rate × matchup (Vegas implied
  totals when available, else shrunk + dampened defence-vs-position, ±10%) × availability
  (Q 0.85, D 0.25, Out 0 then 0.75, IR-type 0 for 4 weeks then 0.5); byes = 0. Confidence:
  high = 4+ full games this season and 8+ effective; medium = 4+ effective; else low.
  DEF points from nflverse defensive stats + final scores. nflverse "LA" = Sleeper "LAR".
- **Trades**: team value = Σ remaining regular-season weeks of the optimal lineup with
  (1) a **free-agent floor**: every slot worth at least replacement level for that slot
  (`repl` = avg of the best 3 healthy FAs; FLEX floor = max of eligible positions), so only
  points above replacement count; (2) **injury cover**: each starter above the floor costs
  `ABSENCE_RATE` (7%) × (pts − max(best eligible bench, floor)); (3) **roster limit**: a team over
  the active roster size (IR/taxi excluded) cuts the player whose loss hurts least (from the
  4 lowest-ROS skill players). Same rules before and after every trade. Ideas need my gain
  >= 5 and theirs > 0; lopsided (< 25% of my gain) last. Each idea records implied cuts.
  VOR = ROS − replacement × weeks.
- **Outlook**: this week uses each team's set lineup (actual + projected). Variance scales
  with projection plus sit risk. Start/sit by P(bench outscores starter): swap >= 60%,
  close 40–60%. Playoffs: 10,000 seeded sims with per-team strength shifts for projection
  error; ranking wins then points for. Future pairings from Sleeper `/matchups/{week}`.
- **Tendencies**: style label after 3+ bids (big spender >= 1.5× league median bid, stingy
  <= 0.5×). Rivals from next week's projected optimal lineups (likely = starts by > 1 pt,
  active, >= $5), history, budget. "Rivals suggest" = likely rivals' typical..biggest bid
  + $1; hot players with no likely rival use possible rivals; bigger spenders = wildcard.

## Installable app (PWA)

`site/manifest.webmanifest`, `site/icons/` (192/512/maskable/apple-touch/favicon) and
`site/sw.js`. The service worker is network-first with a cache fallback, so you get fresh
data when online and the last good copy offline. It only caches same-origin, non-redirected
200s. Navigations go to the network untouched, so an access gate in front of the site
(e.g. Cloudflare Access) still works; only a failed navigation falls back to the cached
page. Requests with `?ping` bypass the worker (the page's offline check). It's registered
only off `file://`. Bump `CACHE` in `sw.js` if the shell file list changes. The header has
Install (shown on `beforeinstallprompt`), reload and theme buttons. iOS gets
`apple-mobile-web-app-*` meta tags plus `apple-touch-icon`.

## Player cards

`dashboard.json` → `cards[player_id]` for every rostered player (built after projections and
trades). Last 3 = last three completed weeks of Sleeper `players_points` (None = not on a
league roster; average skips byes and games not played). Next 3 = next three unplayed
weeks from projections with ±1 SD range; matchup easy >= 1.05 / tough <= 0.95 multiplier.
Usage = last 3 full games (partial only if that's all there is). Position rank = by ROS
projection among all projected players. The site renders each row as `<details>`
(tap to expand). The row shows a **six-week timeline** (`pills()` → `.wk6`): the last 3 played
weeks | a divider | the next 3, every cell labelled with its week; played = points + positional
finish coloured by tier, upcoming = projection + opponent with an easy/tough outline; the
header shows the last-3 average and next-3 projection.
Finish (`projections.assign_finishes`) = rank among every NFL player at the position that
week, by nflverse stats under league scoring (displayed points stay Sleeper's). Tiers come
from `run.starter_counts` (league-wide starters per position = n): boom <= ceil(n/2),
start <= n, bust > 2n (`cards.finish_tiers`). The detail panel adds headline tiles,
`consistency` (floor / median / ceiling, boom / starter / bust weeks), `opportunity`
(target, air-yard and carry share, WOPR, touches, yards per touch, TDs vs the
position's league-wide TDs per opportunity: "hot" if 2+ above, "due" if 1.5+ below), a game
log (`STAT_KEYS`), and `schedule` (remaining weeks plus fantasy playoff weeks from
`run.playoff_weeks`, projected with the same rate and matchup model).
On the Trades tab, `playerExpand()` renders the same details: trade-idea and buyer players
(`.tp` inside `.has-detail`) open a full-width `.trade-detail` panel under the card;
sell-high / buy-low rows are `<details>`; value-table rows (`.tp-row`) insert a
`tr.detail-row`. Handled by one delegated listener (`wireTradeDetails`).

## Design system and navigation

`site/styles.css` is a small "clean & calm" system: neutral greys + one accent (`--accent`);
colour only carries status (`--good/--warn/--bad`, injuries, up/down, finish/rank tiers). Spacing 4/8/12/16/24/32; type 11 label / 13 small / 15 body / 17 title / 28 hero;
flat cards (no nested borders), quiet position labels, small chips. Lists of players, waiver
options, news, trades and offers are `.stack`s: one rounded tile per item with a 10px gap (no
dividers), and an opened tile's details sit in a shaded inset panel inside it, so tiles are
easy to tell apart. Navigation: five sections in a bottom bar (Home · League · Players ·
Moves · Model; floating pill on wide screens) defined in `SECTIONS` (app.js); Moves =
Waivers · News · Trades · Lab · Teams; Settings + Brief sit behind the header gear
(`settings` section, no bar button). Sections with several panels show a segmented sub-nav (`#subnav`). Hashes are panel ids (#faab, #lab …) and
`hashchange` is handled. Any `<p class="lead-text">` directly after an `<h2>` is turned into
an ⓘ toggle by `tidyExplanations()` (MutationObserver), so keep explanations in that shape.
Theme (Auto / Light / Dark) lives in Settings (header gear). Matchup cards include a side-by-side
lineup (`sideBySide`) for every matchup.

## Home and League tabs

Panels: home, league, players, faab, news, trades, lab, nfl, model, more, brief (old #team /
#matchups map to Home; #standings / #playoffs / #rosters to League; #planner (removed) to Home; #waivers to #faab). `league.py` →
`site/data/league.*`: weekly scores + per-week league median (Sleeper matchup points),
all-play record, luck = actual wins − all-play expected wins, power rankings
(z-scores: results so far weight 0.9·n/(n+5), projection 0.9 − that, efficiency 0.1), and
`data/odds_history.json` (one entry per run day, last 60) for the odds trend sparkline.
Toggles remember their view in localStorage (`homeView`, `leagueView`). Weekly scores
(`weeklyChart` / `weeklyStats` in app.js, no pipeline data beyond league.json) shows each
team's last 4 weeks as score pills (score + that week's league rank; 1st = solid green,
top 3 = light green, bottom 3 = red, W/L) and expands to scoring rank, points against per
week (schedule luck), all-play + luck, consistency (SD vs the league median SD) and every
game with "would have beaten N of M". The same `.pill` / `.f-*` tier classes as player cards.

## Self-learning projections (Model tab)

`projections.py` splits each rate into `rate_components` (data) and `rate_from` (settings);
matchups into `matchup_raw` and `multiplier_from`. Settings live in `DEFAULT_PARAMS`
(prior_weight, usage_blend, baseline_games, vegas/dvp damping, per-position `bias` and
`sd_scale`); `build(..., params)` uses them. `run.build_model` runs before projections:
`model.backtest_records` rebuilds every completed week's projection for the fantasy-relevant
players (top 2x league starters per position) from games before that week and records the
nflverse league-scoring result; `model.learn` = `tune` (grid search over `GRID`, adopted only
with >= `MIN_GAMES_TO_TUNE` full games and >= `MIN_IMPROVEMENT`; per-position bias and range
width shrunk with `SHRINK_GAMES` and capped) then a held-out check on the latest week (re-tuned
without it; switched off if it does worse than defaults by > 1%). Everything is recomputed
from scratch every run. `build_model_page` saves the live ledger
(`data/projection_ledger.json`: each player's next-game projection, overwritten until played)
and scores it (Sleeper points, else nflverse, else 0 = didn't play), plus
`data/model_history.json` (one entry per week). Both persist via the private repo's data/.
Site: `site/data/model.*`, `renderModel()`.

**Model v3** (backtest, ranges, extra settings). The backtest is honest: candidates for week
w include players on that week's official injury report who didn't play (actual 0) and
partial games; `project()` applies that week's status (learned availability), weather, game
script and backup-QB flag. Headline metrics cover every record; `full_games` is separate.
New settings (all tunable, all in `DEFAULT_PARAMS`, per-position overrides in `by_pos` via
`pp(P, key, pos)`): `partial_weight` (partial games scaled per snap to a full game and
weighted by their fraction, only with 20%+ snaps and 30%+ of normal: `PARTIAL_MIN_*`),
`rank_prior` (starting point blends in Sleeper's ranking: `sleeper_pos_ranks` → `rank_tiers`
of established players' points per game → `rank_baseline_for`; backtest uses saved
snapshots taken before each week via `run.snapshot_ranks`, so weeks before the first snapshot
can't judge it; default 0.5), `script_rb` / `script_pass` (`script_multiplier`, Vegas expected
margin / 7, capped ±15%), `qb_change` x `qb_factor` (`roles.learn_qb_change`: RB/WR/TE points
when the usual QB - most attempts, 2+ starts - didn't start; `apply_qb_change` when he's out or
not depth-chart #1). Tuning: `_coordinate_search` over the finer `GRID` (global, then
`POS_KEYS` per position with 150+ games and 2%+ gain); adopted with 0.5%+ in-sample gain and a
rolling check (`CV_WEEKS`: re-learn without each of the last 3 weeks, must beat the starting
settings on them combined). Ranges: `learn_quantiles` = 10/16/50/84/90th percentiles of
actual / projected per position in three projection bands (shrunk to the position, 40 games),
with spreads narrowed by sqrt(band median / projection) above the band median
(`quantile_points`); stored as `weekly[w].q` and card `value.range`; coverage is judged on
16th-84th (~68%) and 10th-90th (~80%).

**Recency, injuries, weather** (`factors.py`). `recency` (tuned: 1 = all games equal) weights
this-season games by `recency ** (weeks before the projected week)` (`rate_components` keeps
`this_games` + `as_of`). Injuries: nflverse `injuries_{season}.csv` (last + this season,
`run.INJURIES_URL`) → `learn_availability`: share of normal points produced (0 if he sat) per
status and status|practice (dnp / limited / full), shrunk toward 85/25/0% with 25 cases;
`availability()` uses it for the current week (practice split once it has 20+ cases);
this week's practice comes from `current_practice`. Weather: `schedule()` carries roof /
wind / temp; `learn_weather` gives per-position dome / outdoor / wind (15+ mph) / cold (<= 32F)
factors vs the player's season average (shrunk, capped 0.85-1.15); `weather_strength` (tuned,
starts 0) scales them. Forecasts: Open-Meteo (free, no key) for unplayed outdoor home games in
the next 7 days (`STADIUMS` coordinates; neutral sites skipped), cached 3 h. Both tables travel
in `params` (`availability`, `weather`) and show on the Model page and in each card's
"Game day" note.

## NFL teams, depth charts and roles (phase 1)

`run.build_teams` → `site/data/teams.*` and `cards[pid].role`. Depth order is Sleeper's
`depth_chart_order` (WRs are listed per slot, so ties are broken by projection); weekly usage
from nflverse logs. `teams.weekly_role`: share = carry share (RB), target share (WR/TE) or
snap % (QB) per game; a game is "left early / limited" if the snap share is under 70% of
his median this season (this-season normal, so it catches cases the projection's
`mark_partial` misses). `opportunity_weeks`: weeks where someone ahead on the depth chart
(who has played this season) left early or didn't play; those weeks are shown with ↑ and
excluded from the label. `job_security`: Locked in / Starter / Lead role / Rising / Losing
work (7-point share trend, last 2 normal games vs season) / Committee / One injury away (#2
behind a 50%+ RB, or #2 QB/TE without a role) / Depth / Unproven. `position_strength`:
fantasy points per game produced and allowed per position, ranked 1-32 with the median;
`offence`: plays, pass rate, points, next game's implied total. Site: tap any team code
(`teamLink`, `data-act="team"`) for the team sheet (`dialog#team-sheet`); Moves → Teams
table (sortable by position, localStorage `nflSort`); player panels show a Role section.
Phase 2 (`roles.py`, in projections): `mark_opportunity` flags RB/WR/TE games where a teammate
with a higher median share (2+ full games) sat or left early; they're excluded from the
player's this-season rate and role shares. `mark_partial` now judges snaps against this
season's median once there are 3+ games. `role_components` = team carries/targets per game
(`team_volume`, shrunk 2 games) x normal carry/target share x points per carry/target
(shrunk 40 carries / 25 targets); `rate_from` blends it in by `role_blend` (tuned, starts 0)
x n/(n+2). `learn_take` (last + this season): share of a missing regular's work the next man
down gets (`take`) and all teammates below him combined (`group`), shrunk with 15 events.
`projections.apply_inheritance`: for every week a player's availability < 1, his shares flow
down only (to lower-share teammates): next man `take`, others `group - take` by share; extra
points added to that week (`weekly[w].inherit`) and `contingency` = rate if the top-share
teammate misses a full game. `teams.opportunities` lists next-game boosts >= 2.5 pts (News).
Shown: Role section (if X misses), team sheet, waiver tiles (handcuff), Game day note,
Model page (who inherits the work).

## Player card (detail panel) order

`detailPanel` is built as chapters (`section.pd-ch` with an accent `h3`): actions first
(`.pd-acts`), then **This week** (next game: opponent, matchup, projection with typical range /
floor / ceiling, conditions, plus `gameDayNotes`: injury + practice, inherited work, backup
QB), **Rest of season** (projection, floor / ceiling, rank, value vs a free agent, confidence,
flags, byes, schedule incl. playoffs), **Role & usage** (`roleSection`: depth chart, job
security, if X misses, share by week; then usage & efficiency) and **Track record** (season
ppg, average finish, consistency, game log collapsed in `details.pd-log`). Keep new content in
the chapter that answers the matching question.

## Players (search)

`renderPlayers` searches every projected player (`DATA.lab.players`, ~530) joined with their
card (`site/data/cards.*`: cards for all projected players, written separately from
dashboard.json), waiver analysis (`F.available`), opportunities (`TM.opportunities`) and
trade flags. Filters: text (name / team), position, availability (everyone / free agents /
mine / other teams), NFL team, role labels, health, situation flags (`FLAG_DEFS`: handcuff
value >= 2 pts, opportunity this week, upgrades my team, sell-high, buy-low, held, trending);
sorts (`SORTS`). State in localStorage `playerSearch`; 40 results at a time. Rows are
`playerRow` tiles with an extra summary line (owner, role, handcuff, opportunity, waiver gain).

## Loading, Back button and the to-do list

- Data files are written compact (`output.write_site_data`, no indentation). Player cards are
  split: `cards.js` (rostered players, waiver pool, opportunity players: what Home, Waivers
  and Trades show) loads with the page; `cards_more.js` (everyone else, nulls pruned) loads
  2.5 s later or when Players opens (`ensureMoreCards`).
- Service worker (`sw.js`, cache `fantasy-nfl-v2`): data/*.js are stale-while-revalidate (the
  cached copy shows instantly; if the fresh copy differs the page gets a `data-updated`
  message and shows "Newer data has downloaded · Show it"); app files network-first.
- Back button: tab changes `pushState`; open dialogs (team sheet, Ask Claude) and expanded
  `details.prow-d / .wv / .ws` are layers (`pushLayer` / `dropLayer`); `popstate` closes the
  top live layer first, else restores the tab from the hash. Opening a player scrolls it into view.
- Home starts with **This week** (`todos()`): lineup swaps from start/sit, roster notes,
  opportunities for free agents / my players, waiver upgrades (fit = upgrade), free-agent
  handcuffs for my RB starters (contingency >= 3 pts over their projection), my sell-high
  players (not held) and the best non-lopsided trade idea; 5 shown, rest under "more".
  Buttons use `data-act="go"` (tab) / `"find"` (opens Players with a name search) / `"shop"`.

## Compare, watchlist, search

- **Watchlist** (localStorage `watch`, per device): `☆ Watch` in `actionButtons` for any player
  that isn't mine; watched players show ★ on rows, a Watchlist section on Home (`watchHtml`)
  and a "★ Watching" filter in Players.
- **Compare** (localStorage `compare`, up to 3): `Compare` in `actionButtons`; a floating tray
  (`#compare-tray`) above the tab bar opens `dialog#compare` (`openCompare`): owner, status,
  this week (projection, opponent, matchup, range, floor / ceiling), ROS projection and rank,
  last 3 (avg + finishes), next 3, starter-level weeks, role, if starter misses, value vs FA;
  best value per row highlighted. Back closes it.
- **Search**: header magnifier opens Players with the search box focused. Trade Lab picker has
  a name filter + position toggle (`LAB_FILTER`; selected players always stay visible).

## Card polish, wide screens, glossary

- Opened player cards start with a sticky mini header (`.pd-sticky`: name, position, team,
  this week's projection, Close) and end with a full-width Close button (`data-act="collapse"`;
  also closes Trades-tab detail panels). `.stack > details` uses `overflow: visible` so the
  sticky header works inside tiles.
- ≥1100px: main is 1160px wide; stacks of player / waiver / news / to-do / trade tiles become
  two columns and an opened tile spans both (`:has()` selectors in styles.css).
- `.table-wrap` shows a fade on the side that can scroll (background-attachment local/scroll).
- Settings → Glossary (`GLOSSARY`, `renderGlossary`, searchable); every ⓘ explanation ends with
  a "Glossary →" link. Settings shows the update time as "X ago (date)".

## Freshness

The header subtitle shows "Updated <relative time>" (`showUpdated`, refreshed every minute;
amber when older than 1 day on an NFL game day in US Eastern time (Thu / Sun / Mon), else
4 days). The ↻ button only reloads; new data comes from scheduled or manual pipeline runs.

## Ask Claude (no API)

The header chat icon and an "Ask Claude" button in every player panel and the Lab summary
open `dialog#ask`. `askMessage()` builds plain text: the question, a context line, a
context block (`playerText` = card + waiver view, `tradeText` = `evaluateTrade` result +
players, `waiversText` = Best-for-you list), `rosterText()` and the league brief. The header
icon picks the context from the visible tab (lab with a trade → trade, faab → waivers, else
general). Sent with `navigator.share` (Android share sheet → Claude app) or copied to the
clipboard. Deliberately no API calls: the user doesn't want usage-based costs. Keep messages
around 10 KB.

## Waiver targets (Waivers → Bids & FAAB)

`run.build_available` → `faab.json` `available`: `waivers.pool` takes the best unrostered
players per position by ROS (`POOL_SIZE`; long-term out excluded). `waivers.my_gain` adds each
to my roster with a `trades.Valuer` **without** the free-agent floor (so it's measured
against my real roster) and the roster limit (cuts the weakest; K/DEF replace my weakest at
the position). Fit: upgrade >= 1.5 pts/wk, depth >= 0.5, else none. Bid
(`build_tendencies`): rivals as before; demand from likely rivals (2+ hot, 1 warm, 0 quiet);
upgrade = market level for that demand; depth = bargain (competitive if 2+ likely rivals);
none = league minimum. Each pool player also gets a player card (pills + detail panel). The
site has a position toggle (Best for you = fit != none by gain, max 12; positions by ROS),
localStorage `faabPos`. Trending adds are still fetched but only shown as a tag.

## Trades tab strength views

`trades.season_strength()` gives actual points per week by lineup position from Sleeper
`starters` / `starters_points` (aligned with non-bench `roster_positions`), plus hindsight
efficiency = started points / best lineup from that week's `players_points`.
`trades.trades_made()` counts completed trades per roster. Both go in `trades.json →
history`. The site toggles Season so far / Projected / Partners (choice saved in
localStorage `strengthView`); Partners joins needs/surplus with Playoffs-tab odds.

## Trade Lab (in-browser engine)

`site/data/lab.js` (from `lab.py`) holds compact per-player weekly projections `w` and
variances `v` aligned with `weeks` (0 = bye or game already played), rosters, standings,
remaining schedule, this week's set-lineup distributions and Python `check_scores`.
`site/lab.js` (`window.NFLLab.create(data)`) mirrors lineups.py / trades.Valuer /
outlook.simulate in JavaScript: `lineup`, `value`, `profile`, `simulate` (mulberry32 seed,
same random seasons before/after), `evaluateTrade`. **Any change to the Python valuation
or simulation must be mirrored in lab.js.** Verify with
`uv run --with playwright python tools/lab_parity.py` (values within 0.5, trade gains
within 0.2, odds within 3 percentage points). The site shows a warning if `selfCheck()` fails. Trade Lab odds use
`simulate(..., {mode: "value"})` (weekly means = the trade value's expected points) so odds and
gains agree; the default `mode: "lineup"` matches the Playoffs tab and is what parity checks.
**Optimise this deal** (summary card) calls `improveTrade(partner, give, get)`: keeps the most
valuable player on each side fixed, tries every version within two changes (add / remove /
swap supporting players from each side's top 10 tradeable, holds excluded, sides 1-3), and
returns up to three that I don't lose on and they gain from (smallest fix, best for me,
fairest), or the closest if none. "Apply" loads that version.
Lab page order: picker → result (summary card with verdict, gains and Why; then players
in the deal, odds, lineup, week by week, strength) → suggested offers (the loaded one is
marked "Showing above"; the summary card links down to the rest).
Sub-tabs that share their section's name are selected with `selectTab(name, true)` so they
don't jump back to the last sub-tab. (The Planner was removed: unused.)

**Suggested offers and quick actions.** `suggestOffers({get | give, partner})` in lab.js
searches 1-for-1, 2-for-1, 1-for-2 and 2-for-2 deals around the fixed player (buy: my
tradeable players, plus one of theirs alongside the target; shop: their players, plus one of
mine as a second piece; one partner or all teams). Only like-for-like packages are scored
(total `ros` within 0.67-1.5x). It never suggests a deal that lowers my value; it keeps deals
where they gain, ranked by min(my gain, their gain), boosted when it fills a lineup gap
(`leagueProfiles` needs). If none exist it shows up to 3 near-misses (they'd lose < 3 pts),
labelled as needing a sweetener. Max 2 per team, throw-in duplicates dropped. app.js has one delegated click handler for
`[data-act]` buttons: `trade-for` / `shop` / `pitch` open the Lab with offers already
searched (`openInLab(..., {suggest, shopAll})`), `hold` toggles a stash, `team` opens a
team sheet and `ask` opens Ask Claude. `actionButtons(pid)` picks the buttons from the owner in `DATA.lab`
(mine / another team / free agent) and is used in player detail panels, FAAB cards and News.

**Holds (stashes).** localStorage `holds` (per device). `ownerOf` falls back to the league rosters (`lab.rosters[].all`) for players without a projection (e.g. no current NFL team), so they can still be held; Lab buttons only show for projected players. Held players are passed to the
engine (`setHolds`) so they're never offered or cut in Lab maths; trade ideas that give or
drop one are hidden (with a count), they're left out of sell-high and "players you could
pitch", and the sell-high flag is replaced by a "held" tag. Python output is unaffected (parity runs with no holds).

## Automation

`.github/workflows/update.yml`: tests on every push/PR. The pipeline + GitHub Pages deploy
run on schedule (`0 8 * * 2,5` UTC, after MNF/TNF all season) or manually, **only when
the `LEAGUE_ID` repository variable is set**. League data is never committed; `data/` is
carried between runs in the Actions cache. Pin `astral-sh/setup-uv` to a full version
(no floating major tags).

## Testing

Tests cover all calculation logic with saved neutral sample data in `tests/fixtures/`.
**Tests never call live APIs.**

## Git workflow

Each feature on its own branch, small clearly described commits, a PR describing what
changed, why, and how to check it. Commits use the GitHub noreply email.

## Gotchas

- `uv` may warn about `VIRTUAL_ENV` if conda is active; harmless.
- Headless Chrome can't go below ~500px wide; for phone screenshots put several 390px
  iframes side by side in a wide window and use `--virtual-time-budget`.
