from __future__ import annotations

import re

_SIG_RE = re.compile(r"([A-Za-z]{1,3})\s*[/-]\s*(\d{1,6})\s*[/-]\s*(\d{4})")

class SignatureError(ValueError):
    """Raised when a string contains no recognizable signature."""

def _parts(s: str) -> tuple[str, str, str]:
    m = _SIG_RE.search(s or "")
    if not m:
        raise SignatureError(f"no signature found in {s!r}")
    letters, number, year = m.groups()
    return letters.upper(), number, year

def canonical(s: str) -> str:
    letters, number, year = _parts(s)
    return f"{letters}/{number}/{year}"

def to_url(s: str) -> str:
    letters, number, year = _parts(s)
    return f"{letters.lower()}-{number}-{year}"

def to_slug(s: str) -> str:
    letters, number, year = _parts(s)
    return f"{letters}-{number}-{year}"

def letters_of(s: str) -> str:
    return _parts(s)[0]

def year_of(s: str) -> str:
    return _parts(s)[2]

def find_all(text: str) -> list[str]:
    seen: list[str] = []
    for m in _SIG_RE.finditer(text or ""):
        letters, number, year = m.group(1).upper(), m.group(2), m.group(3)
        sig = f"{letters}/{number}/{year}"
        if sig not in seen:
            seen.append(sig)
    return seen
