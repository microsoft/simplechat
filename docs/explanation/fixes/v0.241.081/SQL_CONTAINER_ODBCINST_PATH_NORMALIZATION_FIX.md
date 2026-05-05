# SQL Container ODBCINST Path Normalization Fix

Version: 0.241.081

Fixed/Implemented in version: **0.241.081**

## Issue Description

After updating the SQL container runtime packaging to use `odbcinst -j`, Azure Container Registry builds still failed while assembling the distroless ODBC payload.

## Root Cause Analysis

On Azure Linux 3, the `DRIVERS` entry returned by `odbcinst -j` resolves to the full file path `/etc/unixODBC/odbcinst.ini`, not just the containing directory.

The previous Dockerfile revision treated that value as a directory and appended another `/odbcinst.ini`, producing an invalid path like `/etc/unixODBC/odbcinst.ini/odbcinst.ini`.

## Technical Details

### Files Modified

- `application/single_app/Dockerfile`
- `application/single_app/config.py`
- `functional_tests/test_sql_container_odbc_runtime.py`

### Code Changes Summary

- Normalized the `odbcinst -j` result into a concrete `driver_config_file` first.
- Added shell-only handling for both supported output shapes: a direct `odbcinst.ini` file path or a directory path.
- Derived the runtime copy target directory from the normalized file path before copying the ODBC registry into `/odbc-runtime`.
- Extended the SQL container regression test to assert the file-or-directory normalization logic.

## Testing And Validation

- Local functional regression: `functional_tests/test_sql_container_odbc_runtime.py`
- Local container reproduction against `mcr.microsoft.com/azurelinux/base/python:3.12` confirmed that `odbcinst -j` reports `/etc/unixODBC/odbcinst.ini` on Azure Linux 3.

## Impact Analysis

- Local Docker builds and ACR task builds no longer depend on guessing whether `odbcinst -j` returns a directory or the full file path.
- The SQL Server ODBC runtime packaging step now works with the actual Azure Linux 3 unixODBC layout used by `msodbcsql18`.