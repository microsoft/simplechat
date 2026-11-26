# module_isolation.py
"""Keep one test file's ``sys.modules`` stubs from leaking into the next file.

Version: 0.261.489
Implemented in: 0.261.489

Many functional tests install stand-in modules in ``sys.modules`` at import
time (``functions_appinsights``, ``semantic_kernel.connectors.mcp``,
``functions_authentication`` and similar) so that a pure-logic module can be
imported without Azure clients. Run on its own, each of those files passes.
Run as one suite, pytest imports every file during collection, so a stub left
behind by one file is what the next file imports, and that file then fails
with errors such as ``cannot import name 'workflow_log_context' from
'functions_appinsights' (unknown location)``.

This plugin gives every test file the ``sys.modules`` view it would have had if
it were run alone:

* Collection. Around each test file's import, record which ``sys.modules``
  entries the file added or replaced. If any of them is a stub (a module that
  was not loaded from a file, or a replaced real module), the file is marked as
  "stubbing": the stubs it added are taken back out, the entries it replaced
  get their originals back, and repository modules (application and test
  helper code) it imported are taken out too, because they bound the stubs
  when they ran. Third-party packages it imported for real stay cached;
  removing them breaks packages such as pydantic that look up their own
  submodules in sys.modules.
* Run. Before the first test of a stubbing file, its own entries are put back.
  They stay in place for all of that file's tests, so module-scoped fixtures
  that install or import modules keep working, and after the file's last test
  the same rules take back what the file's tests added or replaced.

Files that install no stubs are untouched, so most of the suite runs exactly as
before. The plugin is loaded from functional_tests/conftest.py and
ui_tests/conftest.py. Set ``SIMPLECHAT_TEST_MODULE_ISOLATION=0`` to turn it off
while investigating an ordering problem.
"""

import os
import sys
import types
from functools import lru_cache

import pytest


_ENABLED = os.getenv("SIMPLECHAT_TEST_MODULE_ISOLATION", "1").strip().lower() not in ("0", "false", "no", "off")

# Normalized path of a stubbing test file -> {module name: module object} for the
# sys.modules entries that file added or replaced while it was imported.
_OWNED = {}

# (normalized path, sys.modules snapshot) for the stubbing file whose tests are running.
_ACTIVE = None

_REPO_ROOT = os.path.normcase(os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
_APP_ROOT = os.path.join(_REPO_ROOT, "application", "single_app")
_FUNCTIONAL_TESTS = os.path.join(_REPO_ROOT, "functional_tests")
_UI_TESTS = os.path.join(_REPO_ROOT, "ui_tests")
_THIRD_PARTY_MARKERS = tuple(
    os.path.normcase(os.sep + part + os.sep) for part in ("site-packages", "node_modules", ".venv", "venv")
)


# Third-party packages that functional tests replace with stand-ins. Real modules
# from these packages are never treated as stubs; only hand-built ones are.
_STUBBED_THIRD_PARTY_PACKAGES = frozenset({"azure", "olefile", "pandas", "semantic_kernel", "yamcs"})


@lru_cache(maxsize=None)
def _repo_top_level_names():
    """Top-level module and package names that this repository's own code provides."""
    names = set()
    for directory in (_APP_ROOT, _FUNCTIONAL_TESTS, _UI_TESTS):
        if not os.path.isdir(directory):
            continue
        for entry in os.listdir(directory):
            stem, extension = os.path.splitext(entry)
            if extension == ".py" or os.path.isdir(os.path.join(directory, entry)):
                names.add(stem if extension == ".py" else entry)
    return frozenset(names)


def _is_stub(name, module):
    """Return True when a sys.modules value is a test stand-in rather than an imported module.

    Extension modules register helper entries with no spec or file of their own
    (``swig_runtime_data4`` for PyMuPDF, ``_cython_*`` and ``cython_runtime`` for
    Cython builds, ``typing.io``). Those are not stubs and must never be removed:
    taking ``swig_runtime_data4`` out of sys.modules corrupts PyMuPDF's SWIG type
    table and crashes the interpreter in the next ``fitz.Font()`` call. So a
    hand-built module only counts as a stub when its name belongs to this
    repository or to a third-party package the tests are known to stub.
    """
    if module is None or not isinstance(module, types.ModuleType):
        # MagicMock, SimpleNamespace and other stand-ins.
        return True
    if getattr(module, "__spec__", None) is not None or getattr(module, "__file__", None):
        return False
    top_level = name.split(".", 1)[0]
    return top_level in _repo_top_level_names() or top_level in _STUBBED_THIRD_PARTY_PACKAGES


def _is_repo_module(module):
    """Return True for a real module loaded from this repository's own source."""
    module_file = getattr(module, "__file__", None)
    if not module_file:
        return False
    module_file = os.path.normcase(os.path.abspath(module_file))
    if not module_file.startswith(_REPO_ROOT + os.sep):
        return False
    return not any(marker in module_file for marker in _THIRD_PARTY_MARKERS)


def _take_back(added):
    """Return the added entries that must not outlive the file or test that added them."""
    return {name: module for name, module in added.items() if _is_stub(name, module) or _is_repo_module(module)}


def _snapshot():
    return dict(sys.modules)


def _diff(before, after):
    """Return (added, replaced) for two sys.modules snapshots."""
    added = {name: module for name, module in after.items() if name not in before}
    replaced = {
        name: module
        for name, module in after.items()
        if name in before and before[name] is not module
    }
    return added, replaced


def _restore(before, added, replaced):
    for name in _take_back(added):
        sys.modules.pop(name, None)
    for name in replaced:
        sys.modules[name] = before[name]


def _normalized(path):
    return os.path.normcase(os.path.abspath(str(path))) if path is not None else None


@pytest.hookimpl(wrapper=True)
def pytest_make_collect_report(collector):
    """Import each test file, then take back any stubs it left in sys.modules."""
    if not _ENABLED or not isinstance(collector, pytest.Module):
        return (yield)

    before = _snapshot()
    report = yield
    added, replaced = _diff(before, _snapshot())

    stubbing = bool(replaced) or any(_is_stub(name, module) for name, module in added.items())
    if stubbing:
        _OWNED[_normalized(getattr(collector, "path", None))] = {**_take_back(added), **replaced}
        _restore(before, added, replaced)
    return report


def _leave_active_file():
    global _ACTIVE
    if _ACTIVE is not None:
        before = _ACTIVE[1]
        _ACTIVE = None
        added, replaced = _diff(before, _snapshot())
        _restore(before, added, replaced)


@pytest.hookimpl(wrapper=True)
def pytest_runtest_protocol(item, nextitem):
    """Run a stubbing file's tests with that file's entries, restoring after its last test."""
    global _ACTIVE
    path = _normalized(getattr(item, "path", None))
    if _ACTIVE is not None and _ACTIVE[0] != path:
        _leave_active_file()
    owned = _OWNED.get(path)
    if owned is None:
        return (yield)

    if _ACTIVE is None:
        _ACTIVE = (path, _snapshot())
        sys.modules.update(owned)
    try:
        return (yield)
    finally:
        # Module-scoped fixtures are torn down during the file's last test, so the
        # file's entries are taken back only once nothing of the file is left to run.
        if nextitem is None or _normalized(getattr(nextitem, "path", None)) != path:
            _leave_active_file()
