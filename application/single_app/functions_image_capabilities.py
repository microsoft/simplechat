# functions_image_capabilities.py
"""Provider-qualified image operations, independent of application hosting and credentials."""

import re
from collections.abc import Mapping
from urllib.parse import urlsplit

from functions_model_capabilities import get_image_operation_profile, get_model_catalog_capabilities


IMAGE_APIS = ("images", "responses", "mai", "flux")
IMAGE_PROVIDERS = ("aoai", "aifoundry", "new_foundry", "custom")
AZURE_IMAGE_POLICY_REASON = (
    "SimpleChat uses dedicated image models on Azure OpenAI and Foundry. "
    "Choose a GPT Image, MAI Image, or supported Foundry FLUX deployment; "
    "GPT chat models can use the image tool only through a compatible direct OpenAI Custom connection."
)
PROVIDER_LABELS = {
    "openai": "OpenAI (direct)",
    "azure_openai": "Azure OpenAI",
    "foundry": "Microsoft Foundry",
    "custom": "Custom",
}
CLOUD_LABELS = {
    "commercial": "Commercial",
    "government": "Azure Government",
    "unknown": "Cloud not identified",
}
_CHAT_MODEL_PATTERN = re.compile(r"^(?:gpt[-_.]?\d|o\d(?:[-_.]|$))", re.IGNORECASE)


def _mapping(value):
    return value if isinstance(value, Mapping) else {}


def _text(value):
    return value.strip() if isinstance(value, str) else ""


def _flag(model, *names):
    for name in names:
        value = _mapping(model).get(name)
        if isinstance(value, bool):
            return value
    return None


def image_model_name(model):
    if isinstance(model, str):
        return model.strip()
    for name in ("modelName", "behavior_name", "deploymentName", "deployment", "name"):
        value = _text(_mapping(model).get(name))
        if value:
            return value
    return ""


def _host_has_suffix(hostname, suffix):
    return hostname == suffix or hostname.endswith(f".{suffix}")


def resolve_image_endpoint_context(endpoint=None, provider="aoai"):
    """Identify service delivery, never using the app environment or token authority."""
    endpoint = _mapping(endpoint)
    connection = _mapping(endpoint.get("connection"))
    provider = _text(endpoint.get("provider") or provider).lower()
    api_type = _text(endpoint.get("api_type")).lower().replace("-", "_")
    try:
        hostname = (urlsplit(_text(connection.get("endpoint"))).hostname or "").lower().rstrip(".")
    except ValueError:
        hostname = ""
    azure_commercial = any(_host_has_suffix(hostname, suffix) for suffix in (
        "openai.azure.com", "services.ai.azure.com", "cognitiveservices.azure.com",
        "api.cognitive.microsoft.com",
    ))
    azure_government = any(_host_has_suffix(hostname, suffix) for suffix in (
        "openai.azure.us", "services.ai.azure.us", "cognitiveservices.azure.us",
        "api.cognitive.microsoft.us",
    ))
    cloud = "government" if azure_government else "commercial" if azure_commercial else "unknown"
    explicit_cloud = _text(connection.get("image_cloud")).lower()
    if cloud == "unknown" and explicit_cloud in ("commercial", "government"):
        cloud = explicit_cloud
    service = ""
    if provider == "aoai":
        service = "azure_openai"
    elif provider in ("aifoundry", "new_foundry"):
        service = "foundry"
    elif provider == "custom":
        if api_type == "azure_openai" or (api_type == "openai" and (azure_commercial or azure_government)):
            service = "azure_openai"
        elif api_type == "openai":
            if hostname == "api.openai.com":
                service, cloud = "openai", "commercial"
            elif connection.get("image_provider") == "openai":
                service = "openai"
            else:
                service = "custom"
    if hostname == "api.openai.com" and not (provider == "custom" and api_type == "openai"):
        service = ""
        cloud = "commercial"
    return {
        "connection_provider": provider,
        "provider": service,
        "provider_label": PROVIDER_LABELS.get(service, "Unsupported image provider"),
        "cloud": cloud,
        "cloud_label": CLOUD_LABELS[cloud],
        "api_type": api_type,
    }


