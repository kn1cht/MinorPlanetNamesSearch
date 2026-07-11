"""Parser for MPC's Minor Planet Names alphabetical list."""

from __future__ import annotations

import re
from dataclasses import dataclass
from html.parser import HTMLParser
from .latex import decode_latex


@dataclass(frozen=True)
class NameRecord:
    permid: str
    name_ascii: str
    name_display: str


class _PreTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_pre = False
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "pre":
            self._in_pre = True

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "pre":
            self._in_pre = False

    def handle_data(self, data: str) -> None:
        if self._in_pre:
            self.parts.append(data)


LINE_RE = re.compile(r"^\s*\((?P<permid>\d+)\)\s+(?P<names>.+?)\s*$")


def parse_mpnames_html(html: str) -> list[NameRecord]:
    """Extract numbered minor-planet names from MPNames.html."""
    parser = _PreTextParser()
    parser.feed(html)
    text = "".join(parser.parts)
    records: list[NameRecord] = []

    for raw_line in text.splitlines():
        line = raw_line.rstrip()
        match = LINE_RE.match(line)
        if not match:
            continue

        permid = match.group("permid")
        names = match.group("names")
        left, right = _split_name_columns(names)
        if not left:
            continue
        name_ascii = decode_latex(left)
        name_display = decode_latex(right or left)
        records.append(NameRecord(permid=permid, name_ascii=name_ascii, name_display=name_display))

    return records


def _split_name_columns(value: str) -> tuple[str, str]:
    parts = re.split(r"\s{2,}", value.strip(), maxsplit=1)
    if len(parts) == 1:
        return parts[0].strip(), parts[0].strip()
    return parts[0].strip(), parts[1].strip()

