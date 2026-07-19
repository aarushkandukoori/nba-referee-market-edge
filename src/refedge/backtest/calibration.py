"""Calibration / reliability diagram: predicted probability vs. observed frequency.

A model can improve log-loss yet be miscalibrated; for a betting backtest,
calibration is what makes the edge real, so we report it explicitly (binned
reliability curve + expected calibration error).
"""
from __future__ import annotations

import numpy as np
import pandas as pd


def reliability_table(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """Per-bin predicted mean, observed frequency, and count (equal-width bins)."""
    y = np.asarray(y, dtype=float)
    p = np.clip(np.asarray(p, dtype=float), 0, 1)
    bins = np.linspace(0, 1, n_bins + 1)
    idx = np.clip(np.digitize(p, bins) - 1, 0, n_bins - 1)
    rows = []
    for b in range(n_bins):
        m = idx == b
        if not m.any():
            continue
        rows.append({
            "bin_lo": bins[b], "bin_hi": bins[b + 1],
            "pred_mean": float(p[m].mean()),
            "obs_freq": float(y[m].mean()),
            "count": int(m.sum()),
        })
    return pd.DataFrame(rows)


def expected_calibration_error(y: np.ndarray, p: np.ndarray, n_bins: int = 10) -> float:
    t = reliability_table(y, p, n_bins)
    if t.empty:
        return float("nan")
    w = t["count"] / t["count"].sum()
    return float((w * (t["pred_mean"] - t["obs_freq"]).abs()).sum())


def plot_reliability(curves: dict[str, tuple[np.ndarray, np.ndarray]],
                     path, title: str = "Calibration (predicted vs. observed)",
                     n_bins: int = 10) -> None:
    """Save a reliability diagram. ``curves`` maps label -> (y_true, p_pred)."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(6, 6))
    ax.plot([0, 1], [0, 1], "k--", lw=1, label="perfect")
    for label, (y, p) in curves.items():
        t = reliability_table(y, p, n_bins)
        ece = expected_calibration_error(y, p, n_bins)
        ax.plot(t["pred_mean"], t["obs_freq"], "o-", label=f"{label} (ECE={ece:.3f})")
    ax.set_xlabel("Predicted P(over)")
    ax.set_ylabel("Observed frequency of over")
    ax.set_title(title)
    ax.legend(loc="upper left")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)
