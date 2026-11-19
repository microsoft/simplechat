# Post-0.261.439 Retest Remediation Fix (v0.261.443)

Fixed/Implemented in version: **0.261.443**

Related configuration update: `application/single_app/config.py` increments
`VERSION` from `0.261.442` to `0.261.443`.

## Issue

A ten-case federal retest of 0.261.439 (35 original requests, 27 saved
assistants) produced 2 passes, 2 partial results and 6 failures. Three independent
read-only investigations compared the saved runs, Application Insights traces and
source behavior. They agreed on the failure boundaries but not on every cause, and
none replayed the product. This fix changes only what that evidence confirms is
wrong, and adds content-free diagnostics where the evidence could not locate the
failing operand, record or stage. It is not a live acceptance result.

## What the evidence confirmed, and what it did not

| Area | Evidence | Status in this fix |
| --- | --- | --- |
| Native PDF and PowerPoint properties | Raw native responses already carried a PDF's `/Lang` and four bookmarks, but the canonical audit facts omitted them with no truncation. | Fixed: typed `language` and `bookmarks` facts. |
| Native record paging | A byte-bounded page returned a prefix of the records (about 29 of 111 for one tagged PDF, about 10 of 118 for the PowerPoint), and the follow-up chain was model-driven. | Fixed: coverage states how many whole records were returned; partial review is disclosed. |
| Planner and calculation contract | The relationship contract left every expression and predicate open. Planner rejections named `oneof` with no location, and execution failures carried only an error class. | Fixed: grammar and column rules are visible to the planner, unavailable columns are corrected before approval, and failures name a stable code and location. |
| Source continuation | The comparison of earlier source selections was sensitive to list order. The actual conflicting records were not captured. | Fixed for order-only differences; genuine differences stay ambiguous and are now diagnosable. |
| Exact titles | A saved answer already contained an added backslash before the browser rendered it; the inserting stage was not localized. | Fixed at the last boundary; the inserting stage remains unknown. |
| Inline comparison versus a new deck | The planner declared an explicit deck deliverable for a request to show each concern's slide. | Fixed: planner guidance separates showing content from creating a file. |
| Action results | Two actions failed with no usable function results, and their checkpoints could not distinguish "never called" from "returned nothing". | Diagnostics only. The no-usable-result refusal is unchanged. |
| Step budget | One logged `plan_step_budget` event showed a single dictionary step with no raw count or limit. | Diagnostics only. No limit is raised. |

Not changed: the exact failed relational specifications and operands, the actual
competing continuation selections, whether the two actions made zero calls or
lost results, the first wrong stage of the supplier-identity merge, the exact
live NASA reference handle, and per-request serving-image provenance. Those need
the new diagnostics to be observed on a later separately approved run. The strict
Office package guard, retained read-only inspectors, source files, arithmetic
engine, tool catalog and action budgets are unchanged.

## Technical details

### Native evidence

- `functions_pptx_native_evidence.py` emits a typed `language` fact from
  `docProps/core.xml`.
- `functions_accessibility.py` adds `language` (`/Root/Lang`) and `bookmarks`
  (`/Root/Outlines`) to PDF native properties, and `language` to the PowerPoint
  fallback. The bookmark state comes from the catalog's own `/Outlines` entry, not
  from how many entries the outline reader returned: no entry is `absent`, an
  outline container with no first item and no declared entries is `present_empty`,
  and an outline that cannot be established (a non-dictionary entry, a count with
  no first item, an unreadable first item, or a catalog and outline reader that
  disagree) is `inaccessible` with a reason. It was checked against hand-built
  catalogs for each of those shapes and against the two original FEMA PDFs (the
  tagged one has four bookmarks and the untagged one has no `/Outlines` entry, so
  neither state changes).
- `functions_native_document_inspection.py` raises the native inspection version
  to `1.2`, because the properties inventory gains records. An older continuation
  cursor is refused as a changed source instead of silently shifting.
- `functions_native_audit.py` reports `returned_records_from_start` in
  `inventory_coverage`, instructs answers to state partial review, and escapes a
  vertical bar only inside a Markdown table row. The answer decoder restores an
  exact native value in prose, lists, headings and inline code, leaving table
  rows, fenced code and legitimate backslashes unchanged. Its review policy now
  defines `present_empty` as stored but empty (an empty string, or a bookmark
  outline with no entries), so an empty outline is not mistaken for an absent one.

### Planner and calculation contract

- `functions_tabular_relational.py` documents the expression grammar and the
  column propagation rules in the `relational_spec` schema description. Each
  statement is pinned to the runtime by tests. Typed content-free detail
  (`check`, `role`, `category`, step position and operation) is attached to
  rejections and failures, and a conservative `check_relational_columns`
  preflight applies the runtime's column rules to headers that are known exactly.
  A header is known exactly only when the names in the planning preview equal the
  names the calculation reader will use. The reader collapses repeated spaces and
  normalizes Unicode (`functions_tabular_merge.display_header_name`), so a header
  such as `Unit  Price` is left to the run instead of rejecting the spelling the
  reader would accept.
