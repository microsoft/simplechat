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
from functions_chat_orchestration import user_requested_image_generation
from functions_image_messages import build_image_message_documents, decode_image_content


INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE = 'simpleimage'
IMAGE_PROPOSAL_GUIDANCE_MARKER = '[OPT_IN_IMAGE_GENERATION_PROPOSAL_GUIDANCE]'
IMAGE_PROPOSAL_PROMPT_MAX_LENGTH = 4000
IMAGE_PROPOSAL_TEXT_MAX_LENGTH = 600
IMAGE_PROPOSAL_ID_MAX_LENGTH = 120
IMAGE_PROPOSAL_METADATA_ID_MAX_LENGTH = 160
IMAGE_PROPOSAL_METADATA_MAX_ITEMS = 24
IMAGE_PROPOSAL_APPROVAL_REVIEW_VERSION = 1

IMAGE_PROPOSAL_SOURCE_LABELS = {
    'assigned_knowledge': 'Assigned Knowledge',
    'conversation_documents': 'Conversation Documents',
    'conversation_history': 'Conversation History',
    'deep_research': 'Deep Research',
    'document_action': 'Selected Action',
    'prior_citations': 'Prior Citations',
    'selected_action': 'Selected Action',
    'selected_agent': 'Selected Agent',
    'selected_documents': 'Selected Documents',
    'selected_image': 'Selected Image',
    'selected_images': 'Selected Image',
    'source_review': 'Source Review',
    'user_message': 'User Provided',
    'web_search': 'Web Search',
    'workspace_search': 'Workspace Search',
}

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

    return (
        any(marker in normalized_message for marker in IMAGE_PROPOSAL_REQUEST_MARKERS)
        or user_requested_image_generation(normalized_message)
    )


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
    "context": "Brief source context",
    "evidenceIds": ["fact_or_result_id"],
    "sourceSummary": "Friendly summary of the sources used",
    "missingEvidence": ["Requested evidence that was not verified"],
    "referenceImageIds": ["verified_image_reference_id"]
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


def build_grounded_image_synthesis_profile():
    """Return image-specific output rules for the generic central finalizer."""
    return {
        'type': 'image_proposal',
        'instructions': [
            'Start with a brief evidence summary and disclose material missing evidence in prose.',
            'Emit simpleimage proposals only when supported evidence is sufficient for a useful visual.',
            'Return every proposal as valid JSON inside its own fenced simpleimage block.',
            'Use only supported or user-provided facts from the evidence ledger in proposal descriptions and prompts.',
            'Omit unsupported details or label them explicitly as placeholders; never turn unsupported facts into claims.',
            'Use generic person icons for collaborators unless the ledger contains verified photo references for them.',
            'Use selected-image visual features only when they appear in supported selected-image evidence.',
            'Keep every image prompt self-contained, provider-ready, and under 4000 characters.',
            'Keep proposals user-approvable and never claim image generation already happened.',
            'Reference only evidence, result, artifact, or image IDs retained in the compact evidence ledger.',
            'Use multiple proposals only for distinct requested purposes, not decorative duplicates.',
        ],
        'schema': {
            'format': 'assistant_text_with_fenced_blocks',
            'block_language': INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE,
            'proposal_version': 1,
            'required_fields': [
                'version',
                'visualId',
                'title',
                'description',
                'prompt',
                'visualType',
                'context',
            ],
            'optional_fields': [
                'slideNumber',
                'evidenceIds',
                'sourceSummary',
                'missingEvidence',
                'referenceImageIds',
            ],
            'proposal_shape': {
                'version': 1,
                'visualId': 'short_stable_id',
                'title': 'Short image title',
                'description': 'One sentence describing the proposed image.',
                'prompt': 'Self-contained provider-ready image prompt.',
                'visualType': 'illustration|infographic|diagram|timeline|map|scene|other',
                'context': 'Brief grounded source context.',
                'evidenceIds': ['retained_fact_or_result_id'],
                'sourceSummary': 'Friendly summary of sources used.',
                'missingEvidence': ['Material requested evidence that was not verified.'],
                'referenceImageIds': ['retained_image_reference_artifact_id'],
            },
        },
    }


