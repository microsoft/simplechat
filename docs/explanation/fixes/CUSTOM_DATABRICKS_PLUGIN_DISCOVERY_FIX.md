# Custom Databricks Plugin Discovery Fix

Fixed/Implemented in version: **0.250.103**

## Issue Description

Custom plugin types with Databricks-prefixed names, such as `databricks_table_dscmo`, could inherit the built-in Databricks discovery defaults when action types were listed for the creation modal. These custom plugin types should remain on the standard plugin configuration path unless they are the exact built-in Databricks types.

Associated issue: [microsoft/simplechat#1124](https://github.com/microsoft/simplechat/issues/1124)

## Root Cause Analysis

The action type discovery route selected the Databricks safe manifest whenever the plugin module name contained `databricks`. That substring check was too broad and could classify custom plugin modules as built-in Databricks plugins during metadata extraction.

## Technical Details

Files modified:

- `application/single_app/functions_databricks_operations.py`
- `application/single_app/route_backend_plugins.py`
- `application/single_app/static/js/workspace/view-utils.js`
- `application/single_app/config.py`
- `functional_tests/test_plugin_type_discovery_custom_databricks.py`

Code changes summary:

- Added an exact built-in Databricks discovery classifier for `databricks` and `databricks_table`.
- Updated action type discovery to use the exact classifier instead of a broad `databricks` substring check.
- Updated shared action icon classification so custom Databricks-prefixed plugin types use the standard action icon.
- Added regression coverage for custom Databricks-prefixed plugin type discovery and visual classification.
- The regression test scaffolds a temporary `databricks_table_dscmo` plugin, definition file, and schema files, then confirms discovery and settings merge use the standard plugin path.

## Validation

- Added and ran `functional_tests/test_plugin_type_discovery_custom_databricks.py`.
- The test creates and removes its fake plugin scaffold at runtime, so no test-only plugin remains in the application plugin directory.
- Ran Python syntax checks for the changed Python files.

Reference version update: `application/single_app/config.py` was updated to **0.250.103**.
