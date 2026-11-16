# Tabular evidence-first calculation fix

Version: **0.261.446**  
Fixed/Implemented in version: **0.261.446**  
Related configuration version: `application/single_app/config.py`

## Overview

### Issue

Multi-file tabular plans could gather complete originals but freeze a
calculation before that gathered context was available. A valid source could
then fail on an incorrect relationship grain, while the dependent answer and
generic recovery prose hid useful evidence. A natural follow-up could also
mistake an incorrectly false retrieval hint for permission to discard the
historical exact source selection.

### Root cause

Schema previews and Search receipts were not complete calculation context.
The native reader was complete, but its executable relationship program had
already been authored by the outer planner. The legacy relationship grammar
also lacked checked signed allocation and date-peer cumulative operations
needed by these calculations. Composition required an all-complete calculation
bundle even where a narrowly qualified preparation-only answer was possible.

## Technical details

### Complete preparation

`tabular_analyze` now has a `prepare` operation. It fully scans the selected
authorized CSV/Excel table, retains exact requested cell values with original
row provenance, records the complete header and row count, and commits key
profiles and coverage atomically. Preview rows cannot satisfy this contract.
The context is bounded at 96 KiB and fails explicitly if it cannot fit.

New model-authored multi-source `relate` work uses `calculation_mode=prepared-v1`
and one named preparation input. It cannot contain the old frozen
`relational_spec`. Saved and directly invoked trusted legacy explicit-spec
calculations retain their separate compatibility path.

### Bounded program lowering

The native owner receives the retained preparation and complete original
sources, then asks its existing bound model for one closed deterministic
program without tools. The lowering state durably reserves each call. There
are at most two logical calls: an initial call and one correction.

For this owner only, metadata `require_complete_generation=True` requires the
provider's trusted finish marker to be `"stop"`. Incomplete, missing or other
markers consume usage and the reserved call but cannot save or evaluate a
program. Resume uses only an owner-confirmed saved program or a definite saved
failure with remaining allowance. An uncertain reservation fails closed.

### Checked calculation operators

`tabular-relate-v2` adds:

- `allocate`: distinct event/detail identities, stable detail-ID order,
  absolute-weight fanout, signed USD conservation, HALF_UP cent rounding and
  exact residual assignment to the last detail.
- `cumulative_sum`: partitioned date ordering where all peers on one date see
  its complete signed total, with unknown amounts or keys preserved rather
  than converted to zero.

The v1 operations and numeric aggregate behavior remain available. Unknown,
excluded, Boolean, precision, lineage, cancellation and byte limits are
handled explicitly; no arbitrary code or SQL engine was introduced.

### Qualified calculation answer

The `calculation_answer` tabular requirement binds complete preparation plus
optional complete-only `records`, `lineage` and `coverage` outputs from one
calculation producer. All three calculation members are present or none is
used. If none is available after a definite calculation failure, the answer
may state verified rules, scope, counts and horizon and explain that the dated
monetary determination could not be verified. It does not create a financial
finding, chart or file from a partial calculation. The run remains partial.

Meaningful calculation failures expose closed public causes for incomplete
generation, program/grain invalidity and relationship mismatch without source
keys, operands or provider text. Deterministic-invalid work is not offered as
an unchanged retry.

### Exact source continuation and presentation

Follow-up admission compares exact historical source sets, scope, filters,
references, attachment messages and available source revisions. A false
retrieval flag cannot override a structured follow-up that requires the
original sources. New topics, explicit replacement, ambiguous history,
revocation and changed revisions remain fenced.

V2 progress now groups work as **Gather evidence**, **Prepare answer** and
**Deliver file** while retaining existing machine roles and execution order.
When a qualified partial answer already states the material calculation gap,
the duplicate generic recovery card is suppressed. Transport uncertainty,
approval, sign-in, cancellation and undelivered-file actions remain visible.

## Files and validation

Primary files include:

- `functions_tabular_merge.py`
- `functions_tabular_relational.py`
- `functions_orchestration_native_results.py`
- `functions_orchestration_execution.py`
- `functions_orchestration_checkpoints.py`
- `functions_orchestration_schema.py`
- `functions_orchestration_composition.py`
- `functions_orchestration_context.py`
- `application/v2_ui/src/lib/orchestrationPlan.ts`
- `application/v2_ui/src/components/chat/OrchestrationRecoveryNotice.tsx`

Focused tests cover the real native preparation/retention owner, trusted
complete-generation markers, reserved-call resume state, a portable 104-row
five-source fixture, every dated control, split allocation conservation,
cross-revision cumulative balances, the 250/750 unknown chains, Boolean
rejection, stable residual order, exact continuation and the V2 answer-first
presentation.

## Before and after

Before, the outer planner could author a fixed relationship spec before the
Gather result retained complete rule and grain context. A failed deterministic
calculation then produced only generic partial/dependency prose.

After, complete preparation is a required native input for newly authored
multi-source calculations. The owner lowers once, can correct one closed
defect, executes the deterministic v2 program, and either retains an atomic
complete bundle or supports a narrowly qualified answer from preparation.
No preview, partial bundle, omitted source or unconfirmed provider generation
is relabelled as a completed financial calculation.
