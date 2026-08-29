# The HDARP Protocol, v6 — Direct Agent Reading for Hard Documents

**Status**: specification (the runnable Python in this repository implements the v5.1
OCR-consensus half; see the README). This document describes the protocol as practiced today.
It is written to be standalone: no internal tooling is required to read it.

---

## 1. What problem this solves

Hard documents — scanned books, statistical annuals, archival reports, mixed content with tables
and equations — defeat plain OCR pipelines. Vision-capable AI agents *can* read them, the way a
person does: look at the page, understand the table, transcribe the equation. But naive agent
reading fails **silently and at scale**: the model returns something plausible, the pipeline
accepts it, and three hundred pages later nobody can tell which extraction was real.

HDARP v6 is the discipline layer around agent reading. Its position can be stated in one line:

> **Agents read the chunks; the protocol makes their reading checkable — and refuses to let a
> failure masquerade as a success.**

## 2. Lifecycle

```
source PDF
  → prepare:  measure, split into chunks (manifest recorded)
  → extract:  one chunk at a time — agent reads; four content types captured
  → check:    per-chunk completeness (all four types dispositioned)
  → validate: batch-level review; can FAIL a batch back to prepared
  → record:   per-document processing detail; provenance from source to artifact
```

Each stage emits artifacts to disk. Conversation state is disposable; the artifacts are the
source of truth.

## 3. Mandatory chunking

- Any PDF over **10 pages OR 1 MB** is split before processing. No exceptions.
- One chunk is read, processed, and committed at a time — never a whole-document single pass.
- The splitter is **density-aware** (text-heavy vs image-heavy pages get different
  pages-per-chunk and size budgets, with retry-on-overshoot). The repository's `splitter.py`
  implements one such strategy; the protocol requires *some* measured, adaptive strategy, not
  this exact one.
- Every chunk carries boundary markers into its extraction (e.g. `<!-- chunk 031 -->`), so a
  validator can prove the extraction corresponds to a real chunk of the real document.

## 4. The four content types — and the completeness rule

Every chunk is checked for all four types:

| Type | Artifact | Absence handling |
|---|---|---|
| Body text | structured full text (or digest) with chunk markers | required — a chunk with no body text is flagged |
| Tables | CSV with headers | "no tables present" is recorded explicitly |
| Equations | LaTeX | "no equations present" is recorded explicitly |
| Figures | structured description with context | "no figures present" is recorded explicitly |

