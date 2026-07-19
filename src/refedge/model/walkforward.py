"""Season-rolling (walk-forward) validation splits.

This is time series, so we never random-split. We train on an *expanding* window of
whole seasons and test on the next season, rolling forward:

    train {s0..s2} -> test s3
    train {s0..s3} -> test s4
    ...

Whole-season boundaries avoid any within-season temporal bleed, and the expanding
window mirrors how the model would actually be retrained each new season.
"""
from __future__ import annotations

from collections.abc import Iterator

import pandas as pd

from refedge.config import CFG


def season_order(df: pd.DataFrame) -> list[str]:
    # Order by first date seen, so "2018-19" < "2019-20" regardless of string sort.
    return list(df.groupby("season")["date"].min().sort_values().index)


def walk_forward_splits(
    df: pd.DataFrame, min_train_seasons: int | None = None
) -> Iterator[tuple[str, pd.Index, pd.Index]]:
    """Yield (test_season, train_idx, test_idx) for each roll-forward step."""
    k = min_train_seasons or CFG.min_train_seasons
    seasons = season_order(df)
    for i in range(k, len(seasons)):
        train_seasons = seasons[:i]
        test_season = seasons[i]
        train_idx = df.index[df["season"].isin(train_seasons)]
        test_idx = df.index[df["season"] == test_season]
        if len(test_idx) == 0 or len(train_idx) == 0:
            continue
        yield test_season, train_idx, test_idx
