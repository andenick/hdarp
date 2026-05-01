#!/usr/bin/env python3
"""
Sraffa 3.0 OCR Engines — Multi-Engine Wrappers
================================================

Modular OCR engine wrappers with unified interface and graceful degradation.

Engines Implemented:
1. PaddleOCR v3.x (Primary) — Best accuracy, priority 3
2. EasyOCR v1.7.x (Secondary) — Good fallback, priority 2
3. Tesseract v5+ (Tertiary) — Fast baseline, priority 1
4. PyMuPDF (Pre-check) — Embedded text extraction, instant

Architecture:
- Abstract base class for consistent interface
- Lazy initialization (on-demand engine loading)
- Graceful degradation (work with available engines)
- Consistent return format: (texts, confidences)

Author: Nicholas Anderson
Version: 1.0.0
License: MIT
"""

import logging
from abc import ABC, abstractmethod
from typing import List, Tuple, Optional

import numpy as np
from PIL import Image


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==============================================================================
# ABSTRACT BASE CLASS
# ==============================================================================

class BaseOCREngine(ABC):
    """
    Abstract base class for OCR engines.

    All engines must implement:
    - initialize(): Load the engine (lazy initialization)
    - ocr_image(): Process an image and return (texts, confidences)
    - is_available(): Check if engine can be initialized
    """

    def __init__(self, priority: int, name: str):
        self.priority = priority
        self.name = name
        self._engine = None
        self._initialized = False
        self._available = None  # None=unknown, True=available, False=unavailable

    @abstractmethod
    def initialize(self) -> bool:
        """Initialize the OCR engine (lazy loading). Returns True if successful."""
        pass

    @abstractmethod
    def ocr_image(self, image: Image.Image) -> Tuple[List[str], List[float]]:
        """Perform OCR. Returns (texts, confidences)."""
        pass

    @abstractmethod
    def is_available(self) -> bool:
        """Check if this engine is available on the system."""
        pass

    def __repr__(self) -> str:
        status = "initialized" if self._initialized else "not initialized"
        avail = "available" if self._available else "unavailable" if self._available is False else "unknown"
        return f"<{self.name} (priority={self.priority}, {status}, {avail})>"


# ==============================================================================
# PADDLEOCR ENGINE (PRIORITY 3 - PRIMARY)
# ==============================================================================

class PaddleOCREngine(BaseOCREngine):
    """
    PaddleOCR wrapper — Primary OCR engine.

    Best overall accuracy (95-98% on clean documents).
    Handles multi-language, supports angles, excellent line detection.
    """

    def __init__(self, lang: str = "en"):
        super().__init__(priority=3, name="PaddleOCR")
        self.lang = lang

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import paddleocr  # noqa: F401
            self._available = True
            return True
        except ImportError:
            logger.warning(f"{self.name}: Not installed (pip install paddleocr)")
            self._available = False
            return False

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if not self.is_available():
            return False

        try:
            from paddleocr import PaddleOCR
            logger.info(f"[1/3] Initializing {self.name}...")
            self._engine = PaddleOCR(lang=self.lang)
            self._initialized = True
            logger.info(f"  {self.name} ready")
            return True
        except Exception as e:
            logger.error(f"  {self.name} initialization failed: {e}")
            self._available = False
            return False

    def ocr_image(self, image: Image.Image) -> Tuple[List[str], List[float]]:
        if not self._initialized:
            if not self.initialize():
                return ([], [])

        try:
            img_array = np.array(image)
            texts = []
            confidences = []

            try:
                # PaddleOCR v3.x: predict() returns OCRResult dict-like objects
                results = self._engine.predict(img_array)
                for res in results:
                    if isinstance(res, dict) or hasattr(res, '__getitem__'):
                        try:
                            rec_texts = res['rec_texts']
                            rec_scores = res['rec_scores']
                            for text, score in zip(rec_texts, rec_scores):
                                if text:
                                    texts.append(text)
                                    confidences.append(float(score))
                            continue
                        except (KeyError, TypeError):
                            pass
                    if hasattr(res, 'rec_texts') and hasattr(res, 'rec_scores'):
                        for text, score in zip(res.rec_texts, res.rec_scores):
                            if text:
                                texts.append(text)
                                confidences.append(float(score))
            except TypeError:
                # PaddleOCR v2.x fallback
                result = self._engine.ocr(img_array)
                if result and result[0]:
                    for line in result[0]:
                        text = line[1][0]
                        conf = line[1][1]
                        texts.append(text)
                        confidences.append(float(conf))

            return (texts, confidences) if texts else ([], [])

        except Exception as e:
            logger.error(f"{self.name} OCR failed: {e}")
            return ([], [])


