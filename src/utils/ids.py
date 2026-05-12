"""ID generation helpers for derived entities."""

from __future__ import annotations

import hashlib

from src.utils.text import slugify


def make_stable_id(prefix: str, raw_value: str, max_slug_len: int = 40) -> str:
    """Create deterministic ids from text values."""
    text = raw_value or "unknown"
    slug = slugify(text)[:max_slug_len]
    digest = hashlib.sha1(text.encode("utf-8")).hexdigest()[:10]
    return f"{prefix}_{slug}_{digest}"
