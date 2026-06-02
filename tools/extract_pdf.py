"""One-shot PDF text extractor. Output written next to script as relatorio_final.txt."""
from pathlib import Path
from pypdf import PdfReader

ROOT = Path(__file__).resolve().parent.parent
src = ROOT / "RELATORIOS" / "Relatório Final-P33.pdf"
dst = Path(__file__).resolve().parent / "relatorio_final.txt"

reader = PdfReader(src)
with dst.open("w", encoding="utf-8") as f:
    for i, page in enumerate(reader.pages, start=1):
        f.write(f"\n===== PAGE {i} =====\n")
        f.write(page.extract_text() or "")
        f.write("\n")

print(f"Pages: {len(reader.pages)}")
print(f"Output: {dst}")
print(f"Size: {dst.stat().st_size} bytes")
