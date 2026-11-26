# known_failures.py
"""Expect the failures listed in ``functional_tests/known_failures.txt``.

Version: 0.261.489
Implemented in: 0.261.489

Many functional tests fell behind the application before the suite was
normalized. Until each is fixed, the list keeps the suite usable: a run passes
when only listed tests fail, so a new failure stands out.

Each non-comment line of the list names one test or one test file, relative to
``functional_tests/``, followed by ``#`` and the reason::

    test_example.py::test_old_wording        # source text check out of date
    test_example.py::TestThing::test_case[a] # stub missing guard_model_callable
    test_hangs.py                            # whole file: hangs without Cosmos DB

- A listed test is marked ``xfail(strict=True)``. It is reported as ``xfailed``
  while it fails, and it fails the run once it passes, so the fixed test has to
  come off the list. The list can only shrink.
- A listed test with subtests counts as failing when the test or any of its
  subtests fails. Its failing subtests are reported as ``xfailed`` and its
  passing subtests as passed.
- A listed file (no ``::``) is not collected at all. Use this only for files
  that cannot be collected or that hang, since nothing in them runs.

Set ``SIMPLECHAT_IGNORE_KNOWN_FAILURES=1`` to run every test normally, for
example while fixing the listed ones.
"""

import os
from pathlib import Path

import pytest


LIST_FILE_NAME = "known_failures.txt"
IGNORE_ENV = "SIMPLECHAT_IGNORE_KNOWN_FAILURES"


def parse_known_failures(text):
    """Return ``({test_id: reason}, {file_name: reason})`` from the list's text."""
    tests, files = {}, {}
    for number, raw_line in enumerate(text.splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        entry, _, reason = line.partition("#")
        entry, reason = entry.strip(), reason.strip()
        if not reason:
            raise ValueError(f"{LIST_FILE_NAME} line {number}: '{entry}' needs a '# reason'.")
        target = tests if "::" in entry else files
        if entry in target:
            raise ValueError(f"{LIST_FILE_NAME} line {number}: '{entry}' is listed twice.")
        target[entry] = reason
    return tests, files


class KnownFailuresPlugin:
    """Pytest plugin applying one directory's known-failures list."""

    def __init__(self, test_dir):
        self.test_dir = Path(test_dir).resolve()
        list_path = self.test_dir / LIST_FILE_NAME
        text = list_path.read_text(encoding="utf-8") if list_path.is_file() else ""
        self.tests, self.files = parse_known_failures(text)
        self.skipped_files = []
        self.failed_subtests = set()

    def _relative(self, path):
        try:
            return Path(path).resolve().relative_to(self.test_dir).as_posix()
        except ValueError:
            return None

    def pytest_ignore_collect(self, collection_path, config):
        relative = self._relative(collection_path)
        if relative in self.files:
            self.skipped_files.append(relative)
            return True
        return None

    def pytest_collection_modifyitems(self, config, items):
        for item in items:
            relative = self._relative(item.path)
            if relative is None:
                continue
            test_id = relative + "::" + "::".join(item.nodeid.split("::")[1:])
            reason = self.tests.get(test_id)
            if reason:
                item.add_marker(pytest.mark.xfail(reason=f"known failure: {reason}", strict=True))

    @pytest.hookimpl(tryfirst=True)
    def pytest_runtest_logreport(self, report):
        """Judge a listed test with subtests as a whole, not subtest by subtest.

        pytest applies the xfail mark to each subtest on its own, so a passing
        subtest would fail the run as XPASS(strict), and so would the test
        itself once its failing subtests had been reported as xfailed.
        """
        if report.when != "call" or not _is_strict_xpass(report) and not hasattr(report, "wasxfail"):
            return
        if hasattr(report, "context"):  # a subtest report
            if hasattr(report, "wasxfail"):
                self.failed_subtests.add(report.nodeid)
            else:
                report.outcome, report.longrepr = "passed", None
        elif report.nodeid in self.failed_subtests and _is_strict_xpass(report):
            report.outcome = "skipped"
            report.wasxfail = report.longrepr[len(_XPASS_PREFIX):].strip()

    def pytest_terminal_summary(self, terminalreporter):
        if self.skipped_files:
            terminalreporter.write_line(
                f"known failures: {len(self.skipped_files)} listed file(s) not collected "
                f"(see functional_tests/{LIST_FILE_NAME}; set {IGNORE_ENV}=1 to run them)."
            )


_XPASS_PREFIX = "[XPASS(strict)]"


def _is_strict_xpass(report):
    return report.failed and isinstance(report.longrepr, str) and report.longrepr.startswith(_XPASS_PREFIX)


def register(config, test_dir):
    """Register the plugin for ``test_dir`` unless the ignore switch is set."""
    if os.environ.get(IGNORE_ENV, "").strip().lower() in ("1", "true", "yes"):
        return
    config.pluginmanager.register(KnownFailuresPlugin(test_dir), "simplechat-known-failures")
