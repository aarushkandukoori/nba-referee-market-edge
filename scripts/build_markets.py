"""Background job: build the full 2025-26 Polymarket game-total dataset with prices.

Enumerates every NBA game O/U strike-market for the backtest season and fetches
the pre-tip Over-token price for each (the market-implied P(over)). Cached to
parquet; safe to re-run (cache hit returns instantly).
"""
from __future__ import annotations

from refedge.data import markets

if __name__ == "__main__":
    df = markets.build_market_totals(start="2025-09-01", end="2026-07-01",
                                     with_prices=True)
    print(f"[build_markets] DONE: {len(df)} strike-markets, "
          f"{df['game_date'].nunique() if len(df) else 0} game-days, "
          f"priced={df['p_over_tip'].notna().sum() if len(df) else 0}", flush=True)
