# PUBLIC_WORKSPACE_TAG_COLOR_XSS_FIX.md

# Public Workspace Tag Color XSS Fix

Fixed/Implemented in version: **0.241.022**

## Issue Description

Public workspace tag colors could be stored as arbitrary strings and later interpolated into browser `style` attributes and inline handler arguments in the tag-folder grid, tag badges, and tag-management UI.

## Root Cause Analysis

- `application/single_app/functions_documents.py` returned stored tag colors without a defensive fallback for already-persisted invalid values.
- Personal, group, and public tag create and update routes accepted caller-provided colors without shared validation and normalization.
- `application/single_app/static/js/public/public_workspace.js` rendered tag-owned UI fragments with HTML string interpolation, including dynamic `style=` values and inline `onclick` handlers.

## Technical Details

### Files Modified

- `application/single_app/functions_documents.py`
- `application/single_app/route_backend_documents.py`
- `application/single_app/route_backend_group_documents.py`
- `application/single_app/route_backend_public_documents.py`
- `application/single_app/static/js/public/public_workspace.js`
- `functional_tests/test_public_workspace_tag_color_xss_fix.py`
- `ui_tests/test_public_workspace_tag_color_rendering.py`

### Code Changes Summary

- Added shared tag-color normalization, validation, and safe fallback helpers in `functions_documents.py`.
- Applied color validation to personal, group, and public tag create and update routes so new writes persist normalized hex values only.
- Added read-time fallback in shared tag-definition reads so previously stored invalid colors resolve to deterministic safe colors instead of reaching the browser unchanged.
- Rebuilt the affected public workspace tag UI surfaces with DOM-created nodes, `textContent`, and event listeners so tag color values no longer flow through inline HTML or handler interpolation.

### Testing Approach

- `functional_tests/test_public_workspace_tag_color_xss_fix.py` verifies the shared helper layer, all three tag-route surfaces, the public workspace DOM-safe renderer snippets, and the presence of the versioned fix artifacts.
- `ui_tests/test_public_workspace_tag_color_rendering.py` exercises the public workspace page with a malicious tag-color payload and asserts the grid, management list, selection list, and selected-tag chip rendering stay inert.

## Impact Analysis

- Newly created and updated tags keep working with normalized color values.
- Previously stored invalid tag colors now fall back to safe deterministic colors instead of breaking rendering or reaching executable sinks.
- Public workspace tag folders, badges, and management controls retain their existing behavior while removing the stored XSS path.

## Validation

### Before

- Stored tag colors could flow from persistence into HTML `style` attributes and inline handler arguments in the public workspace UI.
- Existing malformed colors already in storage remained live input to the browser renderers.

### After

- Tag colors are validated and normalized before write persistence.
- Shared tag reads repair previously stored invalid colors with safe fallback values.
- Public workspace tag rendering uses DOM APIs and event listeners instead of string-built `style=` and `onclick=` sinks.

## Version Alignment

- `application/single_app/config.py` is aligned to `VERSION = "0.241.022"` for this fix set.