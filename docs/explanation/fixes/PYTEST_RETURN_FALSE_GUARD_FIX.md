# Pytest Return-False Guard Fix (v0.261.203)

## Issue

pytest ignores the value a test function returns. The repo's functional test template has each
test catch its own failure, print it and `return False`, and a `__main__` runner turns the results
into an exit code. Run as a script, such a test fails as intended. Run under pytest, the same test
was reported as passed, with only a `PytestReturnNotNoneWarning`. A probe with three tests
(`return False`, `return True`, `assert False`) reported "1 failed, 2 passed".

Local and agent validation often use pytest, so a failing test could be reported as a pass. During
#1569, a docs quality suite was reported as 6/6 from pytest. Its `__main__` runner later confirmed
the result, but a failure would have looked the same.

Fixed in version: **0.261.203**. This is a test-tooling change, so `VERSION` in
`application/single_app/config.py` is unchanged. Tracked in #1572, found during #1543.

## Root cause

pytest's default `pytest_pyfunc_call` calls the test function and only warns when the result is
not `None`. Nothing in the repo turned a returned `False` into a failure: the root `pytest.ini`
only declares the `ui` marker, and there was no `conftest.py`.

## Technical details

### How the guard works

- `functional_tests/conftest.py` and `ui_tests/conftest.py` contain the same guard block, between
  `# --- begin pytest return-False guard (#1572) ---` and
  `# --- end pytest return-False guard (#1572) ---`.
- The block defines one hook, `pytest_pyfunc_call`, as a
  `pytest.hookimpl(wrapper=True, tryfirst=True)` wrapper. For a sync test it swaps
  `pyfuncitem.obj` for a `functools.wraps` recorder that keeps each return value, lets pytest call
  the test, and restores the original function in a `finally`. If the test returned exactly
  `False` (`is False`), it calls `pytest.fail(..., pytrace=False)`.
