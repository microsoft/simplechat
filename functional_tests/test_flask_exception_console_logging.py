#!/usr/bin/env python3
# test_flask_exception_console_logging.py
"""
Functional test for unhandled exception tracebacks reaching the console.
Version: 0.260.019
Implemented in: 0.260.019

When configure_azure_monitor() runs it attaches a handler to the root logger.
That has two side effects the application depends on being corrected:

  1. logging.basicConfig() becomes a no-op, because it returns early whenever
     root already has handlers.
  2. Flask's create_logger() calls has_level_handler(), finds that root handler,
     and therefore skips attaching its own stderr handler.

The result is that app.logger.exception("Exception on /path [GET]") is delivered
to Application Insights and nowhere else, so an App Service container log shows
only the access-log line for a 500. Diagnosing the Admin Settings 500 required an
Application Insights query for exactly this reason.

These tests pin the correction: ensure_console_error_logging() puts a stderr
handler back, without stacking duplicates and without touching the root logger.
"""

import io
import logging
import sys
from contextlib import redirect_stderr
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from functions_appinsights import (  # noqa: E402  (path setup must precede this import)
    CONSOLE_ERROR_HANDLER_ATTRIBUTE,
    ensure_console_error_logging,
)

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _make_logger(name):
    """Return a clean, isolated logger for a single assertion."""
    logger = logging.getLogger(name)
    logger.handlers.clear()
    logger.setLevel(logging.NOTSET)
    logger.propagate = False
    return logger


def test_root_handler_suppresses_the_flask_default_handler():
    """Document the upstream behaviour that makes the helper necessary."""
    print("Testing that a root handler suppresses Flask's stderr handler...")

    def has_level_handler(logger):
        """Mirror of flask.logging.has_level_handler."""
        level = logger.getEffectiveLevel()
        current = logger
        while current:
            for handler in current.handlers:
                if handler.level <= level:
                    return True
            if not current.propagate:
                break
            current = current.parent
        return False

    probe_logger = logging.getLogger("simplechat_test_probe")
    probe_logger.handlers.clear()
    probe_logger.setLevel(logging.NOTSET)
    probe_logger.propagate = True

    root_logger = logging.getLogger()
    original_handlers = list(root_logger.handlers)
    original_level = root_logger.level
    try:
        root_logger.handlers.clear()
        root_logger.setLevel(logging.WARNING)
        assert not has_level_handler(probe_logger), (
            "Expected no level handler before the Azure Monitor handler is added."
        )

        # Stand in for the handler configure_azure_monitor attaches to root.
        azure_monitor_handler = logging.NullHandler()
        azure_monitor_handler.setLevel(logging.INFO)
        root_logger.addHandler(azure_monitor_handler)

        assert has_level_handler(probe_logger), (
            "A root handler should satisfy has_level_handler, which is why Flask "
            "stops attaching its own stderr handler."
        )
    finally:
        root_logger.handlers.clear()
        for handler in original_handlers:
            root_logger.addHandler(handler)
        root_logger.setLevel(original_level)
        probe_logger.propagate = False

    print("Confirmed a root handler suppresses Flask's stderr default handler.")


def test_console_handler_emits_tracebacks_to_stderr():
    """An unhandled request exception has to be readable in the container log."""
    print("Testing that unhandled exception tracebacks reach stderr...")

    logger = _make_logger("simplechat_test_console_traceback")
    ensure_console_error_logging(logger)

    captured_stderr = io.StringIO()
    with redirect_stderr(captured_stderr):
        for handler in logger.handlers:
            if getattr(handler, CONSOLE_ERROR_HANDLER_ATTRIBUTE, False):
                handler.stream = captured_stderr
        try:
            raise ValueError("simulated admin settings render failure")
        except ValueError:
            logger.exception("Exception on /admin/settings [GET]")

    console_output = captured_stderr.getvalue()
    assert "Exception on /admin/settings [GET]" in console_output, (
        f"Log message missing from stderr output: {console_output!r}"
    )
    assert "Traceback (most recent call last)" in console_output, (
        f"Traceback missing from stderr output: {console_output!r}"
    )
    assert "simulated admin settings render failure" in console_output, (
        f"Exception detail missing from stderr output: {console_output!r}"
    )

    print("Tracebacks are written to stderr.")


def test_console_handler_is_attached_only_once():
    """Worker reloads and repeated init must not stack duplicate handlers."""
    print("Testing that the console handler is not attached twice...")

    logger = _make_logger("simplechat_test_console_once")
    first_handler = ensure_console_error_logging(logger)
    second_handler = ensure_console_error_logging(logger)

    assert first_handler is second_handler, (
        "A second call should return the existing handler, not create a new one."
    )

    console_handlers = [
        handler for handler in logger.handlers
        if getattr(handler, CONSOLE_ERROR_HANDLER_ATTRIBUTE, False)
    ]
    assert len(console_handlers) == 1, (
        f"Expected exactly one console handler, found {len(console_handlers)}."
    )

    print("Console handler is attached exactly once.")


def test_console_handler_does_not_lower_the_root_logger():
    """The handler is scoped to the app logger so libraries cannot flood stderr."""
    print("Testing that the console handler leaves the root logger alone...")

    root_logger = logging.getLogger()
    handlers_before = list(root_logger.handlers)

    logger = _make_logger("simplechat_test_console_scope")
    handler = ensure_console_error_logging(logger)

    assert list(root_logger.handlers) == handlers_before, (
        "ensure_console_error_logging must not modify the root logger's handlers."
    )
    assert handler.level == logging.ERROR, (
        f"Console handler should be pinned at ERROR, found {handler.level}."
    )
    assert logger.getEffectiveLevel() <= logging.ERROR, (
        "The logger must be low enough to emit ERROR records."
    )

    print("Console handler is scoped to the application logger at ERROR.")


if __name__ == "__main__":
    assert_app_version_at_least(
        "0.260.019",
        reason="Console error logging restored for unhandled exceptions.",
    )

    tests = [
        test_root_handler_suppresses_the_flask_default_handler,
        test_console_handler_emits_tracebacks_to_stderr,
        test_console_handler_is_attached_only_once,
        test_console_handler_does_not_lower_the_root_logger,
    ]

    results = []
    for test in tests:
        try:
            test()
            results.append(True)
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} passed")
    sys.exit(0 if all(results) else 1)
