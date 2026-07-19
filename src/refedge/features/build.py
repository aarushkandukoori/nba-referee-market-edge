"""Assemble model-ready frames: join games -> market line -> features -> target.

Two frames, matching the two-layer design:
  * ``build_training_frame`` — layer 1 (2018-19..2022-23): b-ref games joined to the
    SBRO closing total as ``line``; target ``y_over = total_pts > line``.
  * ``build_backtest_frame`` — layer 2 (2025-26): b-ref games joined to Polymarket
    strike-markets; keeps the pre-tip market-implied P(over) for the P&L backtest.

Feature sets:
  * ``FEATURES_BASELINE`` — market line + team/game form, NO referee info.
  * ``FEATURES_TREATMENT`` — baseline + rolling crew features.
The out-of-sample comparison of these two IS the result.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from refedge.config import CFG
from refedge.data import bref, espn, markets, odds
from refedge.features.referee import add_referee_features, crew_feature_columns
from refedge.features.team import add_team_features, team_feature_columns


def _prep_bref_games(seasons: list[str]) -> pd.DataFrame:
    """Assembled b-ref games with canonical team codes and clean numeric fields."""
    from refedge.cache import cached_frame

    frames = []
    for season in seasons:
        def _build(season=season):
            return bref.assemble_games([season])

        g = cached_frame(f"bref_games_{season}", _build, subdir="interim")
        if g.empty:
            continue
        g = g.rename(columns={"away": "away_name", "home": "home_name",
                              "away_code": "away", "home_code": "home"})
        need = ["away", "home", "home_pts", "away_pts", "pace",
                "home_fta", "away_fta", "home_3pa", "away_3pa", "off1_id"]
        g = g.dropna(subset=need).copy()
        g["date"] = pd.to_datetime(g["date"]).dt.normalize()
        g["source"] = "bref"
        frames.append(g)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _prep_espn_games(seasons: list[str]) -> pd.DataFrame:
    """ESPN site-API games (fast fallback for layer-1 seasons while b-ref backfills)."""
    g = espn.build_train_games(seasons)
    if g.empty:
        return g
    need = ["away", "home", "home_pts", "away_pts", "pace",
            "home_fta", "away_fta", "home_3pa", "away_3pa", "off1_id"]
    g = g.dropna(subset=need).copy()
    g["date"] = pd.to_datetime(g["date"]).dt.normalize()
    return g


def _prep_games(seasons: list[str], prefer: str = "auto") -> pd.DataFrame:
    """Load games for ``seasons``.

    ``prefer``:
      * ``bref`` — basketball-reference only
      * ``espn`` — ESPN only
      * ``auto`` — use b-ref when a season is substantially cached (>=80% of
        schedule), otherwise ESPN. Lets the study run before the long b-ref
        scrape finishes, without mixing sources *within* a season.
    """
    if prefer == "espn":
        return _prep_espn_games(seasons)
    if prefer == "bref":
        return _prep_bref_games(seasons)

    frames = []
    for season in seasons:
        try:
            sched = bref.list_games(season)
            n_sched = len(sched)
            n_cached = int(sum(bref._html_cached(g) for g in sched["game_id"])) if n_sched else 0
        except Exception:  # noqa: BLE001
            n_sched, n_cached = 0, 0
        if n_sched and n_cached / n_sched >= 0.80:
            print(f"[build] {season}: b-ref ({n_cached}/{n_sched} cached)", flush=True)
            part = _prep_bref_games([season])
        else:
            print(f"[build] {season}: ESPN fallback "
                  f"(b-ref cache {n_cached}/{n_sched or '?'})", flush=True)
            part = _prep_espn_games([season])
        if not part.empty:
            frames.append(part)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def _finalize(df: pd.DataFrame) -> pd.DataFrame:
    """Apply feature builders and the over/under target once ``line`` is present."""
    df = df.copy()
    if "total_tech" not in df.columns:
        df["total_tech"] = 0.0
    else:
        df["total_tech"] = df["total_tech"].fillna(0.0)
    df = add_team_features(df)
    df = add_referee_features(df)
    df["y_over"] = (df["total_pts"] > df["line"]).astype(int)
    # Drop the rare exact push (integer line == integer total).
    df = df[df["total_pts"] != df["line"]].reset_index(drop=True)
    return df


def build_training_frame(seasons: list[str] | None = None,
                         prefer: str = "espn") -> pd.DataFrame:
    """Layer-1 frame: prefer ESPN for speed/completeness; regular season only."""
    seasons = seasons or list(CFG.train_seasons)
    g = _prep_games(seasons, prefer=prefer)
    if g.empty:
        return g
    # Regular season only (ESPN season_type=2). Playoff officiating differs.
    if "season_type" in g.columns:
        before = len(g)
        g = g[g["season_type"] == 2].copy()
        print(f"[build] regular-season filter: {before} → {len(g)}", flush=True)
    o = odds.build_closing_totals(seasons)[["date", "away", "home", "close_total"]]
    o["date"] = pd.to_datetime(o["date"]).dt.normalize()
    df = g.merge(o, on=["date", "away", "home"], how="inner")
    df = df.rename(columns={"close_total": "line"}).dropna(subset=["line"])
    return _finalize(df)


def build_backtest_frame(season: str | None = None,
                         prefer: str = "espn",
                         history_seasons: list[str] | None = None,
                         ) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (per-game featured frame, strike-level market table) for the backtest.

    The per-game frame uses each game's *primary* line (the strike whose pre-tip
    price is nearest 0.5 — the market's de-facto total) so team/crew features and
    a single over/under label are well-defined. The strike table keeps every
    O/U contract with its pre-tip implied prob for the P&L simulation.

    Rolling ref/team features are computed on ``history_seasons + [season]`` so
    early-season 2025-26 games are not cold-started, then rows are filtered to
    ``season`` only before joining markets.
    """
    season = season or CFG.backtest_season
    # Bridge the gap between SBRO odds coverage (ends 2022-23) and Polymarket
    # (2025-26) so rolling ref features have continuous history.
    history_seasons = history_seasons or ["2022-23", "2023-24", "2024-25"]
    all_seasons = list(dict.fromkeys([*history_seasons, season]))  # preserve order, uniq

    g_all = _prep_games(all_seasons, prefer=prefer)
    if g_all.empty:
        return pd.DataFrame(), markets.build_market_totals()

    # Features only — no placeholder line that would drop games totaling 225.
    g_all = g_all.copy()
    if "total_tech" not in g_all.columns:
        g_all["total_tech"] = 0.0
    else:
        g_all["total_tech"] = g_all["total_tech"].fillna(0.0)
    featured = add_team_features(g_all)
    featured = add_referee_features(featured)
    g = featured[featured["season"] == season].copy()

    pm = markets.build_market_totals()  # cached full-season strike table w/ prices
    if g.empty or pm.empty:
        return pd.DataFrame(), pm

    pm = pm.copy()
    pm["game_date"] = pd.to_datetime(pm["game_date"]).dt.normalize()
    pm = pm.dropna(subset=["p_over_tip"])
    # Primary line per game = strike with implied prob closest to 0.5.
    pm["dist_half"] = (pm["p_over_tip"] - 0.5).abs()
    primary = (pm.sort_values("dist_half")
                 .groupby(["game_date", "away", "home"], as_index=False).first())
    primary = primary.rename(columns={"game_date": "date", "line": "pm_line",
                                      "p_over_tip": "pm_p_over", "over_won": "pm_over_won"})[
        ["date", "away", "home", "pm_line", "pm_p_over", "pm_over_won"]]

    df = g.merge(primary, on=["date", "away", "home"], how="inner")
    df = df.rename(columns={"pm_line": "line", "pm_p_over": "p_over_tip",
                            "pm_over_won": "over_won"})
    if "team_expected_total" in df.columns:
        df["team_total_minus_line"] = df["team_expected_total"] - df["line"]
    df["y_over"] = (df["total_pts"] > df["line"]).astype(int)
    df = df[df["total_pts"] != df["line"]].reset_index(drop=True)

    # Strike-level table joined to game features for P&L (feature row per contract).
    feat_cols = [c for c in df.columns if c not in
                 ("line", "p_over_tip", "over_won", "y_over")]
    strike = pm.rename(columns={"game_date": "date"}).merge(
        df[feat_cols], on=["date", "away", "home"], how="inner", suffixes=("", "_g"))
    return df, strike


# --- feature sets ---------------------------------------------------------
FEATURES_BASELINE = team_feature_columns(include_line=True)
FEATURES_TREATMENT = FEATURES_BASELINE + crew_feature_columns()


def make_xy(df: pd.DataFrame, feature_cols: list[str]):
    X = df[feature_cols].astype(float).replace([np.inf, -np.inf], np.nan)
    y = df["y_over"].astype(int)
    return X, y
