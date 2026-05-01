#!/usr/bin/env python3
"""
PDF Splitter Orchestrator — Density-Aware Adaptive Chunking
=============================================================

Intelligent PDF chunking that honors size constraints by classifying documents
on density (MB/page) and selecting the optimal strategy.

Key Features:
- Density assessment (text-heavy vs image-heavy PDFs)
- Adaptive chunking strategy (SIZE-FIRST vs PAGE-FIRST)
- Actual file size verification (not estimates)
- Accepts single pages >1MB with warning
- HDARP-compatible output structure
- Enhanced manifest with density metrics

Author: Nicholas Anderson
Version: 1.0.0
License: MIT
"""

import os
import sys
import json
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass, asdict
from PyPDF2 import PdfReader, PdfWriter


# ==============================================================================
# DATA CLASSES
# ==============================================================================

@dataclass
class PDFDensityReport:
    """PDF density assessment results."""
    total_pages: int
    total_size_mb: float
    avg_density: float  # MB per page
    density_category: str  # "LOW", "MEDIUM", "HIGH"
    recommended_strategy: str  # "PAGE_FIRST", "SIZE_FIRST"
    estimated_chunks: int

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ChunkInfo:
    """Individual chunk metadata."""
    chunk_num: int
    file_path: str
    start_page: int
    end_page: int
    page_count: int
    size_mb: float
    density: float
    status: str  # "OK", "OVERSIZED_SINGLE_PAGE", "WARNING"

    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class ChunkingResult:
    """Complete chunking operation results."""
    success: bool
    source_pdf: str
    source_size_mb: float
    density_report: PDFDensityReport
    chunks: List[ChunkInfo]
    manifest_path: Optional[str]
    warnings: List[str]
    error_message: Optional[str] = None

    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'source_pdf': self.source_pdf,
            'source_size_mb': self.source_size_mb,
            'density_report': self.density_report.to_dict(),
            'chunks': [chunk.to_dict() for chunk in self.chunks],
            'manifest_path': self.manifest_path,
            'warnings': self.warnings,
            'error_message': self.error_message
        }


# ==============================================================================
# PDF SPLITTER ORCHESTRATOR CLASS
# ==============================================================================

