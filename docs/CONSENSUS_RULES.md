# 6-Rule OCR Consensus Adjudication

## Why Consensus?

Three OCR engines looking at the same text will produce three different results. PaddleOCR might read "Revenue: $1,234"; EasyOCR might read "Revenue: $1,234"; Tesseract might read "Revenue: $l,234" (lowercase L instead of 1). Which one is right?

The naive approach is to pick the one with the highest confidence score. But confidence scores are not comparable across engines — PaddleOCR's 0.92 doesn't mean the same thing as Tesseract's 0.92. And in practice, the wrong answer often comes back with high confidence.

The HDARP consensus engine solves this with a hierarchy of six rules, applied in priority order until one matches.

## The Hierarchy

### Rule 1: Perfect Agreement
**Fires when**: All available engines produce identical text.

**Confidence formula**: `1 - (1-p₁)(1-p₂)(1-p₃)`

This is the probabilistic combination assuming engine errors are independent. If three engines independently produce the same text with confidences 0.90, 0.85, and 0.80, the probability that all three are wrong is (0.10)(0.15)(0.20) = 0.003. So our confidence in the agreed text is 0.997 — capped at 0.99.

**Capped confidence**: 0.99 (we never claim certainty)

**Example**:
```
PaddleOCR:  "Revenue: $1,234" (conf 0.90)
EasyOCR:    "Revenue: $1,234" (conf 0.85)
Tesseract:  "Revenue: $1,234" (conf 0.80)
→ Result:   "Revenue: $1,234" (conf 0.997 → 0.99)
```

### Rule 2: Majority Agreement
**Fires when**: Two or more engines agree but not all three.

**Confidence formula**: `min(0.95, prob_combined × 1.05)` — 5% boost for consensus

Two-out-of-three agreement is strong evidence but not as strong as three-way agreement. We boost the combined confidence slightly to reflect the agreement signal.

**Capped confidence**: 0.95

**Example**:
```
PaddleOCR:  "Revenue" (conf 0.91)
EasyOCR:    "Revenue" (conf 0.89)
Tesseract:  "Revenua" (conf 0.75)  ← disagrees
→ Result:   "Revenue" (conf 0.95, winning_engines=["paddle", "easyocr"])
```

### Rule 3: High-Confidence Unilateral
**Fires when**: One engine has confidence >0.95 AND all others have confidence <0.50.

**Confidence formula**: `min(0.90, high_conf)` — slightly reduced because no agreement

If one engine is very confident and the others have essentially given up, trust the confident one. This handles cases where two engines fail (e.g., on stylized fonts) but one engine handles it well.

**Capped confidence**: 0.90

**Example**:
```
PaddleOCR:  "Quarterly Report" (conf 0.97)
EasyOCR:    ""                  (conf 0.20)  ← failed
Tesseract:  "Quart ly"          (conf 0.35)  ← failed
→ Result:   "Quarterly Report" (conf 0.90, winning_engines=["paddle"])
```

### Rule 4: Column-Type Validation
**Fires when**: Column type is "NUMERIC" and we can clean a result into a valid number.

**Confidence formula**: `min(0.92, conf × 1.1)` — 10% boost for type validation

This rule catches semantic errors. The most common: O→0, I→1, l→1, S→5. If we know we're looking at a numeric column and an engine reads "1O5.3" with high confidence, we can clean it to "105.3" and validate that it's a valid number.

**Capped confidence**: 0.92

**Example**:
```
column_type = "NUMERIC"
PaddleOCR:  "1O5.3" (conf 0.85)  ← O instead of 0
EasyOCR:    "lO5.3" (conf 0.40)  ← l instead of 1, O instead of 0
Tesseract:  ""      (conf 0.0)
→ Rules 1-3 fall through (the engines disagree)
→ Cleaned:  "105.3"
→ Result:   "105.3" (conf 0.92, winning_engines=["paddle"], rule="column_type_validation")
```

**Known limitation — correlated errors are NOT caught.** The rules are tried in
order, so if both engines make the *same* mistake, Rule 1 (perfect agreement)
fires before Rule 4 is ever consulted and the error survives:

```
column_type = "NUMERIC"
PaddleOCR:  "1O5.3" (conf 0.85)
EasyOCR:    "1O5.3" (conf 0.82)  ← same OCR error
→ Result:   "1O5.3" (conf 0.973, rule="perfect_agreement")   ← not cleaned
```

Both cases are asserted in `tests/test_consensus.py`.

### Rule 5: Character Similarity
**Fires when**: Two engines produce texts with >80% character similarity (using `SequenceMatcher`).

**Confidence formula**: `min(0.90, ((conf1 + conf2) / 2) × 1.1)` — average with boost

