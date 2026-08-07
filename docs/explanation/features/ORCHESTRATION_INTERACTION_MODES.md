# Orchestration Interaction Modes

Implemented in version: **0.250.127**

## Overview

Phase 12 adds governed orchestration interaction controls for chat turns. Administrators define which execution modes and review visibility levels are available, while users can choose a per-message override, save a personal default, or save a conversation default when allowed by policy.

Execution mode changes how optional orchestration work is handled. Review visibility changes how much plan/progress detail is expanded in the UI. Review visibility does not authorize tools, data access, writes, or deliverables.

## Dependencies

- Admin Settings application configuration in `application/single_app/functions_settings.py`
- Chat turn orchestration and capability discovery in `application/single_app/route_backend_chats.py`
- Conversation metadata and preference persistence in `application/single_app/route_backend_conversations.py`
- Chat composer controls in `application/single_app/templates/chats.html` and `application/single_app/static/js/chat/chat-orchestration-interaction.js`

## Technical Specifications

The normalized admin policy is stored as `orchestration_interaction_policy` and includes:

- enabled execution modes: `manual`, `balanced`, `auto`
- default execution mode
- enabled/default review visibility: `collapsed`, `expanded`
- per-conversation and per-message override toggles
- context-specific mode restrictions for personal, group, public, and external contexts
- plan drawer, advanced editing, audit, retention, and hard approval boundary metadata

Each submitted turn persists an `orchestration_interaction` snapshot beside existing orchestration metadata. The snapshot includes the resolved execution mode, review visibility, policy/preference version digests, context type, hard approval boundaries, and mode budget summary.

Pending capability decisions are revalidated against the current admin policy version before resume. If policy changed after a proposal was created, the stale pending decision fails closed.

## Usage Instructions

Administrators configure the policy in Admin Settings under **Orchestration Interaction**. Users choose the active mode from the chat composer dropdown beside the model selector.

Users may:

- choose a mode for only the next submitted message;
- toggle expanded plan details for only the next submitted message;
- save the current selection as their personal default;
- save the current selection as the conversation default when admin policy allows it.

## Testing and Validation

Coverage added in version **0.250.127**:

- `functional_tests/test_orchestration_interaction_policy.py`
- `ui_tests/test_chat_orchestration_interaction_modes.py`

The focused functional test validates policy normalization, per-message overrides, legacy `review_only` migration, context-specific fallback recording, and mode-specific capability inventory behavior.

The UI source-contract test validates chat composer controls, Admin Settings controls, safe DOM rendering patterns, request payload wiring, and expanded review visibility integration with processing thoughts.

## Known Limitations

Directive conflict persistence and memory revision enforcement remain bounded to the snapshot contract in this phase. Future governed memory phases can populate applied, overridden, and conflicting directive references without changing the per-turn interaction snapshot shape.