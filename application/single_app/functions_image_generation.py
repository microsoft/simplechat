# functions_image_generation.py
"""Shared helpers for opt-in chat image generation proposals."""

import json
import mimetypes
import random
import re
import time
from datetime import datetime
from urllib.parse import urlparse

import requests
from azure.identity import DefaultAzureCredential, get_bearer_token_provider

from config import AzureOpenAI, cognitive_services_scope, cosmos_messages_container
from functions_appinsights import log_event
from functions_image_messages import build_image_message_documents, decode_image_content


INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE = 'simpleimage'
IMAGE_PROPOSAL_GUIDANCE_MARKER = '[Opt-in Image Generation Proposal Guidance]'
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


def resolve_image_generation_client(settings):
    """Create the Azure OpenAI image generation client and return it with the deployment name."""
    if not image_generation_is_enabled(settings):
        raise PermissionError('Image generation is not enabled')

    if settings.get('enable_image_gen_apim', False):
        image_gen_model = settings.get('azure_apim_image_gen_deployment')
        image_gen_client = AzureOpenAI(
            api_version=settings.get('azure_apim_image_gen_api_version'),
            azure_endpoint=settings.get('azure_apim_image_gen_endpoint'),
            api_key=settings.get('azure_apim_image_gen_subscription_key'),
        )
        return image_gen_client, image_gen_model

    image_gen_model = None
    image_gen_model_obj = settings.get('image_gen_model', {})
    if image_gen_model_obj and image_gen_model_obj.get('selected'):
        selected_image_gen_model = image_gen_model_obj['selected'][0]
        image_gen_model = selected_image_gen_model.get('deploymentName')

    if settings.get('azure_openai_image_gen_authentication_type') == 'managed_identity':
        token_provider = get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)
        image_gen_client = AzureOpenAI(
            api_version=settings.get('azure_openai_image_gen_api_version'),
            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
            azure_ad_token_provider=token_provider,
        )
    else:
        image_gen_client = AzureOpenAI(
            api_version=settings.get('azure_openai_image_gen_api_version'),
            azure_endpoint=settings.get('azure_openai_image_gen_endpoint'),
            api_key=settings.get('azure_openai_image_gen_key'),
        )

    if not image_gen_model:
        raise ValueError('No image generation deployment is selected')

    return image_gen_client, image_gen_model


def extract_generated_image_source(image_response):
    """Extract a usable image URL or data URL from an Azure OpenAI image response."""
    response_dict = json.loads(image_response.model_dump_json())
    if 'data' not in response_dict or not response_dict['data']:
        raise ValueError('No image data in response')

    image_data = response_dict['data'][0]
    if image_data.get('url'):
        return image_data['url']

    if image_data.get('b64_json'):
        return f"data:image/png;base64,{image_data['b64_json']}"

    available_keys = list(image_data.keys())
    raise ValueError(f'No URL or base64 data in image response. Available keys: {available_keys}')


def resolve_generated_image_bytes(generated_image_url):
    """Resolve generated image output into bytes and a MIME type for blob storage."""
    normalized_image_url = str(generated_image_url or '').strip()
    if not normalized_image_url:
        raise ValueError('Generated image URL is empty')

    if normalized_image_url.startswith('data:image/'):
        return decode_image_content(normalized_image_url)

    parsed_url = urlparse(normalized_image_url)
    if parsed_url.scheme not in {'http', 'https'}:
        raise ValueError('Generated image output is not a supported image source')

    response = requests.get(normalized_image_url, timeout=30)
    response.raise_for_status()
    image_bytes = response.content
    if not image_bytes:
        raise ValueError('Generated image download returned empty content')

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

    image_gen_client, image_gen_model = resolve_image_generation_client(settings)
    image_response = image_gen_client.images.generate(
        prompt=normalized_prompt,
        n=1,
        model=image_gen_model,
    )
    generated_image_url = extract_generated_image_source(image_response)
    if not generated_image_url or generated_image_url == 'null':
        raise ValueError('Generated image URL is null or empty')

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
        '[ImageGeneration] Generated chat image message',
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
