# conftest.py
"""
Shared pytest configuration for this test directory.

Version: 0.261.203
Implemented in: 0.261.203 (issue #1572)

The code between the "pytest return-False guard (#1572)" markers below fails a
pytest test whose function returns False. The same guard block lives in
functional_tests/conftest.py and ui_tests/conftest.py. Keep the guard blocks
identical and put anything specific to one directory outside the block;
functional_tests/test_pytest_return_false_guard.py checks the blocks and runs
the guard in a subprocess.
"""

# --- begin pytest return-False guard (#1572) ---
import functools
import inspect

import pytest


def _is_async_test(function):
    """Mirror pytest's own check for coroutine and async generator test functions."""
    return (
        inspect.iscoroutinefunction(function)
        or getattr(function, "_is_coroutine", False)
        or inspect.isasyncgenfunction(function)
    )


@pytest.hookimpl(wrapper=True, tryfirst=True)
def pytest_pyfunc_call(pyfuncitem):
    """
    Run the test through a recorder and fail it if the test function returned False.

    Many SimpleChat functional and UI tests follow the repository's script
    template: each test_* function returns True or False and a __main__ runner
    turns the results into an exit code. pytest ignores a test's return value
    and only emits PytestReturnNotNoneWarning, so under pytest a test that
    returned False used to be reported as passed.

    Only a return value that "is False" fails. True, None and every other value
    keep pytest's normal behavior, including its warning for non-None returns.

    Scope and limits:

    * Module-level test functions and Test* class methods are guarded,
      including parametrized and fixture-using tests. unittest.TestCase methods
      never go through pytest_pyfunc_call, so they are not guarded.
    * async def tests and async generators are left to pytest or an async
      plugin. They produce a coroutine or async generator, never False, and
      pytest already fails unmarked ones. A plugin that runs an async test (for
      example pytest-asyncio) discards its return value, so it cannot be
      checked here.
    * Running a file as a script (python test_x.py) does not load this file
      unless the script's __main__ calls pytest.main().
    * Nothing changes at collection time and no module state is touched. The
      test function is swapped for a recording wrapper only for the duration of
      the call and is always restored. pytest --noconftest disables the guard.
    * tryfirst=True installs the recorder before any other pytest_pyfunc_call
      wrapper, so it ends up innermost, next to the real function. A wrapper
      that discards the return value, such as pytest --trace, therefore cannot
      hide it.
    """
    original = pyfuncitem.obj
    if _is_async_test(original):
        return (yield)

    returned_values = []

    @functools.wraps(original)
    def record_return_value(*args, **kwargs):
        value = original(*args, **kwargs)
        returned_values.append(value)
        return value

    pyfuncitem.obj = record_return_value
    try:
        result = yield
    finally:
        pyfuncitem.obj = original

    if any(value is False for value in returned_values):
        pytest.fail(
            f"{pyfuncitem.nodeid} returned False. Under pytest a test that returns False "
            "now fails (#1572); pytest itself ignores return values, so this test used to "
            "be reported as passed. The test's captured stdout, printed after this message, "
            "usually says why it returned False. Check with assert, or raise AssertionError "
            "where the check must survive python -O, and keep return True/False for the "
            "__main__ runner only.",
            pytrace=False,
        )
    return result
# --- end pytest return-False guard (#1572) ---


import os  # noqa: E402
import sys  # noqa: E402


# Let a test file import application modules and test_support when it is run alone.
# Appended, so a path a test file inserts itself still wins. Before 0.261.491 many
# files only imported because an earlier file had added the application folder.
for _path in (
    os.path.dirname(os.path.abspath(__file__)),
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "application", "single_app"),
):
    _path = os.path.abspath(_path)
    if os.path.isdir(_path) and _path not in sys.path:
        sys.path.append(_path)


# Per-test-file sys.modules isolation, so stub modules one file installs at import
# time cannot leak into the files collected after it. See
# test_support/module_isolation.py; set SIMPLECHAT_TEST_MODULE_ISOLATION=0 to disable.
try:
    from test_support.module_isolation import (  # noqa: E402,F401
        pytest_make_collect_report,
        pytest_runtest_protocol,
    )
except ModuleNotFoundError as _error:
    # This conftest copied outside the repository (the return-False guard's own
    # tests do that) runs without the isolation plugin.
    if _error.name not in ("test_support", "test_support.module_isolation"):
        raise


# With no Cosmos DB account configured, let tests import the real config.py against an
# in-memory Cosmos client. See test_support/offline_cosmos.py.
try:
    from test_support.offline_cosmos import install_offline_cosmos  # noqa: E402
except ModuleNotFoundError as _error:
    if _error.name not in ("test_support", "test_support.offline_cosmos"):
        raise
else:
    install_offline_cosmos()


# Tests listed in known_failures.txt are expected to fail until they are fixed; a
# listed test that passes fails the run so it comes off the list. See
# test_support/known_failures.py; set SIMPLECHAT_IGNORE_KNOWN_FAILURES=1 to disable.
def pytest_configure(config):
    try:
        from test_support.known_failures import register
    except ModuleNotFoundError as error:
        if error.name not in ("test_support", "test_support.known_failures"):
            raise
        return
    register(config, os.path.dirname(os.path.abspath(__file__)))
