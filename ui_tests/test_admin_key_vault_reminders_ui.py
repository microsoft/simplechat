# test_admin_key_vault_reminders_ui.py
"""
UI test for Key Vault expiration reminder controls and external alert guidance.

Version: 0.250.123
Implemented in: 0.250.121; 0.250.122; 0.250.123

This test ensures the admin Key Vault reminder inventory and action-modal
reminder controls render with stable IDs, external alert guidance, optional
contact email telemetry controls, and safe local JavaScript wiring.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
ADMIN_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "admin_settings.html"
PLUGIN_MODAL_TEMPLATE = REPO_ROOT / "application" / "single_app" / "templates" / "_plugin_modal.html"
ADMIN_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "admin" / "admin_settings.js"
PLUGIN_MODAL_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "plugin_modal_stepper.js"


def _extract_function(source, function_name):
    start = source.index(f"function {function_name}")
    next_function = source.find("\nfunction ", start + 1)
    if next_function == -1:
        return source[start:]
    return source[start:next_function]


def test_admin_key_vault_reminder_dashboard_contract():
    """Validate admin inventory controls, endpoint wiring, and safe rendering."""
    template = ADMIN_TEMPLATE.read_text(encoding="utf-8")
    source = ADMIN_JS.read_text(encoding="utf-8")

    required_ids = [
        "enable_key_vault_secret_expiration_reminders",
        "key_vault_expiration_reminder_settings",
        "key_vault_secret_expiration_default_lead_days",
        "key_vault_secret_expiration_default_contact_email",
        "key_vault_secret_expiration_admin_roles",
        "key_vault_secret_expiration_scan_interval_seconds",
        "key_vault_secret_expiration_require_expiration",
        "key_vault_secret_expiration_emit_contact_email_in_telemetry",
        "key_vault_secret_expiration_emit_contact_email_in_telemetry_help",
        "key-vault-reminders-refresh",
        "key-vault-reminders-search",
        "key-vault-reminders-status",
        "key-vault-reminders-run",
        "key-vault-reminders-status-message",
        "key-vault-reminders-table-body",
        "key-vault-external-alert-guidance",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert "keyVaultSettings.style.display" not in source
    assert "keyVaultReminderSettings.classList.toggle('d-none'" in source
    assert "/api/admin/settings/key-vault/secret-reminders" in source
    assert "/api/admin/settings/key-vault/secret-reminders/run" in source
    assert "key_vault_secret_expiration_reminder_triggered" in template
    assert "customDimensions.sc_event_name" in template
    assert "customDimensions.sc_event_contact_email" in template
    assert "Azure Monitor scheduled query alert" in template
    assert "Reminder ID" in template
    assert "function renderKeyVaultReminderInventory" in source
    render_function = _extract_function(source, "renderKeyVaultReminderInventory")
    assert "textContent" in render_function
    assert "replaceChildren" in render_function
    assert "reminder.id" in render_function
    assert "innerHTML" not in render_function


def test_action_modal_key_vault_reminder_contract():
    """Validate action modal reminder controls and metadata payload wiring."""
    template = PLUGIN_MODAL_TEMPLATE.read_text(encoding="utf-8")
    source = PLUGIN_MODAL_JS.read_text(encoding="utf-8")

    required_ids = [
        "plugin-key-vault-reminder-enabled",
        "plugin-key-vault-reminder-fields",
        "plugin-key-vault-reminder-expires-on",
        "plugin-key-vault-reminder-email",
        "plugin-key-vault-reminder-lead-days",
        "plugin-key-vault-reminder-label",
        "plugin-key-vault-reminder-notes",
    ]
    for element_id in required_ids:
        assert f'id="{element_id}"' in template

    assert "KEY_VAULT_SECRET_REMINDERS_METADATA_FIELD = 'key_vault_secret_reminders'" in source
    assert "KEY_VAULT_SECRET_REMINDER_ALL_FIELDS = '__all__'" in source
    assert "toggleKeyVaultReminderFields" in source
    assert "populateKeyVaultReminderForm(plugin.metadata || {})" in source
    assert "validateKeyVaultReminderFields" in source
    assert "applyKeyVaultReminderMetadata(metadata)" in source
