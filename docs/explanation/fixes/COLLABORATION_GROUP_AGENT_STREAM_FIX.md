# Collaboration Group Agent Stream Fix

Fixed/Implemented in version: **0.241.068**

## Issue Description

Group collaborative conversations could finish an agent run and show partial content in the UI, but the final shared stream completion step still failed and surfaced the yellow `Stream interrupted` banner.

Related config update: `application/single_app/config.py` now sets `VERSION = "0.241.068"`.

## Root Cause Analysis

- The collaborative stream bridge emitted its final mirrored SSE payload with raw `json.dumps(...)` instead of normalizing nested values first.
- Agent responses can carry richer citation payloads than plain model responses, including nested values that need JSON-safe normalization before the collaborative route re-emits them.
- Hidden collaboration source conversations for group multi-user chats were also being rewritten back to `group-single-user`, which caused the inner stream path to drift away from the intended group-scoped source conversation behavior.

## Technical Details

Files modified:

- `application/single_app/route_backend_collaboration.py`
- `application/single_app/functions_collaboration.py`
- `application/single_app/functions_conversation_metadata.py`
- `functional_tests/test_collaboration_shared_ai_workflow.py`
- `functional_tests/test_collaboration_group_agent_stream_fix.py`
- `application/single_app/config.py`

Code changes summary:

- Sanitized the final mirrored collaborative SSE payload with `make_json_serializable(...)` before emitting it to the browser.
- Synchronized hidden collaboration source conversations so group collaborative chats keep the source chat typed as `group`.
- Preserved `group` chat typing for `collaboration_source` conversations inside conversation metadata collection instead of forcing them back to `group-single-user`.
- Added regression coverage for both the hidden-source metadata path and the agent-citation serialization path.

Testing approach:

- Re-ran the existing collaboration stream bridge regression tests.
- Added a focused functional test that simulates agent citations containing nested JSON-unsafe values and verifies the collaborative SSE completion payload remains valid.

## Validation

Before:

- Group collaborative agent runs could produce content and citations but still fail during the final shared-stream completion step.
- Existing hidden source conversations could drift back to `group-single-user` metadata during later metadata collection.

After:

- Group collaborative agent responses complete through the shared stream bridge without tripping the final collaborative stream error banner.
- Hidden collaboration source conversations remain group-scoped, which keeps downstream streaming metadata aligned with the collaborative group workflow.

Related functional tests:

- `functional_tests/test_collaboration_shared_ai_workflow.py`
- `functional_tests/test_collaboration_stream_image_completion_fix.py`
- `functional_tests/test_collaboration_group_agent_stream_fix.py`