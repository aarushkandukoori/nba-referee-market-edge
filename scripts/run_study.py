"""End-to-end study runner: features → walk-forward → permutation → Polymarket backtest.

Produces:
  * ``reports/findings.md`` — honest summary (null is a valid outcome)
  * ``reports/metrics.json`` — machine-readable metrics
  * ``reports/figures/calibration.png`` — reliability diagram
  * ``reports/figures/equity.png`` — fractional-Kelly equity curve
  * parquet caches under ``data/features/`` and ``data/interim/``

Usage:
    python scripts/run_study.py
    python scripts/run_study.py --n-perms 20 --prefer-train espn --prefer-backtest bref
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

from refedge.config import CFG, FEATURES, FIGURES, INTERIM, REPORTS
from refedge.features.build import (
    FEATURES_BASELINE,
    FEATURES_TREATMENT,
    build_backtest_frame,
    build_training_frame,
)
from refedge.model.permutation import permutation_test
from refedge.model.train import compare_models, evaluate, walk_forward_predict
from refedge.backtest.kelly import simulate
from refedge.backtest.calibration import plot_reliability, expected_calibration_error
from refedge.backtest.metrics import max_drawdown


def _sample_size_caveats(df: pd.DataFrame) -> dict:
    """Flag thin referee / crew histories — the main statistical power caveat."""
    refs = pd.concat([
        df[["date", "off1_id"]].rename(columns={"off1_id": "ref_id"}),
        df[["date", "off2_id"]].rename(columns={"off2_id": "ref_id"}),
        df[["date", "off3_id"]].rename(columns={"off3_id": "ref_id"}),
    ]).dropna()
    games_per_ref = refs.groupby("ref_id").size()
    # Exact 3-man crew recurrence (ignore missing slots)
    def _crew_key(row) -> str:
        ids = [str(x) for x in row if pd.notna(x) and str(x) not in ("", "nan", "None")]
        return "|".join(sorted(ids)) if ids else "unknown"

    crews = df.copy()
    crews["crew_key"] = df[["off1_id", "off2_id", "off3_id"]].apply(_crew_key, axis=1)
    crew_counts = crews.groupby("crew_key").size()
    thin = int((df["crew_min_experience"] < CFG.ref_min_history).sum()) if "crew_min_experience" in df else None
    return {
        "n_games": int(len(df)),
        "n_seasons": int(df["season"].nunique()) if "season" in df else None,
        "n_unique_refs": int(games_per_ref.index.nunique()),
        "ref_games_median": float(games_per_ref.median()),
        "ref_games_p10": float(games_per_ref.quantile(0.10)),
        "ref_games_p90": float(games_per_ref.quantile(0.90)),
        "frac_refs_under_40_games": float((games_per_ref < 40).mean()),
        "n_unique_crews": int(crew_counts.index.nunique()),
        "frac_crews_seen_once": float((crew_counts == 1).mean()),
        "frac_games_thin_crew_history": float(thin / len(df)) if thin is not None else None,
        "warning": (
            "Crew-level samples are thin: most exact 3-man crews appear once. "
            "Trust individual-ref shrunk features, not crew interactions."
            if (crew_counts == 1).mean() > 0.7 else "Crew recurrence is moderate."
        ),
    }


def _plot_equity(equity: np.ndarray, path: Path, title: str) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(8, 4))
    ax.plot(equity, lw=1.5)
    ax.axhline(1.0, color="k", lw=0.8, ls="--")
    ax.set_title(title)
    ax.set_xlabel("Bet index (incl. skipped)")
    ax.set_ylabel("Bankroll (start=1)")
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


def _write_findings(path: Path, payload: dict) -> None:
    o = payload["overall"]
    caveats = payload["sample_size"]
    perm = payload["permutation"]
    bt = payload.get("backtest", {})
    delta_ll = o["delta_logloss"]
    delta_br = o["delta_brier"]
    helped = delta_ll < 0  # lower log-loss is better

    lines = [
        "# Findings — NBA referee-crew edge on totals",
        "",
        "## Headline (the comparison IS the result)",
        "",
        f"- **Baseline** OOS log-loss `{o['baseline']['logloss']:.4f}`, "
        f"Brier `{o['baseline']['brier']:.4f}` (n={o['baseline']['n']})",
        f"- **Treatment** (+ crew features) OOS log-loss `{o['treatment']['logloss']:.4f}`, "
        f"Brier `{o['treatment']['brier']:.4f}`",
        f"- **Δ log-loss (treatment − baseline)** = `{delta_ll:+.5f}` "
        f"({'treatment better' if helped else 'treatment worse / no gain'})",
        f"- **Δ Brier** = `{delta_br:+.5f}`",
        "",
        "## Permutation test",
        "",
        f"- Real treatment-over-baseline log-loss improvement: `{perm['real_improvement']:+.5f}`",
        f"- Null mean / std (crew labels shuffled): `{perm['null_mean']:+.5f}` / `{perm['null_std']:.5f}`",
        f"- Permutation p-value: `{perm['p_value']:.3f}` "
        f"(n_perms={perm['n_perms']})",
        "",
        ("Crew features look like noise under permutation — do **not** treat any "
         "in-sample edge as real."
         if perm["p_value"] > 0.1 else
         "Real improvement sits in the right tail of the null — still report with "
         "sample-size caveats below."),
        "",
        "## Sample-size caveats",
        "",
        f"- Games in statistical frame: **{caveats['n_games']}** "
        f"across {caveats['n_seasons']} seasons",
        f"- Unique referees: {caveats['n_unique_refs']} "
        f"(median games/ref={caveats['ref_games_median']:.0f}, "
        f"p10={caveats['ref_games_p10']:.0f})",
        f"- Unique exact 3-man crews: {caveats['n_unique_crews']} "
        f"({100*caveats['frac_crews_seen_once']:.0f}% seen only once)",
        f"- Games with thin crew history (<{CFG.ref_min_history} prior games/ref): "
        f"{100*(caveats['frac_games_thin_crew_history'] or 0):.0f}%",
        f"- {caveats['warning']}",
        "",
        "## Polymarket backtest (single season — underpowered)",
        "",
    ]
    if bt:
        s = bt["summary"]
        lines += [
            f"- Season: `{payload.get('backtest_season')}`",
            f"- Candidates / bets: {s.get('n_candidates')} / {s.get('n_bets')}",
            f"- Total return: `{100*s.get('total_return', 0):+.1f}%`",
            f"- Hit rate: `{100*s.get('hit_rate', 0):.1f}%`",
            f"- Sharpe-like (per-bet, ann.): `{s.get('sharpe_like', 0):.2f}`",
            f"- Max drawdown: `{100*s.get('max_drawdown', 0):.1f}%`",
            f"- ECE (treatment): `{bt.get('ece', float('nan')):.3f}`",
            "",
            "This layer is **one season of thin-liquidity markets**. Even a positive "
            "P&L here is not confirmatory without the layer-1 statistical result "
            "and a non-null permutation test.",
        ]
    else:
        lines.append("_Backtest frame empty — check Polymarket ↔ games join._")

    lines += [
        "",
        "## Method notes",
        "",
        "- Walk-forward by season; no random splits.",
        "- Referee features are rolling + shrunk; current game excluded.",
        "- Market closing total is a control feature in both models.",
        f"- Train source preference: `{payload.get('prefer_train')}`; "
        f"backtest: `{payload.get('prefer_backtest')}`.",
        "",
    ]
    path.write_text("\n".join(lines))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-perms", type=int, default=20)
    ap.add_argument("--prefer-train", default="espn",
                    choices=["auto", "espn", "bref"])
    ap.add_argument("--prefer-backtest", default="espn",
                    choices=["auto", "espn", "bref"])
    ap.add_argument("--skip-backtest", action="store_true")
    ap.add_argument("--skip-permutation", action="store_true")
    args = ap.parse_args()

    REPORTS.mkdir(parents=True, exist_ok=True)
    FIGURES.mkdir(parents=True, exist_ok=True)
    FEATURES.mkdir(parents=True, exist_ok=True)
    INTERIM.mkdir(parents=True, exist_ok=True)

    print("[study] building training frame…", flush=True)
    train = build_training_frame(prefer=args.prefer_train)
    if train.empty:
        raise SystemExit("training frame empty — check odds join / game sources")
    train.to_parquet(FEATURES / "train_frame.parquet", index=False)
    print(f"[study] train games={len(train)} seasons={sorted(train.season.unique())}",
          flush=True)

    print("[study] walk-forward baseline vs treatment…", flush=True)
    cmp = compare_models(train, FEATURES_BASELINE, FEATURES_TREATMENT)
    cmp["preds"].to_parquet(FEATURES / "oos_preds.parquet", index=False)
    print("[study] overall:", json.dumps(cmp["overall"], indent=2), flush=True)

    caveats = _sample_size_caveats(train)
    print("[study] sample-size:", json.dumps(caveats, indent=2), flush=True)

    if args.skip_permutation:
        perm = {"real_improvement": None, "p_value": None, "n_perms": 0,
                "null_mean": None, "null_std": None, "null": []}
    else:
        print(f"[study] permutation test (n={args.n_perms})…", flush=True)
        perm = permutation_test(train, FEATURES_BASELINE, FEATURES_TREATMENT,
                                n_perms=args.n_perms)
        print("[study] permutation:",
              {k: perm[k] for k in ("real_improvement", "null_mean", "p_value")},
              flush=True)

    backtest_payload = {}
    if not args.skip_backtest:
        print("[study] building Polymarket backtest frame…", flush=True)
        bt_games, bt_strikes = build_backtest_frame(prefer=args.prefer_backtest)
        if bt_games.empty:
            print("[study] WARN: backtest games empty", flush=True)
        else:
            # Fit on all train seasons, predict 2025-26 (single holdout season).
            # Use treatment + baseline; for P&L we need model probs on bt_games.
            # Retrain on full train frame (no peek at 2025-26).
            from refedge.model.train import _fit_predict
            from refedge.features.build import make_xy

            Xtr_b, ytr = make_xy(train, FEATURES_BASELINE)
            Xtr_t, _ = make_xy(train, FEATURES_TREATMENT)
            Xte_b, yte = make_xy(bt_games, FEATURES_BASELINE)
            Xte_t, _ = make_xy(bt_games, FEATURES_TREATMENT)
            p_b = _fit_predict(Xtr_b, ytr, Xte_b, CFG.random_state)
            p_t = _fit_predict(Xtr_t, ytr, Xte_t, CFG.random_state)
            bt_games = bt_games.copy()
            bt_games["pred_base"] = p_b
            bt_games["pred"] = p_t
            bt_games.to_parquet(FEATURES / "backtest_games.parquet", index=False)

            # Attach treatment preds onto strike table via game_id.
            strikes = bt_strikes.merge(
                bt_games[["game_id", "pred", "pred_base"]],
                on="game_id", how="inner")
            # Only bet the primary-ish strikes near 50¢ to avoid deep OTM junk.
            strikes = strikes[(strikes["p_over_tip"] > 0.25) &
                              (strikes["p_over_tip"] < 0.75)].copy()
            sim = simulate(strikes, p_col="pred", q_col="p_over_tip",
                           outcome_col="over_won")
            ece = expected_calibration_error(bt_games["y_over"].to_numpy(),
                                             bt_games["pred"].to_numpy())
            plot_reliability(
                {
                    "baseline": (bt_games["y_over"].to_numpy(), bt_games["pred_base"].to_numpy()),
                    "treatment": (bt_games["y_over"].to_numpy(), bt_games["pred"].to_numpy()),
                },
                FIGURES / "calibration.png",
                title="2025-26 Polymarket holdout calibration",
            )
            _plot_equity(sim["equity"], FIGURES / "equity.png",
                         "Fractional-Kelly equity (Polymarket 2025-26)")
            sim["log"].to_parquet(FEATURES / "backtest_bets.parquet", index=False)
            backtest_payload = {
                "summary": sim["summary"],
                "ece": ece,
                "holdout_metrics": {
                    "baseline": evaluate(bt_games["y_over"], bt_games["pred_base"]),
                    "treatment": evaluate(bt_games["y_over"], bt_games["pred"]),
                },
            }
            print("[study] backtest:", json.dumps(backtest_payload["summary"], indent=2),
                  flush=True)

    payload = {
        "overall": cmp["overall"],
        "by_season": cmp["by_season"],
        "permutation": {k: v for k, v in perm.items() if k != "null"},
        "permutation_null": perm.get("null", []),
        "sample_size": caveats,
        "backtest": backtest_payload,
        "backtest_season": CFG.backtest_season,
        "prefer_train": args.prefer_train,
        "prefer_backtest": args.prefer_backtest,
        "feature_counts": {
            "baseline": len(FEATURES_BASELINE),
            "treatment": len(FEATURES_TREATMENT),
        },
    }
    (REPORTS / "metrics.json").write_text(json.dumps(payload, indent=2, default=str))
    _write_findings(REPORTS / "findings.md", payload)
    print(f"[study] wrote {REPORTS / 'findings.md'}", flush=True)


if __name__ == "__main__":
    main()
