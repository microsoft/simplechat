# Conversation References and Queued AI Handoffs

**Version: 0.261.381** (tracked in `application/single_app/config.py`)

**Implemented in version: 0.261.381** (`application/single_app/config.py`, Refs #1835)

## Overview

Conversation References and Queued AI Handoffs let a user keep each chat thread focused on a single task while reusing prior work or delegating a follow-up question to another conversation.

SimpleChat separates two distinct operations:

- **Reference a conversation (`~` or Reference Conversation)**: pulls bounded, relevant excerpts from the latest visible messages of one of the user's own private conversations into the current turn, orchestration plan, or personal workflow run. The source conversation is never modified and no work starts inside it.
- **Send To Conversation**: delivers an explicit instruction and optional conversation references to a destination private conversation and starts a new AI turn there. When the destination conversation is already generating a response, the handoff waits in a durable FIFO queue and runs after the active turn finishes instead of interrupting or replacing the stream.

This capability is available in the React V2 interface with shared backend enforcement across ordinary chat, orchestration, plan-editor Ask AI, and personal workflows.

## Dependencies

- React V2 interface (`/v2/chat` and `/v2/workspace/workflows`).
- Authenticated user session with personal conversations in Azure Cosmos DB.
- Optional `enable_chat_orchestration` for orchestration capabilities (`conversation_search`, `conversation_read`, and `conversation_send`) and plan-editor Ask AI.
- Optional `allow_user_workflows` for personal workflow conversation source bindings and workflow Ask AI.

## Technical Specifications

### Architecture

1. **Private-owner eligibility and evidence projection (`functions_conversation_references.py`, `functions_conversation_reference_runtime.py`)**
   - Every source and destination conversation is checked with `is_private_owned_conversation` before any title, snippet, or message read occurs, and checked again after evidence projection.
   - Only private personal conversations owned by the caller are eligible. Shared/collaborative conversations, hidden orchestration backing records, group/public conversations, deleted records, and conversations with non-owner participant tags are refused.
   - Message projection applies `checked_history_messages(..., for_model=True)` and excludes soft-deleted messages, full-message masks, canonical `masked_ranges`, inactive retry threads, superseded orchestration attempts, generated chat artifacts, and blocked/retracted safety messages before lexical matching, snippet generation, or excerpt packing.
   - Evidence is wrapped in an untrusted-source policy header (`_POLICY`) and bounded to at most 5 referenced conversations per request, 10 search results per page, 200 recent messages scanned per source conversation, and 4,000 UTF-8 bytes of serialized evidence.
2. **Typed V2 composer and Ask AI grammar (`application/v2_ui/src/lib/`)**
   - Typing `~` at a word boundary opens the conversation picker without interfering with `#` document/tag context, `@` mentions, `/` saved prompts, `~~` strikethrough, code blocks, or paths such as `~/notes`.
   - Selecting a conversation inserts an inline `~[Title]` token and attaches a typed `{kind: 'conversation', id, message_ids?}` entry in `conversation_references`. Display labels never establish identity on their own, and conversation references never implicitly enable workspace `hybrid_search` or populate `selected_document_ids`.
   - Portable reference links can be copied from the conversation menu and pasted into another V2 composer, where the server resolves and authorizes the conversation ID before creating a chip.
3. **Durable handoff queue and destination admission (`functions_conversation_handoffs.py`, `route_backend_conversation_handoffs.py`, `route_backend_chats.py`)**
   - Handoffs are stored in a dedicated Cosmos container partitioned by `destination_conversation_id` alongside a per-destination admission lease record.
   - Normal chat streams, orchestrated runs, and queued handoffs share the destination admission gate so a handoff never calls `ActiveConversationStreamRegistry.start_session` over an active turn.
   - Each handoff reserves deterministic request and destination message identifiers before execution, preventing duplicate destination turns across retries, browser refreshes, or worker restarts.
4. **Orchestration and personal workflows (`functions_orchestration_registry.py`, `functions_workflow_definitions.py`, `functions_workflow_bindings.py`, `functions_workflow_assist.py`)**
   - Orchestration adds `conversation_search` and `conversation_read` for user-requested source lookup, plus `conversation_send` with an explicit manual approval floor when a destination has not been pre-approved.
   - Personal workflows support additive `conversation_reference_inputs` and per-task `conversation_reference_ids` without altering existing document `reference_inputs`. Each run resolves fresh visible excerpts under the workflow owner's identity and records source revisions and provenance.

### API Endpoints

| Endpoint | Method | Purpose |
| --- | --- | --- |
| `/api/conversation-references` | GET | Paginated title and optional message-content search across the caller's eligible private conversations. |
| `/api/conversation-references/resolve` | POST | Authorize up to five private conversation references and return bounded excerpts, source revisions, and partial-coverage indicators. |
| `/api/conversation-handoffs` | GET, POST | List recent outgoing/incoming handoffs for a conversation or enqueue a new AI handoff to an eligible private destination conversation. |
| `/api/conversation-handoffs/<handoff_id>` | GET | Inspect current queue/execution state for a handoff. |
| `/api/conversation-handoffs/<handoff_id>/cancel` | POST | Cancel a queued or running handoff without deleting destination history. |

### File Structure

| File | Purpose |
| --- | --- |
| `application/single_app/functions_conversation_references.py` | Bootstrap-free reference normalization, private-owner checks, masking-first projection, search, and bounded excerpt packing. |
| `application/single_app/functions_conversation_reference_runtime.py` | Runtime wiring to Cosmos containers and checked-history message projection. |
| `application/single_app/route_backend_conversations.py` | `/api/conversation-references` and `/api/conversation-references/resolve` routes. |
| `application/single_app/functions_conversation_handoffs.py` | Durable handoff records, per-destination leases, FIFO queue admission, loop bounds, and AI turn dispatch. |
| `application/single_app/route_backend_conversation_handoffs.py` | Authenticated Blueprint routes for creating, listing, inspecting, and cancelling handoffs. |
| `application/v2_ui/src/components/chat/ComposerEditor.tsx` | Shared `~` picker, inline token highlighting, portable paste resolution, and conversation chips across chat and Ask AI. |
| `application/v2_ui/src/components/chat/ConversationRail.tsx` | **Reference Conversation** and **Send To Conversation** menu actions. |

## Usage Instructions

1. **Pull evidence into the current chat with `~`**:
   - Type `~` in the V2 chat composer, plan editor Ask AI, or workflow Ask AI, or open a conversation's menu in the rail and choose **Reference Conversation → Use in current conversation**.
   - Ask your question and send. SimpleChat resolves bounded excerpts from the latest visible messages of the referenced conversation and records the source conversation in reply citations.
2. **Copy a portable reference**:
   - Choose **Reference Conversation → Copy reference** from any private conversation's menu, then paste into another composer to attach that conversation as a verified pill.
3. **Delegate follow-up AI work with Send To Conversation**:
   - Choose **Send To Conversation** from a conversation's menu, pick the destination private conversation, review the resolved model/agent and bounded source preview, and confirm.
   - If the destination conversation is idle, AI work starts immediately; if it is busy, the handoff is queued and starts automatically when the active turn finishes.

## Testing and Validation

- `functional_tests/test_conversation_references.py`: private-owner eligibility, Cosmos SDK `CosmosDict` normalization, masking/deletion/inactive-thread filtering before search and snippet generation, bounded token budgets, revision changes, and HTTP route headers.
- `functional_tests/test_conversation_handoffs.py`: deterministic handoff IDs, busy destination FIFO queueing, lease contention, cancellation, crash/uncertain-effect handling, and loop/hop limits.
- `functional_tests/test_orchestration_conversation_references.py`, `functional_tests/test_workflow_conversation_references.py`, and `functional_tests/test_orchestration_conversation_sends.py`: planner/schema/adapter contracts, Ask AI reference operations, personal workflow source bindings, and approval-floor enforcement.
- `functional_tests/test_v2_conversation_reference_tokens.mjs`, `ui_tests/test_v2_conversation_references.py`, and `ui_tests/test_v2_conversation_handoffs.py`: `~` token parsing, keyboard picker navigation, portable reference paste, and end-to-end V2 browser flows.

### Known Limitations

- The initial release supports only the authenticated user's own private conversations. Shared, group, and public conversations cannot be referenced or targeted by handoffs.
- Retrieval uses bounded lexical matching over the latest 200 visible messages per referenced conversation rather than a global conversation embedding index; when a conversation exceeds scan or token limits, the response marks coverage as `partial`.
- Masking or deleting a source message prevents future reference resolutions from returning that text, but does not rewrite prose that was already generated in earlier turns.
