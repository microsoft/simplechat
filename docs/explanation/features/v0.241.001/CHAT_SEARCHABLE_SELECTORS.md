# Chat Searchable Selectors

## Overview
Snapshot of the searchable chat selector update as implemented in version **0.239.123**.

This version adds in-menu search to the chat workspace scope and tag filters, and rebuilds the prompt, model, and agent toolbar selectors as searchable dropdowns while keeping the hidden native selects in place for existing chat integrations.

**Version Implemented:** 0.239.123
**Dependencies:** chats.html toolbar and workspace filter markup, chats.css dropdown styling, chat-documents.js, chat-prompts.js, chat-model-selector.js, chat-agents.js, chat-searchable-select.js

## Technical Specifications

### Architecture Overview
- Adds a shared `chat-searchable-select.js` helper for two selector patterns:
  - searchable single-select dropdowns for prompts, models, and agents
  - searchable filter overlays for the existing scope, tags, and documents dropdowns
- Keeps `#prompt-select`, `#model-select`, and `#agent-select` as the canonical state holders so existing chat modules can continue reading native select values and option metadata.
- Extends the existing search-documents card instead of introducing a second workspace filtering UI.

### Prompt Loading
- Prompt loading now walks paginated `/api/prompts`, `/api/group_prompts`, and `/api/public_prompts` responses using `page_size=100` until the full prompt set is loaded.
- This removes the prior first-page cap from the chat prompt picker without changing shared prompt API semantics used elsewhere in the application.
- Scope filtering still applies after prompt data is loaded, so the searchable list only shows prompt categories that match the current chat workspace scope.

### File Structure
- `application/single_app/templates/chats.html`
- `application/single_app/static/css/chats.css`
- `application/single_app/static/js/chat/chat-searchable-select.js`
- `application/single_app/static/js/chat/chat-documents.js`
- `application/single_app/static/js/chat/chat-prompts.js`
- `application/single_app/static/js/chat/chat-model-selector.js`
- `application/single_app/static/js/chat/chat-agents.js`
- `functional_tests/test_chat_searchable_selectors.py`
- `application/single_app/config.py`

## Usage Instructions

### Scope, Tags, and Documents
- Open **Workspaces** on the chat page.
- Use **Search workspaces...** to narrow the scope dropdown.
- Use **Search tags...** to narrow tag and classification choices.
- Use **Search documents...** to narrow the document list after scope and tag filtering have been applied.

### Prompts
- Open **Prompts** on the chat page.
- Search within the prompt dropdown to find a saved prompt by name.
- Select a single prompt to mirror the value back into the hidden prompt select used by message submission.

### Models and Agents
- Use the model dropdown search to quickly locate a deployment in long GPT model lists.
- When agent mode is enabled, the model control swaps to a searchable agent dropdown with the same search interaction.
- Agent labels continue to include group/global context when needed to distinguish duplicate display names.

## Testing and Validation

### Functional Coverage
- `functional_tests/test_chat_searchable_selectors.py`
- `functional_tests/test_workspace_scope_prompts_fix.py`

### Validation Focus
- Confirms the chat template contains searchable selector markup for scope, tags, prompts, models, and agents.
- Confirms the shared helper supports both dropdown filtering and searchable single-select behavior.
- Confirms prompt loading pages through all available prompt results instead of stopping at the default first page.
- Confirms the app version bump for the feature.