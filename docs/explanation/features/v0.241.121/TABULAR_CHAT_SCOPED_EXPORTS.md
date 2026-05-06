# Tabular Chat-Scoped Exports

Overview

Version implemented: 0.241.121
Dependencies: application/single_app/route_backend_chats.py, application/single_app/functions_simplechat_operations.py, application/single_app/route_enhanced_citations.py, application/single_app/route_backend_conversations.py, application/single_app/functions_retention_policy.py, application/single_app/static/js/chat/chat-messages.js

This update moves generated tabular JSON and CSV exports from the personal workspace pipeline into the active chat conversation. Large structured outputs now save as conversation-scoped blob-backed artifacts, which keeps the assistant reply concise while still giving the user a direct preview and download path.

Technical Specifications

Architecture overview:
- Generated tabular exports now use a reusable chat artifact helper in application/single_app/functions_simplechat_operations.py.
- The helper stores the generated file in the personal-chat blob container and persists a hidden blob-backed file message in the conversation.
- Assistant replies persist lightweight `generated_tabular_outputs` metadata that points at the hidden chat artifact instead of a workspace document record.
- The download experience now uses an authorized chat artifact route in application/single_app/route_enhanced_citations.py.
- Personal conversation deletion and retention cleanup now remove blob-backed chat files when archiving is not enabled.

Configuration and file structure:
- Version source remains application/single_app/config.py.
- The chat artifact metadata is rendered by application/single_app/static/js/chat/chat-messages.js.
- Prompt-history reconstruction in application/single_app/route_backend_chats.py skips hidden generated artifacts so they do not pollute later model context.

Usage Instructions

How it works:
- When a tabular request explicitly asks for downloadable JSON or CSV output, the tabular pipeline generates the file and stores it in the current chat.
- The assistant message shows a generated export card with a preview, source file details, and a download button.
- The user can download the artifact directly from the chat without creating a personal workspace document.

Integration points:
- The new helper is reusable for tabular analysis, review, comparison, or other future flows that need conversation-scoped generated files.
- The older workspace download path remains available for previously saved workspace-scoped exports.

Testing and Validation

Test coverage:
- functional_tests/test_tabular_generated_output_exports.py validates the backend helper wiring, chat download route, and chat UI hooks.
- ui_tests/test_chat_generated_tabular_output_card.py validates card rendering, safe text handling, and chat artifact downloads.

Performance and lifecycle considerations:
- Chat-scoped exports avoid pushing large structured payloads through the final assistant response.
- Blob-backed chat files are now cleaned up when personal conversations are deleted without archiving.
- When conversation archiving is enabled, blob-backed chat files are retained so archived messages keep their blob references.