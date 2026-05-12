"""Text utility functions."""

from __future__ import annotations

import re
import unicodedata


def normalize_whitespace(value: str) -> str:
    """Trim and collapse repeated whitespace."""
    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def slugify(value: str) -> str:
    """Convert text to a simple ASCII slug."""
    normalized = unicodedata.normalize("NFKD", normalize_whitespace(value))
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    lowered = ascii_text.lower()
    slug = re.sub(r"[^a-z0-9]+", "_", lowered).strip("_")
    return slug or "unknown"
