# Document analysis Markdown escape fix

**Version: 0.261.316**

Fixed in version: **0.261.316**, recorded in
`application/single_app/config.py`.

## Issue and root cause

A fresh PDF analysis read its entire source window but rejected two of six
findings. The extracted Markdown contained `2\. Partnership` and
`6\) TELEPHONE NUMBER`; the model quoted the rendered punctuation as
`2. Partnership` and `6) TELEPHONE NUMBER`. The shared evidence locator
treated the formatting backslashes as written content.

Each affected finding also had valid citations, but one unmatched citation makes
the finding unresolved. The final analysis therefore retained four findings and
was partial. Complete-only Compose correctly refused that input, before Word
rendering started. Ordinary search-backed chat does not use this same narrative
Analyze validation path.

## General formatting comparison

The shared normalized comparison now decodes Markdown backslash escapes of ASCII
punctuation in both the quote and source. It retains the punctuation itself and
maps it back to the original two-character source span. For example, `6\)`
can match `6)`, while saved evidence still contains `6\)` and its original
character offsets.

This is deterministic formatting normalization, not a document-specific
exception, an additional model evaluation, or a retry strategy. Exact matching
still runs first, preserving the [literal evidence fix](DOCUMENT_ANALYSIS_LITERAL_EVIDENCE_FIX.md).
The result contract, tiers, and `evidence-matcher-v2` identifier are unchanged.

Escaped punctuation stays literal after decoding: escaped asterisks and backticks
do not become emphasis, escaped angle brackets do not become HTML tags, escaped
ampersands do not begin entities, and escaped pipes do not become table separators.
Decoded character entities receive the same literal treatment.

## Safeguards and limitations

Backslash pairs are processed left to right. A doubled backslash represents a
literal backslash; a backslash before a letter is not a punctuation escape.
Backslashes inside recognized inline code, top-level backtick or tilde fences,
indented code lines, and HTML `code` or `pre` content remain literal. Unclosed
fences and HTML code regions are protected through the end of the text.
This is a conservative evidence normalizer, not a complete Markdown renderer;
it does not add support for every nested Markdown construct.

Punctuation, numbers, signs, and checkbox states must still agree. Missing,
wrong-location, ambiguous, paraphrased, and unsupported citations remain
unresolved. Complete-only Compose, source coverage, access checks, and findings
validation are unchanged. No citation is silently dropped to make a report pass.

Matching proves that a quotation can be located, not that every claim in a
finding is factually entailed by the quotation. No factual-accuracy evaluation
was added. Old failed attempts are not repaired or migrated; use a fresh request
after deployment. This change adds no settings, routes, dependencies, or
source-reprocessing requirements.

## Files and regression coverage

- `application/single_app/functions_document_analysis_results.py`: literal-span
  handling before markup and entity normalization.
- `functional_tests/test_document_analysis_evidence_matching.py`: punctuation
  escapes, backslash parity, literal code, source offsets, changed values,
  checkbox states, citation locations, and real Analyze finalization without
  correction calls.
- `functional_tests/test_orchestration_document_derivation_reliability.py`:
  escaped source evidence through real Analyze, Compose, Word rendering,
  publication, and download, using the existing offline harness.
- `application/single_app/config.py`: patch version update.

## Validation

The unchanged saved response was replayed offline against the original source,
with its content fingerprint verified. Before the fix, four findings were
accepted, two unresolved, and 23 evidence passages retained. After the fix,
all six findings were accepted, none unresolved, and all 25 evidence passages
retained. Source coverage remained complete. Normal and optimized Python
produced the same result, with no model calls or Azure writes.

The earlier footer incident also remains valid: all 25 findings pass unchanged.
The automated regressions exercise both positive matches and rejected content
changes, and the Word publication cases require exactly the existing two
analysis calls plus one composition call, with no response correction.

The targeted matcher, finalization, derivation, saved-result, workflow-publication,
and attempt-fence suites passed **379 tests and 272 subtests**. Documentation
surface coverage and site quality checks also passed. Validation used isolated
test dependencies; no shared Python packages or application manifests were
modified. No live deployment was performed.
