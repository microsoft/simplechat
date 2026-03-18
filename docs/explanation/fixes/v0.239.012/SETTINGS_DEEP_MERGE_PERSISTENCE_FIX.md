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

 - Updated `deep_merge_dicts()` in `functions_settings.py` to return a boolean `changed` flag indicating whether any values were added or updated during the merge.
 - Updated `get_settings()` (and related callers) to use the returned `settings_changed` flag to decide whether to upsert the merged settings back to Cosmos DB.
 - Kept the merge semantics the same while fixing the persistence condition so that only genuinely changed settings trigger an upsert.
 - Preserved existing upsert behavior, logging flow, and return shapes for callers.

### Testing Approach

- Added functional regression test: `functional_tests/test_settings_deep_merge_persistence_fix.py`.
- Test validates marker-based wiring for:
  - the `changed` flag returned from `deep_merge_dicts()`,
  - the `settings_changed` gate that controls whether the Cosmos upsert path is invoked,
  - Cosmos upsert path availability and logging when defaults introduce new keys,
  - version alignment in `config.py`.

### Impact Analysis

- Restores intended persistence behavior for newly introduced default settings keys.
- Reduces risk of drift between in-memory merged settings and persisted Cosmos settings.
- Maintains compatibility with existing callers and return shapes.

## Validation

### Before

- Missing default keys could be merged in memory but not persisted, because the change check compared a mutated object to itself.

### After

- Missing default keys trigger the upsert path and persistence logging because `deep_merge_dicts()` reports that changes occurred and `settings_changed` evaluates `True`, causing the merged settings to be written back to Cosmos DB.

### Test Result

- Verified by running `py -3 functional_tests/test_settings_deep_merge_persistence_fix.py`.
