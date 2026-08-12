# Tabular LLM Generation Acceleration Phase 2 Handoff

Implemented in version: **0.250.138**

## Overview

Phase 2 makes accepted background tabular runs produce one concise, truthful foreground acknowledgment. When SimpleChat queues an exhaustive export, analysis, or combined run, the assistant response now describes the complete accepted work and labels visible rows as a sample or preview instead of saying only retrieved preview rows can be generated.

## Purpose

The goal is to keep the static assistant prose aligned with the durable run that the server accepted. Progress, retry, and completion details remain in the background status card, while the assistant text acknowledges the requested row count and deliverable.

## Dependencies

- Background tabular generated-output runner in `application/single_app/functions_tabular_generated_exports.py`
- Chat handoff and message finalization in `application/single_app/route_backend_chats.py`
- Background status card rendering in `application/single_app/static/js/chat/chat-messages.js`
- Functional and UI coverage in `functional_tests/test_tabular_row_orchestration_scale.py` and `ui_tests/test_chat_background_generated_export_status.py`

## Technical Specifications

### Server-Composed Handoff

`route_backend_chats.py` now builds the user-facing handoff from public run metadata for active background tabular runs. The shared helper handles structured export, hierarchical analysis, and combined export plus analysis modes.

The final assistant content is replaced with the server-composed handoff before non-streaming messages are persisted and before streaming final completion metadata is emitted. The model-facing system message is constrained to the same text and no longer includes run identifiers, storage locations, batch counts, or checkpoint details.

### Public Metadata

`build_background_tabular_generated_output_metadata(...)` now includes safe handoff metadata:

- `handoff_mode`
- `requested_row_count`
- `preview_available`
- `preview_row_count`
- `foreground_response_policy_version`

These fields do not expose settings, source storage paths, raw rows, or protected backend details.

## Usage Instructions

Users continue asking for exhaustive row-level CSV, JSON, XML, or analysis output. If the work is queued, the immediate response acknowledges the complete row count and tells the user that processing continues in the background. Any visible preview rows are described as a sample, and the status card remains the source of mutable progress details.

## Testing and Validation

- Functional contract: `python functional_tests/test_tabular_row_orchestration_scale.py`
- UI contract: `ui_tests/test_chat_background_generated_export_status.py`
- Python syntax: `python -m py_compile application/single_app/route_backend_chats.py application/single_app/functions_tabular_generated_exports.py functional_tests/test_tabular_row_orchestration_scale.py ui_tests/test_chat_background_generated_export_status.py`

## Known Limitations

- Streaming clients may briefly receive model tokens before the final server-authored message replaces the temporary streaming content at completion.
- This phase changes foreground communication only. It does not alter run scheduling, checkpointing, retry behavior, or artifact finalization.

## Related Version Updates

- `application/single_app/config.py` was updated to version **0.250.138** for Phase 2 truthful background handoff behavior.