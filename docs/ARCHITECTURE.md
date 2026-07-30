# HDARP Architecture

## Design Goals

HDARP was built for one specific use case: **enabling AI agents to reliably extract structured data from large document corpora for scholarly research and regulatory analysis**.

Three principles guide every design decision:

1. **Accuracy over speed** — Three OCR engines are slower than one, but the consensus mechanism catches errors no single engine would.
2. **Transparency over opacity** — Every extraction includes a full audit trail.
3. **Safety over convenience** — Never present a guess as a reading. See [§5](#5-what-this-snapshot-does-and-does-not-do-about-fabrication) for what that principle does and does not amount to in the shipped code.

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
   ├─→ Hybrid Extraction
   │   ├─→ DARP (agent vision)
   │   │     Tables → CSV (98%+ accuracy)
   │   │     Equations → LaTeX
   │   │     Figures → markdown descriptions
   │   │
   │   └─→ Sraffa 3.0 OCR (consensus.py + ocr_engines.py)
   │         PaddleOCR + EasyOCR + Tesseract
   │         6-rule consensus adjudication
   │         95-98% accuracy (indicative — see Performance)
   │
   ├─→ Quality Scoring (quality_scorer.py)
   │     27-point weighted framework
   │     Flags low-quality extractions for review
   │
   └─→ Output
       structured CSV/LaTeX/markdown/text
```

## Key Architectural Decisions

### 1. Why Hybrid (DARP + OCR)?

Pure OCR misses tables. Pure agent vision is expensive at scale. The hybrid approach uses each tool where it's strongest:

- **DARP** (agent vision) for structured content: tables, equations, figures. ~$0.01-0.05 per page.
- **Sraffa 3.0 OCR** (local engines) for body text. Free after one-time model download.

As an illustrative example, a 200-page document with 30 tables incurs far fewer agent calls (paying for ~30 table extractions instead of running agent vision over all 200 pages) — an order-of-magnitude cost saving. The exact ratio depends entirely on document mix; this is a worked example, not a measured figure.

### 2. Why Three OCR Engines?

Each engine has different strengths:

- **PaddleOCR**: Best raw accuracy on modern documents, weakest on Asian scripts
- **EasyOCR**: Strong on degraded/historical scans, slower
- **Tesseract**: Fast, reliable baseline, weak on stylized fonts

When all three agree, we have very high confidence. When they disagree, the disagreement pattern tells us *why* — and the 6-rule consensus often picks the right answer anyway.

See `CONSENSUS_RULES.md` for the full rule hierarchy.

### 3. Why Density-Aware Chunking?

A 100-page text-heavy academic paper and a 100-page image-heavy annual report behave very differently when chunked:

- Text-heavy: 10 pages per chunk easily fits in 1MB
- Image-heavy: 10 pages might be 50MB

The density classifier (LOW < 0.05 MB/page, MEDIUM 0.05-0.10, HIGH > 0.10) selects the right strategy:

- **PAGE_FIRST**: Maximize pages per chunk (good for text)
- **SIZE_FIRST**: Strict size limits with retry (good for images)

This is the difference between processing a corpus correctly and failing on the first scanned book.

### 4. Why a Quality Scorer?

OCR confidence scores are not comparable across engines and don't map cleanly to "is this extraction good enough." The 27-point framework gives a single weighted score:

| Component | Max Points |
|-----------|-----------|
| Tables | 8 |
| Text | 4 |
| Equations | 3 |
| Figures | 3 |
| OCR Confidence | 2 |
| Formatting | 3 |
| Metadata | 4 |

Scores below a threshold get flagged for human review or re-processing with different parameters.

The scorer is a standalone utility in this snapshot — `orchestrator.py` does not call it. The catalog's `quality_score` column holds the mean OCR consensus confidence (0-1), or nothing at all when no confidence was measured.

### 5. What this snapshot does (and does not do) about fabrication

A fabricated number is worse than a missing number. In scholarly contexts, missing data is a known unknown — you handle it explicitly. Fabricated data is an unknown unknown — it corrupts everything downstream.

What the shipped code does towards that:

- **Audit trail**: every result records which rule fired, which engines contributed, and what alternatives were considered.
- **No invented confidence**: the embedded-text path runs no OCR and no consensus, so it reports `confidence: None` rather than a hardcoded 1.0, and the catalog stores nothing rather than a perfect score.

What it does **not** do, and you must therefore do yourself:

- **There is no confidence threshold and no gap marker.** Rule 6 always returns the primary engine's text, and its `max(0.60, conf × 0.9)` floor raises a distrusted read to 0.60 instead of dropping it. Apply your own floor to `result.confidence`.
- **There is no content-filter handling here**, because there is no agent-vision call in this package.

## Module Responsibilities

Line counts are `wc -l` of the files in this commit.

### `splitter.py` (451 LOC)
- Density assessment
- Adaptive chunking (PAGE_FIRST vs SIZE_FIRST)
- Retry logic for oversized chunks
- Manifest generation

### `consensus.py` (635 LOC)
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

### `quality_scorer.py` (318 LOC)
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
| Table extraction | N/A | high (agent vision) |
| Processing speed | ~1 sec/page | ~3-5 sec/page |

(An earlier version of this table claimed "near-zero false positives (gap marking)". That row has been removed: this package does not gap-mark, and no false-positive rate was ever measured. See [§5](#5-what-this-snapshot-does-and-does-not-do-about-fabrication).)

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

## Integration with AI Agent Pipelines

HDARP was designed to run inside Claude Code agent pipelines. The protocol is:

1. Agent identifies a PDF that needs processing
2. Agent calls splitter for density assessment
3. Agent decides chunking strategy (or accepts default)
4. For each chunk: agent calls DARP for tables/equations, OCR for body text
5. Consensus engine adjudicates OCR results
6. Quality scorer evaluates the chunk
7. Catalog is updated with status, score, and metadata
8. Next chunk processes (auto-continuation)

A reviewer can drop into any stage of this pipeline and inspect the full state — what was processed, what consensus rules fired, what the alternatives were.
