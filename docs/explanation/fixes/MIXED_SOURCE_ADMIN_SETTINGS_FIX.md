# Mixed-Source Admin Settings Fix

Fixed/Implemented in version: **0.261.266**

Related config.py update: `VERSION = "0.261.266"`

## Header Information

### Issue description

Admin Settings in the V2 interface showed five switches under **Knowledge > Web &
Research > Deep Research** with no description, only a label generated from each
key name:

| Switch shown | What it actually did |
| --- | --- |
| Mixed source analyze (`enable_mixed_source_analyze`) | Nothing. The gate was removed in 0.250.071, when combined Analyze began routing mixed narrative and tabular selections natively. The key survived only in stored settings documents. |
| Mixed source analyze all (`enable_mixed_source_analyze_all`) | Allowed an Analyze target of every document in scope, which no chat or workflow screen can request. |
| Mixed source manifest (`enable_mixed_source_manifest`) | Phase 1 shadow mode: resolved a source manifest in the background, discarded it, and logged on failure. Every mixed-source path now resolves its manifest for real. |
| Mixed source relevance candidates (`enable_mixed_source_relevance_candidates`) | Nothing on its own. It extends `enable_mixed_source_chat_search`, which had no control in either admin interface. |
| Mixed source development telemetry (`enable_mixed_source_development_telemetry`) | Aggregate `[MIXED_SOURCE_TELEMETRY]` counts and timings in Application Insights. |

The behaviors that mattered most had no control at all. `enable_mixed_source_chat_search`
and `enable_mixed_source_conversation_continuity` were suppressed from the V2 page and
absent from the classic page, and `enable_cross_format_compare` and
`enable_cross_format_compare_one_to_many` were filed under "Other capabilities". All of
them defaulted off, so:

- The classic chat page ignored selected documents whenever its Search Documents panel
  was closed.
- Workflow Search did not run selected spreadsheets through the spreadsheet engine.
- Comparing a document with a spreadsheet failed with "Mixed narrative and tabular
  Compare is temporarily unavailable while cross-format Compare is disabled."

### Root cause analysis

1. **Placement.** None of the keys was declared in `admin_settings_fields.py`, so the V2
   page drew them with its `enable_*` fallback scan, which files a key under the first
   section sharing the most word stems. Every `enable_mixed_source_*` key matched only
   "source" in `source-review-section`, which is Deep Research. The cross-format pair
   matched nothing.
2. **Stale keys.** Commit `a4834912d` removed the defaults for `enable_mixed_source_analyze`
   and `enable_mixed_source_analyze_all`, but `deep_merge_dicts()` never deletes keys, so
   deployments that had loaded settings earlier kept both in Cosmos DB, and the scan kept
   drawing them.
