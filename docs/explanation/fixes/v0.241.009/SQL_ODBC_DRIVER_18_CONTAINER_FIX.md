# SQL ODBC Driver 18 Container Fix - v0.241.009

## Issue Description

Users creating or testing SQL actions against SQL Server or Azure SQL received errors indicating that `ODBC Driver 17 for SQL Server` could not be found. The Python application included `pyodbc`, but the Azure Linux distroless application image did not include the native Microsoft ODBC SQL Server driver and unixODBC runtime files required by `pyodbc`.

## Root Cause Analysis

The SQL action code imported `pyodbc` and built SQL Server connection strings, but the container only installed Python packages from `requirements.txt`. The final distroless runtime image did not copy forward Microsoft ODBC driver files, unixODBC shared libraries, or `/etc/odbcinst.ini`, so `pyodbc.connect()` could fail at runtime with a missing Driver 17 library error.

Existing SQL action defaults also preferred `ODBC Driver 17 for SQL Server`, which meant new actions continued to select the driver users were missing.

## Fixed in version: **0.241.009**

The version was updated in `application/single_app/config.py` from `0.241.008` to `0.241.009` for this fix.

## Technical Details

### Files Modified

| File | Change |
|------|--------|
| `application/single_app/Dockerfile` | Registers the Microsoft Azure Linux `ms-non-oss` package feed, installs `msodbcsql18` and `unixODBC` in the builder stage, then copies `/opt/microsoft`, `/etc/odbcinst.ini`, unixODBC shared libraries, and ODBC library paths into the distroless runtime. |
| `application/single_app/semantic_kernel_plugins/sql_odbc_utils.py` | Adds shared Driver 18 constants, SQL Server connection string construction, and Driver 17-to-18 retry logic for missing-driver errors. |
| `application/single_app/semantic_kernel_plugins/sql_schema_plugin.py` | Uses Driver 18 as the default SQL Server ODBC driver and applies legacy Driver 17 fallback. |
| `application/single_app/semantic_kernel_plugins/sql_query_plugin.py` | Uses Driver 18 as the default SQL Server ODBC driver and applies legacy Driver 17 fallback. |
| `application/single_app/semantic_kernel_plugins/sql_plugin_factory.py` | Generates SQL Server and Azure SQL plugin configuration with Driver 18 defaults. |
| `application/single_app/route_backend_plugins.py` | Uses Driver 18 defaults and fallback logic in the SQL action Test Connection endpoint. |
| `application/single_app/templates/_plugin_modal.html` | Presents Driver 18 before Driver 17 in the SQL action driver selector. |
| `application/single_app/static/js/plugin_modal_stepper.js` | Defaults new SQL actions and examples to Driver 18. |
| `application/single_app/semantic_kernel_plugins/SQL_Plugins_Configuration_Guide.md` | Updates SQL Server connection string examples to Driver 18. |
| `functional_tests/test_sql_odbc_driver_18_support.py` | Adds regression coverage for container ODBC runtime installation, Driver 18 defaults, legacy Driver 17 fallback, and version consistency. |

### Code Changes Summary

- The application image now registers the Microsoft Azure Linux `ms-non-oss` package feed, installs the Microsoft ODBC Driver 18 package using `ACCEPT_EULA=Y`, and includes the native ODBC files needed by the final distroless runtime.
- New SQL Server and Azure SQL action defaults use `ODBC Driver 18 for SQL Server`.
- Saved actions or connection strings that still reference `ODBC Driver 17 for SQL Server` are retried with Driver 18 when the failure is specifically a missing-driver error.
- Non-driver errors, such as login failures, are not retried or masked by the fallback logic.

## Testing Approach

- Functional test: `functional_tests/test_sql_odbc_driver_18_support.py`
- Validates Dockerfile ODBC runtime installation and copy-forward instructions.
- Validates generated SQL Server connection strings default to Driver 18.
- Validates saved Driver 17 connection strings retry with Driver 18 when Driver 17 is unavailable.
- Validates non-driver errors are not hidden by fallback behavior.
- Validates `config.py` version consistency for v0.241.009.

## Impact Analysis

- **SQL Server and Azure SQL actions**: New actions now target Driver 18 by default, and existing Driver 17 actions can recover automatically when the missing-driver error occurs.
- **Container deployments**: Azure Linux distroless runtime images include the native ODBC driver and registration files needed by `pyodbc`.
- **Other database actions**: PostgreSQL, MySQL, and SQLite paths are unchanged.
- **Security**: The fallback logs driver names and exception type only; it does not log connection strings, usernames, or passwords.

## Validation

Before the fix, SQL actions could fail with missing native ODBC Driver 17 errors despite `pyodbc` being installed. After the fix, the runtime image includes Driver 18, new action defaults point to Driver 18, and legacy Driver 17 references retry with Driver 18 only when the legacy driver is unavailable.