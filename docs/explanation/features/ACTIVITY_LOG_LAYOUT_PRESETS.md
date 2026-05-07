# Activity Log Layout Presets

Fixed/Implemented in version: **0.241.016**

## Overview and Purpose

The Control Center Activity Logs tab now includes layout presets so users can choose between balanced scanning, longer detail visibility, or denser column presentation without manually resizing the browser.

This feature improves readability for wide and narrow viewports while keeping the existing raw-log modal available for full detail inspection.

Dependencies: `application/single_app/templates/control_center.html`, `application/single_app/static/js/control-center.js`, browser `localStorage`, Bootstrap button styling, the existing Activity Logs raw-log modal.

## Technical Specifications

Architecture overview:

- The Activity Logs table in `application/single_app/templates/control_center.html` now exposes three presets: `Balanced`, `Details Focus`, and `Compact`.
- The table keeps the existing fixed-layout approach, but the column widths are now driven by CSS custom properties instead of hard-coded width blocks only.
- `application/single_app/static/js/control-center.js` applies the active preset by setting `data-layout-preset` on `#activityLogsTable` and updates the helper hint text.

Configuration options:

- Default preset: `balanced`
- Browser persistence key: `simplechat_activityLogsLayoutPreset`
- Preset values: `balanced`, `details-focus`, `compact`

File structure:

- `application/single_app/templates/control_center.html` — preset controls, helper text, preset-aware table styling.
- `application/single_app/static/js/control-center.js` — preset load/apply/save logic and hint updates.
- `functional_tests/test_control_center_activity_logs_layout_presets.py` — source-level regression coverage.
- `ui_tests/test_control_center_activity_logs_layout_presets.py` — browser workflow and persistence validation.

## Usage Instructions

How to use:

- Open Control Center and switch to the Activity Logs tab.
- Choose `Balanced` for the default five-column layout.
- Choose `Details Focus` to widen the Details column and show more multiline content.
- Choose `Compact` to prioritize quicker scanning across surrounding columns.
- Click any Activity Logs row to open the existing raw-log modal for the full JSON payload.

Integration points:

- Preset changes are applied immediately in the browser with no server round-trip.
- The selected preset is restored from `localStorage` after a page reload.
- The feature builds on top of the Activity Logs hardening work documented in `docs/explanation/fixes/v0.241.015/CONTROL_CENTER_ACTIVITY_LOGS_HARDENING_FIX.md`.

## Testing and Validation

Test coverage:

- `functional_tests/test_control_center_activity_logs_layout_presets.py`
- `ui_tests/test_control_center_activity_logs_layout_presets.py`

Validation highlights:

- Confirms the template exposes preset controls, helper text, and preset-aware CSS variables.
- Confirms the client stores the selected preset in `localStorage` and reapplies it on reload.
- Confirms the browser-visible preset changes update table layout characteristics without breaking Activity Logs loading.

Known limitations:

- Preset persistence is local to the current browser and device.
- This release does not add draggable column resizing.
- Mobile and narrow layouts still rely on the existing responsive wrapper and row-to-modal flow for full details.