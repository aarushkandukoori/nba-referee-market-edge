"""Leakage-safe TEAM/GAME features + the market line as a control.

For each team we roll offensive/defensive form and pace over that team's PRIOR
games only (shifted so the current game is excluded), then attach the home and
away team's form to each game. Rest days / back-to-back come from each team's own
schedule gaps.

The **closing total (``line``) is included as a control feature** so the model's
job is to find *incremental* signal over the market, not to re-predict the total
from scratch. This is central to the honest framing: baseline vs. treatment both
see the line; only treatment additionally sees the referee crew.
"""
from __future__ import annotations

import pandas as pd

from refedge.config import CFG

_TEAM_ROLL_STATS = ["pts_for", "pts_against", "fta", "tpa", "pace"]


def _team_long(games: pd.DataFrame) -> pd.DataFrame:
    """One row per (team, game) with that team's own box line + pace."""
    home = pd.DataFrame({
        "game_id": games["game_id"], "date": games["date"], "team": games["home"],
        "is_home": 1, "pts_for": games["home_pts"], "pts_against": games["away_pts"],
        "fta": games["home_fta"], "tpa": games["home_3pa"], "pace": games["pace"],
    })
    away = pd.DataFrame({
        "game_id": games["game_id"], "date": games["date"], "team": games["away"],
        "is_home": 0, "pts_for": games["away_pts"], "pts_against": games["home_pts"],
        "fta": games["away_fta"], "tpa": games["away_3pa"], "pace": games["pace"],
    })
    return pd.concat([home, away], ignore_index=True)


def add_team_features(games: pd.DataFrame, roll: int | None = None) -> pd.DataFrame:
    """Add home_/away_ rolling form, rest days, and derived total proxies."""
    roll = roll or CFG.team_roll_games
    df = games.sort_values("date").reset_index(drop=True).copy()

    long = _team_long(df).sort_values(["team", "date", "game_id"]).reset_index(drop=True)

    def _prior_roll(s: pd.Series) -> pd.Series:
        return s.shift(1).rolling(roll, min_periods=1).mean()

    for stat in _TEAM_ROLL_STATS:
        long[f"roll_{stat}"] = long.groupby("team")[stat].transform(_prior_roll)

    # Rest days from each team's own previous game (leakage-safe: uses only past dates).
    long["prev_date"] = long.groupby("team")["date"].shift(1)
    long["rest_days"] = (long["date"] - long["prev_date"]).dt.days
    long["is_b2b"] = (long["rest_days"] == 1).astype("float")
    long["rest_days"] = long["rest_days"].clip(upper=7)  # cap long layoffs/season starts
    long["n_prior_team"] = long.groupby("team").cumcount()

    keep = [f"roll_{s}" for s in _TEAM_ROLL_STATS] + ["rest_days", "is_b2b", "n_prior_team"]
    hcols = {c: f"home_{c}" for c in keep}
    acols = {c: f"away_{c}" for c in keep}

    home = long[long.is_home == 1][["game_id"] + keep].rename(columns=hcols)
    away = long[long.is_home == 0][["game_id"] + keep].rename(columns=acols)
    df = df.merge(home, on="game_id", how="left").merge(away, on="game_id", how="left")

    # Derived, market-agnostic total proxies (pure team form, no leakage).
    df["team_pace_sum"] = df["home_roll_pace"] + df["away_roll_pace"]
    df["team_expected_total"] = (
        df["home_roll_pts_for"] + df["away_roll_pts_against"]
        + df["away_roll_pts_for"] + df["home_roll_pts_against"]
    ) / 2.0
    df["team_fta_sum"] = df["home_roll_fta"] + df["away_roll_fta"]
    df["team_tpa_sum"] = df["home_roll_tpa"] + df["away_roll_tpa"]
    # How far the team-form total estimate sits from the market line (edge proxy).
    if "line" in df.columns:
        df["team_total_minus_line"] = df["team_expected_total"] - df["line"]
    return df


def team_feature_columns(include_line: bool = True) -> list[str]:
    cols = []
    for side in ("home", "away"):
        cols += [f"{side}_roll_{s}" for s in _TEAM_ROLL_STATS]
        cols += [f"{side}_rest_days", f"{side}_is_b2b", f"{side}_n_prior_team"]
    cols += ["team_pace_sum", "team_expected_total", "team_fta_sum", "team_tpa_sum"]
    if include_line:
        cols += ["line", "team_total_minus_line"]
    return cols
