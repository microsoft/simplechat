# functions_image_api_route.py

"""Which API an image deployment is reached through, and how to read its answer.

Azure OpenAI produces images two different ways, and the difference is not a detail that
can be hidden behind one call.

``gpt-image-*`` and the legacy ``dall-e-*`` models serve ``/images/generations``: a
deployment is asked for an image and answers with one. That is the route SimpleChat has
always used, and it remains the route for every deployment that can take it.

A general chat model -- ``gpt-5.6-*``, ``gpt-4o`` and their relations -- serves no such
endpoint. It can still produce an image, but only through the Responses API's hosted
``image_generation`` tool, which is a different request, a different response shape and a
different API version. That route exists here because a deployment of one of those models
is sometimes the only thing a tenant has: where ``gpt-image-*`` is unavailable, a chat
deployment is the difference between image generation working and not being offered.

The route is derived from the model name already stored alongside the selected
deployment rather than asked of the administrator, because it is not a preference. A
deployment serves one of these APIs and not the other, and a wrong answer is a failed
request rather than a degraded one.

Two cases deliberately keep the images endpoint rather than being guessed at:

- A deployment whose model name was never recorded. Settings saved before ``modelName``
  was stored have none, and treating "unknown" as "chat model" would move a working
  deployment onto a route it cannot serve.
- The API Management route, which records a deployment name and nothing else. There is
  no model name to classify on, and a gateway's published operation is what decides the
  shape of the call in any case.

Nothing here imports application configuration or an Azure client, so the classification
and the response reading can be exercised directly.
"""

import json
import re


# The two ways an image is produced. Named rather than expressed as a boolean because
# "not the images endpoint" is not a description of anything.
IMAGE_API_ROUTE_IMAGES = 'images'
IMAGE_API_ROUTE_RESPONSES = 'responses'

# Models that serve /images/generations. Matched as substrings because a deployment
# reports a model name like ``gpt-image-1.5`` or ``dall-e-3`` and the family is what
# decides the route, not the version. ``image`` is deliberately the broad form rather than
# ``gpt-image``: it is what the discovery filter has always matched on, so narrowing it
# here would drop a deployment that was previously selectable and send it to a route it
# cannot serve.
IMAGES_ENDPOINT_MODEL_MARKERS = ('image', 'dall-e', 'dalle')

# Deployments that produce vectors and nothing else. Named so discovery can rule them out
# before the general chat-model test below, which they would otherwise pass on the strength
# of an unrelated substring.
EMBEDDING_MODEL_MARKERS = ('embedding', 'ada')

# A chat model recognisable to Azure OpenAI. The same shape the chat-model discovery filter
# uses, so a deployment cannot be a chat model for one list and not the other.
_CHAT_MODEL_SERIES_PATTERN = re.compile(r'o\d+')

# The earliest Azure preview that routes /responses with hosted tools. The image
# section's own API version governs /images/generations and /images/edits, and defaults
# to a version predating the Responses API entirely, so it cannot be used here. An
# administrator who has pinned something newer is honoured; anything older is replaced
# rather than reported, because the setting was never about this route.
RESPONSES_IMAGE_API_VERSION = '2025-04-01-preview'

# What the image_generation tool call answers with when no format is stated.
DEFAULT_RESPONSES_IMAGE_FORMAT = 'png'

_IMAGE_FORMAT_MIME_TYPES = {
    'png': 'image/png',
    'webp': 'image/webp',
    'jpeg': 'image/jpeg',
    'jpg': 'image/jpeg',
}


def resolve_selected_image_model_name(settings):
    """Return the model behind the selected image deployment, or '' when it is not recorded.

    Admin settings persist ``{deploymentName, modelName}`` for the chosen deployment, but an
    APIM route records only a deployment name and settings saved before ``modelName`` was added
    have none either. An empty answer therefore means "unknown", not "none".
    """
    if not isinstance(settings, dict):
        return ''

    if settings.get('enable_image_gen_apim', False):
        return ''

    selected = (settings.get('image_gen_model') or {}).get('selected') or []
    if not selected or not isinstance(selected[0], dict):
        return ''
    return str(selected[0].get('modelName') or '').strip()


def resolve_selected_image_deployment_name(settings):
    """Return the deployment name image requests are addressed to, or '' when none is set.

    The APIM route names its deployment directly; the direct route names it inside the
    stored catalog entry. Both are the same fact, and callers that only need to say which
    deployment answered should not have to know which route produced it.
    """
    if not isinstance(settings, dict):
        return ''

    if settings.get('enable_image_gen_apim', False):
        return str(settings.get('azure_apim_image_gen_deployment') or '').strip()

    selected = (settings.get('image_gen_model') or {}).get('selected') or []
    if not selected or not isinstance(selected[0], dict):
        return ''
    return str(selected[0].get('deploymentName') or '').strip()


