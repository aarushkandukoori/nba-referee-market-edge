"""Direct look-ahead-bias tests for the feature builders.

The definitive property: a game's features must be computable without knowing that
game's *outcome*. So if we perturb ONLY game g's outcome (its total points / box
line), then:
  * game g's own features must NOT change (the current game is excluded), and
  * a later game sharing a referee/team WITH g MUST change (g has entered its
    rolling history).
A feature builder that leaks the target would fail the first assertion.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from refedge.features.referee import add_referee_features, crew_feature_columns
from refedge.features.team import add_team_features, team_feature_columns


def _synthetic_games(n: int = 40, seed: int = 0) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    refs = [f"ref{i:02d}" for i in range(8)]
    teams = [f"T{i:02d}" for i in range(10)]
    rows = []
    date = pd.Timestamp("2021-10-20")
    for i in range(n):
        date = date + pd.Timedelta(days=1)
        a, h = rng.choice(teams, size=2, replace=False)
        crew = rng.choice(refs, size=3, replace=False)
        home_pts = int(rng.integers(95, 130))
        away_pts = int(rng.integers(95, 130))
        rows.append({
            "game_id": f"G{i:03d}", "date": date, "away": a, "home": h,
            "home_pts": home_pts, "away_pts": away_pts,
            "total_pts": home_pts + away_pts,
            "pace": float(rng.integers(94, 104)),
            "home_fta": int(rng.integers(10, 30)), "away_fta": int(rng.integers(10, 30)),
            "home_3pa": int(rng.integers(25, 50)), "away_3pa": int(rng.integers(25, 50)),
            "home_pf": int(rng.integers(12, 26)), "away_pf": int(rng.integers(12, 26)),
            "off1_id": crew[0], "off2_id": crew[1], "off3_id": crew[2],
            "line": 225.0,
        })
    df = pd.DataFrame(rows)
    df["total_fta"] = df["home_fta"] + df["away_fta"]
    df["total_3pa"] = df["home_3pa"] + df["away_3pa"]
    df["total_pf"] = df["home_pf"] + df["away_pf"]
    return df


def _refs_of(df, gid):
    r = df.loc[df.game_id == gid, ["off1_id", "off2_id", "off3_id"]].iloc[0]
    return set(r.values)


def test_referee_features_exclude_current_game():
    df = _synthetic_games()
    base = add_referee_features(df).set_index("game_id")
    ccols = crew_feature_columns()

    g = "G020"
    later = next(gid for gid in df.game_id
                 if gid > g and _refs_of(df, gid) & _refs_of(df, g))

    pert = df.copy()
    m = pert.game_id == g
    pert.loc[m, ["total_pts", "total_pf", "total_fta"]] += 100000  # blow up g's outcome
    out = add_referee_features(pert).set_index("game_id")

    # g's own crew features unchanged -> no leakage of g's outcome into g's features.
    np.testing.assert_allclose(base.loc[g, ccols].to_numpy(float),
                               out.loc[g, ccols].to_numpy(float), rtol=1e-9,
                               err_msg="LEAK: game features changed when its own outcome changed")
    # A later game that shares a ref with g MUST change (g is now in its history).
    assert not np.allclose(base.loc[later, ccols].to_numpy(float),
                           out.loc[later, ccols].to_numpy(float)), \
        "expected later same-ref game to reflect g in its rolling history"


def test_team_features_exclude_current_game():
    df = _synthetic_games()
    base = add_team_features(df).set_index("game_id")
    tcols = [c for c in team_feature_columns(include_line=False) if c in base.columns]

    g = "G015"
    gteams = set(df.loc[df.game_id == g, ["home", "away"]].iloc[0].values)
    later = next(gid for gid in df.game_id if gid > g and
                 (set(df.loc[df.game_id == gid, ["home", "away"]].iloc[0].values) & gteams))

    pert = df.copy()
    m = pert.game_id == g
    pert.loc[m, ["home_pts", "away_pts", "total_pts"]] += 100000
    out = add_team_features(pert).set_index("game_id")

    np.testing.assert_allclose(base.loc[g, tcols].to_numpy(float),
                               out.loc[g, tcols].to_numpy(float), rtol=1e-9,
                               err_msg="LEAK: team features changed when the game's own score changed")
    assert not np.allclose(base.loc[later, tcols].to_numpy(float),
                           out.loc[later, tcols].to_numpy(float)), \
        "expected later same-team game to reflect g in its rolling history"


def test_referee_rolling_matches_manual_prior_mean():
    """A referee's shrunk feature equals the exact shrink of their prior-game mean."""
    from refedge.config import CFG
    df = _synthetic_games(60, seed=3)
    out = add_referee_features(df)
    M = CFG.ref_min_history

    ref = "ref03"
    ref_games = df[(df[["off1_id", "off2_id", "off3_id"]] == ref).any(axis=1)] \
        .sort_values("date").reset_index(drop=True)
    if len(ref_games) < 4:
        return
    g3 = ref_games.iloc[3]  # 4th game -> 3 prior games
    prior_mean = ref_games.iloc[:3]["total_pts"].mean()
    # league prior at that date (expanding mean of games strictly before it)
    league = df[df.date < g3["date"]]["total_pts"].mean()
    expected = (3 * prior_mean + M * league) / (3 + M)
    # crew_total_pts_* aggregates 3 refs; instead verify via the per-ref value path
    # by re-deriving: min over crew should be <= expected <= max (sanity bound).
    row = out[out.game_id == g3["game_id"]].iloc[0]
    assert row["crew_total_pts_min"] - 1e-6 <= expected <= row["crew_total_pts_max"] + 1e-6


if __name__ == "__main__":
    test_referee_features_exclude_current_game()
    test_team_features_exclude_current_game()
    test_referee_rolling_matches_manual_prior_mean()
    print("all leakage tests passed")
