"""Stage 2: PDF Extraction Module.

Routes each PDF to the correct extractor:
  - text-based PDFs  → pymupdf4llm markdown (preserves headings / lists)
  - scanned PDFs     → pytesseract OCR (page images via pdf2image)

Tables are always extracted separately via pdfplumber and kept atomic.

Every content item carries:
  {doc_id, filename, page_num, content_type: "text" | "table"}

Output: output/extractions/<doc_id>.json  (one file per PDF)
Re-run safe: skips PDFs whose checksum hasn't changed.
"""
from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path
from typing import Any

import pdfplumber
import pymupdf4llm

logger = logging.getLogger(__name__)

# Pages with fewer embedded characters than this are treated as scanned.
_SCANNED_CHAR_THRESHOLD = 100


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _doc_id(path: Path) -> str:
    """Stable 8-char ID derived from the filename stem."""
    return hashlib.md5(path.name.encode()).hexdigest()[:8]


def _checksum(path: Path) -> str:
    return hashlib.md5(path.read_bytes()).hexdigest()


def _table_to_markdown(rows: list[list[str | None]]) -> str:
    """Convert a pdfplumber table (list of rows) to a markdown table string."""
    if not rows:
        return ""
    cleaned = [[str(cell).strip() if cell is not None else "" for cell in row] for row in rows]
    header, *body = cleaned
    sep = ["---"] * len(header)
    lines = [
        "| " + " | ".join(header) + " |",
        "| " + " | ".join(sep) + " |",
    ]
    for row in body:
        # pad/trim to header width
        row = (row + [""] * len(header))[: len(header)]
        lines.append("| " + " | ".join(row) + " |")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Scanned detection
# ---------------------------------------------------------------------------

def _is_scanned(path: Path) -> bool:
    """Return True if the average embedded character count per page is below threshold."""
    try:
        with pdfplumber.open(path) as pdf:
            if not pdf.pages:
                return True
            total_chars = sum(len(p.extract_text() or "") for p in pdf.pages)
            avg = total_chars / len(pdf.pages)
            logger.debug("%s  avg chars/page=%.0f  threshold=%d", path.name, avg, _SCANNED_CHAR_THRESHOLD)
            return avg < _SCANNED_CHAR_THRESHOLD
    except Exception as exc:
        logger.warning("Could not inspect %s for scan detection: %s", path.name, exc)
        return False


# ---------------------------------------------------------------------------
# Table extraction (always run, regardless of PDF type)
# ---------------------------------------------------------------------------

def _extract_tables(path: Path, doc_id: str) -> list[dict[str, Any]]:
    """Extract all tables from a PDF, one item per table."""
    items: list[dict[str, Any]] = []
    try:
        with pdfplumber.open(path) as pdf:
            for page in pdf.pages:
                for table in page.extract_tables():
                    if not table:
                        continue
                    items.append({
                        "doc_id": doc_id,
                        "filename": path.name,
                        "page_num": page.page_number,
                        "content_type": "table",
                        "text": _table_to_markdown(table),
                        "raw_table": table,
                    })
    except Exception as exc:
        logger.warning("Table extraction failed for %s: %s", path.name, exc)
    return items


# ---------------------------------------------------------------------------
# Text PDF extraction
# ---------------------------------------------------------------------------

def _extract_text_pdf(path: Path, doc_id: str) -> list[dict[str, Any]]:
    """Extract markdown text from a text-based PDF using pymupdf4llm."""
    items: list[dict[str, Any]] = []
    try:
        chunks: list[dict[str, Any]] = pymupdf4llm.to_markdown(str(path), page_chunks=True)
        for chunk in chunks:
            text: str = chunk.get("text", "").strip()
            if not text:
                continue
            # pymupdf4llm page numbers are 0-based
            page_num: int = chunk.get("metadata", {}).get("page", 0) + 1
            items.append({
                "doc_id": doc_id,
                "filename": path.name,
                "page_num": page_num,
                "content_type": "text",
                "text": text,
            })
    except Exception as exc:
        logger.error("Text extraction failed for %s: %s", path.name, exc)
    return items


# ---------------------------------------------------------------------------
# Scanned PDF extraction via pytesseract
# ---------------------------------------------------------------------------

def _extract_scanned_pdf(path: Path, doc_id: str) -> list[dict[str, Any]]:
    """OCR each page of a scanned PDF using pytesseract + pdf2image."""
    try:
        import pytesseract
        from pdf2image import convert_from_path
    except ImportError:
        logger.error(
            "pytesseract / pdf2image not installed — cannot OCR scanned PDF %s. "
            "Install with: pip install pytesseract pdf2image  (also needs 'tesseract' binary).",
            path.name,
        )
        return []

    items: list[dict[str, Any]] = []
    try:
        images = convert_from_path(str(path))
        for page_num, image in enumerate(images, start=1):
            text = pytesseract.image_to_string(image).strip()
            if text:
                items.append({
                    "doc_id": doc_id,
                    "filename": path.name,
                    "page_num": page_num,
                    "content_type": "text",
                    "text": text,
                    "extraction_method": "ocr",
                })
    except Exception as exc:
        logger.error("OCR failed for %s: %s", path.name, exc)
    return items


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def extract_pdf(path: Path, output_dir: Path) -> dict[str, Any]:
    """Extract one PDF and write output/<doc_id>.json.

    Returns the result dict (already saved to disk).
    Skips processing if the PDF checksum hasn't changed since last run.
    """
    path = Path(path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    doc_id = _doc_id(path)
    checksum = _checksum(path)
    out_path = output_dir / f"{doc_id}.json"

    # --- skip if unchanged ---
    if out_path.exists():
        existing = json.loads(out_path.read_text())
        if existing.get("checksum") == checksum:
            logger.info("SKIP %s (unchanged)", path.name)
            return existing

    scanned = _is_scanned(path)
    method = "ocr" if scanned else "text"
    logger.info("PROCESS %s  [%s]  doc_id=%s", path.name, method, doc_id)

    if scanned:
        text_items = _extract_scanned_pdf(path, doc_id)
    else:
        text_items = _extract_text_pdf(path, doc_id)

    table_items = _extract_tables(path, doc_id)

    # Merge and sort by page number, tables after text on the same page.
    all_items = sorted(
        text_items + table_items,
        key=lambda x: (x["page_num"], 0 if x["content_type"] == "text" else 1),
    )

    result: dict[str, Any] = {
        "doc_id": doc_id,
        "filename": path.name,
        "filepath": str(path.resolve()),
        "extraction_method": method,
        "checksum": checksum,
        "page_count": max((x["page_num"] for x in all_items), default=0),
        "item_count": len(all_items),
        "table_count": sum(1 for x in all_items if x["content_type"] == "table"),
        "content": all_items,
    }

    out_path.write_text(json.dumps(result, indent=2, ensure_ascii=False))
    logger.info(
        "DONE %s  pages=%d  text_items=%d  tables=%d",
        path.name,
        result["page_count"],
        len(text_items),
        len(table_items),
    )
    return result
