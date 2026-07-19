"""Long-running background job: populate the basketball-reference HTML cache.

Fetches every boxscore page (for officials + box/pace) for the configured seasons,
newest first, throttled under b-ref's rate limit. Fully resumable: re-running skips
anything already cached, so it is safe to interrupt/restart. Parsing into the games
table is done separately and cheaply by ``refedge.data.bref.assemble_games``.

Usage:
    python scripts/scrape_bref.py                 # all CFG.seasons + recent
    python scripts/scrape_bref.py 2025-26 2024-25 # explicit subset
"""
from __future__ import annotations

import sys

from refedge.data import bref

# Two-layer design: 2025-26 is the Polymarket backtest season (fetched FIRST);
# 2018-19..2022-23 feed the 5-season statistical test vs. Vegas closing totals
# (sportsbookreviewsonline closing-total coverage ends at 2022-23).
DEFAULT_SEASONS = [
    "2025-26", "2022-23", "2021-22", "2020-21", "2019-20", "2018-19",
]


def main() -> None:
    seasons = sys.argv[1:] or DEFAULT_SEASONS
    print(f"[scrape] seasons (newest first): {sorted(seasons, reverse=True)}", flush=True)
    bref.fetch_all_html(seasons, newest_first=True)
    print("[scrape] ALL DONE", flush=True)


if __name__ == "__main__":
    main()
