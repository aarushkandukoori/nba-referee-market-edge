# Findings — NBA referee-crew edge on totals

## Headline (the comparison IS the result)

- **Baseline** OOS log-loss `0.6928`, Brier `0.2498` (n=1838)
- **Treatment** (+ crew features) OOS log-loss `0.6932`, Brier `0.2500`
- **Δ log-loss (treatment − baseline)** = `+0.00038` (treatment worse / no gain)
- **Δ Brier** = `+0.00019`

## Permutation test

- Real treatment-over-baseline log-loss improvement: `-0.00003`
- Null mean / std (crew labels shuffled): `+0.00005` / `0.00034`
- Permutation p-value: `0.571` (n_perms=20)

Crew features look like noise under permutation — do **not** treat any in-sample edge as real.

## Sample-size caveats

- Games in statistical frame: **5041** across 5 seasons
- Unique referees: 98 (median games/ref=190, p10=9)
- Unique exact 3-man crews: 4553 (90% seen only once)
- Games with thin crew history (<15 prior games/ref): 15%
- Crew-level samples are thin: most exact 3-man crews appear once. Trust individual-ref shrunk features, not crew interactions.

## Polymarket backtest (single season — underpowered)

- Season: `2025-26`
- Candidates / bets: 2056 / 1131
- Total return: `-8.9%`
- Hit rate: `41.9%`
- Sharpe-like (per-bet, ann.): `-0.48`
- Max drawdown: `-87.8%`
- ECE (treatment): `0.018`

This layer is **one season of thin-liquidity markets**. Even a positive P&L here is not confirmatory without the layer-1 statistical result and a non-null permutation test.

## Method notes

- Walk-forward by season; no random splits.
- Referee features are rolling + shrunk; current game excluded.
- Market closing total is a control feature in both models.
- Train source preference: `espn`; backtest: `espn`.
