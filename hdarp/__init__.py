"""
HDARP — Hybrid Direct Agent Reading Protocol
=============================================

PDF extraction for AI agent pipelines, built around multi-engine OCR consensus.

Indicative accuracy (illustrative ranges from development use, NOT results from
a published benchmark dataset — none ships with this repo): 95-98% on clean
documents, 85-92% on degraded scans.

Modules:
    splitter        — Density-aware PDF chunking
    consensus       — 6-rule OCR consensus adjudication
    ocr_engines     — PaddleOCR/EasyOCR/Tesseract unified interface
    processor       — Multi-engine OCR processing orchestration
    orchestrator    — Batch pipeline with auto-continuation
    quality_scorer  — 27-point quality scoring framework

Quick Start:
    >>> from hdarp import PDFSplitterOrchestrator, Sraffa30ConsensusEngine
    >>> splitter = PDFSplitterOrchestrator()
    >>> result = splitter.chunk_pdf_intelligent("input.pdf", "output/")
"""

from hdarp.splitter import (
    PDFSplitterOrchestrator,
    PDFDensityReport,
    ChunkInfo,
    ChunkingResult,
)
from hdarp.consensus import Sraffa30ConsensusEngine, ConsensusResult
from hdarp.ocr_engines import (
    BaseOCREngine,
    PaddleOCREngine,
    EasyOCREngine,
    TesseractEngine,
    PyMuPDFExtractor,
    get_available_engines,
)
from hdarp.processor import Sraffa30Processor
from hdarp.orchestrator import HDARPOrchestrator, CatalogEntry
from hdarp.quality_scorer import QualityScorer, QualityScore

__version__ = "5.1"
__author__ = "Nicholas Anderson"

__all__ = [
    # Splitter
    "PDFSplitterOrchestrator",
    "PDFDensityReport",
    "ChunkInfo",
    "ChunkingResult",
    # Consensus
    "Sraffa30ConsensusEngine",
    "ConsensusResult",
    # OCR engines
    "BaseOCREngine",
    "PaddleOCREngine",
    "EasyOCREngine",
    "TesseractEngine",
    "PyMuPDFExtractor",
    "get_available_engines",
    # Processor
    "Sraffa30Processor",
    # Orchestrator
    "HDARPOrchestrator",
    "CatalogEntry",
    # Quality
    "QualityScorer",
    "QualityScore",
]
