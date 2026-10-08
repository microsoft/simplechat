#!/usr/bin/env python3
# test_safety_escalate_removal.py
"""
Functional test for removing Escalate as a safety action.
Version: 0.261.296
Implemented in: 0.261.296

This test ensures that Escalate can no longer be chosen in either interface or set through
the API, while records that already carry it stay editable, are labelled
"Escalated (legacy)", and are still counted in the escalate_count statistic. Real modules run
in fresh processes with network access blocked, under normal and optimized Python.
"""

import re
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
V2_SRC = ROOT / "application" / "v2_ui" / "src"
sys.path.insert(0, str(ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

LEGACY_LABEL = "Escalated (legacy)"


ESCALATE_PROBE = r'''
import importlib
import sys
from contextlib import ExitStack
from pathlib import Path

root = Path(sys.argv[1])
sys.path.insert(0, str(root / "functional_tests"))
sys.path.insert(0, str(root / "application" / "single_app"))
from test_support.offline_bootstrap import offline_app_imports
from test_support.safety_review_harness import build_safety_app, check, sign_in

with offline_app_imports(), ExitStack() as stack:
    importlib.import_module(sys.argv[2])
    h = build_safety_app(stack)
    client, container = h.client, h.container
    base = {"user_id": "user-1", "status": "New", "created_at": "2026-10-01T00:00:00", "message": "Flagged"}
    container.seed({**base, "id": "log-none", "action": "None"})
    container.seed({**base, "id": "log-escalated", "action": "Escalate"})
    sign_in(client, "reviewer-1", roles=("Admin",))

    response = client.patch("/api/safety/logs/log-none", json={"status": "In-Review", "action": "Escalate"})
    body = response.get_json()
    check(response.status_code == 400 and "Escalate is no longer available" in body["error"], str(body))
    check(container.items["log-none"]["action"] == "None" and container.items["log-none"]["status"] == "New",
          "A refused Escalate still changed the record")

    response = client.patch("/api/safety/logs/log-escalated", json={
        "status": "Resolved", "action": "Escalate", "notes": "Closed out.",
    })
    check(response.status_code == 200, f"A legacy record could not be edited: {response.get_json()}")
    stored = container.items["log-escalated"]
    check(stored["action"] == "Escalate" and stored["status"] == "Resolved" and stored["notes"] == "Closed out.", str(stored))
    check(h.notifications == [] and h.approvals == [], "Escalate did something")

    stats = client.get("/api/safety/logs/stats").get_json()
    check(stats["escalate_count"] == 1 and stats["block_user_count"] == 0, str(stats))

    # Moving a legacy record off Escalate is allowed; it can't be set back afterwards.
    check(client.patch("/api/safety/logs/log-escalated", json={"action": "None"}).status_code == 200, "move off")
    response = client.patch("/api/safety/logs/log-escalated", json={"action": "Escalate"})
    check(response.status_code == 400, "Escalate could be set again")
    check(client.get("/api/safety/logs/stats").get_json()["escalate_count"] == 0, "stale escalate_count")

    response = client.patch("/api/safety/logs/log-none", json={"action": "Bogus"})
    check(response.status_code == 400 and response.get_json()["error"] == "Invalid safety action", "unknown action")

print("PASS: Escalate removed, legacy records kept")
'''


@pytest.mark.parametrize("optimized", [False, True])
def test_real_escalate_rules(optimized):
    command = [sys.executable, "-B"]
    if optimized:
        command.append("-O")
    result = subprocess.run(
        command + ["-c", ESCALATE_PROBE, str(ROOT), "route_backend_safety"],
        capture_output=True,
        text=True,
        timeout=180,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS: Escalate removed, legacy records kept" in result.stdout


def _actions_constant(source):
    match = re.search(r"const ACTIONS = \[([^\]]*)\];", source)
    assert match, "ACTIONS constant not found"
    return match.group(1)


def test_v2_pages_no_longer_offer_escalate():
    admin_page = (V2_SRC / "pages" / "AdminSafetyViolationsPage.tsx").read_text(encoding="utf-8")
    violations = (V2_SRC / "components" / "settings" / "ViolationsTab.tsx").read_text(encoding="utf-8")
    for source in (admin_page, violations):
        assert "Escalate" not in _actions_constant(source)
        assert LEGACY_LABEL in source
    # Only a record that already carries Escalate offers it again, as its legacy label.
    assert "selected.action === LEGACY_ESCALATE_ACTION ? [...ACTIONS, LEGACY_ESCALATE_ACTION] : ACTIONS" in admin_page
    assert "Escalated or blocked" not in admin_page
    assert "label={(stats?.escalate_count ?? 0) > 0" in admin_page


def test_classic_pages_no_longer_offer_escalate():
    for template in ("admin_safety_violations.html", "my_safety_violations.html", "profile.html"):
        source = (APP_DIR / "templates" / template).read_text(encoding="utf-8")
        assert '<option value="Escalate">' not in source, template
    admin_template = (APP_DIR / "templates" / "admin_safety_violations.html").read_text(encoding="utf-8")
    assert 'id="safetyBlockedCount"' in admin_template and 'id="safetyStatsLegacyEscalateRow"' in admin_template
    assert 'id="safetyEscalatedCount"' not in admin_template

    admin_script = (APP_DIR / "static" / "js" / "admin" / "admin-safety-violations.js").read_text(encoding="utf-8")
    assert "Escalate: 'Escalated (legacy)'" in admin_script
    assert "function syncLegacyEscalateOption(selectElement, logItem)" in admin_script
    for path in (
        APP_DIR / "templates" / "my_safety_violations.html",
        APP_DIR / "static" / "js" / "profile" / "profile-tabs.js",
    ):
        assert LEGACY_LABEL in path.read_text(encoding="utf-8"), path.name


def test_backend_keeps_the_legacy_action_and_statistic():
    source = (APP_DIR / "route_backend_safety.py").read_text(encoding="utf-8")
    assert "SELECTABLE_SAFETY_ACTIONS = {'None', 'WarnUser', 'SuspendUser', 'BlockUser'}" in source
    assert "ALLOWED_SAFETY_ACTIONS = SELECTABLE_SAFETY_ACTIONS | {SAFETY_ACTION_ESCALATE_LEGACY}" in source
    assert '"escalate_count": 0,' in source


def test_version():
    assert_app_version_at_least("0.261.296")


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
