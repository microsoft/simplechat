# TABULAR DISTINCT VALUE HANDOFF FIX

Fixed/Implemented in version: **0.240.036**

Related config.py update: `VERSION = "0.240.036"`

## Header Information

- Issue description: Successful `get_distinct_values` reviewer-recovery runs could still produce weak final answers because the outer-model handoff compacted the value list too aggressively.
- Root cause analysis: The reviewer recovery stage executed the right analytical tool, but the raw fallback formatter treated distinct-value lists like generic payloads and reduced them to a tiny preview. The outer GPT then saw a truncated list and answered conservatively instead of using the tool-backed values.
- Version implemented: 0.240.036

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_raw_tool_fallback.py`, `functional_tests/test_tabular_llm_reviewer_recovery.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`, `functional_tests/test_tabular_all_scope_group_source_context.py`
- Code changes summary: Added a list-aware fallback path for `get_distinct_values` so full scalar value lists are preserved when they fit the prompt budget, updated the reviewer prompt to favor filtered distinct-value calls for subset questions, and clarified that full scalar lists can be enumerated directly by the outer model.
- Testing approach: Added regression coverage for preserved distinct-value lists, reviewer prompt guidance, and the version bump across the related tabular tests.
- Impact analysis: List-style workbook questions can now survive the inner-to-outer handoff without losing the tool-backed values the outer GPT needs to answer directly.

## Validation

- Test results: Focused regressions verify distinct-value fallback preservation, reviewer guidance, and the preserved tabular orchestration/version checks.
- Before/after comparison: Before the fix, reviewer recovery could succeed but the final answer still claimed truncation because only a preview of the distinct list survived. After the fix, full scalar lists are handed to the outer model whenever they fit the prompt budget.
- User experience improvements: Questions like listing SharePoint sites from a workbook column now have a better chance of producing the full list instead of a conservative fallback response.