# ==============================================================================
# EASYOCR ENGINE (PRIORITY 2 - SECONDARY)
# ==============================================================================

class EasyOCREngine(BaseOCREngine):
    """
    EasyOCR wrapper — Secondary OCR engine.

    Decent accuracy (90-95%). Good fallback. Many languages supported.
    """

    def __init__(self, languages: Optional[List[str]] = None, gpu: bool = False):
        super().__init__(priority=2, name="EasyOCR")
        self.languages = languages or ['en']
        self.gpu = gpu

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import easyocr  # noqa: F401
            self._available = True
            return True
        except ImportError:
            logger.warning(f"{self.name}: Not installed (pip install easyocr)")
            self._available = False
            return False

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if not self.is_available():
            return False

        try:
            import easyocr
            logger.info(f"[2/3] Initializing {self.name}...")
            self._engine = easyocr.Reader(
                self.languages,
                gpu=self.gpu,
                verbose=False
            )
            self._initialized = True
            logger.info(f"  {self.name} ready")
            return True
        except Exception as e:
            logger.error(f"  {self.name} initialization failed: {e}")
            self._available = False
            return False

    def ocr_image(self, image: Image.Image) -> Tuple[List[str], List[float]]:
        if not self._initialized:
            if not self.initialize():
                return ([], [])

        try:
            img_array = np.array(image)
            result = self._engine.readtext(img_array)

            if not result:
                return ([], [])

            texts = []
            confidences = []
            for detection in result:
                # detection is: (bbox, text, confidence)
                text = detection[1]
                conf = detection[2]
                texts.append(text)
                confidences.append(float(conf))

            return (texts, confidences)

        except Exception as e:
            logger.error(f"{self.name} OCR failed: {e}")
            return ([], [])


# ==============================================================================
# TESSERACT ENGINE (PRIORITY 1 - TERTIARY)
# ==============================================================================

class TesseractEngine(BaseOCREngine):
    """
    Tesseract wrapper — Tertiary OCR engine.

    Fast baseline (85-90% accuracy). Widely available, lightweight.
    """

    def __init__(self):
        super().__init__(priority=1, name="Tesseract")

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available

        try:
            import pytesseract
            import os

            # Windows: try common Tesseract install paths if not in PATH
            if os.name == 'nt':
                tesseract_paths = [
                    r'C:\Program Files\Tesseract-OCR\tesseract.exe',
                    r'C:\Program Files (x86)\Tesseract-OCR\tesseract.exe',
                ]
                for path in tesseract_paths:
                    if os.path.exists(path):
                        pytesseract.pytesseract.tesseract_cmd = path
                        break

            pytesseract.get_tesseract_version()
            self._available = True
            return True
        except Exception:
            logger.warning(f"{self.name}: Not installed or not in PATH")
            self._available = False
            return False

    def initialize(self) -> bool:
        if self._initialized:
            return True
        if not self.is_available():
            return False

        try:
            import pytesseract
            logger.info(f"[3/3] Initializing {self.name}...")
            self._engine = pytesseract
            self._initialized = True
            logger.info(f"  {self.name} ready")
            return True
        except Exception as e:
            logger.error(f"  {self.name} initialization failed: {e}")
            self._available = False
            return False

    def ocr_image(self, image: Image.Image) -> Tuple[List[str], List[float]]:
        if not self._initialized:
            if not self.initialize():
                return ([], [])

        try:
            data = self._engine.image_to_data(
                image,
                output_type=self._engine.Output.DICT
            )

            texts = []
            confidences = []
            current_line_text = []
            current_line_confs = []
            last_line_num = -1

            for i, word_text in enumerate(data['text']):
                line_num = data['line_num'][i]
                conf = float(data['conf'][i])

                if word_text.strip():
                    if line_num != last_line_num and current_line_text:
                        combined_text = ' '.join(current_line_text)
                        avg_conf = sum(current_line_confs) / len(current_line_confs) / 100.0
                        texts.append(combined_text)
                        confidences.append(avg_conf)
                        current_line_text = []
                        current_line_confs = []

                    current_line_text.append(word_text)
                    current_line_confs.append(conf)
                    last_line_num = line_num

            if current_line_text:
                combined_text = ' '.join(current_line_text)
                avg_conf = sum(current_line_confs) / len(current_line_confs) / 100.0
                texts.append(combined_text)
                confidences.append(avg_conf)

            return (texts, confidences)

        except Exception as e:
            logger.error(f"{self.name} OCR failed: {e}")
            return ([], [])


