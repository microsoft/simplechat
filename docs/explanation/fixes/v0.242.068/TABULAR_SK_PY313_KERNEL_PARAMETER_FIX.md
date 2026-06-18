# Tabular SK Python 3.13 Kernel Parameter Fix

Fixed in version: **0.242.068**

## Issue Description

Semantic Kernel tool-call parsing can fail on Python 3.13 when public plugin parameters are annotated as `Annotated[Optional[str], ...]`. During argument coercion, Semantic Kernel may try to instantiate `typing.Optional[str]`, which is a `Union[str, None]` and is not callable.

The failure appears as a `TypeError` similar to `Cannot instantiate typing.Union` and can prevent tabular workbook tools from running even when the same tool signatures worked under older runtime behavior.

## Root Cause Analysis

The affected surface is the public `@kernel_function` method signatures in `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`. These signatures are parsed by Semantic Kernel, unlike normal internal helper annotations.

Internal helpers can safely keep `Optional[str]` annotations. Public Semantic Kernel tool parameters should use concrete parseable types, while defaults such as `= None` continue to represent omitted optional arguments.

## Technical Details

### Files Modified

- `application/single_app/semantic_kernel_plugins/tabular_processing_plugin.py`
- `functional_tests/test_tabular_kernel_parameter_annotations.py`
- `application/single_app/config.py`

### Code Changes Summary

- Replaced public `@kernel_function` parameter annotations from `Annotated[Optional[str], ...]` to `Annotated[str, ...]`.
- Kept `None` defaults for optional tool parameters so omitted values remain supported.
- Preserved internal helper type hints that are not parsed by Semantic Kernel.
- Added a regression test that parses the tabular plugin AST and fails if any `@kernel_function` parameter reintroduces `Annotated[Optional[str], ...]`.

## Validation

Validation includes:

- Python compile checks for the tabular plugin and new functional test.
- `functional_tests/test_tabular_kernel_parameter_annotations.py`.
- Existing tabular pagination and relational helper tests to ensure the annotation cleanup does not change runtime behavior.

## Impact Analysis

This change supports both Python 3.12 and Python 3.13. Tool-call behavior remains the same for callers: optional arguments can still be omitted, and plugin code still treats `None` and empty strings as not provided where appropriate.

## Attribution

This fix was inspired by and adapted from PR #892 by @vivche, which identified the Python 3.13 Semantic Kernel `Optional[str]` parameter parsing issue while investigating tabular SK multi-endpoint workbook analysis.

The multi-endpoint route changes from PR #892 were not merged directly because current Development already supersedes them through the shared model-context runtime, but the Python 3.13 compatibility insight is preserved here with a focused regression test.

## Related Version Updates

- `application/single_app/config.py` updated to `0.242.068`.
