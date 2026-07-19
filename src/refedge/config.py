"""Central configuration: paths, seasons, and knobs shared across the pipeline.

Kept deliberately small and import-light so every module can `from refedge.config
import CFG` without side effects.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Repo root = two levels up from this file (src/refedge/config.py -> repo root)
ROOT = Path(__file__).resolve().parents[2]

DATA = ROOT / "data"
RAW = DATA / "raw"            # untouched API/scrape pulls, cached as parquet
INTERIM = DATA / "interim"   # cleaned/joined intermediate tables
FEATURES = DATA / "features"  # model-ready feature matrices
REPORTS = ROOT / "reports"
FIGURES = REPORTS / "figures"

for _p in (RAW, INTERIM, FEATURES, REPORTS, FIGURES):
    _p.mkdir(parents=True, exist_ok=True)


@dataclass(frozen=True)
class Config:
    # --- Two-layer season plan (dictated by data availability, see docs/DATA_SOURCES.md) ---
    # Layer 1 (statistical test): seasons with BOTH b-ref box+officials AND a Vegas
    # closing total (sportsbookreviewsonline covers through 2022-23).
    train_seasons: tuple[str, ...] = (
        "2018-19", "2019-20", "2020-21", "2021-22", "2022-23",
    )
    # Layer 2 (tradeable backtest): the only season with Polymarket NBA game totals.
    backtest_season: str = "2025-26"

    @property
    def seasons(self) -> tuple[str, ...]:
        """All seasons we need b-ref data for (train + backtest)."""
        return (*self.train_seasons, self.backtest_season)

    season_type: str = "Regular Season"

    # Walk-forward validation: first `min_train_seasons` are the initial training
    # block; we then test one season at a time, rolling forward.
    min_train_seasons: int = 3

    # Rolling window (in prior games) for referee/team form features. Rolling —
    # NOT season averages — so a game is only ever described by data strictly
    # before it. See features/referee.py.
    ref_roll_games: int = 40      # ~ two-thirds of a ref's season
    team_roll_games: int = 20

    # Minimum prior games a referee must have before we trust their rolling stats;
    # below this we fall back to the league/crew prior (shrinkage).
    ref_min_history: int = 15

    # Market / backtest
    platform: str = "polymarket"  # "polymarket" | "kalshi" — set after recon
    kelly_fraction: float = 0.25  # fractional Kelly
    # Polymarket: no explicit trading fee; cost is spread. Kalshi: fee below.
    kalshi_fee_coeff: float = 0.07  # fee = ceil(0.07 * C * P * (1-P)) cents/contract

    random_state: int = 20260714  # fixed seed; walk-forward is deterministic anyway

    tags: dict = field(default_factory=dict)


CFG = Config()
