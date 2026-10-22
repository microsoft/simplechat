# Mixed-Mode Conversation History Ordering and Superseded Saved-Memory Fix

**Version: 0.261.378**

Fixed/Implemented in version: **0.261.378**

Related `application/single_app/config.py` update: **0.261.377 -> 0.261.378**.

## Issue Description and Root Cause

In multi-turn conversations that alternate between manual chat turns and orchestrated turns while updating saved profile memories (`Instruction Memory` and `Fact Memory`) mid-conversation, two general product behaviors interacted to cause stale-memory references on later consistency-check turns:

1. **Non-Chronological Ordering of Mixed Manual and Orchestration History (`functions_chat.py`)**:
   - Manual chat turns persist `metadata.thread_info.thread_id`, whereas orchestration turns (`user_orchestration_*` and `assistant_orchestration_*`) do not set `metadata.thread_info.thread_id` unless regenerated.
   - `sort_messages_by_thread(messages)` in `application/single_app/functions_chat.py` partitioned messages into `legacy_msgs` (without `thread_id`) and `threaded_msgs` (with `thread_id`) and returned `legacy_msgs + ordered_threaded`.
   - In any mixed-mode conversation, `build_conversation_history_segments` (`route_backend_chats.py`), conversation summaries (`route_backend_conversations.py`), and exports (`route_backend_conversation_export.py`) placed all orchestration turns before all manual turns. When saved memory was updated mid-conversation, earlier manual turns (containing pre-update memory values) were placed *after* later orchestration turns (containing post-update memory values), making the conversation history appear to oscillate between the old and new reviewer identities.

2. **Superseded Memory Contrasted During Consistency Audits (`functions_fact_memory_context.py`, `functions_orchestration_composition.py`, `functions_orchestration_planner.py`, `route_backend_chats.py`)**:
   - Saved-memory prompts instructed the model to use current saved memories instead of repeating obsolete names or roles as current, but did not explain that differences between earlier assistant replies' prefixes/names/roles and current saved memory reflect an intentional profile update rather than an inconsistency in the conversation notes. When asked to check consistency across earlier notes, the model could still quote or flag the superseded identity from earlier assistant replies.

## Technical Details

| File | Summary of Changes |
| --- | --- |
| `application/single_app/functions_chat.py` | Updates `sort_messages_by_thread` to interleave unthreaded messages (`legacy_msgs`) chronologically with threaded turns based on each thread's earliest timestamp (honoring `root_timestamp` and descendant bounds), while preserving retry chains and top-level/metadata `thread_id` lookup. |
| `application/single_app/functions_fact_memory_context.py` | Clarifies in `build_instruction_memory_payload` and `build_fact_memory_recall_payload` that any difference between earlier assistant replies and current saved memory is an intentional profile update rather than a note inconsistency, and forbids repeating, mentioning, quoting, contrasting, or flagging superseded values. |
| `application/single_app/functions_orchestration_composition.py` | Updates `CONVERSATION_POLICY` so compose treats current saved memory as the consistent baseline and never repeats, mentions, quotes, contrasts, or flags superseded earlier assistant values. |
| `application/single_app/functions_orchestration_planner.py` | Aligns planner and request-resolution memory instructions so superseded earlier assistant prefixes, names, call signs, or roles are never carried forward or contrasted. |
| `application/single_app/config.py` | Increments `VERSION` to `0.261.378`. |
| `functional_tests/test_mixed_mode_history_and_memory_supersede_fix.py` | Validates mixed manual + orchestration chronological turn ordering, retry chain preservation, and superseded-memory prompt contracts. |

## Validation

- `python functional_tests\test_mixed_mode_history_and_memory_supersede_fix.py`
- `python functional_tests\test_message_threading_system.py`
- `python functional_tests\test_message_ordering_with_retry.py`
- `python functional_tests\test_fact_memory_read_only_context.py`
- `python functional_tests\test_fact_memory_streaming_context_fix.py`
- `python functional_tests\test_fact_memory_history_context_leak_fix.py`
- `python -m pytest -q -p test_support.cosmos_network_guard functional_tests\test_orchestration_memory_context.py functional_tests\test_orchestration_request_memory_resolution.py`
