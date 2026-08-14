# Tabular Analyze/Search Line Terminology Routing Fix

## Issue Description

A customer reported that a prompt phrased around "line" instead of "row"
never triggered the durable tabular Analyze/Search parity pipeline for
**either** Analyze or Search:

> "For each line in this document, I need eight questions answered. I want
> the questions to be answered individually for each line item. Do not
> consolidate by bank or by activity. Go line by line and make sure all
> eight questions are answered for each line..."

Production evidence (chat export PDFs and Application Insights logs)
confirmed the request was handled entirely by the old bounded foreground
`TabularProcessingPlugin.query_tabular_data` tool-calling loop instead of the
durable background pipeline: the assistant's response explicitly stated
"the supplied evidence is truncated after FRI-007" out of 200 total rows,
and a second attempt (with both Document Search and Workspace Search
enabled) produced only a 3-row sample plus a claim that "the full assessment
covers FRI-001 through FRI-200" without ever generating that assessment.

Version implemented: **0.250.197**.

## Root Cause Analysis

Two independent gaps combined to produce this failure.

### 1. Every exhaustive/per-row intent detector recognized "row" but not "line"

At least eight separate keyword-list functions across four files decide
whether a prompt should be treated as an exhaustive, whole-dataset,
per-row request (which routes to the durable pipeline) versus a bounded,
sampled, or aggregate query (which stays on the foreground tool path):

- `functions_tabular_orchestration.py`: `question_requests_tabular_generated_output()`,
  `question_requests_tabular_hierarchical_analysis()`
- `functions_tabular_parity_contract.py`: `_question_requests_structured_artifact()`,
  `_question_requests_full_source()`
- `route_backend_chats.py`: `question_requests_attachment_backed_row_follow_up()`,
  `question_requests_tabular_structured_object_output()`,
  `question_requests_tabular_exhaustive_results()`
- `functions_document_analysis.py`: `_prompt_requests_per_source_output()`

