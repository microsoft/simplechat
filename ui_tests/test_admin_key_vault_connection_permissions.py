# test_admin_key_vault_connection_permissions.py
"""
Classic/V2 Key Vault diagnostic workflows with Azure Playwright.
Version: 0.261.125
Implemented in: 0.261.125

Verify draft identity selection, busy states, actionable write/cleanup errors,
successful cleanup, and safe rendering without touching real Azure secrets.
"""

from pathlib import Path
import re
import sys

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from admin_diagnostics import ClassicAdminDiagnosticsFixture, SUCCESS, V2KeyVaultFixture
from playwright_connection import connect_options  # noqa: F401


pytestmark = pytest.mark.ui


@pytest.fixture(params=["classic", "v2"])
def vault_ui(page, request):
    fixture = ClassicAdminDiagnosticsFixture(page) if request.param == "classic" else V2KeyVaultFixture(page)
    fixture.interface = request.param
    yield fixture
    fixture.assert_clean()


def controls(fixture):
    page = fixture.page
    if fixture.interface == "classic":
        return (
            page.locator("#key_vault_name"), page.locator("#key_vault_identity"),
            page.locator("#test_key_vault_button"), page.locator("#test_key_vault_result"),
        )
    return (
        page.get_by_label("Key Vault Name", exact=True),
        page.get_by_label("Managed Identity Client ID", exact=True),
        page.get_by_role("button", name=re.compile(r"Test Key Vault connection|Testing")),
        page.get_by_role("status").filter(has_text="Key Vault"),
    )


def test_probe_uses_draft_values_and_waits_for_cleanup(vault_ui):
    vault_ui.hold_probe = True
    vault_ui.open()
    vault, identity, button, result = controls(vault_ui)
    vault.fill("draft-vault")
    identity.fill("11111111-2222-3333-4444-555555555555")
    button.click()
    expect(button).to_be_disabled()
    button.evaluate("(button) => button.click()")
    assert len(vault_ui.probe_calls) == 1
    assert vault_ui.probe_calls[0] == {
        "test_type": "key_vault", "vault_name": "draft-vault",
        "client_id": "11111111-2222-3333-4444-555555555555",
    }
    vault_ui.release_probe()
    expect(result).to_have_text(SUCCESS["message"])
    expect(button).to_be_enabled()
    assert vault_ui.patches == []


@pytest.mark.parametrize("stage", ["write", "cleanup"])
def test_denied_permissions_remain_visible_without_executing_markup(vault_ui, stage):
    message = f"Key Vault denied {stage} access. Grant the selected app identity Key Vault Secrets Officer on this vault."
    if stage == "cleanup":
        message += " Cleanup of temporary test secret 'simplechat-connection-test-owned' could not be confirmed."
    message += ' <img src=x onerror="window.untrustedExecuted=true">'
    vault_ui.probe_response = {"success": False, "error": message, "failed_stage": stage}
    vault_ui.probe_status = 400
    vault_ui.open()
    _, _, button, result = controls(vault_ui)
    button.click()
    expect(result).to_have_text(message)
    expect(button).to_be_enabled()
    expect(vault_ui.page.locator('img[src="x"]')).to_have_count(0)
    executed = vault_ui.page.evaluate("window.untrustedExecuted")
    assert executed is None
    assert vault_ui.patches == []


def test_classic_configuration_guide_explains_runtime_identity_and_probe(page):
    fixture = ClassicAdminDiagnosticsFixture(page)
    fixture.open()
    page.get_by_role("button", name="Configuration Guide", exact=True).click()
    guide = page.get_by_role("dialog")
    expect(guide).to_be_visible()
    expect(guide).to_contain_text("Key Vault Secrets Officer")
    expect(guide).to_contain_text("system-assigned identity")
    expect(guide).to_contain_text("soft-deleted metadata remains")
    fixture.assert_clean()
