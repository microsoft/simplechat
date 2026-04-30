# Swagger Route Check Annotation Fix

Fixed/Implemented in version: **0.240.003**

## Header Information

### Issue Description

The pull request Swagger route validator could terminate with a raw traceback when a changed Python file could not be decoded as UTF-8 or parsed by `ast.parse()`.

That failure stopped the job, but it did not emit a GitHub Actions `::error` annotation that pointed reviewers to the file and line that blocked validation.

### Root Cause Analysis

`scripts/check_swagger_routes.py` read and parsed files without handling `UnicodeDecodeError`, `OSError`, or `SyntaxError`.

The script also re-read each file in `main()` to detect route usage, which meant the main loop had a second unhandled file-read path even after inspection logic completed.

### Version Implemented

`0.240.003`

## Technical Details

### Files Modified

- `scripts/check_swagger_routes.py`
- `functional_tests/test_swagger_route_pr_workflow.py`
- `application/single_app/config.py`
- `docs/explanation/features/SWAGGER_PR_ROUTE_CHECK.md`

### Code Changes Summary

- Added shared GitHub Actions annotation formatting for Swagger route validation failures.
- Wrapped file reads so decode and file access failures emit `::error file=...,line=1::...` output and fail cleanly.
- Wrapped AST parsing so syntax failures emit `::error file=...,line=...::...` output using the parser line number.
- Removed the duplicate file read from `main()` by returning route-presence information from the inspection helper.
- Bumped the application version to `0.240.003`.

### Testing Approach

- Extended the existing functional workflow regression test with syntax-error and invalid-UTF-8 cases.
- Retained the existing success-path and missing-swagger-decorator coverage.

### Impact Analysis

- Makes pull request failures actionable because the checker now produces standard GitHub Actions annotations for parser and read failures.
- Prevents the validation script from crashing before it can explain why the workflow failed.
- Keeps the route inspection logic consistent by reading each file only once.

## Validation

### Before/After Comparison

Before: a malformed or non-UTF-8 Python file could crash the checker with a traceback and no targeted annotation for reviewers.

After: the checker exits non-zero with a GitHub Actions error annotation that identifies the failing file and line.

### Test Results

- Functional regression coverage updated in `functional_tests/test_swagger_route_pr_workflow.py`.
- The checker continues to pass valid files and reject missing Swagger decorators while now also reporting read and parse failures cleanly.