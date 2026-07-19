"""Fractional-Kelly staking on binary over/under contracts, net of costs.

Each row is one over/under contract with a market-implied P(over) ``q`` (the pre-tip
price) and a model P(over) ``p``. We take the side the model favours vs. the market,
size by fractional Kelly, apply a transaction cost, and settle on the realised
outcome (``over_won``). Polymarket charges no explicit trading fee, so the cost we
model is the effective spread/slippage — configurable and applied on entry.

Kelly for a $1-payout binary bought at price ``c`` with win prob ``w``:
    f* = (w - c) / (1 - c)
which is just edge / downside. We stake ``kelly_fraction * max(f*, 0)`` of bankroll
and never bet when the post-cost edge is non-positive.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from refedge.config import CFG
from refedge.backtest.metrics import summarize_pnl


def _kelly_fraction(win_prob: float, cost: float) -> float:
    if cost <= 0 or cost >= 1:
        return 0.0
    return (win_prob - cost) / (1.0 - cost)


def simulate(
    df: pd.DataFrame,
    p_col: str = "pred",
    q_col: str = "p_over_tip",
    outcome_col: str = "over_won",
    txn_cost: float = 0.015,
    kelly_fraction: float | None = None,
    min_edge: float = 0.02,
    max_stake: float = 0.05,
    bankroll0: float = 1.0,
) -> dict:
    """Simulate sequential fractional-Kelly betting; return P&L summary + per-bet log.

    ``txn_cost`` (default 1.5c) is charged on the entry price of whichever side we
    take. ``min_edge`` requires the model to disagree with the market by at least
    that much (post-cost) before betting. ``max_stake`` caps any single bet's
    fraction of bankroll (a guard against a mispriced-thin-market blow-up).
    """
    kf = CFG.kelly_fraction if kelly_fraction is None else kelly_fraction
    d = df.dropna(subset=[p_col, q_col, outcome_col]).sort_values("date").copy()

    bankroll = bankroll0
    equity = [bankroll]
    rows = []
    for r in d.itertuples(index=False):
        p = float(getattr(r, p_col))          # model P(over)
        q = float(getattr(r, q_col))          # market P(over)
        over_won = bool(getattr(r, outcome_col))
        if not (0 < q < 1):
            continue

        # Choose the side the model favours vs market; cost applied to entry price.
        if p > q:  # model likes the OVER
            side, cost, win_prob, won = "over", q + txn_cost, p, over_won
        else:      # model likes the UNDER
            side, cost, win_prob, won = "under", (1 - q) + txn_cost, 1 - p, (not over_won)

        edge = win_prob - cost
        if edge < min_edge:
            equity.append(bankroll)
            continue
        f = min(kf * _kelly_fraction(win_prob, cost), max_stake)
        if f <= 0:
            equity.append(bankroll)
            continue

        stake = f * bankroll
        # $1-payout contract bought at `cost`: win -> +stake*(1-cost)/cost, lose -> -stake.
        pnl = stake * ((1 - cost) / cost) if won else -stake
        bankroll += pnl
        equity.append(bankroll)
        rows.append({
            "game_id": getattr(r, "game_id", None), "date": getattr(r, "date", None),
            "side": side, "p": p, "q": q, "edge": edge, "stake_frac": f,
            "won": won, "bet_return": pnl / stake, "bankroll": bankroll,
        })
        if bankroll <= 0:
            break

    log = pd.DataFrame(rows)
    summary = summarize_pnl(log["bet_return"].to_numpy() if len(log) else np.array([]),
                            np.array(equity))
    summary["n_candidates"] = int(len(d))
    summary["bet_frequency"] = float(len(log) / len(d)) if len(d) else 0.0
    return {"summary": summary, "log": log, "equity": np.array(equity)}