If two engines mostly agree but differ in one or two characters (typical OCR variance), pick the one from the higher-priority engine.

**Capped confidence**: 0.90

**Example**:
```
PaddleOCR:  "Financial Statement" (conf 0.88)
EasyOCR:    "Financial Statment"  (conf 0.86)  ← missing 'e', 97% similar
Tesseract:  ""                    (conf 0.0)
→ Similarity: 0.973
→ Result:   "Financial Statement" (conf 0.90, winning_engines=["paddle", "easyocr"])
```

### Rule 6: Default to Primary
**Fires when**: No other rule applies.

**Confidence formula**: `max(0.60, conf × 0.9)` — reduced because uncertain

Fallback to the highest-priority engine (PaddleOCR), with reduced confidence because we couldn't reach consensus.

**Confidence range**: [0.60, 0.90] — engine confidence × 0.9, floored at 0.60

**Example**:
```
PaddleOCR:  "Alpha"   (conf 0.75)
EasyOCR:    "Beta"    (conf 0.72)  ← different
Tesseract:  "Gamma"   (conf 0.70)  ← different
→ No agreement, no high-confidence unilateral, no similarity
→ Result:   "Alpha" (conf 0.675, winning_engines=["paddle"], rule="default_to_primary")
```

Note the strings have to be genuinely dissimilar to reach Rule 6: near-misses
like "Item A" / "Item B" are >80% similar and are taken by Rule 5 instead.

Note also that the 0.60 floor cuts both ways. It discounts a confident engine
(0.90 → 0.81), but it *raises* a read the engine itself distrusted (0.11 →
0.60). Rule 6 never drops a line.

## Engine Priority

The consensus engine ranks engines for tie-breaking:

| Engine | Priority | Why |
|--------|----------|-----|
| PaddleOCR | 3 (highest) | Best raw accuracy on most document types |
| EasyOCR | 2 | Strong on degraded scans; good fallback |
| Tesseract | 1 (lowest) | Fast and reliable but lower raw accuracy |

The priorities live in a plain dict on the engine (`engine.engine_priority`), which you can override after construction; the constructor takes no arguments. The defaults come from development use on academic papers, regulatory filings, and historical documents — not from a published benchmark.

## Statistics Tracking

Every adjudication updates a counter. The values below are an **illustrative example** of the shape of `get_statistics()` output — not measured results from a published benchmark:

```python
engine.get_statistics()
# {
#   'total_adjudications': 1284,
#   'perfect_agreement': {'count': 892, 'percentage': 69.5},
#   'majority_agreement': {'count': 261, 'percentage': 20.3},
#   'high_confidence_unilateral': {'count': 73, 'percentage': 5.7},
#   'column_type_validation': {'count': 28, 'percentage': 2.2},
#   'character_similarity': {'count': 24, 'percentage': 1.9},
#   'default_to_primary': {'count': 6, 'percentage': 0.4}
# }
```

This is itself a useful diagnostic. A high `default_to_primary` percentage suggests the document is challenging — perhaps a degraded scan or unusual font. A high `perfect_agreement` percentage suggests clean input.

## Why This Hierarchy?

The rules are ordered by reliability of evidence:

1. **Perfect agreement** is the strongest signal (probability of three independent failures is tiny)
2. **Majority agreement** is the next strongest (one outlier is more likely than two)
3. **High-confidence unilateral** handles the "one engine has the right tool for this job" case
4. **Column-type validation** catches systematic errors that all engines made the same way
5. **Character similarity** handles the "close but not exact" case
6. **Default to primary** is the safe fallback

Each rule's confidence cap reflects the strength of its evidence. Perfect agreement gets 0.99; the default fallback is capped at 0.90 (engine confidence × 0.9) and floored at 0.60.

## No confidence threshold: what the engine will *not* do for you

This engine always returns a text. It has **no** minimum-confidence threshold, **no** gap marker, and **no** "below threshold" return path — the only empty results are the degenerate ones (`no_engines` when nothing was passed in, `perfect_agreement_empty` when every engine returned an empty string).

Concretely, three garbage reads come back as an asserted line:

```
PaddleOCR:  "Itcm A" (conf 0.11)
EasyOCR:    "Xtem B" (conf 0.09)
Tesseract:  "Ztum C" (conf 0.05)
→ Result:   "Itcm A" (conf 0.600, rule="default_to_primary")
```

The 0.60 you get back is the floor, not a measurement of that line.

For scholarly and regulatory use, where a fabricated number is worse than a missing one, the caller must therefore apply its own floor to `result.confidence` and decide what to do below it. Gap marking belongs to the surrounding protocol, not to this package. This behaviour is asserted in `tests/test_consensus.py::test_engine_applies_no_minimum_confidence_threshold`.
