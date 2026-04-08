# Personal Workspace Tutorial

Fixed/Implemented in version: **0.239.191**

## Overview

The personal workspace page now includes a guided tutorial that walks users through the main workspace controls for documents, prompts, agents, and actions.

## Dependencies

- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/workspace/workspace-tutorial.js`
- Bootstrap tabs and collapse behavior already used on the workspace page

## Technical Specifications

### Architecture overview

The tutorial is implemented as a dedicated client-side module that:

- Launches from the same fixed `?` tutorial button pattern used on the chat page, including the same ready-state fade-in container and hover-expanding label treatment
- Switches tabs programmatically to show prompts, agents, and actions in sequence
- Expands filter panels only for the relevant steps
- Uses an overlay highlight and floating card to explain each control
- Restores the original active tab and temporary UI state when the tutorial ends

### Coverage

The tutorial currently covers:

- Document uploads
- Document search and filters
- List versus grid view
- Expanded document details
- Document metadata editing walkthrough
- Single-file tag selection inside metadata editing
- Row actions for chat, sharing, and selection mode
- Bulk selection actions including tag assignment
- Workspace tag management popup walkthrough
- Tutorial-only example tag previews so the UI can explain tags without using real user data
- Workspace tag management
- Prompt creation and prompt search
- Agent templates, agent creation, and agent search
- Action creation and action search

### File structure

- `application/single_app/templates/workspace.html`
- `application/single_app/static/js/workspace/workspace-tutorial.js`
- `functional_tests/test_personal_workspace_tutorial_selector_coverage.py`

## Usage Instructions

Press the `Workspace Tutorial` button at the top of Personal Workspace to start the walkthrough.

The tutorial advances step by step across the workspace tabs and opens the required tab or filter section automatically before highlighting the relevant control.

Within the documents section, it now walks through opening a file row, reviewing its details, previewing the metadata editor, immediately following that with the single-file tag picker, then later surfacing the bulk tag assignment popup after the selection bar so it follows the actual selection workflow more naturally. Action-menu item steps now use an on-top item highlight so Share, Chat, and Select read clearly above the cloned menu.

## Testing and Validation

- Added selector coverage for the workspace tutorial launcher, target selectors, and state-management guards
- Added document-flow coverage for expanded rows, metadata previews, action walkthroughs, selection mode, workspace tag management, and tutorial-owned tag-selection surfaces
- Verified the tutorial wiring against the current personal workspace template structure

## Known Limitations

- The tutorial highlights currently focus on the personal workspace page only
- It does not yet provide separate walkthroughs for group or public workspace pages