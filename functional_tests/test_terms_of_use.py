#!/usr/bin/env python3
# test_terms_of_use.py
"""
Functional test for Terms of Use recurrence and persistence helpers.
Version: 0.261.051
Implemented in: 0.250.055
Redirect hardening updated in: 0.250.057
Disabled-setting and activity revision regressions: 0.261.050 (#1615, #1616)

This test ensures Terms of Use hashes, redirect validation,
pre-auth session acceptance, and user-settings persistence behave consistently.
"""

import ast
from copy import deepcopy
from datetime import datetime
import logging
import sys
import types
import importlib.util
from pathlib import Path
from typing import Optional
from unittest.mock import Mock
import uuid

import pytest
from werkzeug.datastructures import MultiDict


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

from functions_terms_of_use_config import format_terms_of_use_version, normalize_terms_of_use_revision


class FakeSession(dict):
    """Minimal Flask session stand-in for helper tests."""

    modified = False


fake_session = FakeSession()
_MISSING_MODULE = object()


def _install_helper_test_stubs():
    fake_flask = types.ModuleType("flask")
    fake_flask.session = fake_session
    fake_flask.has_request_context = lambda: True
    stubs = {"flask": fake_flask}

    fake_activity = types.ModuleType("functions_activity_logging")
    fake_activity.log_terms_of_use_accepted = lambda **payload: None
    fake_activity.log_terms_of_use_declined = lambda **payload: None
    stubs["functions_activity_logging"] = fake_activity

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    stubs["functions_appinsights"] = fake_appinsights

    fake_settings = types.ModuleType("functions_settings")
    fake_settings.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
    fake_settings.update_user_settings = lambda user_id, payload: True
    stubs["functions_settings"] = fake_settings

    originals = {}
    for name, module in stubs.items():
        originals[name] = sys.modules.get(name, _MISSING_MODULE)
        sys.modules[name] = module
    return originals


def _restore_helper_test_stubs(originals):
    for name, original_module in originals.items():
        if original_module is _MISSING_MODULE:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original_module


