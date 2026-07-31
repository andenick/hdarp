# HDARP Architecture

## Scope of this package

This repository publishes the **OCR-consensus layer** of the in-house protocol the acronym HDARP
comes from (*Hybrid Direct Agent Reading Protocol*). The agent-reading half of that protocol is
**not** in this repository: nothing here calls a language or vision model, and nothing here
produces tables, equations or figure descriptions. What is here is PDF chunking, three OCR engine
wrappers, a six-rule consensus adjudicator, a sequential batch pipeline, and a standalone quality
scorer. See the README's "What this package does **not** do" for the full list.

## Design Goals

The layer was built to feed large document corpora into downstream scholarly and regulatory
analysis. Three principles guide every design decision:

1. **Accuracy over speed** — Three OCR engines are slower than one, but the consensus mechanism catches errors no single engine would.
2. **Transparency over opacity** — Every extraction includes a full audit trail.
3. **Safety over convenience** — Never present a guess as a reading. See [§4](#4-what-this-snapshot-does-and-does-not-do-about-fabrication) for what that principle does and does not amount to in the shipped code.

## High-Level Pipeline

```
PDF Input
   │
   ├─→ Density Assessment (splitter.py)
   │     Calculates MB/page, classifies LOW/MED/HIGH
   │     Selects PAGE_FIRST or SIZE_FIRST strategy
   │
   ├─→ Intelligent Chunking (splitter.py)
   │     Creates chunks ≤1MB, ≤10 pages
   │     Retries with fewer pages if oversized
   │     Accepts oversized single pages with warning
   │
   ├─→ Embedded-text pre-check (ocr_engines.py)
   │     PDF already has a text layer? Copy it verbatim and stop.
   │     No OCR, no consensus, no confidence reported.
   │
   ├─→ Sraffa 3.0 OCR (ocr_engines.py + consensus.py)   [no text layer]
   │     PaddleOCR + EasyOCR + Tesseract, per rendered page
   │     6-rule consensus adjudication, per line
   │     95-98% accuracy (indicative — see Performance)
   │
   └─→ Output
       plain text per document + a CSV catalog (orchestrator.py)

Off to the side, called by nothing above:
   quality_scorer.py — 27-point scoring for extractions you assemble yourself
```

## Key Architectural Decisions

### 1. Why Three OCR Engines?

Each engine has different strengths:

- **PaddleOCR**: Best raw accuracy on modern documents, weakest on Asian scripts
- **EasyOCR**: Strong on degraded/historical scans, slower
- **Tesseract**: Fast, reliable baseline, weak on stylized fonts

When all three agree, we have very high confidence. When they disagree, the disagreement pattern tells us *why* — and the 6-rule consensus often picks the right answer anyway.

See `CONSENSUS_RULES.md` for the full rule hierarchy.

### 2. Why Density-Aware Chunking?

A 100-page text-heavy academic paper and a 100-page image-heavy annual report behave very differently when chunked:

- Text-heavy: 10 pages per chunk easily fits in 1MB
- Image-heavy: 10 pages might be 50MB

The density classifier (LOW < 0.05 MB/page, MEDIUM 0.05-0.10, HIGH > 0.10) selects the right strategy:

- **PAGE_FIRST**: Maximize pages per chunk (good for text)
- **SIZE_FIRST**: Strict size limits with retry (good for images)

This is the difference between processing a corpus correctly and failing on the first scanned book.

### 3. Why a Quality Scorer?

OCR confidence scores are not comparable across engines and don't map cleanly to "is this extraction good enough." The 27-point framework gives a single weighted score:

| Component | Max Points | Scoreable from this package's own output? |
|-----------|-----------|-------------------------------------------|
| Text | 4 | Yes — from the extracted text |
| Formatting | 3 | Yes — from the extracted text |
| OCR Confidence | 2 | Yes — from the mean consensus confidence |
| Tables | 8 | No — caller-supplied |
| Equations | 3 | No — caller-supplied |
| Figures | 3 | No — caller-supplied |
| Metadata | 4 | No — caller-supplied |

Read that second column before using the score. **The scorer is a standalone utility in this
snapshot** — `orchestrator.py` does not call it, and this package produces no tables, equations,
figures or document metadata for it to score. Fed only what this package emits, an extraction caps
at 9/27, which grades F; that is a property of the inputs, not of the extraction. The 18
caller-fed points are retained because the scoring logic is sound and useful to anyone holding
those artifacts from another tool.

The catalog's `quality_score` column is a different number entirely: it holds the mean OCR
consensus confidence (0-1), or nothing at all when no confidence was measured.

### 4. What this snapshot does (and does not do) about fabrication

A fabricated number is worse than a missing number. In scholarly contexts, missing data is a known unknown — you handle it explicitly. Fabricated data is an unknown unknown — it corrupts everything downstream.

What the shipped code does towards that:

- **Audit trail**: every result records which rule fired, which engines contributed, and what alternatives were considered.
- **No invented confidence**: the embedded-text path runs no OCR and no consensus, so it reports `confidence: None` rather than a hardcoded 1.0, and the catalog stores nothing rather than a perfect score.
- **Floored confidences are labelled as such**: the one place where a reported confidence is a constant rather than a measurement is Rule 6's 0.60 floor, and a floored result says so in `metadata["confidence_floor_applied"]` while keeping the engine's own number in `metadata["primary_engine_confidence"]`.

What it does **not** do, and you must therefore do yourself:

- **There is no confidence threshold and no gap marker.** Rule 6 always returns the primary engine's text, and its `max(0.60, conf × 0.9)` floor raises a distrusted read to 0.60 instead of dropping it. Apply your own floor to `result.confidence` (or to `metadata["primary_engine_confidence"]`).
- **There is no content-filter or refusal handling here**, because this package makes no model call that could be filtered.

## Module Responsibilities

Line counts are `wc -l` of the files in this commit.

### `splitter.py` (451 LOC)
- Density assessment
- Adaptive chunking (PAGE_FIRST vs SIZE_FIRST)
- Retry logic for oversized chunks
- Manifest generation

### `consensus.py` (661 LOC)
- 6-rule adjudication hierarchy
- Probabilistic confidence combination
- Statistics tracking
- Numeric cleaning for column-type validation

### `ocr_engines.py` (494 LOC)
- Unified interface for PaddleOCR, EasyOCR, Tesseract
- Engine initialization and warmup
- Result normalization
- Embedded-text pre-check (PyMuPDF; not OCR, not measured)

### `processor.py` (332 LOC)
- Multi-engine OCR orchestration
- Coordinates engines + consensus
- Error handling and recovery

### `orchestrator.py` (444 LOC)
- Batch pipeline state management (sequential; no validator, no concurrency)
- Automatic batch continuation
- Reads back the splitter's manifest and processes each chunk in order
- Catalog synchronisation (CSV)

### `quality_scorer.py` (320 LOC)
- 27-point weighted scoring framework
- Per-component metrics
- Quality grade assignment (A-F)
- Standalone: the batch pipeline does not call it

## Performance

The figures below are **indicative**, not benchmark results — illustrative ranges observed across academic papers, books, and regulatory documents during development. No formal benchmark dataset or reproducible eval harness is published with this repo; treat these as order-of-magnitude guidance, not measured claims:

| Metric | Single Engine | HDARP Consensus |
|--------|--------------|-----------------|
| Text accuracy (clean scans) | 88-92% | 95-98% |
| Text accuracy (degraded) | 70-80% | 85-92% |
| Processing speed | ~1 sec/page | ~3-5 sec/page |

(Two rows have been removed from earlier versions of this table. "Near-zero false positives (gap marking)" went because this package does not gap-mark and no false-positive rate was ever measured — see [§4](#4-what-this-snapshot-does-and-does-not-do-about-fabrication). "Table extraction — high (agent vision)" went because this package extracts no tables at all.)

Indicatively, the 3-5× speed cost buys a meaningful accuracy improvement.

## Design Trade-offs

### What HDARP Optimizes For
- Scholarly accuracy (false positives are catastrophic)
- Auditability (every result has full provenance)
- Resilience (degraded scans, unusual fonts, mixed content)

### What HDARP Does Not Optimize For
- Throughput (3-5 sec/page is slow for high-volume use cases)
- Real-time processing (batch architecture, not streaming)
- Memory efficiency (loads all three OCR engines simultaneously)

For high-throughput use cases, a single-engine pipeline with Tesseract or PaddleOCR alone would be 3-5× faster at the cost of an indicative 7-15 percentage points of accuracy. The right choice depends on how much error your downstream use case can absorb — and, either way, on the confidence floor you apply yourself.

## What a caller drives

The package is a library first and a batch runner second. A caller — a script, a scheduler, or a
person — typically does this:

1. Point `HDARPOrchestrator` at a corpus directory and an output directory.
2. It discovers the PDFs and writes a catalog row per document (`PENDING`).
3. It assesses density and chunks each document, writing `manifest.json` (`PREPARED`).
4. It processes each chunk in order: embedded-text copy if there is a text layer, otherwise
   three-engine OCR with per-line consensus.
5. It writes concatenated text per document, records the mean measured confidence and SHA-256
   input/output hashes, and marks the row `COMPLETE` (or `FAILED`, with the error).
6. It advances to the next batch of `PENDING` documents, unless `--single` was given.

Nothing in that loop validates the output, and nothing runs concurrently. A caller who wants a
quality gate applies its own — a floor on `result.confidence`, or `QualityScorer` fed with
artifacts from elsewhere.

A reviewer can drop into any stage and inspect the full state — what was processed, what consensus
rules fired, which engines contributed, and whether a confidence was measured or floored.
