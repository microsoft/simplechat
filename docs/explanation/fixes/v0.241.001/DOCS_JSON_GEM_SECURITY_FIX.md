# Docs JSON Gem Security Fix

Fixed/Implemented in version: **0.239.136**

## Issue Description

The docs site bundle resolved the Ruby `json` gem to `2.15.0`, which falls in the
advisory's affected range for format string injection when parsing untrusted JSON
with `allow_duplicate_key: false`.

## Root Cause Analysis

The docs Jekyll bundle relied on transitive dependency resolution for `json`
without an explicit minimum version constraint, so `bundle update` had previously
locked the site to a vulnerable release.

## Technical Details

### Files Modified

- `docs/Gemfile`
- `docs/Gemfile.lock`
- `application/single_app/config.py`
- `functional_tests/test_docs_json_gem_security_fix.py`

### Code Changes Summary

- Added an explicit `json >= 2.19.2` dependency to the docs bundle.
- Updated the docs lockfile from `json 2.15.0` to `json 2.19.2`.
- Added a regression test that verifies the Gemfile floor, resolved lockfile version,
  and application version bump.
- Bumped the application version to `0.239.136`.

### Testing Approach

- Ran a targeted `bundle update json` in `docs/` to resolve the patched gem version.
- Added `functional_tests/test_docs_json_gem_security_fix.py` to verify the fix stays
  in place.

## Validation

### Before

- `docs/Gemfile.lock` resolved `json (2.15.0)`.
- The patched version was not enforced directly in `docs/Gemfile`.

### After

- `docs/Gemfile.lock` resolves `json (2.19.2)`.
- `docs/Gemfile` enforces a patched minimum so future dependency refreshes do not
  drift back into the vulnerable range.

### Impact Analysis

This is a low-risk dependency hardening change scoped to the docs site bundle. It
does not alter application runtime behavior, but it removes a known vulnerable gem
version from the repository-managed Ruby dependencies.