**The completeness rule**: a chunk processed for body text only, with no recorded disposition of
the other three types, is *incomplete by definition*. The absence of a type is data ("this chunk
has no tables") and must be written down; it may not be inferred from silence. This rule exists
because the failure mode it prevents was observed in the wild: an entire corpus extracted with
zero tables and zero equations, validated as complete, because nothing checked.

## 5. Extraction modes

Chosen per document, recorded per document (`extraction_method` field):

- **Verbatim** — faithful, structured full-text extraction. Default for public-domain and
  technical sources.
- **Analytical digest** — a neutral, encyclopedic *paraphrase* of each chunk: arguments, events,
  data, and themes restated; only short verbatim quotes. Default for in-copyright trade books,
  and for any document whose verbatim extraction would exceed processing budgets. The mode is a
  fidelity choice, not a quality grade — both modes are complete extractions under §4.

## 6. Validation — the stage that can fail

A validator (in practice: a second model pass with a rubric) examines each processed batch:

1. **Provenance**: chunk markers present and sequential; artifact directories non-empty or
   explicitly marked empty.
2. **Completeness**: per-chunk, all four types dispositioned (§4).
3. **Honesty of failure**: pages the reader could not read are *marked as such* — an
   `[UNREADABLE]` marker is a valid outcome; a silently smoothed-over gap is not.
4. **Verdict**: a batch is validated, failed back to `PREPARED` for re-extraction, or
   (rarely, with recorded cause) quarantined.

Self-validation by the same pass that extracted is not validation.

## 7. The retry ladder (failures are worked, not wished away)

When an extraction attempt fails — content refusal, timeout, transport error, billing gate —
the ladder is:

```
content refusal → bisect the chunk recursively to single pages
              → per-page retry with scholarly framing
              → only then: log the page for OCR rescue
timeout        → bisect; single-page retries
transient API  → immediate retry → 30 s → 5 min → requeue
file corrupt   → only a genuinely unreadable file is quarantined
```

Exactly **three outcomes** may terminate a chunk without extraction, each recorded:

1. **DUPLICATE** — the content provably exists elsewhere in the corpus (hash or recorded
   confirmation, never "looks similar").
2. **CF_EXHAUSTED** — content filter refused the page at every rung of the ladder.
3. **QUARANTINED** — the file is physically unreadable (zero recoverable content), which is a
   property of the file, not a judgment about scan quality — poor scans get the OCR path.

Everything else gets extracted. Confusion, unfamiliarity, "low quality", "too large", and
first-try refusals are all reasons to climb the ladder, not to stop.

## 8. Anti-silent-degradation — the hardest rule

The incident that shaped v6: a long-running extraction campaign, hitting repeated agent
failures on scanned PDFs, silently switched to a plain OCR text dump — then *validated it as
complete* and deleted its inputs. The result was a corpus that claimed quality it did not have.

The rule, in three checkable parts:

1. **Never substitute** a mechanical text dump *for* agent extraction and label it as such.
   (Mechanical dumps are fine as *additional* artifacts, clearly labeled.)
2. **Never validate** output that fails the completeness rule (§4) — a text-only file is not a
   complete extraction, whatever its word count suggests.
3. **Never mark complete** a batch whose extraction method changed mid-run without the change
   being recorded and caused.

If extraction fails: **stop and report.** Switching methods to "get through it" is the failure
mode, not the recovery.

## 9. OCR's two supporting roles (and only two)

OCR is not the headline in v6. It serves exactly two functions:

1. **The verbatim sibling.** Alongside the agent extraction — after it, into a separate tree — a
   straight OCR pass over the same pages. Its purpose is comparison: the two readings of the
   same page can be checked against each other. It is *augmentation, never substitution*:

   | | substitution (forbidden) | augmentation (required) |
   |---|---|---|
   | when | instead of agent reading | after agent extraction completes |
   | where | the extraction's own tree, labeled as extraction | a separate tree |
   | claims | to *be* the extraction | to be a second, verbatim reading |

2. **Per-page rescue.** The terminal rung of §7's ladder: a page that defeats agent reading at
   every step gets an OCR recovery pass, spliced in with a rescue marker so every reader knows
   how that page was produced.

The consensus engine in this repository (six rules adjudicating three OCR engines line-by-line)
is the component design used for these roles in one production lineage; other engines may fill
the slot. Document-adaptive routing — instant extraction for digital pages, GPU OCR for scans,
escalation only on QA failure — is an implementation detail of the OCR layer, not of the
protocol.

## 10. Per-document processing records

A document is not "done" until its record exists:

- **Identity & lineage**: content hash of the source, document id, batch id.
- **Chunking**: split count, processed count, complete count.
- **Content counts**: tables / equations / figures / body-text size; absence recorded as zero,
  never omitted.
- **Quality & status**: score, status (`PREPARED` → `COMPLETE` → `VERIFIED`), extraction mode,
  process version.
- **Provenance**: preparation/processing/completion dates, processing agent, validator,
  retry counts, output location.

The record is the audit surface: corpus-level claims are computed from records, never asserted.

## 11. Scope boundaries

- **HDARP (this protocol)** is the *agent-reading* discipline: chunking, four-type completeness,
  validation, retry, records. It is engine-agnostic about the vision model.
- **The OCR layer** (partially shipped here) fills the two §9 roles.
- A **separate local-GPU engine** exists in the same production ecosystem (multi-model vision
  routing over a single consumer GPU). It is a distinct system with its own failure taxonomy;
  it is neither part of this package nor claimed by this specification.
- **In-house campaign lanes** that change the model roster do not change this specification.

## 12. Version history (protocol level)

| Version | What it added |
|---|---|
| v5.1 | The OCR-consensus layer (this repository's code) — frozen snapshot, 2026-05-01 |
| v6.0 | Direct agent reading as the protocol's center: four-type completeness, anti-silent-degradation, retry ladder |
| v6.1 (refinements) | Mandatory per-document processing records; corpus-level audit cataloging |
| v6.2 | The two extraction modes (verbatim / analytical digest); output-budget discipline |
| v6.3 | Native enrichment capture — table metadata recorded at extraction time rather than recovered later |

Numbers note: this specification makes **no accuracy claims**. Where the README or docs cite
figures, they are indicative of development use, not published benchmarks.

---

*License and citation: see the repository root.*
