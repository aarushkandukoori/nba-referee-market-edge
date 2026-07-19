"""Polymarket historical NBA game total-points (O/U) markets + pre-tip prices.

Coverage (verified during recon): full 2025-26 season + 2025 playoffs; earlier
seasons were moneyline-only. Each game has a ladder of ``O/U X.5`` strike markets,
each a two-sided ["Over","Under"] binary that resolves on the combined score.

We pull, per strike-market:
  * teams / game date / line   — parsed from the slug ``nba-{away}-{home}-{date}-total-{line}pt5``
  * resolution                 — ``outcomePrices`` (["1","0"] => Over won)
  * the **Over token price just before tip-off** — the market-implied P(over),
    the single most important number for the backtest — via the CLOB
    ``prices-history`` endpoint (``interval=max`` is broken for resolved markets,
    so we use explicit ``startTs``/``endTs``).

Everything is cached to parquet; the Gamma offset cap (~2100) is bypassed with
monthly ``end_date_min/max`` windows.
"""
from __future__ import annotations

import json
import re
import time
import urllib.request
from datetime import datetime, timedelta, timezone

import pandas as pd

from refedge.cache import cached_frame
from refedge.data.teams import to_bref

GAMMA = "https://gamma-api.polymarket.com"
CLOB = "https://clob.polymarket.com"
NBA_TAG = 745

_SLUG_RE = re.compile(r"nba-([a-z]{2,4})-([a-z]{2,4})-(\d{4}-\d{2}-\d{2})-total-(\d+)pt5")


def _get(url: str, tries: int = 5):
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "refedge/1.0"})
            with urllib.request.urlopen(req, timeout=40) as r:
                return json.load(r)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(1.0 + i)
    print(f"[markets] GET failed: {url[:100]} :: {last}")
    return None


def _month_windows(start: str, end: str):
    """Yield (min_iso, max_iso) month boundaries spanning [start, end]."""
    d = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    end_d = datetime.strptime(end, "%Y-%m-%d").replace(tzinfo=timezone.utc)
    while d < end_d:
        nxt = (d.replace(day=28) + timedelta(days=7)).replace(day=1)
        yield d.strftime("%Y-%m-%dT00:00:00Z"), nxt.strftime("%Y-%m-%dT00:00:00Z")
        d = nxt


def _enumerate_totals(start: str, end: str) -> pd.DataFrame:
    """All NBA game O/U total strike-markets whose tip falls in [start, end)."""
    recs: dict[str, dict] = {}
    for dmin, dmax in _month_windows(start, end):
        offset = 0
        while True:
            url = (f"{GAMMA}/markets?tag_id={NBA_TAG}&closed=true&limit=100&offset={offset}"
                   f"&end_date_min={dmin}&end_date_max={dmax}")
            b = _get(url)
            rows = b if isinstance(b, list) else (b or {}).get("data", [])
            if not rows:
                break
            for m in rows:
                slug = m.get("slug") or ""
                mo = _SLUG_RE.search(slug)
                if not mo:
                    continue
                away, home, gdate, line_int = mo.groups()
                ids = m.get("clobTokenIds")
                ids = json.loads(ids) if isinstance(ids, str) else (ids or [])
                prices = m.get("outcomePrices")
                prices = json.loads(prices) if isinstance(prices, str) else (prices or [])
                if len(ids) < 2 or len(prices) < 2:
                    continue
                over_won = str(prices[0]) in ("1", "1.0")
                recs[slug] = {
                    "slug": slug,
                    "game_date": gdate,
                    "away": to_bref(away),
                    "home": to_bref(home),
                    "line": float(line_int) + 0.5,
                    "over_token": ids[0],
                    "under_token": ids[1],
                    "over_won": over_won,
                    "tip_utc": m.get("endDate"),
                    "volume": float(m.get("volumeNum") or m.get("volume") or 0),
                    "question": m.get("question"),
                }
            offset += len(rows)
            if len(rows) < 100 or offset > 4000:
                break
    df = pd.DataFrame(list(recs.values()))
    if not df.empty:
        df["game_date"] = pd.to_datetime(df["game_date"])
    return df


def _pretip_prices(over_token: str, tip_utc: str) -> dict:
    """Over-token price at / just before tip, plus T-30m and T-60m snapshots.

    Returns market-implied P(over) at several pre-game offsets so the backtest can
    choose a snapshot and we can check robustness. All strictly BEFORE tip.
    """
    try:
        tip = datetime.strptime(tip_utc, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return {}
    end_ts = int(tip.timestamp())
    start_ts = end_ts - 5 * 86400
    h = _get(f"{CLOB}/prices-history?market={over_token}&startTs={start_ts}&endTs={end_ts}&fidelity=1")
    pts = (h or {}).get("history") or []
    pts = [p for p in pts if p.get("t", 1e18) <= end_ts]
    if not pts:
        return {"n_price_pts": 0}
    pts.sort(key=lambda p: p["t"])

    def price_before(offset_s: int):
        cutoff = end_ts - offset_s
        pre = [p for p in pts if p["t"] <= cutoff]
        return pre[-1]["p"] if pre else None

    return {
        "p_over_tip": pts[-1]["p"],                 # last print before tip
        "p_over_t30": price_before(30 * 60),
        "p_over_t60": price_before(60 * 60),
        "n_price_pts": len(pts),
        "last_price_lag_s": end_ts - pts[-1]["t"],  # how stale the last print is
    }


def build_market_totals(start: str = "2025-09-01", end: str = "2026-07-01",
                        with_prices: bool = True, force: bool = False) -> pd.DataFrame:
    """Enumerate + (optionally) price all 2025-26 NBA game total markets. Cached."""
    def _build():
        df = _enumerate_totals(start, end)
        if df.empty or not with_prices:
            return df
        snaps = []
        n = len(df)
        for i, row in enumerate(df.itertuples(index=False)):
            snaps.append(_pretip_prices(row.over_token, row.tip_utc))
            if i % 50 == 0 or i == n - 1:
                print(f"[markets] prices {i + 1}/{n}", flush=True)
        return pd.concat([df.reset_index(drop=True), pd.DataFrame(snaps)], axis=1)

    return cached_frame(f"pm_totals_{start}_{end}_{int(with_prices)}", _build,
                        subdir="raw", force=force)
