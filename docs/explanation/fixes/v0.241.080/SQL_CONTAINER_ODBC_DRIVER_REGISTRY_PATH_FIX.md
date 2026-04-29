# SQL Container ODBC Driver Registry Path Fix

Version: 0.241.080

Fixed/Implemented in version: **0.241.080**

## Issue Description

`azd deploy` container builds started failing in Azure Container Registry during the ODBC runtime packaging step with `cp: cannot stat '/etc/odbcinst.ini': No such file or directory`.

## Root Cause Analysis

The SQL container runtime packaging logic assumed that `msodbcsql18` would always register the unixODBC driver in `/etc/odbcinst.ini`.

On Azure Linux 3, the package install reports its driver target directory through `odbcinst -j`, and the build log showed that the active location was `/etc/unixODBC`. The Dockerfile hard-coded the older root-level path, so the build failed before the distroless runtime image could be assembled.

## Technical Details

### Files Modified

- `application/single_app/Dockerfile`
- `application/single_app/config.py`
- `functional_tests/test_sql_container_odbc_runtime.py`

### Code Changes Summary

- Updated the Dockerfile to detect the unixODBC driver registry directory with `odbcinst -j` instead of assuming `/etc/odbcinst.ini`.
- Copied the detected `odbcinst.ini` path into the `/odbc-runtime` payload so the final distroless image preserves the package-selected layout.
- Kept a compatibility copy under `/etc/odbcinst.ini` when the package uses a subdirectory path.
- Extended the existing SQL container regression test to verify the dynamic path handling and to fail if the Dockerfile regresses to the old hard-coded copy path.

## Testing And Validation

- Focused Dockerfile diagnostics in the editor after the packaging-step update.
- Functional regression: `functional_tests/test_sql_container_odbc_runtime.py`

## Impact Analysis

- ACR builds no longer fail when Azure Linux 3 registers the SQL Server ODBC driver under `/etc/unixODBC` instead of `/etc`.
- The distroless runtime keeps the unixODBC driver registry in the same location reported by the installed package.
- This change is a follow-up to the earlier SQL runtime packaging work documented in `docs/explanation/fixes/SQL_CONTAINER_ODBC_RUNTIME_FIX.md`.