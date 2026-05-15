# SQL ODBC Driver Registration File Fix

Fixed/Implemented in version: **0.241.012**

Related config.py update: `VERSION = "0.241.012"`

## Issue Description

`azd up` could fail during the Windows `predeploy` ACR build after installing SQL Server ODBC Driver 18. The Docker build reached the distroless runtime stage and then failed with missing ODBC runtime copy sources, including:

```text
COPY failed: stat etc/odbcinst.ini: file does not exist
COPY failed: no source files were specified
```

## Root Cause Analysis

The Dockerfile assumed the Azure Linux `msodbcsql18` and `unixODBC` package installation would always create `/etc/odbcinst.ini` in the builder stage and place unixODBC libraries under `/usr/lib64`. In the ACR remote build, `/etc/odbcinst.ini` was absent and the unixODBC libraries were not available through the hardcoded `/usr/lib64/libodbc*` copy pattern, so Docker failed before the image could be published.

## Technical Details

### Files Modified

- `application/single_app/Dockerfile`
- `application/single_app/config.py`
- `functional_tests/test_sql_odbc_driver_18_support.py`
- `functional_tests/test_entra_application_graph_mfa_auth.py`
- `functional_tests/test_entra_application_azd_env_persistence.py`

### Code Changes Summary

- After installing `msodbcsql18`, the Docker builder stage now resolves the installed `libmsodbcsql-*.so*` path under `/opt/microsoft/msodbcsql18/lib64`.
- The builder writes a deterministic `/etc/odbcinst.ini` registration for `ODBC Driver 18 for SQL Server`.
- The builder stages unixODBC and libltdl shared libraries from either `/usr/lib64` or `/usr/lib` into `/odbc-runtime/usr/lib64`.
- The distroless runtime can now copy the registration file and staged unixODBC libraries reliably while preserving the existing Driver 18 runtime support.

## Validation

- ACR log review for failed run `cp1` confirmed the missing `/etc/odbcinst.ini` source file.
- ACR log review for failed run `cp2` confirmed the hardcoded `/usr/lib64/libodbc*` copy pattern had no sources.
- ACR verification run `cp3` succeeded with the staged ODBC runtime files.
- `azd deploy` completed successfully after the Dockerfile fix.
- Functional test: `functional_tests/test_sql_odbc_driver_18_support.py`
- Functional test: `functional_tests/test_entra_application_graph_mfa_auth.py`
- Functional test: `functional_tests/test_entra_application_azd_env_persistence.py`
- Expected outcome: the ACR Docker build no longer fails while copying ODBC Driver 18 registration or unixODBC runtime files into the distroless image.