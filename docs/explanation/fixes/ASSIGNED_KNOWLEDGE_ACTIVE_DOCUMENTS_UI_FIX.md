# Assigned Knowledge Active Documents UI Fix

Fixed in version: **0.241.117**

Updated in version: **0.241.118**

Updated in version: **0.241.119**

## Issue Description

Agent creators could select a public workspace source and see many resolved documents, then move to the Documents section and accidentally reduce the final document set to only one document. The page did not clearly explain that sources create the document pool, tags and specific documents are optional limits, and the resolved document list is the final set used by the agent.

A follow-up issue showed that the agent workflow modal was not wide enough for the Assigned Knowledge two-column pickers, and that the public workspace source picker only listed workspaces visible in the user's normal public workspace directory instead of all searchable public workspaces.

Another follow-up issue showed that inventory questions such as "what documents do you have access to" were answered from the top retrieved citations instead of the full active Assigned Knowledge document set. Personal agents assigned to public workspace knowledge could also become public-scope conversations after retrieval, causing the personal agent to disappear from the locked conversation's agent picker.

## Root Cause Analysis

The Knowledge step used internal wording such as Sources, Documents, and Resolved Documents without explaining the workflow. The preview also treated selected tags as any-tag matches, while backend search requires documents to match all selected tags before they qualify through tag limits.

## Technical Details

### Files Modified

- `application/single_app/templates/_agent_modal.html`
- `application/single_app/static/js/agent_modal_stepper.js`
- `application/single_app/functions_assigned_knowledge.py`
- `application/single_app/functions_search.py`
- `application/single_app/functions_conversation_metadata.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `docs/explanation/features/v0.241.068/ASSIGNED_KNOWLEDGE.md`
- `functional_tests/test_assigned_knowledge_active_documents_ui.py`
- `ui_tests/test_agent_modal_assigned_knowledge_step.py`

### Code Changes Summary

- Added a question-mark help button to the Assigned Knowledge step with concise workflow guidance.
- Renamed the authoring model around Source Workspaces, Tag Limits, Specific Documents, and Active Documents.
- Added a live active-document summary near the top of the controls.
- Updated active-document counts and empty states so users can see when they are using all source documents versus a narrowed set.
- Aligned the browser preview with backend tag behavior by requiring every selected tag limit to match before a document is included by tags.
- Widened the agent workflow modal from the large Bootstrap modal to an extra-large bounded dialog.
- Updated the Assigned Knowledge public source catalog to list all public workspaces, not only the user's directory-visible public workspaces.
- Added an Assigned Knowledge search path override so assigned public workspaces are searched even when they are hidden from the user's normal public workspace selector.
- Added a backend active-document inventory resolver for Assigned Knowledge.
- Added deterministic chat augmentation for Assigned Knowledge inventory questions so answers can state and list the full active document set.
- Kept personal Assigned Knowledge agents anchored to personal conversation metadata while tracking assigned public workspaces as additional locked context.
- Updated `application/single_app/config.py` to version `0.241.119`.

### Testing Approach

- Added a functional regression test for the modal wording and JavaScript preview contract.
- Updated the Assigned Knowledge UI test to validate the new active-document summary and all-tag matching behavior.
- Ran JavaScript syntax checks and targeted Python validation for changed tests.

## Impact Analysis

This change is UI-focused and does not alter stored Assigned Knowledge payloads or backend runtime filters. It reduces accidental over-narrowing by making the final active document set more prominent and by explaining when the Documents section should be used.

## Validation

The updated UI now makes the final document set visible as Active Documents, clarifies that source workspaces alone use all documents from those sources, and describes tag/document selections as optional limits. The browser preview now matches the backend all-tag filter semantics, avoiding misleading active-document counts before the agent is saved.