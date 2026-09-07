# Tabular Execution Settings Sanitization Fix (0.250.168)

Fixed in version: **0.250.168**

Related version update: `application/single_app/config.py` reports `0.250.168`.

## Issue Description

Normal user-facing settings responses could include admin-only tabular execution controls. These values revealed internal execution behavior and could expose the configured deployment name used for chunk processing.

Related issue: [#1199](https://github.com/microsoft/simplechat/issues/1199).

## Root Cause

`sanitize_settings_for_user()` removes tabular backend settings through `TABULAR_GENERATION_BACKEND_SETTING_KEYS`. Newly added hierarchical-analysis, chunk-model, and model-validation retry settings were not added to that denylist, so they passed through the sanitizer.

## Technical Details

The backend-only denylist now removes:

- `enable_tabular_hierarchical_analysis`
- `tabular_hierarchical_analysis_reduce_fan_in`
- `tabular_generated_output_chunk_model_mode`
- `tabular_generated_output_chunk_model_deployment`
- `tabular_generated_output_model_validation_auto_retries`

The durable-run confirmation toggle and row and batch thresholds remain available because the chat frontend uses them to confirm very large tabular runs.

Files modified:

- `application/single_app/functions_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_tabular_execution_settings_sanitization.py`

## Impact

Non-admin frontend routes that use `sanitize_settings_for_user()` no longer receive the five internal execution controls. Admin settings behavior is unchanged because admin routes continue to use the full settings object.

## Validation

Focused functional coverage executes the shared sanitizer and verifies that all five backend settings are removed, all three chat-required confirmation settings remain available, and ordinary public settings are preserved.

Before the fix, the five execution controls passed through normal frontend settings responses. After the fix, only the chat-required confirmation fields remain visible.