def _description(model, context, *, supported=False, source="unknown", reason="", api=""):
    return {
        "supported": supported,
        "source": source,
        "reason": reason,
        "api": api,
        "model_name": image_model_name(model),
        "publisher": "",
        "connection_provider": context["connection_provider"],
        "provider": context["provider"],
        "provider_label": context["provider_label"],
        "cloud": context["cloud"],
        "cloud_label": context["cloud_label"],
        "availability": "unknown",
        "availability_reason": "",
        "lifecycle": "",
        "editing": False,
        "masking": False,
        "mode": "unavailable",
        "sizes": [],
        "qualities": [],
        "backgrounds": [],
        "input_formats": [],
        "output_formats": [],
        "model_path": "",
        "transport": "native",
        "max_mask_bytes": 4 * 1024 * 1024,
        "min_dimension": 0,
        "max_pixels": 0,
    }


def resolve_image_model_capability(model, endpoint=None, provider="aoai"):
    """Intersect catalog facts, the implemented adapter, and explicit compatible metadata."""
    endpoint = _mapping(endpoint)
    context = resolve_image_endpoint_context(endpoint, provider)
    service = context["provider"]
    result = _description(model, context)
    if not service:
        result.update(source="provider", reason="This connection type has no supported image adapter.")
        return result

    declared = _flag(model, "supportsImageGeneration", "supports_image_generation")
    if declared is False:
        result.update(source="declared", reason="Image generation is not supported by this model.")
        return result
    catalog = get_model_catalog_capabilities(model) or {}
    if catalog.get("generatesEmbeddings") is True and catalog.get("generatesImages") is False:
        result.update(source="model", reason="This embedding model does not generate images.")
        return result
    result["publisher"] = _text(catalog.get("publisher"))
    profiles = _mapping(catalog.get("imageProfiles"))
    profile_service = "azure_openai" if service == "foundry" and profiles.get("azure_openai") else service
    lifecycle = _mapping(catalog.get("imageLifecycle")).get(profile_service, "")
    result["lifecycle"] = lifecycle
    if lifecycle == "retired":
        result.update(
            source="lifecycle", availability="unavailable",
            reason="This image model is retired on the configured provider. Choose an available image model.",
        )
        return result

    profile_id = profiles.get(profile_service)
    profile = get_image_operation_profile(profile_id) if isinstance(profile_id, str) else None
    route = _text(_mapping(model).get("image_generation_api"))
    azure_delivery = service in ("azure_openai", "foundry")
    chat_model = bool(_CHAT_MODEL_PATTERN.search(image_model_name(model))) or (
        catalog.get("generatesText") is True and catalog.get("generatesImages") is not True
    )
    if azure_delivery and (chat_model or (route == "responses" and profile is None)):
        result.update(source="policy", reason=AZURE_IMAGE_POLICY_REASON)
        return result
    if service == "azure_openai" and context["connection_provider"] == "custom" and context["api_type"] == "openai":
        result.update(
            source="provider",
            reason="Use the Azure OpenAI API type for this Azure endpoint so its deployment identity and image route are preserved.",
        )
        return result
    if profile is None and profiles and service != "custom":
        result.update(source="provider", reason="This image model has no documented image adapter on the configured provider.")
        return result

    if profile is None and declared is True:
        catalog_flag = {"images": "generatesImages", "responses": "imageGenerationTool"}.get(route)
        if catalog_flag and catalog.get(catalog_flag) is False:
            result.update(
                source="catalog",
                reason="The catalog does not support this model on the requested image API. A declaration cannot override a known incompatibility.",
            )
            return result
        legacy_images = (
            _text(endpoint.get("migration_source")).startswith("legacy_image_")
            and route == "images" and not catalog
        )
        custom_operation = context["connection_provider"] == "custom" and route in ("images", "responses")
        if not (legacy_images or custom_operation):
            result.update(
                source="provider",
                reason="Declare a compatible image API on a Custom connection, or select a cataloged dedicated image model.",
            )
            return result
        if azure_delivery and route != "images":
            result.update(source="policy", reason=AZURE_IMAGE_POLICY_REASON)
            return result
        profile = {
            "api": route,
            "editing": _flag(model, "supportsImageEditing", "supports_image_editing") is True,
            "masking": _flag(model, "supportsImageMasking", "supports_image_masking") is True,
            "sizes": [], "qualities": [], "backgrounds": [],
            "inputFormats": ["image/png", "image/jpeg"],
            "outputFormats": ["image/png", "image/jpeg", "image/webp"],
            "availability": {},
        }
        if profile["masking"] and not profile["editing"]:
            result.update(source="declared", reason="Masked image editing also requires declared image-editing support.")
            return result
        result["source"] = "legacy" if legacy_images else "declared"
    elif profile is None:
        result.update(
            source="provider" if azure_delivery else "unknown",
            reason=(
                AZURE_IMAGE_POLICY_REASON if azure_delivery else
                "Image generation has not been established for this model and endpoint. "
                "An OpenAI-compatible API or a GPT model name alone is not sufficient."
            ),
        )
        return result
    else:
        result["source"] = "catalog"

    api = profile.get("api")
    if api not in IMAGE_APIS or (azure_delivery and api == "responses"):
        result.update(source="provider", reason="The model has no compatible image operation on this provider.")
        return result
    if api in ("mai", "flux") and service != "foundry":
        result.update(source="provider", reason="This image model requires its Foundry provider API.")
        return result
    if not isinstance(profile.get("editing"), bool) or not isinstance(profile.get("masking"), bool):
        result.update(source="catalog", reason="The image operation metadata is invalid.")
        return result
    if profile["masking"] and not profile["editing"]:
        result.update(source="catalog", reason="The image operation has inconsistent editing metadata.")
        return result
    for name in ("sizes", "qualities", "backgrounds", "inputFormats", "outputFormats"):
        value = profile.get(name, [])
        if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
            result.update(source="catalog", reason="The image operation options are invalid.")
            return result
    for name in ("maxMaskBytes", "minDimension", "maxPixels"):
        if name in profile and (type(profile[name]) is not int or profile[name] <= 0):
            result.update(source="catalog", reason="The image operation limits are invalid.")
            return result
    model_path = profile.get("modelPath", "")
    transport = profile.get("transport", "native")
    if transport not in ("native", "openai_images") or (
        transport == "openai_images" and (api != "flux" or model_path != "flux-kontext-pro")
    ):
        result.update(source="catalog", reason="The image transport metadata is invalid.")
        return result
    if api == "flux" and model_path not in ("flux-2-pro", "flux-2-flex", "flux-kontext-pro", "flux-pro-1.1"):
        result.update(source="catalog", reason="The Foundry FLUX operation path is invalid.")
        return result

    availability_map = profile.get("availability")
    if not isinstance(availability_map, Mapping) or any(
        value not in ("documented", "unknown", "unavailable") for value in availability_map.values()
    ):
        result.update(source="catalog", reason="The image availability metadata is invalid.")
        return result
    availability = availability_map.get(context["cloud"], "unknown")
    if availability == "unavailable":
        result.update(availability=availability, source="provider", reason="This image model is unavailable on the endpoint's provider/cloud.")
        return result
    editing = profile["editing"] and _flag(model, "supportsImageEditing", "supports_image_editing") is not False
    masking = profile["masking"] and editing and _flag(model, "supportsImageMasking", "supports_image_masking") is not False
    result.update(
        supported=True, api=api, editing=editing, masking=masking,
        mode="masked" if masking else "edit" if editing else "regenerate",
        availability=availability,
        availability_reason=(
            "Model availability in this endpoint cloud is not established by the reviewed provider documentation."
            if availability == "unknown" else ""
        ),
        sizes=list(profile.get("sizes", [])),
        qualities=list(profile.get("qualities", [])),
        backgrounds=list(profile.get("backgrounds", [])),
        input_formats=list(profile.get("inputFormats", [])),
        output_formats=list(profile.get("outputFormats", [])),
        model_path=model_path,
        transport=transport,
        max_mask_bytes=profile.get("maxMaskBytes", result["max_mask_bytes"]),
        min_dimension=profile.get("minDimension", 0),
        max_pixels=profile.get("maxPixels", 0),
    )
    return result


def validate_image_options(capability, size="", quality="", background=""):
    """Reject unsupported explicit options instead of quietly changing the requested image."""
    options = {"size": size, "quality": quality, "background": background}
    for name, allowed_key in (("size", "sizes"), ("quality", "qualities"), ("background", "backgrounds")):
        value = options[name]
        if not isinstance(value, str):
            raise ValueError(f"Image {name} must be text.")
        if value and value not in capability.get(allowed_key, []):
            raise ValueError(f"The selected image model does not support that {name}.")
    if size:
        match = re.fullmatch(r"(\d+)x(\d+)", size)
        if not match:
            raise ValueError("The image dimensions are invalid.")
        width, height = (int(part) for part in match.groups())
        minimum = capability.get("min_dimension", 0)
        maximum = capability.get("max_pixels", 0)
        if width < minimum or height < minimum or (maximum and width * height > maximum):
            raise ValueError("The image dimensions exceed the selected model's limits.")
    return options
