# test_admin_support_export_source_detection.py
"""
Functional test for automatic support-export source detection.
Version: 0.261.473
Implemented in: 0.261.473

This test ensures that support exports find the Azure cloud, the App Service
resource ID, and the Application Insights resource ID from the running deployment,
so admins no longer have to type them, while saved overrides still win.
"""

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from support_export_contracts import (
    SupportExportError, effective_configuration, normalize_configuration, normalize_overrides,
)
from support_export_discovery import (
    detect_cloud, detect_configuration, detect_site_resource_id, instrumentation_key,
    lookup_app_insights_resource_id,
)


SUBSCRIPTION = "00000000-1111-2222-3333-444444444444"
KEY = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
SITE = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-chat/providers/Microsoft.Web/sites/chat-app"
APP = f"/subscriptions/{SUBSCRIPTION}/resourceGroups/rg-chat/providers/Microsoft.Insights/components/chat-ai"
APP_SERVICE_ENV = {
    "WEBSITE_SITE_NAME": "chat-app",
    "WEBSITE_OWNER_NAME": f"{SUBSCRIPTION}+rg-chat-EastUSwebspace-Linux",
    "WEBSITE_RESOURCE_GROUP": "rg-chat",
    "AZURE_ENVIRONMENT": "public",
    "APPLICATIONINSIGHTS_CONNECTION_STRING": f"InstrumentationKey={KEY};IngestionEndpoint=https://example.test/",
}


def test_cloud_comes_from_azure_environment():
    assert detect_cloud({}) == "public"
    assert detect_cloud({"AZURE_ENVIRONMENT": "usgovernment"}) == "usgovernment"
    assert detect_cloud({"AZURE_ENVIRONMENT": "custom"}) == ""


def test_site_resource_id_comes_from_app_service_platform_variables():
    assert detect_site_resource_id(APP_SERVICE_ENV) == SITE
    without_group = {key: value for key, value in APP_SERVICE_ENV.items() if key != "WEBSITE_RESOURCE_GROUP"}
    assert detect_site_resource_id(without_group) == SITE
    slot = {**APP_SERVICE_ENV, "WEBSITE_SLOT_NAME": "staging"}
    assert detect_site_resource_id(slot) == SITE + "/slots/staging"
    assert detect_site_resource_id({**APP_SERVICE_ENV, "WEBSITE_SLOT_NAME": "Production"}) == SITE
    assert detect_site_resource_id({"AZURE_ENVIRONMENT": "public"}) == ""
    normalize_configuration({"cloud": "public", "app_resource_id": "", "site_resource_id": SITE + "/slots/staging"})


def test_app_insights_prefers_deployer_setting_then_connection_string_lookup():
    calls = []
    deployed = detect_configuration({**APP_SERVICE_ENV, "APPLICATIONINSIGHTS_RESOURCE_ID": APP},
                                    lookup=lambda *args: calls.append(args) or "")
    assert deployed["app_resource_id"] == APP and deployed["origins"]["app_resource_id"] == "environment"
    assert calls == []

    found = detect_configuration(APP_SERVICE_ENV, lookup=lambda key, cloud: calls.append((key, cloud)) or APP)
    assert found["app_resource_id"] == APP and found["origins"]["app_resource_id"] == "connection_string"
    assert calls == [(KEY, "public")]
    assert found["cloud"] == "public" and found["site_resource_id"] == SITE

    missing = detect_configuration(APP_SERVICE_ENV, lookup=lambda *args: "")
    assert missing["app_resource_id"] == "" and missing["origins"]["app_resource_id"] == ""
    assert instrumentation_key({"APPINSIGHTS_INSTRUMENTATIONKEY": KEY.upper()}) == KEY


def test_resource_graph_lookup_is_bounded_and_validated():
    sent = {}

    def post(url, json, headers, timeout):
        sent.update(url=url, query=json["query"], headers=headers)
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": [{"id": APP}]})

    credential = SimpleNamespace(get_token=lambda scope: SimpleNamespace(token="token-for-" + scope))
    assert lookup_app_insights_resource_id(KEY, "usgovernment", credential, post=post) == APP
    assert sent["url"].startswith("https://management.usgovcloudapi.net/providers/Microsoft.ResourceGraph/resources")
    assert f'"{KEY}"' in sent["query"]
    assert sent["headers"]["Authorization"] == "Bearer token-for-https://management.usgovcloudapi.net/.default"

    def ambiguous(*args, **kwargs):
        return SimpleNamespace(raise_for_status=lambda: None, json=lambda: {"data": [{"id": APP}, {"id": APP}]})

    assert lookup_app_insights_resource_id(KEY, "public", credential, post=ambiguous) == ""
    assert lookup_app_insights_resource_id("not-a-key' or 1==1", "public", credential, post=post) == ""


def test_overrides_win_for_resources_but_detected_cloud_wins():
    detected = {"cloud": "usgovernment", "app_resource_id": APP, "site_resource_id": SITE}
    assert effective_configuration({}, detected) == {
        "cloud": "usgovernment", "app_resource_id": APP, "site_resource_id": SITE,
    }
    other = APP.replace("chat-ai", "other-ai")
    legacy = {"cloud": "public", "app_resource_id": other, "site_resource_id": ""}
    assert effective_configuration(legacy, detected) == {
        "cloud": "usgovernment", "app_resource_id": other, "site_resource_id": SITE,
    }
    assert effective_configuration({"cloud": "usgovernment"}, {"cloud": ""})["cloud"] == "usgovernment"
    assert normalize_overrides({})["cloud"] == ""
    with pytest.raises(SupportExportError):
        normalize_overrides({"cloud": "custom"})


def test_service_reports_where_each_value_came_from():
    from test_support.support_exports import build_service

    service = build_service()[0]
    service.detected = {
        "cloud": "public", "app_resource_id": APP, "site_resource_id": "",
        "origins": {"cloud": "environment", "app_resource_id": "connection_string", "site_resource_id": ""},
    }
    ready = service.readiness()
    assert ready["configuration"]["app_resource_id"] == APP
    assert ready["sources"]["telemetry"]["available"] is True
    assert ready["sources"]["console"]["available"] is False
    origins = ready["setup"]["origins"]
    assert origins["app_resource_id"] == {"origin": "detected", "detected_from": "connection_string"}
    assert origins["site_resource_id"]["origin"] == "missing"

    saved = service.configure("admin", ["Admin"], {"cloud": "", "app_resource_id": "", "site_resource_id": SITE})
    assert saved["configuration"]["site_resource_id"] == SITE
    assert service.readiness()["setup"]["origins"]["site_resource_id"]["origin"] == "override"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
