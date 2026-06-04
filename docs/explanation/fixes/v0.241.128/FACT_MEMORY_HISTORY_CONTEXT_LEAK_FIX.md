# Fact Memory History Context Leak Fix (v0.241.128)

Fixed/Implemented in version: **0.241.128**

## Header Information

### Issue Description

Assistant replies could expose internal prior citation/tool scaffolding in the visible chat bubble, including `Prior tool results` content from saved instruction memory or fact memory citations.

### Root Cause Analysis

`application/single_app/route_backend_chats.py` intentionally appends compact prior citation context to assistant turns before sending conversation history to the model. This helps follow-up questions reuse tabular and source evidence, but fact-memory citations are already injected as fresh current-turn system context and are also available through the citation UI. Replaying those citations inside prior assistant history gave the model answer-shaped text that could be quoted back to the user.

### Version Implemented

`0.241.128`

## Technical Details

### Files Modified

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_fact_memory_history_context_leak_fix.py`
- `docs/explanation/fixes/v0.241.128/FACT_MEMORY_HISTORY_CONTEXT_LEAK_FIX.md`

### Code Changes Summary

- Added a history-replay exclusion for fact-memory citation records, including `Instruction Memory`, `Fact Memory Recall`, and citations with the `fact_memory` plugin name.
- Kept tabular citation summaries eligible for follow-up grounding so users can still ask short follow-up questions about prior workbook/tool results.
- Added an explicit internal-grounding instruction to the remaining supporting citation context block so the model is told not to quote, summarize, reveal, or mention the hidden context labels or raw tool payloads.
- Bumped the application version to `0.241.128`.

### Testing Approach

- Added `functional_tests/test_fact_memory_history_context_leak_fix.py`.
- Verified fact-memory-only citations do not produce a `Prior tool results` block in assistant history text.
- Verified mixed fact-memory and tabular citations still preserve tabular evidence for follow-up grounding while excluding the saved memory payloads.
- Verified documentation and `config.py` version alignment for the fix.

## Validation

### Before

- Prior assistant turns with instruction/fact memory citations could be serialized back into model history under `Prior tool results`.
- The model could echo saved memory citation JSON in the visible response even though those details belonged in citations/thoughts, not the assistant answer.

### After

- Saved instruction/fact memory citation payloads remain available through citation metadata but are not replayed as prior assistant-history text.
- Tabular citation evidence remains available for follow-up grounding.
- The remaining hidden citation context includes a stronger instruction to avoid revealing internal context labels or tool payloads.
