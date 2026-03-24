# Tabular Workspace Trigger and Thoughts Fix

## Issue Description
Users could ask multiple questions against the same selected tabular workspace file and see inconsistent behavior. A simple aggregation question could trigger the tabular SK mini-agent, while a later question against the same selected file could fall back to schema-only reasoning. In addition, the Processing Thoughts UI did not show any explicit `tabular_analysis` step even when tabular functions were used.

**Version implemented:** 0.239.032

Fixed/Implemented in version: **0.239.032**

Related `config.py` update: `VERSION` was bumped to `0.239.032`.

## Root Cause Analysis
1. **Workspace trigger depended too heavily on search results**
   - The tabular trigger only inspected `combined_documents` returned from hybrid search.
   - If the selected tabular file produced sparse retrieval output or schema-only chunks, the trigger could miss the explicit workspace selection.
2. **Mini-agent responses were not hardened against no-tool replies**
   - For more complex analytical prompts, the mini-agent could return narrative text without actually calling the `TabularProcessingPlugin`.
   - That produced no tool citations and left the final model with schema-only context.
3. **Processing thoughts missed tabular work entirely**
   - The chat flow recorded search, web, and generation steps, but never wrote a `tabular_analysis` thought for workspace or chat tabular runs.

## Technical Details
### Files Modified
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`

### Code Changes Summary
- Added shared helpers to:
  - detect supported tabular filenames consistently,
  - resolve explicitly selected workspace tabular documents, and
  - merge search-result files with selected-document files before triggering analysis.
- Moved workspace tabular trigger logic so it can run from explicit workspace selection, not just retrieved chunks.
- Hardened `run_tabular_sk_analysis()` with a retry path that requires actual tabular tool usage before accepting the result.
- Added `tabular_analysis` thoughts for:
  - workspace tabular analysis start/completion in non-streaming mode,
  - workspace tabular analysis start/completion in streaming mode,
  - chat-uploaded tabular analysis start/completion in non-streaming mode,
  - chat-uploaded tabular analysis start/completion in streaming mode.

### Testing Approach
- Added `functional_tests/test_workspace_tabular_trigger_and_thoughts.py` to verify:
  - explicit workspace-selected tabular files participate in trigger detection,
  - tabular analysis thoughts are emitted in both chat paths,
  - the mini-agent prompt now requires tool execution and retries when it answers without tools.

## Impact Analysis
- Explicitly selected CSV/Excel workspace files now have a more reliable analysis trigger path.
- Complex tabular prompts are less likely to degrade into schema-only answers.
- Users can now see tabular analysis activity directly in Processing Thoughts, improving transparency and debugging.

## Validation
### Before
- Some workspace-selected tabular questions skipped the SK mini-agent even though the same file was still selected.
- Thoughts could show search and generation steps without any indication that tabular analysis ran.

### After
- Workspace tabular analysis considers both retrieved tabular documents and explicitly selected tabular files.
- Mini-agent retries are stricter when the first response skips tool execution.
- Processing Thoughts now includes clear `tabular_analysis` steps whenever tabular analysis is attempted.

## Related Validation Assets
- Functional test: `functional_tests/test_workspace_tabular_trigger_and_thoughts.py`
- Related feature documentation: `docs/explanation/features/v0.239.003/PROCESSING_THOUGHTS.md`
- Related earlier fix: `docs/explanation/fixes/v0.239.008/CHAT_TABULAR_SK_TRIGGER_FIX.md`