def _load_helper_module():
    originals = _install_helper_test_stubs()
    module_path = APP_DIR / "functions_terms_of_use.py"
    spec = importlib.util.spec_from_file_location("terms_of_use_under_test", module_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    finally:
        _restore_helper_test_stubs(originals)
    return module


terms = _load_helper_module()


def _enabled_settings(frequency="once", message="Please accept these terms."):
    return {
        "enable_terms_of_use": True,
        "terms_of_use_title": "Rules of Behavior",
        "terms_of_use_message": message,
        "terms_of_use_frequency": frequency,
        "terms_of_use_decline_redirect_url": "/",
        "terms_of_use_accept_button_text": "Accept",
        "terms_of_use_decline_button_text": "Cancel",
    }


def test_hash_and_redirect_normalization():
    """Validate hash invalidation and redirect safety."""
    first_hash = terms.compute_terms_of_use_hash("Title", "Message", "once")
    second_hash = terms.compute_terms_of_use_hash("Title", "Changed", "once")

    assert first_hash != second_hash
    assert terms.normalize_terms_of_use_frequency("once-per-day") == "daily"
    assert terms.normalize_terms_of_use_redirect_url("/goodbye") == "/goodbye"
    assert terms.normalize_terms_of_use_redirect_url("https://contoso.example/terms") == "https://contoso.example/terms"
    assert terms.normalize_terms_of_use_redirect_url("http://contoso.example/terms") == "/"
    assert terms.normalize_terms_of_use_redirect_url("https://user:pass@contoso.example/terms") == "/"
    assert terms.normalize_terms_of_use_redirect_url("//evil.example") == "/"
    assert terms.normalize_terms_of_use_redirect_url("javascript:alert(1)") == "/"
    assert terms.normalize_terms_of_use_return_path("/chats?x=1") == "/chats?x=1"
    assert terms.normalize_terms_of_use_return_path("https://evil.example") == "/"


def test_pre_auth_session_acceptance_unblocks_login_for_daily_mode():
    """Validate anonymous pre-auth acceptance prevents a daily-mode login loop."""
    settings = _enabled_settings(frequency="daily")

    fake_session.clear()
    assert not terms.has_terms_of_use_acceptance(settings)
    terms.mark_pre_auth_terms_of_use_acceptance(settings)
    assert terms.has_terms_of_use_acceptance(settings)
    assert terms.TERMS_OF_USE_PRE_AUTH_SESSION_KEY in fake_session


def test_once_acceptance_persists_to_user_settings_and_activity_log():
    """Validate once-per-version acceptance writes user settings and audit data."""
    settings = _enabled_settings(frequency="once")
    updates = []
    audits = []

    original_update_user_settings = terms.update_user_settings
    original_get_user_settings = terms.get_user_settings
    original_log_acceptance = terms.log_terms_of_use_accepted

    terms.update_user_settings = lambda user_id, payload: updates.append((user_id, payload)) or True
    terms.get_user_settings = lambda user_id: {"id": user_id, "settings": {}}
    terms.log_terms_of_use_accepted = lambda **payload: audits.append(payload)

    try:
        fake_session.clear()
        record = terms.record_terms_of_use_acceptance(
            user_id="user-123",
            settings=settings,
            source="post_auth",
        )
        assert record["frequency"] == "once"
        assert fake_session[terms.TERMS_OF_USE_SESSION_KEY]["hash"] == record["hash"]
    finally:
        terms.update_user_settings = original_update_user_settings
        terms.get_user_settings = original_get_user_settings
        terms.log_terms_of_use_accepted = original_log_acceptance

    assert updates[0][0] == "user-123"
    stored_record = updates[0][1][terms.TERMS_OF_USE_USER_SETTINGS_KEY]
    assert stored_record["hash"] == record["hash"]
    assert audits[0]["user_id"] == "user-123"
    assert audits[0]["frequency"] == "once"


def test_daily_user_settings_acceptance_requires_today():
    """Validate daily recurrence expires on the next UTC date."""
    settings = _enabled_settings(frequency="daily")
    config = terms.get_terms_of_use_config(settings)
    today_record = {
        "hash": config["hash"],
        "frequency": "daily",
        "accepted_date": terms._utc_now().strftime("%Y-%m-%d"),
    }
    stale_record = {
        "hash": config["hash"],
        "frequency": "daily",
        "accepted_date": "2000-01-01",
    }

    original_get_user_settings = terms.get_user_settings
    try:
        terms.get_user_settings = lambda user_id: {
            "id": user_id,
            "settings": {terms.TERMS_OF_USE_USER_SETTINGS_KEY: today_record},
        }
        assert terms.has_terms_of_use_acceptance(settings, user_id="user-123")

        terms.get_user_settings = lambda user_id: {
            "id": user_id,
            "settings": {terms.TERMS_OF_USE_USER_SETTINGS_KEY: stale_record},
        }
        assert not terms.has_terms_of_use_acceptance(settings, user_id="user-123")
    finally:
        terms.get_user_settings = original_get_user_settings


def _load_functions(path, names, namespace):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    functions = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name in names
    ]
    assert {node.name for node in functions} == set(names)
    exec(compile(ast.Module(body=functions, type_ignores=[]), str(path), "exec"), namespace)
    return namespace


