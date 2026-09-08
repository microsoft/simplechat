# functions_image_generation.py
"""Shared helpers for opt-in chat image generation proposals."""

import mimetypes
import random
import re
import time
from copy import deepcopy
from datetime import datetime
from urllib.parse import urlparse

import requests
from azure.identity import get_bearer_token_provider
from openai import OpenAI

from functions_ai_connections import (
    AIConnectionError,
    IMAGE_GENERATION_CAPABILITY,
    create_capability_client,
    get_connection_operation_settings,
    image_settings_use_connections,
    register_capability_client_factory,
)
from functions_appinsights import log_event
from functions_image_api_route import (
    DEFAULT_IMAGES_API_VERSION,
    IMAGE_API_ROUTE_RESPONSES,
    ImageGenerationError,
    _as_response_dict,
    build_image_api_base_url,
    build_image_generation_tool,
    extract_responses_image_source,
    resolve_image_api_route,
    resolve_image_binding_api,
    resolve_image_binding_deployment,
    resolve_image_generation_api_version,
    resolve_responses_image_backend,
    resolve_selected_image_deployment_name,
    resolve_shared_image_binding,
)
from functions_image_messages import build_image_message_documents, decode_image_content
from functions_model_endpoint_identity_header import build_model_endpoint_identity_headers


INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE = 'simpleimage'
IMAGE_PROPOSAL_GUIDANCE_MARKER = '[OPT_IN_IMAGE_GENERATION_PROPOSAL_GUIDANCE]'
IMAGE_PROPOSAL_PROMPT_MAX_LENGTH = 4000
IMAGE_PROPOSAL_TEXT_MAX_LENGTH = 600
IMAGE_PROPOSAL_ID_MAX_LENGTH = 120

IMAGE_PROPOSAL_REQUEST_MARKERS = (
    'image',
    'illustration',
    'illustrate',
    'visual',
    'visualize',
    'visualise',
    'picture',
    'graphic',
    'diagram',
    'timeline',
    'slide',
    'powerpoint',
    'presentation',
    'poster',
    'infographic',
    'storyboard',
    'concept art',
    'map',
    'workflow',
    'process',
)



def image_generation_is_enabled(settings):
    """Return whether chat image generation is enabled in app settings."""
    return bool(isinstance(settings, dict) and settings.get('enable_image_generation'))


def user_request_supports_image_proposals(user_message):
    """Return true when a response could reasonably include optional image proposals."""
    normalized_message = re.sub(r'\s+', ' ', str(user_message or '').strip().lower())
    if not normalized_message:
        return False

    return any(marker in normalized_message for marker in IMAGE_PROPOSAL_REQUEST_MARKERS)


def build_image_proposal_guidance_message():
    """Return system guidance for assistant-authored image proposal cards."""
    return f"""{IMAGE_PROPOSAL_GUIDANCE_MARKER}
Image generation is available as an opt-in user action. Do not generate or embed images directly in the assistant answer. When one or more generated images would materially help the user, include compact fenced `{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}` JSON proposals inline at the point where each visual belongs. The browser will render each block as an approval card with approve, cancel, and edit controls.

Use this exact fenced block shape and valid JSON only:
```{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}
{{
  "version": 1,
  "visualId": "short_stable_id",
  "title": "Short image title",
  "description": "One sentence describing the proposed image.",
  "prompt": "Detailed image-generation prompt with subject, composition, labels, style, accessibility/readability constraints, and any source context needed.",
  "visualType": "timeline|diagram|illustration|infographic|map|scene|other",
  "slideNumber": 9,
  "context": "Brief source context"
}}
```

Rules:
- Only propose images when they are useful; omit the block when text alone is better.
- Place each `{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}` block immediately after the paragraph, bullet, slide section, or visual suggestion it supports. Do not collect image proposals at the end unless the end is the relevant section.
- For slide decks, keep each proposal inside the slide it supports, directly after the slide's visual suggestion, include list, or speaker note.
- Suggest zero, one, or multiple images based on value. One strong image proposal is fine; multiple distinct proposals are appropriate when several slides or sections benefit from visuals.
- Avoid decorative duplicates and avoid proposing images that do not directly support the surrounding content.
- Keep each prompt self-contained and under {IMAGE_PROPOSAL_PROMPT_MAX_LENGTH} characters.
- The user must approve before generation; never state that an image has already been created.
- Do not include secrets, private URLs, or unsupported instructions in the prompt.
""".strip()


