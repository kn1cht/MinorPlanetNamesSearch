"""Parser for MPC NumberedMPs discovery-circumstances rows."""

from __future__ import annotations

import re
from dataclasses import dataclass
from .latex import decode_latex


DATE_RE = re.compile(r"\b(?P<year>\d{4})\s(?P<month>\d{2})\s(?P<day>\d{2})")
PERMID_RE = re.compile(r"^\s*\((?P<permid>\d+)\)(?:\s+(?P<name>.+))?$")

PERSON_RE = re.compile(
    r"[A-Z][A-Za-z'`.-]*(?:\s+[a-z][A-Za-z'`.-]*)?(?:\s+[A-Z][A-Za-z'`.-]*)*,\s+"
    r"(?:[A-Z]\.\s*){1,4}"
)


@dataclass(frozen=True)
class DiscoveryRecord:
    permid: str
    name: str
    discovery_date: str
    discovery_site: str
    discoverer_text: str
    discoverers: tuple[str, ...]


def parse_numbered_mps(text: str) -> dict[str, DiscoveryRecord]:
    """Parse NumberedMPs.txt into discovery records keyed by permanent number."""
    records: dict[str, DiscoveryRecord] = {}
    for line in text.splitlines():
        record = parse_numbered_mps_line(line)
        if record:
            records[record.permid] = record
    return records


def parse_numbered_mps_line(line: str) -> DiscoveryRecord | None:
    # Find YYYY MM DD date (which is always 10 characters and present in every valid row)
    date_match = DATE_RE.search(line)
    if not date_match:
        return None

    prefix = line[:date_match.start()].strip()
    permid_match = PERMID_RE.match(prefix)
    if not permid_match:
        return None

    permid = permid_match.group("permid")
    name = decode_latex((permid_match.group("name") or "").strip())
    
    year = date_match.group("year")
    month = date_match.group("month")
    day = date_match.group("day")
    
    de = date_match.end()
    # Columns after date are fixed width. Site is de+2 to de+26.
    if len(line) < de + 2:
        return None
        
    site = line[de+2 : de+26].strip()
    if site.startswith("*"):
        site = site[1:].strip()
        
    discoverer_raw = line[de+26:]
    discoverer_text = clean_discoverer_text(discoverer_raw)
    
    # In some rare cases, site is empty in raw data (e.g. WISE only objects).
    # We allow site to be empty, but discoverer must exist.
    if not discoverer_text:
        return None

    return DiscoveryRecord(
        permid=permid,
        name=name,
        discovery_date=f"{year}-{month}-{day}",
        discovery_site=site,
        discoverer_text=discoverer_text,
        discoverers=split_discoverers(discoverer_text),
    )


def split_discoverers(value: str) -> tuple[str, ...]:
    """Split common MPC person lists while preserving survey/team names."""
    text = value.strip()
    if not text:
        return ()

    matches = [match.group(0).strip().rstrip(",") for match in PERSON_RE.finditer(text)]
    if matches:
        covered = "".join(matches).replace(" ", "")
        compact = re.sub(r"[\s,]+", "", text)
        matched_compact = re.sub(r"[\s,]+", "", covered)
        if matched_compact and compact.startswith(matched_compact):
            return tuple(dict.fromkeys(matches))

    return (text,)


def clean_discoverer_text(value: str) -> str:
    """Remove MPC numeric discoverer prefixes when present."""
    text = value.strip()
    return re.sub(r"^\d+\s+", "", text)
