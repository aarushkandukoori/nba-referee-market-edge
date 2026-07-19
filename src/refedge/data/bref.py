"""basketball-reference scraper: officials + box scores/pace, per game.

Why this module exists: ``stats.nba.com`` (the ``nba_api`` backend) is IP-blocked
from this environment, and it is the only endpoint that returns the officiating
crew. basketball-reference publishes the 3 officials on every boxscore page plus
full team box scores and pace, and is reachable — so it is our source of record.

Design principles:
  * **Cache raw HTML** (gzipped) on first fetch, so re-parsing is free and we
    never re-hit b-ref for a page we already have. Parsed tables are cached as
    parquet on top of that.
  * **Throttle hard.** b-ref rate-limits ~20 req/min and will issue temporary
    bans above that; we enforce a minimum inter-request gap + exponential backoff.
  * **Resumable.** ``build_games`` skips any game already parsed, so a long
    multi-season backfill can be interrupted and continued.

b-ref hides most tables inside HTML comments to defeat naive scrapers; we strip
the ``<!-- -->`` markers before parsing (see ``_decomment``).
"""
from __future__ import annotations

import gzip
import io
import re
import time
from pathlib import Path

import pandas as pd
import requests

from refedge.config import RAW

HTML_DIR = RAW / "bref_html"
HTML_DIR.mkdir(parents=True, exist_ok=True)

_BASE = "https://www.basketball-reference.com"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# --- polite rate limiting -------------------------------------------------
MIN_GAP_S = 3.5            # >= 3.5s between requests => < ~17/min, under b-ref's limit
_last_request_ts = [0.0]
_session = requests.Session()
_session.headers.update(_HEADERS)

_MONTHS = ["october", "november", "december", "january", "february", "march",
           "april", "may", "june", "july", "august", "september"]


def _throttle() -> None:
    dt = time.time() - _last_request_ts[0]
    if dt < MIN_GAP_S:
        time.sleep(MIN_GAP_S - dt)
    _last_request_ts[0] = time.time()


def _get(url: str, max_tries: int = 5) -> str:
    """GET with throttle + exponential backoff. Raises on repeated failure.

    A 429 (rate-limited) triggers a long cooldown — b-ref bans are ~minutes.
    """
    last_err: Exception | None = None
    for attempt in range(max_tries):
        _throttle()
        try:
            r = _session.get(url, timeout=30)
            if r.status_code == 429:
                cooldown = 60 * (attempt + 1)
                print(f"[bref] 429 rate-limited on {url} — cooling {cooldown}s")
                time.sleep(cooldown)
                continue
            r.raise_for_status()
            return r.text
        except Exception as e:  # noqa: BLE001 — retry any transient network error
            last_err = e
            time.sleep(2 ** attempt)
    raise RuntimeError(f"[bref] failed to GET {url}: {last_err}")


def _cached_html(key: str, url: str) -> str:
    """Return page HTML, fetching + caching (gzip) on a miss."""
    fp = HTML_DIR / f"{key}.html.gz"
    if fp.exists():
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            return fh.read()
    html = _get(url)
    with gzip.open(fp, "wt", encoding="utf-8") as fh:
        fh.write(html)
    return html


def _decomment(html: str) -> str:
    return html.replace("<!--", "").replace("-->", "")


# --- schedules ------------------------------------------------------------
def _season_end_year(season: str) -> int:
    """'2023-24' -> 2024 (b-ref indexes seasons by the year they end in)."""
    start = int(season[:4])
    return start + 1


