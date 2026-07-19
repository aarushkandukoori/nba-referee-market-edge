"""P&L and probabilistic scoring metrics for the backtest."""
from __future__ import annotations

import numpy as np


def max_drawdown(equity: np.ndarray) -> float:
    """Largest peak-to-trough drop of an equity curve, as a fraction of the peak."""
    equity = np.asarray(equity, dtype=float)
    if len(equity) == 0:
        return 0.0
    peak = np.maximum.accumulate(equity)
    dd = (equity - peak) / peak
    return float(dd.min())


def sharpe_like(returns: np.ndarray, periods_per_year: int = 1000) -> float:
    """Sharpe-like ratio of per-bet returns.

    Bets are not calendar-spaced, so this is a *per-bet* Sharpe annualised by an
    assumed bets/year (default ~1000, an NBA season of daily bets). Report it as a
    unitless comparison figure, not a tradeable guarantee.
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 2 or r.std(ddof=1) == 0:
        return 0.0
    return float(r.mean() / r.std(ddof=1) * np.sqrt(periods_per_year))


def summarize_pnl(bet_returns: np.ndarray, equity: np.ndarray) -> dict:
    r = np.asarray(bet_returns, dtype=float)
    return {
        "n_bets": int(len(r)),
        "total_return": float(equity[-1] / equity[0] - 1.0) if len(equity) else 0.0,
        "final_bankroll": float(equity[-1]) if len(equity) else float("nan"),
        "mean_bet_return": float(r.mean()) if len(r) else 0.0,
        "hit_rate": float((r > 0).mean()) if len(r) else 0.0,
        "sharpe_like": sharpe_like(r),
        "max_drawdown": max_drawdown(equity),
    }
