#!/usr/bin/env python3
"""
HDARP Auto-Orchestrator — Batch pipeline with auto-continuation
=================================================================

Orchestrates HDARP processing across many PDFs:
1. Discovers documents in a corpus directory
2. Tracks state in a master catalog (CSV)
3. Manages chunk preparation, processing, validation
4. Auto-continues across batches without user intervention
5. Records hash-based audit trail

Author: Nicholas Anderson
Version: 1.0.0
License: MIT
"""

import csv
import json
import logging
import sys
from dataclasses import dataclass, asdict
from datetime import datetime
from hashlib import sha256
from pathlib import Path
from typing import Dict, List, Optional

from hdarp.splitter import PDFSplitterOrchestrator
from hdarp.processor import Sraffa30Processor


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


# ==============================================================================
# DATA CLASSES
# ==============================================================================

@dataclass
class CatalogEntry:
    """Master catalog entry for a single document."""
    doc_id: str
    pdf_path: str
    total_pages: int
    total_size_mb: float
    status: str  # PENDING, PREPARED, PROCESSING, COMPLETE, VERIFIED, FAILED
    chunk_count: int
    quality_score: Optional[float]
    completion_date: Optional[str]
    error_message: Optional[str]
    input_hash: Optional[str]
    output_hash: Optional[str]


# ==============================================================================
# ORCHESTRATOR
# ==============================================================================

