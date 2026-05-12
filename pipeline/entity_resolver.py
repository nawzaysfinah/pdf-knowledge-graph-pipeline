"""Stage 6: Entity Resolution Module.

Pipeline:
  1. Collect all entity surface forms from output/extractions.jsonl, grouped by type
  2. Normalise: strip legal suffixes, collapse whitespace (comparison only)
  3. Embed with sentence-transformers all-MiniLM-L6-v2
  4. Cluster within each type via union-find on cosine similarity > THRESHOLD
  5. Elect canonical name (longest / most complete surface form per cluster)
  6. Build canonical_map: {surface_form -> {canonical_id, canonical_name, type}}
  7. Save output/canonical_map.json

canonical_id format: "<lowercase_type>_<md5[:8] of canonical_name.lower()>"
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from typing import Any

import numpy as np
from sklearn.metrics.pairwise import cosine_similarity

logger = logging.getLogger(__name__)

EXTRACTIONS_PATH  = Path("output") / "extractions.jsonl"
CANONICAL_MAP_PATH = Path("output") / "canonical_map.json"

SIMILARITY_THRESHOLD = 0.92
EMBED_MODEL          = "all-MiniLM-L6-v2"

_LEGAL_SUFFIX_RE = re.compile(
    r"\b(inc\.?|ltd\.?|corp\.?|llc\.?|pte\.?|co\.?|pty\.?|plc\.?|gmbh|ag|bv)\b",
    re.IGNORECASE,
)
_WHITESPACE_RE = re.compile(r"\s+")


# ---------------------------------------------------------------------------
# String normalisation (comparison only — display form is preserved)
# ---------------------------------------------------------------------------

def _normalise(name: str) -> str:
    name = _LEGAL_SUFFIX_RE.sub("", name)
    name = _WHITESPACE_RE.sub(" ", name).strip().lower()
    return name


# ---------------------------------------------------------------------------
# Canonical ID
# ---------------------------------------------------------------------------

def _make_canonical_id(entity_type: str, canonical_name: str) -> str:
    digest = hashlib.md5(canonical_name.lower().encode()).hexdigest()[:8]
    return f"{entity_type.lower()}_{digest}"


# ---------------------------------------------------------------------------
# Union-Find
# ---------------------------------------------------------------------------

class _UnionFind:
    def __init__(self, n: int) -> None:
        self._parent = list(range(n))

    def find(self, x: int) -> int:
        while self._parent[x] != x:
            self._parent[x] = self._parent[self._parent[x]]
            x = self._parent[x]
        return x

    def union(self, x: int, y: int) -> None:
        px, py = self.find(x), self.find(y)
        if px != py:
            self._parent[px] = py

    def clusters(self, names: list[str]) -> list[list[str]]:
        groups: dict[int, list[str]] = defaultdict(list)
        for i, name in enumerate(names):
            groups[self.find(i)].append(name)
        return list(groups.values())


# ---------------------------------------------------------------------------
# Canonical name election
# ---------------------------------------------------------------------------

def _elect_canonical(names: list[str]) -> str:
    """Pick the longest name; break ties by word count, then alphabetically."""
    return max(names, key=lambda n: (len(n), len(n.split()), n))


# ---------------------------------------------------------------------------
# Core resolution logic
# ---------------------------------------------------------------------------

def collect_entities(
    extractions_path: Path,
) -> tuple[dict[str, list[str]], dict[str, set[str]]]:
    """Return:
      by_type:    {entity_type: [surface_forms...]}
      alias_links: {canonical_name: {alias1, alias2, ...}}  — from LLM alias field
    """
    by_type: dict[str, set[str]] = defaultdict(set)
    alias_links: dict[str, set[str]] = defaultdict(set)

    with extractions_path.open() as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            record = json.loads(line)
            for ent in record.get("entities", []):
                name  = ent.get("name",  "").strip()
                etype = ent.get("type",  "").strip()
                if not (name and etype):
                    continue
                by_type[etype].add(name)
                for alias in ent.get("aliases", []):
                    alias = alias.strip()
                    if alias and alias != name:
                        by_type[etype].add(alias)
                        alias_links[name].add(alias)

    return (
        {t: sorted(names) for t, names in by_type.items()},
        dict(alias_links),
    )


def resolve_entities(
    by_type: dict[str, list[str]],
    alias_links: dict[str, set[str]] | None = None,
    threshold: float = SIMILARITY_THRESHOLD,
) -> tuple[dict[str, list[list[str]]], dict[str, Any]]:
    """Embed, cluster, and elect canonical names.

    Two merge passes per entity type:
      1. Alias-based: force-merge any name with its LLM-supplied aliases
      2. Embedding-based: merge pairs whose cosine similarity ≥ threshold

    Returns:
        proposed_merges: {type: [[cluster_members], ...]}  (clusters with >1 member)
        canonical_map:   {surface_form: {canonical_id, canonical_name, type}}
    """
    from sentence_transformers import SentenceTransformer

    alias_links = alias_links or {}

    logger.info("Loading embedding model: %s", EMBED_MODEL)
    model = SentenceTransformer(EMBED_MODEL)

    proposed_merges: dict[str, list[list[str]]] = {}
    canonical_map: dict[str, Any] = {}

    for entity_type, names in by_type.items():
        if not names:
            continue

        logger.info("Processing type %-25s  %d unique names", entity_type, len(names))

        name_index = {n: i for i, n in enumerate(names)}
        uf = _UnionFind(len(names))

        # Pass 1 — alias-based merges (handles acronym ↔ full-name)
        for canonical_name, aliases in alias_links.items():
            if canonical_name not in name_index:
                continue
            for alias in aliases:
                if alias in name_index:
                    uf.union(name_index[canonical_name], name_index[alias])
                    logger.debug("Alias merge: %r ← %r", canonical_name, alias)

        # Pass 2 — embedding similarity merges
        embeddings = model.encode(names, normalize_embeddings=True, show_progress_bar=False)
        sim = np.dot(embeddings, embeddings.T)
        for i in range(len(names)):
            for j in range(i + 1, len(names)):
                if sim[i, j] >= threshold:
                    uf.union(i, j)

        clusters = uf.clusters(names)

        merges = [sorted(c) for c in clusters if len(c) > 1]
        if merges:
            proposed_merges[entity_type] = merges

        for cluster in clusters:
            canonical_name = _elect_canonical(cluster)
            canonical_id   = _make_canonical_id(entity_type, canonical_name)
            entry = {"canonical_id": canonical_id, "canonical_name": canonical_name, "type": entity_type}
            for surface in cluster:
                canonical_map[surface] = entry

    return proposed_merges, canonical_map


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------

def save_canonical_map(canonical_map: dict[str, Any], path: Path = CANONICAL_MAP_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(canonical_map, indent=2, ensure_ascii=False))
    logger.info("Saved canonical_map (%d entries) → %s", len(canonical_map), path)


def load_canonical_map(path: Path = CANONICAL_MAP_PATH) -> dict[str, Any]:
    return json.loads(Path(path).read_text())
