# Tabular Background Status Details Fix

Fixed in version: **0.250.150**

Related issue: **microsoft/simplechat#1031**

## Issue Description

Running tabular export cards displayed filename and source metadata, background-processing guidance, checkpoint counts, remaining batch and chunk counts, throughput, model concurrency, timestamps, and optional previews at the same time. The information was useful for troubleshooting but too dense for the normal progress-monitoring workflow.

## Root Cause

The card renderer appended every status and metadata element directly to the visible card. Although previews for some completed analysis artifacts already used a native disclosure, running background export metadata did not have an equivalent collapsed boundary.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-messages.js`
- `application/single_app/config.py`
- `functional_tests/test_tabular_background_generated_exports.py`
- `ui_tests/test_chat_background_generated_export_status.py`
- `docs/explanation/features/TABULAR_BACKGROUND_GENERATED_EXPORTS.md`

### Code Changes

Background export cards now show these elements without expansion:

- generated export title;
- current status badge;
- progress bar;
- available Continue or Cancel actions;
- a `View details` disclosure.

The closed disclosure contains:

- generated filename and total row count;
- storage and source information;
- safe status details and checkpoint summaries;
- remaining work, throughput, concurrency, retry, and ETA information;
- last update and heartbeat timestamps;
- optional generated previews.

The renderer continues to create DOM nodes and populate dynamic values through `textContent`. No untrusted content is inserted through an HTML execution sink.

## Validation

The browser regression verifies that status and progress remain visible, operational details are hidden initially, and every detail becomes visible after activating `View details`. Cancellation and terminal failure states retain their existing controls and status badges.

Validated with:

```bash
node --check application/single_app/static/js/chat/chat-messages.js
python -m pytest functional_tests/test_tabular_background_generated_exports.py -q
python -m pytest ui_tests/test_chat_background_generated_export_status.py -q
```

The authenticated Playwright scenarios require `SIMPLECHAT_UI_BASE_URL` and `SIMPLECHAT_UI_STORAGE_STATE`; they skip when those values are not configured.

## Related Version Update

`application/single_app/config.py` was incremented from **0.250.149** to **0.250.150** for this background status-card simplification.