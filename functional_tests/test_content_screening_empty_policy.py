# test_content_screening_empty_policy.py
"""
Functional tests for enabled-empty Content Screening configuration.
Version: 0.261.127
Implemented in: 0.261.114

Exercise real policy persistence and shared settings writes behind isolated
Cosmos, Blob, and authenticated route fixtures. No deployed services are used.
"""

import ast
import copy
import sys
from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Reuse the existing isolated application loaders instead of starting Azure clients.
import test_content_screening_admin_settings_fix as admin_settings_tests
import test_content_screening_settings_api as settings_tests
from test_content_screening_persistence import FakeBlobService, FakeCosmos
from content_screening import service
from content_screening.contracts import (
    SCREENING_FIELD,
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningPolicyRequiredError,
    subject_from_document,
)
from content_screening.policies import default_policy, normalize_policy
from content_screening.repository import ScreeningRepository
from content_screening.storage import ScreeningStorage


@pytest.fixture
def activation(monkeypatch):
    repository = ScreeningRepository(FakeCosmos())
    settings = {
        "id": "app_settings", "_etag": "settings-1",
        "enable_content_screening": False, "enable_enhanced_citations": True,
    }
    container = Mock()
    container.read_item.side_effect = lambda **kwargs: copy.deepcopy(settings)

    def replace(**kwargs):
        assert kwargs["etag"] == settings["_etag"]
        settings.update(copy.deepcopy(kwargs["body"]))
        settings["_etag"] = f"settings-{container.replace_item.call_count + 1}"
        return copy.deepcopy(settings)

    container.replace_item.side_effect = replace
    helpers = settings_tests.settings_functions(
        get_settings=lambda **kwargs: copy.deepcopy(settings),
        cosmos_settings_container=container,
        _get_app_settings_store=lambda: settings_tests.AppSettingsStore(container),
    )
    monkeypatch.setattr(service, "_repository", lambda value=None: repository if value is None else value)
    monkeypatch.setattr(service, "_settings", lambda value=None: settings if value is None else value)
    monkeypatch.setitem(sys.modules, "config", SimpleNamespace(
        build_enhanced_citations_blob_service_client=lambda values: FakeBlobService(),
    ))
    monkeypatch.setitem(sys.modules, "functions_embedding_compatibility", SimpleNamespace(
        embedding_settings_write_guard=lambda *args, **kwargs: nullcontext(),
    ))
    return SimpleNamespace(repository=repository, settings=settings, container=container, helpers=helpers)


def enable(activation):
    return activation.helpers["update_settings"]({"enable_content_screening": True})


def test_first_settings_activation_creates_and_reuses_enabled_empty_baseline(activation):
    activated = enable(activation)
    assert activated is True
    saved = activation.repository.get_policy("global", "global")
    assert saved["policy"] == normalize_policy({**default_policy(), "enabled": True})
    assert saved["actor_id"] == "system-content-screening"
    assert activation.settings["enable_content_screening"] is True
    activated_again = enable(activation)
    reloaded = activation.repository.get_policy("global", "global")
    assert activated_again is True
    assert reloaded == saved


@pytest.mark.parametrize("enabled", [False, True])
def test_activation_never_replaces_or_activates_an_existing_policy(activation, enabled):
    policy = settings_tests.activation_policy(ai_enabled=False)
    policy["enabled"] = enabled
    saved = activation.repository.save_policy("global", "global", policy, "administrator")
    activated = enable(activation)
    reloaded = activation.repository.get_policy("global", "global")
    assert activated is True
    assert reloaded == saved


def test_prerequisite_failure_does_not_initialize_policy_or_enable_settings(activation):
    with patch.object(service, "validate_screening_configuration", side_effect=ScreeningConfigurationError()):
        activated = enable(activation)
        assert activated is False
    saved = activation.repository.get_policy("global", "global")
    assert saved is None
    activation.container.replace_item.assert_not_called()
    assert activation.settings["enable_content_screening"] is False


def test_policy_creation_failure_cannot_report_settings_success_or_leak_errors(activation):
    with patch.object(activation.repository, "save_policy", side_effect=RuntimeError("private-provider-canary")):
        activated = enable(activation)
        assert activated is False
    activation.container.replace_item.assert_not_called()
    assert activation.settings["enable_content_screening"] is False
    assert "private-provider-canary" not in str(activation.helpers["log_event"].call_args_list)


def test_failed_settings_write_keeps_blank_policy_reusable_without_enabling_scanning(activation):
    replace = activation.container.replace_item.side_effect
    activation.container.replace_item.side_effect = RuntimeError("private-provider-canary")
    activated = enable(activation)
    assert activated is False
    saved = activation.repository.get_policy("global", "global")
    assert saved["policy"]["enabled"] is True and saved["policy"]["rules"] == []
    assert activation.settings["enable_content_screening"] is False
    activation.container.replace_item.side_effect = replace
    activated = enable(activation)
    reloaded = activation.repository.get_policy("global", "global")
    assert activated is True
    assert reloaded == saved


