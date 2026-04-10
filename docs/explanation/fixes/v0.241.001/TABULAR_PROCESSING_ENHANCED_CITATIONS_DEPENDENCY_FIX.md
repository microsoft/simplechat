# Tabular Processing Enhanced Citations Dependency Fix

Fixed/Implemented in version: **0.240.002**

## Overview

Tabular processing was previously exposed as a separate Action toggle even though the runtime also required Enhanced Citations to be enabled. That created a fragile configuration where admins could disable a workflow that is required for reliable CSV and workbook analysis.

## Issue Description

The admin Actions UI treated tabular processing as independently turn-onable and turn-offable. In practice, the feature only works when Enhanced Citations is enabled because tabular files rely on the enhanced citations storage path for full-data analysis.

## Root Cause Analysis

The codebase stored and checked `enable_tabular_processing_plugin` as if it were a first-class setting even though the real dependency was `enable_enhanced_citations`. Runtime checks, admin APIs, and UI state all carried that extra toggle forward, which allowed configuration drift between the stored flag and the actual runtime requirement.

## Technical Details

### Files modified

- `application/single_app/functions_settings.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/route_backend_chats.py`
- `application/single_app/semantic_kernel_loader.py`
- `application/single_app/route_frontend_admin_settings.py`
- `application/single_app/templates/admin_settings.html`
- `application/single_app/static/js/admin/admin_settings.js`
- `application/single_app/config.py`
- `functional_tests/test_tabular_processing_enhanced_citations_dependency.py`

### Code changes summary

- Added a shared helper that derives tabular processing availability directly from Enhanced Citations.
- Normalized persisted settings so `enable_tabular_processing_plugin` mirrors the derived state for compatibility.
- Updated chat and semantic-kernel runtime checks to use the derived helper instead of the legacy dual-flag condition.
- Removed the independent admin Actions checkbox and replaced it with dependency messaging.
- Kept the admin plugin settings API backward-compatible for legacy callers that still post `enable_tabular_processing_plugin`.

### Testing approach

- Added `functional_tests/test_tabular_processing_enhanced_citations_dependency.py`.
- Verified derived settings logic, runtime helper usage, admin API compatibility markers, and admin UI removal of the independent toggle.

## Validation

### Before

- Admins could see and manipulate a separate Tabular Processing Action toggle.
- Runtime behavior depended on both the legacy tabular flag and Enhanced Citations, which allowed drift.

### After

- Tabular processing is automatically on when Enhanced Citations is on.
- The feature is no longer independently turnoffable in the admin Actions UI.
- Runtime gating now follows the actual dependency consistently.

### User experience improvements

- Reduced configuration confusion in Admin Settings.
- Prevented disabling a critical part of tabular analysis while still surfacing the Enhanced Citations requirement.