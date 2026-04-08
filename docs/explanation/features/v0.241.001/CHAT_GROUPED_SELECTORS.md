# CHAT_GROUPED_SELECTORS

Implemented in version: **0.239.195**

## Overview

The chat composer now renders prompts, models, agents, and documents with the same grouped selector pattern used by the workspace scope picker. The update standardizes section headers, search behavior, ordering, and scope-aware option states so the selector stack feels consistent and is ready for future tagging work across more chat resources.

## Dependencies

- `application/single_app/route_frontend_chats.py`
- `application/single_app/functions_prompts.py`
- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-searchable-select.js`
- `application/single_app/static/js/chat/chat-prompts.js`
- `application/single_app/static/js/chat/chat-agents.js`
- `application/single_app/static/js/chat/chat-model-selector.js`
- `application/single_app/static/js/chat/chat-documents.js`

## Technical Specifications

### Architecture Overview

- The shared searchable single-select renderer now understands grouped `<optgroup>` sections and preserves section headers when matching child items remain visible during search.
- Prompt data for chat is preloaded on the chats route, similar to the existing chat agent and model catalogs, so grouped prompt sections can be built without relying on the active group or active public workspace API endpoints.
- Agent and model selectors now keep full grouped catalogs visible while disabling options that fall outside the current effective scope.
- Document dropdown rendering now uses real section headers instead of embedding scope labels directly in each item name.

### Ordering Rules

- Agents and models are ordered: Global, Personal, then each group in alphabetical order.
- Prompts and documents are ordered: Personal, groups in alphabetical order, then public workspaces in alphabetical order.
- Items inside each section are ordered alphabetically by display name.

### Scope Behavior

- Prompt selection remains a normal grouped single-select and does not act as a scope lock.
- Agent and model selections still narrow the active workspace scope for new conversations only.
- After a scope is narrowed, out-of-scope agent and model options remain visible but disabled, and the dropdown exposes an inline action to restore the full available workspace set.
- Existing conversations continue to honor their persisted personal, group, or public workspace scope.

## Usage Instructions

### User Workflow

- Open prompts, models, agents, or documents in chat and browse resources by section header instead of parsing inline scope prefixes.
- Type into selector search boxes to filter items while retaining matching section headers.
- Pick a scoped agent or model in a new conversation to narrow the workspace, then use the inline `Use all available workspaces` action inside the dropdown to restore the broader scope when needed.

### Integration Points

- Chat bootstrap data now includes `chatPromptOptions`, `chatAgentOptions`, and `chatModelOptions` on the chats page.
- Prompt grouping is now chat-specific and no longer depends on the currently active group or public workspace prompt endpoints.

## Testing And Validation

### Coverage

- `functional_tests/test_chat_searchable_selectors.py`
- `ui_tests/test_chat_grouped_selectors.py`

### Performance Considerations

- Prompt, agent, and model option catalogs are preloaded once with the chats page so selector rendering and filtering stay client-side after initial page load.
- Grouped rendering is centralized in the shared selector helper to reduce repeated DOM logic across selectors.

### Known Limitations

- Agent and model scope clearing restores the full available workspace set but preserves the current selected item unless the selection becomes invalid for the rebuilt option list.
- UI regression coverage still depends on authenticated Playwright environment variables being configured.