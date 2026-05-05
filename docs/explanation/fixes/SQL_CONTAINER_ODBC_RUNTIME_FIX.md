# SQL Container ODBC Runtime Fix (v0.241.064)

Fixed/Implemented in version: **0.241.064**

## Issue Summary

Fresh container deployments failed the SQL Server "Test Connection" flow with `Database driver not installed: libodbc.so.2: cannot open shared object file: No such file or directory`.

## Root Cause

- The application Docker build installed `pyodbc`, but the final distroless runtime image did not carry forward the unixODBC shared libraries required at runtime.
- Azure Linux 3 publishes `msodbcsql18` in the supported Microsoft non-OSS package feed, while the app still defaulted new SQL configurations and examples to ODBC Driver 17.
- That mismatch meant fresh container deployments could fail before connecting, and new SQL configurations would still point at an older driver that is not present in the image.

## Files Modified

- `application/single_app/Dockerfile`
- `application/single_app/config.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/semantic_kernel_plugins/sql_query_plugin.py`
- `application/single_app/semantic_kernel_plugins/sql_schema_plugin.py`
- `application/single_app/semantic_kernel_plugins/sql_plugin_factory.py`
- `application/single_app/semantic_kernel_plugins/SQL_Plugins_Configuration_Guide.md`
- `application/single_app/static/js/plugin_modal_stepper.js`
- `application/single_app/templates/_plugin_modal.html`
- `functional_tests/test_sql_container_odbc_runtime.py`

## Code Changes Summary

1. Added the Azure Linux Microsoft non-OSS repository to the builder image and installed `unixODBC`, `unixODBC-devel`, and `msodbcsql18`.
2. Packaged the required ODBC runtime files into an intermediate `/odbc-runtime` directory and copied them into the final distroless image, including `odbcinst.ini`, unixODBC shared libraries, and the Microsoft SQL driver files under `/opt/microsoft`.
3. Switched fresh SQL Server defaults, factory-generated connection strings, UI defaults, and documentation examples from ODBC Driver 17 to ODBC Driver 18.
4. Improved the SQL test-connection error for missing unixODBC runtime and for explicit Driver 17 selection in the container image.
5. Added a focused regression test that validates the container packaging and fresh-driver defaults.

## Validation

- `functional_tests/test_sql_container_odbc_runtime.py` checks that the Dockerfile now packages the unixODBC runtime and `msodbcsql18` artifacts for the distroless image.
- The same functional test validates that backend defaults, frontend defaults, and SQL examples all point to ODBC Driver 18 for fresh deployments.
- The SQL driver picker regression check keeps ODBC Driver 17 available for older custom images, but prioritizes ODBC Driver 18 for the supported container path.

## Impact

- Fresh container deployments can load `pyodbc` successfully for SQL Server connectivity.
- New SQL plugin configurations now default to the driver version that the Azure Linux container image actually ships.
- Existing custom environments can still choose ODBC Driver 17 explicitly if they build images that provide it.