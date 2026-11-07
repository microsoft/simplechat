# test_image_generation_responses_route.py
"""
Functional test for image generation through the Responses image tool.
Version: 0.261.107
Implemented in: 0.261.088

Shared connection routing, v1 transport, and strict non-success validation were added
in 0.261.102. Since 0.261.107, verified direct OpenAI Custom models use Responses;
Azure GPT chat models are excluded, and dedicated models use Images, MAI, or FLUX.
These pure routing tests do not establish live provider availability.
"""

import copy
import sys
import traceback
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

sys.path.append(str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_ai_connections import (  # noqa: E402 - application path set above
    AIConnectionError,
    IMAGE_GENERATION_CAPABILITY,
    ModelBinding,
)
from functions_image_api_route import (  # noqa: E402  - path set above
    DEFAULT_RESPONSES_IMAGE_FORMAT,
    IMAGE_API_ROUTE_FLUX,
    IMAGE_API_ROUTE_IMAGES,
    IMAGE_API_ROUTE_MAI,
    IMAGE_API_ROUTE_RESPONSES,
    ImageGenerationError,
    RESPONSES_IMAGE_API_VERSION,
    build_image_api_base_url,
    build_image_generation_tool,
    extract_responses_image_source,
    is_image_capable_model_name,
    resolve_image_api_route,
    resolve_image_binding_api_version,
    resolve_image_binding_deployment,
    resolve_image_generation_api_version,
    resolve_responses_image_api_version,
    resolve_selected_image_deployment_name,
    resolve_selected_image_model_name,
    resolve_shared_image_binding,
)


def settings_for(model_name, deployment_name="image-deployment", **extra):
    """Build the legacy Azure settings shape for a selected image deployment."""
    selected = {"deploymentName": deployment_name}
    if model_name is not None:
        selected["modelName"] = model_name
    return {
        "enable_image_generation": True,
        "image_gen_model": {"selected": [selected]},
        **extra,
    }


def connection_settings_for(
    model_name, deployment_name="image-deployment", *, provider="custom",
    api_type=None, endpoint_url=None, model_fields=None, image_profile=None, **extra,
):
    """Keep registry IDs, wire model names, and deployment names deliberately distinct."""
    endpoint_id = "image-connection"
    model_id = "registry-image-model"
    if endpoint_url is None:
        endpoint_url = {
            "custom": "https://api.openai.com/v1",
            "aoai": "https://images.openai.azure.com",
            "aifoundry": "https://images.services.ai.azure.com",
            "new_foundry": "https://images.services.ai.azure.com",
        }[provider]
    endpoint = {
        "id": endpoint_id,
        "provider": provider,
        "api_type": api_type if api_type is not None else "openai" if provider == "custom" else "azure_openai",
        "enabled": True,
        "connection": {
            "endpoint": endpoint_url,
            "operation_settings": {"image_generation": dict(image_profile or {})},
        },
        "models": [{
            "id": model_id,
            "modelName": model_name,
            "deploymentName": deployment_name,
            "enabled": True,
            **(model_fields or {}),
        }],
    }
    return {
        "enable_image_generation": True,
        "enable_multi_model_endpoints": False,
        "image_generation_model_selection": {
            "endpoint_id": endpoint_id, "model_id": model_id, "provider": provider,
        },
        "model_endpoints": [endpoint],
        **extra,
    }


def expect_connection_error(function, value, code):
    try:
        function(value)
    except AIConnectionError as exc:
        assert exc.code == code, f"Unexpected configuration failure: {exc.code}"
        assert str(exc) == exc.public_message
        return exc
    raise AssertionError(f"{function.__name__} accepted an invalid image configuration")


def test_image_models_keep_the_images_endpoint():
    """Supported dedicated Azure image models retain Images, not a GPT tool route."""
    print("\nTesting that image models keep the images endpoint...")

    for model_name in (
        "gpt-image-1",
        "gpt-image-1-mini",
        "gpt-image-1.5",
        "gpt-image-2",
        "GPT-Image-2",
        "gpt-image-2.5-flare",
        "gpt-image-2.5-sunburst",
    ):
        route = resolve_image_api_route(settings_for(model_name))
        assert route == IMAGE_API_ROUTE_IMAGES, (
            f"{model_name} was routed to {route!r}. It serves /images/generations, and "
            "the Responses route would fail every request against it."
        )

    print("  All supported dedicated image models retain the Images endpoint.")
    return True


def test_direct_openai_chat_models_route_to_the_responses_tool():
    """Verified GPT tools require the explicit Custom direct OpenAI connection identity."""
    print("\nTesting direct OpenAI chat models with the Responses image tool...")

    for model_name in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-6-astra"):
        settings = connection_settings_for(model_name)
        original = copy.deepcopy(settings)
        route = resolve_image_api_route(settings)
        assert route == IMAGE_API_ROUTE_RESPONSES, (
            f"{model_name} was routed to {route!r}. It serves no image endpoint, so the "
            "images route would fail rather than degrade."
        )
        assert resolve_selected_image_model_name(settings) == model_name
        assert resolve_selected_image_deployment_name(settings) == model_name
        assert settings == original

    print("  Cataloged GPT image-tool models route to the Responses image tool.")
    return True


def test_azure_chat_models_cannot_be_routed_by_stale_image_overrides():
    """An invalid Azure image default must fail rather than choosing a different model."""
    for provider in ("aoai", "aifoundry", "new_foundry"):
        for route in ("images", "responses"):
            settings = connection_settings_for(
                "gpt-5.6-sol", provider=provider,
                model_fields={"supportsImageGeneration": True, "image_generation_api": route},
                image_profile={"api": route, "api_version": "v1"},
            )
            settings["model_endpoints"][0]["models"].append({
                "id": "valid-alternative", "modelName": "gpt-image-1",
                "deploymentName": "other-image-deployment", "enabled": True,
            })
            original = copy.deepcopy(settings)
            expect_connection_error(
                resolve_image_api_route, settings, "model_configuration_unavailable"
            )
            assert resolve_selected_image_model_name(settings) == ""
            expect_connection_error(
                resolve_selected_image_deployment_name, settings, "model_configuration_unavailable"
            )
            assert settings == original
    expect_connection_error(
        resolve_image_api_route, settings_for("gpt-5.6-sol"), "model_capability_unavailable"
    )
    return True


def test_retired_and_unverified_models_are_not_invented_image_routes():
    """A historical Images marker or generic GPT tool flag is not an active image profile."""
    for model_name in ("dall-e-3", "dall-e-2", "dalle-2", "some-other-image-model"):
        expect_connection_error(
            resolve_image_api_route, settings_for(model_name), "model_capability_unavailable"
        )
    for model_name in ("dall-e-3", "gpt-5-pro", "o3-mini", "gpt-4.1-mini", "unknown-image-model"):
        expect_connection_error(
            resolve_image_api_route,
            connection_settings_for(model_name),
            "model_configuration_unavailable",
        )
    return True


def test_known_dedicated_models_ignore_stale_responses_route_metadata():
    """Stored operation metadata cannot convert a dedicated image model into a GPT tool."""
    for provider in ("custom", "aoai", "aifoundry", "new_foundry"):
        settings = connection_settings_for(
            "gpt-image-1", provider=provider,
            model_fields={"supportsImageGeneration": True, "image_generation_api": "responses"},
            image_profile={"api": "responses", "api_version": "2025-04-01-preview"},
        )
        original = copy.deepcopy(settings)
        assert resolve_image_api_route(settings) == IMAGE_API_ROUTE_IMAGES
        assert settings == original
    return True


def test_an_unknown_model_stays_on_the_images_endpoint():
    """Settings saved before modelName was stored must not be re-routed on a guess."""
    print("\nTesting the two cases with no model name to classify on...")

    unrecorded = settings_for(None)
    assert resolve_selected_image_model_name(unrecorded) == "", (
        "A deployment saved without modelName should read as unknown."
    )
    assert resolve_image_api_route(unrecorded) == IMAGE_API_ROUTE_IMAGES, (
        "A deployment with no recorded model name was moved off the images endpoint. "
        "Unknown is not the same as 'chat model', and this is what an installation that "
        "has not re-selected its deployment looks like."
    )

    apim = {
        "enable_image_generation": True,
        "enable_image_gen_apim": True,
        "azure_apim_image_gen_deployment": "gateway-images",
    }
    assert resolve_image_api_route(apim) == IMAGE_API_ROUTE_IMAGES, (
        "The APIM route was classified. It records no model name, and what a gateway "
        "publishes decides the shape of the call in any case."
    )
    assert resolve_selected_image_deployment_name(apim) == "gateway-images", (
        "The APIM deployment name should still be readable for reporting."
    )
    assert resolve_selected_image_deployment_name(unrecorded) == "image-deployment", (
        "The direct deployment name should be readable without a model name."
    )

    print("  An unrecorded model name and the APIM route both stay on the images endpoint.")
    return True


def test_direct_responses_do_not_inherit_azure_api_versions():
    """Direct OpenAI uses v1 independently of stale Azure image and chat version metadata."""
    print("\nTesting direct Responses API version isolation...")

    stored_default = {"azure_openai_image_gen_api_version": "2024-12-01-preview"}
    assert resolve_responses_image_api_version(stored_default) == RESPONSES_IMAGE_API_VERSION, (
        "The image section's default API version was used for a Responses call. It "
        "predates the Responses API entirely."
    )

    for unusable in ({}, {"azure_openai_image_gen_api_version": ""}, {"azure_openai_image_gen_api_version": "latest"}):
        assert resolve_responses_image_api_version(unusable) == RESPONSES_IMAGE_API_VERSION, (
            f"An unreadable API version {unusable!r} should fall back to the constant."
        )

    newer = {"azure_openai_image_gen_api_version": "2026-01-01-preview"}
    assert resolve_responses_image_api_version(newer) == "v1"
    assert RESPONSES_IMAGE_API_VERSION == "v1"
    for version in ("2024-12-01-preview", "2026-01-01-preview", "", "latest"):
        settings = connection_settings_for(
            "gpt-5.6-sol",
            image_profile={"api_version": version},
            azure_openai_image_gen_api_version=version,
        )
        settings["model_endpoints"][0]["connection"]["openai_api_version"] = version
        original = copy.deepcopy(settings)
        assert resolve_image_generation_api_version(settings) == "v1"
        assert resolve_image_binding_api_version(resolve_shared_image_binding(settings)) == "v1"
        assert settings == original

    print("  Dated Images/chat API versions never become the Responses image-tool version.")
    return True


def test_model_names_deployments_and_registry_ids_remain_distinct():
    """Use the real Custom model-identity helper without replacing it with a test stub."""
    for provider, api_type, model_name, endpoint_url, expected in (
        ("custom", "openai", "gpt-5.6-sol", "https://api.openai.com/v1", "gpt-5.6-sol"),
        ("custom", "openai", "gpt-image-1", "https://api.openai.com/v1", "gpt-image-1"),
        ("custom", "azure_openai", "gpt-image-1", "https://images.openai.azure.com", "image-deployment"),
        ("aoai", "azure_openai", "gpt-image-1", "https://images.openai.azure.com", "image-deployment"),
        ("new_foundry", "azure_openai", "MAI-Image-2.6", "https://images.services.ai.azure.com", "image-deployment"),
    ):
        settings = connection_settings_for(
            model_name, provider=provider, api_type=api_type, endpoint_url=endpoint_url,
        )
        original = copy.deepcopy(settings)
        binding = resolve_shared_image_binding(settings)
        assert resolve_image_binding_deployment(binding) == expected
        assert resolve_selected_image_deployment_name(settings) == expected
        assert binding.selection["model_id"] == "registry-image-model"
        assert expected != binding.selection["model_id"]
        missing_identity = dict(binding.model)
        missing_identity.pop("modelName" if provider == "custom" and api_type == "openai" else "deploymentName")
        invalid_binding = ModelBinding(
            IMAGE_GENERATION_CAPABILITY, binding.selection, binding.endpoint, missing_identity
        )
        expect_connection_error(
            resolve_image_binding_deployment, invalid_binding, "model_configuration_unavailable"
        )
        assert settings == original
    return True


def test_invalid_shared_defaults_do_not_reactivate_legacy_images():
    """Neither a valid alternative nor preserved legacy settings can replace a saved reference."""
    for selection in (
        {},
        {"endpoint_id": "image-connection", "model_id": "removed-model", "provider": "custom"},
        {"endpoint_id": "image-connection", "model_id": "registry-image-model", "provider": "aoai"},
    ):
        settings = connection_settings_for(
            "gpt-5.6-sol",
            image_generation_model_selection=selection,
            image_gen_model={"selected": [{"modelName": "gpt-image-1", "deploymentName": "legacy-images"}]},
            azure_openai_image_gen_endpoint="https://legacy.openai.azure.com",
        )
        original = copy.deepcopy(settings)
        expect_connection_error(
            resolve_image_api_route, settings, "model_configuration_unavailable"
        )
        assert resolve_selected_image_model_name(settings) == ""
        assert settings == original
    return True


def test_unknown_custom_models_need_explicit_compatible_routes():
    """An unknown gateway gets only the explicitly declared implemented operation."""
    for route in ("images", "responses"):
        settings = connection_settings_for(
            "private-image-model", endpoint_url="https://gateway.example.invalid/team/v1",
            model_fields={"supportsImageGeneration": True},
        )
        expect_connection_error(
            resolve_image_api_route, settings, "model_configuration_unavailable"
        )
        settings["model_endpoints"][0]["models"][0]["image_generation_api"] = route
        assert resolve_image_api_route(settings) == route
        assert resolve_selected_image_deployment_name(settings) == "private-image-model"
    return True


def test_foundry_models_use_their_own_routes_and_preserve_gateway_prefixes():
    """MAI/FLUX route selection does not pretend their APIs are Azure Responses."""
    for model_name, route, version, suffix in (
        ("MAI-Image-2.6", IMAGE_API_ROUTE_MAI, "v1", "mai/v1/"),
        ("FLUX.2-pro", IMAGE_API_ROUTE_FLUX, "preview", "providers/blackforestlabs/v1/"),
        ("FLUX.1-Kontext-pro", IMAGE_API_ROUTE_FLUX, "preview", "providers/blackforestlabs/v1/"),
    ):
        settings = connection_settings_for(model_name, provider="new_foundry")
        assert resolve_image_api_route(settings) == route
        assert resolve_image_generation_api_version(settings) == version
        assert resolve_selected_image_deployment_name(settings) == "image-deployment"
        assert build_image_api_base_url(
            "https://images.services.ai.azure.com/api/projects/studio", route,
        ) == f"https://images.services.ai.azure.com/{suffix}"
        assert build_image_api_base_url(
            "https://gateway.example.invalid/team/openai", route,
        ) == f"https://gateway.example.invalid/team/{suffix}"
    return True


def test_only_stated_image_options_are_sent():
    """The tool defaults each option itself; a guessed value fails the whole request."""
    print("\nTesting the image_generation tool spec...")

    assert build_image_generation_tool() == {"type": "image_generation"}, (
        "An unset control was filled in with a guess."
    )

    tool = build_image_generation_tool(size="1024x1536", quality="high", background="transparent")
    assert tool == {
        "type": "image_generation",
        "size": "1024x1536",
        "quality": "high",
        "background": "transparent",
    }, f"Stated options were not carried onto the tool: {tool!r}"

    partial = build_image_generation_tool(size="1024x1024", quality="", background="")
    assert partial == {"type": "image_generation", "size": "1024x1024"}, (
        f"Empty options were sent as values: {partial!r}"
    )

    print("  Only stated options reach the tool.")
    return True


def test_a_generated_image_is_read_out_of_the_responses_output():
    """Returning the same data URL is what keeps every downstream consumer route-agnostic."""
    print("\nTesting extraction from a Responses result...")

    response = {
        "output": [
            {"type": "reasoning", "id": "rs_1", "summary": []},
            {"type": "image_generation_call", "id": "ig_1", "status": "completed", "result": "QUJD"},
            {"type": "message", "id": "msg_1", "content": []},
        ]
    }
    source = extract_responses_image_source(response)
    assert source == "data:image/png;base64,QUJD", (
        f"The image was not read out of the output items: {source!r}"
    )

    webp = {
        "output": [
            {
                "type": "image_generation_call",
                "id": "ig_2",
                "status": "completed",
                "result": "QUJD",
                "output_format": "webp",
            }
        ]
    }
    assert extract_responses_image_source(webp) == "data:image/webp;base64,QUJD", (
        "A stated output format was ignored, so the stored image would claim the wrong type."
    )

    unknown_format = {
        "output": [
            {"type": "image_generation_call", "id": "ig_3", "result": "QUJD", "output_format": "tiff"}
        ]
    }
    assert extract_responses_image_source(unknown_format) == "data:image/png;base64,QUJD", (
        f"An unrecognised format should fall back to {DEFAULT_RESPONSES_IMAGE_FORMAT}."
    )

    print("  The image is read as a data URL, honouring the stated format.")
    return True


def test_a_reply_without_an_image_is_reported_as_empty():
    """'Answered without calling the tool' is a different outcome from 'the call failed'."""
    print("\nTesting a Responses result that carries no image...")

    for barren in (
        {"output": []},
        {"output": [{"type": "message", "id": "msg_1", "content": []}]},
        {"output": [{"type": "image_generation_call", "id": "ig_1", "status": "completed", "result": None}]},
        {},
        {"output": "not a list"},
    ):
        assert extract_responses_image_source(barren) == "", (
            f"A result with no usable image returned something: {barren!r}"
        )

    print("  All 5 imageless results read as empty rather than raising.")
    return True


def test_failed_and_incomplete_responses_are_not_images():
    """A failed tool or incomplete outer response must not persist partial image bytes."""
    for response in (
        {"status": "incomplete", "output": [{"type": "image_generation_call", "result": "QUJD"}]},
        {"status": "failed", "output": [{"type": "image_generation_call", "result": "QUJD"}]},
        {"output": [{"type": "image_generation_call", "status": "failed", "result": "QUJD"}]},
        {"output": [{"type": "image_generation_call", "status": "in_progress", "result": "QUJD"}]},
    ):
        try:
            extract_responses_image_source(response)
        except ImageGenerationError as exc:
            assert exc.code == "image_generation_incomplete"
            assert exc.status_code >= 500
        else:
            raise AssertionError("A non-successful image operation was accepted")
    return True


def test_discovery_offers_what_could_actually_produce_an_image():
    """Discovery uses the selected endpoint's provider, not publisher-wide tool flags."""
    print("\nTesting image deployment discovery...")

    openai = connection_settings_for("gpt-5.6-sol")["model_endpoints"][0]
    foundry = connection_settings_for("MAI-Image-2.6", provider="new_foundry")["model_endpoints"][0]
    for model_name in ("gpt-image-1", "gpt-image-2", "gpt-image-2.5-flare", "gpt-image-2.5-sunburst"):
        assert is_image_capable_model_name(model_name), (
            f"{model_name} was excluded from discovery, so it could never be selected."
        )
        assert is_image_capable_model_name(model_name, "custom", endpoint=openai)
        assert is_image_capable_model_name(model_name, "new_foundry", endpoint=foundry)

    for model_name in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-6-astra"):
        assert is_image_capable_model_name(model_name, "custom", endpoint=openai)
        assert not is_image_capable_model_name(model_name)
        assert not is_image_capable_model_name(model_name, "new_foundry", endpoint=foundry)

    for model_name in ("MAI-Image-2.6", "FLUX.2-pro", "FLUX.1-Kontext-pro", "FLUX-1.1-pro"):
        assert is_image_capable_model_name(model_name, "new_foundry", endpoint=foundry)
        assert not is_image_capable_model_name(model_name)
        assert not is_image_capable_model_name(model_name, "custom", endpoint=openai)

    for model_name in (
        "text-embedding-3-large", "text-embedding-ada-002", "", None, "whisper",
        "some-other-image-model", "gpt-not-in-the-image-tool-catalog",
        "dall-e-3", "gpt-5-pro", "o3-mini", "gpt-4.1-mini",
    ):
        assert not is_image_capable_model_name(model_name), (
            f"{model_name!r} was offered as an image model. It can produce no image on "
            "the selected provider, so selecting it would fail at the point of use."
        )
        assert not is_image_capable_model_name(model_name, "custom", endpoint=openai)

    print("  Discovery respects verified provider profiles and excludes retired or unverified models.")
    return True


if __name__ == "__main__":
    assert_app_version_at_least("0.261.088")

    tests = [
        test_image_models_keep_the_images_endpoint,
        test_direct_openai_chat_models_route_to_the_responses_tool,
        test_azure_chat_models_cannot_be_routed_by_stale_image_overrides,
        test_retired_and_unverified_models_are_not_invented_image_routes,
        test_known_dedicated_models_ignore_stale_responses_route_metadata,
        test_an_unknown_model_stays_on_the_images_endpoint,
        test_direct_responses_do_not_inherit_azure_api_versions,
        test_model_names_deployments_and_registry_ids_remain_distinct,
        test_invalid_shared_defaults_do_not_reactivate_legacy_images,
        test_unknown_custom_models_need_explicit_compatible_routes,
        test_foundry_models_use_their_own_routes_and_preserve_gateway_prefixes,
        test_only_stated_image_options_are_sent,
        test_a_generated_image_is_read_out_of_the_responses_output,
        test_a_reply_without_an_image_is_reported_as_empty,
        test_failed_and_incomplete_responses_are_not_images,
        test_discovery_offers_what_could_actually_produce_an_image,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
