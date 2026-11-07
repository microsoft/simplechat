# Orchestration Timeline Visual Delivery Fix

**Version: 0.261.341**

Fixed in version: **0.261.341**, recorded in
`application/single_app/config.py`.

## Issue

An Orchestrate request asked to turn an earlier gravel-ride nutrition plan into a
two-lane schedule: eating and fueling in one lane, drinking and hydration in the
other, from before the ride through recovery. The answer-writing task completed,
but the plan panel marked the chart **Not delivered** with the reason
"The answer did not include it."

## Root cause

The planner could classify an event schedule as a numerical chart because the
user called it a chart. That selected analytical-chart instructions, which
discourage charts for purely textual material and forbid substituting Mermaid
for numerical data charts. A schedule is better represented as a structural
diagram with event labels than as invented numerical series.

Separately, compose accepted any nonempty Markdown as prepared content. Its
single corrective call covered malformed JSON outputs, not an omitted explicit
visual. Finalization correctly detected the missing chart, but only after the
answer-writing task had finished. A Mermaid schedule declared as a chart also
failed delivery: charts require a `simplechart` fence, whereas diagrams require
a `mermaid` fence.

The screenshot did not include the complete generated answer, saved plan, or
model response. The investigation reproduced this delivery path locally; it
does not establish precisely why the deployed model omitted the chart.

## Technical changes

- `functions_orchestration_planner.py` distinguishes activity schedules and
  event timelines from measured numerical plots. Schedule requests use diagram
  deliverables and the structured `diagram` visual flag, even when called charts.
- `functions_diagram_operations.py` explains a two-lane representation using
  `flowchart TB`, labelled subgraphs, and `direction LR` within each lane.
  Relative times remain event labels, without invented calendar dates or values.
- `functions_orchestration_deliverables.py` shares the existing visual-format
  presence rule between compose omission checks and final answer delivery.
  Compiled deliverable context identifies which explicit, enabled visuals the
  compose step owes.
- `functions_orchestration_composition.py` makes at most one application-level
  corrective call for either an output-shape problem or a missing explicit chart
  or diagram. Correction must still satisfy the declared output kinds and
  schemas. Charts already placed from upstream results satisfy the check without
  another model call.

The retry preserves context-budget checks, authorization, cancellation, named
inputs, and hashed logging. Neither generated answer text nor source content is
included in corrective-call logs. No integration action or retrieval is repeated
to correct the prepared answer.

## Delivery behavior

Before this fix, a prose-only Markdown reply immediately finished the compose
step and reached finalization with its chart missing.

After this fix, the step requests a complete corrected answer once. A successful
correction carries the renderable visual into the answer and its delivery state
becomes **Delivered**. Suggested visuals do not cause retries.

If correction cannot fit the context budget, the original usable answer is kept.
If a schema-valid correction still omits the visual, the corrected usable answer
is kept. Existing finalization reports partial completion and **Not delivered**
for an explicit visual missing from the final answer. Invalid correction output,
provider failures, and revoked access retain their existing explicit failure
paths rather than masquerading as successful correction.

Saved plans are not silently relabelled. A schedule already declared as a chart
needs replanning to become a diagram. True numerical charts continue to require
their native chart format.

## Validation

The regression harness supplies the earlier nutrition plan as conversation
reference data and runs the real schema, executor, result retention, compose,
and final publication services with offline model replies. It covers:

- omission followed by a delivered two-lane diagram;
- repeated omission retaining a usable answer and partial delivery;
- native-chart correction without accepting Mermaid as a numerical chart;
- JSON-shape and visual corrections sharing one allowance, without a third call;
- malformed corrections, context-budget refusal, and access/cancellation changes
  immediately before correction;
- suggested visuals, already-present visuals, and upstream charts avoiding
  unnecessary model calls;
- correction logs containing codes and hashed identifiers, not private replies.

Coverage lives in `test_orchestration_compose_output_retry.py`,
`test_orchestration_visual_outputs.py`,
`test_orchestration_action_chart_delivery.py`, and the existing
`test_mermaid_diagram_prompt_guidance.py` suite. The shared deliverables fixture
also supports retained conversation history for this scenario.

These four suites passed together: **84 tests passed**. Eight additional
deliverables-contract regressions passed, including shared fixture use, CSV
delivery, visual flag derivation, and answer binding behavior. Documentation
surface coverage passed all seven checks and site quality passed all six checks.
The regression failed before the implementation with the same failed-run/partial-
outcome combination as the reported missing visual. A headless Chromium probe
rendered the two-lane example using the pinned local Mermaid 11.17.2 bundle,
confirmed both lanes and relative-time labels, and made no network requests.

The local system Python had an incompatible OpenSSL dependency combination;
validation used a separate virtual environment without changing shared packages.
Additional broad deliverables runs encountered native PyMuPDF access violations
in existing Office-renderer tests. Those unrelated renderer paths are not
changed or claimed as validated by this fix.

## Limitations

Visual selection and the corrective answer remain model-generated. One correction
is not a guarantee that a visual will be produced, and it must not invent source
data to force success. Format presence is not complete Mermaid syntax validation,
chart semantic validation, or proof that every distinct requested visual appears.
The final answer's existing delivery check remains authoritative.

The two-lane flowchart shows event sequence and relative-time labels, not exact
time-scaled duration. This fix adds no browser library, chart type, setting,
capability, route, or deployment requirement.

See [Review and edit orchestration plans](../../guides/review-and-edit-orchestration-plans.md)
for the user-facing behavior.
