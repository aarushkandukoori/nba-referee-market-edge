"""Walk-forward training + the baseline-vs-treatment comparison (the core result).

We predict P(over) — the game total exceeding the market line — with a deliberately
*conservative* gradient-boosted model, because the hypothesised edge is small and
overfitting is the primary risk. Two feature sets are run through the identical
pipeline:

    baseline  = market line + team/game form (NO referee info)
    treatment = baseline + rolling crew features

The out-of-sample log-loss / Brier difference between them is the headline. Early
stopping uses a within-train, time-ordered validation slice (never the test season),
so no test information leaks into model selection.
"""
from __future__ import annotations

import warnings

import numpy as np
import pandas as pd
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

from refedge.config import CFG
from refedge.features.build import make_xy
from refedge.model.walkforward import walk_forward_splits

warnings.filterwarnings("ignore", category=UserWarning)

# Conservative LightGBM params: shallow trees, strong leaf regularisation, few
# leaves. Tuned for "don't overfit a weak signal", not for squeezing training fit.
LGB_PARAMS = dict(
    objective="binary",
    n_estimators=600,
    learning_rate=0.02,
    num_leaves=15,
    max_depth=4,
    min_child_samples=80,
    subsample=0.8,
    subsample_freq=1,
    colsample_bytree=0.8,
    reg_lambda=5.0,
    reg_alpha=1.0,
    n_jobs=-1,
    verbose=-1,
)


def _fit_predict(X_tr, y_tr, X_te, seed: int) -> np.ndarray:
    """Fit one LightGBM with within-train early stopping; return P(over) on test."""
    import lightgbm as lgb

    n = len(X_tr)
    cut = int(n * 0.85)  # last 15% of (time-ordered) train = internal validation
    Xt, yt = X_tr.iloc[:cut], y_tr.iloc[:cut]
    Xv, yv = X_tr.iloc[cut:], y_tr.iloc[cut:]
    model = lgb.LGBMClassifier(random_state=seed, **LGB_PARAMS)
    if len(Xv) >= 50 and yv.nunique() == 2:
        # LightGBM >=4.6 prefers eval_X/eval_y over deprecated eval_set.
        try:
            model.fit(
                Xt, yt,
                eval_X=Xv, eval_y=yv,
                eval_metric="binary_logloss",
                callbacks=[lgb.early_stopping(40, verbose=False)],
            )
        except TypeError:
            model.fit(
                Xt, yt,
                eval_set=[(Xv, yv)],
                eval_metric="binary_logloss",
                callbacks=[lgb.early_stopping(40, verbose=False)],
            )
    else:
        model.fit(X_tr, y_tr)
    return model.predict_proba(X_te)[:, 1]


def walk_forward_predict(df: pd.DataFrame, feature_cols: list[str],
                         seed: int | None = None) -> pd.DataFrame:
    """Collect out-of-sample P(over) for every test season. Returns test rows only."""
    seed = CFG.random_state if seed is None else seed
    df = df.sort_values("date").reset_index(drop=True)
    preds = []
    for test_season, tr_idx, te_idx in walk_forward_splits(df):
        X_tr, y_tr = make_xy(df.loc[tr_idx], feature_cols)
        X_te, _ = make_xy(df.loc[te_idx], feature_cols)
        p = _fit_predict(X_tr, y_tr, X_te, seed)
        out = df.loc[te_idx, ["game_id", "date", "season", "y_over", "total_pts", "line"]].copy()
        out["pred"] = p
        preds.append(out)
    return pd.concat(preds, ignore_index=True) if preds else pd.DataFrame()


def evaluate(y: np.ndarray, p: np.ndarray) -> dict:
    y = np.asarray(y, dtype=int)
    p = np.clip(np.asarray(p, dtype=float), 1e-6, 1 - 1e-6)
    out = {
        "n": int(len(y)),
        "logloss": float(log_loss(y, p, labels=[0, 1])),
        "brier": float(brier_score_loss(y, p)),
        "accuracy": float(((p > 0.5).astype(int) == y).mean()),
        "base_rate": float(y.mean()),
    }
    out["auc"] = float(roc_auc_score(y, p)) if len(np.unique(y)) == 2 else float("nan")
    return out


def compare_models(df: pd.DataFrame, baseline_cols: list[str],
                   treatment_cols: list[str], seed: int | None = None) -> dict:
    """Run both feature sets walk-forward; return metrics + the paired improvement."""
    base = walk_forward_predict(df, baseline_cols, seed)
    treat = walk_forward_predict(df, treatment_cols, seed)
    m = base[["game_id", "y_over"]].merge(
        treat[["game_id", "pred"]].rename(columns={"pred": "pred_treat"}), on="game_id")
    m = base.merge(m[["game_id", "pred_treat"]], on="game_id")

    res = {
        "overall": {
            "baseline": evaluate(m["y_over"], m["pred"]),
            "treatment": evaluate(m["y_over"], m["pred_treat"]),
        },
        "by_season": {},
        "preds": m,
    }
    res["overall"]["delta_logloss"] = (
        res["overall"]["treatment"]["logloss"] - res["overall"]["baseline"]["logloss"])
    res["overall"]["delta_brier"] = (
        res["overall"]["treatment"]["brier"] - res["overall"]["baseline"]["brier"])
    for s, grp in m.groupby("season"):
        res["by_season"][s] = {
            "baseline": evaluate(grp["y_over"], grp["pred"]),
            "treatment": evaluate(grp["y_over"], grp["pred_treat"]),
        }
    return res
