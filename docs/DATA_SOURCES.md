# Data-availability reconnaissance — findings & decisions

*Compiled from live API probing on 2026-07-18. Every claim below was checked
against the real endpoint, not documentation, unless marked otherwise.*

## TL;DR

| Question | Answer |
|---|---|
| Do prediction markets have historical NBA **total-points** markets? | **Yes, but shallow.** Polymarket ≈ **one season** (2025-26). Kalshi ≈ **2026 playoffs only**. |
| Which platform to target? | **Polymarket** for the tradeable backtest (full 2025-26 season, 1-min pre-tip prices). Kalshi is forward-only. |
| Can we get 5+ seasons of referee + box-score data? | **Yes** — but **not** via `nba_api` from this environment (`stats.nba.com` is IP-blocked). basketball-reference is the fallback. |
| Is the thesis likely to yield a tradeable edge? | **Probably small-to-null.** Well-known idea; crew-level samples are underpowered; confounds are severe. Honest null is the base case. |

**The central tension:** the referee signal needs 5+ seasons to have any statistical
power, but prediction-market prices for NBA totals only exist for ~1 season. The
design resolves this with two layers (see `README` + below).

---

## 1. Kalshi — `KXNBATOTAL` "Pro Basketball Total Points"

- **Exists.** Per-game combined total as a **ladder of binary "Over X.5" strikes**
  (3 pts apart), each resolving Yes if combined score > line. Under price = 1 − Yes.
- **Public read API, no auth**, base `https://api.elections.kalshi.com/trade-api/v2`.
  Minute/hour/day candlesticks (`/series/KXNBATOTAL/markets/{ticker}/candlesticks`,
  UNIX `start_ts`/`end_ts`), tick trades (`/markets/trades`), settlement result/value.
- **Coverage: only 2026-05-06 → 2026-06-14** (2026 playoffs, ~498 settled strike-markets).
  **No regular-season history retrievable.** Launched/retained from the May 2026 playoffs.
- **Fees (sports, `quadratic_with_maker_fees`):** taker ≈ `ceil(0.07·C·P·(1−P))` cents/contract
  (peaks 1.75¢ at P=0.50), maker ≈ 25% of that. Confirm against live July-2026 fee PDF.
- **Verdict:** great for *forward* capture / 2026-playoffs-on studies; **cannot** source a
  multi-season historical backtest today.

## 2. Polymarket — NBA game O/U totals  ✅ target platform

- **Exists** as clean two-sided `["Over","Under"]` markets, e.g. `"Warriors vs. Spurs: O/U 229.5"`.
- **Gamma API** `https://gamma-api.polymarket.com`; NBA tag `id=745`. Markets/events paginate
  at 100/page; the API caps offset near ~2100, so size long spans with
  `end_date_min`/`end_date_max` filters.
- **Coverage (game O/U totals, strike-market counts, 2025-26 season):**
  Oct 561 · Nov 1049 · Dec 636 · Jan 382 · Feb 367 · Mar 390 · Apr 333 · May 290 · Jun 173
  (~4,180 strike-markets ≈ **800–1000 games** at several strikes each). Plus the 2025 playoffs
  (May–Jun 2025). **Earlier seasons (2023-24, 2024-25 regular season) were moneyline-only — no totals.**
  So usable game-total history ≈ **one season (2025-26)**.
- **Historical prices — CLOB** `https://clob.polymarket.com/prices-history?market={clobTokenId}&startTs=..&endTs=..&fidelity=1`.
  `interval=max` returns empty for resolved markets — **use explicit `startTs`/`endTs`.** Verified:
  1-minute bars, e.g. last pre-tip print **0.64 at 02:29:08 UTC, one minute before a 02:30 tip.**
  This gives a clean **market-implied probability at/near tip-off** — exactly what the backtest needs.
- **Resolution:** `outcomePrices` `["0","1"]` / `["1","0"]` gives the winning side; `outcomes` labels them.
- **Fees:** no explicit per-trade fee; **cost is spread** (+ small on-chain/relayer cost). Liquidity on
  individual game totals is **thin** (many markets < ~$1k volume) — a real execution caveat.
- **Verdict:** the only viable platform for a historical NBA-totals *price* backtest, but only **~1 season**.

## 3. Referee crews + box scores (5+ seasons)

- **`nba_api` / `stats.nba.com`: BLOCKED from this environment.** TCP connects but `/stats/`
  endpoints blackhole (15s timeout, 0 bytes) even sandbox-off with full browser headers;
  `cdn.nba.com`/`data.nba.com` return 403 (Akamai). **`boxscoresummaryv2` officials cannot be
  pulled here.** *It may work from a residential IP* — an option if the user runs it themselves.