def list_games(season: str) -> pd.DataFrame:
    """All regular+playoff games for a season as (game_id, date, away, home, is_playoff?).

    game_id is the b-ref boxscore id, e.g. '202403010BOS' (date + '0' + home code).
    Parsed row-by-row so we can attach the boxscore link (read_html drops hrefs).
    """
    from bs4 import BeautifulSoup

    end_year = _season_end_year(season)
    rows: list[dict] = []
    for month in _MONTHS:
        url = f"{_BASE}/leagues/NBA_{end_year}_games-{month}.html"
        key = f"sched_{end_year}_{month}"
        fp = HTML_DIR / f"{key}.html.gz"
        # A month with no games returns 404; cache the miss as an empty marker.
        if not fp.exists():
            try:
                html = _get(url)
            except RuntimeError:
                with gzip.open(fp, "wt", encoding="utf-8") as fh:
                    fh.write("")   # remember: this month has no page
                continue
            with gzip.open(fp, "wt", encoding="utf-8") as fh:
                fh.write(html)
        with gzip.open(fp, "rt", encoding="utf-8") as fh:
            html = fh.read()
        if not html.strip():
            continue
        soup = BeautifulSoup(html, "lxml")
        table = soup.find("table", id="schedule")
        if table is None or table.tbody is None:
            continue
        for tr in table.tbody.find_all("tr"):
            if tr.get("class") and "thead" in tr.get("class"):
                continue
            link = tr.find("a", href=re.compile(r"/boxscores/\d{9}[A-Z]{3}\.html"))
            if link is None:
                continue  # unplayed/postponed row
            gid = re.search(r"/boxscores/(\d{9}[A-Z]{3})\.html", link["href"]).group(1)
            def cell(stat):
                el = tr.find(["td", "th"], attrs={"data-stat": stat})
                return el.get_text(strip=True) if el else None
            rows.append({
                "game_id": gid,
                "date": gid[:8],  # YYYYMMDD, unambiguous vs. localized date text
                "away": cell("visitor_team_name"),
                "home": cell("home_team_name"),
                "away_pts_sched": pd.to_numeric(cell("visitor_pts"), errors="coerce"),
                "home_pts_sched": pd.to_numeric(cell("home_pts"), errors="coerce"),
                "season": season,
            })
    df = pd.DataFrame(rows)
    if not df.empty:
        df["date"] = pd.to_datetime(df["date"], format="%Y%m%d")
        df = df.sort_values("date").reset_index(drop=True)
    return df


# --- boxscores ------------------------------------------------------------
_OFF_RE = re.compile(r"/referees/([a-z0-9]+)\.html'>([^<]+)</a>")


def parse_boxscore(html: str, game_id: str) -> dict:
    """Extract officials + final scores + pace + team FTA/3PA/PF from one page."""
    dec = _decomment(html)
    out: dict = {"game_id": game_id}

    # Officials (stable ref IDs). Home team code = last 3 chars of game_id.
    m = re.search(r"Officials:.*?</div>", dec, re.S)
    offs = _OFF_RE.findall(m.group(0)) if m else []
    for i in range(3):
        out[f"off{i+1}_id"] = offs[i][0] if i < len(offs) else None
        out[f"off{i+1}_name"] = offs[i][1].strip() if i < len(offs) else None
    out["n_officials"] = len(offs)

    home_code = game_id[-3:]
    # line_score: two rows (away then home), 'T' column = final points
    try:
        ls = pd.read_html(io.StringIO(dec), attrs={"id": "line_score"})[0]
        ls.columns = [c[-1] if isinstance(c, tuple) else c for c in ls.columns]
        team_col = ls.columns[0]
        pts = dict(zip(ls[team_col].astype(str), pd.to_numeric(ls["T"], errors="coerce")))
        codes = list(pts.keys())
        out["away_code"], out["home_code"] = codes[0], codes[1]
        out["away_pts"] = pts[codes[0]]
        out["home_pts"] = pts[codes[1]]
    except Exception:  # noqa: BLE001
        out["away_code"] = out["home_code"] = None
        out["away_pts"] = out["home_pts"] = None

    # four_factors: Pace (identical for both teams), FT/FGA per team
    try:
        ff = pd.read_html(io.StringIO(dec), attrs={"id": "four_factors"})[0]
        ff.columns = [c[-1] if isinstance(c, tuple) else c for c in ff.columns]
        out["pace"] = pd.to_numeric(ff["Pace"], errors="coerce").iloc[0]
    except Exception:  # noqa: BLE001
        out["pace"] = None

    # team basic box 'Team Totals' -> FTA, 3PA, PF, PTS per team
    for side, code in (("away", out.get("away_code")), ("home", out.get("home_code"))):
        code = code or (home_code if side == "home" else None)
        try:
            t = pd.read_html(io.StringIO(dec), attrs={"id": f"box-{code}-game-basic"})[0]
            t.columns = [c[-1] if isinstance(c, tuple) else c for c in t.columns]
            tot = t[t.iloc[:, 0].astype(str).str.contains("Team Totals", na=False)].iloc[0]
            out[f"{side}_fta"] = pd.to_numeric(tot.get("FTA"), errors="coerce")
            out[f"{side}_3pa"] = pd.to_numeric(tot.get("3PA"), errors="coerce")
            out[f"{side}_pf"] = pd.to_numeric(tot.get("PF"), errors="coerce")
        except Exception:  # noqa: BLE001
            out[f"{side}_fta"] = out[f"{side}_3pa"] = out[f"{side}_pf"] = None

    return out


