# test_gpt6_reasoning_model_parameters.py
"""
Functional test for GPT-6 models using reasoning-model request parameters.
Version: 0.261.219
Implemented in: 0.261.219

GPT-6 models reject `max_tokens` ("Use 'max_completion_tokens' instead"), as GPT-5 and
o-series models do. SimpleChat recognized only gpt-5, o1, o3 and o4 as reasoning models,
so any request that set a response length for a GPT-6 deployment failed with a 400. A
workflow sets one on every model call once the model's token limits are configured.

The model behavior policy and the workflow budget's parameter choice are run unchanged
from source.
"""

import sys
from collections.abc import Mapping

import pytest

from test_support.app_source import run_definitions


def load_behavior():
    namespace = run_definitions(
        "model_endpoint_clients.py", {"OPENAI_REASONING_MODEL_PREFIXES", "ModelEndpointBehavior"}, {"Any": object},
    )
    return namespace["ModelEndpointBehavior"]


ModelEndpointBehavior = load_behavior()
response_parameter = run_definitions(
    "functions_workflow_context.py", {"_response_parameter"},
    {"ModelEndpointBehavior": ModelEndpointBehavior, "Mapping": Mapping},
)["_response_parameter"]


@pytest.mark.parametrize("name", ["gpt-6-astra", "gpt-6-sol", "N-gpt-6-astra", "astra-deployment GPT 6 Astra"])
def test_gpt6_models_use_reasoning_parameters(name):
    behavior = ModelEndpointBehavior("aoai", name)
    assert behavior.is_openai_reasoning_model is True
    assert behavior.response_length_parameter == "max_completion_tokens"


@pytest.mark.parametrize("name,parameter", [
    ("gpt-5.6-luna", "max_completion_tokens"),
    ("o4-mini", "max_completion_tokens"),
    ("gpt-4o", "max_tokens"),
    ("gpt-4.1", "max_tokens"),
])
def test_other_models_keep_their_parameter(name, parameter):
    assert ModelEndpointBehavior("aoai", name).response_length_parameter == parameter


@pytest.mark.parametrize("audit,model", [
    ({"model_id": "gpt-6-astra"}, {}),
    ({}, {"modelName": "gpt-6-astra", "deploymentName": "gpt-6-astra"}),
])
def test_workflow_budget_sets_max_completion_tokens_for_gpt6(audit, model):
    assert response_parameter(audit, model, "aoai") == "max_completion_tokens"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
