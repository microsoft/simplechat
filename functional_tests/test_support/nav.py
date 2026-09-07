# nav.py
"""Access to the Admin Settings navigation map from functional tests.

``admin_settings_nav`` lives in ``application/single_app``, which is not on the
test path by default. Centralising the import here keeps individual tests from
each manipulating ``sys.path``, and gives them one place to read navigation
structure from.
"""

import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
APP_ROOT = REPO_ROOT / "application" / "single_app"

if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

from admin_settings_nav import (  # noqa: E402
    ADMIN_NAV,
    get_group_for_tab,
    get_section_ids,
    get_tab_ids,
    iter_tabs,
)

__all__ = [
    "ADMIN_NAV",
    "get_group_for_tab",
    "get_section_ids",
    "get_tab_ids",
    "iter_tabs",
]
