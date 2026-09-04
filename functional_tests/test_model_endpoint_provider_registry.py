#!/usr/bin/env python3
"""
Functional test for the Custom model endpoint provider registry.
Version: 0.261.012
Implemented in: 0.261.012

Custom endpoints previously supported exactly three API types, hard-coded in five
places: the allowlist, the request-model resolver, the protocol inference
if-chain, the admin template's option list, and the admin JavaScript. Adding a
provider meant editing all five.

These tests ensure that:
  * every registered API type is reachable end to end -- normalization, protocol
    inference, request-model resolution, and the admin UI descriptor,
  * the three original API types behave exactly as they did before the registry,
  * Google Gemini is supported and its OpenAI-compatible base URL is not mangled
    by the "/v1" appending rule that applies to plain OpenAI endpoints,
  * an unregistered API type is still rejected.
"""

import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "application",
        "single_app",
    )
)

from test_support.versioning import assert_app_version_at_least

from functions_model_endpoint_providers import (
    MODEL_ENDPOINT_API_TYPE_ANTHROPIC,
    MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI,
    MODEL_ENDPOINT_API_TYPE_GEMINI,
    MODEL_ENDPOINT_API_TYPE_OPENAI,
    MODEL_ENDPOINT_PROVIDERS,
    URL_POLICY_AS_GIVEN,
    get_model_endpoint_provider,
    get_model_endpoint_provider_ui_options,
    normalize_custom_endpoint_url_mode,
)
from functions_model_endpoint_types import (
    normalize_model_endpoint_api_type,
    resolve_model_endpoint_request_model,
)
from model_endpoint_clients import (
    MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
    MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
    MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
    infer_model_endpoint_protocol,
    resolve_custom_openai_base_url,
)


