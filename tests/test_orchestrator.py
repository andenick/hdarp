"""
Assertion tests for the batch orchestrator's chunk handling.

These use a stub processor, so no OCR engine is needed.

Run: python -m pytest
"""

import json

import pytest

from hdarp.orchestrator import HDARPOrchestrator


class StubProcessor:
    """Returns a canned result per chunk, recording the order it was called in."""

    def __init__(self, results):
        self.results = results
        self.seen = []

    def process_pdf(self, pdf_path):
        self.seen.append(pdf_path)
        return self.results.pop(0)


@pytest.fixture()
def orch(tmp_path):
    corpus = tmp_path / "corpus"
    corpus.mkdir()
    return HDARPOrchestrator(corpus_dir=corpus, output_dir=tmp_path / "out")


def _write_manifest(orch, doc_id, chunk_files, create=True):
    doc_dir = orch.output_dir / doc_id
    (doc_dir / "chunks").mkdir(parents=True, exist_ok=True)
    chunks = []
    for i, name in enumerate(chunk_files, start=1):
        path = doc_dir / "chunks" / name
        if create:
            path.write_bytes(b"%PDF-1.4\n")
        chunks.append({"chunk_num": i, "file_path": str(path)})
    (doc_dir / "manifest.json").write_text(json.dumps({"chunks": chunks}), encoding="utf-8")
    return chunks


def test_chunk_paths_returns_chunks_in_order(orch):
    _write_manifest(orch, "doc", ["doc_chunk_01.pdf", "doc_chunk_02.pdf", "doc_chunk_03.pdf"])

    paths = orch.chunk_paths("doc")

    assert [p.name for p in paths] == [
        "doc_chunk_01.pdf", "doc_chunk_02.pdf", "doc_chunk_03.pdf",
    ]


def test_chunk_paths_is_empty_when_nothing_was_prepared(orch):
    assert orch.chunk_paths("never-prepared") == []


def test_chunk_paths_skips_files_missing_from_disk(orch):
    _write_manifest(orch, "doc", ["a.pdf", "b.pdf"])
    (orch.output_dir / "doc" / "chunks" / "b.pdf").unlink()

    assert [p.name for p in orch.chunk_paths("doc")] == ["a.pdf"]


def test_process_chunks_concatenates_in_order_and_averages_confidence(orch):
    _write_manifest(orch, "doc", ["a.pdf", "b.pdf"])
    processor = StubProcessor([
        {"method": "sraffa30_ocr", "text": "first", "confidence": 0.80},
        {"method": "sraffa30_ocr", "text": "second", "confidence": 0.90},
    ])

    result = orch._process_chunks(processor, orch.chunk_paths("doc"))

    assert [p.split("\\")[-1].split("/")[-1] for p in processor.seen] == ["a.pdf", "b.pdf"]
    assert result["chunks_processed"] == 2
    assert result["text"].index("first") < result["text"].index("second")
    assert "<!-- chunk: a.pdf -->" in result["text"]
    assert result["confidence"] == pytest.approx(0.85)


def test_unmeasured_chunks_do_not_count_towards_confidence(orch):
    """A chunk taking the embedded-text path reports None, not 1.0."""
    _write_manifest(orch, "doc", ["a.pdf", "b.pdf"])
    processor = StubProcessor([
        {"method": "pymupdf_embedded", "text": "digital", "confidence": None},
        {"method": "sraffa30_ocr", "text": "scanned", "confidence": 0.70},
    ])

    result = orch._process_chunks(processor, orch.chunk_paths("doc"))

    assert result["confidence"] == pytest.approx(0.70)
    assert result["method"] == "pymupdf_embedded+sraffa30_ocr"


def test_confidence_is_none_when_nothing_was_measured(orch):
    _write_manifest(orch, "doc", ["a.pdf"])
    processor = StubProcessor([
        {"method": "pymupdf_embedded", "text": "digital", "confidence": None},
    ])

    result = orch._process_chunks(processor, orch.chunk_paths("doc"))

    assert result["confidence"] is None


def test_declared_statuses_are_only_the_ones_the_pipeline_assigns(orch):
    assert orch.STATUSES == ["PENDING", "PREPARED", "COMPLETE", "FAILED"]
