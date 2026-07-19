"""Project-wide defaults that are safe to tune in one place."""

from __future__ import annotations

from pathlib import Path


DEFAULT_DB = Path("data/mpnames.sqlite3")

MPNAMES_URL = "https://www.minorplanetcenter.net/iau/lists/MPNames.html"
NUMBERED_MPS_URL = "https://www.minorplanetcenter.net/iau/lists/NumberedMPs.txt"
NUMBERED_MPS_CACHE = Path("data/NumberedMPs.txt")
IDENTIFIER_URL = "https://data.minorplanetcenter.net/api/query-identifier"
ORBITS_URL = "https://data.minorplanetcenter.net/api/get-orb"
WGSBN_ARCHIVE_URL = "https://www.wgsbn-iau.org/files/json/index.html"
WGSBN_INTER_REQUEST_DELAY_SECONDS = 0.1

IDENTIFIER_BATCH_SIZE = 10
IDENTIFIER_INTER_REQUEST_DELAY_SECONDS = 0.05
IDENTIFIER_LONG_PAUSE_EVERY_REQUESTS = 3
IDENTIFIER_LONG_PAUSE_SECONDS = 5.0
ORBIT_INTER_REQUEST_DELAY_SECONDS = 0.05
ORBIT_LONG_PAUSE_EVERY_REQUESTS = 8
ORBIT_LONG_PAUSE_SECONDS = 10.0

OLLAMA_HOST = "http://127.0.0.1:11434"
