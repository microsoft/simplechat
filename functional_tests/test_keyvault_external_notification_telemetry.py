#!/usr/bin/env python3
# test_keyvault_external_notification_telemetry.py
"""
Functional test for Key Vault expiration reminder external telemetry.
Version: 0.250.123
Implemented in: 0.250.122; 0.250.123

This test ensures Key Vault expiration reminder notifications emit a safe,
queryable Azure Monitor event and include contact email only when admins opt in.
"""

import importlib
import os
import sys
import types


sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


class FakeCosmosResourceNotFoundError(Exception):
    pass


class FakeReminderContainer:
    def __init__(self, items=None):
        self.items = {
            item["id"]: dict(item)
            for item in (items or [])
        }
        self.upserted_items = []

    def read_item(self, item, partition_key):
        stored_item = self.items.get(item)
        if not stored_item or stored_item.get("scope_key") != partition_key:
            raise FakeCosmosResourceNotFoundError("not found")
        return dict(stored_item)

    def query_items(self, query=None, parameters=None, enable_cross_partition_query=False):
        return [dict(item) for item in self.items.values()]

    def upsert_item(self, body):
        self.items[body["id"]] = dict(body)
        self.upserted_items.append(dict(body))
        return dict(body)


class FakeLogger:
    def __init__(self):
        self.records = []

    def log(self, level, message, extra=None, stacklevel=None):
        self.records.append({
            "level": level,
            "message": message,
            "extra": dict(extra or {}),
            "stacklevel": stacklevel,
        })


def _restore_modules(original_modules):
    for module_name, original_module in original_modules.items():
        if original_module is None:
            sys.modules.pop(module_name, None)
        else:
            sys.modules[module_name] = original_module