def _trim_text(value, max_length):
    normalized_value = re.sub(r'\s+', ' ', str(value or '').strip())
    if len(normalized_value) <= max_length:
        return normalized_value
    return normalized_value[:max_length].rstrip()


def _normalize_visual_id(value):
    normalized_value = re.sub(r'[^a-zA-Z0-9_.-]+', '_', str(value or '').strip())
    normalized_value = normalized_value.strip('._-')
    return normalized_value[:IMAGE_PROPOSAL_ID_MAX_LENGTH]


def _normalize_metadata_id(value):
    normalized_value = re.sub(r'[^a-zA-Z0-9_.:-]+', '_', str(value or '').strip())
    return normalized_value.strip('._:-')[:IMAGE_PROPOSAL_METADATA_ID_MAX_LENGTH]


def _normalize_metadata_list(values, *, identifiers=False):
    if not isinstance(values, (list, tuple, set)):
        return []
    normalized_values = []
    for value in values:
        normalized_value = (
            _normalize_metadata_id(value)
            if identifiers
            else _trim_text(value, IMAGE_PROPOSAL_TEXT_MAX_LENGTH)
        )
        if normalized_value and normalized_value not in normalized_values:
            normalized_values.append(normalized_value)
        if len(normalized_values) >= IMAGE_PROPOSAL_METADATA_MAX_ITEMS:
            break
    return normalized_values


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

    evidence_ids = _normalize_metadata_list(
        raw_proposal.get('evidenceIds', raw_proposal.get('evidence_ids')),
        identifiers=True,
    )
    if evidence_ids:
        normalized_proposal['evidenceIds'] = evidence_ids

    source_summary = _trim_text(
        raw_proposal.get('sourceSummary', raw_proposal.get('source_summary')),
        IMAGE_PROPOSAL_TEXT_MAX_LENGTH,
    )
    if source_summary:
        normalized_proposal['sourceSummary'] = source_summary

    missing_evidence = _normalize_metadata_list(
        raw_proposal.get('missingEvidence', raw_proposal.get('missing_evidence')),
    )
    if missing_evidence:
        normalized_proposal['missingEvidence'] = missing_evidence

    reference_image_ids = _normalize_metadata_list(
        raw_proposal.get('referenceImageIds', raw_proposal.get('reference_image_ids')),
        identifiers=True,
    )
    if reference_image_ids:
        normalized_proposal['referenceImageIds'] = reference_image_ids

    return normalized_proposal


def constrain_image_proposal_to_evidence_ledger(proposal, evidence_ledger):
    """Retain proposal lineage IDs only when the source ledger proves them."""
    normalized_proposal = normalize_image_proposal(proposal)
    if not isinstance(evidence_ledger, dict):
        normalized_proposal.pop('evidenceIds', None)
        normalized_proposal.pop('referenceImageIds', None)
        return normalized_proposal

    known_evidence_ids = {
        str(entry.get('id'))
        for section in ('facts', 'results', 'citations', 'artifacts')
        for entry in (evidence_ledger.get(section) or [])
        if isinstance(entry, dict) and entry.get('id')
    }
    known_reference_image_ids = {
        str(artifact.get('id'))
        for artifact in (evidence_ledger.get('artifacts') or [])
        if isinstance(artifact, dict)
        and artifact.get('id')
        and artifact.get('type') == 'image_reference'
    }

    retained_evidence_ids = [
        evidence_id
        for evidence_id in normalized_proposal.get('evidenceIds') or []
        if evidence_id in known_evidence_ids
    ]
    if retained_evidence_ids:
        normalized_proposal['evidenceIds'] = retained_evidence_ids
    else:
        normalized_proposal.pop('evidenceIds', None)

    retained_reference_image_ids = [
        reference_id
        for reference_id in normalized_proposal.get('referenceImageIds') or []
        if reference_id in known_reference_image_ids
    ]
    if retained_reference_image_ids:
        normalized_proposal['referenceImageIds'] = retained_reference_image_ids
    else:
        normalized_proposal.pop('referenceImageIds', None)

    return normalized_proposal


