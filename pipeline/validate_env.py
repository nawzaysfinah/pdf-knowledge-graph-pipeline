"""Run to verify all pipeline dependencies and credentials before starting."""
from __future__ import annotations

import sys
import os

REQUIRED_IMPORTS = [
    ("pymupdf4llm",           "marker-pdf / pymupdf4llm"),
    ("pdfplumber",            "pdfplumber"),
    ("sentence_transformers", "sentence-transformers"),
    ("sklearn",               "scikit-learn"),
    ("neo4j",                 "neo4j"),
    ("numpy",                 "numpy"),
    ("tqdm",                  "tqdm"),
    ("dotenv",                "python-dotenv"),
    ("requests",              "requests"),
]

REQUIRED_ENV = [
    "OLLAMA_URL",
    "OLLAMA_MODEL",
    "NEO4J_URI",
    "NEO4J_USER",
    "NEO4J_PASSWORD",
]


def check_imports() -> list[str]:
    errors: list[str] = []
    print("\nChecking imports:")
    for module, package in REQUIRED_IMPORTS:
        try:
            __import__(module)
            print(f"  [OK]     {package}")
        except ImportError as exc:
            print(f"  [MISSING] {package}  ({exc})")
            errors.append(package)
    return errors


def check_env() -> list[str]:
    from dotenv import load_dotenv
    load_dotenv()
    errors: list[str] = []
    print("\nChecking environment variables:")
    for key in REQUIRED_ENV:
        val = os.getenv(key)
        if val:
            masked = ("*" * 8) + val[-4:] if len(val) > 4 else "****"
            print(f"  [OK]     {key} = {masked}")
        else:
            print(f"  [MISSING] {key}")
            errors.append(key)
    return errors


if __name__ == "__main__":
    import_errors = check_imports()
    env_errors = check_env()
    total = len(import_errors) + len(env_errors)
    print()
    if total:
        print(f"  {total} issue(s) found — fix before proceeding.")
        sys.exit(1)
    else:
        print("  All dependencies and credentials OK. Ready to run the pipeline.")