class PDFSplitterOrchestrator:
    """
    PDF splitter with density-aware adaptive chunking.

    Intelligently chunks PDFs based on actual density, measuring real file sizes
    and adapting strategy as needed.

    Usage:
        orchestrator = PDFSplitterOrchestrator(max_chunk_size_mb=1.0, max_chunk_pages=10)
        result = orchestrator.chunk_pdf_intelligent("input.pdf", "output/")
    """

    LOW_DENSITY_THRESHOLD = 0.05   # MB/page - text-heavy PDFs
    HIGH_DENSITY_THRESHOLD = 0.10  # MB/page - image-heavy PDFs

    def __init__(self,
                 max_chunk_size_mb: float = 1.0,
                 max_chunk_pages: int = 10,
                 create_manifest: bool = True,
                 verbose: bool = True):
        self.max_chunk_size_mb = max_chunk_size_mb
        self.max_chunk_pages = max_chunk_pages
        self.create_manifest = create_manifest
        self.verbose = verbose

    def _log(self, message: str):
        if self.verbose:
            print(message)

    def _get_file_size_mb(self, filepath: str) -> float:
        size_bytes = os.path.getsize(filepath)
        return size_bytes / (1024 * 1024)

    def assess_pdf_density(self, pdf_path: str) -> PDFDensityReport:
        """
        Phase 1: Assess PDF density and recommend chunking strategy.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF not found: {pdf_path}")

        reader = PdfReader(pdf_path)
        total_pages = len(reader.pages)
        total_size_mb = self._get_file_size_mb(pdf_path)
        avg_density = total_size_mb / total_pages if total_pages > 0 else 0

        if avg_density < self.LOW_DENSITY_THRESHOLD:
            density_category = "LOW"
            recommended_strategy = "PAGE_FIRST"
        elif avg_density < self.HIGH_DENSITY_THRESHOLD:
            density_category = "MEDIUM"
            recommended_strategy = "SIZE_FIRST"
        else:
            density_category = "HIGH"
            recommended_strategy = "SIZE_FIRST"

        if recommended_strategy == "PAGE_FIRST":
            estimated_chunks = (total_pages + self.max_chunk_pages - 1) // self.max_chunk_pages
        else:
            pages_per_chunk = min(
                self.max_chunk_pages,
                max(1, int(self.max_chunk_size_mb / avg_density * 0.9))
            )
            estimated_chunks = (total_pages + pages_per_chunk - 1) // pages_per_chunk

        return PDFDensityReport(
            total_pages=total_pages,
            total_size_mb=total_size_mb,
            avg_density=avg_density,
            density_category=density_category,
            recommended_strategy=recommended_strategy,
            estimated_chunks=estimated_chunks
        )

    def _create_chunk(self, reader: PdfReader, start_page: int, num_pages: int,
                      output_path: str) -> Tuple[float, int]:
        writer = PdfWriter()
        total_pages = len(reader.pages)
        actual_pages = min(num_pages, total_pages - start_page)

        for i in range(actual_pages):
            page_idx = start_page + i
            if page_idx < total_pages:
                writer.add_page(reader.pages[page_idx])

        with open(output_path, 'wb') as f:
            writer.write(f)

        size_mb = self._get_file_size_mb(output_path)
        return size_mb, actual_pages

    def _chunk_with_retry(self, reader: PdfReader, start_page: int, target_pages: int,
                          output_dir: str, base_name: str, chunk_num: int) -> Optional[ChunkInfo]:
        """
        Try to create a chunk, retrying with fewer pages if size exceeds limit.
        Retry sequence: target_pages -> target/2 -> 3 -> 2 -> 1 (single page)
        """
        total_pages = len(reader.pages)
        remaining_pages = total_pages - start_page
        target_pages = min(target_pages, remaining_pages)

        page_attempts = [target_pages]
        if target_pages > 5:
            page_attempts.append(target_pages // 2)
        if target_pages > 3:
            page_attempts.append(3)
        if target_pages > 2:
            page_attempts.append(2)
        page_attempts.append(1)

        for attempt_pages in page_attempts:
            if attempt_pages > remaining_pages:
                continue

            chunk_path = os.path.join(output_dir, f"{base_name}_chunk_{chunk_num:02d}.pdf")
            size_mb, actual_pages = self._create_chunk(reader, start_page, attempt_pages, chunk_path)

            if size_mb <= self.max_chunk_size_mb:
                density = size_mb / actual_pages if actual_pages > 0 else 0
                self._log(f"  Created chunk {chunk_num}: {size_mb:.2f} MB, {actual_pages} pages "
                          f"(density: {density:.3f} MB/page)")
                return ChunkInfo(
                    chunk_num=chunk_num,
                    file_path=chunk_path,
                    start_page=start_page + 1,
                    end_page=start_page + actual_pages,
                    page_count=actual_pages,
                    size_mb=round(size_mb, 3),
                    density=round(density, 3),
                    status="OK"
                )
            elif actual_pages == 1:
                density = size_mb
                self._log(f"  WARNING Created chunk {chunk_num}: {size_mb:.2f} MB, 1 page "
                          f"(OVERSIZED - single page accepted)")
                return ChunkInfo(
                    chunk_num=chunk_num,
                    file_path=chunk_path,
                    start_page=start_page + 1,
                    end_page=start_page + 1,
                    page_count=1,
                    size_mb=round(size_mb, 3),
                    density=round(density, 3),
                    status="OVERSIZED_SINGLE_PAGE"
                )
            else:
                os.remove(chunk_path)
                continue

        return None

    def chunk_pdf_intelligent(self, pdf_path: str, output_dir: str,
                              document_name: Optional[str] = None) -> ChunkingResult:
        """
        Phase 2: Execute adaptive chunking with intelligent strategy selection.
        """
        warnings = []
        try:
            Path(output_dir).mkdir(parents=True, exist_ok=True)
            chunks_dir = os.path.join(output_dir, "chunks")
            Path(chunks_dir).mkdir(parents=True, exist_ok=True)
            base_name = document_name or Path(pdf_path).stem

            self._log(f"\n{'=' * 70}")
            self._log(f"PDF SPLITTER ORCHESTRATOR - Intelligent Chunking")
            self._log(f"{'=' * 70}\n")
            self._log(f"Input PDF: {pdf_path}")

            density_report = self.assess_pdf_density(pdf_path)

            self._log(f"\nDensity Assessment:")
            self._log(f"  Total pages: {density_report.total_pages}")
            self._log(f"  Total size: {density_report.total_size_mb:.2f} MB")
            self._log(f"  Avg density: {density_report.avg_density:.4f} MB/page")
            self._log(f"  Category: {density_report.density_category}")
            self._log(f"  Strategy: {density_report.recommended_strategy}")
            self._log(f"  Estimated chunks: {density_report.estimated_chunks}\n")

            reader = PdfReader(pdf_path)
            total_pages = density_report.total_pages
            chunks: List[ChunkInfo] = []
            current_page = 0
            chunk_num = 1

            self._log(f"Starting adaptive chunking...")
            self._log(f"Max chunk size: {self.max_chunk_size_mb} MB")
            self._log(f"Max chunk pages: {self.max_chunk_pages}\n")

            while current_page < total_pages:
                remaining_pages = total_pages - current_page

                if density_report.recommended_strategy == "PAGE_FIRST":
                    target_pages = min(self.max_chunk_pages, remaining_pages)
                else:
                    safe_pages = int(self.max_chunk_size_mb / density_report.avg_density * 0.9)
                    target_pages = min(safe_pages, self.max_chunk_pages, remaining_pages)
                    target_pages = max(1, target_pages)

                chunk_info = self._chunk_with_retry(
                    reader, current_page, target_pages,
                    chunks_dir, base_name, chunk_num
                )

                if chunk_info is None:
                    error_msg = f"Failed to create chunk {chunk_num} starting at page {current_page + 1}"
                    self._log(f"  ERROR: {error_msg}")
                    warnings.append(error_msg)
                    break

                if chunk_info.status == "OVERSIZED_SINGLE_PAGE":
                    warning = (f"Page {chunk_info.start_page}: {chunk_info.size_mb:.2f}MB "
                               f"(single page exceeds {self.max_chunk_size_mb}MB limit - accepted for processing)")
                    warnings.append(warning)

                chunks.append(chunk_info)
                current_page += chunk_info.page_count
                chunk_num += 1

            manifest_path = None
            if self.create_manifest and chunks:
                manifest_path = self.generate_manifest(
                    pdf_path=pdf_path,
                    output_dir=output_dir,
                    base_name=base_name,
                    density_report=density_report,
                    chunks=chunks,
                    warnings=warnings
                )

            self._log(f"\n{'=' * 70}")
            self._log(f"Chunking Complete!")
            self._log(f"{'=' * 70}")
            self._log(f"  Total chunks created: {len(chunks)}")
            self._log(f"  Output directory: {chunks_dir}")
            if warnings:
                self._log(f"  Warnings: {len(warnings)}")
                for warning in warnings:
                    self._log(f"    - {warning}")
            if manifest_path:
                self._log(f"  Manifest: {manifest_path}")
            self._log(f"{'=' * 70}\n")

            return ChunkingResult(
                success=True,
                source_pdf=pdf_path,
                source_size_mb=density_report.total_size_mb,
                density_report=density_report,
                chunks=chunks,
                manifest_path=manifest_path,
                warnings=warnings
            )

        except Exception as e:
            error_msg = f"Chunking failed: {str(e)}"
            self._log(f"\nERROR: {error_msg}\n")
            return ChunkingResult(
                success=False,
                source_pdf=pdf_path,
                source_size_mb=0,
                density_report=PDFDensityReport(0, 0, 0, "ERROR", "NONE", 0),
                chunks=[],
                manifest_path=None,
                warnings=[],
                error_message=error_msg
            )

    def generate_manifest(self, pdf_path: str, output_dir: str, base_name: str,
                          density_report: PDFDensityReport, chunks: List[ChunkInfo],
                          warnings: List[str]) -> str:
        """Generate manifest with density metrics."""
        manifest = {
            "document_name": base_name,
            "source_pdf": pdf_path,
            "source_size_mb": round(density_report.total_size_mb, 2),
            "total_pages": density_report.total_pages,
            "preparation_date": datetime.now().isoformat(),
            "chunks_created": len(chunks),
            "max_chunk_size_mb": self.max_chunk_size_mb,
            "max_chunk_pages": self.max_chunk_pages,
            "hdarp_version": "1.0",
            "processing_status": "READY",
            "ready_for_processing": True,
            "avg_density_mb_per_page": round(density_report.avg_density, 4),
            "density_category": density_report.density_category,
            "strategy_used": density_report.recommended_strategy,
            "estimated_chunks": density_report.estimated_chunks,
            "chunks": [chunk.to_dict() for chunk in chunks],
            "warnings": warnings
        }

        manifest_path = os.path.join(output_dir, "manifest.json")
        with open(manifest_path, 'w') as f:
            json.dump(manifest, f, indent=2)

        return manifest_path


# ==============================================================================
# CLI INTERFACE
# ==============================================================================

def main():
    """Command-line interface for PDF Splitter Orchestrator."""
    if len(sys.argv) < 3:
        print("PDF Splitter Orchestrator")
        print("=" * 70)
        print("\nUsage: python -m hdarp.splitter INPUT_PDF OUTPUT_DIR [OPTIONS]")
        print("\nOptions:")
        print("  --max-size-mb MB     Maximum chunk size in MB (default: 1.0)")
        print("  --max-pages N        Maximum pages per chunk (default: 10)")
        print("  --no-manifest        Don't create manifest.json")
        print("  --quiet              Suppress progress messages")
        print("\nExamples:")
        print('  python -m hdarp.splitter "input.pdf" "output/"')
        print('  python -m hdarp.splitter "input.pdf" "output/" --max-size-mb 0.8')
        sys.exit(1)

    input_pdf = sys.argv[1]
    output_dir = sys.argv[2]
    max_size_mb = 1.0
    max_pages = 10
    create_manifest = True
    verbose = True

    i = 3
    while i < len(sys.argv):
        if sys.argv[i] == '--max-size-mb' and i + 1 < len(sys.argv):
            max_size_mb = float(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--max-pages' and i + 1 < len(sys.argv):
            max_pages = int(sys.argv[i + 1])
            i += 2
        elif sys.argv[i] == '--no-manifest':
            create_manifest = False
            i += 1
        elif sys.argv[i] == '--quiet':
            verbose = False
            i += 1
        else:
            print(f"Unknown option: {sys.argv[i]}")
            sys.exit(1)

    if not os.path.exists(input_pdf):
        print(f"ERROR: Input file not found: {input_pdf}")
        sys.exit(1)

    orchestrator = PDFSplitterOrchestrator(
        max_chunk_size_mb=max_size_mb,
        max_chunk_pages=max_pages,
        create_manifest=create_manifest,
        verbose=verbose
    )
    result = orchestrator.chunk_pdf_intelligent(input_pdf, output_dir)
    sys.exit(0 if result.success else 1)


if __name__ == "__main__":
    main()
