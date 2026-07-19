"""ESPN site-API fallback for historical games + officials.

Used for the layer-1 statistical seasons (2018-19..2022-23) when basketball-
reference HTML is still backfilling. ESPN's public site API is reachable from
this environment and returns the 3-man crew plus team box lines (PTS/FTA/3PA/PF).

Pace is not published on the ESPN summary endpoint, so we estimate possessions
from the standard box-score formula and convert to a per-48 pace estimate. That
is good enough as a rolling team/ref tendency feature; the Polymarket backtest
season still prefers b-ref (which has true pace) once its HTML cache is complete.

Official IDs are slugified display names (stable across seasons). Everything is
parquet-cached; re-runs never re-hit the API for games we already have.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from pathlib import Path

import pandas as pd

from refedge.cache import cached_frame, path_for
from refedge.config import RAW
from refedge.data.teams import to_bref

ESPN = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba"
SDV_OFF = (
    "https://github.com/sportsdataverse/sportsdataverse-data/releases/download/"
    "espn_nba_officials/officials_{year}.parquet"
)

_JSON_DIR = RAW / "espn_json"
_JSON_DIR.mkdir(parents=True, exist_ok=True)

_MIN_GAP_S = 0.25  # ESPN is far more tolerant than b-ref
_last_ts = [0.0]


def _throttle() -> None:
    dt = time.time() - _last_ts[0]
    if dt < _MIN_GAP_S:
        time.sleep(_MIN_GAP_S - dt)
    _last_ts[0] = time.time()


def _get_json(url: str, tries: int = 4):
    last = None
    for i in range(tries):
        _throttle()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "refedge/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    print(f"[espn] GET failed: {url[:120]} :: {last}")
    return None


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", (name or "").lower())


def _split_made_att(val: str | None) -> tuple[float | None, float | None]:
    if not val or "-" not in str(val):
        return None, None
    a, b = str(val).split("-", 1)
    try:
        return float(a), float(b)
    except ValueError:
        return None, None


def _stat_map(team_block: dict) -> dict:
    return {s.get("name"): s.get("displayValue") for s in (team_block.get("statistics") or [])}


def _end_year(season: str) -> int:
    return int(season[:4]) + 1


def load_officials_table(season: str) -> pd.DataFrame:
    """Sportsdataverse ESPN officials for one season (keyed by ESPN game_id)."""
    year = _end_year(season)

    def _build():
        url = SDV_OFF.format(year=year)
        path = RAW / f"sdv_officials_{year}.parquet"
        if not path.exists():
            data = urllib.request.urlopen(url, timeout=60).read()
            path.write_bytes(data)
        return pd.read_parquet(path)

    return cached_frame(f"sdv_officials_{season}", _build, subdir="raw")


def _cached_summary(game_id: int | str) -> dict | None:
    fp = _JSON_DIR / f"{game_id}.json.gz"
    import gzip

    if fp.exists():
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            return json.load(fh)
    raw = _get_json(f"{ESPN}/summary?event={game_id}")
    if raw is None:
        return None
    with gzip.open(fp, "wt", encoding="utf-8") as fh:
        json.dump(raw, fh)
    return raw


def parse_summary(raw: dict, game_id: int | str) -> dict | None:
    """Parse one ESPN summary into a b-ref-compatible games row."""
    header = raw.get("header") or {}
    comps = header.get("competitions") or []
    if not comps:
        return None
    comp = comps[0]
    status = ((comp.get("status") or {}).get("type") or {}).get("name")
    if status and status not in ("STATUS_FINAL", "STATUS_FULL_TIME"):
        # still keep finals that lack the exact name if scores exist
        pass
    competitors = {c.get("homeAway"): c for c in comp.get("competitors") or []}
    if "home" not in competitors or "away" not in competitors:
        return None

    def team_code(c):
        return to_bref((c.get("team") or {}).get("abbreviation") or "")

    home_c, away_c = competitors["home"], competitors["away"]
    home, away = team_code(home_c), team_code(away_c)
    try:
        home_pts = float(home_c.get("score"))
        away_pts = float(away_c.get("score"))
    except (TypeError, ValueError):
        return None

    # Officials: prefer gameInfo; fall back to empty.
    offs = (raw.get("gameInfo") or {}).get("officials") or []
    offs = sorted(offs, key=lambda o: o.get("order") or 0)
    off_ids, off_names = [], []
    for o in offs[:3]:
        name = o.get("displayName") or o.get("fullName") or ""
        off_names.append(name)
        off_ids.append(_slug(name) or None)
    while len(off_ids) < 3:
        off_ids.append(None)
        off_names.append(None)

    # Team box lines from boxscore.teams
    box_teams = {(t.get("team") or {}).get("abbreviation"): t
                 for t in ((raw.get("boxscore") or {}).get("teams") or [])}
    # Map ESPN abbrev -> our codes for lookup
    side_stats = {"home": {}, "away": {}}
    for side, comp_c in (("home", home_c), ("away", away_c)):
        abbr = (comp_c.get("team") or {}).get("abbreviation")
        block = box_teams.get(abbr) or {}
        sm = _stat_map(block)
        _, fga = _split_made_att(sm.get("fieldGoalsMade-fieldGoalsAttempted"))
        _, tpa = _split_made_att(sm.get("threePointFieldGoalsMade-threePointFieldGoalsAttempted"))
        _, fta = _split_made_att(sm.get("freeThrowsMade-freeThrowsAttempted"))
        try:
            orb = float(sm.get("offensiveRebounds") or 0)
        except ValueError:
            orb = 0.0
        try:
            tov = float(sm.get("totalTurnovers") or sm.get("turnovers") or 0)
        except ValueError:
            tov = 0.0
        try:
            pf = float(sm.get("fouls") or 0)
        except ValueError:
            pf = None
        try:
            tech = float(sm.get("totalTechnicalFouls") or sm.get("technicalFouls") or 0)
        except ValueError:
            tech = 0.0
        side_stats[side] = {
            "fta": fta, "tpa": tpa, "fga": fga, "orb": orb, "tov": tov,
            "pf": pf, "tech": tech,
        }

    # Estimated possessions / pace (per team, then average).
    def poss(s):
        fga, orb, tov, fta = s.get("fga"), s.get("orb"), s.get("tov"), s.get("fta")
        if None in (fga, fta):
            return None
        return (fga - (orb or 0) + (tov or 0) + 0.44 * fta)

    ph, pa = poss(side_stats["home"]), poss(side_stats["away"])
    if ph is not None and pa is not None:
        # Regulation minutes = 48; OT not modelled precisely — fine for rolling features.
        pace = 0.5 * (ph + pa)
    else:
        pace = None

    # ESPN tip timestamps are UTC; NBA "game date" is the US/Eastern calendar date
    # (opening night 2018 tip `2018-10-17T00:00Z` is still 2018-10-16 ET).
    tip = comp.get("date")
    if tip:
        ts = pd.to_datetime(tip, utc=True).tz_convert("America/New_York")
        date = ts.normalize().tz_localize(None)
    else:
        date = None

    # season.type: 2 = regular season, 3 = postseason
    season_meta = header.get("season") or {}
    season_type = int(season_meta.get("type") or 0)

    return {
        "game_id": f"espn_{game_id}",
        "espn_game_id": int(game_id),
        "date": date,
        "away": away,
        "home": home,
        "away_pts": away_pts,
        "home_pts": home_pts,
        "pace": pace,
        "away_fta": side_stats["away"].get("fta"),
        "home_fta": side_stats["home"].get("fta"),
        "away_3pa": side_stats["away"].get("tpa"),
        "home_3pa": side_stats["home"].get("tpa"),
        "away_pf": side_stats["away"].get("pf"),
        "home_pf": side_stats["home"].get("pf"),
        "total_tech": (side_stats["away"].get("tech") or 0) + (side_stats["home"].get("tech") or 0),
        "off1_id": off_ids[0], "off1_name": off_names[0],
        "off2_id": off_ids[1], "off2_name": off_names[1],
        "off3_id": off_ids[2], "off3_name": off_names[2],
        "n_officials": sum(1 for x in off_ids if x),
        "season_type": season_type,  # 2=reg, 3=post
        "source": "espn",
    }


def build_season_games(season: str, force: bool = False) -> pd.DataFrame:
    """All final games for ``season`` with officials + box features (cached)."""

    def _build():
        offs = load_officials_table(season)
        gids = sorted(offs["game_id"].unique().tolist())
        # Prefer officials names from the sportsdataverse table when summary lacks them.
        off_by_game = {
            int(gid): (grp.sort_values("official_order")
                       .assign(slug=lambda d: d["official_display_name"].map(_slug)))
            for gid, grp in offs.groupby("game_id")
        }
        rows = []
        n = len(gids)
        for i, gid in enumerate(gids):
            raw = _cached_summary(gid)
            if raw is None:
                continue
            rec = parse_summary(raw, gid)
            if rec is None:
                continue
            # Fill missing officials from SDV table.
            if rec["n_officials"] < 3 and int(gid) in off_by_game:
                grp = off_by_game[int(gid)]
                for j, r in enumerate(grp.itertuples(index=False)):
                    if j >= 3:
                        break
                    if not rec.get(f"off{j+1}_id"):
                        rec[f"off{j+1}_id"] = r.slug
                        rec[f"off{j+1}_name"] = r.official_display_name
                rec["n_officials"] = sum(1 for k in (1, 2, 3) if rec.get(f"off{k}_id"))
            rec["season"] = season
            rows.append(rec)
            if i % 100 == 0 or i == n - 1:
                print(f"[espn] {season} summaries {i + 1}/{n}", flush=True)
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["total_pts"] = df["away_pts"] + df["home_pts"]
        df["total_fta"] = df["away_fta"] + df["home_fta"]
        df["total_3pa"] = df["away_3pa"] + df["home_3pa"]
        df["total_pf"] = df["away_pf"] + df["home_pf"]
        return df.sort_values("date").reset_index(drop=True)

    return cached_frame(f"espn_games_{season}", _build, subdir="interim", force=force)


def build_train_games(seasons: list[str], force: bool = False) -> pd.DataFrame:
    frames = [build_season_games(s, force=force) for s in seasons]
    frames = [f for f in frames if not f.empty]
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
