"""LaTeX escape sequences decoder for MPC names and citations."""

from __future__ import annotations

import re
import unicodedata

# Mapping from LaTeX accent commands to Unicode combining characters
ACCENT_MAP = {
    "'": "\u0301",  # acute: \'e -> é
    "`": "\u0300",  # grave: \`e -> è
    "^": "\u0302",  # circumflex: \^e -> ê
    '"': "\u0308",  # umlaut: \"u -> ü
    "~": "\u0303",  # tilde: \~a -> ã
    "=": "\u0304",  # macron: \={o} -> ō
    "v": "\u030c",  # caron: \v{s} -> š
    "c": "\u0327",  # cedilla: \c{c} -> ç
    "H": "\u030b",  # double acute: \H{o} -> ő
    "d": "\u0323",  # dot under: \d{o} -> ọ
    "b": "\u0331",  # line under: \b{o} -> o̱
    "u": "\u0306",  # breve: \u{o} -> ŏ
    "r": "\u030a",  # ring above: \r{a} -> å
    ".": "\u0307",  # dot above: \.z -> ż
    "k": "\u0328",  # ogonek: \k{a} -> ą
}

# Mapping for special LaTeX macros/symbols
SPECIAL_MAP = {
    r"{\AE}": "Æ",
    r"{\ae}": "æ",
    r"{\OE}": "Œ",
    r"{\oe}": "œ",
    r"{\O}": "Ø",
    r"{\o}": "ø",
    r"{\AA}": "Å",
    r"{\aa}": "å",
    r"\L{}": "Ł",
    r"\L": "Ł",
    r"\l{}": "ł",
    r"\l": "ł",
    r"{\ss}": "ß",
    r"\ss": "ß",
    r"{\i}": "i",  # Map dotless i to regular i for Unicode combining character resolution
    r"\i": "i",
}

def decode_latex(text: str | None) -> str | None:
    """Decode LaTeX accent commands and special characters into Unicode."""
    if not text:
        return text

    # 1. Apply special symbols mapping
    for key, val in SPECIAL_MAP.items():
        text = text.replace(key, val)

    # 2. Match LaTeX accent commands with brackets: \COMMAND{CHAR}
    # e.g., \={i}, \c{s}, \v{r}
    def replace_bracket_accent(match: re.Match) -> str:
        cmd = match.group(1)
        char = match.group(2)
        comb = ACCENT_MAP.get(cmd)
        if comb:
            return char + comb
        return match.group(0)

    text = re.sub(r"\\(['\"^~=vchdburk\.]+)\{([^{}]+)\}", replace_bracket_accent, text)

    # 3. Match LaTeX accent commands without brackets: \COMMAND CHAR
    # e.g., \'e, \"U, \~a, \=o
    def replace_no_bracket_accent(match: re.Match) -> str:
        cmd = match.group(1)
        char = match.group(2)
        comb = ACCENT_MAP.get(cmd)
        if comb:
            return char + comb
        return match.group(0)

    # We match accent characters (both symbols and letters) followed by optional spaces and a character
    text = re.sub(r"\\(['\"^~=\.])[ ]?([A-Za-z])", replace_no_bracket_accent, text)
    text = re.sub(r"\\([vchdburk])[ ]+([A-Za-z])", replace_no_bracket_accent, text)
    text = re.sub(r"\\([vchdburk])([A-Za-z])", replace_no_bracket_accent, text)

    res = unicodedata.normalize("NFC", text)
    
    # 4. Convert Romanian/Turkish style cedilla symbols to modern Romanian comma below where expected
    res = (
        res.replace("\u015f", "\u0219")  # ş -> ș
        .replace("\u015e", "\u0218")  # Ş -> Ș
        .replace("\u0163", "\u021b")  # ţ -> ț
        .replace("\u0162", "\u021a")  # Ţ -> Ț
    )
    return res
