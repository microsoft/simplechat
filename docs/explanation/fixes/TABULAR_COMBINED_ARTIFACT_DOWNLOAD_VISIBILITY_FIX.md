# Tabular Combined Analyze Artifact Download Visibility Fix

## Issue Description

After the truncation fix and the combined-run `output_schema` deferral fix
shipped in `0.250.189` (see
[TABULAR_ANALYZE_SEARCH_PARITY_DEFAULT_ACTIVATION_FIX.md](./TABULAR_ANALYZE_SEARCH_PARITY_DEFAULT_ACTIVATION_FIX.md)),
a customer reported a new symptom on combined (Analyze) tabular runs:

> "its working, yay!, but its sitting at complete and never transitions to
> showing the file for download"

The chat UI shows the background export card reaching "Complete" at 100%
progress, but the Download CSV / View CSV / Add to Workspace controls never
appear. Production logs confirmed the run's Markdown analysis artifact and
CSV structured-export artifact both uploaded successfully
(`structured_artifact_message_id` and `analysis_artifact_message_id` were
populated in the `Background combined tabular run completed` log event), so
the files exist — the UI simply never surfaces them. This affected every
combined run observed in the follow-up production logs, not just one.

Version implemented: **0.250.191** (root cause fixed; diagnostics from
`0.250.190` retained permanently as low-noise guardrails).

## Root Cause Analysis

### The trigger: sanitization silently dropped `requested_artifacts`

`_normalize_tabular_run_planner_metadata()` sanitizes shared planner metadata
before it is persisted onto a durable run (stripping locators/raw prompts and
bounding sizes). It rebuilds the `deliverable_contract` sub-object from an
**explicit field whitelist** — and that whitelist never included
`requested_artifacts`:

```python
normalized_metadata['deliverable_contract'] = {
    'contract_version': ...,
    'action_mode': ...,
    'analysis_required': ...,
    'primary_artifact_role': ...,
    'public_output_schema': [...],
    'internal_checkpoint_schema': [...],
    'lineage_schema': [...],
    'row_cardinality': ...,
    'ordering': ...,
    'transformation_mode': ...,
    'validation_profile': ...,
    'publication_policy': ...,
    # requested_artifacts was missing entirely
}
```

Every run whose planner metadata passed through this sanitizer therefore
persisted a `deliverable_contract` with **zero** expected artifacts.

### Why that froze the download UI forever

At run completion, `_publish_artifact_set_members()` calls
`validate_analysis_artifact_set(deliverable_contract, validation_artifacts)`.
With `requested_artifacts == []`, the expected-artifact set is empty, so
**both** the published Markdown analysis artifact and the CSV sibling are
classified as `extra_artifact` — confirmed directly from the `0.250.190`
diagnostic log added to capture exactly this:

```text
[TABULAR_GENERATED_OUTPUT] Artifact set publication validation --
{'artifact_set_valid': False, 'reason_codes': ['extra_artifact'],
 'counts': {'expected_artifact_count': 0, 'actual_artifact_count': 2,
            'extra_artifact_count': 2, ...},
 'validation_artifacts': [
     {'artifact_id': 'analysis', 'role': 'primary_analysis', 'format': 'md', 'status': 'published'},
     {'artifact_id': 'requested-csv', 'role': 'requested_output', 'format': 'csv', 'status': 'published'}],
 'expected_artifact_ids': []}
```

Validation failure sets `artifact_set_manifest.lifecycle_state =
'rollback_required'`. The chat UI (`chat-messages.js`) only swaps the plain
progress card for the downloadable artifact-set card when
`isGeneratedArtifactSetComplete()` sees `lifecycle_state === 'completed'`;
any other value blocks the swap. Worse, `_build_or_update_artifact_set_manifest()`
only recomputes `lifecycle_state` from scratch when the persisted value was
`'planned'` — any other persisted value (like `rollback_required`) is
preserved verbatim on every later read — and the frontend stops polling
entirely once `run.status == 'completed'`. The combination made the freeze
permanent with no self-heal path, confirmed by the second `0.250.190`
diagnostic log (`Artifact set stuck below completed lifecycle on a completed
run`) firing repeatedly across both customer test runs.

### How this was found

