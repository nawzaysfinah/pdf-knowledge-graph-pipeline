"""CLI runner for Stage 2: PDF Extraction.

Usage:
    python -m pipeline.run_extract                  # process all PDFs in ./pdfs/
    python -m pipeline.run_extract path/to/file.pdf # process a single PDF
"""
from __future__ import annotations

import json
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

from pipeline.pdf_extractor import extract_pdf

load_dotenv()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(message)s",
    datefmt="%H:%M:%S",
)

PDF_DIR = Path("pdfs")
OUTPUT_DIR = Path("output") / "extractions"


def main(targets: list[Path]) -> None:
    if not targets:
        print(f"No PDFs found in {PDF_DIR}/", file=sys.stderr)
        sys.exit(1)

    print(f"\nExtracting {len(targets)} PDF(s) → {OUTPUT_DIR}/\n")

    summary: list[dict] = []
    for path in targets:
        result = extract_pdf(path, OUTPUT_DIR)
        summary.append({
            "filename": result["filename"],
            "doc_id": result["doc_id"],
            "method": result["extraction_method"],
            "pages": result["page_count"],
            "text_items": result["item_count"] - result["table_count"],
            "tables": result["table_count"],
        })

    print("\n── Extraction Summary ──────────────────────────────")
    print(f"  {'Filename':<35} {'doc_id':<10} {'Method':<6} {'Pages':>5} {'Text':>5} {'Tables':>6}")
    print(f"  {'-'*35} {'-'*10} {'-'*6} {'-'*5} {'-'*5} {'-'*6}")
    for r in summary:
        print(
            f"  {r['filename']:<35} {r['doc_id']:<10} {r['method']:<6}"
            f" {r['pages']:>5} {r['text_items']:>5} {r['tables']:>6}"
        )
    print(f"\n  Output: {OUTPUT_DIR.resolve()}/")


if __name__ == "__main__":
    if len(sys.argv) > 1:
        targets = [Path(p) for p in sys.argv[1:] if Path(p).suffix.lower() == ".pdf"]
    else:
        targets = sorted(PDF_DIR.glob("*.pdf"))
    main(targets)
