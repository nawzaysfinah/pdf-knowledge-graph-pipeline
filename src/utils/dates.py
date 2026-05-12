"""Date helpers for canonicalization and trend queries."""

from __future__ import annotations

from datetime import datetime


def extract_year(value: str) -> str:
    """Return a four-digit year if parseable; else empty string."""
    if not value:
        return ""
    text = str(value).strip()
    if len(text) >= 4 and text[:4].isdigit():
        return text[:4]

    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
        try:
            return str(datetime.strptime(text, fmt).year)
        except ValueError:
            continue
    return ""
