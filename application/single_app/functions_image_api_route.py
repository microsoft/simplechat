# functions_image_api_route.py

"""Pure image route, shared-binding, and response validation helpers.

Dedicated image models use Images; compatible GPT deployments use the v1 Responses
image tool. Technical support comes from the shared capability catalog or explicit
model metadata, not from generic tool or vision support. Neither proves live service
availability. Unmigrated legacy image settings retain their existing Images route
when the underlying model was never recorded.
"""

import base64
import binascii
import json
import re
from urllib.parse import quote, urlsplit, urlunsplit

from functions_ai_connections import (
    AIConnectionError,
    IMAGE_GENERATION_CAPABILITY,
    IMAGE_SELECTION_KEY,
    get_connection_operation_settings,
    image_settings_use_connections,
    resolve_capability_binding,
    resolve_model_capability,
    supports_model_capability,
)


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

RESPONSES_IMAGE_API_VERSION = 'v1'
# New shared connections support both Images generations and edits without inheriting
# a chat API version. Explicit imported image profiles always take precedence.
DEFAULT_IMAGES_API_VERSION = '2025-04-01-preview'
LEGACY_DEFAULT_IMAGES_API_VERSION = '2024-12-01-preview'

# What the image_generation tool call answers with when no format is stated.
DEFAULT_RESPONSES_IMAGE_FORMAT = 'png'

_IMAGE_FORMAT_MIME_TYPES = {
    'png': 'image/png',
    'webp': 'image/webp',
    'jpeg': 'image/jpeg',
    'jpg': 'image/jpeg',
}


class ImageGenerationError(RuntimeError):
    """A non-successful image operation with a stable, browser-safe explanation."""

    def __init__(self, message, code='image_generation_failed', status_code=502, context=None):
        super().__init__(message)
        self.public_message = message
        self.code = code
        self.status_code = status_code
        self.context = dict(context or {})


def resolve_image_binding_deployment(binding):
    """Use the deployment, never a stable registry ID, as the provider's model value."""
    deployment = str(
        binding.model.get('deploymentName') or binding.model.get('deployment') or ''
    ).strip()
    if not deployment:
        raise AIConnectionError(
            'The selected image model has no deployment configured.',
            'model_configuration_unavailable',
        )
    return deployment


def resolve_shared_image_binding(settings):
    """Resolve a server-only image binding consistently for readiness and execution."""
    binding = resolve_capability_binding(settings, IMAGE_GENERATION_CAPABILITY)
    selection = settings.get(IMAGE_SELECTION_KEY) or {}
    supplied_provider = str(selection.get('provider') or '').strip().lower()
    if supplied_provider and supplied_provider != binding.selection['provider']:
        raise AIConnectionError('The selected image model does not belong to that provider.')
    resolve_image_binding_deployment(binding)
    return binding


def resolve_image_binding_api(binding):
    """Resolve only an established, enabled image capability on the selected connection."""
    provider = binding.endpoint.get('provider') or 'aoai'
    support = resolve_model_capability(binding.model, IMAGE_GENERATION_CAPABILITY, provider)
    if (
        binding.capability != IMAGE_GENERATION_CAPABILITY
        or binding.endpoint.get('enabled') is False
        or not supports_model_capability(binding.model, IMAGE_GENERATION_CAPABILITY, provider)
    ):
        raise AIConnectionError(
            support.get('reason') or 'The selected model is not available for image generation.',
            'model_capability_unavailable',
        )
    profile = get_connection_operation_settings(binding.endpoint, IMAGE_GENERATION_CAPABILITY)
    if profile.get('api') not in (None, '', IMAGE_API_ROUTE_IMAGES, IMAGE_API_ROUTE_RESPONSES):
        raise AIConnectionError('The image connection has an unsupported API route.')
    # A connection can host both kinds of model. A migrated operation profile must
    # not force a newly selected GPT deployment onto its previous Images route.
    route = support.get('api') or profile.get('api')
    if route not in (IMAGE_API_ROUTE_IMAGES, IMAGE_API_ROUTE_RESPONSES):
        raise AIConnectionError('The selected model has no compatible image API.', 'unsupported_capability')
    return route


