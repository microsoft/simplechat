# TABULAR MULTISHEET TOOL START GUIDANCE FIX

Fixed/Implemented in version: **0.240.034**

Related config.py update: `VERSION = "0.240.034"`

## Header Information

- Issue description: Multi-sheet workbook questions could preload schemas successfully but still return a narrative answer without making any tabular tool calls.
- Root cause analysis: The analysis path relied too much on preloaded schema plus route-side hints, while the model had no generic discovery loop to inspect workbook structure and then continue into analytical tools when the right worksheet was still unclear.
- Version implemented: 0.240.034

## Technical Details

- Files modified: `application/single_app/route_backend_chats.py`, `application/single_app/config.py`, `functional_tests/test_tabular_multisheet_tool_start_guidance.py`
- Code changes summary: Replaced content-targeted guidance with a generic multi-sheet discovery iteration model. Analysis mode now allows `describe_tabular_file` as an exploration step for multi-sheet workbooks, carries compact workbook-discovery summaries into retries, forces tool use on the first multi-sheet analytical pass, and still rejects discovery-only runs as incomplete until analytical tool calls succeed.
- Testing approach: Added and updated functional regressions to verify generic entity-lookup routing, compact discovery summaries, multi-sheet discovery iteration guidance, and the preserved rule that discovery alone is not a completed analytical answer.
- Impact analysis: Multi-sheet workbook prompts now have a more general tool-iteration path that lets the model inspect workbook structure and continue into analytical tools without hardcoded content or column targeting.

## Validation

- Test results: Targeted regressions verify the new multi-sheet discovery iteration guidance, workbook-discovery retry summaries, and the version bump.
- Before/after comparison: Before the fix, some multi-sheet workbook prompts stalled with schema-only narration; after the fix, the route explicitly supports discovery-first iteration while still requiring analytical tool results before completion.
- User experience improvements: Multi-sheet workbook analysis is less brittle because it relies on a generic workbook exploration loop instead of route-side content targeting.