"""WGSBN Bulletin archive parsing for minor-planet naming publications."""

from __future__ import annotations

import datetime as dt
import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urljoin, urlparse


@dataclass(frozen=True)
class WgsbnBulletin:
    volume: int
    issue: int
    published_date: str
    source_url: str


@dataclass(frozen=True)
class WgsbnNaming:
    permid: str
    name: str
    citation: str | None
    reference: str | None


_ARCHIVE_ITEM_RE = re.compile(
    r'<li>.*?Volume\s+(?P<volume>\d+),\s*#(?P<issue>\d+).*?'
    r'href="(?P<href>files/json/V\d{3}/WGSBNBull_V\d{3}_\d{3}\.json)".*?'
    r'\((?P<date>\d{4}\s+[A-Za-z]+\.?\s+\d{1,2})\)',
    re.IGNORECASE,
)


def parse_wgsbn_archive(html: str, archive_url: str) -> list[WgsbnBulletin]:
    """Parse the WGSBN archive page into dated JSON bulletin endpoints."""
    parsed = urlparse(archive_url)
    site_root = f"{parsed.scheme}://{parsed.netloc}/"
    seen: set[str] = set()
    bulletins: list[WgsbnBulletin] = []
    for match in _ARCHIVE_ITEM_RE.finditer(html):
        source_url = urljoin(site_root, match.group("href"))
        if source_url in seen:
            continue
        seen.add(source_url)
        bulletins.append(
            WgsbnBulletin(
                volume=int(match.group("volume")),
                issue=int(match.group("issue")),
                published_date=_parse_archive_date(match.group("date")),
                source_url=source_url,
            )
        )
    return sorted(bulletins, key=lambda bulletin: (bulletin.published_date, bulletin.volume, bulletin.issue))


def parse_wgsbn_namings(body: str) -> list[WgsbnNaming]:
    """Parse one WGSBN UTF-8 JSON file, ignoring malformed non-planet entries."""
    payload = json.loads(body)
    if not isinstance(payload, list):
        raise ValueError("WGSBN naming data must be a JSON array")

    namings: list[WgsbnNaming] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        permid = str(item.get("mp_number") or "").strip()
        name = str(item.get("name") or "").strip()
        if not permid.isdigit() or not name:
            continue
        citation = item.get("citation")
        reference = item.get("reference")
        namings.append(
            WgsbnNaming(
                permid=permid,
                name=name,
                citation=str(citation) if citation is not None else None,
                reference=str(reference) if reference is not None else None,
            )
        )
    return namings


def _parse_archive_date(value: str) -> str:
    year_text, month_text, day_text = value.replace(".", "").split()
    month = month_text[:3].title()
    return dt.datetime.strptime(f"{year_text} {month} {day_text}", "%Y %b %d").date().isoformat()