- `functions_tabular_transformations.py` gives each transformation failure a
  stable code derived from its fixed message. A test proves every message yields
  a unique, log-safe code that cannot be mistaken for a routing code.
- `functions_schema_diagnostics.py` (new) locates a schema failure using only
  schema-owned names: the innermost keyword, the property path with array
  positions, the oneOf alternative selected by a schema constant, and allowed
  properties or values. A property name the schema does not define is only counted.
  An alternative whose own constant (such as a step's `op`) equals the instance's
  value is chosen before closeness, so a derive step with several faults is never
  corrected with a filter step's fields. Only when no constant matches does the
  alternative with the fewest failures (then the lowest position) decide.
- `functions_orchestration_schema.py` adds those locations to argument problems,
  applies the column preflight inside the existing source-schema check, and adds
  the raw step count and effective limit to a hand-off `plan_step_budget`
  rejection. The ordinary `result_step_limit` error is unchanged.
- `functions_orchestration_native_results.py` carries the detail through the
  bridge and logs it on failure. `functions_orchestration_planner.py` also logs
  the diagnostics on each correction request and points the model at the
  documented grammar.
- `functions_appinsights.py` allows the new closed-token keys; see the
  [logging reference](../../reference/logging-tags.md).

### Continuation, actions and delivery

- `functions_orchestration_context.py` compares earlier source selections by
  canonical members, ignoring only list order. A different document, workspace
  scope, filter, reference or attachment message stays a different selection and
  still requires a choice. A conflict logs how many selections differ and in which
  dimension, never their document IDs.
- `functions_orchestration_actions.py` and `functions_orchestration_adapters.py`
  add started-call, captured-result, reply, correction, bound-document and limit
  counts to the `action_results_missing` failure.
- `functions_orchestration_planner.py` tells the planner that showing, listing,
  comparing or explaining what a document, slide or deck contains is an answer in
  the chat, and that a file or a document created from a reference is planned only
  when the user asks for one.

### Files modified

- Application: `config.py`, `functions_accessibility.py`,
  `functions_appinsights.py`, `functions_native_audit.py`,
  `functions_native_document_inspection.py`, `functions_orchestration_actions.py`,
  `functions_orchestration_adapters.py`, `functions_orchestration_context.py`,
  `functions_orchestration_native_results.py`, `functions_orchestration_planner.py`,
  `functions_orchestration_schema.py`, `functions_pptx_native_evidence.py`,
  `functions_schema_diagnostics.py` (new), `functions_tabular_merge.py` (one public
  helper, `display_header_name`), `functions_tabular_relational.py` and
  `functions_tabular_transformations.py`.
- Tests: the native fidelity, native audit reliability, native inspection
  request contract, tabular relational calculation, transformation precision,
  plan schema, planner contract recovery, relational results, selected-source
  planning, document loader reliability and deliverables suites.
- Documentation: the logging reference (including a corrected `debug_only` note),
  multi-file tabular calculations, and document accessibility and structure
  extraction.
- `functional_tests/cosmos_response_boundaries.json`: renewed module fingerprints
  for five unchanged Cosmos owners in `functions_orchestration_context.py`.

## Behavior and impact

| Situation | Before | After |
| --- | --- | --- |
| Source language and PDF bookmarks | Returned by the reader, omitted from facts | Present, absent, empty or inaccessible, as the source actually is |
| A large document's native properties | A prefix could read as a full review | Coverage says how many records were reviewed |
| A calculation that names a column its step no longer has | Failed after approval with `relational_column_missing` and no location | Corrected once before approval when the header is known; otherwise a located failure |
| A rejected relational plan | `oneof`, with no location | Innermost keyword, property path, step and allowed properties |
| A transformation run error | An error class | A stable code and the step that raised it |
| The same documents listed in another order | Reported as conflicting selections | One selection |
| Genuinely different earlier selections | A generic notice | The same notice, plus content-free logging of how they differ |
| Showing what a slide contains | Could be planned as a new deck | Answered in chat unless a file is requested |

No Flask route, authorization rule, credential handling, tool budget, source
document or sample row is added or changed. A source's original bytes are never
modified.

## Validation

All commands ran offline with Cosmos network access blocked, from the repository
root with `PYTHONPATH` set to `application/single_app` and `functional_tests`.
Each suite ran on the changed tree and on an unmodified archive of base commit
`a47100f7` (0.261.442), with the same file lists and options. The failed-test
sets were then compared by name.

- **Native evidence, 4 suites: 179 passed** (base: 151).
  `test_native_audit_reliability`, `test_native_audit_answer_delivery`,
  `test_native_inspection_request_contract` and `test_native_document_fidelity`.
  New cases cover tagged and untagged PDF fixtures for language, PowerPoint
  language present, empty and absent, partial-page disclosure, and exact title
  values in prose and inline code versus table cells. The bookmark cases write
  the catalog directly, so they cover shapes a PDF writer never emits: no
  `/Outlines`, an empty outline with and without a zero count, a count with no
  first item, an outline that is a number, an array, null or a dangling
  reference, and a dangling or non-dictionary first item. They also cover an
  emptied outline root written by pypdf, an outline reader that fails or
  disagrees with the catalog, and a valid outline item.
- **Accessibility and pipeline suites, 4 files: 77 passed, 2 failed**, the same
  two as on the base (see below).
- **Orchestration, planner, tabular and action suites, 18 files** (an earlier
  19-name list included one file that does not exist): **723 passed, 5 failed**.
  The same five fail on the base, which passes 648; the difference is the 75
  tests added here. New cases pin each documented expression shape and column
  rule to the runtime, compare the planning preflight with the runtime for eight
  kinds of unavailable column (same role and category, unknown headers never
  guessed, and a header the reader spells differently left to the run), name each
  semantic check without model text, prove every transformation message has a
  unique log-safe code, show planner corrections and runtime failures log a
  stable code and location without source values, cover order-independent and
  genuinely conflicting source sets, action result counts and step-budget
  diagnostics, and check the planner guidance for inline comparison. Derive,
  project and aggregate steps with several faults at once are located in the
  operation they name, and a step that names no known operation falls back to
  the closest alternative.
- **Tabular merge suites, 2 files: 60 passed** (base: 60), because
  `functions_tabular_merge.py` gained one public helper.
- **Documentation:** `test_docs_app_surface_coverage` and `test_docs_site_quality`
  pass (13 tests, base and changed). No setting, admin tab, action or chat
  control is added, so the application surface inventory is unchanged.
- **Cosmos response boundaries:** the checker reports **0 review gaps** across
  **1104 owners** and **430 doubles**. For the five unchanged owners in
  `functions_orchestration_context.py`, only the enclosing module fingerprint
  changed and their reviews were renewed by hand. The complete
  `python scripts/check_cosmos_response_boundaries.py --run-contracts` gate ran
  last, on the final code, and exited **0** with **1565 passed** in about 20
  minutes (the network-blocked core, owner-runtime and SDK-default contract
  suites).

### Pre-existing failures, unrelated to this fix

Each of these fails identically on the unmodified 0.261.442 base:

- 28 tests in the five `test_orchestration_workflow_*_off_golden` suites, whose
  captured planner requests are stale.
- `test_orchestration_tabular_reconciliation.py::test_composition_profile_validator_accepts_only_valid_mappings`.
- `test_orchestration_deliverables.py::test_an_invalid_deliverables_plan_gets_exactly_one_repair_call`.
- `test_orchestration_action_chart_delivery.py::test_a_gather_only_plan_gets_one_correction_round`.
- Two `test_native_auto_turn_reaches_a_saved_cited_answer` cases
  (`False-True-pdf` and `False-True-docx`), which fail only when run after the
  other suites in that sequence and pass on their own.
- `test_native_document_fidelity_pipeline.py::test_old_source_metadata_cannot_describe_a_sanitized_active_file`
  and `test_excel_document_accessibility_extraction.py::test_report_and_citations_reuse_authorized_contract`,
  which both raise a `NameError` for `validate_native_report_sections` in
  `functions_search_service.py`.

`test_tabular_relational_analysis_helpers.py` imports the application
configuration and cannot be collected without real Cosmos credentials, so it was
not run. No deployment, live replay or source upload was performed.

## Remaining evidence-gated items

These need a later, separately approved, unchanged-source run with the new
diagnostics, and are intentionally not guessed here:

- the exact specification or operand behind each remaining planner rejection and
  execution failure;
- the competing source selections, to decide whether a genuine conflict should
  offer a source-only clarification on the saved question;
- whether the two actions made no call or lost a result;
- which preparation stage first produced the unsupported supplier candidates and
  the extra title backslash;
- the exact live reference handle behind the NASA package failure. The original
  package declares seven slide-master parts that are absent, so the strict guard
  is correct to refuse it and is not relaxed.

## Related documentation

- [Multi-file tabular calculations](../features/MULTI_FILE_TABULAR_CALCULATIONS.md)
- [Document accessibility, structure and comment extraction](../features/DOCUMENT_ACCESSIBILITY_AND_STRUCTURE_EXTRACTION.md)
- [Logging reference](../../reference/logging-tags.md)