def resolve_selected_image_model_name(settings):
    """Return a display name, or '' for an unknown model or unavailable shared default.

    Bootstrap and admin rendering use this helper, so an invalidated reference must not
    abort the page. Readiness reasons come from the capability projection. Execution uses
    the strict binding/route/deployment resolvers instead and never falls back to legacy.
    """
    if not isinstance(settings, dict):
        return ''

    if image_settings_use_connections(settings):
        try:
            binding = resolve_shared_image_binding(settings)
            return str(binding.model.get('modelName') or resolve_image_binding_deployment(binding)).strip()
        except AIConnectionError:
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

    if image_settings_use_connections(settings):
        return resolve_image_binding_deployment(resolve_shared_image_binding(settings))

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
    if image_settings_use_connections(settings):
        return resolve_image_binding_api(resolve_shared_image_binding(settings))

    model_name = resolve_selected_image_model_name(settings).lower()
    if not model_name:
        return IMAGE_API_ROUTE_IMAGES

    if any(marker in model_name for marker in IMAGES_ENDPOINT_MODEL_MARKERS):
        return IMAGE_API_ROUTE_IMAGES

    support = resolve_model_capability(
        {'modelName': model_name}, IMAGE_GENERATION_CAPABILITY, 'aoai'
    )
    if not support['supported']:
        raise AIConnectionError(
            support.get('reason') or 'Image generation support is unknown for this model.',
            'model_capability_unavailable',
        )
    return support['api']


def is_image_capable_model_name(model_name):
    """Compatibility entry point for discovery, using the shared technical catalog."""
    return resolve_model_capability(
        {'modelName': str(model_name or '').strip()}, IMAGE_GENERATION_CAPABILITY, 'aoai'
    )['supported']


def resolve_responses_image_api_version(settings):
    """The image tool uses v1, independently of any dated chat or Images API version."""
    return RESPONSES_IMAGE_API_VERSION


def resolve_image_generation_api_version(settings):
    """Read image-specific transport options without changing the connection's chat version."""
    if resolve_image_api_route(settings) == IMAGE_API_ROUTE_RESPONSES:
        return RESPONSES_IMAGE_API_VERSION
    if image_settings_use_connections(settings):
        binding = resolve_shared_image_binding(settings)
        profile = get_connection_operation_settings(binding.endpoint, IMAGE_GENERATION_CAPABILITY)
        return str(profile.get('api_version') or DEFAULT_IMAGES_API_VERSION).strip()
    key = (
        'azure_apim_image_gen_api_version'
        if settings.get('enable_image_gen_apim')
        else 'azure_openai_image_gen_api_version'
    )
    return str(settings.get(key) or LEGACY_DEFAULT_IMAGES_API_VERSION).strip()


def build_image_api_base_url(endpoint, route, deployment='', api_version=''):
    """Normalize an API suffix, preserving the origin and every gateway/project prefix."""
    try:
        parsed = urlsplit(str(endpoint or '').strip())
        if (
            parsed.scheme not in ('https', 'http') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
        ):
            raise ValueError('Invalid endpoint')
    except ValueError as exc:
        raise AIConnectionError('The image connection endpoint is invalid.') from exc

    path = parsed.path.rstrip('/')
    # Only strip a recognizable API suffix. A gateway prefix such as /models/team
    # is part of the configured route, not a reason to redirect to the resource root.
    suffix = re.search(
        r'/openai(?:/v1)?(?:/deployments/[^/]+)?'
        r'(?:/(?:responses|chat/completions|images/(?:generations|edits)))?$',
        path,
        flags=re.IGNORECASE,
    )
    if suffix:
        path = path[:suffix.start()]
    if route == IMAGE_API_ROUTE_RESPONSES or api_version == 'v1':
        path = f'{path}/openai/v1/'
    else:
        if not deployment:
            raise AIConnectionError('The image connection has no deployment configured.')
        path = f'{path}/openai/deployments/{quote(deployment, safe="")}/'
    return urlunsplit((parsed.scheme, parsed.netloc, path, '', ''))