@pytest.mark.parametrize("invalid_model", [False, True])
def test_concurrent_policy_creation_is_preserved_and_revalidated(activation, invalid_model):
    save_policy = activation.repository.save_policy
    concurrent = settings_tests.activation_policy(ai_enabled=invalid_model)

    def concurrent_create(*args, **kwargs):
        save_policy("global", "global", concurrent, "another-administrator")
        raise ScreeningConflictError()

    model_validation = Mock(side_effect=ScreeningConfigurationError() if invalid_model else None)
    with patch.object(activation.repository, "save_policy", side_effect=concurrent_create), patch.dict(sys.modules, {
        "content_screening.model": SimpleNamespace(validate_model_bindings=model_validation),
    }):
        activated = enable(activation)
        assert activated is not invalid_model
    saved = activation.repository.get_policy("global", "global")
    assert saved["policy"] == normalize_policy(concurrent)
    assert saved["actor_id"] == "another-administrator"
    assert activation.settings["enable_content_screening"] is not invalid_model
    if invalid_model:
        model_validation.assert_called_once()
        activation.container.replace_item.assert_not_called()


def test_missing_policy_during_runtime_is_not_a_silent_unscreened_fallback(activation):
    activation.settings["enable_content_screening"] = True
    with pytest.raises(ScreeningPolicyRequiredError):
        service.document_requires_screening({"id": "new-document", "user_id": "owner", "version": 1})
    service.validate_screening_configuration(
        activation.settings, proposed_settings=True, allow_missing_policy=True,
    )
    saved = activation.repository.get_policy("global", "global")
    assert saved is None


@pytest.mark.parametrize("marker", [None, {}, {"state": "pending_review"}, {"state": "cleared"}])
def test_existing_or_malformed_enrollment_never_uses_empty_policy_bypass(activation, marker):
    activated = enable(activation)
    assert activated is True
    document = {"id": "document", "user_id": "owner", "version": 1, SCREENING_FIELD: marker}
    required = service.document_requires_screening(document)
    assert required is True
    activation.settings["enable_content_screening"] = False
    still_required = service.document_requires_screening(document)
    assert still_required is True


@pytest.mark.parametrize("enrolled", [False, True])
def test_reprocessing_dispatch_keeps_old_enrollment_but_skips_empty_policy_for_unmarked_content(activation, enrolled):
    activated = enable(activation)
    assert activated is True
    document = {"id": "document", "user_id": "owner", "version": 1}
    if enrolled:
        document[SCREENING_FIELD] = {"state": "pending_review"}
    source = settings_tests.APP_DIR / "functions_documents.py"
    tree = ast.parse(source.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef)
                    and node.name == "process_document_reprocess_extraction_background")
    ordinary = Mock(return_value="ordinary")
    screened = Mock(return_value="screened")
    namespace = {
        "get_document_metadata": lambda *args: copy.deepcopy(document),
        "get_settings": lambda: activation.settings,
        "document_requires_screening": service.document_requires_screening,
        "subject_from_document": subject_from_document,
        "normalize_document_intelligence_manual_extraction_mode": lambda value: value,
        "reprocess_document": screened,
        "_process_document_reprocess_extraction_background_impl": ordinary,
    }
    exec(compile(ast.Module(body=[function], type_ignores=[]), str(source), "exec"), namespace)
    result = namespace[function.name]("document", "owner", "enhanced")
    assert result == ("screened" if enrolled else "ordinary")
    assert ordinary.call_count == int(not enrolled) and screened.call_count == int(enrolled)


def test_v2_settings_handler_uses_shared_empty_policy_persistence(activation):
    handler = admin_settings_tests.patch_handler(activation.settings)
    handler["update_settings"] = activation.helpers["update_settings"]
    handler["validate_content_screening_settings"] = activation.helpers["validate_content_screening_settings"]
    handler["get_settings"] = lambda **kwargs: copy.deepcopy(activation.settings)
    payload, status = admin_settings_tests.invoke(handler, {"enable_content_screening": True})
    assert status == 200 and payload["settings"]["enable_content_screening"] is True
    assert activation.settings["enable_content_screening"] is True
    saved = activation.repository.get_policy("global", "global")
    assert saved["policy"]["rules"] == []


def test_classic_configuration_route_initializes_policy_and_roundtrips_empty_saves(activation):
    case = settings_tests.ScreeningApiTests()
    case.setUp()
    try:
        case.login("admin", ["Admin"])
        with patch.object(case.route, "_repository", return_value=activation.repository), \
                patch.object(case.route, "cosmos_settings_container", activation.container), \
                patch.object(case.route, "get_settings", side_effect=lambda: copy.deepcopy(activation.settings)), \
                patch.object(case.route, "update_settings", activation.helpers["update_settings"]), \
                patch.object(sys.modules["content_screening.storage"], "ScreeningStorage", ScreeningStorage):
            response = case.client.put("/api/content-screening/configuration", json={"enabled": True})
            assert response.status_code == 200 and response.json["enabled"] is True
            path = "/api/content-screening/policies/global/global"
            loaded = case.client.get(path).json
            assert loaded["etag"] is not None
            assert loaded["policy"]["enabled"] is True and loaded["policy"]["rules"] == []
            saved = case.client.put(path, json={"policy": loaded["policy"], "etag": loaded["etag"]})
            assert saved.status_code == 200 and saved.json["policy"]["enabled"] is True
            assert activation.settings["enable_content_screening"] is True
    finally:
        case.doCleanups()
