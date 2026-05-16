# Control Center Debug Print Import Fix (v0.241.029)

Fixed/Implemented in version: **0.241.029**

## Issue Description

Application startup failed while importing the admin settings route because `functions_control_center.py` attempted to import `debug_print` from `config.py`.

The runtime error was:

```text
ImportError: cannot import name 'debug_print' from 'config'
```

## Root Cause Analysis

`debug_print` is exposed through the shared `functions_debug.py` compatibility shim, which forwards to the Application Insights logging implementation. Most backend modules already import `debug_print` from that shim.

The Control Center helper module was the lone startup path importing `debug_print` from `config.py`, where that symbol is not defined.

## Technical Details

Files modified: `application/single_app/functions_control_center.py`, `application/single_app/config.py`, `functional_tests/test_control_center_debug_print_import.py`

Code changes summary:

- Updated `functions_control_center.py` to import Cosmos containers from `config.py` and `debug_print` from `functions_debug.py`.
- Bumped `application/single_app/config.py` to `VERSION = "0.241.029"`.
- Added a source-level functional regression test that prevents `functions_control_center.py` from importing `debug_print` from `config.py` again.

Impact analysis:

- Admin settings and Control Center helper imports no longer fail during application startup.
- Debug logging continues to flow through the existing Application Insights-backed debug shim.
- No authorization, route behavior, or frontend rendering behavior changed.

## Validation

Test coverage: `functional_tests/test_control_center_debug_print_import.py`

Test results:

- `python -m py_compile application/single_app/config.py application/single_app/functions_control_center.py functional_tests/test_control_center_debug_print_import.py`
- `python functional_tests/test_control_center_debug_print_import.py`
- `python -c "import route_frontend_admin_settings; print('route_frontend_admin_settings import ok')"`

Before/after comparison:

- Before: Startup failed while loading `route_frontend_admin_settings.py` because `config.py` did not export `debug_print`.
- After: `functions_control_center.py` resolves `debug_print` through the established `functions_debug.py` shim and the admin settings import completes.

Related config.py version update: `VERSION = "0.241.029"`