# HDARP — Hybrid Direct Agent Reading Protocol

**Production-grade PDF extraction for AI agent pipelines. High body-text accuracy through multi-engine OCR consensus.**

> **Snapshot note**: This repository is a frozen snapshot of the HDARP **v5.1** OCR-consensus layer, released **2026-05-01**. It is preserved as a self-contained reference implementation of the multi-engine consensus approach and is not tracked against later, unpublished versions of the protocol. Everything below describes the code in this repository as of that date.
>
> **On the numbers**: Accuracy and cost figures in this README and `docs/` are **indicative** — illustrative ranges and worked examples drawn from development use, *not* results from a published, reproducible benchmark dataset. No formal benchmark corpus is released with this repo. Treat them as order-of-magnitude guidance, not measured claims.

---

## What HDARP Does

HDARP solves the fundamental problem of getting structured data out of scanned PDFs at scale when you're working with AI agents. It combines two complementary approaches:

1. **DARP (Direct Agent Reading)** for structured content: Uses Claude's vision API to extract tables → CSV (high accuracy), equations → LaTeX, and figures → markdown descriptions.

2. **Sraffa 3.0 Multi-Engine OCR Consensus** for body text: A 3-engine ensemble (PaddleOCR, EasyOCR, Tesseract) with a 6-rule adjudication hierarchy that is, in development use, materially more accurate than any single engine.

> **Version note**: This repo implements the Sraffa 3.0 consensus engine. Later production versions of the engine are not published here.

The result is a hybrid system that uses expensive agent vision only where it matters (tables, equations) and free local OCR where it's sufficient (body text), with intelligent consensus to maximize accuracy.

---

## Key Innovations

### 1. Density-Aware Chunking

Not all PDFs are created equal. A 100-page text-heavy academic paper behaves very differently from a 100-page image-heavy annual report. HDARP calculates the actual MB/page density of each PDF and selects the optimal chunking strategy:

| Density | MB/page | Strategy | Rationale |
|---------|---------|----------|-----------|
| LOW | < 0.05 | PAGE_FIRST | Text-heavy: maximize pages per chunk (up to 10) |
| MEDIUM | 0.05-0.10 | SIZE_FIRST | Mixed: balance pages and size |
| HIGH | > 0.10 | SIZE_FIRST | Image-heavy: strict size limits with retry |

The splitter retries with progressively fewer pages if a chunk exceeds the size limit, and accepts oversized single pages with a warning flag rather than failing.

### 2. Six-Rule OCR Consensus

When three OCR engines look at the same text, how do you decide which one is right? HDARP applies six rules in priority order:

| # | Rule | Confidence | When It Fires |
|---|------|------------|---------------|
| 1 | **Perfect Agreement** | 0.95-0.99 | All engines produce identical text. Confidence: `1 - (1-p₁)(1-p₂)(1-p₃)` |
| 2 | **Majority Agreement** | 0.85-0.95 | 2+ engines agree. 5% confidence boost for consensus. |
| 3 | **High-Confidence Unilateral** | 0.85-0.90 | One engine >95% confidence, others <50%. Trust the confident one. |
| 4 | **Column-Type Validation** | 0.85-0.92 | NUMERIC context catches O→0, I→1 substitutions. Semantic validation. |
| 5 | **Character Similarity** | 0.80-0.90 | >80% character overlap. Weighted by engine priority. |
| 6 | **Default to Primary** | 0.60-0.90 | Fallback to PaddleOCR (highest-priority engine). `max(0.60, conf × 0.9)` — note the floor *raises* a read the engine itself distrusted. |

The probabilistic confidence combination in Rule 1 is mathematically rigorous: if PaddleOCR is 90% confident and EasyOCR is 85% confident and Tesseract is 80% confident, the probability all three are wrong simultaneously is (0.10)(0.15)(0.20) = 0.003 — giving us 99.7% confidence in perfect agreement.

### 3. Quality Scoring Framework

Every extraction is scored on a 27-point weighted scale:

| Component | Max Points | What It Measures |
|-----------|-----------|-----------------|
| Tables | 8 | CSV formatting, header detection, cell accuracy |
| Text | 4 | Character accuracy, word completion, paragraph structure |
| Equations | 3 | LaTeX validity, symbol recognition |
| Figures | 3 | Description completeness, reference accuracy |
| OCR Confidence | 2 | Mean confidence across consensus results |
| Formatting | 3 | Section structure, whitespace, encoding |
| Metadata | 4 | Page numbers, headers/footers, cross-references |

`QualityScorer` is a standalone utility in this snapshot: the batch pipeline does not call it, and 18 of its 27 points score tables, equations, figures and metadata that this package does not itself produce, so the caller supplies them.

### 4. Batch Processing Architecture

HDARP processes documents in batches. Each batch is prepared (density assessment → chunking), then every chunk of every prepared document is processed in chunk order, and the results are concatenated with an explicit chunk boundary marker:

```
Batch 1 → [prepare: chunk each PDF] → [process each chunk in order] → Complete
Batch 2 → [prepare: chunk each PDF] → [process each chunk in order] → Complete
```

**What this snapshot does not contain**: batches run sequentially in a single process — there is no validator stage, and no threading, multiprocessing or async anywhere in the package. The previous-batch validation pattern used to overlap validation with extraction belongs to the wider protocol and is not published here.

**Automatic continuation** (v5.1): After completing a batch, the system automatically advances to the next batch of PENDING documents and continues until no more remain. Use `--single` for one-batch-at-a-time processing.

### 5. Confidence Reporting (and what is *not* guaranteed)

The design intent is that a fabricated number is worse than a missing one. What this snapshot actually implements towards that is reporting, not refusal:

- **Every result carries the rule that produced it**, the engines that contributed, and the alternatives considered — so a low-quality line is identifiable after the fact.
- **The embedded-text path reports no confidence at all.** When a PDF has a text layer, that text is copied verbatim, no OCR and no consensus run, and `confidence` is `None` rather than a hardcoded 1.0.
- **The consensus engine applies no minimum-confidence threshold and marks no gaps.** Rule 6 always returns the primary engine's text, and its `max(0.60, conf × 0.9)` floor *raises* a read the engine itself distrusted — three garbage reads at 0.11 / 0.09 / 0.05 come back as text at 0.600.

**So: if your use case needs "do not use below X", you must apply that floor yourself to `result.confidence`.** Gap marking is a property of the surrounding protocol, not of this package.

---

## Installation

```bash
git clone https://github.com/andenick/hdarp.git
cd hdarp
pip install -e .            # importable from anywhere; chunking + consensus only
```

`pip install -e .` pulls only the light dependencies (`pypdf`, `Pillow`, `numpy`) — enough to chunk PDFs and run the consensus engine. Add extras as needed:

```bash
pip install -e ".[pdf]"     # PyMuPDF, for rendering pages and reading text layers
pip install -e ".[ocr]"     # PaddleOCR + EasyOCR + Tesseract wrappers
pip install -e ".[dev]"     # pytest
pip install -r requirements.txt   # or: everything at once
```

### OCR Engine Dependencies

Running actual OCR requires the three engines. Install them separately:

```bash
# PaddleOCR (primary engine)
pip install paddlepaddle paddleocr

# EasyOCR (secondary engine)
pip install easyocr

# Tesseract (tertiary engine)
# Windows: Download from https://github.com/UB-Mannheim/tesseract/wiki
# macOS: brew install tesseract
# Linux: sudo apt install tesseract-ocr
pip install pytesseract

# PDF handling
pip install pypdf PyMuPDF
```