@pytest.fixture
def recorded_terms(monkeypatch):
    records = []
    users = {}
    logger = Mock()
    container = Mock()
    container.create_item.side_effect = lambda *, body: records.append(deepcopy(body))
    namespace = _load_functions(
        APP_DIR / "functions_activity_logging.py",
        {"log_terms_of_use_accepted", "log_terms_of_use_declined"},
        {
            "uuid": uuid, "datetime": datetime, "Optional": Optional,
            "cosmos_activity_logs_container": container,
            "log_event": logger, "logging": logging, "debug_print": Mock(),
        },
    )
    monkeypatch.setattr(terms, "log_terms_of_use_accepted", namespace["log_terms_of_use_accepted"])
    monkeypatch.setattr(terms, "log_terms_of_use_declined", namespace["log_terms_of_use_declined"])
    monkeypatch.setattr(terms, "get_user_settings", lambda user: {"settings": deepcopy(users.get(user, {}))})

    def save_user(user, changes):
        users.setdefault(user, {}).update(deepcopy(changes))
        return True

    monkeypatch.setattr(terms, "update_user_settings", save_user)
    fake_session.clear()
    yield records, users, logger
    fake_session.clear()


@pytest.mark.parametrize("frequency", ["once", "daily", "every_session"])
@pytest.mark.parametrize("source", ["pre_auth", "post_auth"])
def test_activity_records_identify_each_accepted_terms_revision(recorded_terms, frequency, source):
    records, users, logger = recorded_terms
    first = _enabled_settings(frequency, message="First **revision**.")
    normalize_terms_of_use_revision(first)
    second = _enabled_settings(frequency, message="Second **revision**.")
    second["terms_of_use_revision"] = deepcopy(first["terms_of_use_revision"])
    normalize_terms_of_use_revision(second)
    for version, settings in enumerate((first, second), start=1):
        if source == "pre_auth":
            terms.mark_pre_auth_terms_of_use_acceptance(settings)
            accepted = terms.apply_pending_pre_auth_terms_of_use("reader", settings)
        else:
            accepted = terms.record_terms_of_use_acceptance("reader", settings)
        assert records[-1]["terms_hash"] == accepted["hash"]
        assert records[-1]["terms_version"] == accepted["version"] == version
        assert records[-1]["terms_hash"] == terms.get_terms_of_use_config(settings)["hash"]
        assert records[-1]["source"] == source
        assert records[-1]["frequency"] == frequency
        assert records[-1]["activity_type"] == "terms_of_use_accepted"
        assert "message" not in records[-1]
        if frequency != "every_session":
            assert users["reader"]["termsOfUse"]["hash"] == records[-1]["terms_hash"]

    assert len(records) == 2
    assert records[0]["terms_hash"] != records[1]["terms_hash"]
    assert len(records[0]["terms_hash"]) == 64
    assert not any(call.kwargs["level"] == logging.ERROR for call in logger.call_args_list)


def test_changed_terms_do_not_publish_stale_pre_auth_acceptance(recorded_terms):
    records, _, _ = recorded_terms
    terms.mark_pre_auth_terms_of_use_acceptance(_enabled_settings(message="Old terms"))
    assert terms.apply_pending_pre_auth_terms_of_use("reader", _enabled_settings(message="New terms")) is None
    assert records == []


def test_decline_records_current_terms_revision(recorded_terms):
    records, _, _ = recorded_terms
    settings = _enabled_settings()
    normalize_terms_of_use_revision(settings)
    terms.record_terms_of_use_decline("reader", settings)
    assert records[0]["activity_type"] == "terms_of_use_declined"
    assert records[0]["terms_hash"] == terms.get_terms_of_use_config(settings)["hash"]
    assert records[0]["terms_version"] == 1


@pytest.mark.parametrize("activity_type", ["terms_of_use_accepted", "terms_of_use_declined"])
def test_activity_csv_includes_recorded_revision_not_current_settings(activity_type):
    formatter = _load_functions(
        APP_DIR / "route_backend_control_center.py",
        {"format_activity_log_details_for_csv"}, {"format_terms_of_use_version": format_terms_of_use_version},
    )["format_activity_log_details_for_csv"]
    revisions = [terms.get_terms_of_use_config(_enabled_settings(message=text))["hash"] for text in ("Old", "New")]
    for version, revision in enumerate(revisions, start=1):
        details = formatter({
            "activity_type": activity_type, "terms_hash": revision,
            "terms_version": version,
            "frequency": "once", "source": "pre_auth",
        })
        assert f"Terms version: v{version}" in details
        assert revision not in details
        assert "Frequency: once" in details
        assert "Source: pre_auth" in details
    assert "Terms version: Legacy" in formatter({"activity_type": activity_type, "terms_hash": revisions[0]})


