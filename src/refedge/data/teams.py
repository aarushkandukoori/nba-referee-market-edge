"""NBA team-code normalisation across sources.

Different sources use different 3-letter codes for a handful of teams:
  * basketball-reference: PHO, BRK, CHO  (Phoenix, Brooklyn, Charlotte)
  * Polymarket slugs:      PHX, BKN, CHA
plus franchise-relocation history (Charlotte/New Orleans) that we ignore because
our window is post-2018. We normalise everything to the **b-ref** code, which is
our source of record for games.
"""
from __future__ import annotations

# Canonical (b-ref) codes -> set of full-name spellings seen across sources.
BREF_CODES = {
    "ATL", "BOS", "BRK", "CHO", "CHI", "CLE", "DAL", "DEN", "DET", "GSW", "HOU",
    "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK", "OKC", "ORL",
    "PHI", "PHO", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
}

# Polymarket / common-abbrev code -> b-ref code (only the ones that differ).
_ALIAS = {
    "PHX": "PHO",
    "BKN": "BRK",
    "CHA": "CHO",
    "NO": "NOP",
    "NOH": "NOP",
    "SA": "SAS",
    "GS": "GSW",
    "NY": "NYK",
    "UTAH": "UTA",
    "WSH": "WAS",
}


def to_bref(code: str) -> str:
    """Normalise any source's team code to the b-ref canonical code."""
    c = (code or "").strip().upper()
    c = _ALIAS.get(c, c)
    return c


# Full team name -> b-ref code, for sources that give names not codes
# (e.g. sportsbookreviewsonline uses city/nickname strings).
NAME_TO_BREF = {
    "atlanta": "ATL", "hawks": "ATL",
    "boston": "BOS", "celtics": "BOS",
    "brooklyn": "BRK", "nets": "BRK",
    "charlotte": "CHO", "hornets": "CHO", "bobcats": "CHO",
    "chicago": "CHI", "bulls": "CHI",
    "cleveland": "CLE", "cavaliers": "CLE", "cavs": "CLE",
    "dallas": "DAL", "mavericks": "DAL", "mavs": "DAL",
    "denver": "DEN", "nuggets": "DEN",
    "detroit": "DET", "pistons": "DET",
    "goldenstate": "GSW", "warriors": "GSW", "golden": "GSW",
    "houston": "HOU", "rockets": "HOU",
    "indiana": "IND", "pacers": "IND",
    "laclippers": "LAC", "clippers": "LAC",
    "lalakers": "LAL", "lakers": "LAL",
    "memphis": "MEM", "grizzlies": "MEM",
    "miami": "MIA", "heat": "MIA",
    "milwaukee": "MIL", "bucks": "MIL",
    "minnesota": "MIN", "timberwolves": "MIN", "wolves": "MIN",
    "neworleans": "NOP", "pelicans": "NOP",
    "newyork": "NYK", "knicks": "NYK",
    "oklahomacity": "OKC", "thunder": "OKC",
    "orlando": "ORL", "magic": "ORL",
    "philadelphia": "PHI", "76ers": "PHI", "sixers": "PHI",
    "phoenix": "PHO", "suns": "PHO",
    "portland": "POR", "blazers": "POR", "trailblazers": "POR",
    "sacramento": "SAC", "kings": "SAC",
    "sanantonio": "SAS", "spurs": "SAS",
    "toronto": "TOR", "raptors": "TOR",
    "utah": "UTA", "jazz": "UTA",
    "washington": "WAS", "wizards": "WAS",
}


def name_to_bref(name: str) -> str | None:
    key = "".join(ch for ch in (name or "").lower() if ch.isalnum())
    if key in NAME_TO_BREF:
        return NAME_TO_BREF[key]
    # try nickname (last word) match
    for token in reversed((name or "").lower().split()):
        tkey = "".join(ch for ch in token if ch.isalnum())
        if tkey in NAME_TO_BREF:
            return NAME_TO_BREF[tkey]
    return None
