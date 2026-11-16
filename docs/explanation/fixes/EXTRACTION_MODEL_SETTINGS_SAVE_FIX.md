# Extraction and Vision Model Settings Save Fix

Fixed in version: **0.261.393** (`application/single_app/config.py`)

## Issue Description

When an administrator enabled **Metadata Extraction** and **Multi-Modal Vision Analysis** in V2 Admin Settings and selected a model from AI Connections (such as `gpt-5.6-terra · Migrated Azure OpenAI Endpoint`), clicking **Save changes** failed with HTTP `400 Bad Request` on `PATCH /api/v2/admin/settings` and displayed:

- `metadata_extraction_model cannot be changed through this endpoint.`
- `multimodal_vision_model cannot be changed through this endpoint.`

## Root Cause Analysis

1. **Component field rejection in PATCH normalization**: In `application/single_app/admin_settings_fields.py`, both `metadata_extraction_model` and `multimodal_vision_model` are declared with `type: "component"` (`component: "model-picker"`). In the V2 UI (`AdminSettingsPage.tsx` and `ModelPicker.tsx`), changing a `model-picker` stages the chosen value into the standard `PATCH /api/v2/admin/settings` payload. However, `_normalize_field_value()` rejects all `component` fields with `"<key> cannot be changed through this endpoint."` unless they are registered in `_COMPONENT_VALUE_VALIDATORS`. Neither key was registered.
2. **Missing AI Connection selection references in V2 saves**: Document metadata extraction (`_resolve_metadata_extraction_client` in `functions_documents.py`) prefers `metadata_extraction_model_selection` (`endpoint_id`, `model_id`, `provider`) when `enable_multi_model_endpoints` is enabled, and V2 `ModelPicker` only staged the scalar deployment string. In addition, `_build_model_catalog` in `route_backend_v2.py` deduplicated solely by deployment name, collapsing distinct AI Connections that published the same deployment name.

## Technical Details

### Files Modified

- `application/single_app/admin_settings_fields.py`
  - Added `selection_key` metadata (`metadata_extraction_model_selection` and `multimodal_vision_model_selection`) to the two `model-picker` field definitions and claimed `metadata_extraction_model_selection_json` in `LEGACY_FIELD_NAMES`.
  - Registered `metadata_extraction_model`, `metadata_extraction_model_selection`, `multimodal_vision_model`, and `multimodal_vision_model_selection` in `_COMPONENT_VALUE_VALIDATORS`.
  - Added `_check_extraction_model_selections()` to validate the selected model and connection against enabled `model_endpoints` (or classic GPT/APIM deployments when multi-endpoint mode is off), verify chat and vision capabilities, resolve the request model and provider server-side, reject ambiguous scalar-only names when multiple connections share a deployment name, and clear companion selection dicts when cleared or in classic mode.
- `application/single_app/route_backend_v2.py`
  - Updated `_build_model_catalog()` to skip disabled endpoints, include `model_id` and `provider`, deduplicate by `(endpoint_id, model_id or deployment)`, and fall back to classic APIM or `gpt_model.selected` entries when `enable_multi_model_endpoints` is disabled.
  - Updated `_persist_global_model_endpoints()` to re-resolve `multimodal_vision_model_selection` alongside `metadata_extraction_model_selection` when connections are modified or deleted.
- `application/single_app/functions_settings.py`
  - Added default `multimodal_vision_model_selection` and `resolve_vision_model_selection()`.
- `application/single_app/functions_documents.py`
  - Updated `resolve_vision_model_endpoint()` to resolve explicit `multimodal_vision_model_selection` references first (failing closed if the selected connection or model is missing or disabled) while preserving name-based resolution for legacy settings.
  - Updated `_resolve_metadata_extraction_client()` to also resolve name-only `metadata_extraction_model` values against enabled AI Connections when `metadata_extraction_model_selection` is empty.
- `application/single_app/route_backend_settings.py`
  - Updated `_test_multimodal_vision_connection()` to honor an explicit `multi_endpoint` selection from the test payload before falling back to `resolve_vision_model_endpoint()`.
- `application/v2_ui/src/lib/adminFields.ts`, `application/v2_ui/src/components/admin/ModelPicker.tsx`, `application/v2_ui/src/pages/AdminSettingsPage.tsx`
  - Extended `AdminModelCatalogEntry` and `ModelPicker` to preserve `endpoint_id`, `model_id`, and `provider`, disambiguate duplicate deployment names across connections, stage companion `selection_key` objects into the settings draft without inflating the unsaved-change count, and forward `multi_endpoint` selection details in `buildConnectionTestPayload()`.
- `application/single_app/config.py`
  - Incremented `VERSION` from `0.261.392` to `0.261.393`.

## Validation

- Functional tests:
  - `python functional_tests\test_v2_admin_extraction_model_settings.py` (passed)
  - `python functional_tests\test_v2_admin_knowledge_extraction.py` (passed)
  - `python functional_tests\test_v2_admin_settings_normalization.py` (passed)
  - `python -m unittest functional_tests\test_ai_connection_defaults_api.py` (passed)
  - `python functional_tests\test_v2_admin_model_endpoints_api.py` (passed)
  - `python functional_tests\test_image_description_indexing_without_ocr_text.py --offline-probe` (passed)
- Browser UI tests:
  - `python -m pytest ui_tests\test_v2_admin_extraction_model_settings.py -q` (3 passed)
- Frontend build and typecheck:
  - `npm --prefix .\application\v2_ui run typecheck` (passed)
  - `npm --prefix .\application\v2_ui run build` (passed)
