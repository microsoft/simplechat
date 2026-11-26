# Test Suite Normalization

Implemented in version: **0.261.489**

## Overview and Purpose

SimpleChat's functional and UI tests had fallen behind the application. Many
failed on any machine without the SimpleChat team's Azure resources, many failed
on every version bump because they compared an exact version string, and stubs
installed by one test file broke the files that ran after it. A fork or an
organization that customizes SimpleChat could not tell its own regressions from
the existing failures.

This change makes the suites runnable anywhere, keeps them working across version
bumps, and records the tests that are still out of date in a list that can only
shrink.

Dependencies: pytest, Node's built-in test runner, Playwright for the UI suite.
pytest-xdist and pytest-timeout are used when installed but are not required.

## Technical Specifications

### Architecture

| Piece | File | What it does |
|---|---|---|
| Offline Cosmos DB | `functional_tests/test_support/offline_cosmos.py` | With no Cosmos DB account configured, the real `config.py` imports against an in-memory Cosmos client. |
| Live-service skips | `functional_tests/test_support/live_services.py` | `require_live_cosmos(__file__)` skips a file that needs a real deployment and names the missing setting. |
| Per-file module isolation | `functional_tests/test_support/module_isolation.py` | Stubs a file puts in `sys.modules` are removed after it is collected and restored while its own tests run, then removed again after its last test. |
| Version checks | `functional_tests/test_support/versioning.py` | `assert_app_version_at_least()` replaces exact `VERSION = "..."` comparisons. |
| Known failures | `functional_tests/known_failures.txt`, `functional_tests/test_support/known_failures.py` | Listed tests run as strict expected failures; listed files are not collected. |
| Runner | `scripts/run_tests.py` | Runs the functional, JavaScript (`.js` and `.mjs`) and UI suites with the flags each needs. |
| Header tool | `scripts/normalize_test_headers.py` | Checks and fixes each test file's filename comment and `Version:` / `Implemented in:` lines. |

`functional_tests/conftest.py` wires these together. The pytest return-False
guard (#1572) is unchanged and still identical in both conftests.

### Known-failures list

Each line names a test (`file::test`) or a whole file, followed by `# reason`.

- A listed test is marked `xfail(strict=True)`. It reports `xfailed` while it
  fails; once it passes, the run fails with `XPASS(strict)` until the line is
  removed.
- A listed test with subtests counts as failing when it or any of its subtests
  fails. Its failing subtests report `xfailed` and its passing subtests pass.
- A listed Python file is not collected. This is only for files that cannot be
  imported or that hang.
- A listed JavaScript file is run by `scripts/run_tests.py js`, which reports it
  as `xfail` while it fails and fails the run once it passes.
- `SIMPLECHAT_IGNORE_KNOWN_FAILURES=1` turns the list off.
- Tests that GitHub workflows run are never listed, so the list cannot change
  what CI checks.
- `functional_tests/test_functional_known_failures_list.py` checks that the list
  parses and names existing files, and that the plugin behaves as described.

### Configuration

| Variable | Effect |
|---|---|
| `SIMPLECHAT_TESTS_OFFLINE=1` | Skip live-service tests even when a deployment is configured. |
| `SIMPLECHAT_ENV_FILE` | Dotenv file to read deployment settings from. |
| `SIMPLECHAT_TEST_MODULE_ISOLATION=0` | Turn off per-file `sys.modules` isolation. |
| `SIMPLECHAT_IGNORE_KNOWN_FAILURES=1` | Run listed tests normally. |

### Removed tests

40 test files for removed features (the old workflow and PII analysis pages),
debugging scripts that were never tests, and tests that only worked against one
team's real data were deleted after review.

### Application fixes found by the tests

- The Control Center Activity Logs auto-refresh had been lost and is restored
  (`CONTROL_CENTER_ACTIVITY_LOG_AUTO_REFRESH.md`).
- Admin Settings rendered two elements with the same ID for the Latest Features
  settings (`ADMIN_LATEST_FEATURES_VISIBILITY_FIX.md`).

## Usage Instructions

See `docs/contributing/testing.md` for setup and commands. In short:

```powershell
python scripts/run_tests.py functional
```

```powershell
python scripts/run_tests.py js
```

To work on a listed test, run it with the list turned off, fix it (or the
application, if the test found a real problem), and remove its line:

```powershell
$env:SIMPLECHAT_IGNORE_KNOWN_FAILURES = "1"; python -m pytest functional_tests/test_example.py -q
```

## Testing and Validation

- Each of the 2,019 functional test files was run in its own pytest process
  against this version, with no Azure resources configured. The list holds
  2,607 tests from 573 files and 6 whole Python files (4 that cannot be
  imported, 2 with a test that runs longer than 5 minutes).
- 940 of those tests, in 97 files, passed before this change was rebased
  onto Development 0.261.488 and fail the same way on that Development commit,
  with or without per-file isolation. Their stubs and source checks predate
  application changes merged there.
- Seven files that GitHub workflows run fail on a Windows machine without a
  deployment (`test_export_evidence_cosmos_contract.py`,
  `test_global_identity_admin_routes.py`, `test_orchestration_deliverables.py`,
  `test_orchestration_document_loader_reliability.py`,
  `test_shared_agent_secret_responses.py`,
  `test_tabular_row_orchestration_scale.py`, `test_workflow_configuration.py`).
  On Development, without the in-memory Cosmos client, most of them cannot be
  imported at all. They are not listed, for the reason above.
- With the list active, every file was run again in its own process. Apart from
  the seven files above and the listed whole files (which a run that names them
  directly still collects), every file passed. Two timing tests
  (`test_source_review_chromium_startup.py` and
  `test_tabular_model_http_diagnostics.py`) failed only when 14 files ran at
  once. They pass when run alone and are not listed.
- `scripts/check_cosmos_response_boundaries.py --run-contracts`, which CI runs
  with the network blocked, was run against this change: 2,416 passed and 0
  review gaps.
- `test_functional_known_failures_list.py` and
  `test_functional_module_isolation.py` cover the list and the per-file
  isolation.
- The JavaScript suite was run with `scripts/run_tests.py js`: 112 of 128 files
  passed, and the 16 failing files are listed. The 7 that started failing after
  the rebase fail the same way on Development.

### Known limitations

- The known-failures list is a starting point, not a fix. Its entries are being
  fixed in follow-up changes, and a fixed test must come off the list.
- A test that depends on real data can pass against the empty in-memory Cosmos
  client without checking anything meaningful. Such tests should call
  `require_live_cosmos(__file__)`.
- The UI suite has no known-failures list and was not rerun for this change.
  Offline UI tests need Chromium and the built v2 SPA; live UI tests skip unless
  `SIMPLECHAT_UI_BASE_URL` is set.
- The whole functional suite in a single pytest process (`run_tests.py
  functional` without pytest-xdist) is much slower than running files in
  parallel.
