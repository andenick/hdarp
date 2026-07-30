"""
Assertion tests for the 6-rule consensus engine.

These pin the values the README and docs/CONSENSUS_RULES.md quote, so a change
in the rule hierarchy or in a confidence cap fails here instead of silently
making the documentation wrong.

Run: python -m pytest
"""

import pytest

from hdarp.consensus import Sraffa30ConsensusEngine


@pytest.fixture()
def engine():
    return Sraffa30ConsensusEngine()


# ---------------------------------------------------------------------------
# Rule 1-6: the documented hierarchy
# ---------------------------------------------------------------------------

def test_rule1_perfect_agreement(engine):
    result = engine.adjudicate(
        paddle_text="Hello World", paddle_conf=0.95,
        easyocr_text="Hello World", easyocr_conf=0.92,
        tesseract_text="Hello World", tesseract_conf=0.88,
    )
    assert result.text == "Hello World"
    assert result.rule_applied == "perfect_agreement"
    assert result.confidence == pytest.approx(0.99)  # capped at 0.99


def test_rule2_majority_agreement_matches_readme_quickstart(engine):
    """The exact Quick Start call in README.md must produce the documented output."""
    result = engine.adjudicate(
        paddle_text="Total Revenue: $1,234,567", paddle_conf=0.92,
        easyocr_text="Total Revenue: $1,234,567", easyocr_conf=0.88,
        tesseract_text="Total Revenue: $l,234,567", tesseract_conf=0.75,
        column_type="TEXT",
    )
    assert result.text == "Total Revenue: $1,234,567"
    assert result.rule_applied == "majority_agreement"
    assert result.confidence == pytest.approx(0.95)  # Rule 2 caps at 0.95
    assert result.winning_engines == ["paddle", "easyocr"]


def test_rule3_high_confidence_unilateral(engine):
    result = engine.adjudicate(
        paddle_text="Quarterly Report", paddle_conf=0.97,
        easyocr_text="", easyocr_conf=0.20,
        tesseract_text="Quart ly", tesseract_conf=0.35,
    )
    assert result.text == "Quarterly Report"
    assert result.rule_applied == "high_confidence_unilateral"
    assert result.confidence == pytest.approx(0.90)  # capped at 0.90


def test_rule4_column_type_validation_cleans_numeric(engine):
    """Rule 4 only gets a turn once Rules 1-3 have fallen through."""
    result = engine.adjudicate(
        paddle_text="1O5.3", paddle_conf=0.85,
        easyocr_text="lO5.3", easyocr_conf=0.40,
        column_type="NUMERIC",
    )
    assert result.text == "105.3"
    assert result.rule_applied == "column_type_validation"
    assert result.confidence == pytest.approx(0.92)  # capped at 0.92


def test_rule4_is_skipped_when_engines_share_the_same_error(engine):
    """
    Known limitation, asserted so it cannot be quietly "fixed" in the docs only:
    when both engines make the SAME numeric error, Rule 1 fires first and the
    error survives uncleaned.
    """
    result = engine.adjudicate(
        paddle_text="1O5.3", paddle_conf=0.85,
        easyocr_text="1O5.3", easyocr_conf=0.82,
        column_type="NUMERIC",
    )
    assert result.text == "1O5.3"  # NOT cleaned to 105.3
    assert result.rule_applied == "perfect_agreement"


def test_rule5_character_similarity(engine):
    result = engine.adjudicate(
        paddle_text="Financial Statement", paddle_conf=0.88,
        easyocr_text="Financial Statment", easyocr_conf=0.86,
    )
    assert result.text == "Financial Statement"  # higher-priority engine wins
    assert result.rule_applied == "character_similarity"
    assert result.confidence == pytest.approx(0.90)  # capped at 0.90
    assert result.metadata["similarity"] >= 0.80


def test_rule6_default_to_primary(engine):
    result = engine.adjudicate(
        paddle_text="Alpha", paddle_conf=0.75,
        easyocr_text="Beta", easyocr_conf=0.72,
        tesseract_text="Gamma", tesseract_conf=0.70,
    )
    assert result.text == "Alpha"
    assert result.rule_applied == "default_to_primary"
    assert result.confidence == pytest.approx(0.675)  # 0.75 * 0.9


# ---------------------------------------------------------------------------
# Honesty tests: what the engine does NOT do
# ---------------------------------------------------------------------------

def test_rule6_confidence_range_is_060_to_090(engine):
    """Documented range is [0.60, 0.90] — there is no 0.85 cap."""
    low = engine.adjudicate(
        paddle_text="Alpha", paddle_conf=0.05,
        easyocr_text="Beta", easyocr_conf=0.04,
        tesseract_text="Gamma", tesseract_conf=0.03,
    )
    high = engine.adjudicate(
        paddle_text="Alpha", paddle_conf=1.00,
        easyocr_text="Beta", easyocr_conf=0.02,
        tesseract_text="Gamma", tesseract_conf=0.01,
    )
    assert low.confidence == pytest.approx(0.60)   # floor
    assert high.confidence == pytest.approx(0.90)  # ceiling, not 0.85


def test_engine_applies_no_minimum_confidence_threshold(engine):
    """
    The engine returns the primary engine's text even when every engine
    distrusts its own read, and floors the reported confidence UP to 0.60.
    Callers needing a "do not use below X" policy must apply their own floor.
    """
    result = engine.adjudicate(
        paddle_text="Itcm A", paddle_conf=0.11,
        easyocr_text="Xtem B", easyocr_conf=0.09,
        tesseract_text="Ztum C", tesseract_conf=0.05,
    )
    assert result.text == "Itcm A"          # not dropped, not gap-marked
    assert result.confidence == pytest.approx(0.60)  # raised from 0.11


# ---------------------------------------------------------------------------
# Degenerate inputs
# ---------------------------------------------------------------------------

def test_single_engine_returns_its_own_confidence(engine):
    result = engine.adjudicate(paddle_text="Only one", paddle_conf=0.42)
    assert result.rule_applied == "single_engine"
    assert result.confidence == pytest.approx(0.42)


def test_no_engines_returns_empty(engine):
    result = engine.adjudicate(paddle_text="", paddle_conf=0.0)
    assert result.text == ""
    assert result.rule_applied == "no_engines"
    assert result.confidence == 0.0


def test_all_engines_empty_is_low_confidence(engine):
    result = engine.adjudicate(
        paddle_text="", paddle_conf=0.5,
        easyocr_text="", easyocr_conf=0.4,
    )
    assert result.text == ""
    assert result.rule_applied == "perfect_agreement_empty"
    assert result.confidence == 0.0


# ---------------------------------------------------------------------------
# Statistics
# ---------------------------------------------------------------------------

def test_statistics_count_each_rule(engine):
    engine.adjudicate(paddle_text="A", paddle_conf=0.9, easyocr_text="A", easyocr_conf=0.9,
                      tesseract_text="A", tesseract_conf=0.9)
    engine.adjudicate(paddle_text="Alpha", paddle_conf=0.75, easyocr_text="Beta",
                      easyocr_conf=0.72, tesseract_text="Gamma", tesseract_conf=0.70)

    stats = engine.get_statistics()
    assert stats["total_adjudications"] == 2
    assert stats["perfect_agreement"]["count"] == 1
    assert stats["default_to_primary"]["count"] == 1

    engine.reset_statistics()
    assert engine.get_statistics()["total_adjudications"] == 0
