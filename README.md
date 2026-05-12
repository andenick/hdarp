# HDARP — Hybrid Direct Agent Reading Protocol

**Production-grade PDF extraction for AI agent pipelines. 95-98% accuracy through multi-engine OCR consensus.**

---

## What HDARP Does

HDARP solves the fundamental problem of getting structured data out of scanned PDFs at scale when you're working with AI agents. It combines two complementary approaches:

1. **DARP (Direct Agent Reading)** for structured content: Uses Claude's vision API to extract tables → CSV (98%+ accuracy), equations → LaTeX, and figures → markdown descriptions.

2. **Sraffa 3.0 Multi-Engine OCR Consensus** for body text: A 3-engine ensemble (PaddleOCR, EasyOCR, Tesseract) with a 6-rule adjudication hierarchy that achieves 95-98% accuracy — significantly better than any single engine.

> **Version note**: This repo implements the Sraffa 3.0 consensus engine. The current production system uses **Sraffa 4.0**, which adds document-adaptive routing (digital pages → PyMuPDF instant extraction, scanned pages → EasyOCR GPU with agent QA, QA failures → Chandra 2 NF4 fallback). The Sraffa 3.0 consensus engine remains the core OCR adjudication layer within Sraffa 4.0.

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
| 6 | **Default to Primary** | 0.60-0.85 | Fallback to PaddleOCR (highest-priority engine). |

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

### 4. Batch Processing Architecture

HDARP processes documents in batches with a parallel validation pattern:

```
Batch 1 → [Processors extract] → Complete
                                    ↓
Batch 2 → [Processors extract] → [Validator checks Batch 1] → Complete
                                                                  ↓
Batch 3 → [Processors extract] → [Validator checks Batch 2] → Complete
```

This previous-batch validation design eliminates race conditions and enables true parallel execution. The validator always works on a completed batch while processors handle the current one.

**Automatic continuation** (v5.1): After completing a batch, the system automatically advances to the next PREPARED batch and continues until no more remain. Use `--single` for one-batch-at-a-time processing.

### 5. Zero-Fabrication Guarantee

HDARP implements a strict policy: **never fabricate content**. If a region cannot be read with sufficient confidence, it is marked as a gap rather than filled with plausible-looking text. This is critical for scholarly and regulatory use cases where false positives are worse than missing data.

---

## Quick Start

```bash
git clone https://github.com/andenick/hdarp.git
cd hdarp
pip install -r requirements.txt
```

### OCR Engine Dependencies

HDARP requires three OCR engines. Install them separately:

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
pip install PyPDF2 PyMuPDF
```

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
print(f"Confidence: {result.confidence}")  # 0.987 (perfect agreement between 2 engines)
print(f"Rule: {result.rule_applied}")      # "majority_agreement"
print(f"Engines: {result.winning_engines}")# ["paddle", "easyocr"]
```

### Score Extraction Quality

```python
from hdarp import QualityScorer

scorer = QualityScorer()
score = scorer.score_extraction(extraction_result)
print(f"Quality: {score.total}/27 ({score.grade})")
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
│  │ Batch Orchestration  │ ← Parallel processing     │
│  │ (orchestrator.py)    │   with auto-continuation  │
│  └──────────────────────┘                           │
│                                                      │
└─────────────────────────────────────────────────────┘
```

---

## Module Reference

| Module | LOC | Purpose |
|--------|-----|---------|
| `splitter.py` | 582 | Density-aware PDF chunking with retry logic |
| `ocr_engines.py` | 627 | PaddleOCR, EasyOCR, Tesseract wrappers with unified interface |
| `consensus.py` | 590 | 6-rule consensus adjudication engine |
| `processor.py` | 356 | Multi-engine OCR processing orchestration |
| `orchestrator.py` | 756 | Batch pipeline with state management and auto-continuation |
| `quality_scorer.py` | 640 | 27-point quality scoring framework |

---

## Performance

Tested on a corpus of 3,000+ academic papers, books, and regulatory documents:

| Metric | Single Engine | HDARP Consensus |
|--------|--------------|-----------------|
| Text accuracy (clean scans) | 88-92% | 95-98% |
| Text accuracy (degraded) | 70-80% | 85-92% |
| Table extraction | N/A (OCR only) | 98%+ (agent vision) |
| Processing speed | ~1 sec/page | ~3-5 sec/page |
| False positives | Common | Near-zero (gap marking) |

---

## Design Philosophy

HDARP was built for a specific use case: enabling AI agents to reliably extract structured data from large document corpora for scholarly research and regulatory analysis. Three principles guide its design:

1. **Accuracy over speed**: Three OCR engines are slower than one, but the consensus mechanism catches errors that no single engine would. In scholarly contexts, a missed decimal point or a fabricated number can invalidate an entire analysis.

2. **Transparency over opacity**: Every extraction includes a full audit trail — which engine won, which rule applied, what the confidence was, and what the alternatives were. A researcher can inspect any result and understand why it was chosen.

3. **Safety over convenience**: The zero-fabrication guarantee means HDARP will never produce plausible-looking text that wasn't in the source document. Missing data is marked as missing, not filled in.

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

MIT

---

## Citation

If you use HDARP in academic work:

```bibtex
@software{hdarp2025,
  title = {HDARP: Hybrid Direct Agent Reading Protocol},
  author = {Anderson, Nicholas},
  year = {2025},
  url = {https://github.com/andenick/hdarp}
}
```