def test_legacy_pre_auth_acceptance_is_not_given_an_invented_version(recorded_terms):
    records, _, _ = recorded_terms
    settings = _enabled_settings()
    pending = terms.mark_pre_auth_terms_of_use_acceptance(settings)
    pending.pop("version")
    normalize_terms_of_use_revision(settings)
    terms.apply_pending_pre_auth_terms_of_use("reader", settings)
    assert records[0]["terms_version"] is None
    assert records[0]["terms_hash"] == terms.get_terms_of_use_config(settings)["hash"]


def test_revision_metadata_does_not_invalidate_existing_acceptance(recorded_terms):
    records, users, _ = recorded_terms
    settings = _enabled_settings()
    terms.record_terms_of_use_acceptance("reader", settings)
    original_hash = users["reader"]["termsOfUse"]["hash"]
    normalize_terms_of_use_revision(settings)
    assert terms.has_terms_of_use_acceptance(settings, "reader")
    assert terms.record_terms_of_use_acceptance("reader", settings) is None
    assert len(records) == 1
    assert original_hash == settings["terms_of_use_revision"]["hash"]


@pytest.mark.parametrize("enabled", [False, True])
def test_admin_terms_parsing_includes_edits_when_disabled(enabled):
    """Exercise the actual route's Terms statements and saved-field mapping offline."""
    tree = ast.parse((APP_DIR / "route_frontend_admin_settings.py").read_text(encoding="utf-8"))
    registrar = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "register_route_frontend_admin_settings")
    route = next(node for node in registrar.body if isinstance(node, ast.FunctionDef) and node.name == "admin_settings")
    post = next(node for node in route.body if isinstance(node, ast.If) and ast.unparse(node.test) == "request.method == 'POST'")
    start = next(index for index, node in enumerate(post.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "enable_terms_of_use" for target in node.targets))
    end = next(index for index, node in enumerate(post.body) if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "enable_ai_notice" for target in node.targets))
    settings_assignment = next(node for node in post.body if isinstance(node, ast.Assign) and any(isinstance(target, ast.Name) and target.id == "new_settings" for target in node.targets))
    pairs = [(key, value) for key, value in zip(settings_assignment.value.keys, settings_assignment.value.values) if isinstance(key, ast.Constant) and (key.value.startswith("terms_of_use_") or key.value == "enable_terms_of_use")]
    projection = ast.Return(value=ast.Dict(
        keys=[key for key, _ in pairs], values=[value for _, value in pairs],
    ))
    form = MultiDict({
        "terms_of_use_title": "Updated title",
        "terms_of_use_message": "Updated **terms** while disabled.",
        "terms_of_use_frequency": "daily",
        "terms_of_use_decline_redirect_url": "/goodbye",
        "terms_of_use_accept_button_text": "Agree",
        "terms_of_use_decline_button_text": "Decline",
    })
    if enabled:
        form["enable_terms_of_use"] = "on"
    namespace = {**vars(terms), "form_data": form, "flash": Mock()}
    wrapper = ast.parse("def parse_terms():\n    pass\n").body[0]
    wrapper.body = post.body[start:end] + [projection]
    module = ast.fix_missing_locations(ast.Module(body=[wrapper], type_ignores=[]))
    exec(compile(module, "admin_terms_save", "exec"), namespace)
    assert namespace["parse_terms"]() == {
        **{key: value for key, value in form.items() if key != "enable_terms_of_use"},
        "enable_terms_of_use": enabled,
    }
    namespace["flash"].assert_not_called()


if __name__ == "__main__":
    sys.exit(pytest.main([str(Path(__file__).resolve())]))
