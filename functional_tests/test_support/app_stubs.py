# app_stubs.py
"""Import application modules in tests without standing up Azure clients.

``config.py`` builds a Cosmos client at import time, so any module that reaches
it transitively -- directly or through ``functions_settings`` and
``functions_activity_logging`` -- cannot be imported by a functional test on a
developer machine.

``test_terms_of_use.py`` solved this by installing stub modules in
``sys.modules`` before importing the module under test. This centralises that
approach so several tests can share it, and so the stub surface is described in
one place rather than drifting between copies.

Only the seams that keep a pure-logic module from importing are stubbed. A test
that needs real behaviour from one of these dependencies should not be using
this helper.
"""

import importlib
import sys
import types
from contextlib import contextmanager
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "application" / "single_app"

_MISSING = object()


def _build_stub_modules():
    """Return the stand-in modules that break the import chain to config.py."""
    activity_logging = types.ModuleType("functions_activity_logging")
    activity_logging.log_terms_of_use_accepted = lambda **payload: None
    activity_logging.log_terms_of_use_declined = lambda **payload: None
    activity_logging.log_general_admin_action = lambda **payload: None
    activity_logging.log_governance_change = lambda **payload: None
    activity_logging.log_web_search_consent_acceptance = lambda **payload: None

    appinsights = types.ModuleType("functions_appinsights")
    appinsights.log_event = lambda *args, **kwargs: None

    settings = types.ModuleType("functions_settings")
    settings.get_settings = lambda: {}
    settings.update_settings = lambda payload: True
    settings.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
    settings.update_user_settings = lambda user_id, payload: True
    settings.sanitize_settings_for_user = lambda values: dict(values or {})

    return {
        "functions_activity_logging": activity_logging,
        "functions_appinsights": appinsights,
        "functions_settings": settings,
    }


@contextmanager
def stubbed_app_imports():
    """Temporarily install the stub modules and put the app root on sys.path."""
    added_path = str(APP_ROOT) not in sys.path
    if added_path:
        sys.path.insert(0, str(APP_ROOT))

    stubs = _build_stub_modules()
    originals = {}
    for name, module in stubs.items():
        originals[name] = sys.modules.get(name, _MISSING)
        sys.modules[name] = module

    try:
        yield
    finally:
        for name, original in originals.items():
            if original is _MISSING:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = original


def import_app_module(module_name):
    """Import an application module with the Azure-dependent seams stubbed.

    The module is removed from ``sys.modules`` afterwards so a later import in
    the same process, made without stubs, is not served the stubbed copy.
    """
    with stubbed_app_imports():
        previously_loaded = module_name in sys.modules
        module = importlib.import_module(module_name)
        if not previously_loaded:
            sys.modules.pop(module_name, None)
        return module
