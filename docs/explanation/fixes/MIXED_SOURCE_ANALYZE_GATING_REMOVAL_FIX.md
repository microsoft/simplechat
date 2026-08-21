# Mixed-Source Analyze Gating Removal Fix

Version: 0.250.071

Fixed/Implemented in version: **0.250.071**

Related config.py update: `VERSION = "0.250.071"`

## Header Information

- Issue description: Combined Analyze rejected a selected mixture of narrative and tabular documents when the internal mixed-source rollout setting was false.
- Root cause analysis: The workflow runner used a default-off settings flag to choose between the native mixed-source workflow and legacy single-engine paths. The legacy path then raised an error for mixed document types.
- Version implemented: 0.250.071

## Technical Details

- Files modified: `application/single_app/functions_workflow_runner.py`, `application/single_app/functions_settings.py`, `application/single_app/config.py`, `functional_tests/test_mixed_source_analyze_workflow.py`.
- Code changes summary: Combined Analyze now always uses the existing authorization-safe mixed-source workflow for both agent and direct-model runners. The obsolete settings defaults, helpers, and legacy rejection path were removed.
- Testing approach: Updated the focused functional test to require automatic mixed-source routing, preserve per-document behavior, and reject reintroduction of the settings flag.

## Validation

- Test results: `functional_tests/test_mixed_source_analyze_workflow.py` passes with all three tests successful.
- Before/after comparison: Before the fix, a PDF/DOCX plus XLSX/CSV selection could fail with a disabled mixed-source Analyze message. After the fix, selected narrative and tabular sources are partitioned and analyzed by their native engines before a combined response is produced.
- User experience improvements: Users can select compatible narrative and tabular documents together for Analyze without requiring an administrator or deployment setting change.