- **basketball-reference.com — reachable (200), and the primary fallback:**
  - Each boxscore page lists the **3 officials with stable ref IDs**, e.g.
    `Officials: Ray Acosta (/referees/acostra99r.html), Brandon Adair, Nate Green`.
  - Full team box scores, four-factor / advanced tables (pace, FTA rate, 3PA rate), and per-season
    schedules are all present. So (game_id, date, home, away, off1..3, pts, pace, FTA, 3PA) is
    fully assemblable.
  - **Caveats:** ~1,300 games/season → **~6,500 boxscore pages for 5 seasons**; b-ref rate-limits
    (~20 req/min, blocks aggressive scraping); scraping is against ToS (tolerated for light personal
    research). Budget a few hours of throttled, cached pulls.
- **Pre-built officials datasets (found, cover 2010–2024 only):** `CMSC122/NBARefs` (ref→game map),
  `blakelaw/Referee-Analysis`, `NocturneBear/NBA-Data-2010-2024`. Useful to *seed* older seasons and
  cross-check, **but none cover 2025-26** — the season we actually need for the Polymarket overlap —
  so b-ref (or nba_api) is required for 2025-26 regardless. Licensing to be verified before use.
- **Forward crew assignments:** `official.nba.com/referee-assignments/` posts crews game-day (~9–10am
  ET) with an API/JSON behind it — the "public before market close" hook for a live signal, and a
  cross-check on historical crews.

## 4. Sportsbook closing totals (the pre-2025 "market" benchmark)

Because prediction markets only exist for 2025-26, the **Vegas closing total** is the market baseline
for the earlier seasons (it's what "the market" priced then). Freely available for 5+ seasons:
- **sportsbookreviewsonline.com** — opening/closing spreads **and totals** per season (spreadsheets).
- **Kaggle** — e.g. `ehallmar/nba-historical-stats-and-betting-data` (money lines, spreads, totals,
  2008–2023). Use as the market-line control feature and the pre-2025 baseline to beat.

## 5. Prior art & the honest caveats (why the base case is "null")

- **Not novel.** A cottage industry (RefMetrics, NBAstuffer, Covers, "Donaghy Effect") publishes
  per-ref O/U and FTA trends; academic work exists on ref bias (Price & Wolfers; "Subperfect Game").
  Assume sophisticated bettors already model it.
- **"Books don't adjust for refs" is weak evidence of inefficiency** — the *closing* line still
  absorbs all ref-aware sharp money even if no trader types a manual ref adjustment.
- **Confounds most likely to manufacture a false edge (rank-ordered):**
  1. **Regional assignment routing** → ref identity is collinear with which teams/pace they see.
  2. **Endogenous pace/fouls** — fast teams draw fouls; refs *reflect* rather than *cause* pace.
  3. **3-man crews almost never recur** → crew-level samples are underpowered; easy to overfit.
  4. Playoff vs regular-season officiating differ materially (keep them separate).
- **Magnitude:** credible claimed edge is ~1–3% EV on affected totals and contested; a defensible true
  individual-ref effect is likely 0–2 total points, often statistically indistinguishable from zero
  after team-pace controls. **Vig (~4.5% on −110 totals) exceeds the claimed EV**, so only low-juice /
  prediction-market venues could clear it.
- **Design implication:** model at the **individual-referee level with heavy shrinkage**, not the
  3-man crew level; control for both teams' pace; strictly pre-game rolling stats; separate playoffs;
  treat any large in-sample edge as leakage/confounding until OOS + fee-clearing evidence says otherwise.

---

## Recommended design (given the above)

**Two layers**, so the statistical question keeps 5-season power while the tradeable claim uses the
real prediction-market prices we actually have:

1. **Modeling / statistical test — 5+ seasons (b-ref box scores + officials; sportsbook closing total
   as the market control).** Walk-forward; baseline (no ref) vs. treatment (+ shrunk individual-ref
   features); paired OOS log-loss / Brier; permutation test on ref labels. *This is where the result lives.*
2. **Tradeable backtest — 2025-26 (Polymarket 1-min pre-tip prices).** Model prob → edge vs.
   market-implied prob → fractional-Kelly net of spread/fees → P&L, Sharpe-like, max drawdown,
   calibration. **Explicitly caveated as a single-season, thin-liquidity sample.**
