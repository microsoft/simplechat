# test_v2_sql_connection_diagnostic_reference.py
"""
SQL connection failures show only the safe correlation reference in the real V2 SPA.
Version: 0.261.355
Implemented in: 0.261.355

Uses the existing Azure Playwright connection/local fallback and closed HTTP fixture.
No database, model, or external action is invoked.
"""

from pathlib import Path
import sys

import pytest
from playwright.sync_api import expect

# The shared fixture imports its existing helpers by their fixture-directory names.
sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))
from ui_tests.fixtures.workspace_authoring import (
    ACTION_ID, connect_options, workspace_ui,  # noqa: F401
)


@pytest.mark.ui
@pytest.mark.parametrize("width", [390, 1440])
def test_sql_failure_reference_is_visible_without_provider_diagnostics(workspace_ui, width):
    ui, page = workspace_ui, workspace_ui.page
    ui.actions[ACTION_ID].update({
        "type": "sql_query",
        "auth": {"type": "identity", "identity": "managed_identity"},
        "additionalFields": {
            "database_type": "azure_sql", "server": "db.example.test", "database": "test-db",
            "auth_type": "managed_identity", "read_only": True,
        },
    })
    ui.secret_paths[ACTION_ID] = []
    reference = "ca1a790dfb984a5da089cd5b453921c6"
    message = "SQL authentication was rejected. Verify the selected authentication settings and database access."
    ui.reject_next(
        "POST", "/api/plugins/test-sql-connection", status=400, error=message,
        success=False, error_code="sql_authentication_failed",
        details={"diagnostic_reference": reference},
    )
    ui.open(f"/workspace/actions/{ACTION_ID}", width=width)
    sections = page.get_by_role("combobox", name="Jump to section")
    if width < 1024:
        sections.select_option(label="Authentication")
    else:
        page.get_by_role("navigation", name="Editor sections").get_by_role(
            "button", name="Authentication", exact=True,
        ).click()
    page.get_by_role("button", name="Test connection", exact=True).click()
    feedback = page.get_by_role("alert").filter(has_text=message)
    expect(feedback).to_be_visible()
    expect(feedback.get_by_text("diagnostic reference:", exact=True)).to_be_visible()
    expect(feedback.get_by_text(reference, exact=True)).to_be_visible()
    for private_detail in ["28000", "18456", "InterfaceError", "IDENTITY_HEADER", "SQLDriverConnect"]:
        assert private_detail not in feedback.inner_text()
    assert len(ui.editor_writes) == 0
    ui.assert_no_overflow()
