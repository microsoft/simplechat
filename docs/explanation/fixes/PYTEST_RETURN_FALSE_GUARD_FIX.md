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
  them.
- `tryfirst` keeps the recorder innermost. Without it, `pytest --trace` wraps the test function
  first and discards the return value, and the test passes again.
- The block adds no collection hooks and does not touch `sys.modules`, `sys.path` or any other
  global state. `--noconftest` turns it off.

### Where the guard lives

- `functional_tests/` holds the template-style tests. `ui_tests/` needs the guard too: 44 tests in
  8 `ui_tests/test_v2_orchestration_*.py` files return `False`. Their page tests depend on `main()`
  setting `_PAGE`. Under pytest such a test hits its `except` branch and returns `False`, and was
  reported as passed.
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

Running. The counts, the method and a breakdown by area will be added to this section in a
follow-up commit on this branch.

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

## Related

- #1572: pytest reports a test that returns `False` as passed.
- #1543: the Chat Orchestration Workflows roadmap, where the gap was found.
- `.github/instructions/location_of_functional_tests.instructions.md`, section "pytest
  return-False guard (#1572)".