def test_original_api_types_are_unchanged():
    """The three pre-registry API types must behave exactly as before."""
    print("Testing original API type behaviour...")
    try:
        expected = {
            MODEL_ENDPOINT_API_TYPE_OPENAI: (
                MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE,
                "gpt-4o",
            ),
            MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI: (
                MODEL_ENDPOINT_PROTOCOL_AZURE_OPENAI,
                "my-deployment",
            ),
            MODEL_ENDPOINT_API_TYPE_ANTHROPIC: (
                MODEL_ENDPOINT_PROTOCOL_ANTHROPIC,
                "gpt-4o",
            ),
        }
        model = {"modelName": "gpt-4o", "deploymentName": "my-deployment"}

        for api_type, (protocol, request_model) in expected.items():
            assert normalize_model_endpoint_api_type("custom", api_type) == api_type
            resolved_protocol = infer_model_endpoint_protocol(
                "custom", "https://example.com/v1", "m", api_type
            )
            assert resolved_protocol == protocol, (
                f"{api_type} inferred {resolved_protocol}, expected {protocol}"
            )
            endpoint = {"provider": "custom", "api_type": api_type}
            resolved_model = resolve_model_endpoint_request_model(endpoint, model)
            assert resolved_model == request_model, (
                f"{api_type} resolved {resolved_model}, expected {request_model}"
            )

        # A non-custom provider must never report an explicit API type.
        assert normalize_model_endpoint_api_type("aoai", "openai") == ""

        print("Original API type behaviour unchanged")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_every_registered_provider_is_reachable():
    """Each registered API type must resolve through the whole pipeline."""
    print("Testing registry completeness...")
    try:
        ui_values = {option["value"] for option in get_model_endpoint_provider_ui_options()}

        for provider in MODEL_ENDPOINT_PROVIDERS:
            api_type = provider.api_type

            assert normalize_model_endpoint_api_type("custom", api_type) == api_type
            assert get_model_endpoint_provider(api_type) is provider
            assert api_type in ui_values, f"{api_type} missing from the UI options."

            protocol = infer_model_endpoint_protocol(
                "custom", "https://example.com/v1", "m", api_type
            )
            assert protocol == provider.protocol

            endpoint = {"provider": "custom", "api_type": api_type}
            model = {"modelName": "model-a", "deploymentName": "deploy-a"}
            resolved = resolve_model_endpoint_request_model(endpoint, model)
            expected = "model-a" if provider.uses_model_name else "deploy-a"
            assert resolved == expected, f"{api_type} resolved {resolved}, expected {expected}"

        print(f"All {len(MODEL_ENDPOINT_PROVIDERS)} registered API types are reachable")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_unregistered_api_type_is_rejected():
    """An API type that is not registered must still be refused."""
    print("Testing unregistered API type rejection...")
    try:
        for api_type in ("vertex", "bedrock", "totally-made-up", ""):
            assert normalize_model_endpoint_api_type("custom", api_type) == "", (
                f"{api_type!r} must not normalize to a supported API type."
            )
            try:
                infer_model_endpoint_protocol(
                    "custom", "https://example.com/v1", "m", api_type
                )
            except ValueError:
                pass
            else:
                raise AssertionError(
                    f"{api_type!r} must raise when inferring a Custom protocol."
                )

        print("Unregistered API types rejected")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_gemini_base_url_is_not_mangled():
    """Gemini's OpenAI-compatible base must not have a second /v1 appended."""
    print("Testing Gemini URL policy...")
    try:
        provider = get_model_endpoint_provider(MODEL_ENDPOINT_API_TYPE_GEMINI)
        assert provider is not None, "Gemini must be a registered API type."
        assert provider.url_policy == URL_POLICY_AS_GIVEN
        assert provider.protocol == MODEL_ENDPOINT_PROTOCOL_OPENAI_STYLE

        gemini_base = "https://generativelanguage.googleapis.com/v1beta/openai"
        resolved = resolve_custom_openai_base_url(gemini_base, MODEL_ENDPOINT_API_TYPE_GEMINI)
        assert resolved == f"{gemini_base}/", f"Gemini base resolved to {resolved}"
        assert "/v1beta/openai/v1" not in resolved, (
            "Appending /v1 to Gemini's compatible base produces a 404."
        )

        # A trailing slash must not double up.
        assert resolve_custom_openai_base_url(
            f"{gemini_base}/", MODEL_ENDPOINT_API_TYPE_GEMINI
        ) == f"{gemini_base}/"

        # Plain OpenAI keeps the appending behaviour.
        assert resolve_custom_openai_base_url(
            "https://api.gen.ai.mil", MODEL_ENDPOINT_API_TYPE_OPENAI
        ) == "https://api.gen.ai.mil/v1/"
        assert resolve_custom_openai_base_url(
            "https://api.openai.com/v1", MODEL_ENDPOINT_API_TYPE_OPENAI
        ) == "https://api.openai.com/v1/"

        print("Gemini URL policy passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_ui_descriptors_are_complete():
    """Every UI descriptor must carry the fields the admin JavaScript reads."""
    print("Testing UI descriptor contract...")
    try:
        required_fields = {
            "value",
            "label",
            "usesModelName",
            "requiresApiVersion",
            "versionField",
            "defaultVersion",
            "authTypes",
            "description",
        }
        options = get_model_endpoint_provider_ui_options()
        assert options, "The registry must expose at least one API type."

        for option in options:
            missing = required_fields - set(option)
            assert not missing, f"{option.get('value')} is missing {sorted(missing)}"
            assert isinstance(option["usesModelName"], bool)
            assert isinstance(option["requiresApiVersion"], bool)
            assert isinstance(option["authTypes"], list) and option["authTypes"]

        azure = next(o for o in options if o["value"] == MODEL_ENDPOINT_API_TYPE_AZURE_OPENAI)
        assert azure["requiresApiVersion"] is True
        assert azure["versionField"] == "api_version"
        assert azure["usesModelName"] is False

        anthropic = next(o for o in options if o["value"] == MODEL_ENDPOINT_API_TYPE_ANTHROPIC)
        assert anthropic["versionField"] == "anthropic_version"
        assert anthropic["defaultVersion"] == "2023-06-01"

        print(f"UI descriptor contract passed for {len(options)} API types")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_url_policy_respects_existing_version_and_operation_paths():
    """"/v1" must be appended only when the URL does not already say where the API lives."""
    print("Testing URL append policy...")
    try:
        cases = [
            # (configured URL, expected resolved base)
            ("https://api.openai.com/v1", "https://api.openai.com/v1/"),
            ("https://api.openai.com", "https://api.openai.com/v1/"),
            ("https://api.gen.ai.mil", "https://api.gen.ai.mil/v1/"),
            ("https://vllm.corp.example.com/v1", "https://vllm.corp.example.com/v1/"),
            # A version segment already names the API surface.
            ("https://gw.example.com/api/v2", "https://gw.example.com/api/v2/"),
            ("https://x.example.com/v1beta", "https://x.example.com/v1beta/"),
            # A full operation URL states the base exactly, so it must not gain /v1.
            (
                "https://apim.example.com/inference/chat/completions",
                "https://apim.example.com/inference/",
            ),
        ]
        for configured, expected in cases:
            resolved = resolve_custom_openai_base_url(configured, MODEL_ENDPOINT_API_TYPE_OPENAI)
            assert resolved == expected, (
                f"{configured} resolved to {resolved}, expected {expected}"
            )

        print(f"URL append policy correct for {len(cases)} endpoint shapes")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_exact_url_mode_escape_hatch():
    """url_mode "exact" must disable rewriting for any API type."""
    print("Testing exact URL escape hatch...")
    try:
        assert normalize_custom_endpoint_url_mode("exact") == "exact"
        assert normalize_custom_endpoint_url_mode("") == "auto"
        assert normalize_custom_endpoint_url_mode("nonsense") == "auto"

        gateway = "https://gw.example.com/llm/openai"
        # Auto mode appends, because the path does not name a version.
        assert resolve_custom_openai_base_url(
            gateway, MODEL_ENDPOINT_API_TYPE_OPENAI
        ) == f"{gateway}/v1/"
        # Exact mode leaves it alone.
        assert resolve_custom_openai_base_url(
            gateway, MODEL_ENDPOINT_API_TYPE_OPENAI, "exact"
        ) == f"{gateway}/"

        print("Exact URL escape hatch passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_bumped():
    """The provider registry ships at or after its implementation version."""
    print("Testing config version...")
    try:
        assert_app_version_at_least("0.261.014")
        print("Config version check passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_original_api_types_are_unchanged,
        test_every_registered_provider_is_reachable,
        test_unregistered_api_type_is_rejected,
        test_gemini_base_url_is_not_mangled,
        test_url_policy_respects_existing_version_and_operation_paths,
        test_exact_url_mode_escape_hatch,
        test_ui_descriptors_are_complete,
        test_version_bumped,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