# ==============================================================================
# PYMUPDF EXTRACTOR (PRE-CHECK - NOT OCR)
# ==============================================================================

class PyMuPDFExtractor:
    """
    PyMuPDF embedded text extractor — Pre-check before OCR.

    NOT an OCR engine. Extracts embedded text from PDFs instantly.
    100% accurate for PDFs with embedded text (most modern PDFs).
    Always check this first before running OCR.
    """

    def __init__(self):
        self.name = "PyMuPDF"
        self._available = None

    def is_available(self) -> bool:
        if self._available is not None:
            return self._available
        try:
            import fitz  # noqa: F401
            self._available = True
            return True
        except ImportError:
            logger.warning(f"{self.name}: Not installed (pip install PyMuPDF)")
            self._available = False
            return False

    def extract_text(self, pdf_path: str) -> Optional[str]:
        if not self.is_available():
            return None

        try:
            import fitz
            doc = fitz.open(pdf_path)
            full_text = []
            for page in doc:
                text = page.get_text()
                if text and len(text.strip()) > 50:
                    full_text.append(text)
            doc.close()

            if full_text:
                combined = '\n\n'.join(full_text)
                if len(combined.strip()) > 100:
                    return combined
            return None

        except Exception as e:
            logger.error(f"{self.name} extraction failed: {e}")
            return None

    def __repr__(self) -> str:
        avail = "available" if self._available else "unavailable" if self._available is False else "unknown"
        return f"<{self.name} ({avail})>"


# ==============================================================================
# ENGINE FACTORY
# ==============================================================================

def get_available_engines() -> Tuple[List[BaseOCREngine], PyMuPDFExtractor]:
    """
    Get all available OCR engines and PyMuPDF extractor.

    Returns:
        Tuple of (ocr_engines, pymupdf_extractor)
        OCR engines are sorted by priority (highest first)
    """
    logger.info("=" * 80)
    logger.info("SRAFFA 3.0 — CHECKING AVAILABLE ENGINES")
    logger.info("=" * 80)

    pymupdf = PyMuPDFExtractor()
    if pymupdf.is_available():
        logger.info(f"  {pymupdf.name} available (embedded text extraction)")
    else:
        logger.warning(f"  {pymupdf.name} not available")

    engines = [
        PaddleOCREngine(),
        EasyOCREngine(),
        TesseractEngine()
    ]

    available = []
    for engine in engines:
        if engine.is_available():
            available.append(engine)
            logger.info(f"  {engine.name} available (priority {engine.priority})")
        else:
            logger.warning(f"  {engine.name} not available")

    if not available:
        logger.error("ERROR: No OCR engines available. Install at least PaddleOCR.")
    else:
        available.sort(key=lambda e: e.priority, reverse=True)
        logger.info(f"\n{len(available)} OCR engine(s) available")

    logger.info("=" * 80)
    return (available, pymupdf)


if __name__ == "__main__":
    """Test engine initialization."""
    print("\nHDARP OCR Engines — Initialization Test")
    print("=" * 80)

    ocr_engines, pymupdf = get_available_engines()

    print(f"\nResults:")
    print(f"  PyMuPDF Extractor: {pymupdf}")
    print(f"  Available OCR Engines: {len(ocr_engines)}")
    for engine in ocr_engines:
        print(f"    - {engine}")

    print(f"\nInitializing engines...")
    for engine in ocr_engines:
        success = engine.initialize()
        status = "OK" if success else "FAIL"
        print(f"  [{status}] {engine.name}")

    print("\n" + "=" * 80)
    print("Test complete.")
