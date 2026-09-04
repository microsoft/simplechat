#!/usr/bin/env python3
# test_image_generation_responses_route.py
"""
Functional test for image generation through the Responses image tool.
Version: 0.261.087
Implemented in: 0.261.087

Azure OpenAI produces images two different ways. ``gpt-image-*`` and the legacy
``dall-e-*`` models serve ``/images/generations``; a chat model such as ``gpt-5.6-*``
serves no image endpoint at all and can only produce one through the Responses API's
hosted ``image_generation`` tool. SimpleChat now selects between the two from the model
name already stored alongside the chosen deployment.

The risk this test covers is not that the new route fails -- that surfaces immediately --
but that it captures deployments it should have left alone. Everything selectable before
the Responses route existed answers on the images endpoint, and moving one of those onto
a route it cannot serve would break image generation for an installation that changed
nothing.

So these checks pin the classification in both directions, the two cases that must stay on
the images endpoint despite carrying no usable model name, the API version substitution
that makes the Responses call routable at all, and the response reading that lets
everything downstream stay unaware of which route was taken.
"""

import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least

sys.path.append(str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_image_api_route import (  # noqa: E402  - path set above
    DEFAULT_RESPONSES_IMAGE_FORMAT,
    IMAGE_API_ROUTE_IMAGES,
    IMAGE_API_ROUTE_RESPONSES,
    RESPONSES_IMAGE_API_VERSION,
    build_image_generation_tool,
    extract_responses_image_source,
    is_image_capable_model_name,
    resolve_image_api_route,
    resolve_responses_image_api_version,
    resolve_selected_image_deployment_name,
    resolve_selected_image_model_name,
)


def settings_for(model_name, deployment_name="image-deployment", **extra):
    """Build the settings shape admin saves for a selected image deployment."""
    selected = {"deploymentName": deployment_name}
    if model_name is not None:
        selected["modelName"] = model_name
    return {
        "enable_image_generation": True,
        "image_gen_model": {"selected": [selected]},
        **extra,
    }


def test_image_models_keep_the_images_endpoint():
    """Every deployment selectable before this change must route exactly as it did."""
    print("\nTesting that image models keep the images endpoint...")

    for model_name in (
        "gpt-image-1",
        "gpt-image-1-mini",
        "gpt-image-1.5",
        "gpt-image-2",
        "GPT-Image-2",
        "dall-e-3",
        "dall-e-2",
        "dalle-2",
        # Anything the old discovery filter matched on has to keep working, or this
        # change would take a selectable deployment and route it somewhere it cannot go.
        "some-other-image-model",
    ):
        route = resolve_image_api_route(settings_for(model_name))
        assert route == IMAGE_API_ROUTE_IMAGES, (
            f"{model_name} was routed to {route!r}. It serves /images/generations, and "
            "the Responses route would fail every request against it."
        )

    print("  All 9 image models route to the images endpoint.")
    return True


def test_chat_models_route_to_the_responses_tool():
    """A chat deployment is the only thing some tenants have, and has no image endpoint."""
    print("\nTesting that chat models route to the Responses image tool...")

    for model_name in ("gpt-5.6-sol", "gpt-5.6-terra", "gpt-5.6-luna", "gpt-5", "gpt-4o", "o3"):
        route = resolve_image_api_route(settings_for(model_name))
        assert route == IMAGE_API_ROUTE_RESPONSES, (
            f"{model_name} was routed to {route!r}. It serves no image endpoint, so the "
            "images route would fail rather than degrade."
        )

    print("  All 6 chat models route to the Responses image tool.")
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


def test_the_responses_route_does_not_inherit_an_unusable_api_version():
    """The stored default predates the Responses API, so honouring it would fail every call."""
    print("\nTesting the Responses API version substitution...")

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
    assert resolve_responses_image_api_version(newer) == "2026-01-01-preview", (
        "A deliberately pinned newer version was overridden by a constant that will age."
    )

    print(f"  Older and unreadable versions become {RESPONSES_IMAGE_API_VERSION}; newer ones survive.")
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
        {"output": [{"type": "image_generation_call", "id": "ig_1", "status": "failed", "result": None}]},
        {},
        {"output": "not a list"},
    ):
        assert extract_responses_image_source(barren) == "", (
            f"A result with no usable image returned something: {barren!r}"
        )

    print("  All 5 imageless results read as empty rather than raising.")
    return True


def test_discovery_offers_what_could_actually_produce_an_image():
    """Discovery answers 'is this worth offering', which both routes now widen."""
    print("\nTesting image deployment discovery...")

    for model_name in ("gpt-image-1", "gpt-image-2", "dall-e-3", "gpt-5.6-sol", "gpt-4o", "o3", "gpt-5"):
        assert is_image_capable_model_name(model_name), (
            f"{model_name} was excluded from discovery, so it could never be selected."
        )

    # The old filter matched any name containing "image". Discovery must stay a superset
    # of what it offered, or this change would remove a working configuration's model
    # from the list it was chosen from.
    assert is_image_capable_model_name("some-other-image-model"), (
        "A deployment the previous filter offered is no longer discoverable."
    )

    for model_name in ("text-embedding-3-large", "text-embedding-ada-002", "", None, "whisper"):
        assert not is_image_capable_model_name(model_name), (
            f"{model_name!r} was offered as an image model. It can produce no image on "
            "either route, so selecting it would fail at the point of use."
        )

    print("  Image and chat models are offered; embedding and audio models are not.")
    return True


if __name__ == "__main__":
    assert_app_version_at_least("0.261.087")

    tests = [
        test_image_models_keep_the_images_endpoint,
        test_chat_models_route_to_the_responses_tool,
        test_an_unknown_model_stays_on_the_images_endpoint,
        test_the_responses_route_does_not_inherit_an_unusable_api_version,
        test_only_stated_image_options_are_sent,
        test_a_generated_image_is_read_out_of_the_responses_output,
        test_a_reply_without_an_image_is_reported_as_empty,
        test_discovery_offers_what_could_actually_produce_an_image,
    ]

    results = []
    for test in tests:
        try:
            results.append(bool(test()))
        except Exception as exc:
            print(f"FAILED {test.__name__}: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
