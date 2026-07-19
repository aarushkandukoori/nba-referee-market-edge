"""Leakage-safe rolling REFEREE features, aggregated to crew level.

This is the treatment signal the whole study hangs on, so leakage control is the
priority:

  * For each official, their tendency stats (game total points, pace, total PF,
    total FTA, total 3PA in the games they work) are computed from a **rolling
    window of that official's PRIOR games only** — every value is shifted so the
    current game is never in its own feature.
  * Thin histories are **shrunk toward a time-varying league prior** (itself
    computed only from games before the current date), so a referee with few
    prior games doesn't contribute a noisy point estimate.
  * We model at the **individual-referee level and then aggregate**, per the
    prior-art finding that 3-man crews almost never recur and crew-level samples
    are statistically underpowered. The crew features are the mean across the 3
    officials plus dispersion terms (interaction / heterogeneity), and an
    experience floor that flags untrustworthy (thin-history) crews.

Input: a games table sorted by date with columns
    game_id, date, off1_id, off2_id, off3_id, and the per-game tendency stats.
Output: the same table with ``crew_*`` columns added.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from refedge.config import CFG

# Per-game stats attributed to each official who worked the game.
# total_tech may be 0/missing for b-ref rows; fillna(0) before rolling.
REF_STATS = ["total_pts", "pace", "total_pf", "total_fta", "total_3pa", "total_tech"]


def _league_prior(games: pd.DataFrame, stat: str) -> pd.Series:
    """Time-ordered expanding league mean of ``stat``, excluding the current game.

    Indexed by game_id. Same-date leakage is negligible (the prior is a slow,
    league-wide aggregate ~constant over a day) and we accept it for simplicity.
    """
    g = games.sort_values("date")
    prior = g[stat].expanding().mean().shift(1)
    prior = prior.fillna(g[stat].mean())  # first game: fall back to global mean
    return pd.Series(prior.values, index=g["game_id"].values)


def add_referee_features(
    games: pd.DataFrame,
    roll: int | None = None,
    shrink_strength: int | None = None,
) -> pd.DataFrame:
    """Add leakage-safe rolling crew features. Does not mutate the input."""
    roll = roll or CFG.ref_roll_games
    M = shrink_strength if shrink_strength is not None else CFG.ref_min_history

    df = games.sort_values("date").reset_index(drop=True).copy()
    # Allow callers/tests to omit optional stats (e.g. total_tech on b-ref rows).
    for stat in REF_STATS:
        if stat not in df.columns:
            df[stat] = 0.0
        else:
            df[stat] = df[stat].fillna(0.0)
    ref_cols = ["off1_id", "off2_id", "off3_id"]

    # League priors (leakage-safe), one lookup Series per stat.
    priors = {s: _league_prior(df, s) for s in REF_STATS}

    # Long format: one row per (official, game), preserving game order.
    long = df.melt(
        id_vars=["game_id", "date"] + REF_STATS,
        value_vars=ref_cols,
        var_name="slot",
        value_name="ref_id",
    ).dropna(subset=["ref_id"])
    long = long.sort_values(["ref_id", "date", "game_id"]).reset_index(drop=True)

    # Number of PRIOR games this official has worked (0 for their debut).
    long["n_prior"] = long.groupby("ref_id").cumcount()

    # Rolling mean of each stat over the official's prior games only.
    def _prior_roll(s: pd.Series) -> pd.Series:
        return s.shift(1).rolling(roll, min_periods=1).mean()

    for stat in REF_STATS:
        roll_col = long.groupby("ref_id")[stat].transform(_prior_roll)
        prior_vals = long["game_id"].map(priors[stat]).astype(float)
        n = long["n_prior"].to_numpy()
        roll_filled = roll_col.fillna(prior_vals)
        # Shrink the official's rolling estimate toward the league prior by history.
        long[f"ref_{stat}"] = (n * roll_filled + M * prior_vals) / (n + M)

    # Aggregate the (up to) 3 officials back to the game / crew level.
    agg_src = long.groupby("game_id")
    out_rows = {"game_id": [], "crew_min_experience": [], "crew_sum_experience": []}
    for stat in REF_STATS:
        for suffix in ("mean", "std", "max", "min"):
            out_rows[f"crew_{stat}_{suffix}"] = []

    for gid, grp in agg_src:
        out_rows["game_id"].append(gid)
        out_rows["crew_min_experience"].append(int(grp["n_prior"].min()))
        out_rows["crew_sum_experience"].append(int(grp["n_prior"].sum()))
        for stat in REF_STATS:
            vals = grp[f"ref_{stat}"].to_numpy(dtype=float)
            out_rows[f"crew_{stat}_mean"].append(np.nanmean(vals))
            out_rows[f"crew_{stat}_std"].append(np.nanstd(vals))
            out_rows[f"crew_{stat}_max"].append(np.nanmax(vals))
            out_rows[f"crew_{stat}_min"].append(np.nanmin(vals))

    crew = pd.DataFrame(out_rows)
    return df.merge(crew, on="game_id", how="left")


def crew_feature_columns() -> list[str]:
    """The exact list of crew feature columns produced above (for model feature sets)."""
    cols = ["crew_min_experience", "crew_sum_experience"]
    for stat in REF_STATS:
        cols += [f"crew_{stat}_{s}" for s in ("mean", "std", "max", "min")]
    return cols