class HDARPOrchestrator:
    """
    Batch orchestrator for HDARP processing.

    Maintains a master catalog tracking the status of each document,
    and runs the full pipeline (chunk -> process -> validate) with
    auto-continuation across batches.
    """

    STATUSES = ["PENDING", "PREPARED", "PROCESSING", "COMPLETE", "VERIFIED", "FAILED", "BLOCKED"]

    def __init__(self,
                 corpus_dir: Path,
                 output_dir: Path,
                 catalog_path: Optional[Path] = None,
                 max_chunk_size_mb: float = 1.0,
                 max_chunk_pages: int = 10):
        self.corpus_dir = Path(corpus_dir).resolve()
        self.output_dir = Path(output_dir).resolve()
        self.catalog_path = catalog_path or (self.output_dir / "HDARP_MASTER_CATALOG.csv")
        self.max_chunk_size_mb = max_chunk_size_mb
        self.max_chunk_pages = max_chunk_pages

        self.output_dir.mkdir(parents=True, exist_ok=True)

        self.splitter = PDFSplitterOrchestrator(
            max_chunk_size_mb=max_chunk_size_mb,
            max_chunk_pages=max_chunk_pages,
            verbose=False
        )
        # Lazy-init the processor to avoid loading OCR engines unless needed
        self._processor = None

    def _get_processor(self) -> Sraffa30Processor:
        if self._processor is None:
            self._processor = Sraffa30Processor()
        return self._processor

    def _hash_file(self, path: Path) -> str:
        """SHA-256 hash of a file."""
        h = sha256()
        with open(path, 'rb') as f:
            for chunk in iter(lambda: f.read(65536), b''):
                h.update(chunk)
        return h.hexdigest()

    def discover_documents(self) -> List[Path]:
        """Find all PDFs in the corpus directory."""
        return sorted(self.corpus_dir.rglob("*.pdf"))

    def load_catalog(self) -> Dict[str, CatalogEntry]:
        """Load the master catalog from disk."""
        if not self.catalog_path.exists():
            return {}

        catalog = {}
        with open(self.catalog_path, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                # Convert numeric fields
                for k in ('total_pages', 'chunk_count'):
                    if row.get(k):
                        row[k] = int(row[k])
                for k in ('total_size_mb', 'quality_score'):
                    if row.get(k):
                        row[k] = float(row[k])
                # Empty strings to None
                for k, v in list(row.items()):
                    if v == '':
                        row[k] = None
                entry = CatalogEntry(**row)
                catalog[entry.doc_id] = entry
        return catalog

    def save_catalog(self, catalog: Dict[str, CatalogEntry]) -> None:
        """Save the master catalog to disk."""
        if not catalog:
            return

        fieldnames = list(asdict(next(iter(catalog.values()))).keys())
        with open(self.catalog_path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for entry in catalog.values():
                writer.writerow(asdict(entry))

    def initialize_catalog(self) -> Dict[str, CatalogEntry]:
        """Discover documents and initialize catalog entries."""
        catalog = self.load_catalog()
        documents = self.discover_documents()

        for pdf_path in documents:
            doc_id = pdf_path.stem
            if doc_id in catalog:
                continue

            try:
                report = self.splitter.assess_pdf_density(str(pdf_path))
                catalog[doc_id] = CatalogEntry(
                    doc_id=doc_id,
                    pdf_path=str(pdf_path.relative_to(self.corpus_dir)),
                    total_pages=report.total_pages,
                    total_size_mb=round(report.total_size_mb, 3),
                    status="PENDING",
                    chunk_count=0,
                    quality_score=None,
                    completion_date=None,
                    error_message=None,
                    input_hash=self._hash_file(pdf_path),
                    output_hash=None,
                )
            except Exception as e:
                logger.error(f"Failed to initialize catalog entry for {doc_id}: {e}")

        self.save_catalog(catalog)
        return catalog

    def prepare_batch(self, doc_ids: List[str]) -> List[str]:
        """Run chunking phase for the specified documents."""
        catalog = self.load_catalog()
        prepared = []

        for doc_id in doc_ids:
            if doc_id not in catalog:
                logger.warning(f"Skipping unknown doc_id: {doc_id}")
                continue

            entry = catalog[doc_id]
            if entry.status not in ("PENDING", "FAILED"):
                continue

            pdf_path = self.corpus_dir / entry.pdf_path
            chunks_dir = self.output_dir / doc_id

            try:
                logger.info(f"Preparing {doc_id}...")
                result = self.splitter.chunk_pdf_intelligent(
                    str(pdf_path),
                    str(chunks_dir),
                    document_name=doc_id,
                )
                if result.success:
                    entry.status = "PREPARED"
                    entry.chunk_count = len(result.chunks)
                    entry.error_message = None
                    prepared.append(doc_id)
                else:
                    entry.status = "FAILED"
                    entry.error_message = result.error_message or "chunking_failed"
            except Exception as e:
                entry.status = "FAILED"
                entry.error_message = str(e)
                logger.error(f"Chunking failed for {doc_id}: {e}")

        self.save_catalog(catalog)
        return prepared

    def process_batch(self, doc_ids: List[str]) -> List[str]:
        """Run OCR processing for the specified documents."""
        catalog = self.load_catalog()
        completed = []

        processor = None  # Lazy initialize

        for doc_id in doc_ids:
            if doc_id not in catalog:
                continue

            entry = catalog[doc_id]
            if entry.status != "PREPARED":
                continue

            pdf_path = self.corpus_dir / entry.pdf_path

            try:
                if processor is None:
                    processor = self._get_processor()

                logger.info(f"Processing {doc_id}...")
                result = processor.process_pdf(str(pdf_path))

                output_path = self.output_dir / doc_id / f"{doc_id}_text.txt"
                output_path.parent.mkdir(parents=True, exist_ok=True)
                with open(output_path, 'w', encoding='utf-8') as f:
                    f.write(result['text'])

                entry.status = "COMPLETE"
                entry.completion_date = datetime.now().isoformat()
                entry.output_hash = self._hash_file(output_path)
                # Set a coarse quality proxy from confidence
                entry.quality_score = round(result.get('confidence', 0.0), 3)
                entry.error_message = None
                completed.append(doc_id)
            except Exception as e:
                entry.status = "FAILED"
                entry.error_message = str(e)
                logger.error(f"Processing failed for {doc_id}: {e}")

        self.save_catalog(catalog)
        return completed

    def run_full_pipeline(self, batch_size: int = 10, single_batch: bool = False) -> Dict:
        """
        Run the full HDARP pipeline with auto-continuation.

        Args:
            batch_size: Number of documents per batch
            single_batch: If True, only process one batch and stop

        Returns:
            Summary dict with counts of documents at each status
        """
        catalog = self.initialize_catalog()
        logger.info(f"Catalog initialized: {len(catalog)} documents")

        total_processed = 0
        batches_run = 0

        while True:
            # Find next batch of pending documents
            pending = [doc_id for doc_id, entry in catalog.items()
                       if entry.status == "PENDING"][:batch_size]

            if not pending:
                logger.info("No pending documents. Pipeline complete.")
                break

            logger.info(f"\n=== Batch {batches_run + 1}: {len(pending)} documents ===")

            # Prepare (chunk)
            prepared = self.prepare_batch(pending)
            logger.info(f"  Prepared: {len(prepared)}/{len(pending)}")

            # Process (OCR)
            completed = self.process_batch(prepared)
            logger.info(f"  Completed: {len(completed)}/{len(prepared)}")

            total_processed += len(completed)
            batches_run += 1

            # Reload catalog for next iteration
            catalog = self.load_catalog()

            if single_batch:
                logger.info("--single flag set; stopping after one batch.")
                break

        # Summary
        summary = {status: 0 for status in self.STATUSES}
        for entry in catalog.values():
            summary[entry.status] = summary.get(entry.status, 0) + 1
        summary["total_processed_this_run"] = total_processed
        summary["batches_run"] = batches_run

        return summary


def main():
    """CLI for HDARP orchestrator."""
    import argparse

    parser = argparse.ArgumentParser(description="HDARP batch orchestrator")
    parser.add_argument("corpus_dir", help="Directory containing PDFs to process")
    parser.add_argument("output_dir", help="Directory for chunks and outputs")
    parser.add_argument("--batch-size", type=int, default=10,
                        help="Documents per batch (default: 10)")
    parser.add_argument("--single", action="store_true",
                        help="Process only one batch then stop")

    args = parser.parse_args()

    orch = HDARPOrchestrator(
        corpus_dir=args.corpus_dir,
        output_dir=args.output_dir,
    )

    summary = orch.run_full_pipeline(
        batch_size=args.batch_size,
        single_batch=args.single,
    )

    print("\n" + "=" * 70)
    print("HDARP Pipeline Summary")
    print("=" * 70)
    for status, count in summary.items():
        print(f"  {status}: {count}")
    print("=" * 70)


if __name__ == "__main__":
    main()
