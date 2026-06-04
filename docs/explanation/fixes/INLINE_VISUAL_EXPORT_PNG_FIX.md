# Inline Visual Export PNG Fix

Fixed/Implemented in version: **0.241.143**

## Issue Description

Per-message exports did not consistently carry inline visuals into the exported artifact. PowerPoint exports could omit charts entirely for structured slide-deck responses, Word exports did not convert approved inline image proposal blocks into embedded image media, and email drafts only prepared chart PNG downloads while leaving image proposal JSON-like text in the body.

## Root Cause Analysis

Charts already had a backend PNG renderer, but structured PowerPoint exports disabled appendix slides and did not extract rendered chart images from each authored slide section. Approved `simpleimage` proposal results were associated to their source assistant message in the browser, but the export backend did not perform the same association or replace `simpleimage` blocks with exportable image HTML. The PowerPoint parser also treated authoring labels such as `Title:` and `Bullet Points:` as literal slide bullets.

## Technical Details

Files modified:

- `application/single_app/route_backend_conversation_export.py`
- `application/single_app/static/js/chat/chat-message-export.js`
- `application/single_app/config.py`
- `functional_tests/test_per_message_powerpoint_export.py`
- `functional_tests/test_per_message_export.py`
- `functional_tests/test_conversation_export_inline_chart_images.py`

Code changes summary:

- Added export-side generated image proposal lookup and PNG data URI rendering for approved `simpleimage` blocks.
- Reused one rendered-content path for Word, PowerPoint, and email exports so charts and generated images are handled consistently.
- Added structured PowerPoint slide image extraction and inline placement so charts/images stay with the slide section where they appear.
- Cleaned structured slide labels so `Title:`, `Bullet Points:`, and visual block metadata do not appear as exported slide bullets.
- Broadened email PNG attachment payloads from chart-only to chart-or-image visuals.

## Validation

Test coverage added or updated:

- `functional_tests/test_per_message_powerpoint_export.py`
- `functional_tests/test_per_message_export.py`
- `functional_tests/test_conversation_export_inline_chart_images.py`

Expected behavior:

- PowerPoint exports embed chart and generated-image PNG media on the appropriate structured slide.
- Word exports embed approved generated image proposal PNGs as document media.
- Email draft export downloads PNG payloads for both charts and generated images and references them cleanly in the draft body.
- Exported PowerPoint slides no longer show label scaffolding such as `Title:` or `Bullet Points:` as slide bullets.

Config version reference:

- `application/single_app/config.py` updated to `0.241.143`.
