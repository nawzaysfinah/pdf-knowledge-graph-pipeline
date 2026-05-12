"""Knowledge graph schema constants."""

from __future__ import annotations

NODE_LABELS = {
    "Document",
    "Division",
    "Initiative",
    "Topic",
    "Issue",
    "Learning",
    "Outcome",
}

RELATIONSHIP_TYPES = {
    "CREATED_BY",
    "OWNED_BY",
    "ABOUT",
    "MENTIONS",
    "CAPTURES",
    "RELATES_TO",
    "ADDRESSES",
    "RESULTED_IN",
    "CO_OCCURS_WITH",
    "SHARES_LEARNING_WITH",
    "CROSSES_DIVISION",
}

ENTITY_KEYS = {
    "Initiative": ("initiative_id", "name"),
    "Topic": ("topic_id", "name"),
    "Issue": ("issue_id", "name"),
    "Learning": ("learning_id", "text"),
    "Outcome": ("outcome_id", "name"),
    "Division": ("division_id", "name"),
    "Document": ("doc_id",),
}
