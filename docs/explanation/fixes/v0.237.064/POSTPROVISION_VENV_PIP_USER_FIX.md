# Postprovision Venv Pip User Fix

Fixed/Implemented in version: **0.237.064**

## Issue Description

`azd up` could fail in `postprovision` at the Python dependency installation step when the deployment was launched from an activated virtual environment.

## Root Cause Analysis

The postprovision hook always used `pip install --user`, but pip rejects `--user` installs when the active interpreter is already inside a virtual environment because user site-packages are not visible there.

## Technical Details

### Files Modified

- `deployers/azure.yaml`
- `functional_tests/test_postprovision_python_dependency_install.py`
- `application/single_app/config.py`

### Code Changes Summary

- Added Python virtual environment detection to the POSIX and Windows postprovision hooks.
- Changed the dependency install step to omit `--user` when the active interpreter is inside a virtual environment.
- Improved error reporting so pip output is surfaced when the install still fails.

## Validation

- Functional test: `functional_tests/test_postprovision_python_dependency_install.py`
- Reproduced root cause locally with: `python -m pip install --user ...` under the repo virtual environment.
- Expected outcome: postprovision dependency installation succeeds whether deployment runs from a virtual environment or a system interpreter.