A prior investigation pass (documented in this same file before the fix)
traced the full "happy path" — contract construction, descriptor resolution,
artifact tagging, and publication — using a real, unmocked deliverable
contract and could not reproduce the bug, because that reproduction built
the run's `tabular_planner_metadata` directly from the raw contract and
never routed it through `_normalize_tabular_run_planner_metadata()`, the
exact step that drops `requested_artifacts`. The two `0.250.190` diagnostic
log points were shipped specifically to close that evidence gap; the
customer's next test run captured the exact `reason_codes`/`expected_artifact_ids`
shown above within the same session, confirming the root cause immediately.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
  - Added `ANALYSIS_DELIVERABLE_MAX_ARTIFACT_ID_LENGTH` and
    `ANALYSIS_DELIVERABLE_MAX_ARTIFACTS` to the `functions_analysis_deliverables`
    import.
  - `_normalize_tabular_run_planner_metadata()`: added a bounded, sanitized
    `requested_artifacts` list to the persisted `deliverable_contract`,
    carrying `artifact_id`, `role`, `format`, `required`, and `request_order`
    per artifact (capped at `ANALYSIS_DELIVERABLE_MAX_ARTIFACTS` entries).
  - (From `0.250.190`, retained) `_publish_artifact_set_members()` and
    `_build_or_update_artifact_set_manifest()` diagnostic `log_event` calls.
- `application/single_app/config.py`: version bump to `0.250.191`.
- `functional_tests/test_tabular_phase5_artifact_set_lifecycle.py`: extended
  the shared AST-extraction helper loader to also expose
  `_normalize_tabular_run_planner_metadata()` (plus its transitive
  dependencies) so tests can route real planner metadata through the exact
  sanitizer production uses.
- `functional_tests/test_tabular_combined_artifact_set_download_visibility.py`:
  added `test_planner_metadata_sanitization_preserves_requested_artifacts()`
  as a direct regression guard for the root cause, and updated the other two
  tests to build the run's `tabular_planner_metadata` via the real sanitizer
  instead of the raw contract, so this suite would have caught the bug
  before it shipped.

### Code Changes Summary

```python
normalized_metadata['deliverable_contract'] = {
    ...
    'primary_artifact_role': str(deliverable_contract.get('primary_artifact_role') or '').strip().lower()[:80],
    'requested_artifacts': [
        {
            'artifact_id': str(artifact.get('artifact_id') or '').strip()[:ANALYSIS_DELIVERABLE_MAX_ARTIFACT_ID_LENGTH],
            'role': str(artifact.get('role') or '').strip().lower()[:40],
            'format': str(artifact.get('format') or '').strip().lower()[:20],
            'required': bool(artifact.get('required', True)),
            'request_order': _safe_int(artifact.get('request_order'), default=0, minimum=0),
        }
        for artifact in list(deliverable_contract.get('requested_artifacts') or [])[:ANALYSIS_DELIVERABLE_MAX_ARTIFACTS]
        if isinstance(artifact, dict) and str(artifact.get('artifact_id') or '').strip()
    ],
    'public_output_schema': [...],
    ...
}
```

### Testing Approach

- New: `test_planner_metadata_sanitization_preserves_requested_artifacts` —
  proves the real sanitizer preserves `requested_artifacts` end to end.
- Updated: `test_completed_combined_run_publishes_both_artifacts_for_download`
  and `test_stuck_artifact_set_emits_diagnostic_log_on_every_read` — both now
  build the run's planner metadata via the real sanitizer. All 3/3 pass.
- Re-validated with no regressions: `test_tabular_phase5_artifact_set_lifecycle.py`
  (4/4), `test_tabular_phase8_ui_telemetry_rollout.py` (4/4),
  `test_tabular_queue_run_output_schema_end_to_end.py` (2/2),
  `test_tabular_combined_output_schema_deferral_fix.py` (2/2),
  `test_tabular_analyze_search_parity_default_activation.py` (2/2),
  `test_tabular_row_orchestration_scale.py` (full suite, exit code 0).
- `python -m py_compile application/single_app/functions_tabular_generated_exports.py`
  and editor diagnostics clean across all changed files.

## Impact Analysis

- Fixes artifact-set publication validation for **every** durable tabular
  run whose planner metadata passes through `_normalize_tabular_run_planner_metadata()`
  with a non-empty `requested_artifacts` contract — not just combined
  (Analyze+export) runs, since structured-export-only and
  hierarchical-analysis-only runs share the same sanitizer.
- No behavior change for runs whose deliverable contract has no
  `requested_artifacts` (falls back to `_default_artifact_descriptors_for_run()`
  as before).
- The `0.250.190` diagnostic log points remain in place permanently as a
  low-noise (narrowly scoped) early-warning guardrail for any future
  regression in this area.

## Validation

**Before**: `artifact_set_valid: False`, `reason_codes: ['extra_artifact']`,
`lifecycle_state: rollback_required` (frozen forever, no download UI).

**After**: `artifact_set_valid: True`, `reason_codes: []`,
`lifecycle_state: completed`, both the Markdown analysis artifact and CSV
sibling returned as public `generated_artifacts`, verified via a real,
unmocked deliverable contract routed through the production sanitizer.

