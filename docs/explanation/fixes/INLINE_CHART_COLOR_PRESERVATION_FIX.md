# Inline Chart Color Preservation Fix

Fixed/Implemented in version: **0.241.139**

## Issue Description

Users could ask for chart colors, such as fruit-colored pie slices, but rendered pie charts still used the default palette. Re-asking the model for different colors did not visibly change the chart.

## Root Cause Analysis

The model and chart tool could provide color values, but the browser chart normalizer replaced pie, doughnut, and polar-area slice colors with the default palette. The export PNG normalizer used the same fallback behavior. Common named colors were also rejected unless they were already CSS hex, RGB, or HSL strings.

## Technical Details

### Files Modified

- `application/single_app/static/js/chat/chat-inline-charts.js`
- `application/single_app/functions_chart_export.py`
- `application/single_app/semantic_kernel_plugins/chart_plugin.py`
- `application/single_app/functions_chart_operations.py`
- `application/single_app/config.py`
- `functional_tests/test_chart_action_inline_rendering.py`
- `functional_tests/test_conversation_export_inline_chart_images.py`

### Code Changes Summary

- Preserved explicit `backgroundColor` and `borderColor` arrays for pie, doughnut, and polar-area charts in the browser renderer.
- Preserved the same slice colors in server-side PNG export rendering.
- Added safe named color normalization for common color words and semantic fruit labels such as `red`, `orange`, `green`, `apple`, `oranges`, and `pears`.
- Updated chart guidance and chart tool metadata so models know to use per-slice color arrays when users request specific colors.
- Bumped `config.py` version to `0.241.139`.

### Testing Approach

- Added chart plugin coverage for semantic pie slice colors.
- Added export helper coverage for requested pie slice colors.

## Impact Analysis

Charts now better honor user color requests and exports should match the live rendered chart colors. Existing charts without explicit colors continue to use the default palette.

## Validation

- `node --check application/single_app/static/js/chat/chat-inline-charts.js`
- `python -m py_compile application/single_app/functions_chart_export.py application/single_app/semantic_kernel_plugins/chart_plugin.py application/single_app/functions_chart_operations.py functional_tests/test_chart_action_inline_rendering.py functional_tests/test_conversation_export_inline_chart_images.py`
- `python functional_tests/test_chart_action_inline_rendering.py`
- `python functional_tests/test_conversation_export_inline_chart_images.py`
- `git -c core.whitespace=blank-at-eol,blank-at-eof,space-before-tab,cr-at-eol diff --check`