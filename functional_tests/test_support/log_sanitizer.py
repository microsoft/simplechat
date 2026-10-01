# log_sanitizer.py
"""The application's ``sanitize_log_message`` for closed-namespace harnesses.

Version: 0.261.216
Implemented in: 0.261.216

Harnesses that execute route or cache functions in a namespace they build must supply
every name those functions use. ``real_sanitize_log_message`` runs
``sanitize_log_message`` and the constants it reads unchanged from
``functions_appinsights.py``, so a harness gets the real line-break removal, secret
masking and truncation without importing Azure Monitor or the settings cache.
"""

import re
from typing import Any

from test_support.app_source import run_definitions


SANITIZE_LOG_MESSAGE_DEFINITIONS = {
    "REDACTED_LOG_VALUE",
    "MAX_LOG_STRING_LENGTH",
    "SECRET_ASSIGNMENT_RE",
    "AUTHORIZATION_VALUE_RE",
    "LOG_CONTROL_CHAR_RE",
    "sanitize_log_message",
}


def real_sanitize_log_message():
    """``sanitize_log_message`` executed from ``functions_appinsights.py``."""
    namespace = run_definitions(
        "functions_appinsights.py",
        SANITIZE_LOG_MESSAGE_DEFINITIONS,
        {"re": re, "Any": Any},
    )
    return namespace["sanitize_log_message"]