- The failure message names the test, says that under pytest a test that returns False now fails
  (#1572), and points at the test's captured stdout, which pytest prints after the message.
- `True`, `None`, `0`, `""` and every other value are left alone, so pytest keeps warning about
  them.
- Fixtures, yield fixtures, parametrized tests and `Test*` class methods work as before.
  `functools.wraps` keeps the signature that pytest injects fixtures by, and fixture teardown still
  runs after a guard failure.
- Async tests (coroutine functions, legacy `_is_coroutine` markers and async generator functions)
  pass through untouched, so pytest or an async plugin such as pytest-asyncio or anyio handles them
  as before. A sync test that returns a coroutine fails with pytest's own async message, never the
  guard's. `unittest.TestCase` methods never reach `pytest_pyfunc_call`, so the guard does not see
  them. The impact sweep lists the two async tests that return `False`.
- `tryfirst` keeps the recorder innermost. Without it, `pytest --trace` wraps the test function
  first and discards the return value, and the test passes again.
- The block adds no collection hooks and does not touch `sys.modules`, `sys.path` or any other
  global state. `--noconftest` turns it off.

### Where the guard lives

- `functional_tests/` holds the template-style tests. `ui_tests/` needs the guard too: 44 tests in
  8 `ui_tests/test_v2_orchestration_*.py` files can return `False`. Their page tests depend on
  `main()` setting `_PAGE`. Under pytest such a test hits its `except` branch and returns
  `False`, and was reported as passed. In the impact sweep, 36 of the 44 returned `False`.
- A single root `conftest.py` was not used. pytest would import it with the repo root first on
  `sys.path` for every run, and it would extend the guard to directories that do not need it.
  pytest scopes each directory conftest to the tests under it, so a combined run never wraps a
  test twice.
- The two copies must stay identical. The guard test compares the code between the markers, and
  checks that each file has exactly one `pytest_pyfunc_call`, inside the block, with the expected
  decorator and imports, and that neither file defines a collection hook.

### What does not change

- `python <file>` runs never load a conftest, so script runs behave as before. That includes CI,
  which runs functional tests as scripts. None of the 176 test files that call `pytest.main()`, and
  none of the tests another test file runs through pytest, returns `False` or a computed value.
- The staging UI workflow runs `python -m pytest <target> -m ui`. None of the `ui_tests` tests that
  return `False` is marked `ui`, so that run is unchanged, even over the whole directory.
- No application code, setting or `VERSION` changes.

### Files modified

- `functional_tests/conftest.py` (new): the guard block.
- `ui_tests/conftest.py` (new): the identical guard block.
- `functional_tests/test_pytest_return_false_guard.py` (new): the guard test.
- `.github/instructions/location_of_functional_tests.instructions.md`: a guard section, and a note
  under the Python test template.
- `CLAUDE.md`: a one-line note under the test template.

### Tests

`functional_tests/test_pytest_return_false_guard.py` runs pytest in a subprocess on probe files in
a temporary directory and reads each outcome from a JUnit XML report. Its checks raise
`AssertionError` explicitly, so they also run under `python -O`.

- The two guard blocks are identical, and each defines only the expected hook and imports.
- 25 probe outcomes for each copy:
  - Returning `False` fails with the guard message: a module function, a function in a nested
    directory, a parametrized case, a fixture, a yield fixture (whose teardown still runs) and two
    class methods.
  - Returning `True`, `None`, nothing, `0` or `""` passes, as does a test whose helper returns
    `False`.
  - `assert False` and a raised `ValueError` fail with their own messages.
  - Async tests and a sync test that returns a coroutine fail with pytest's own message, and a
    `unittest.TestCase` method that returns `False` passes. The guard never claims them.
  - The name and signature pytest sees are unchanged, and every test's function object is restored.
- The same outcomes under `python -O -m pytest`, and with the installed pytest plugins autoloaded.
  The plugin check is an environment skip, not a failure, when pytest cannot start with the
  installed plugins.
- `pytest --trace` still fails a test that returns `False`.
- `--collect-only` lists the same tests with and without the conftest.

A pytest subprocess that does not finish within 90 s is killed and retried, up to three attempts.
On the heavily loaded Windows machine used for this work, roughly one pytest start in seven
stalled: pytest imports `readline` at startup, pyreadline3 calls `platform.system()`, and Python
3.12's `platform` module runs a WMI query that did not return.

## Impact sweep

The sweep ran each test file the static scan flagged under pytest with the guard, at head
`ff2b730a9`, to see which tests the guard now fails. This change fixes none of them.

### Method

- **Scope.** An AST scan of the 1,877 test files (`test_*.py` and `*_test.py`) in
  `functional_tests/` and `ui_tests/` selected each file with a sync pytest-style test (a
  module-level `test*` function, or a `test*` method of a `Test*` class) whose own body returns a
  literal `False`, plus each file with such a test that returns a computed value, such as
  `return all(results)`. That is 327 files: 314 with 1,168 literal-`False` tests and 13 more with
  26 computed-return tests. 319 are in `functional_tests/`, 8 in `ui_tests/` and none in
  `functional_tests/route_tests/`.
- **Run.** Each file ran in its own
  `python -m pytest -p no:cacheprovider -q -rA --junitxml=<report> <file>` subprocess, one at a
  time, from the repo root, with the pinned test venv (Python 3.12.10, pytest 9.0.3). Outcomes come
  from each file's JUnit report.
- **Environment.** `PYTHONPATH=application/single_app;functional_tests` and
  `PYTHONIOENCODING=utf-8`. The harness would have removed `PYTEST_ADDOPTS`, `PYTEST_PLUGINS`,
  `PYTHONOPTIMIZE`, `PYTHONWARNINGS`, `SIMPLECHAT_ENV_FILE` and every variable whose name contains
  `AZURE`, `COSMOS`, `OPENAI` or `SEARCH`. Of those, only `TOOL_SEARCH` was set, and nothing in the
  repo reads it. No `.env` file was on the `load_dotenv` search path, so no test had Azure
  configuration or credentials.
- **Limits and retries.** Each file had 180 s, after which its process tree was killed. Each run
  started pytest through a small bootstrap, the same way `python -m pytest` does. On this machine
  some Python starts hang in the Windows WMI query behind `platform.system()`, before any test
  runs. The bootstrap left that query unchanged on the thread that made it, and a watcher thread
  flagged it when it had not returned after 15 s. A flagged attempt was killed and retried, up to
  three attempts. The bootstrap also turned off the Windows crash dialog, so a native crash would
  end a run at once, and armed a single stack dump at 170 s to show where a run that was about to
  time out was waiting. The two ten-minute repeat tests named for deselection are not in the sweep
  set, so nothing was deselected.
- **Isolation.** After every file, `git status` was checked. Changed tracked files would have been
  restored from `HEAD` and new untracked files deleted. Processes a test left running were killed.

Two async tests also return `False`. The guard passes coroutine functions through untouched,
because pytest and its async plugins own them, so the sweep counts them like any other test:

- `functional_tests/test_increased_content_size.py::test_increased_content_size`: pytest reported
  it as failed: "Failed: async def functions are not natively supported".
- `functional_tests/test_real_website_integration.py::test_real_websites`: not in the sweep set,
  because no sync test in the file returns `False`.

### Results

327 of 327 files completed with a JUnit report, and those files reported 1,171 test results. A
parametrized test counts once per case.

| Outcome | Tests | Files |
|---|---:|---:|
| Guard failure: the test returned a literal `False` | 438 | 199 |
| Guard failure: the test returned a computed value that was `False` | 5 | 5 |
| **Guard failures, total** | **443** | **202** |
| Other failure (an assertion or exception in the test) | 37 | 11 |
| Error (setup, teardown or collection) | 22 | 22 |
| Skipped | 0 | 0 |
| Passed | 669 | 200 |
| Timed out at 180 s, no per-test results | - | 0 |
| Hung in the WMI query in all three attempts | - | 0 |

The Files column counts the files with at least one test in that row, so one file can appear in
several rows.

Every guard failure was in a test the static scan listed. 21 of the 22 files with an error failed
during collection, so none of their tests ran. The other error was in fixture setup. pytest reports
an error only for collection, setup or teardown, never for the test call where the guard acts.

### Environment noise

These counts describe the machine, not the tests. They are kept apart from the results above.

- **WMI startup hangs:** 2 attempts in 2 files had a WMI query (`platform._wmi_query`) still
  running after 15 s. Each was killed and started again. Every retried file then completed.
- **Timeouts:** none. No file hit the 180 s limit.
- **Leftover processes:** none. No process was still running after its file finished.

### Worktree

- **Before the sweep:** `git status --porcelain -uall` printed nothing. The harness does not start
  on a dirty worktree.
- **After the sweep:** `git status --porcelain -uall` printed nothing.
- **Ignored files:** no new ignored files outside `__pycache__/`.
- **Changed by a test and reverted:** nothing. No test changed a tracked file or left an untracked
  one.

### By area

Each area groups `functional_tests` files by the first word of the file name, after any `test_`
prefix, and `ui_tests/` is one area. In the "Guard failures (files)" column, the number in
parentheses is how many files had a guard failure.

| Area | Files | Completed | Guard failures (files) | Other failures | Errors | Skipped | Passed |
|---|---:|---:|---:|---:|---:|---:|---:|
| `functional_tests/test_tabular*` | 22 | 22 | 17 (12) | 0 | 5 | 0 | 43 |
| `functional_tests/test_group*` | 17 | 17 | 20 (13) | 2 | 0 | 0 | 19 |
| `functional_tests/test_chat*` | 14 | 14 | 10 (5) | 0 | 0 | 0 | 53 |
| `functional_tests/test_enhanced*` | 14 | 14 | 16 (9) | 0 | 3 | 0 | 10 |
| `functional_tests/test_workflow*` | 14 | 14 | 42 (13) | 0 | 0 | 0 | 2 |
| `functional_tests/test_control*` | 13 | 13 | 14 (8) | 0 | 0 | 0 | 31 |
| `functional_tests/test_agent*` | 12 | 12 | 7 (3) | 0 | 0 | 0 | 50 |
| `functional_tests/test_workspace*` | 10 | 10 | 10 (4) | 0 | 0 | 0 | 14 |
| `functional_tests/test_document*` | 9 | 9 | 10 (7) | 0 | 0 | 0 | 8 |
| `functional_tests/test_backend*` | 8 | 8 | 16 (6) | 0 | 1 | 0 | 17 |
| `functional_tests/test_v2*` | 8 | 8 | 3 (3) | 0 | 0 | 0 | 67 |
| `ui_tests/` | 8 | 8 | 36 (8) | 0 | 0 | 0 | 8 |
| `functional_tests/test_public*` | 7 | 7 | 5 (5) | 0 | 1 | 0 | 1 |
| `functional_tests/test_custom*` | 6 | 6 | 7 (4) | 0 | 0 | 0 | 24 |
| `functional_tests/test_docs*` | 6 | 6 | 4 (2) | 0 | 0 | 0 | 23 |
| `functional_tests/test_orchestration*` | 5 | 5 | 1 (1) | 0 | 0 | 0 | 26 |
| `functional_tests/test_plugin*` | 5 | 5 | 2 (2) | 7 | 0 | 0 | 9 |
| `functional_tests/test_sql*` | 5 | 5 | 16 (4) | 0 | 0 | 0 | 10 |
| `functional_tests/test_swagger*` | 5 | 5 | 10 (5) | 4 | 0 | 0 | 4 |
| 101 other areas (fewer than 5 files each) | 139 | 139 | 197 (88) | 24 | 12 | 0 | 250 |
| **Total** | 327 | 327 | 443 (202) | 37 | 22 | 0 | 669 |

### Where the lists are

The per-file lists are in the description of pull request #1574.

## Impact

- Under pytest, a test that returns `False` now fails with a message that names it and refers to
  #1572. A guard failure means the test returned `False` under pytest in that environment, which
  pytest used to hide. It is not necessarily a product bug: many tests need Azure configuration, a
  running app, or setup that only their `__main__` runner does.
- The 8 `ui_tests/test_v2_orchestration_*` files that return `False` need `main()` to set up the
  page, so run them with `python <file>`. Converting them to pytest fixtures is follow-up work.
- Script runs, CI and the application are unchanged.

## Validation

- Before the guard, under pytest: `functional_tests/test_docs_link_integrity.py` 4 passed,
  `functional_tests/test_docs_release_notes_integrity.py` 1 passed, and
  `ui_tests/test_v2_orchestration_composer.py` 6 passed.
- After the guard: 3 failed and 1 passed, 1 failed, and 5 failed and 1 passed, each failure with
  the guard message. As scripts, the two docs files report 2/5 and 0/1, the same failures the guard
  now shows. `functional_tests/test_app_version_assertion_guardrails.py`, whose test returns `True`,
  passes before and after.
- The guard test passes 7/7 as a script and under pytest, each with and without `-O`.
- The sweep's split between guard failures and other failures was spot-checked with the guard
  turned off (`pytest --noconftest`). `test_personal_conversation_followup_authorization.py`
  reported 5 failed and 2 passed: the same 5 failures as in the sweep, and its guard-failed test
  passed. `quick_schema_test.py` failed collection with the same `TypeError` as in the sweep.

## Related

- #1572: pytest reports a test that returns `False` as passed.
- #1543: the Chat Orchestration Workflows roadmap, where the gap was found.
- `.github/instructions/location_of_functional_tests.instructions.md`, section "pytest
  return-False guard (#1572)".
