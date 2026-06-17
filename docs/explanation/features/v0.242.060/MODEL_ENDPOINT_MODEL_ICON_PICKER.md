# Model Endpoint Model Icon Picker

Implemented in version: **0.242.060**
Fixed/Implemented in version: **0.242.060**
Related Config Update: `application/single_app/config.py` -> `VERSION = "0.242.060"`

## Overview
Model endpoint available-model rows now support the same icon workflow used by agent configuration: admins, personal workspace users, and group workspace owners can search local Bootstrap Icons or upload a PNG/JPEG image for each model.

## Purpose
Model choices in chat can already render model icon metadata. This feature makes that metadata practical to maintain from the shared Model Endpoint modal instead of requiring manual JSON edits or a raw icon class text field.

## Dependencies
- Shared Model Endpoint modal
- Local Bootstrap Icons CSS asset
- Shared agent icon helper in `application/single_app/static/js/agents_common.js`
- Model endpoint normalization in `application/single_app/functions_settings.py`

## Technical Specifications
- `agents_common.js` now exposes generalized icon controls that accept scoped selectors while preserving the existing agent modal API.
- `admin_model_endpoints.js` and `workspace_model_endpoints.js` render a full icon editor for every available model row.
- Model icon payloads are saved as `{ kind: "bootstrap", value: "bi-*" }` or `{ kind: "image", value: "data:image/..." }`.
- Existing backend normalization continues to validate model icon payloads through `normalize_icon_payload()`.

## Usage Instructions
1. Open Admin Settings, Workspace, or Group Workspace model endpoint management.
2. Add or edit a model endpoint.
3. In Available Models, use the Icon controls on a model row.
4. Choose Bootstrap Icon to search local Bootstrap Icons, or Image to upload a PNG/JPEG.
5. Save the endpoint, then save settings where required.

## Testing and Validation
- Functional coverage: `functional_tests/test_model_endpoint_model_icon_picker.py`.
- UI coverage: `ui_tests/test_model_endpoint_request_uses_endpoint_id.py` validates the modal controls are visible and usable.
- JavaScript parse checks cover the shared helper plus admin and workspace endpoint scripts.

## Known Limitations
- Uploaded model icons are intentionally small data images. Large images are resized client-side and rejected if they remain over the icon payload limit.
