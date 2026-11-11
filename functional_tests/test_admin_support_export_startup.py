# test_admin_support_export_startup.py
"""
Fresh-process web/scheduler and current-registry support-export integration.
Version: 0.261.428
Implemented in: 0.261.428

Import real application modules in both orders and optimized Python, blocking
network access and replacing only external Cosmos I/O with SDK-default responses.
"""

import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
PROBE = r'''
import importlib
import sys
sys.path[:0] = sys.argv[1:3]
from test_support.offline_bootstrap import offline_app_imports

with offline_app_imports():
    for name in sys.argv[3].split(","):
        importlib.import_module(name)
    import config
    import functions_support_exports as runtime
    import app as web
    paths = {rule.rule for rule in web.app.url_map.iter_rules()}
    if "/api/admin/support-exports/review" not in paths or "/api/support-export-consents/<consent_id>/decision" not in paths:
        raise AssertionError("Support routes were not wired into the real web app.")
    from background_tasks import run_support_export_scheduler_loop
    if not callable(run_support_export_scheduler_loop):
        raise AssertionError("Scheduler wiring is missing.")
    settings = {
        "id": "app_settings", "enable_multi_model_endpoints": True,
        "default_model_selection": {"endpoint_id": "endpoint", "model_id": "model", "provider": "aoai"},
        "model_endpoints": [{
            "id": "endpoint", "provider": "aoai", "enabled": True,
            "connection": {"endpoint": "https://example.openai.azure.com", "openai_api_version": "2025-01-01-preview"},
            "models": [{
                "id": "model", "deploymentName": "deployment", "modelName": "gpt-4o", "enabled": True,
                "contextWindow": 128000, "inputTokenLimit": 128000, "outputTokenLimit": 8192,
                "responseLength": 1024, "outputTokenAccounting": "total_generation",
            }],
        }],
    }
    config.cosmos_settings_container.upsert_item(settings)
    runtime.get_settings = lambda: {}
    first = runtime._model_info()
    if first.get("available") is not True:
        raise AssertionError("The live registry was hidden by the empty settings cache: " + repr(first))
    settings["model_endpoints"][0]["connection"]["endpoint"] = "https://changed.openai.azure.com"
    config.cosmos_settings_container.upsert_item(settings)
    second = runtime._model_info()
    if first["fingerprint"] == second["fingerprint"]:
        raise AssertionError("The live AI destination change did not invalidate its disclosure.")
    runtime.audit_support_export("startup_test", actor="owner")
    if not config.cosmos_activity_logs_container.items:
        raise AssertionError("Support audit evidence was not persisted.")
    def unexpected_service():
        raise AssertionError("Unused support exports constructed cloud clients.")
    runtime.get_support_export_service = unexpected_service
    runtime.check_due_support_exports_once()
'''


@pytest.mark.parametrize("optimized", [False, True])
@pytest.mark.parametrize("order", [
    "functions_support_exports,background_tasks,app",
    "app,background_tasks,functions_support_exports",
])
def test_real_web_scheduler_and_fresh_registry_imports(order, optimized):
    command = [sys.executable, *(["-O"] if optimized else []), "-c", PROBE,
               str(ROOT / "application" / "single_app"), str(ROOT / "functional_tests"), order]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-5000:]