def resolve_responses_image_backend(binding):
    """Use only an explicitly stored backend binding; otherwise leave routing to the provider."""
    profile = get_connection_operation_settings(binding.endpoint, IMAGE_GENERATION_CAPABILITY)
    backend = profile.get('image_deployment')
    if backend in (None, ''):
        return ''
    if not isinstance(backend, str) or not re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', backend):
        raise AIConnectionError('The stored image backend binding is invalid.')
    if backend == resolve_image_binding_deployment(binding):
        raise AIConnectionError('A GPT deployment cannot be used as its own image backend.')
    for model in binding.endpoint.get('models') or []:
        if not isinstance(model, dict):
            continue
        if (model.get('deploymentName') or model.get('deployment')) != backend:
            continue
        support = resolve_model_capability(
            model, IMAGE_GENERATION_CAPABILITY, binding.endpoint.get('provider')
        )
        if (
            not supports_model_capability(model, IMAGE_GENERATION_CAPABILITY, binding.endpoint.get('provider'))
            or support.get('api') != IMAGE_API_ROUTE_IMAGES
        ):
            raise AIConnectionError('The stored image backend is unavailable or incompatible.')
    return backend


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
    try:
        result = None
        if hasattr(response, 'model_dump_json'):
            result = json.loads(response.model_dump_json())
        elif hasattr(response, 'model_dump'):
            result = response.model_dump()
        if isinstance(result, dict):
            return result
    except (TypeError, ValueError) as exc:
        raise ImageGenerationError('The image service returned an unreadable response.') from exc
    raise ImageGenerationError('The image service returned an unreadable response.')


def _valid_image_base64(value):
    if not isinstance(value, str) or not value.strip():
        return False
    try:
        return bool(base64.b64decode(value, validate=True))
    except (ValueError, binascii.Error):
        return False


def extract_responses_image_source(response):
    """Return a data URL for the image a Responses result carries, or '' when it has none.

    The image arrives as an ``image_generation_call`` item in ``output``, alongside the
    reasoning and message items the model also produced, and carries base64 rather than a
    URL. Returning the same data-URL string the images endpoint path produces is what lets
    everything downstream -- blob storage, proposals, revisions, the lightbox -- stay
    unaware of which route was taken.

    Failed/incomplete responses and refusals are never accepted, even if an output item
    contains image bytes. A text-only successful response returns an empty string.
    """
    response_dict = _as_response_dict(response)
    response_error = response_dict.get('error') or {}
    error_code = str(response_error.get('code') or '').lower() if isinstance(response_error, dict) else ''
    incomplete_details = response_dict.get('incomplete_details') or {}
    if isinstance(incomplete_details, dict) and incomplete_details.get('reason') == 'content_filter':
        error_code = 'content_filter'
    if error_code in ('content_filter', 'content_policy_violation', 'responsibleaipolicyviolation'):
        raise ImageGenerationError(
            'Image generation was blocked by content safety policies. Please edit the prompt and try again.',
            'image_content_refused', 400,
        )
    if response_dict.get('status') not in (None, 'completed') or response_error:
        raise ImageGenerationError(
            'The image service did not complete generation. Please try again.',
            'image_generation_incomplete',
        )
    output_items = response_dict.get('output')
    if not isinstance(output_items, list):
        return ''

    for item in output_items:
        if not isinstance(item, dict):
            continue
        content = item.get('content')
        if (
            item.get('type') == 'refusal'
            or (isinstance(content, list) and any(
                isinstance(part, dict) and part.get('type') == 'refusal'
                for part in content
            ))
        ):
            raise ImageGenerationError(
                'Image generation was refused. Please edit the prompt and try again.',
                'image_content_refused', 400,
            )
        if item.get('type') == 'image_generation_call' and item.get('status') not in (None, 'completed'):
            raise ImageGenerationError(
                'The image tool did not complete generation. Please try again.',
                'image_generation_incomplete',
            )

    for item in output_items:
        if not isinstance(item, dict) or item.get('type') != 'image_generation_call':
            continue
        encoded_image = item.get('result')
        if not _valid_image_base64(encoded_image):
            continue

        image_format = str(item.get('output_format') or DEFAULT_RESPONSES_IMAGE_FORMAT).lower()
        mime_type = _IMAGE_FORMAT_MIME_TYPES.get(
            image_format,
            _IMAGE_FORMAT_MIME_TYPES[DEFAULT_RESPONSES_IMAGE_FORMAT],
        )
        return f'data:{mime_type};base64,{encoded_image}'

    return ''
