"""
Assertion tests for density-aware chunking.

Builds a synthetic PDF with pypdf, so these run with no OCR engine installed.

Run: python -m pytest
"""

import json

import pytest

from pypdf import PdfReader, PdfWriter

from hdarp.splitter import PDFSplitterOrchestrator


def _make_pdf(path, pages):
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)  # US Letter, 72 dpi units
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture()
def pdf_12_pages(tmp_path):
    return _make_pdf(tmp_path / "source.pdf", 12)


def test_density_assessment_classifies_a_text_light_pdf_as_low(pdf_12_pages):
    splitter = PDFSplitterOrchestrator(verbose=False)
    report = splitter.assess_pdf_density(str(pdf_12_pages))

    assert report.total_pages == 12
    assert report.density_category == "LOW"          # blank pages are tiny
    assert report.recommended_strategy == "PAGE_FIRST"
    assert report.estimated_chunks == 2              # ceil(12 / 10)


def test_chunking_covers_every_page_exactly_once(tmp_path, pdf_12_pages):
    splitter = PDFSplitterOrchestrator(max_chunk_pages=5, verbose=False)
    result = splitter.chunk_pdf_intelligent(str(pdf_12_pages), str(tmp_path / "out"))

    assert result.success
    assert [c.page_count for c in result.chunks] == [5, 5, 2]
    assert result.chunks[0].start_page == 1
    assert result.chunks[-1].end_page == 12

    # No gaps, no overlaps.
    covered = []
    for chunk in result.chunks:
        covered.extend(range(chunk.start_page, chunk.end_page + 1))
    assert covered == list(range(1, 13))

    # And the chunk PDFs on disk really hold those pages.
    for chunk in result.chunks:
        assert len(PdfReader(chunk.file_path).pages) == chunk.page_count


def test_manifest_records_the_shipped_version(tmp_path, pdf_12_pages):
    splitter = PDFSplitterOrchestrator(max_chunk_pages=5, verbose=False)
    result = splitter.chunk_pdf_intelligent(str(pdf_12_pages), str(tmp_path / "out"))

    with open(result.manifest_path, encoding="utf-8") as f:
        manifest = json.load(f)

    from hdarp import __version__

    assert manifest["hdarp_version"] == __version__
    assert manifest["chunks_created"] == len(result.chunks)
    assert manifest["total_pages"] == 12


def test_missing_pdf_is_reported_not_raised(tmp_path):
    splitter = PDFSplitterOrchestrator(verbose=False)
    result = splitter.chunk_pdf_intelligent(str(tmp_path / "nope.pdf"), str(tmp_path / "out"))

    assert result.success is False
    assert "not found" in (result.error_message or "").lower()
