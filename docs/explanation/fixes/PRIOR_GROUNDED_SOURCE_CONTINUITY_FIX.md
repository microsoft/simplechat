# Prior Grounded Source Continuity Fix

Fixed/Implemented in version: **0.250.157**

Related work: Fixes #1204

## Issue Description

Follow-up mixed-source tasks did not automatically combine previously grounded sources with the current turn's selected or retrieved sources. For example, after summarizing an XML template, a user could ask to add a selected PDF's content into "that XML file," but the current turn would only use the PDF context and not rehydrate the prior XML template as an active source.

## Root Cause Analysis

SimpleChat already persisted compact prior grounded source references in `last_grounded_document_refs`, and it had a history-grounded fallback path for turns with workspace search disabled. However, that fallback only ran when the current turn was not already performing retrieval or explicit mixed-source selection. A turn with a current PDF/source selection therefore bypassed the fallback and never merged in prior cited sources.

## Technical Details

Files modified:

- `application/single_app/route_backend_chats.py`
- `application/single_app/config.py`
- `functional_tests/test_chat_history_grounded_follow_up_fix.py`
- `docs/explanation/release_notes.md`

Code changes:

- Added detection for explicit follow-up references to prior sources, including phrases such as "that XML file," "same template," and "previous spreadsheet."
- Added a shared merge helper that combines current selected document IDs with revalidated prior grounded document IDs while preserving group and public workspace scope context.
- Wired the merge helper into both standard and streaming chat paths before mixed-source manifest/search resolution.
- Stored a compact `prior_grounded_source_merge` metadata marker on the current user message when prior sources are merged.
- Prevented the no-search history grounding prompt from being inserted when prior sources have been merged into the current retrieval context.
- Updated `config.py` from `0.250.156` to `0.250.157`.

## Testing Approach

Updated `functional_tests/test_chat_history_grounded_follow_up_fix.py` to verify:

- Prior-source reference phrases are detected for XML templates, same-source prompts, and previous spreadsheets.
- Generic current-source prompts do not trigger prior-source reuse.
- Current document IDs and prior grounded document IDs merge without duplicates.
- Mixed personal/group scopes collapse to `all` with authorized group context preserved.
- Standard and streaming chat paths both include prior-source merge wiring.

## Impact Analysis

Users can chain document workflows more naturally when a follow-up explicitly references a prior grounded source and also supplies or selects a current source. The prior source is still treated only as a reauthorization hint; source content and storage locators are not trusted from conversation history.

## Validation

- `python functional_tests\test_chat_history_grounded_follow_up_fix.py`

## Before and After

Before, a follow-up such as "add this PDF content into that XML file" could ground only on the selected PDF. After this fix, the route detects the reference to the prior XML source, revalidates it, and includes it alongside the current PDF before mixed-source execution.