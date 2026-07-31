"""
HDARP — Multi-Engine OCR Consensus for PDF Extraction
======================================================

Density-aware PDF chunking, three OCR engine wrappers, and a six-rule consensus
adjudicator that turns disagreeing OCR reads into one line with an audit trail.

The name is the acronym of an in-house protocol ("Hybrid Direct Agent Reading
Protocol"); this package publishes only its OCR-consensus half. There is no
agent or vision code here: nothing calls a language or vision model, and nothing
produces tables, equations or figure descriptions.

Indicative accuracy (illustrative ranges from development use, NOT results from
a published benchmark dataset — none ships with this repo): 95-98% on clean
documents, 85-92% on degraded scans.

Modules:
    splitter        — Density-aware PDF chunking
    consensus       — 6-rule OCR consensus adjudication
    ocr_engines     — PaddleOCR/EasyOCR/Tesseract unified interface
    processor       — Multi-engine OCR processing orchestration
    orchestrator    — Sequential batch pipeline with auto-continuation
    quality_scorer  — 27-point quality scoring framework (standalone; the
                      pipeline does not call it, and 18 of its 27 points score
                      artifacts this package does not produce)

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
