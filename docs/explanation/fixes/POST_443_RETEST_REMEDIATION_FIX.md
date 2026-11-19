# Post-443 retest remediation

Version: **0.261.444**

Fixed/Implemented in version: **0.261.444**
(`application/single_app/config.py`).

## Issue description

Post-0.261.443 retesting found that complete tabular requests could be planned
from discovery previews, safe aggregate-to-detail rejoins were rejected before
the protected runtime ran, native relational failures lost safe locations, Word
comment CSV preparation omitted native attribution, and focused PowerPoint
object questions paged unrelated slides.

## Root cause

Relational normalization treated all shared ancestry as unsafe without
considering isolated output namespaces. Compose's source-presence validation
did not express whether table evidence needed an overview, complete rows or a
native calculation. Several error boundaries replaced, rather than merged,
content-free diagnostics. Native comment attribution remained only in the
retained Word reader, while composition records were not deterministically
projected from it. PPTX native pagination had no slide filter or XML ordinal.

## Technical changes

- `functions_tabular_relational.py`: namespace-aware derived rejoins with
  unchanged runtime collision, cardinality, interval, lineage and budget guards;
  merged safe relational/evaluator diagnostics.
- `functions_tabular_transformations.py`: bounded primitive-category,
  requested-type, field/expression and measure/value positions.
- `functions_orchestration_registry.py`, `functions_orchestration_schema.py`,
  `functions_orchestration_result_runtime.py`, `functions_orchestration_composition.py`:
  complete tabular purpose and authoritative records/lineage/coverage handoff.
- `functions_orchestration_context.py` and `route_backend_orchestration.py`:
  explicit source-conflict correlation and original-turn source-choice form.
- `functions_orchestration_excel.py`: lossless native Word attribution and reply
  metadata projection into existing scalar records.
- `functions_pptx_native_evidence.py`,
  `functions_native_document_inspection.py`, `functions_native_audit.py` and
  Document Search: XML object ordinal/text and slide-bound object cursors.
- Recovery owners and routes: code-owned guard/stage/producer diagnostics without
  changing fingerprint or replay policy.

The implementation review additionally closed four boundary gaps. Purpose
validation now follows trusted server source kinds through `document_search`,
not only native tabular producer IDs; overview mode cannot emit datasets or
replace an explicitly selected complete operation. Explicit invalid PowerPoint
slide filters remain invalid through the plugin rather than becoming omitted
filters. Tagged checkpoint, claim and harness recovery failures survive
application-owned wrapping into the existing Warning logger. Complete zero-root
Word comment inventories now remain valid evidence and can produce a
header-only disposition CSV; unknown or duplicate roots still refuse. The
delivery final-response comparison uses an initialized producer identity for
the no-plan-binding refusal, and provenance projection now requires a valid
nonnegative root count for every covered source, rejecting missing, null,
Boolean and negative counts.

No new global setting, dependency, source repair, model fallback, execution
replanning loop, source-equivalence relaxation or original-slide renderer was
added.

## Validation

Final local commands/results:

- Consolidated blocked-network remediation sweep: **660 passed**. This is the
  broad suite covering relational, planner/source-kind, selected-source,
  native-result, recovery, Word and native-inspection owners.
- Final edge-owner regressions: **97 passed**. These overlap the consolidated
  sweep and specifically cover the recovery logger/claim paths, Word count and
  export cases, and plugin isolation.
- Independently rerun final review selectors: **13 passed** (these also overlap
  the 660-test sweep).
- `check_cosmos_response_boundaries.py --refresh` followed by
  `--run-contracts`: **1,565 passed**; **1,104 owners**, **430 doubles**, and
  **0 review gaps**. The final refresh renewed five affected owner entries.
- Route policy scripts: **15/15**, **10/10**, and **4/4** passed.
- Documentation checks: inventory coverage **7/7** and site quality **6/6**.
- XSS full-file checks, `python -m compileall -q application\single_app`, and
  `git --no-pager diff --check`: passed.

The Word provenance regression uses the real native reader, retained
composition result and existing CSV exporter. The 660, 97 and 13 results are
not additive because the smaller runs intentionally repeat focused cases.
These commands validate implementation contracts only; no live deployment or
unchanged whole-case acceptance retest was run or claimed.

## Before and after

Before: a valid detail/summary rejoin was rejected, complete calculations could
consume preview-shaped evidence, later relational failures lacked locations, and
Word/PPTX requests lost native metadata or paged unrelated material.

After: safe isolated rejoins reach the existing runtime, complete calculations
require authoritative outputs, diagnostics retain bounded closed fields, Word
disposition exports receive native attribution deterministically, and PPTX
object focus stays within one slide. Word recovery fingerprint changes, extended
source equivalence, original-slide image rendering and live whole-case acceptance
remain separately gated.
