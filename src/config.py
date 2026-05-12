"""Application configuration and path helpers."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os

from dotenv import load_dotenv


@dataclass(frozen=True)
class Neo4jSettings:
    uri: str
    user: str
    password: str
    database: str


@dataclass(frozen=True)
class OllamaSettings:
    base_url: str
    model: str


@dataclass(frozen=True)
class PathSettings:
    root: Path
    data_raw: Path
    data_canonical: Path
    data_sample: Path
    mapping_config: Path
    mapping_config_sample: Path
    review_db: Path
    reports_dir: Path
    neo4j_constraints: Path
    neo4j_indexes: Path
    neo4j_postcompute: Path


@dataclass(frozen=True)
class AppConfig:
    neo4j: Neo4jSettings
    ollama: OllamaSettings
    paths: PathSettings
    log_level: str


def project_root() -> Path:
    """Resolve repository root based on src/config.py location."""
    return Path(__file__).resolve().parents[1]


def load_config() -> AppConfig:
    """Load env vars and compute path configuration."""
    load_dotenv(project_root() / ".env")
    root = project_root()

    paths = PathSettings(
        root=root,
        data_raw=root / "data" / "raw",
        data_canonical=root / "data" / "canonical",
        data_sample=root / "data" / "sample",
        mapping_config=root / "data" / "mapping" / "mapping_config.yaml",
        mapping_config_sample=root / "data" / "mapping" / "mapping_config.sample.yaml",
        review_db=root / "data" / "canonical" / "review_store.sqlite",
        reports_dir=root / "reports",
        neo4j_constraints=root / "neo4j" / "constraints.cypher",
        neo4j_indexes=root / "neo4j" / "indexes.cypher",
        neo4j_postcompute=root / "neo4j" / "load" / "postcompute.cypher",
    )

    return AppConfig(
        neo4j=Neo4jSettings(
            uri=os.getenv("NEO4J_URI", "bolt://localhost:7687"),
            user=os.getenv("NEO4J_USER", "neo4j"),
            password=os.getenv("NEO4J_PASSWORD", "changeme"),
            database=os.getenv("NEO4J_DATABASE", "neo4j"),
        ),
        ollama=OllamaSettings(
            base_url=os.getenv("OLLAMA_URL", "http://localhost:11434"),
            model=os.getenv("OLLAMA_MODEL", "qwen3:latest"),
        ),
        paths=paths,
        log_level=os.getenv("LOG_LEVEL", "INFO"),
    )
