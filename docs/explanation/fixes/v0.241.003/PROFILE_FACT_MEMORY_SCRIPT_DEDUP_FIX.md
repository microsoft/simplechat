# Profile Fact Memory Script Dedup Fix

Fixed in version: **0.241.003**

Related config.py update: `VERSION = "0.241.004"`

## Overview

The profile page no longer ships duplicate fact-memory inline helpers or a duplicate Chart.js include that caused browser parsing to fail before the fact-memory UI could initialize.

## Issue Description

Opening the profile page could trigger `Uncaught SyntaxError: Identifier 'factMemoryEntries' has already been declared` because the template contained two copies of the same fact-memory declarations and helper functions.

## Root Cause

`application/single_app/templates/profile.html` contained a duplicated inline-script segment for the fact-memory editor, including repeated `let` declarations and helper functions, plus a second Chart.js script tag.

## Technical Details

### Files Modified

- `application/single_app/templates/profile.html`
- `functional_tests/test_profile_fact_memory_script_dedup.py`
- `ui_tests/test_profile_fact_memory_editor.py`
- `application/single_app/config.py`

### Code Changes Summary

- Removed the duplicate Chart.js script include from the profile template.
- Removed the second copy of the fact-memory/tutoral helper declarations and functions from the profile inline script.
- Added a functional regression test that counts key profile-script markers and fails if any duplicate block returns.
- Hardened the profile fact-memory UI test to fail on browser page errors and duplicate-declaration console errors during load.

## Testing Approach

- Added `functional_tests/test_profile_fact_memory_script_dedup.py` to validate that the profile template contains only one copy of the relevant fact-memory markers.
- Updated `ui_tests/test_profile_fact_memory_editor.py` so the Playwright workflow fails immediately when the profile page raises browser parse/runtime errors.

## Impact Analysis

- The profile fact-memory editor loads normally again.
- Browser-side failures caused by duplicate inline declarations are now covered by both source-level and UI-level regression checks.

## Validation

- Before: The profile page could stop executing its inline script with a duplicate declaration error for `factMemoryEntries`.
- After: The template declares those fact-memory symbols once, and the regression tests guard the page against the same merge-style duplication.