3. **Staged rollout never finished.** The mixed-source phases (#1055 to #1061) shipped
   behind default-off switches pending production approval. The switches that gate the
   user-facing behavior were never exposed, so nobody could approve them from the
   product.

### Version implemented

0.261.266

## Technical Details

### Decisions

Every mixed-source tabular step needs `is_tabular_processing_enabled()`, which is
`enable_enhanced_citations`. With Enhanced Citations on, a spreadsheet is indexed as one
schema summary chunk and has to go through the spreadsheet engine; with it off, rows are
indexed as text chunks. Forcing the mixed-source path on everywhere would have turned
spreadsheets in deployments without Enhanced Citations from "searched as text" into
"unavailable", because Phase 6 forbids a table falling back to narrative processing.

| Key | Now |
| --- | --- |
| `enable_mixed_source_chat_search` | Derived from `enable_enhanced_citations` on every load and save; suppressed in V2 |
| `enable_mixed_source_conversation_continuity` | Derived the same way; suppressed |
| `enable_cross_format_compare` | Derived the same way; suppressed |
| `enable_cross_format_compare_one_to_many` | Derived the same way; suppressed. The Comparison document limits still bound Targets. |
| `enable_mixed_source_relevance_candidates` | Administrator choice under **Chat > Citations > Enhanced**, shown while Enhanced Citations is on. Default **on**; a one-time upgrade turns it on for existing deployments. |
| `enable_mixed_source_development_telemetry` | Administrator choice under **Operations > Logging & Health > Application Insights**, default off |
| `enable_mixed_source_analyze_all` | Default restored to off and suppressed in V2. The one-time upgrade resets it to off. |
| `enable_mixed_source_analyze` | Retired; removed from stored settings on load |
| `enable_mixed_source_manifest` | Retired; removed on load, and the shadow-resolution code is deleted |

The derived behaviors have one rollback path: the `SIMPLECHAT_DISABLE_MIXED_SOURCE`
environment variable, applied to every settings read in `_format_result` and never
persisted. This mirrors `SIMPLECHAT_DISABLE_TABULAR_PARITY_DURABLE_PREFLIGHT`.

`enable_appinsights_global_logging` is now declared in `application-insights-section`
too. The scan had filed it under Debug Logging on the word "logging", which would have
left the telemetry switch alone in an otherwise empty Application Insights section.

### Files modified

| File | Change |
| --- | --- |
| `application/single_app/functions_settings.py` | `MIXED_SOURCE_DERIVED_SETTING_KEYS`, `normalize_mixed_source_derived_settings()`, `normalize_mixed_source_settings_upgrade()`, `_apply_mixed_source_env_kill_switch()`; two keys added to `RETIRED_SETTING_KEYS`; defaults updated; `is_mixed_source_manifest_enabled()` removed |
| `application/single_app/route_backend_chats.py` | `_maybe_resolve_chat_source_manifest()` and its two call sites removed |
| `application/single_app/functions_workflow_runner.py` | Shadow manifest block removed from `_maybe_execute_tabular_document_action()`; Compare limitation message names Enhanced Citations |
| `application/single_app/admin_settings_fields.py` | Relevance candidates declared under Enhanced Citations; `application-insights-section` declared; Enhanced Citations help text names spreadsheet analysis; suppression reasons updated and three keys added |
| `application/single_app/templates/admin/_panes/citation.html` | "Spreadsheets in Chat" card with the relevance switch |
| `application/single_app/templates/admin/_panes/logging.html` | Metrics switch under Application Insights |
| `application/single_app/route_frontend_admin_settings.py` | Classic save persists both switches |

### One-time upgrade

`mixed_source_settings_version` (default `0`) records whether the upgrade ran. On the
first load at version 1 it turns relevance candidates on and Analyze All off, then
stores the marker, so an administrator who turns relevance candidates off later keeps
that choice. It runs on load only, never on save.

### Impact

- Deployments with Enhanced Citations on start using mixed-source Chat and Search,
  follow-up continuity and cross-format Compare on the first settings load after
  upgrading.
- The first load rewrites the settings document once. Saved orchestration runs bind to
  a fingerprint of the full settings, so a run paused across the upgrade may report that
  its execution context changed, exactly as after any administrator save.
- With Enhanced Citations off, behavior is unchanged, apart from the actionable Compare
  message. The classic chat page still uses selected documents only while its Search
  Documents panel is on; the V2 chat already sends them whenever they are attached.
- The flag-off branches remain in code as the kill switch path.

## Validation

### Tests

| Test | Covers |
| --- | --- |
| `functional_tests/test_mixed_source_settings_derivation.py` | Derivation from Enhanced Citations, read-time kill switch, retired keys purged and unseeded, one-time upgrade and later choices, admin declarations in both interfaces, classic save, Compare message |
| `functional_tests/test_v2_admin_capability_placement.py` | New relocations and suppressions; no mixed-source key left to the fallback scan |
| `ui_tests/test_v2_admin_mixed_source_settings.py` | Built V2 page with the real schema: nothing mixed-source under Deep Research, both switches described in their sections, the spreadsheet switch hidden without Enhanced Citations, saves through the field normalizer; classic panes submit both switches |
| Updated suites | `test_mixed_source_chat_search_consistency.py`, `test_mixed_source_conversation_continuity.py`, `test_cross_format_compare_workflow.py`, `test_tabular_document_actions_workflow.py`, `test_orchestration_single_contract.py`, `test_docs_app_surface_coverage.py`, and the settings writer tests that stub normalizers |

### Before and after

| | Before | After |
| --- | --- | --- |
| Deep Research section | Five unlabelled mixed-source switches | Deep Research settings only |
| Relevance candidates | Shown, no effect | Described under Enhanced Citations, effective, default on |
| Telemetry | Under Deep Research | Under Application Insights with a privacy statement |
| PDF compared with XLSX | Fails while the hidden switch is off | Works with Enhanced Citations; otherwise refused with a message naming it |
| Classic chat, panel closed, Enhanced Citations on | Selected documents ignored | Selected documents used |

## Related

- `docs/admin/chat.md` (Enhanced Citations) and `docs/admin/operations.md` (Application Insights)
- `docs/explanation/fixes/MIXED_SOURCE_ANALYZE_GATING_REMOVAL_FIX.md`
- `docs/explanation/features/MIXED_SOURCE_CHAT_AND_SEARCH_CONSISTENCY.md`
- `docs/explanation/features/CROSS_FORMAT_COMPARE.md`
- `docs/explanation/features/V2_ADMIN_CHAT_SETTINGS.md`
