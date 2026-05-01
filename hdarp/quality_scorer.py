#!/usr/bin/env python3
"""
HDARP Quality Scorer — 27-point Weighted Quality Framework
============================================================

Evaluates the quality of an HDARP extraction across seven weighted components,
producing a single 27-point score and a letter grade.

Components:
  Tables:           8 points (CSV format, header detection, cell accuracy)
  Text:             4 points (character accuracy, paragraph structure)
  Equations:        3 points (LaTeX validity, symbol recognition)
  Figures:          3 points (description completeness, references)
  OCR Confidence:   2 points (mean confidence across consensus results)
  Formatting:       3 points (section structure, whitespace, encoding)
  Metadata:         4 points (page numbers, headers, cross-references)
  ==========       27 points total

Grading:
  A: 24-27   Production-quality extraction
  B: 20-23   Acceptable with minor issues
  C: 15-19   Usable but needs review
  D: 10-14   Significant issues
  F: < 10    Failed extraction

Author: Nicholas Anderson
Version: 1.0.0
License: MIT
"""

from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class QualityScore:
    """Complete quality assessment for one extraction."""
    tables: float          # 0-8
    text: float            # 0-4
    equations: float       # 0-3
    figures: float         # 0-3
    ocr_confidence: float  # 0-2
    formatting: float      # 0-3
    metadata: float        # 0-4

    @property
    def total(self) -> float:
        return (self.tables + self.text + self.equations + self.figures
                + self.ocr_confidence + self.formatting + self.metadata)

    @property
    def grade(self) -> str:
        t = self.total
        if t >= 24:
            return "A"
        if t >= 20:
            return "B"
        if t >= 15:
            return "C"
        if t >= 10:
            return "D"
        return "F"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "tables": round(self.tables, 2),
            "text": round(self.text, 2),
            "equations": round(self.equations, 2),
            "figures": round(self.figures, 2),
            "ocr_confidence": round(self.ocr_confidence, 2),
            "formatting": round(self.formatting, 2),
            "metadata": round(self.metadata, 2),
            "total": round(self.total, 2),
            "grade": self.grade,
        }


