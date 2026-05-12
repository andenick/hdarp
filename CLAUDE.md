# HDARP — For Claude Code Reviewers

## What This Is

HDARP (Hybrid Direct Agent Reading Protocol) is a production PDF extraction system that achieves 95-98% accuracy through multi-engine OCR consensus. It was built to run inside Claude Code agent pipelines for scholarly research.

## Quick Orientation

The interesting code is in `hdarp/`:
- **`consensus.py`** — The 6-rule adjudication engine. Start here. This is the core intellectual contribution: how to combine three OCR engines that disagree into a reliable result.
- **`splitter.py`** — Density-aware PDF chunking. Classifies PDFs by content density and adapts the chunking strategy accordingly.
- **`quality_scorer.py`** — 27-point weighted scoring framework for extraction quality.

## Try It

```python
from hdarp import Sraffa30ConsensusEngine

engine = Sraffa30ConsensusEngine()
result = engine.adjudicate(
    paddle_text="Revenue: $1,234",
    paddle_conf=0.92,
    easyocr_text="Revenue: $1,234",
    easyocr_conf=0.85,
    tesseract_text="Revenue: $l,234",
    tesseract_conf=0.70
)
print(result.rule_applied, result.confidence)
```

## Context

This is one of four repositories demonstrating an integrated system for AI-driven economic research:
1. **HDARP** (this repo) — Input layer: get data into the pipeline
2. [anu-data-framework](https://github.com/andenick/anu-data-framework) — Protocol layer: structure agent tasks
3. [nickydata](https://github.com/andenick/nickydata) — Reproducibility layer: run without agents
4. [capitalism-data](https://github.com/andenick/capitalism-data) — Demonstration: proof at scale