def resolve_image_api_route(settings):
    """Return which API the selected image deployment is reached through.

    Defaults to the images endpoint. Every deployment selectable before the Responses
    route existed answers to it, so an unrecognised or unrecorded model name leaves an
    existing configuration exactly where it was.
    """
    model_name = resolve_selected_image_model_name(settings).lower()
    if not model_name:
        return IMAGE_API_ROUTE_IMAGES

    if any(marker in model_name for marker in IMAGES_ENDPOINT_MODEL_MARKERS):
        return IMAGE_API_ROUTE_IMAGES

    return IMAGE_API_ROUTE_RESPONSES


def is_image_capable_model_name(model_name):
    """Return whether a deployment of this model could produce an image at all.

    Used by discovery, so it answers the question an administrator is actually asking
    when they press Fetch: is this deployment worth offering as the image model. A
    gpt-image or DALL-E model qualifies through the images endpoint; a chat model
    qualifies through the Responses image tool. An embedding deployment qualifies through
    neither, and is ruled out before the chat test rather than after, because its name can
    otherwise satisfy it.
    """
    normalized_model = str(model_name or '').strip().lower()
    if not normalized_model:
        return False

    if any(marker in normalized_model for marker in IMAGES_ENDPOINT_MODEL_MARKERS):
        return True

    if any(marker in normalized_model for marker in EMBEDDING_MODEL_MARKERS):
        return False

    return 'gpt' in normalized_model or bool(_CHAT_MODEL_SERIES_PATTERN.search(normalized_model))


def _parse_preview_api_version(api_version):
    """Return an Azure API version as a comparable date tuple, or None."""
    parts = str(api_version or '').strip().split('-')
    if len(parts) < 3:
        return None
    try:
        return tuple(int(part) for part in parts[:3])
    except (TypeError, ValueError):
        return None


def resolve_responses_image_api_version(settings):
    """Return the API version the Responses image route should be called with.

    The stored image API version wins only when it is newer, which keeps a deliberate pin
    -- a tenant on a later preview, or one whose gateway publishes a specific version --
    from being overridden by a constant that will age.
    """
    settings = settings if isinstance(settings, dict) else {}
    stored = _parse_preview_api_version(settings.get('azure_openai_image_gen_api_version'))
    minimum = _parse_preview_api_version(RESPONSES_IMAGE_API_VERSION)

    if stored and minimum and stored > minimum:
        return str(settings.get('azure_openai_image_gen_api_version')).strip()
    return RESPONSES_IMAGE_API_VERSION


def build_image_generation_tool(size='', quality='', background=''):
    """Describe the hosted image_generation tool for a Responses request.

    Only stated options are sent. The tool defaults each of these itself, and naming a
    value the deployment does not accept fails the request, so an unset control is left
    unset rather than filled in with a guess.
    """
    tool = {'type': 'image_generation'}
    if size:
        tool['size'] = size
    if quality:
        tool['quality'] = quality
    if background:
        tool['background'] = background
    return tool


def _as_response_dict(response):
    """Return a Responses result as a plain dict, whether it arrived as one or as a model."""
    if isinstance(response, dict):
        return response
    if hasattr(response, 'model_dump_json'):
        return json.loads(response.model_dump_json())
    if hasattr(response, 'model_dump'):
        return response.model_dump()
    raise ValueError('Image response could not be read')


def extract_responses_image_source(response):
    """Return a data URL for the image a Responses result carries, or '' when it has none.

    The image arrives as an ``image_generation_call`` item in ``output``, alongside the
    reasoning and message items the model also produced, and carries base64 rather than a
    URL. Returning the same data-URL string the images endpoint path produces is what lets
    everything downstream -- blob storage, proposals, revisions, the lightbox -- stay
    unaware of which route was taken.

    An empty answer is returned rather than raised because "the model replied without
    calling the tool" is a distinct outcome from "the call failed", and only the caller
    knows which message suits.
    """
    response_dict = _as_response_dict(response)
    output_items = response_dict.get('output')
    if not isinstance(output_items, list):
        return ''

    for item in output_items:
        if not isinstance(item, dict) or item.get('type') != 'image_generation_call':
            continue

        encoded_image = item.get('result')
        if not encoded_image:
            continue

        image_format = str(item.get('output_format') or DEFAULT_RESPONSES_IMAGE_FORMAT).lower()
        mime_type = _IMAGE_FORMAT_MIME_TYPES.get(
            image_format,
            _IMAGE_FORMAT_MIME_TYPES[DEFAULT_RESPONSES_IMAGE_FORMAT],
        )
        return f'data:{mime_type};base64,{encoded_image}'

    return ''
