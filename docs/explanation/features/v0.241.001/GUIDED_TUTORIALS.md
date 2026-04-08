# Guided Tutorials

Feature version: **0.239.198**

## Overview

SimpleChat includes guided tutorials for the main chat experience and the Personal Workspace experience. These walkthroughs are designed to help users discover the most important controls in the live UI without needing separate training content or manual setup.

This document covers the tutorial features only:

- Chat Tutorial
- Personal Workspace Tutorial

## Purpose

The tutorial system exists to make the application easier to learn in-context. Instead of describing features in static text only, the tutorials highlight the actual controls on screen, explain what each one does, and move users through the main workflows step by step.

## Dependencies

### Chat Tutorial

- `application/single_app/templates/chats.html`
- `application/single_app/static/js/chat/chat-tutorial.js`
- `application/single_app/static/js/chat/chat-sidebar-conversations.js`
- `application/single_app/static/css/chats.css`

### Personal Workspace Tutorial

- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/workspace/workspace-tutorial.js`

### Regression Coverage

- `functional_tests/test_chat_tutorial_selector_coverage.py`
- `functional_tests/test_personal_workspace_tutorial_selector_coverage.py`
- `functional_tests/test_personal_workspace_tutorial_document_flow.py`
- `functional_tests/test_workspace_tutorial_reposition_fix.py`
- `functional_tests/test_workspace_tutorial_layer_order_fix.py`

## Technical Specifications

### Architecture Overview

Both tutorials use the same core approach:

- A launcher button visible on the page itself
- A guided, step-by-step overlay
- A highlight box that tracks the active UI target
- A floating tutorial card with explanatory text and next/previous navigation
- UI preparation logic that opens the required tab, section, menu, or modal only when needed
- Cleanup logic that restores temporary tutorial state when the walkthrough ends

The tutorials are implemented as client-side walkthrough modules so they can follow the actual rendered interface and react to live page state.

## Chat Tutorial

### Coverage

The chat tutorial walks users through the current chat interface, including:

- Main chat toolbar actions
- Workspace and scope controls
- Prompt and model selection controls
- Web search, voice input, and send actions
- Sidebar conversation navigation
- Conversation search and advanced search
- Sidebar selection mode and bulk actions
- Conversation export-related flows
- Message-level actions after sending a prompt
- Metadata, editing, retry, feedback, reuse, export, thoughts, and citations

### Behavior

The chat tutorial is designed around the live chat layout and includes safeguards for dynamic UI behavior:

- It waits for the conversation UI to finish loading before exposing the launcher
- It expands the sidebar automatically for sidebar-specific tutorial steps
- It uses tutorial-owned popup surfaces where the live dropdown/modal lifecycle would otherwise be brittle
- It can inject temporary sample messages when a conversation does not yet contain enough content for message-level walkthrough steps
- It keeps step highlighting aligned to the visible target after popup positioning and layout changes

### User Flow

Users start the walkthrough from the chat tutorial launcher on the chat page. The tutorial then moves through chat controls in a guided order and explains each control in place.

## Personal Workspace Tutorial

### Coverage

The Personal Workspace tutorial walks users through the main workspace experience, including:

- Document upload controls
- Search and filter controls
- List and grid view switching
- Expanded document details
- Document metadata editing flow
- Tag selection for a single document
- Row action menu coverage
- Share, chat, and selection-mode actions
- Bulk selection workflow and bulk tag assignment
- Workspace tag management
- Prompt creation and prompt search
- Agent creation and agent search
- Action creation and action search

### Behavior

The workspace tutorial includes page-state orchestration so the walkthrough stays aligned with the workspace interface:

- It switches tabs programmatically as needed
- It expands filter panels only for the relevant steps
- It supports tutorial-owned popup surfaces for menus and modal-style explanations
- It keeps the tutorial card and highlight aligned during collapse, tab, scroll, and layout changes
- It restores temporary tutorial UI state when the walkthrough ends

### User Flow

Users start the walkthrough from the workspace tutorial launcher on the Personal Workspace page. The tutorial then moves across documents, prompts, agents, and actions in sequence.

## Testing And Validation

The tutorial features are protected by focused regression coverage that verifies:

- Tutorial selectors still match the live templates
- Required walkthrough targets remain available
- Document-flow ordering remains correct in the workspace tutorial
- Repositioning safeguards remain present for layout changes
- Layer ordering remains correct for tutorial-owned popup surfaces

## Related Documentation

- `docs/explanation/fixes/CHAT_TUTORIAL_SELECTOR_COVERAGE_FIX.md`
- `docs/explanation/features/PERSONAL_WORKSPACE_TUTORIAL.md`
- `docs/explanation/fixes/PERSONAL_WORKSPACE_TUTORIAL_REPOSITION_FIX.md`
- `docs/explanation/fixes/PERSONAL_WORKSPACE_TUTORIAL_LAYER_ORDER_FIX.md`

## Known Scope

This document covers the chat tutorial and the Personal Workspace tutorial only. It does not describe separate walkthroughs for group workspace or public workspace pages.