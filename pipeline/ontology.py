"""Ontology loader for the knowledge graph pipeline.

Reads output/ontology.json and exposes typed structures used by
Stage 5 (triple extraction) and Stage 7 (validation).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ONTOLOGY_PATH = Path("output") / "ontology.json"


@dataclass
class EntityType:
    type: str
    description: str
    examples: list[str]


@dataclass
class RelationshipType:
    predicate: str
    description: str
    allowed_subject_types: list[str]
    allowed_object_types: list[str]


@dataclass
class Ontology:
    domain: str
    version: str
    entity_types: list[EntityType]
    relationship_types: list[RelationshipType]
    notes: list[str]

    # Fast lookup sets built on load
    valid_entity_type_names: set[str] = field(default_factory=set)
    predicate_constraints: dict[str, dict[str, list[str]]] = field(default_factory=dict)

    def __post_init__(self) -> None:
        self.valid_entity_type_names = {e.type for e in self.entity_types}
        self.predicate_constraints = {
            r.predicate: {
                "subject": r.allowed_subject_types,
                "object": r.allowed_object_types,
            }
            for r in self.relationship_types
        }

    def is_valid_triple(
        self,
        subject_type: str,
        predicate: str,
        object_type: str,
    ) -> bool:
        """Return True if this subject→predicate→object combination is allowed."""
        constraint = self.predicate_constraints.get(predicate)
        if not constraint:
            return False
        return (
            subject_type in constraint["subject"]
            and object_type in constraint["object"]
        )


def load_ontology(path: Path = ONTOLOGY_PATH) -> Ontology:
    data: dict[str, Any] = json.loads(Path(path).read_text())
    return Ontology(
        domain=data["domain"],
        version=data["version"],
        entity_types=[EntityType(**e) for e in data["entity_types"]],
        relationship_types=[RelationshipType(**r) for r in data["relationship_types"]],
        notes=data.get("notes", []),
    )


def print_summary(ontology: Ontology) -> None:
    """Print a formatted summary table of entity and relationship types."""
    width = 80

    print("\n" + "=" * width)
    print(f"  Ontology: {ontology.domain}  (v{ontology.version})")
    print("=" * width)

    print(f"\n  ENTITY TYPES  ({len(ontology.entity_types)})")
    print(f"  {'Type':<28} {'Description':<45} Examples")
    print(f"  {'-'*28} {'-'*45} {'-'*20}")
    for e in ontology.entity_types:
        ex = ", ".join(e.examples[:2])
        desc = e.description[:44]
        print(f"  {e.type:<28} {desc:<45} {ex}")

    print(f"\n  RELATIONSHIP TYPES  ({len(ontology.relationship_types)})")
    print(f"  {'Predicate':<22} {'Allowed Subjects':<38} Allowed Objects")
    print(f"  {'-'*22} {'-'*38} {'-'*30}")
    for r in ontology.relationship_types:
        subj = ", ".join(r.allowed_subject_types[:3])
        obj  = ", ".join(r.allowed_object_types[:3])
        print(f"  {r.predicate:<22} {subj:<38} {obj}")

    print(f"\n  Notes:")
    for note in ontology.notes:
        print(f"    • {note}")
    print("=" * width + "\n")
