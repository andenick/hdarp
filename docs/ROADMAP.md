# HDARP — Roadmap

**Status**: direction, not promises. Nothing here is dated, and nothing here is a claim about
current behavior. Where the protocol already does something, the link says so.

## Specification track

- **Machine-readable processing records (§10 of the v6 spec).** The record fields exist as
  prose; the direction is a published schema (JSON Schema) so corpus audits can be scripted by
  anyone, not just read by anyone.
- **Validator rubric as data.** The four validation checks (provenance, completeness, honesty
  of failure, verdict) are described qualitatively today; a machine-checkable rubric — with the
  completeness rule as its first assertion — is the natural next artifact.
- **Benchmarks, honestly.** The v6 spec deliberately makes no accuracy claims. A *published,
  reproducible benchmark corpus* for hard-document extraction (scans, tables, equations, with
  gold artifacts that can legally ship) is a goal. Until one exists and is run, no number in
  this repository will be presented as a measurement.

## Code track (this repository)

- The package remains the **v5.1 consensus reference implementation**. Plausible follow-ons,
  in rough order of value to a user of the package:
  - an adapter interface for the two §9 protocol roles (sibling pass, page rescue), so the
    consensus engine can be dropped into a v6-style pipeline as a component;
  - the density-aware splitter generalized beyond its current strategy table;
  - packaging niceties already present (tests, example) extended with a small corpus fixture.
- A full v6 agent-reading *implementation* is explicitly **not** on this roadmap: the protocol's
  agent half is a prompt/validation discipline over a vision-capable model, not a library, and
  shipping a half-version of it would blur the honest line this repository now draws between
  specification and code.

## Ecosystem notes

- The separate local-GPU engine (multi-model vision routing) referenced in the spec may publish
  its own artifacts, with its own evidence, under its own name. Cross-links will land here when
  they exist.
- In-house lane experiments that swap model rosters stay in-house until they change the
  *specification*, at which point this document and the version table update.

---

*Additions to this roadmap are made by pull request; items are removed by achieving them or by
explicitly cancelling them with a note — never by silence.*
