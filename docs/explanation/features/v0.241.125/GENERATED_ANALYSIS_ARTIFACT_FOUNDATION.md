# Generated Analysis Artifact Foundation

Overview

Implemented in version: **0.241.125**

This feature introduces a shared chat-scoped artifact foundation for large generated analysis outputs. Instead of forcing full structured review, comparison, or tabular results inline in the assistant message, the backend can now persist the full result as a hidden chat artifact, render a short inline summary plus preview card, and provide a secure download path from the chat UI.

Dependencies

- Chat artifact upload helper in `application/single_app/functions_simplechat_operations.py`
- Chat document resolution in `application/single_app/functions_search_service.py`
- Chat assistant persistence in `application/single_app/route_backend_chats.py`
- Document-action execution in `application/single_app/functions_workflow_runner.py`
- Artifact rendering in `application/single_app/static/js/chat/chat-messages.js`

Technical Specifications

Architecture overview

- Hidden chat artifacts continue to use blob-backed `role='file'` messages in the personal chat storage container.
- Assistant messages now persist a generic `generated_analysis_artifacts` metadata array, with `generated_tabular_outputs` retained as a backward-compatible alias for existing UI and tests.
- Generated artifact file messages now carry generic metadata, including capability, output format, and storage scope.
- Chat document resolution now distinguishes generated artifacts from regular chat uploads through `source_subtype='generated_chat_artifact'` while preserving the existing `chat_upload` source type for compatibility.

Implemented phases

- **Phase 1**: Generic artifact foundation
  - Added `upload_generated_analysis_artifact_for_current_user(...)`
  - Added backend metadata normalization for generic generated artifacts
  - Added generic artifact UI hydration and preview rendering
  - Added configurable size cap support through `max_generated_chat_artifact_size_mb`

- **Phase 2**: Document analysis artifacts
  - Document analysis now creates a chat artifact from the final analysis output when the result is explicitly requested as an artifact, is already structured JSON, or is large enough to justify a downloadable file.
  - The assistant reply is shortened to a narrative summary when an analysis artifact is created.

- **Phase 3**: Comparison artifacts
  - Document comparison now creates a chat artifact from the final comparison output under the same artifact-trigger rules.
  - Comparison artifacts reuse the same generic metadata and UI card surface.

Current boundary

- **Phase 4** promotion and approval flows are not yet implemented.
- Artifact promotion into personal or group workspaces still needs approval-aware routing.
- Multi-user collaboration source-conversation routing for generated artifacts is still pending.

Usage Instructions

User workflow

- Ask for a large tabular export, analysis, or document comparison.
- When the response is structured or large enough, the assistant stores the full result as a hidden chat artifact.
- The assistant renders a short summary plus a preview card with a download button.
- The full artifact downloads through `/api/chat_artifacts/download` after conversation ownership checks.

Artifact metadata

- `capability`: `tabular`, `analyze`, or `comparison`
- `artifact_message_id`: hidden chat file message id
- `conversation_id`: owning chat id
- `storage_scope`: currently `chat`
- `output_format`: `json` or `md` in the current implementation
- `summary`, `preview_rows`, `preview_items`, or `preview_lines` for UI rendering

Testing and Validation

Functional coverage

- `functional_tests/test_tabular_generated_output_exports.py`
- `functional_tests/test_document_analysis_generated_artifacts.py`
- `functional_tests/test_document_comparison_generated_artifacts.py`

Validation performed

- Python compile checks for the touched backend files
- JavaScript parse check for `chat-messages.js`
- Focused functional regressions for tabular, analysis, and comparison artifact plumbing

Known limitations

- Promotion/approval flows are still pending
- Artifact citations are not yet surfaced as first-class downloadable citation chips
- Public data sources are supported as inputs to single-user chats, but generated artifacts still persist against the owning chat conversation rather than a separate public workspace artifact model