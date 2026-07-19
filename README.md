# NBA Referee-Crew Edge — Prediction-Market Backtest

**One-sentence pitch:** I tested whether NBA referee crews create a predictable edge on game totals in prediction markets — with a leakage-safe walk-forward backtest — and found **no statistically significant edge**.

This is a **research study, not a trading bot.** The interesting part for FAANG/quant interviews is the experimental design (look-ahead control, baselines, permutation tests), not a made-up P&L.

---

## What I built (plain English)

**Hypothesis:** Some referee crews call more fouls / slow the game down more than others. Those differences show up in total points. Crew assignments are public before markets close. Maybe Polymarket/Kalshi underreact to that public info, creating an edge on over/under markets.

**What I actually did:**
1. Built a historical dataset of NBA games + the 3 officials + team stats (5+ seasons).
2. Built **rolling** referee features that only use games *before* the one being predicted (no cheating).
3. Trained a gradient-boosted model to predict P(over) **with** vs **without** referee features.
4. Compared them with season walk-forward validation (no random train/test splits).
5. Ran a permutation test (shuffle crew labels) to check if any “edge” is noise.
6. Simulated a fractional-Kelly strategy on Polymarket historical prices (one season).

**Result:** Referee features did **not** beat the market+team baseline out-of-sample. Permutation p ≈ 0.57. Honest null — markets don’t appear to leave this on the table under this design.

Full write-up: [`reports/findings.md`](reports/findings.md) · metrics: [`reports/metrics.json`](reports/metrics.json)

---

## The result IS the comparison

| Model | Features |
|-------|----------|
| **Baseline** | market line + team/game form, **no referee info** |
| **Treatment** | baseline **+** rolling referee-crew features |

If treatment doesn’t beat baseline on **out-of-sample log-loss / Brier**, there is no edge. P&L is secondary and caveated (single Polymarket season, thin liquidity).

### Headline numbers

| Metric | Value |
|--------|-------|
| Train sample | 5,041 regular-season games (2018–23) |
| OOS test games (walk-forward) | 1,838 |
| Δ log-loss (treatment − baseline) | **+0.00038** (treatment worse) |
| Permutation p-value | **0.57** (noise) |
| Polymarket Kelly (2025–26) | −8.9% return (underpowered; do not overclaim) |

---

## How look-ahead bias is designed out

- **Rolling, never season-average, referee stats** — only prior games (`features/referee.py`).
- **Shrinkage** for thin ref histories toward a time-varying league prior.
- **Market line as a control** — model hunts *incremental* edge, not the whole total.
- **Walk-forward by season** — train on seasons N…N+k, test N+k+1.
- **Permutation test** — shuffle crews; real “improvement” must beat the null.
- **Pre-tip prices** — last Polymarket print before tip-off, never settlement.

---

## Repo layout

```
src/refedge/
  config.py, cache.py
  data/          # ESPN games+officials, SBRO closing totals, Polymarket prices
  features/      # leakage-safe ref + team features
  model/         # walk-forward LightGBM, permutation test
  backtest/      # Kelly, calibration, drawdown metrics
scripts/run_study.py   # end-to-end: features → models → report
reports/               # findings.md, metrics.json, figures/
docs/DATA_SOURCES.md   # why Polymarket over Kalshi; data caveats
```

## Reproduce

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt && pip install -e .
# data already cached under data/ — re-runs are free
python scripts/run_study.py --n-perms 20 --prefer-train espn --prefer-backtest espn
pytest tests/test_leakage.py -q
```

> **Note:** `stats.nba.com` / `nba_api` is IP-blocked in some environments. This study uses ESPN (officials + box) + sportsbook closing totals (layer 1) and Polymarket pre-tip prices (layer 2). See `docs/DATA_SOURCES.md`.