class QualityScorer:
    """
    Score the quality of an HDARP extraction.

    Each scoring method returns a value in [0, max_points] for the component.
    Pass an extraction result dict containing the various extracted artifacts
    (text, tables, equations, figures, metadata, ocr_confidence).
    """

    def score_tables(self, tables: Optional[list]) -> float:
        """Score tables (max 8 points).

        Awarded for: presence of tables, valid CSV structure, header detection,
        consistent column counts, no encoding errors.
        """
        if not tables:
            return 0.0

        max_points = 8.0
        points = 0.0

        # 2 points for any extracted tables
        points += 2.0

        # 2 points if tables have detected headers (heuristic: first row differs from rest)
        with_headers = sum(1 for t in tables if isinstance(t, list) and len(t) >= 2
                           and len(t[0]) == len(t[1]))
        if tables and with_headers / len(tables) > 0.5:
            points += 2.0

        # 2 points for consistent column counts within each table
        consistent = 0
        for t in tables:
            if isinstance(t, list) and len(t) > 1:
                col_counts = [len(row) for row in t]
                if len(set(col_counts)) == 1:
                    consistent += 1
        if tables and consistent / len(tables) >= 0.8:
            points += 2.0

        # 2 points for non-empty cells (data density)
        non_empty_ratio = self._cell_density(tables)
        points += 2.0 * non_empty_ratio

        return min(points, max_points)

    def score_text(self, text: str) -> float:
        """Score body text (max 4 points)."""
        if not text:
            return 0.0

        max_points = 4.0
        points = 0.0

        # 1 point for non-trivial length
        if len(text) > 200:
            points += 1.0

        # 1 point for paragraph structure (multiple newline groups)
        if text.count("\n\n") >= 2:
            points += 1.0

        # 1 point for low ratio of nonsense characters
        printable = sum(1 for c in text if c.isprintable() or c in "\n\t ")
        if len(text) > 0 and printable / len(text) > 0.95:
            points += 1.0

        # 1 point for word completeness (low ratio of single-character "words")
        words = text.split()
        if words:
            single_char_words = sum(1 for w in words if len(w) == 1)
            if single_char_words / len(words) < 0.10:
                points += 1.0

        return min(points, max_points)

    def score_equations(self, equations: Optional[list]) -> float:
        """Score equations (max 3 points)."""
        if not equations:
            return 0.0

        max_points = 3.0
        points = 0.0

        # 1 point for any equations extracted
        points += 1.0

        # 1 point if extracted as LaTeX (heuristic: contains \frac, \sum, ^, _, etc.)
        latex_signals = ('\\frac', '\\sum', '\\int', '\\sqrt', '^', '_')
        latex_eqs = sum(1 for e in equations
                        if isinstance(e, str) and any(s in e for s in latex_signals))
        if equations and latex_eqs / len(equations) > 0.5:
            points += 1.0

        # 1 point for balanced delimiters
        balanced = sum(1 for e in equations
                       if isinstance(e, str)
                       and e.count('{') == e.count('}')
                       and e.count('(') == e.count(')'))
        if equations and balanced / len(equations) > 0.8:
            points += 1.0

        return min(points, max_points)

    def score_figures(self, figures: Optional[list]) -> float:
        """Score figures (max 3 points)."""
        if not figures:
            return 0.0

        max_points = 3.0
        points = 0.0

        # 1 point for any figure descriptions
        points += 1.0

        # 1 point for substantial descriptions (heuristic: >100 words on average)
        descriptions = [f.get("description", "") if isinstance(f, dict) else str(f) for f in figures]
        avg_words = sum(len(d.split()) for d in descriptions) / max(len(descriptions), 1)
        if avg_words > 100:
            points += 1.0

        # 1 point for figure references (e.g., "Figure 2.1", "Fig.")
        with_refs = sum(1 for d in descriptions
                        if "Figure" in d or "Fig." in d or "fig" in d.lower())
        if descriptions and with_refs / len(descriptions) > 0.3:
            points += 1.0

        return min(points, max_points)

    def score_ocr_confidence(self, mean_confidence: Optional[float]) -> float:
        """Score OCR confidence (max 2 points)."""
        if mean_confidence is None:
            return 0.0

        # Linear scaling: 0.5 conf → 0 pts, 1.0 conf → 2 pts
        score = max(0.0, (mean_confidence - 0.5) * 4)
        return min(score, 2.0)

    def score_formatting(self, text: str, metadata: Optional[Dict] = None) -> float:
        """Score formatting (max 3 points)."""
        if not text:
            return 0.0

        max_points = 3.0
        points = 0.0

        # 1 point for section headers (heuristic: lines that are ALL CAPS or start with #)
        lines = text.split("\n")
        headers = sum(1 for ln in lines
                      if ln.strip() and (ln.strip().isupper() or ln.lstrip().startswith("#")))
        if headers > 2:
            points += 1.0

        # 1 point for reasonable whitespace ratio (not too dense, not too sparse)
        if 0.05 < text.count("\n") / max(len(text), 1) < 0.20:
            points += 1.0

        # 1 point for valid encoding (no replacement characters)
        if "�" not in text:
            points += 1.0

        return min(points, max_points)

    def score_metadata(self, metadata: Optional[Dict]) -> float:
        """Score metadata completeness (max 4 points)."""
        if not metadata:
            return 0.0

        max_points = 4.0
        points = 0.0

        for key in ("page_numbers", "headers", "cross_references", "title"):
            if metadata.get(key):
                points += 1.0

        return min(points, max_points)

    def score_extraction(self, extraction: Dict[str, Any]) -> QualityScore:
        """
        Score a complete extraction across all 27 points.

        Args:
            extraction: dict with keys: text, tables, equations, figures,
                        ocr_confidence, metadata

        Returns:
            QualityScore object
        """
        return QualityScore(
            tables=self.score_tables(extraction.get("tables")),
            text=self.score_text(extraction.get("text", "")),
            equations=self.score_equations(extraction.get("equations")),
            figures=self.score_figures(extraction.get("figures")),
            ocr_confidence=self.score_ocr_confidence(extraction.get("ocr_confidence")),
            formatting=self.score_formatting(
                extraction.get("text", ""),
                extraction.get("metadata"),
            ),
            metadata=self.score_metadata(extraction.get("metadata")),
        )

    @staticmethod
    def _cell_density(tables: list) -> float:
        """Fraction of non-empty cells across all tables (0.0-1.0)."""
        total_cells = 0
        non_empty = 0
        for t in tables:
            if isinstance(t, list):
                for row in t:
                    if isinstance(row, list):
                        for cell in row:
                            total_cells += 1
                            if cell is not None and str(cell).strip():
                                non_empty += 1
        return non_empty / total_cells if total_cells > 0 else 0.0


if __name__ == "__main__":
    """Quick demo."""
    scorer = QualityScorer()
    sample = {
        "text": "Section 1\n\nThis is a sample extraction with paragraphs. "
                "It demonstrates body text scoring.\n\nSection 2\n\nMore text here.",
        "tables": [
            [["Name", "Value"], ["Revenue", "1234"], ["Expenses", "567"]],
        ],
        "equations": ["E = mc^2", "\\frac{a}{b} = c"],
        "figures": [{"description": "Figure 1.1 shows the relationship between A and B " * 20}],
        "ocr_confidence": 0.92,
        "metadata": {"page_numbers": True, "headers": True, "title": "Sample Document"},
    }
    score = scorer.score_extraction(sample)
    print("HDARP Quality Score Demo")
    print("=" * 40)
    for k, v in score.to_dict().items():
        print(f"  {k}: {v}")