Every one of these lists matched "each row", "every row", "for each row",
"for every row", "one row per", "all rows", etc., but **none** recognized
"line" as an equally natural synonym ("each line", "line by line", "for
each line", "one line per", "all lines"). The customer's prompt used "line"
exclusively and never used the word "row" at all, so none of these
detectors classified it as an exhaustive per-row request.

(Two closely related functions — `functions_document_analysis.py`'s
`_prompt_requests_exhaustive_output()` and
`functions_workflow_runner.py`'s `_prompt_requests_exhaustive_analysis_output()`
— already worked correctly for "line" phrasing by coincidence, because they
match the bare, generic substrings `"every "` and `"each "` rather than
requiring the following word to be "row".)

### 2. `enable_tabular_hierarchical_analysis` defaulted to off with no admin UI

Even after fixing the keyword gap, `question_requests_tabular_hierarchical_analysis()`
returning `True` is not sufficient on its own.
`get_tabular_generated_output_task_type()` only selects the durable
`hierarchical_analysis` task type when a second, backend-only setting,
`enable_tabular_hierarchical_analysis`, is also enabled:

```python
hierarchical_analysis_enabled = settings_flag_enabled(
    settings, "enable_tabular_hierarchical_analysis", False,
)
...
if hierarchical_analysis_requested and hierarchical_analysis_enabled:
    return TABULAR_RUN_TASK_HIERARCHICAL_ANALYSIS
return None
```

This flag defaulted to `False` in `DEFAULT_SETTINGS` and is listed in
`TABULAR_GENERATION_BACKEND_SETTING_KEYS`, meaning it has **no admin UI
toggle** — the same "always-on feature shipped disabled with no way to turn
it on" pattern already fixed once this session for
`tabular_request_planner_mode` / `enable_tabular_search_shared_preflight` /
`enable_tabular_analyze_durable_preflight` (see
[TABULAR_ANALYZE_SEARCH_PARITY_DEFAULT_ACTIVATION_FIX.md](./TABULAR_ANALYZE_SEARCH_PARITY_DEFAULT_ACTIVATION_FIX.md)).
This flag specifically gates **narrative** (non-CSV/JSON/XML-export)
exhaustive per-row/per-line Analyze and Search requests — exactly the
customer's scenario — so it needed the same fix.

Both gaps had to be fixed together: the keyword fix alone would have made
`hierarchical_analysis_requested` `True` but `get_tabular_generated_output_task_type()`
would still have returned `None` with the flag off; the flag fix alone
would have had no effect because the request was never classified as
hierarchical-analysis intent in the first place.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_orchestration.py`: added
  `"all lines"`, `"every line"`, `"for each line"`, `"for every line"`,
  `"line by line"`, `"one line per"`, `"each line"` to the exhaustive-marker
  tuples in `question_requests_tabular_generated_output()` and
  `question_requests_tabular_hierarchical_analysis()`.
- `application/single_app/functions_tabular_parity_contract.py`: added the
  same line-phrase set to `_question_requests_structured_artifact()`'s
  `structured_markers` and `_question_requests_full_source()`'s
  `exhaustive_markers`.
- `application/single_app/route_backend_chats.py`: added line-phrase
  variants to `question_requests_attachment_backed_row_follow_up()`'s
  `per_row_markers`, `question_requests_tabular_structured_object_output()`'s
  `structured_markers`, and `question_requests_tabular_exhaustive_results()`'s
  `explicit_phrases` plus two new `structured_row_patterns` regexes for
  "one line per"/"one object for each line"/"for each/every line".
- `application/single_app/functions_document_analysis.py`: added line-phrase
  variants to `_prompt_requests_per_source_output()`'s `source_output_markers`.
- `application/single_app/functions_settings.py`: flipped
  `enable_tabular_hierarchical_analysis` default from `False` to `True`;
  extended `_apply_tabular_parity_env_kill_switch()` to also force it back
  off when `SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT` is set.
- `application/single_app/config.py`: version bump to `0.250.197`.
- `functional_tests/test_tabular_line_terminology_routing_fix.py` (new):
  verifies "line" phrasing is recognized, the exact customer prompt resolves
  to the `hierarchical_analysis` durable task type for both Analyze and
  Search, reproduces the bug with the flag off, and verifies the default
  value plus the extended env kill switch.

### Code Changes Summary

```python
# functions_settings.py
'enable_tabular_hierarchical_analysis': True,  # was False
...
if _env_flag_enabled('SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT'):
    settings_payload['tabular_request_planner_mode'] = 'off'
    settings_payload['enable_tabular_search_shared_preflight'] = False
    settings_payload['enable_tabular_analyze_durable_preflight'] = False
    settings_payload['enable_tabular_hierarchical_analysis'] = False  # added
```

### Testing Approach

- New: `test_tabular_line_terminology_routing_fix.py` (3/3 passing) —
  directly imports `functions_tabular_orchestration`/`functions_tabular_parity_contract`
  (both import-safe with two lightweight dependency stubs) and drives the
  exact customer prompt end to end through `get_tabular_generated_output_task_type()`.
- Re-validated with no regressions: `test_tabular_shared_request_planner.py`,
  `test_tabular_analyze_search_parity_contract.py`, `test_analyze_deliverable_contract.py`,
  `test_tabular_phase7_lifecycle_coverage.py`, `test_tabular_phase7b_production_correctness.py`,
  `test_tabular_phase8_ui_telemetry_rollout.py`, `test_tabular_phase9_legacy_retirement.py`,
  `test_tabular_analyze_search_parity_default_activation.py`,
  `test_tabular_document_actions_workflow.py`, `test_tabular_search_shared_preflight_adapter.py`,
  `test_tabular_analyze_shared_preflight_adapter.py`, `test_tabular_transformations_phase4.py`,
  `test_analyze_artifact_phase7_rollout_rollback.py`, `test_tabular_exhaustive_result_synthesis_fix.py`,
  `test_tabular_execution_settings_sanitization.py`, `test_tabular_row_orchestration_scale.py`
  (full suite, exit code 0). All pass.
- Confirmed pre-existing, unrelated failure in `test_tabular_entity_lookup_mode.py::test_per_row_exports_route_to_exhaustive_mode`
  (`_shared_question_requests_tabular_generated_output` is not defined in that
  test's AST-extracted namespace) reproduces identically on unmodified
  `Development` — not caused by this change, out of scope for this fix.
- `python -m py_compile` and editor diagnostics clean across all changed files.

## Impact Analysis

- Fixes exhaustive per-row/per-line detection for **every** caller of the
  affected functions, not just Analyze/Search chat prompts (e.g., document
  action workflows that route through `functions_document_analysis.py`).
- `enable_tabular_hierarchical_analysis` defaulting to active affects any
  narrative (non-export) whole-dataset Analyze/Search request, broadening
  durable-pipeline coverage beyond just "line"-phrased prompts.
- No behavior change for requests that don't match any exhaustive-intent
  marker; bounded/sampled/aggregate queries continue to use the foreground
  tool path as before.