def _image_proposal_source_label(source_type):
    normalized_type = _normalize_metadata_id(source_type).lower()
    if normalized_type in IMAGE_PROPOSAL_SOURCE_LABELS:
        return IMAGE_PROPOSAL_SOURCE_LABELS[normalized_type]
    return _trim_text(normalized_type.replace('_', ' ').title(), 80) or 'Evidence Source'


def _image_proposal_entry_source_ids(entry):
    source_ids = _normalize_metadata_list(entry.get('source_ids'), identifiers=True)
    source_id = _normalize_metadata_id(entry.get('source_id'))
    if source_id and source_id not in source_ids:
        source_ids.append(source_id)
    return source_ids


def build_image_proposal_approval_review(
    evidence_ledger,
    orchestration_runtime=None,
    proposal=None,
):
    """Build a bounded user-facing approval state from authorized turn metadata."""
    if not isinstance(evidence_ledger, dict):
        return {
            'version': IMAGE_PROPOSAL_APPROVAL_REVIEW_VERSION,
            'state': 'ready',
            'can_approve': True,
            'requires_confirmation': False,
            'ledger_status': 'unavailable',
            'runtime_status': 'unavailable',
            'message': 'Review the image proposal before generation.',
            'sources': [],
            'missing_evidence': [],
            'reference_images': [],
        }

    runtime = orchestration_runtime if isinstance(orchestration_runtime, dict) else {}
    normalized_proposal = proposal if isinstance(proposal, dict) else {}
    ledger_status = _normalize_metadata_id(evidence_ledger.get('status')).lower() or 'unknown'
    runtime_status = _normalize_metadata_id(runtime.get('status')).lower() or 'unavailable'
    requirements = [
        entry
        for entry in (evidence_ledger.get('requirements') or [])
        if isinstance(entry, dict)
    ]
    sources = [
        entry
        for entry in (evidence_ledger.get('sources') or [])
        if isinstance(entry, dict)
    ]

    retained_evidence_ids = set(_normalize_metadata_list(
        normalized_proposal.get('evidenceIds', normalized_proposal.get('evidence_ids')),
        identifiers=True,
    ))
    retained_reference_ids = set(_normalize_metadata_list(
        normalized_proposal.get('referenceImageIds', normalized_proposal.get('reference_image_ids')),
        identifiers=True,
    ))
    supported_entries = []
    for section in ('facts', 'citations', 'artifacts'):
        supported_entries.extend(
            entry
            for entry in (evidence_ledger.get(section) or [])
            if isinstance(entry, dict)
        )
    supported_entries.extend(
        entry
        for entry in (evidence_ledger.get('results') or [])
        if isinstance(entry, dict) and entry.get('status') in {'succeeded', 'partial'}
    )

    selected_entry_ids = retained_evidence_ids | retained_reference_ids
    used_source_ids = {
        source_id
        for entry in supported_entries
        if selected_entry_ids and _normalize_metadata_id(entry.get('id')) in selected_entry_ids
        for source_id in _image_proposal_entry_source_ids(entry)
    }
    source_summaries = []
    for source in sources[:IMAGE_PROPOSAL_METADATA_MAX_ITEMS]:
        source_id = _normalize_metadata_id(source.get('id'))
        source_type = _normalize_metadata_id(source.get('type')).lower() or 'evidence_source'
        source_status = _normalize_metadata_id(source.get('status')).lower() or 'unknown'
        source_summaries.append({
            'id': source_id,
            'type': source_type,
            'label': _image_proposal_source_label(source_type),
            'status': source_status,
            'required': bool(source.get('required')),
            'used': source_id in used_source_ids,
        })

    missing_evidence = []
    for gap in evidence_ledger.get('missing_or_failed') or []:
        if not isinstance(gap, dict):
            continue
        message = _trim_text(gap.get('message'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH)
        if message and message not in missing_evidence:
            missing_evidence.append(message)
        if len(missing_evidence) >= IMAGE_PROPOSAL_METADATA_MAX_ITEMS:
            break
    for requirement in requirements:
        requirement_status = _normalize_metadata_id(requirement.get('status')).lower()
        if requirement_status not in {'pending', 'partial', 'unsatisfied'}:
            continue
        description = _trim_text(requirement.get('description'), IMAGE_PROPOSAL_TEXT_MAX_LENGTH)
        if description and description not in missing_evidence:
            missing_evidence.append(description)
        if len(missing_evidence) >= IMAGE_PROPOSAL_METADATA_MAX_ITEMS:
            break

    reference_images = []
    for artifact in evidence_ledger.get('artifacts') or []:
        if not isinstance(artifact, dict) or artifact.get('type') != 'image_reference':
            continue
        artifact_id = _normalize_metadata_id(artifact.get('id'))
        if artifact_id not in retained_reference_ids:
            continue
        reference_images.append({
            'id': artifact_id,
            'name': _trim_text(artifact.get('name'), 160) or 'Selected image',
            'reference_id': _normalize_metadata_id(artifact.get('reference')),
            'document_id': _normalize_metadata_id(artifact.get('document_id')),
            'message_id': _normalize_metadata_id(artifact.get('message_id')),
        })
        if len(reference_images) >= IMAGE_PROPOSAL_METADATA_MAX_ITEMS:
            break

    blocking_reasons = []
    confirmation_reasons = []
    if ledger_status in {'collecting', 'pending', 'running'}:
        blocking_reasons.append('Evidence collection is still in progress.')
    elif ledger_status == 'cancelled':
        blocking_reasons.append('The evidence review was cancelled.')
    elif ledger_status not in {'ready', 'partial', 'completed'}:
        blocking_reasons.append('The evidence review did not complete successfully.')

    if runtime_status in {'pending', 'running'}:
        blocking_reasons.append('The orchestration workflow is still running.')
    elif runtime_status == 'cancelled':
        blocking_reasons.append('The orchestration workflow was cancelled.')
    elif runtime_status == 'failed':
        blocking_reasons.append('The orchestration workflow failed.')
    elif runtime_status not in {'unavailable', 'succeeded', 'partial'}:
        blocking_reasons.append('The orchestration workflow is not ready for approval.')

    required_pending = any(
        bool(requirement.get('required'))
        and _normalize_metadata_id(requirement.get('status')).lower() == 'pending'
        for requirement in requirements
    )
    if required_pending:
        blocking_reasons.append('Required evidence is still pending.')

    required_cancelled = any(
        bool(source.get('required'))
        and _normalize_metadata_id(source.get('status')).lower() == 'cancelled'
        for source in sources
    )
    if required_cancelled:
        blocking_reasons.append('A required evidence source was cancelled.')

    has_supported_evidence = bool(supported_entries)
    required_incomplete = any(
        bool(requirement.get('required'))
        and _normalize_metadata_id(requirement.get('status')).lower() in {'partial', 'unsatisfied'}
        for requirement in requirements
    )
    if ledger_status == 'partial' or runtime_status == 'partial' or required_incomplete:
        if (
            has_supported_evidence
            and ledger_status in {'ready', 'partial', 'completed'}
            and not blocking_reasons
        ):
            confirmation_reasons.append(
                'Some requested evidence was not available. Review the missing evidence before continuing.'
            )
        elif not blocking_reasons:
            blocking_reasons.append('Required evidence is incomplete and cannot be approved.')

    if blocking_reasons:
        state = 'blocked'
        message = blocking_reasons[0]
    elif confirmation_reasons:
        state = 'confirmation_required'
        message = confirmation_reasons[0]
    else:
        state = 'ready'
        message = 'Evidence review complete. Review the image proposal before generation.'

    return {
        'version': IMAGE_PROPOSAL_APPROVAL_REVIEW_VERSION,
        'state': state,
        'can_approve': state != 'blocked',
        'requires_confirmation': state == 'confirmation_required',
        'ledger_status': ledger_status,
        'runtime_status': runtime_status,
        'message': message,
        'sources': source_summaries,
        'missing_evidence': missing_evidence,
        'reference_images': reference_images,
    }


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
