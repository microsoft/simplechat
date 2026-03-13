# SETTINGS DEEP MERGE PERSISTENCE FIX

## Overview

- **Issue**: App settings default-key merge changes were not being persisted back to Cosmos DB.
- **Root Cause**: `deep_merge_dicts(default_settings, settings_item)` mutates `settings_item` in place, and `get_settings()` compared `merged` against the same mutated object, so `merged != settings_item` evaluated false.
- **Fixed/Implemented in version: `0.239.012`**
- **Related version update**: `application/single_app/config.py` updated to `VERSION = "0.239.012"`.

## Technical Details

### Files Modified

- `application/single_app/functions_settings.py`
- `application/single_app/config.py`
- `functional_tests/test_settings_deep_merge_persistence_fix.py`

### Code Changes Summary

- Added `import copy` in `functions_settings.py`.
- Captured a pre-merge snapshot with `original_settings_item = copy.deepcopy(settings_item)`.
- Updated change detection to compare `merged` against `original_settings_item`.
- Preserved existing merge behavior and upsert/logging flow.

### Testing Approach

- Added functional regression test: `functional_tests/test_settings_deep_merge_persistence_fix.py`.
- Test validates marker-based wiring for:
  - deep-copy snapshot creation,
  - comparison against pre-merge state,
  - Cosmos upsert path availability,
  - version alignment in `config.py`.

### Impact Analysis

- Restores intended persistence behavior for newly introduced default settings keys.
- Reduces risk of drift between in-memory merged settings and persisted Cosmos settings.
- Maintains compatibility with existing callers and return shapes.

## Validation

### Before

- Missing default keys could be merged in memory but not persisted, because the change check compared a mutated object to itself.

### After

- Missing default keys trigger the upsert path and persistence logging because merge output is compared against a deep-copied pre-merge snapshot.

### Test Result

- Verified by running `py -3 functional_tests/test_settings_deep_merge_persistence_fix.py`.
