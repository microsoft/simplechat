# live_services.py
"""Skip tests that need a live SimpleChat deployment when none is configured.

Version: 0.261.489
Implemented in: 0.261.489

Importing the real ``config.py`` (directly, through ``app``, or through any
module that reaches it) builds an Azure Cosmos DB client, and the Cosmos SDK
contacts the account while that client is constructed. On a machine with no
SimpleChat ``.env`` that import fails with ``TypeError: Unrecognized credential
type`` or a connection error, and pytest reports the whole file as a collection
error instead of saying what is missing.

Call :func:`require_live_cosmos` at the top of such a test file, before the
first application import::

    from test_support.live_services import require_live_cosmos

    require_live_cosmos(__file__)

    import app  # noqa: E402

Under pytest the file is skipped with a reason that names the missing setting.
Run as a script, the file prints the same reason and exits 0. Tests that only
need application logic should use ``test_support.app_stubs`` or
``test_support.offline_bootstrap`` instead, so they keep running everywhere.

Configuration is read the way ``config.py`` reads it: the process environment
first, then the dotenv file named by ``SIMPLECHAT_ENV_FILE``, then
``application/single_app/.env``. Set ``SIMPLECHAT_TESTS_OFFLINE=1`` to skip live
tests even when a deployment is configured.
"""

import os
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "application" / "single_app"
ENV_FILE_VARIABLE = "SIMPLECHAT_ENV_FILE"
OFFLINE_VARIABLE = "SIMPLECHAT_TESTS_OFFLINE"


def _truthy(value):
    return str(value or "").strip().lower() in ("1", "true", "yes", "on")


def _dotenv_values():
    """Return the values of the dotenv file config.py would load, or an empty dict."""
    selected = os.getenv(ENV_FILE_VARIABLE)
    candidate = Path(selected) if selected else APP_ROOT / ".env"
    if not candidate.is_absolute():
        candidate = (APP_ROOT / candidate).resolve()
    if not candidate.is_file():
        return {}
    try:
        from dotenv import dotenv_values
    except ImportError:
        return {}
    return {key: value for key, value in dotenv_values(candidate).items() if value is not None}


def _setting(name, dotenv):
    return os.getenv(name) or dotenv.get(name) or ""


def missing_live_cosmos_settings():
    """Return a human-readable reason live Cosmos DB is unavailable, or '' when it is configured."""
    if _truthy(os.getenv(OFFLINE_VARIABLE)):
        return f"{OFFLINE_VARIABLE} is set"

    dotenv = _dotenv_values()
    endpoint = _setting("AZURE_COSMOS_ENDPOINT", dotenv)
    if not endpoint:
        return "AZURE_COSMOS_ENDPOINT is not set in the environment or the SimpleChat .env file"

    auth_type = (_setting("AZURE_COSMOS_AUTHENTICATION_TYPE", dotenv) or "key").strip().lower()
    if auth_type != "managed_identity" and not _setting("AZURE_COSMOS_KEY", dotenv):
        return "AZURE_COSMOS_KEY is not set and AZURE_COSMOS_AUTHENTICATION_TYPE is not managed_identity"
    return ""


def require_live_cosmos(test_file=None):
    """Skip the calling test module unless a live Cosmos DB account is configured."""
    reason = missing_live_cosmos_settings()
    if not reason:
        return

    name = Path(test_file).name if test_file else "this test"
    message = f"{name} needs a live SimpleChat Cosmos DB account: {reason}."

    if not _running_as_script(test_file):
        import pytest

        pytest.skip(message, allow_module_level=True)

    print(f"SKIPPED: {message}")
    raise SystemExit(0)


def _running_as_script(test_file):
    """Return True when the test file itself is the program being run (python test_x.py)."""
    main_file = getattr(sys.modules.get("__main__"), "__file__", None)
    if not test_file or not main_file:
        return False
    return Path(main_file).resolve() == Path(test_file).resolve()
