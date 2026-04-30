# Changed-Files GitHub Action Supply Chain Fix

Fixed/Implemented in version: **0.239.135**

## Issue Description

The repository's release notes workflow used `tj-actions/changed-files@v44`, a tag family affected by the March 2025 supply chain incident involving retroactively modified action tags.

Even though the malicious window has been closed and current tags were restored, keeping the workflow on the older tag family left the repository behind the patched release identified by the advisory.

## Root Cause Analysis

- `.github/workflows/release-notes-check.yml` depended on `tj-actions/changed-files@v44`.
- The security advisory identifies `46.0.1` as the patched version for the compromised action.

## Technical Details

### Files Modified

- `.github/workflows/release-notes-check.yml`
- `application/single_app/config.py`
- `functional_tests/test_changed_files_action_version.py`

### Code Changes Summary

- Updated the release notes workflow to use `tj-actions/changed-files@v46.0.1`.
- Added a functional regression test that verifies the patched action reference and rejects the known malicious commit SHA.
- Bumped the application version to `0.239.135` for traceability.

### Testing Approach

- Added `functional_tests/test_changed_files_action_version.py` to validate the workflow pin, version bump, and fix documentation marker.

## Validation

### Before

- The workflow referenced `tj-actions/changed-files@v44`.
- There was no repository-level regression check guarding against reintroduction of the malicious commit SHA.

### After

- The workflow references the patched `v46.0.1` release.
- The regression test asserts that the known malicious SHA is absent and the patched version remains in place.

### Impact Analysis

This is a narrow CI supply-chain remediation. It does not change application runtime behavior, but it does reduce the risk of reintroducing a compromised GitHub Action reference in repository automation.