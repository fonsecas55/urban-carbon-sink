"""Batch PDF text extraction for the project's scientific literature.

Writes <name>.txt next to each source PDF in tools/literature/. Skips files
already extracted unless the source PDF is newer.
"""
from __future__ import annotations
import sys
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = Path(__file__).resolve().parent / "literature"
OUT_DIR.mkdir(parents=True, exist_ok=True)

SOURCES = [
    ROOT / "The Utility of Sentinel-2 Spectral Data in Quantifying.pdf",
    ROOT / "atmosphere-14-01161-v3.pdf",
    ROOT / "bg-22-725-2025.pdf",
    ROOT / "remotesensing-17-00488-v3.pdf",
    ROOT / "ChinesProject" / "gmd-15-6919-2022-supplement-title-page.pdf",
    ROOT / "ChinesProject" / "Supplement" / "RS_data_driven_CASA" / "How to run CASA model code.pdf",
]


def extract(src: Path) -> Path:
    safe = src.stem.replace(" ", "_")
    dst = OUT_DIR / f"{safe}.txt"
    if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
        return dst
    reader = PdfReader(src)
    with dst.open("w", encoding="utf-8") as f:
        for i, page in enumerate(reader.pages, start=1):
            f.write(f"\n===== PAGE {i} =====\n")
            f.write(page.extract_text() or "")
            f.write("\n")
    return dst


def main() -> int:
    rows = []
    for src in SOURCES:
        if not src.exists():
            rows.append((src.name, "MISSING", 0, 0))
            continue
        dst = extract(src)
        reader = PdfReader(src)
        rows.append((src.name, dst.name, len(reader.pages), dst.stat().st_size))
    width = max(len(r[0]) for r in rows) + 2
    for name, out, pages, size in rows:
        print(f"{name:<{width}} -> {out:<55} pages={pages:<3} size={size}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
