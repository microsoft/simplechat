# TABULAR MULTISHEET LLM REVIEWER RECOVERY FIX

Fixed/Implemented in version: **0.240.035**

Related config.py update: `VERSION = "0.240.035"`

## Header Information

- Issue description: Some multi-sheet workbook questions got very close to the answer but still stalled after schema discovery, returning schema-only narration instead of committing to the next analytical tool call.
- Root cause analysis: The main tabular SK loop could preload workbook structure and even perform discovery, but if the same model still failed to choose an analytical function, the route had no final reasoning pass to convert the discovered workbook context into an explicit executable plan.
- Version implemented: 0.240.035

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`
- Code changes summary: Added a last-resort LLM reviewer path for multi-sheet analytical runs. When the main SK loop still fails to produce computed analytical results, the route now asks the model for a JSON-only analytical tool plan, injects the correct file source context, executes those analytical plugin calls directly, and returns compact computed results back to the normal answer pipeline.
- Testing approach: Added focused functional regression coverage for reviewer JSON extraction, function-name normalization, source-context injection, reviewer recovery wiring, and the new version bump.
- Impact analysis: Multi-sheet workbook questions can now recover from near-miss discovery-only runs without hardcoded content or column heuristics because the LLM makes the final tool-selection decision from workbook schema and prior discovery output.

## Validation

- Test results: Focused regressions verify reviewer plan parsing, argument normalization, route wiring, and the preserved all-scope source-context behavior under the new version.
- Before/after comparison: Before the fix, close workbook questions could stop after `describe_tabular_file` and fall back to schema narration; after the fix, the route gets one more LLM-driven analytical planning chance and can directly execute the chosen tool calls.
- User experience improvements: Users get fewer “close but not computed” workbook answers because near-miss runs can recover into actual tabular tool execution instead of giving up after discovery.