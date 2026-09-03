# Distroless Runtime Overlay Path Fix

Fixed in version: **0.261.009**

Related config.py version update: `application/single_app/config.py` was incremented to `0.261.009`.

## Issue Description

Container builds could fail during final-stage runtime overlay copy with:

`cannot copy to non-directory ... /usr/lib64`

The failure was first observed on:

- `COPY --from=builder /odbc-runtime/ /`

After addressing that path, the same failure surfaced on:

- `COPY --from=builder /playwright-runtime/ /`

## Root Cause Analysis

The builder staged runtime payloads under directory trees containing `usr/lib64`, then copied those trees into `/` on a distroless base image. On newer base-image layouts, `/usr/lib64` may be a symlink or other non-directory entry, and Docker BuildKit refuses to overlay a directory on top of a non-directory path.

This made full-tree overlays brittle against base image filesystem changes.

## Technical Details

Files modified:

- `application/single_app/Dockerfile`
- `application/single_app/config.py`
- `functional_tests/test_sql_container_odbc_runtime.py`
- `functional_tests/test_sql_odbc_driver_18_support.py`

Code changes summary:

- Updated ODBC staging destination from `"/odbc-runtime/usr/lib64"` to `"/odbc-runtime/usr/lib"`.
- Updated Playwright staging destination from `"/playwright-runtime/usr/lib64"` to `"/playwright-runtime/usr/lib"`.
- Preserved source library glob coverage from both `/usr/lib64` and `/usr/lib` in the builder stage so either package layout remains supported.
- Kept final runtime copies (`/odbc-runtime/` and `/playwright-runtime/`) unchanged while eliminating directory-vs-non-directory path collisions at `/usr/lib64`.

## Validation

Validation evidence for the change sequence included:

- `functional_tests/test_sql_container_odbc_runtime.py` passed after assertion alignment and Dockerfile path updates.
- `functional_tests/test_sql_odbc_driver_18_support.py` continued to validate SQL ODBC Driver 18 runtime/default behavior.
- `functional_tests/test_deep_research_chromium_build_opt_out.py` covered Playwright Chromium build-arg and runtime copy wiring.

## Before and After

- Before: BuildKit could fail in the final stage when runtime overlay trees attempted to create `usr/lib64` as a directory over a non-directory target in the distroless base.
- After: Runtime overlays stage libraries under `usr/lib`, avoiding `/usr/lib64` target-shape conflicts while preserving SQL ODBC and Playwright native runtime packaging.