def _load_appinsights_module(fake_logger):
    app_settings_cache_stub = types.ModuleType("app_settings_cache")
    app_settings_cache_stub.get_settings_cache = lambda: {}

    azure_stub = types.ModuleType("azure")
    monitor_stub = types.ModuleType("azure.monitor")
    opentelemetry_stub = types.ModuleType("azure.monitor.opentelemetry")
    opentelemetry_stub.configure_azure_monitor = lambda *args, **kwargs: None
    monitor_stub.opentelemetry = opentelemetry_stub
    azure_stub.monitor = monitor_stub

    original_modules = {}
    for module_name, module_stub in {
        "app_settings_cache": app_settings_cache_stub,
        "azure": azure_stub,
        "azure.monitor": monitor_stub,
        "azure.monitor.opentelemetry": opentelemetry_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["functions_appinsights"] = sys.modules.get("functions_appinsights")
    sys.modules.pop("functions_appinsights", None)

    module = importlib.import_module("functions_appinsights")
    module.get_appinsights_logger = lambda: fake_logger
    return module, original_modules


def _load_reminders_module(
    container,
    external_events,
    created_notifications,
    settings_override=None,
):
    config_stub = types.ModuleType("config")
    config_stub.cosmos_key_vault_secret_reminders_container = container

    appinsights_stub = types.ModuleType("functions_appinsights")
    appinsights_stub.log_event = lambda *args, **kwargs: None

    def log_external_event(
        event_name,
        extra=None,
        level=None,
        allowed_sensitive_dimensions=None,
    ):
        external_events.append({
            "event_name": event_name,
            "extra": dict(extra or {}),
            "level": level,
            "allowed_sensitive_dimensions": tuple(allowed_sensitive_dimensions or ()),
        })

    appinsights_stub.log_external_event = log_external_event

    notifications_stub = types.ModuleType("functions_notifications")

    def create_notification(**kwargs):
        notification = {
            "id": "notification-123",
            "scope": "assignment" if kwargs.get("assignment") else "personal",
            "metadata": dict(kwargs.get("metadata") or {}),
        }
        created_notifications.append(notification)
        return notification

    notifications_stub.create_notification = create_notification
    notifications_stub.create_group_notification = (
        lambda *args, **kwargs: create_notification(**kwargs)
    )
    notifications_stub.create_public_workspace_notification = (
        lambda *args, **kwargs: create_notification(**kwargs)
    )

    settings = {
        "enable_key_vault_secret_expiration_reminders": True,
        "key_vault_secret_expiration_default_lead_days": 30,
        "key_vault_secret_expiration_default_contact_email": "admin@example.com",
        "key_vault_secret_expiration_emit_contact_email_in_telemetry": False,
        "key_vault_secret_expiration_admin_roles": ["Admin"],
    }
    settings.update(settings_override or {})
    settings_stub = types.ModuleType("functions_settings")
    settings_stub.get_settings = lambda: dict(settings)

    azure_stub = types.ModuleType("azure")
    cosmos_stub = types.ModuleType("azure.cosmos")
    cosmos_exceptions_stub = types.ModuleType("azure.cosmos.exceptions")
    cosmos_exceptions_stub.CosmosResourceNotFoundError = FakeCosmosResourceNotFoundError
    cosmos_stub.exceptions = cosmos_exceptions_stub
    azure_stub.cosmos = cosmos_stub

    original_modules = {}
    for module_name, module_stub in {
        "config": config_stub,
        "functions_appinsights": appinsights_stub,
        "functions_notifications": notifications_stub,
        "functions_settings": settings_stub,
        "azure": azure_stub,
        "azure.cosmos": cosmos_stub,
        "azure.cosmos.exceptions": cosmos_exceptions_stub,
    }.items():
        original_modules[module_name] = sys.modules.get(module_name)
        sys.modules[module_name] = module_stub

    original_modules["functions_keyvault_reminders"] = sys.modules.get("functions_keyvault_reminders")
    sys.modules.pop("functions_keyvault_reminders", None)

    module = importlib.import_module("functions_keyvault_reminders")
    return module, original_modules


def test_log_external_event_preserves_safe_dimensions_and_redacts_raw_sensitive_values():
    """Validate external events expose only safe query dimensions."""
    print("Testing external telemetry helper safety...")
    fake_logger = FakeLogger()
    module, original_modules = _load_appinsights_module(fake_logger)

    try:
        module.log_external_event(
            "Key Vault Reminder!",
            extra={
                "scope": "global",
                "days_until_expiry": 5,
                "contact_email": "owner@example.com",
                "contact_email_hash": "emailhash123",
                "source_id": "global-action-1",
                "source_id_hash": "sourcehash123",
                "secret_name": "global-action-1--action--global--service-principal-action",
            },
        )

        assert len(fake_logger.records) == 1
        record = fake_logger.records[0]
        assert record["message"] == "[SimpleChatExternalEvent] Key_Vault_Reminder"

        extra = record["extra"]
        assert extra["sc_event_name"] == "Key_Vault_Reminder"
        assert extra["sc_event_scope"] == "global"
        assert extra["sc_event_days_until_expiry"] == 5
        assert extra["sc_event_contact_email_present"] is True
        assert extra["sc_event_secret_name_present"] is True
        assert extra["sc_event_contact_email_hash"] == "emailhash123"
        assert extra["sc_event_source_id_hash"] == "sourcehash123"
        assert "sc_event_contact_email" not in extra
        assert "sc_event_secret_name" not in extra
        assert "owner@example.com" not in repr(extra)
        assert "service-principal-action" not in repr(extra)

        module.log_external_event(
            "Key Vault Reminder!",
            extra={
                "contact_email": "owner@example.com",
                "secret_name": "global-action-1--action--global--service-principal-action",
            },
            allowed_sensitive_dimensions=("contact_email",),
        )
        opt_in_extra = fake_logger.records[1]["extra"]
        assert opt_in_extra["sc_event_contact_email"] == "owner@example.com"
        assert opt_in_extra["sc_event_secret_name_present"] is True
        assert "sc_event_secret_name" not in opt_in_extra

        print("Test passed!")
        return True
    finally:
        _restore_modules(original_modules)


def test_keyvault_reminder_external_telemetry_event_is_safe_and_queryable():
    """Validate due reminder notifications emit external-safe Azure Monitor telemetry."""
    print("Testing Key Vault reminder external telemetry event...")
    reminder = {
        "id": "key-vault-secret-reminder-abc123",
        "type": "key_vault_secret_reminder",
        "enabled": True,
        "status": "active",
        "secret_name": "global-action-1--action--global--service-principal-action",
        "key_vault_name": "prod-vault",
        "scope": "global",
        "scope_value": "global-action-1",
        "scope_key": "global:global-action-1",
        "source": "action",
        "source_type": "action",
        "source_id": "global-action-1",
        "source_display_name": "Service Principal Action",
        "field_path": "auth.key",
        "field_label": "auth key",
        "contact_email": "owner@example.com",
        "expires_on": "2026-09-01",
        "lead_days": 30,
        "notify_on": "2026-08-02",
        "key_vault_sync_status": "synced",
        "last_notification_window_key": None,
    }
    container = FakeReminderContainer(items=[reminder])
    external_events = []
    created_notifications = []
    module, original_modules = _load_reminders_module(container, external_events, created_notifications)

    try:
        result = module.check_due_key_vault_secret_reminders_once(
            now=module.datetime(2026, 8, 5, tzinfo=module.timezone.utc),
        )

        assert result["notifications_created"] == 1
        assert len(created_notifications) == 1
        assert len(external_events) == 1

        event = external_events[0]
        assert event["event_name"] == module.KEY_VAULT_SECRET_REMINDER_EXTERNAL_EVENT_NAME
        event_extra = event["extra"]
        assert event_extra["reminder_id"] == reminder["id"]
        assert event_extra["scope"] == "global"
        assert event_extra["source_type"] == "action"
        assert event_extra["days_until_expiry"] == 27
        assert event_extra["notification_id"] == "notification-123"
        assert event_extra["contact_email_hash"]
        assert event_extra["scope_value_hash"]
        assert "contact_email" not in event_extra
        assert event["allowed_sensitive_dimensions"] == ()

        serialized_extra = repr(event_extra)
        assert reminder["secret_name"] not in serialized_extra
        assert reminder["contact_email"] not in serialized_extra

        updated_reminder = container.upserted_items[-1]
        assert updated_reminder["last_notification_window_key"] == "2026-09-01:30"

        print("Test passed!")
        return True
    finally:
        _restore_modules(original_modules)


def test_keyvault_reminder_external_telemetry_can_include_contact_email_when_admin_opts_in():
    """Validate contact email is emitted only with the explicit admin opt-in."""
    print("Testing Key Vault reminder external telemetry contact email opt-in...")
    reminder = {
        "id": "key-vault-secret-reminder-email",
        "type": "key_vault_secret_reminder",
        "enabled": True,
        "status": "active",
        "secret_name": "global-action-1--action--global--service-principal-action",
        "scope": "global",
        "scope_value": "global-action-1",
        "scope_key": "global:global-action-1",
        "source": "action",
        "source_type": "action",
        "source_id": "global-action-1",
        "field_path": "auth.key",
        "contact_email": "owner@example.com",
        "expires_on": "2026-09-01",
        "lead_days": 30,
        "notify_on": "2026-08-02",
        "key_vault_sync_status": "synced",
        "last_notification_window_key": None,
    }
    container = FakeReminderContainer(items=[reminder])
    external_events = []
    created_notifications = []
    module, original_modules = _load_reminders_module(
        container,
        external_events,
        created_notifications,
        settings_override={"key_vault_secret_expiration_emit_contact_email_in_telemetry": True},
    )

    try:
        result = module.check_due_key_vault_secret_reminders_once(
            now=module.datetime(2026, 8, 5, tzinfo=module.timezone.utc),
        )

        assert result["notifications_created"] == 1
        event = external_events[0]
        assert event["extra"]["contact_email"] == "owner@example.com"
        assert event["extra"]["contact_email_hash"]
        assert event["allowed_sensitive_dimensions"] == ("contact_email",)
        assert reminder["secret_name"] not in repr(event["extra"])

        print("Test passed!")
        return True
    finally:
        _restore_modules(original_modules)


if __name__ == "__main__":
    tests = [
        test_log_external_event_preserves_safe_dimensions_and_redacts_raw_sensitive_values,
        test_keyvault_reminder_external_telemetry_event_is_safe_and_queryable,
        test_keyvault_reminder_external_telemetry_can_include_contact_email_when_admin_opts_in,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as exc:
            print(f"Test failed: {exc}")
            import traceback
            traceback.print_exc()
            results.append(False)

    success = all(results)
    print(f"\nResults: {sum(bool(result) for result in results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
