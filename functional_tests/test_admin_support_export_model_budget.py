# test_admin_support_export_model_budget.py
"""
Real isolated model-detector budget and complete-coverage tests.
Version: 0.261.426
Implemented in: 0.261.426

Use the current real protocol helpers rather than the older AST-extracted
adapter fixture; only the inference transport and registry read are injected.
"""

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from content_screening import model
from content_screening.contracts import ContentUnit
from azure.cosmos._cosmos_responses import CosmosDict


SETTINGS = {
    "enable_multi_model_endpoints": True,
    "model_endpoints": [{
        "id": "endpoint", "provider": "aoai", "enabled": True,
        "connection": {"endpoint": "https://example.openai.azure.com", "openai_api_version": "2025-01-01-preview"},
        "models": [{"id": "model", "deploymentName": "deployment", "modelName": "gpt-4o", "enabled": True, "responseLength": 1024}],
    }],
}
CHECK = {
    "id": "privacy", "enabled": True, "model_selection": {"endpoint_id": "endpoint", "model_id": "model"},
    "instructions": "Identify remaining sensitive information.", "severity": "high", "category": "sensitive_information",
    "window_unit": "chunks", "window_size": 1, "max_characters": 12000, "overlap_characters": 500,
}


class Client:
    def __init__(self):
        self.calls = []
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def with_options(self, **kwargs):
        return self

    def create(self, **kwargs):
        self.calls.append(kwargs)
        envelope = json.loads(kwargs["messages"][1]["content"])
        payload = {
            "window_id": envelope["window_id"],
            "results": [{
                "rule_id": envelope["rule_id"], "unit_id": unit["unit_id"],
                "inspected": True, "matched": False, "findings": [],
            } for unit in envelope["units"]],
        }
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content=json.dumps(payload), refusal=None), finish_reason="stop")],
            usage=SimpleNamespace(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        )


def test_all_model_windows_are_inspected_with_the_supported_chunk_contract():
    client = Client()
    result = model.evaluate_model_units(
        [ContentUnit("one", "A scrubbed diagnostic field.")], CHECK, settings=SETTINGS, client=client,
        token_ceiling=200000, input_ceiling=32000,
    )
    assert result.status == "pass", result.error_code
    assert result.completed_units == result.required_units == 1
    assert result.completed_windows == result.required_windows
    assert len(client.calls) == 1 and "tools" not in client.calls[0]


def test_oversize_total_and_per_request_budgets_fail_before_inference():
    for limits in ({"token_ceiling": 1}, {"token_ceiling": 200000, "input_ceiling": 1}):
        client = Client()
        result = model.evaluate_model_units(
            [ContentUnit("one", "A scrubbed diagnostic field.")], CHECK, settings=SETTINGS, client=client, **limits,
        )
        assert result.status == "incomplete" and not client.calls


def test_host_disclosure_mismatch_is_rejected_before_inference():
    client = Client()
    result = model.evaluate_model_units(
        [ContentUnit("one", "Scrubbed text.")], CHECK, settings=SETTINGS, client=client,
        binding_validator=lambda binding: False,
    )
    assert result.error_code == "model_configuration_unavailable" and not client.calls


def test_current_registry_point_response_uses_the_installed_sdk_contract():
    reads = []
    def read(**kwargs):
        reads.append(kwargs)
        return CosmosDict(SETTINGS, response_headers={})
    registry = SimpleNamespace(cosmos_settings_container=SimpleNamespace(read_item=read))
    with patch.dict(sys.modules, {"functions_settings": registry}):
        client = Client()
        result = model.evaluate_model_units(
            [ContentUnit("one", "Scrubbed text.")], CHECK, client=client, token_ceiling=200000,
        )
    assert result.status == "pass", result.error_code
    assert len(reads) >= 3
