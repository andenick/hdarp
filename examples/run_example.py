#!/usr/bin/env python3
"""
Runnable HDARP example.

Everything here uses only the light dependencies (pypdf, Pillow, numpy) — no
OCR engine needs to be installed to run it.

    python examples/run_example.py                # synthetic PDF, chunk + consensus
    python examples/run_example.py my_paper.pdf   # chunk a real PDF instead

What it shows:
  1. Density assessment and adaptive chunking of a PDF (splitter).
  2. The manifest the splitter writes, which the batch orchestrator reads back.
  3. Six consensus adjudications, with the rule that actually fires each time.

Note on OCR: running the OCR engines themselves needs `pip install -e ".[ocr]"`
plus a Tesseract binary; this example deliberately does not require them.
"""

import json
import sys
import tempfile
from pathlib import Path

# Allow `python examples/run_example.py` from a clone without installing.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from hdarp import PDFSplitterOrchestrator, Sraffa30ConsensusEngine  # noqa: E402


def make_sample_pdf(path: Path, pages: int = 12) -> Path:
    from pypdf import PdfWriter

    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        writer.write(f)
    return path


def demo_splitter(pdf_path: Path, out_dir: Path) -> None:
    print("=" * 70)
    print("1. Density assessment and chunking")
    print("=" * 70)

    splitter = PDFSplitterOrchestrator(max_chunk_size_mb=1.0, max_chunk_pages=5,
                                       verbose=False)

    report = splitter.assess_pdf_density(str(pdf_path))
    print(f"  Pages:      {report.total_pages}")
    print(f"  Size:       {report.total_size_mb:.3f} MB")
    print(f"  Density:    {report.avg_density:.4f} MB/page -> {report.density_category}")
    print(f"  Strategy:   {report.recommended_strategy}")
    print(f"  Estimated:  {report.estimated_chunks} chunks")

    result = splitter.chunk_pdf_intelligent(str(pdf_path), str(out_dir))
    if not result.success:
        print(f"  Chunking failed: {result.error_message}")
        return

    print(f"\n  Created {len(result.chunks)} chunks:")
    for chunk in result.chunks:
        print(f"    chunk {chunk.chunk_num:>2}: pages {chunk.start_page}-{chunk.end_page} "
              f"({chunk.size_mb:.3f} MB, {chunk.status})")

    print("\n" + "=" * 70)
    print("2. Manifest (this is what the batch orchestrator reads back)")
    print("=" * 70)
    with open(result.manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)
    for key in ("document_name", "hdarp_version", "chunks_created",
                "density_category", "strategy_used"):
        print(f"  {key}: {manifest[key]}")


def demo_consensus() -> None:
    print("\n" + "=" * 70)
    print("3. Consensus adjudication (which rule fires, and why)")
    print("=" * 70)

    engine = Sraffa30ConsensusEngine()

    cases = [
        ("all three agree",
         dict(paddle_text="Total Revenue: $1,234,567", paddle_conf=0.92,
              easyocr_text="Total Revenue: $1,234,567", easyocr_conf=0.90,
              tesseract_text="Total Revenue: $1,234,567", tesseract_conf=0.88)),
        ("two of three agree",
         dict(paddle_text="Total Revenue: $1,234,567", paddle_conf=0.92,
              easyocr_text="Total Revenue: $1,234,567", easyocr_conf=0.88,
              tesseract_text="Total Revenue: $l,234,567", tesseract_conf=0.75)),
        ("one engine confident, others gave up",
         dict(paddle_text="Quarterly Report", paddle_conf=0.97,
              easyocr_text="", easyocr_conf=0.20,
              tesseract_text="Quart ly", tesseract_conf=0.35)),
        ("numeric column, engines disagree",
         dict(paddle_text="1O5.3", paddle_conf=0.85,
              easyocr_text="lO5.3", easyocr_conf=0.40,
              column_type="NUMERIC")),
        ("close but not identical",
         dict(paddle_text="Financial Statement", paddle_conf=0.88,
              easyocr_text="Financial Statment", easyocr_conf=0.86)),
        ("no agreement at all",
         dict(paddle_text="Alpha", paddle_conf=0.75,
              easyocr_text="Beta", easyocr_conf=0.72,
              tesseract_text="Gamma", tesseract_conf=0.70)),
    ]

    for label, kwargs in cases:
        result = engine.adjudicate(**kwargs)
        print(f"\n  {label}")
        print(f"    text:       {result.text!r}")
        print(f"    rule:       {result.rule_applied}")
        print(f"    confidence: {result.confidence:.3f}")

    print("\n  Rule usage this run:")
    stats = engine.get_statistics()
    for rule, data in stats.items():
        if rule != "total_adjudications" and isinstance(data, dict) and data["count"]:
            print(f"    {rule}: {data['count']}")

    print("\n  Reminder: the engine always returns a text. It applies no minimum")
    print("  confidence threshold and marks no gaps - apply your own floor to")
    print("  result.confidence if your use case needs one.")


def main() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if len(sys.argv) > 1:
            pdf_path = Path(sys.argv[1])
            if not pdf_path.exists():
                print(f"PDF not found: {pdf_path}")
                sys.exit(1)
        else:
            pdf_path = make_sample_pdf(tmp_path / "sample.pdf")
            print(f"(no PDF given - generated a 12-page blank sample at {pdf_path})\n")

        demo_splitter(pdf_path, tmp_path / "chunks_out")
        demo_consensus()


if __name__ == "__main__":
    main()
