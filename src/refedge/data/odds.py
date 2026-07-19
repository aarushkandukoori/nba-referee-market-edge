"""Historical Vegas closing totals from sportsbookreviewsonline (SBRO).

This is the **market benchmark for the layer-1 statistical test** (seasons before
prediction markets existed). SBRO publishes one HTML table per season, two rows
per game (V = visitor, H = home), columns:

    Date, Rot, VH, Team, 1st, 2nd, 3rd, 4th, Final, Open, Close, ML, 2H

The messy part: the ``Open``/``Close`` columns hold BOTH the point spread and the
game total, split across the two rows. NBA totals are ~180–260 and spreads are
~0–20, so we disambiguate by magnitude: **the Close value > 100 is the total**,
the other is the spread. 'pk'/'NL'/blank are treated as missing.

Coverage: through the 2022-23 season (no newer seasons published).
"""
from __future__ import annotations

import html as _html
import re

import pandas as pd

from refedge.cache import cached_frame
from refedge.data.bref import _cached_html  # reuse the throttled/gzip HTML cache
from refedge.data.teams import name_to_bref

_BASE = "https://www.sportsbookreviewsonline.com/scoresoddsarchives"
_COLS = ["Date", "Rot", "VH", "Team", "1st", "2nd", "3rd", "4th",
         "Final", "Open", "Close", "ML", "2H"]


def _num(x):
    x = str(x).strip().lower()
    if x in ("", "pk", "nl", "-", "nan"):
        return None
    try:
        return float(x)
    except ValueError:
        return None


def _mmdd_to_date(mmdd: str, start_year: int, end_year: int):
    """SBRO 'Date' is MMDD with no year; Oct–Dec => start year, Jan–Jun => end year."""
    s = str(mmdd).strip()
    if not s.isdigit() or len(s) not in (3, 4):
        return None
    s = s.zfill(4)
    month, day = int(s[:2]), int(s[2:])
    year = start_year if month >= 9 else end_year
    try:
        return pd.Timestamp(year=year, month=month, day=day)
    except ValueError:
        return None


def _parse_season_html(html: str, season: str) -> pd.DataFrame:
    start_year = int(season[:4])
    end_year = start_year + 1

    # Flatten every table cell to text.
    raw = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", html, re.S)
    cells = [re.sub(r"<[^>]+>", "", _html.unescape(c)).strip() for c in raw]

    # Locate the first header occurrence and chunk the remainder into 13-col rows.
    try:
        h0 = next(i for i in range(len(cells) - 3)
                  if cells[i] == "Date" and cells[i + 1] == "Rot" and cells[i + 2] == "VH")
    except StopIteration:
        return pd.DataFrame()
    body = cells[h0 + len(_COLS):]
    rows = [body[i:i + len(_COLS)] for i in range(0, len(body), len(_COLS))
            if len(body[i:i + len(_COLS)]) == len(_COLS)]

    games = []
    i = 0
    while i + 1 < len(rows):
        v, h = rows[i], rows[i + 1]
        # A valid game is a V row followed by an H row; skip repeated headers / junk.
        if v[2] != "V" or h[2] != "H":
            i += 1
            continue
        rec = dict.fromkeys(_COLS)
        vrow = dict(zip(_COLS, v))
        hrow = dict(zip(_COLS, h))
        date = _mmdd_to_date(vrow["Date"], start_year, end_year)
        away = name_to_bref(vrow["Team"])
        home = name_to_bref(hrow["Team"])
        v_close, h_close = _num(vrow["Close"]), _num(hrow["Close"])
        v_open, h_open = _num(vrow["Open"]), _num(hrow["Open"])
        closes = [x for x in (v_close, h_close) if x is not None]
        opens = [x for x in (v_open, h_open) if x is not None]
        close_total = next((x for x in closes if x > 100), None)
        close_spread = next((x for x in closes if x <= 100), None)
        open_total = next((x for x in opens if x > 100), None)
        games.append({
            "season": season,
            "date": date,
            "away": away,
            "home": home,
            "away_final": _num(vrow["Final"]),
            "home_final": _num(hrow["Final"]),
            "close_total": close_total,
            "open_total": open_total,
            "close_spread": close_spread,
        })
        i += 2

    df = pd.DataFrame(games)
    return df


def season_totals(season: str) -> pd.DataFrame:
    """Closing totals for one season (cached HTML + parsed parquet)."""
    def _build():
        url = f"{_BASE}/nba-odds-{season}"
        html = _cached_html(f"sbro_{season}", url)
        return _parse_season_html(html, season)

    return cached_frame(f"sbro_totals_{season}", _build, subdir="raw")


def build_closing_totals(seasons: list[str]) -> pd.DataFrame:
    """Closing totals across seasons, keyed to join b-ref games on (date, away, home)."""
    frames = [season_totals(s) for s in seasons]
    df = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    if not df.empty:
        df = df.dropna(subset=["date", "away", "home"])
    return df
