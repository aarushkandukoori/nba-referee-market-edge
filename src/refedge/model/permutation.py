"""Permutation test: is the referee 'signal' real, or just noise the model fit?

We destroy the true crew->game linkage by randomly reassigning the actual crews to
different games, recompute the rolling crew features on that shuffled assignment,
and re-run the treatment model. If the crew features carry genuine information, the
real treatment-over-baseline improvement should sit in the far right tail of the
null distribution of shuffled improvements. If it sits in the bulk, the apparent
edge is noise and must be reported as such.

Improvement is measured as ``baseline_logloss - treatment_logloss`` (higher = the
crew features helped). The baseline is fixed across permutations, so only the
treatment (crew) side is re-randomised.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from refedge.config import CFG
from refedge.features.referee import add_referee_features, crew_feature_columns
from refedge.model.train import evaluate, walk_forward_predict


def _strip_crew(df: pd.DataFrame) -> pd.DataFrame:
    return df.drop(columns=[c for c in crew_feature_columns() if c in df.columns])


def _improvement(df: pd.DataFrame, baseline_cols, treatment_cols, seed) -> float:
    base = walk_forward_predict(df, baseline_cols, seed)
    treat = walk_forward_predict(df, treatment_cols, seed)
    bl = evaluate(base["y_over"], base["pred"])["logloss"]
    tl = evaluate(treat["y_over"], treat["pred"])["logloss"]
    return bl - tl


def permutation_test(df: pd.DataFrame, baseline_cols, treatment_cols,
                     n_perms: int = 30, seed: int | None = None) -> dict:
    """Return the real improvement, the null distribution, and a permutation p-value."""
    seed = CFG.random_state if seed is None else seed
    rng = np.random.default_rng(seed)
    off_cols = ["off1_id", "off2_id", "off3_id"]

    base_df = _strip_crew(df).sort_values("date").reset_index(drop=True)
    real_df = add_referee_features(base_df)
    real_impr = _improvement(real_df, baseline_cols, treatment_cols, seed)

    null = []
    for _ in range(n_perms):
        perm = base_df.copy()
        order = rng.permutation(len(perm))
        perm[off_cols] = perm[off_cols].to_numpy()[order]  # reassign crews to games
        perm_feat = add_referee_features(perm)
        null.append(_improvement(perm_feat, baseline_cols, treatment_cols, seed))

    null = np.array(null)
    p_value = (1 + int((null >= real_impr).sum())) / (n_perms + 1)
    return {
        "real_improvement": float(real_impr),
        "null_mean": float(null.mean()),
        "null_std": float(null.std()),
        "null_max": float(null.max()),
        "p_value": float(p_value),
        "n_perms": n_perms,
        "null": null.tolist(),
    }