See [Third-party components and licences](#third-party-components-and-licences) before shipping a build that includes PyMuPDF.

---

## Quick Start

### Chunk a PDF

```python
from hdarp import PDFSplitterOrchestrator

splitter = PDFSplitterOrchestrator(
    max_chunk_size_mb=1.0,
    max_chunk_pages=10
)

# Assess density first
report = splitter.assess_pdf_density("large_document.pdf")
print(f"Density: {report.density_category} ({report.avg_density:.3f} MB/page)")
print(f"Strategy: {report.recommended_strategy}")
print(f"Estimated chunks: {report.estimated_chunks}")

# Chunk with intelligent strategy
result = splitter.chunk_pdf_intelligent("large_document.pdf", "output/chunks/")
print(f"Created {len(result.chunks)} chunks")
```

### Run OCR Consensus

```python
from hdarp import Sraffa30ConsensusEngine

engine = Sraffa30ConsensusEngine()

result = engine.adjudicate(
    paddle_text="Total Revenue: $1,234,567",
    paddle_conf=0.92,
    easyocr_text="Total Revenue: $1,234,567",
    easyocr_conf=0.88,
    tesseract_text="Total Revenue: $l,234,567",  # Common OCR error: 1→l
    tesseract_conf=0.75,
    column_type="TEXT"
)

print(f"Winner: {result.text}")           # "Total Revenue: $1,234,567"
print(f"Confidence: {result.confidence}")  # 0.95 (majority agreement, 2 of 3 engines — Rule 2 cap)
print(f"Rule: {result.rule_applied}")      # "majority_agreement"
print(f"Engines: {result.winning_engines}")# ["paddle", "easyocr"]
```

These values are asserted in `tests/test_consensus.py`, so they cannot drift away from the code.

### Score Extraction Quality

`QualityScorer` is standalone — nothing in the pipeline calls it, and you supply the table/equation/figure/metadata inputs it scores:

```python
from hdarp import QualityScorer

scorer = QualityScorer()
score = scorer.score_extraction(extraction_result)
print(f"Quality: {score.total}/27 ({score.grade})")
```

### Run the example, and the tests

```bash
python examples/run_example.py          # chunk a generated PDF, then adjudicate
python examples/run_example.py doc.pdf  # ... or chunk a real one
python -m pytest                        # 24 assertions across the three modules
```

---

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    HDARP Pipeline                     │
├─────────────────────────────────────────────────────┤
│                                                      │
│  PDF Input                                           │
│    │                                                 │
│    ▼                                                 │
│  ┌──────────────────────┐                           │
│  │ Density Assessment   │ ← Classify LOW/MED/HIGH   │
│  │ (splitter.py)        │                           │
│  └──────────┬───────────┘                           │
│             │                                        │
│             ▼                                        │
│  ┌──────────────────────┐                           │
│  │ Intelligent Chunking │ ← PAGE_FIRST or SIZE_FIRST│
│  │ (splitter.py)        │   with retry on oversize  │
│  └──────────┬───────────┘                           │
│             │                                        │
│     ┌───────┴───────┐                               │
│     │               │                                │
│     ▼               ▼                                │
│  ┌────────┐  ┌───────────────┐                      │
│  │  DARP  │  │  Sraffa 3.0   │                      │
│  │ Tables │  │  OCR Consensus│                      │
│  │ Eqns   │  │  (3 engines)  │                      │
│  │ Figs   │  │  (6 rules)    │                      │
│  └────┬───┘  └──────┬────────┘                      │
│       │              │                               │
│       └──────┬───────┘                               │
│              ▼                                       │
│  ┌──────────────────────┐                           │
│  │ Quality Scoring      │ ← 27-point framework      │
│  │ (quality_scorer.py)  │                           │
│  └──────────┬───────────┘                           │
│             │                                        │
│             ▼                                        │
│  ┌──────────────────────┐                           │
│  │ Batch Orchestration  │ ← Sequential batches      │
│  │ (orchestrator.py)    │   with auto-continuation  │
│  └──────────────────────┘                           │
│                                                      │
└─────────────────────────────────────────────────────┘
```

Two notes on reading this diagram against the shipped code: quality scoring is a standalone utility that the batch pipeline does not call (it stores the mean OCR consensus confidence instead), and batch orchestration is single-threaded — there is no validator stage and no concurrency in this package.

---

## Module Reference

Line counts below are `wc -l` of the files in this commit.

| Module | LOC | Purpose |
|--------|-----|---------|
| `consensus.py` | 635 | 6-rule consensus adjudication engine |
| `ocr_engines.py` | 494 | PaddleOCR, EasyOCR, Tesseract wrappers with unified interface |
| `splitter.py` | 451 | Density-aware PDF chunking with retry logic |
| `orchestrator.py` | 444 | Batch pipeline with state management and auto-continuation |
| `processor.py` | 332 | Multi-engine OCR processing orchestration |
| `quality_scorer.py` | 318 | 27-point quality scoring framework (standalone) |

2,674 lines across the six modules, 2,745 including `__init__.py`; plus 380 lines of tests and 145 of example.

---

## Performance

Indicative performance figures live in one place — [docs/ARCHITECTURE.md § Performance](docs/ARCHITECTURE.md#performance) — together with the caveat that applies to them. They are illustrative ranges from development use, not benchmark results; no benchmark dataset or eval harness ships with this repo.

---

## Design Philosophy

HDARP was built for a specific use case: enabling AI agents to reliably extract structured data from large document corpora for scholarly research and regulatory analysis. Three principles guide its design:

1. **Accuracy over speed**: Three OCR engines are slower than one, but the consensus mechanism catches errors that no single engine would. In scholarly contexts, a missed decimal point or a fabricated number can invalidate an entire analysis.

2. **Transparency over opacity**: Every extraction includes a full audit trail — which engine won, which rule applied, what the confidence was, and what the alternatives were. A researcher can inspect any result and understand why it was chosen.

3. **Safety over convenience**: never present a guess as a reading. In this snapshot that principle is implemented as *reporting* — every line carries its rule and confidence, and the embedded-text path reports no confidence rather than a fake perfect one — not as *refusal*: the consensus engine has no minimum-confidence threshold and does not gap-mark. See [Confidence Reporting](#5-confidence-reporting-and-what-is-not-guaranteed).

---

## Use with Claude Code

HDARP was designed to work inside Claude Code agent pipelines. Drop a `CLAUDE.md` in your project root:

```markdown
# HDARP Project

This project uses HDARP for PDF extraction.

## Quick Start
- Chunk PDFs: `python -c "from hdarp import PDFSplitterOrchestrator; ..."`
- Run OCR: See examples/ for usage patterns
- Check quality: Use QualityScorer on extraction results

## Key Files
- hdarp/splitter.py — PDF chunking
- hdarp/consensus.py — OCR adjudication (the interesting part)
- hdarp/quality_scorer.py — Extraction quality scoring
```

---

## License

MIT — see [LICENSE](LICENSE).

### Third-party components and licences

The MIT licence covers this repository's own code only. A build that installs the dependencies below inherits their terms, and one of them is copyleft:

| Component | Licence | Notes |
|---|---|---|
| **PyMuPDF** (`fitz`) | **AGPL-3.0-or-later, or a commercial licence from Artifex** | **Copyleft.** Used for page rendering (`processor.py`) and embedded-text extraction (`ocr_engines.py`). If you distribute or network-serve a build that includes PyMuPDF, AGPL obligations apply to that build unless you hold a commercial licence. It is an optional extra here (`pip install -e ".[pdf]"`), but the OCR path does not work without it. |
| pypdf | BSD-3-Clause | PDF reading/writing in `splitter.py`. |
| Pillow | MIT-CMU | Image handling. |
| NumPy | BSD-3-Clause | Array handling in the engine wrappers. |
| PaddleOCR / PaddlePaddle | Apache-2.0 | Optional OCR extra. |
| EasyOCR | Apache-2.0 | Optional OCR extra. |
| pytesseract | Apache-2.0 | Optional OCR extra; wraps the Tesseract binary (Apache-2.0), which you install separately. |

Licences are as published by each project at the time of writing; verify against the version you install.

---

## Citation

If you use HDARP in academic work:

```bibtex
@software{hdarp2026,
  title = {HDARP: Hybrid Direct Agent Reading Protocol},
  author = {Anderson, Nicholas},
  version = {5.1},
  year = {2026},
  url = {https://github.com/andenick/hdarp}
}
```
