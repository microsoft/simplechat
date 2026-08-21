# Tabular Completed Artifact Card Fix

Fixed in version: **0.250.151**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Completed generated-file cards continued to show background handoff prose, storage and source notes, a long post-run completeness and common-values summary, and an inline preview. The resulting card looked like an execution report even though the user's primary task was simply to open, download, or retain the completed file.

## Root Cause

The same artifact renderer handled running and completed states. Supporting metadata and previews were appended directly for every completed tabular artifact, while the original assistant handoff remained visible after polling replaced the progress card.

## Technical Details

### Files Modified

- `application/single_app/functions_tabular_generated_exports.py`
- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_tabular_background_generated_exports.py`
- `ui_tests/test_chat_generated_tabular_output_card.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Completed Card

Completed structured tabular artifacts now display:

- generated artifact title;
- filename;
- total row count;
- `Download` action;
- `View` action;
- `Add to Workspace` action.

The renderer omits storage/source notes, post-run diagnostics, and inline preview rows from the finished card. Durable completion metadata also suppresses the stale assistant sentence that says processing is still continuing.

### Bounded View Modal

The durable runner copies a validated preview from output checkpoints into completed artifact metadata. The preview is bounded to:

- at most 10 rows;
- at most 24,000 serialized characters;
- at most 240 characters per displayed cell.

The browser renders these rows in a responsive modal and reports how many preview rows are shown out of the complete artifact row count. It does not download the complete large artifact merely to display the preview.

All modal elements are created with DOM APIs, and dynamic content is assigned through `textContent`.

## Validation

Coverage verifies:

- preview rows preserve source order and remain within row and character bounds;
- completed artifact metadata propagates the preview and handoff-suppression flag;
- completed cards omit background notes, source details, summaries, and inline rows;
- the `View` modal displays bounded rows and total row count;
- `Download` and `Add to Workspace` continue to work;
- untrusted filename and cell content remain inert text.

Validated with:

```bash
node --check application/single_app/static/js/chat/chat-messages.js
python -m pytest functional_tests/test_tabular_background_generated_exports.py -q
python -m pytest functional_tests/test_tabular_row_orchestration_scale.py -q
python -m pytest ui_tests/test_chat_generated_tabular_output_card.py -q
```

The completed-card and modal workflow was also verified through an authenticated browser session using the local unmerged JavaScript module.

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.150** to **0.250.151** for this completed artifact-card simplification.