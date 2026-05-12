"""CLI runner for Stage 6: Entity Resolution.

Displays proposed entity merges, asks for confirmation, then saves
canonical_map.json.

Usage:
    python -m pipeline.run_resolve
    python -m pipeline.run_resolve --auto-confirm   # skip interactive prompt
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline.entity_resolver import (
    CANONICAL_MAP_PATH,
    EXTRACTIONS_PATH,
    collect_entities,
    resolve_entities,
    save_canonical_map,
)

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)

AUTO_CONFIRM = "--auto-confirm" in sys.argv


def _print_merges(proposed_merges: dict) -> None:
    total = sum(len(v) for v in proposed_merges.values())
    if not total:
        print("\n  No merge candidates found (all entities are already distinct).")
        return

    print(f"\n── Proposed Entity Merges  ({total} cluster(s)) ─────────────────")
    for entity_type, clusters in proposed_merges.items():
        print(f"\n  [{entity_type}]")
        for cluster in clusters:
            # Longest name is the canonical (elected in resolve_entities)
            canonical = max(cluster, key=lambda n: (len(n), n))
            others    = [n for n in cluster if n != canonical]
            print(f"    CANONICAL : {canonical!r}")
            for alt in others:
                print(f"    MERGE  ←  {alt!r}")
            print()


def _print_all_entities(by_type: dict) -> None:
    total = sum(len(v) for v in by_type.values())
    print(f"\n── All Entities Collected  ({total} unique surface forms) ────────")
    for etype, names in by_type.items():
        print(f"\n  [{etype}]  {len(names)} name(s)")
        for name in names:
            print(f"    • {name}")


def main() -> None:
    if not EXTRACTIONS_PATH.exists():
        print(f"ERROR: {EXTRACTIONS_PATH} not found. Run Stage 5 first.")
        sys.exit(1)

    print(f"\n  Input  : {EXTRACTIONS_PATH}")
    print(f"  Output : {CANONICAL_MAP_PATH}")

    # Step 1 — collect
    print("\nCollecting entities from extractions...")
    by_type, alias_links = collect_entities(EXTRACTIONS_PATH)
    _print_all_entities(by_type)

    # Step 2 — resolve (alias pass + embed + cluster)
    print("\nEmbedding and clustering (this may take a moment on first run)...")
    proposed_merges, canonical_map = resolve_entities(by_type, alias_links)

    # Step 3 — show proposed merges
    _print_merges(proposed_merges)

    # Step 4 — confirmation
    if not AUTO_CONFIRM:
        print("─" * 60)
        answer = input(
            "  Apply these merges and save canonical_map.json? [y/n]: "
        ).strip().lower()
        if answer not in ("y", "yes"):
            print("\n  Aborted. No changes written.")
            sys.exit(0)
    else:
        print("  (--auto-confirm: applying merges without prompt)")

    # Step 5 — save
    save_canonical_map(canonical_map)

    # Summary
    merged_count = sum(
        len(cluster) - 1
        for clusters in proposed_merges.values()
        for cluster in clusters
    )
    print(f"\n── Resolution Summary ───────────────────────────────────")
    print(f"  Unique surface forms  : {len(canonical_map)}")
    print(f"  Canonical entities    : {len(set(v['canonical_id'] for v in canonical_map.values()))}")
    print(f"  Surface forms merged  : {merged_count}")
    print(f"\n  Saved → {CANONICAL_MAP_PATH.resolve()}")


if __name__ == "__main__":
    main()