def _trim_text(value, max_length):
    normalized_value = re.sub(r'\s+', ' ', str(value or '').strip())
    if len(normalized_value) <= max_length:
        return normalized_value
    return normalized_value[:max_length].rstrip()


def _normalize_visual_id(value):
    normalized_value = re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(value or '').strip())
    normalized_value = normalized_value.strip('._-')
    return normalized_value[:IMAGE_PROPOSAL_ID_MAX_LENGTH]


def normalize_image_proposal(raw_proposal):
    """Validate and normalize a model-authored image proposal payload."""
    if not isinstance(raw_proposal, dict):
        raise ValueError('Image proposal must be a JSON object')

    prompt = _trim_text(raw_proposal.get('prompt'), IMAGE_PROPOSAL_PROMPT_MAX_LENGTH)
    if not prompt:
        raise ValueError('Image proposal prompt is required')

    normalized_proposal = {
        'version': 1,
        'visualId': _normalize_visual_id(raw_proposal.get('visualId') or raw_proposal.get('visual_id')),
        'title': _trim_text(raw_proposal.get('title'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH),
        'description': _trim_text(raw_proposal.get('description'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH),
        'prompt': prompt,
        'visualType': _trim_text(raw_proposal.get('visualType') or raw_proposal.get('visual_type'), 80),
        'context': _trim_text(raw_proposal.get('context'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH),
    }

    slide_number = raw_proposal.get('slideNumber', raw_proposal.get('slide_number'))
    if slide_number is not None and str(slide_number).strip() != '':
        try:
            normalized_proposal['slideNumber'] = int(slide_number)
        except (TypeError, ValueError):
            normalized_proposal['slideNumber'] = _trim_text(slide_number, 40)

    return normalized_proposal


class _ImageOpenAIClient(OpenAI):
    """Preserve Azure/gateway auth and refresh identity tokens with the pinned SDK.

    OpenAI 1.109.1 interpolates ``api_key`` as a string; a callable there becomes
    an invalid bearer credential. Its auth_headers hook is evaluated per request.
    """

    def __init__(self, *, image_auth_header='api-key', image_token_provider=None, **kwargs):
        self._image_auth_header = image_auth_header
        self._image_token_provider = image_token_provider
        super().__init__(**kwargs)

    @property
    def auth_headers(self):
        if self._image_token_provider is not None:
            return {'Authorization': f'Bearer {self._image_token_provider()}'}
        if self._image_auth_header == 'authorization':
            return super().auth_headers
        return {self._image_auth_header: self.api_key}


def image_generation_error_log_context(exc):
    """Keep structured diagnostics, never provider messages, prompts, endpoints, or keys."""
    body = getattr(exc, 'body', None)
    detail = body.get('error', body) if isinstance(body, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    response = getattr(exc, 'response', None)
    headers = getattr(response, 'headers', {}) or {}
    values = {
        'error_type': type(exc).__name__,
        'provider_code': detail.get('code') or getattr(exc, 'code', None),
        'parameter': detail.get('param') or getattr(exc, 'param', None),
        'request_id': getattr(exc, 'request_id', None) or headers.get('x-request-id') or headers.get('apim-request-id'),
    }
    context = {
        key: value for key, value in values.items()
        if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.:\[\]-]{1,128}', value)
    }
    status = getattr(exc, 'status_code', None) or getattr(response, 'status_code', None)
    if isinstance(status, int) and not isinstance(status, bool):
        context['status_code'] = status
    if isinstance(exc, ImageGenerationError):
        context.update(exc.context)
    return context


def normalize_image_generation_error(exc):
    """Distinguish configuration/readiness failures from prompt refusals and throttling."""
    if isinstance(exc, (AIConnectionError, ImageGenerationError)):
        return exc
    context = image_generation_error_log_context(exc)
    status = context.get('status_code')
    code = str(context.get('provider_code') or '').lower()
    parameter = str(context.get('parameter') or '').lower()
    body = getattr(exc, 'body', None)
    detail = body.get('error', body) if isinstance(body, dict) else {}
    detail = detail if isinstance(detail, dict) else {}
    # Provider prose is used only for classification when structured codes are absent.
    # It is deliberately never logged or returned to the caller.
    message = str(detail.get('message') or exc).lower()
    if status == 429 or type(exc).__name__ == 'RateLimitError':
        return ImageGenerationError(
            'The image service is busy or has reached its rate limit. Please try again later.',
            'image_rate_limited', 429, context,
        )
    if (
        code in ('content_filter', 'content_policy_violation', 'responsibleaipolicyviolation', 'safety_violation')
        or any(marker in message for marker in ('content_filter', 'content policy', 'content safety', 'responsibleaipolicyviolation'))
    ):
        return ImageGenerationError(
            'Image generation was blocked by content safety policies. Please edit the prompt and try again.',
            'image_content_refused', 400, context,
        )
    if isinstance(exc, PermissionError):
        return ImageGenerationError('Image generation is not enabled.', 'capability_disabled', 403, context)
    configuration_parameter = parameter in ('model', 'tools', 'tool_choice', 'api-version', 'api_version') or parameter.startswith('tools[')
    configuration_message = any(marker in message for marker in (
        'x-ms-oai-image-generation-deployment', 'image_generation', 'image generation tool',
        'deployment', 'api-version', 'unsupported', 'not supported',
    ))
    if status in (401, 403, 404) or (status == 400 and (configuration_parameter or configuration_message)):
        return ImageGenerationError(
            'The selected connection cannot perform this image operation. Ask an administrator to check its model, API, permissions, and image service availability.',
            'image_service_unavailable', 503, context,
        )
    if isinstance(exc, ValueError) or (status == 400 and (
        parameter in ('prompt', 'input', 'size', 'quality', 'background')
        or parameter.startswith('input[')
        or code in ('invalid_prompt', 'prompt_too_long')
    )):
        return ImageGenerationError(
            'Image generation request is invalid. Please review the prompt and image options and try again.',
            'invalid_image_request', 400, context,
        )
    return ImageGenerationError(
        'Image generation failed due to a technical error. Please try again.',
        'image_generation_failed', 502, context,
    )


def image_generation_error_response(exc):
    """Build the same safe failure contract for chat, approvals, editing, and admin tests."""
    error = normalize_image_generation_error(exc)
    status = (
        403 if error.code == 'capability_disabled' else 503
    ) if isinstance(error, AIConnectionError) else error.status_code
    return {
        'error': error.public_message,
        'error_code': error.code,
        **({'rate_limited': True} if status == 429 else {}),
    }, status


def _build_image_runtime_client(endpoint, settings, deployment, route, api_version, backend=''):
    connection = endpoint.get('connection') or {}
    auth = endpoint.get('auth') or {}
    profile = get_connection_operation_settings(endpoint, IMAGE_GENERATION_CAPABILITY)
    provider = str(endpoint.get('provider') or 'aoai').strip().lower()
    if provider not in ('aoai', 'aifoundry', 'new_foundry'):
        raise AIConnectionError('This connection type has no compatible image adapter.', 'unsupported_capability')
    if not isinstance(api_version, str) or not re.fullmatch(r'(?:v1|\d{4}-\d{2}-\d{2}(?:-preview)?)', api_version):
        raise AIConnectionError('The image connection API version is invalid.')

    base_url = build_image_api_base_url(
        connection.get('endpoint'), route, deployment=deployment, api_version=api_version
    )
    auth_type = str(auth.get('type') or 'managed_identity').strip().lower()
    auth_header = str(profile.get('auth_header') or (
        'api-key' if api_version != 'v1' or provider == 'aoai' or profile.get('is_apim')
        else 'authorization'
    )).lower()
    if auth_header not in ('api-key', 'authorization', 'ocp-apim-subscription-key'):
        raise AIConnectionError('The image connection authentication header is unsupported.')
    token_provider = None
    api_key = ''
    if auth_type in ('api_key', 'key'):
        api_key = auth.get('api_key')
        if not isinstance(api_key, str) or not api_key.strip():
            raise AIConnectionError('The selected image connection is missing an API key.')
    elif auth_type in ('managed_identity', 'service_principal'):
        # These helpers import application configuration; defer them so proposal and
        # response validation can be imported without initializing Cosmos or Azure.
        from config import cognitive_services_scope
        from functions_model_endpoint_runtime import (
            resolve_credential_for_model_endpoint_auth,
            resolve_foundry_scope_for_endpoint_auth,
        )

        credential = resolve_credential_for_model_endpoint_auth(auth)
        scope = cognitive_services_scope
        if provider in ('aifoundry', 'new_foundry'):
            scope = resolve_foundry_scope_for_endpoint_auth(auth, endpoint=connection.get('endpoint'))
        token_provider = get_bearer_token_provider(credential, scope)
    else:
        raise AIConnectionError('The image connection authentication type is unsupported.')

    headers = build_model_endpoint_identity_headers(settings, endpoint_config=endpoint)
    if backend:
        headers['x-ms-oai-image-generation-deployment'] = backend
    return _ImageOpenAIClient(
        api_key=api_key,
        base_url=base_url,
        image_auth_header=auth_header,
        image_token_provider=token_provider,
        default_headers=headers,
        default_query={'api-version': api_version} if api_version != 'v1' else {},
        max_retries=0,
    )


def build_image_connection_client(binding, settings):
    """Registered image adapter: resolve stored global secrets and return only the client."""
    try:
        route = resolve_image_binding_api(binding)
        provider = str(binding.endpoint.get('provider') or 'aoai').strip().lower()
        if binding.selection.get('provider') not in (None, '', provider):
            raise AIConnectionError('The selected image model does not belong to that provider.')
        deployment = resolve_image_binding_deployment(binding)
        profile = get_connection_operation_settings(binding.endpoint, IMAGE_GENERATION_CAPABILITY)
        api_version = (
            'v1' if route == IMAGE_API_ROUTE_RESPONSES
            else str(profile.get('api_version') or DEFAULT_IMAGES_API_VERSION).strip()
        )
        backend = resolve_responses_image_backend(binding) if route == IMAGE_API_ROUTE_RESPONSES else ''
        # The model-endpoint helper enforces endpoint secret scope; a settings-secret
        # reference or browser-redacted credential must never be treated as the key.
        from functions_keyvault import SecretReturnType, keyvault_model_endpoint_get_helper

        endpoint = keyvault_model_endpoint_get_helper(
            deepcopy(binding.endpoint), binding.endpoint['id'], scope='global', return_type=SecretReturnType.VALUE
        )
        return _build_image_runtime_client(endpoint, settings, deployment, route, api_version, backend)
    except AIConnectionError:
        raise
    except Exception as exc:
        log_event('[IMAGE_GENERATION] Image connection initialization failed', extra=image_generation_error_log_context(exc))
        raise AIConnectionError(
            'The image connection could not be initialized. Ask an administrator to check its credentials and configuration.',
            'image_connection_initialization_failed',
        ) from exc


register_capability_client_factory(IMAGE_GENERATION_CAPABILITY, build_image_connection_client)


def resolve_image_generation_client(settings, api_version=None):
    """Return the selected image client and deployment, retaining unmigrated legacy settings."""
    if not image_generation_is_enabled(settings):
        raise PermissionError('Image generation is not enabled')
    if image_settings_use_connections(settings):
        binding = resolve_shared_image_binding(settings)
        return create_capability_client(binding, settings), resolve_image_binding_deployment(binding)

    deployment = resolve_selected_image_deployment_name(settings)
    if not deployment:
        raise AIConnectionError('No image generation deployment is selected.', 'model_configuration_unavailable')
    route = resolve_image_api_route(settings)
    resolved_version = resolve_image_generation_api_version(settings)
    if route != IMAGE_API_ROUTE_RESPONSES and api_version:
        resolved_version = api_version
    is_apim = bool(settings.get('enable_image_gen_apim'))
    prefix = 'azure_apim_image_gen' if is_apim else 'azure_openai_image_gen'
    endpoint = {
        'provider': 'aoai',
        'connection': {
            'endpoint': settings.get(f'{prefix}_endpoint'),
            'operation_settings': {
                IMAGE_GENERATION_CAPABILITY: {'is_apim': is_apim, 'auth_header': 'api-key'},
            },
        },
        'auth': {
            'type': (
                'managed_identity'
                if not is_apim and settings.get('azure_openai_image_gen_authentication_type') == 'managed_identity'
                else 'api_key'
            ),
            'api_key': settings.get(f'{prefix}_subscription_key' if is_apim else f'{prefix}_key'),
        },
    }
    try:
        return _build_image_runtime_client(endpoint, settings, deployment, route, resolved_version), deployment
    except AIConnectionError:
        raise
    except Exception as exc:
        log_event('[IMAGE_GENERATION] Legacy image connection initialization failed', extra=image_generation_error_log_context(exc))
        raise AIConnectionError('The image connection could not be initialized. Check its credentials and configuration.') from exc


def close_image_generation_client(client):
    """Release a per-operation client without replacing an image or its original failure."""
    close = getattr(client, 'close', None)
    if callable(close):
        try:
            close()
        except Exception as exc:
            log_event('[IMAGE_GENERATION] Image client cleanup failed', extra=image_generation_error_log_context(exc))


def request_generated_image_source(settings, prompt, size='', quality='', background=''):
    """Ask the configured deployment for an image and return its URL or data URL.

    The single place that decides between the images endpoint and the Responses image
    tool. Every caller goes through it, including the admin connection test, because a
    test that exercised a different route from the real call would certify a path nobody
    uses.
    """
    client = None
    response = None
    route = ''
    try:
        if not image_generation_is_enabled(settings):
            raise PermissionError('Image generation is not enabled')
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError('Image generation prompt is required')
        route = resolve_image_api_route(settings)
        client, deployment = resolve_image_generation_client(settings)
        if route != IMAGE_API_ROUTE_RESPONSES:
            arguments = {'model': deployment, 'prompt': prompt, 'n': 1}
            if size:
                arguments['size'] = size
            optional = {key: value for key, value in {'quality': quality, 'background': background}.items() if value}
            if optional:
                arguments['extra_body'] = optional
            response = client.images.generate(**arguments)
            return extract_generated_image_source(response)

        response = client.responses.create(
            model=deployment,
            input=prompt,
            tools=[build_image_generation_tool(size=size, quality=quality, background=background)],
            tool_choice={'type': 'image_generation'},
        )
        generated_image_url = extract_responses_image_source(response)
        if not generated_image_url:
            raise ImageGenerationError(
                'The selected model returned no image. Ask an administrator to check image service availability for this connection.',
                'image_output_missing',
            )
        return generated_image_url
    except Exception as exc:
        error = normalize_image_generation_error(exc)
        context = image_generation_error_log_context(exc)
        response_request_id = getattr(response, '_request_id', None)
        if isinstance(response_request_id, str) and re.fullmatch(r'[A-Za-z0-9_.:-]{1,128}', response_request_id):
            context['request_id'] = response_request_id
        provider_status = response.get('status') if isinstance(response, dict) else getattr(response, 'status', None)
        if provider_status in ('completed', 'incomplete', 'failed', 'in_progress', 'queued', 'cancelled'):
            context['provider_status'] = provider_status
        if isinstance(error, ImageGenerationError):
            error.context.update(context)
        log_event(
            '[IMAGE_GENERATION] Image request failed',
            extra={**context, 'route': route},
        )
        if error is exc:
            raise
        raise error from exc
    finally:
        close_image_generation_client(client)


def extract_generated_image_source(image_response):
    """Extract a usable image URL or data URL from an Azure OpenAI image response."""
    response_dict = _as_response_dict(image_response)
    if not isinstance(response_dict.get('data'), list) or not response_dict['data']:
        raise ImageGenerationError('The image service returned no image data.', 'image_output_missing')

    image_data = response_dict['data'][0]
    if not isinstance(image_data, dict):
        raise ImageGenerationError('The image service returned unreadable image data.', 'image_output_missing')
    url = image_data.get('url')
    if isinstance(url, str):
        try:
            parsed_url = urlparse(url.strip())
            if parsed_url.scheme in ('http', 'https') and parsed_url.hostname:
                return url.strip()
        except ValueError:
            pass

    source = extract_responses_image_source({
        'output': [{'type': 'image_generation_call', 'result': image_data.get('b64_json')}],
    })
    if source:
        return source

    raise ImageGenerationError('The image service returned no usable image.', 'image_output_missing')


def resolve_generated_image_bytes(generated_image_url):
    """Resolve generated image output into bytes and a MIME type for blob storage."""
    normalized_image_url = str(generated_image_url or '').strip()
    if not normalized_image_url:
        raise ImageGenerationError('The image service returned no usable image.', 'image_output_missing')

    if normalized_image_url.startswith('data:image/'):
        try:
            return decode_image_content(normalized_image_url)
        except ValueError as exc:
            raise ImageGenerationError('The image service returned unreadable image data.', 'image_output_missing') from exc

    try:
        parsed_url = urlparse(normalized_image_url)
        if parsed_url.scheme not in {'http', 'https'} or not parsed_url.hostname:
            raise ValueError('Unsupported image URL')
    except ValueError as exc:
        raise ImageGenerationError('The image service returned an unsupported image source.', 'image_output_missing') from exc

    try:
        response = requests.get(normalized_image_url, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise ImageGenerationError(
            'The generated image could not be downloaded. Please try again.',
            'image_download_failed', context=image_generation_error_log_context(exc),
        ) from exc
    image_bytes = response.content
    if not image_bytes:
        raise ImageGenerationError('The generated image download was empty.', 'image_output_missing')

    content_type = str(response.headers.get('Content-Type') or '').split(';', 1)[0].strip()
    if not content_type or not content_type.startswith('image/'):
        content_type = mimetypes.guess_type(parsed_url.path)[0] or 'image/png'

    return content_type, image_bytes


def _image_extension_for_mime_type(mime_type):
    if mime_type == 'image/jpeg':
        return '.jpg'
    if mime_type == 'image/webp':
        return '.webp'
    if mime_type == 'image/gif':
        return '.gif'
    return '.png'


def _build_image_proposal_metadata(proposal, source_assistant_message_id=None):
    if not proposal:
        return None

    metadata = dict(proposal)
    metadata['approved_at'] = datetime.utcnow().isoformat()
    if source_assistant_message_id:
        metadata['source_assistant_message_id'] = str(source_assistant_message_id)
    return metadata


def generate_chat_image_message(
    *,
    settings,
    user_id,
    conversation_id,
    prompt,
    user_info=None,
    thread_id=None,
    previous_thread_id=None,
    proposal=None,
    source_assistant_message_id=None,
    store_in_blob=False,
):
    """Generate an image, persist it as a chat image message, and return response data."""
    normalized_prompt = _trim_text(prompt, IMAGE_PROPOSAL_PROMPT_MAX_LENGTH)
    if not normalized_prompt:
        raise ValueError('Image generation prompt is required')

    image_gen_model = resolve_selected_image_deployment_name(settings)
    generated_image_url = request_generated_image_source(settings, normalized_prompt)
    if not generated_image_url or generated_image_url == 'null':
        raise ImageGenerationError('The image service returned no usable image.', 'image_output_missing')

    # Persistence is intentionally lazy: validating proposal payloads must not initialize Cosmos.
    from config import cosmos_messages_container

    image_message_id = f"{conversation_id}_image_{int(time.time())}_{random.randint(1000, 9999)}"
    image_timestamp = datetime.utcnow().isoformat()
    image_metadata = {
        'user_info': user_info,
        'thread_info': {
            'thread_id': thread_id,
            'previous_thread_id': previous_thread_id,
            'active_thread': True,
            'thread_attempt': 1,
        },
    }

    image_proposal_metadata = _build_image_proposal_metadata(
        proposal,
        source_assistant_message_id=source_assistant_message_id,
    )
    if image_proposal_metadata:
        image_metadata['image_proposal'] = image_proposal_metadata

    image_doc = {
        'id': image_message_id,
        'conversation_id': conversation_id,
        'role': 'image',
        'content': generated_image_url,
        'prompt': normalized_prompt,
        'created_at': image_timestamp,
        'timestamp': image_timestamp,
        'model_deployment_name': image_gen_model,
        'metadata': image_metadata,
    }

    response_image_url = generated_image_url
    if store_in_blob:
        # Lazy import keeps proposal-only helpers free of optional document processing dependencies.
        from functions_simplechat_operations import upload_chat_image_bytes_for_user

        image_mime_type, image_bytes = resolve_generated_image_bytes(generated_image_url)
        visual_id = _normalize_visual_id((proposal or {}).get('visualId')) if proposal else ''
        image_file_stem = visual_id or image_message_id
        blob_image_info = upload_chat_image_bytes_for_user(
            user_id=user_id,
            conversation_id=conversation_id,
            message_id=image_message_id,
            file_name=f"{image_file_stem}{_image_extension_for_mime_type(image_mime_type)}",
            image_bytes=image_bytes,
            content_type=image_mime_type,
            image_source='generated',
        )
        image_doc.update({
            'content': blob_image_info['content'],
            'filename': blob_image_info['filename'],
            'file_content_source': blob_image_info['file_content_source'],
            'blob_container': blob_image_info['blob_container'],
            'blob_path': blob_image_info['blob_path'],
            'mime_type': blob_image_info['mime_type'],
        })
        image_doc['metadata']['is_chunked'] = False
        image_doc['metadata']['is_blob_backed'] = True
        image_doc['metadata']['original_size'] = blob_image_info['image_size']
        cosmos_messages_container.upsert_item(image_doc)
        response_image_url = blob_image_info['content']
    else:
        image_documents = build_image_message_documents(image_doc)
        for image_document in image_documents:
            cosmos_messages_container.upsert_item(image_document)

    log_event(
        '[IMAGE_GENERATION] Generated chat image message',
        extra={
            'conversation_id': conversation_id,
            'message_id': image_message_id,
            'model_deployment_name': image_gen_model,
            'store_in_blob': store_in_blob,
            'has_proposal': bool(proposal),
        },
    )

    return {
        'reply': 'Image loading...',
        'image_url': response_image_url,
        'conversation_id': conversation_id,
        'model_deployment_name': image_gen_model,
        'message_id': image_message_id,
        'image_message': image_doc,
    }