def fetch_boxscore(game_id: str) -> dict:
    html = _cached_html(game_id, f"{_BASE}/boxscores/{game_id}.html")
    return parse_boxscore(html, game_id)


def build_boxscores(game_ids: list[str], verbose: bool = True) -> pd.DataFrame:
    """Parse many games (resumable via the raw-HTML cache). Returns one row/game."""
    recs = []
    n = len(game_ids)
    for i, gid in enumerate(game_ids):
        recs.append(fetch_boxscore(gid))
        if verbose and (i % 25 == 0 or i == n - 1):
            print(f"[bref] boxscores {i + 1}/{n}")
    return pd.DataFrame(recs)


def _html_cached(game_id: str) -> bool:
    return (HTML_DIR / f"{game_id}.html.gz").exists()


def fetch_all_html(seasons: list[str], newest_first: bool = True) -> None:
    """Slow path: populate the raw-HTML cache for every game in ``seasons``.

    Intended to run as a long background job. Resumable — skips games already
    cached. Newest season first so the most valuable data (the market-overlap
    season) lands first. Parsing is done separately by ``assemble_games``.
    """
    order = sorted(seasons, reverse=newest_first)
    for season in order:
        games = list_games(season)
        todo = [g for g in games["game_id"] if not _html_cached(g)]
        print(f"[bref] {season}: {len(games)} games, {len(todo)} to fetch", flush=True)
        for i, gid in enumerate(todo):
            _cached_html(gid, f"{_BASE}/boxscores/{gid}.html")
            if i % 20 == 0 or i == len(todo) - 1:
                print(f"[bref]   {season} fetch {i + 1}/{len(todo)}", flush=True)
        print(f"[bref] {season}: fetch complete", flush=True)


def assemble_games(seasons: list[str], require_html: bool = True) -> pd.DataFrame:
    """Fast path: parse whatever HTML is cached into one games table.

    Joins schedule metadata (needs schedule pages, which are cheap) with parsed
    boxscore fields. Games whose boxscore HTML is not yet cached are skipped when
    ``require_html`` (so this returns usable *partial* data mid-backfill).
    Returns tidy per-game rows with officials, final scores, pace, FTA/3PA/PF,
    and derived total points.
    """
    frames = []
    for season in seasons:
        sched = list_games(season)
        if sched.empty:
            continue
        gids = [g for g in sched["game_id"] if (not require_html) or _html_cached(g)]
        if not gids:
            continue
        box = build_boxscores(gids, verbose=False)
        merged = sched.merge(box, on="game_id", how="inner", suffixes=("", "_box"))
        frames.append(merged)
    if not frames:
        return pd.DataFrame()
    df = pd.concat(frames, ignore_index=True)
    df["total_pts"] = df["away_pts"] + df["home_pts"]
    df["total_fta"] = df["away_fta"] + df["home_fta"]
    df["total_3pa"] = df["away_3pa"] + df["home_3pa"]
    df["total_pf"] = df["away_pf"] + df["home_pf"]
    return df.sort_values("date").reset_index(drop=True)
