# functions_content_understanding.py

"""Azure AI Content Understanding client used for Enhanced document extraction.

Standard extraction always uses Azure Document Intelligence ``prebuilt-read``. Enhanced extraction
uses Azure AI Content Understanding when the app runs in an Azure commercial cloud and the service is
configured; otherwise callers fall back to Document Intelligence ``prebuilt-layout``.

The public extraction helper intentionally mirrors the return contract of
``functions_content.extract_content_with_azure_di`` so the ingestion pipeline can swap engines
without reshaping downstream chunking.
"""

import json
import logging
import os
import time
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlparse, urlunparse

import requests
from azure.identity import DefaultAzureCredential

from config import AZURE_ENVIRONMENT, cognitive_services_scope
from functions_appinsights import log_event
from functions_azure_endpoint_validation import validate_azure_content_understanding_endpoint
from functions_debug import debug_print
import functions_settings


CONTENT_UNDERSTANDING_ANALYZE_TIMEOUT_SECONDS = 600
CONTENT_UNDERSTANDING_POLL_INTERVAL_SECONDS = 3
CONTENT_UNDERSTANDING_SUBMIT_TIMEOUT_SECONDS = 300
CONTENT_UNDERSTANDING_POLL_TIMEOUT_SECONDS = 60
CONTENT_UNDERSTANDING_TOKEN_REFRESH_BUFFER_SECONDS = 300

# Content Understanding refuses LLM-backed analyzers until the Foundry resource has default model
# deployments configured. That failure is common enough during setup to deserve its own guidance.
CONTENT_UNDERSTANDING_MISSING_DEPLOYMENT_HINTS = (
    'model deployment',
    'modeldeployment',
    'no default',
    'default model',
    'deployment not found',
    'deploymentnotfound',
)

CONTENT_UNDERSTANDING_MISSING_DEPLOYMENT_MESSAGE = (
    "Content Understanding rejected the request because the Foundry resource has no default model "
    "deployments. Deploy a completion model and an embedding model, then set them as Content "
    "Understanding defaults before using Enhanced extraction."
)


class ContentUnderstandingError(Exception):
    """Raised when a Content Understanding request cannot be completed."""


class ContentUnderstandingNotConfiguredError(ContentUnderstandingError):
    """Raised when Content Understanding is unavailable or missing required configuration."""


def _get_settings():
    return functions_settings.get_settings()


def _resolve_config(settings=None, config_override=None):
    """Return normalized Content Understanding configuration from settings or an explicit override."""
    if config_override:
        return {
            'endpoint': functions_settings.normalize_content_understanding_endpoint(
                config_override.get('endpoint')
            ),
            'key': str(config_override.get('key') or '').strip(),
            'authentication_type': functions_settings.normalize_content_understanding_authentication_type(
                config_override.get('authentication_type')
            ),
            'api_version': functions_settings.normalize_content_understanding_api_version(
                config_override.get('api_version')
            ),
            'analyzer_id': functions_settings.normalize_content_understanding_analyzer_id(
                config_override.get('analyzer_id'),
                functions_settings.CONTENT_UNDERSTANDING_DOCUMENT_ANALYZER_DEFAULT,
            ),
            'image_analyzer_id': functions_settings.normalize_content_understanding_analyzer_id(
                config_override.get('image_analyzer_id'),
                functions_settings.CONTENT_UNDERSTANDING_IMAGE_ANALYZER_DEFAULT,
            ),
        }

    return functions_settings.get_content_understanding_config(
        settings if settings is not None else _get_settings()
    )


_TOKEN_CACHE = {'token': None, 'expires_on': 0}


def _get_bearer_token():
    """Return a cached Entra ID access token for Content Understanding."""
    now = time.time()
    cached_token = _TOKEN_CACHE.get('token')
    cached_expiry = _TOKEN_CACHE.get('expires_on') or 0
    if cached_token and cached_expiry - CONTENT_UNDERSTANDING_TOKEN_REFRESH_BUFFER_SECONDS > now:
        return cached_token

    credential = DefaultAzureCredential()
    access_token = credential.get_token(cognitive_services_scope)
    _TOKEN_CACHE['token'] = access_token.token
    _TOKEN_CACHE['expires_on'] = getattr(access_token, 'expires_on', 0) or 0
    return access_token.token


def _build_auth_headers(config):
    """Build authentication headers for either key or managed identity access."""
    if config.get('authentication_type') == 'managed_identity':
        return {'Authorization': f"Bearer {_get_bearer_token()}"}

    key = config.get('key')
    if not key:
        raise ContentUnderstandingNotConfiguredError(
            "Content Understanding key authentication is selected but no key is configured."
        )
    return {'Ocp-Apim-Subscription-Key': key}


def _validate_config(config):
    """Raise when the environment or configuration cannot support a Content Understanding call."""
    if not functions_settings.is_content_understanding_supported_environment():
        raise ContentUnderstandingNotConfiguredError(
            f"Content Understanding is not available in the {AZURE_ENVIRONMENT} cloud."
        )
    if not config.get('endpoint'):
        raise ContentUnderstandingNotConfiguredError(
            "Content Understanding endpoint is not configured."
        )
    try:
        config['endpoint'] = validate_azure_content_understanding_endpoint(config['endpoint'])
    except ValueError as error:
        raise ContentUnderstandingNotConfiguredError(str(error)) from error


def _build_analyze_binary_url(config, analyzer_id, page_range=None):
    encoded_analyzer_id = quote(str(analyzer_id or '').strip(), safe='-._~')
    query_params = {'api-version': config['api_version']}
    if page_range:
        query_params['range'] = page_range
    url = (
        f"{config['endpoint']}/contentunderstanding/analyzers/{encoded_analyzer_id}:analyzeBinary"
        f"?{urlencode(query_params)}"
    )
    return url


def _canonicalize_operation_location(operation_location, config):
    """Return a same-origin Content Understanding polling URL, or raise."""
    raw_location = str(operation_location or '').strip()
    parsed_location = urlparse(raw_location)
    parsed_endpoint = urlparse(config['endpoint'])
    try:
        parsed_port = parsed_location.port
    except ValueError as error:
        raise ContentUnderstandingError(
            "Content Understanding returned an invalid Operation-Location header."
        ) from error

    if (
        parsed_location.scheme != 'https'
        or parsed_location.hostname != parsed_endpoint.hostname
        or parsed_port not in (None, 443)
        or parsed_location.username is not None
        or parsed_location.password is not None
        or parsed_location.fragment
    ):
        raise ContentUnderstandingError(
            "Content Understanding returned an unsafe Operation-Location header."
        )

    path_parts = [part for part in parsed_location.path.split('/') if part]
    decoded_parts = [unquote(part) for part in path_parts]
    if not path_parts or path_parts[0].lower() != 'contentunderstanding':
        raise ContentUnderstandingError(
            "Content Understanding returned an unexpected Operation-Location path."
        )
    if any(part in {'.', '..'} for part in decoded_parts):
        raise ContentUnderstandingError(
            "Content Understanding returned an unsafe Operation-Location path."
        )

    safe_path = '/' + '/'.join(quote(part, safe='-._~:') for part in path_parts)
    safe_query = urlencode(parse_qsl(parsed_location.query, keep_blank_values=True))
    return urlunparse(('https', parsed_endpoint.netloc, safe_path, '', safe_query, ''))


def _describe_http_error(response):
    """Return a readable message for a failed Content Understanding HTTP response."""
    detail = ''
    try:
        payload = response.json()
        error_payload = payload.get('error') if isinstance(payload, dict) else None
        if isinstance(error_payload, dict):
            detail = str(error_payload.get('message') or error_payload.get('code') or '')
        if not detail and isinstance(payload, dict):
            detail = str(payload.get('message') or '')
        if not detail:
            detail = json.dumps(payload)[:500]
    except (ValueError, TypeError):
        detail = (response.text or '')[:500]

    if _looks_like_missing_model_deployment(detail):
        return CONTENT_UNDERSTANDING_MISSING_DEPLOYMENT_MESSAGE

    return f"Content Understanding request failed with HTTP {response.status_code}: {detail}".strip()


def _looks_like_missing_model_deployment(message):
    normalized_message = str(message or '').lower()
    return any(hint in normalized_message for hint in CONTENT_UNDERSTANDING_MISSING_DEPLOYMENT_HINTS)


def analyze_file_with_content_understanding(
    file_path,
    analyzer_id=None,
    page_range=None,
    settings=None,
    config_override=None,
    max_wait_seconds=CONTENT_UNDERSTANDING_ANALYZE_TIMEOUT_SECONDS,
):
    """Submit a local file to Content Understanding and return the completed ``result`` payload."""
    config = _resolve_config(settings=settings, config_override=config_override)
    _validate_config(config)

    resolved_analyzer_id = functions_settings.normalize_content_understanding_analyzer_id(
        analyzer_id,
        config['analyzer_id'],
    )

    with open(file_path, 'rb') as file_handle:
        file_bytes = file_handle.read()

    if not file_bytes:
        raise ContentUnderstandingError(f"Cannot analyze empty file: {os.path.basename(file_path)}")

    headers = {'Content-Type': 'application/octet-stream'}
    headers.update(_build_auth_headers(config))

    submit_url = _build_analyze_binary_url(config, resolved_analyzer_id, page_range=page_range)
    debug_print(
        f"[CONTENT_UNDERSTANDING] Submitting {os.path.basename(file_path)} "
        f"({len(file_bytes)} bytes) to analyzer {resolved_analyzer_id}"
        + (f" range={page_range}" if page_range else "")
    )

    # codeql[py/partial-ssrf]
    response = requests.post(
        submit_url,
        headers=headers,
        data=file_bytes,
        timeout=CONTENT_UNDERSTANDING_SUBMIT_TIMEOUT_SECONDS,
        allow_redirects=False,
    )

    if response.status_code >= 400:
        raise ContentUnderstandingError(_describe_http_error(response))

    # Content extraction analyzers can answer synchronously for small inputs.
    if response.status_code == 200:
        payload = response.json()
        if isinstance(payload, dict) and payload.get('result'):
            return payload['result']
        if isinstance(payload, dict) and payload.get('contents'):
            return payload

    operation_location = response.headers.get('Operation-Location') or response.headers.get('operation-location')
    if not operation_location:
        raise ContentUnderstandingError(
            "Content Understanding did not return an Operation-Location header for the analysis request."
        )

    return _poll_analysis_result(
        operation_location,
        config,
        max_wait_seconds=max_wait_seconds,
    )


def _poll_analysis_result(operation_location, config, max_wait_seconds):
    """Poll a Content Understanding operation until it succeeds, fails, or times out."""
    poll_headers = _build_auth_headers(config)
    poll_url = _canonicalize_operation_location(operation_location, config)
    start_time = time.time()

    while True:
        elapsed_seconds = time.time() - start_time
        if elapsed_seconds > max_wait_seconds:
            raise TimeoutError(
                f"Content Understanding analysis did not finish within {max_wait_seconds} seconds."
            )

        time.sleep(CONTENT_UNDERSTANDING_POLL_INTERVAL_SECONDS)

        # codeql[py/partial-ssrf]
        poll_response = requests.get(
            poll_url,
            headers=poll_headers,
            timeout=CONTENT_UNDERSTANDING_POLL_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
        if poll_response.status_code >= 400:
            raise ContentUnderstandingError(_describe_http_error(poll_response))

        payload = poll_response.json()
        status = str(payload.get('status') or '').strip().lower()

        if status == 'succeeded':
            result = payload.get('result')
            if not result:
                raise ContentUnderstandingError(
                    "Content Understanding reported success but returned no result payload."
                )
            return result

        if status == 'failed':
            error_payload = payload.get('error') or {}
            message = str(error_payload.get('message') or 'Content Understanding analysis failed.')
            if _looks_like_missing_model_deployment(message):
                raise ContentUnderstandingError(CONTENT_UNDERSTANDING_MISSING_DEPLOYMENT_MESSAGE)
            raise ContentUnderstandingError(f"Content Understanding analysis failed: {message}")

        if status == 'canceled':
            raise ContentUnderstandingError("Content Understanding analysis was canceled.")


def _iter_document_contents(result):
    """Yield document content entries from a Content Understanding result payload."""
    contents = (result or {}).get('contents')
    if not isinstance(contents, list):
        return []
    return [content for content in contents if isinstance(content, dict)]


def _slice_markdown_by_spans(markdown_text, spans):
    """Return the markdown covered by a page's spans."""
    if not markdown_text or not spans:
        return ''

    slices = []
    for span in spans:
        if not isinstance(span, dict):
            continue
        try:
            offset = int(span.get('offset', 0))
            length = int(span.get('length', 0))
        except (TypeError, ValueError):
            continue
        if length <= 0:
            continue
        slices.append(markdown_text[offset:offset + length])

    return ''.join(slices)


def _build_figure_summaries(content):
    """Map page-agnostic figure offsets to readable description blocks.

    The description and any structured diagram source are kept separate so de-duplication can drop
    a description that Content Understanding already inlined into the markdown without discarding
    the machine-readable diagram alongside it.
    """
    figures = content.get('figures')
    if not isinstance(figures, list):
        return []

    summaries = []
    for figure in figures:
        if not isinstance(figure, dict):
            continue

        description = str(figure.get('description') or '').strip()
        figure_content = figure.get('content')
        figure_kind = str(figure.get('kind') or '').strip().lower()

        diagram_block = ''
        if figure_kind == 'mermaid' and isinstance(figure_content, str) and figure_content.strip():
            diagram_block = f"```mermaid\n{figure_content.strip()}\n```"
        elif figure_kind == 'chart' and isinstance(figure_content, (dict, list)):
            try:
                diagram_block = f"```json\n{json.dumps(figure_content, ensure_ascii=False)}\n```"
            except (TypeError, ValueError):
                diagram_block = ''

        caption = figure.get('caption')
        caption_text = ''
        if isinstance(caption, dict):
            caption_text = str(caption.get('content') or '').strip()
        elif isinstance(caption, str):
            caption_text = caption.strip()

        # Descriptions are optional in the API schema, so a caption alone is still worth indexing.
        if not description and not diagram_block and not caption_text:
            continue

        label = caption_text or str(figure.get('id') or '').strip() or 'Figure'

        span = figure.get('span')
        offset = None
        if isinstance(span, dict):
            try:
                offset = int(span.get('offset'))
            except (TypeError, ValueError):
                offset = None

        summaries.append({
            'offset': offset,
            'label': label,
            'description': description,
            'diagram_block': diagram_block,
        })

    return summaries


def _render_figure_summary(summary, page_text=''):
    """Render a figure summary block, omitting parts already present in the page markdown."""
    description = summary.get('description') or ''
    diagram_block = summary.get('diagram_block') or ''
    label = summary.get('label') or 'Figure'

    lines = []
    # prebuilt-documentSearch already inlines most descriptions into the markdown.
    if description and description not in page_text:
        lines.append(description)
    if diagram_block and diagram_block not in page_text:
        lines.append(diagram_block)

    if not lines:
        # A caption-only figure still earns a line when nothing else survived de-duplication.
        if label and label not in page_text:
            return f"Figure ({label})"
        return ''

    # The label goes on its own line so a leading code fence still starts at column zero.
    return f"Figure ({label}):\n" + "\n".join(lines)


def _assign_figures_to_pages(figure_summaries, page_ranges):
    """Group figure summary blocks by the page whose span range contains them."""
    figures_by_page = {}
    for summary in figure_summaries:
        offset = summary.get('offset')
        target_page = None

        if offset is not None:
            for page_number, start, end in page_ranges:
                if start <= offset < end:
                    target_page = page_number
                    break

        if target_page is None:
            target_page = page_ranges[0][0] if page_ranges else 1

        figures_by_page.setdefault(target_page, []).append(summary)

    return figures_by_page


def build_pages_from_content_understanding_result(result):
    """Convert a Content Understanding result into ``[{page_number, content}]`` entries.

    Page text is reconstructed by slicing the content-level ``markdown`` with each page's spans, which
    is the documented way to recover per-page content. Figure descriptions are appended to the page
    that contains them when they are not already present in that page's markdown.
    """
    pages_data = []

    for content in _iter_document_contents(result):
        markdown_text = str(content.get('markdown') or '')
        pages = content.get('pages')
        start_page_number = content.get('startPageNumber')
        try:
            start_page_number = int(start_page_number)
        except (TypeError, ValueError):
            start_page_number = 1

        if not isinstance(pages, list) or not pages:
            fallback_content = markdown_text.strip()
            # Figures still carry descriptions even when the response has no per-page spans.
            fallback_blocks = []
            for summary in _build_figure_summaries(content):
                rendered_summary = _render_figure_summary(summary, fallback_content)
                if rendered_summary:
                    fallback_blocks.append(rendered_summary)
            if fallback_blocks:
                fallback_content = (
                    f"{fallback_content.rstrip()}\n\n" + "\n\n".join(fallback_blocks)
                ).strip()
            if fallback_content:
                pages_data.append({
                    'page_number': start_page_number or 1,
                    'content': fallback_content,
                })
            continue

        page_ranges = []
        page_markdown = {}
        for page in pages:
            if not isinstance(page, dict):
                continue
            try:
                page_number = int(page.get('pageNumber'))
            except (TypeError, ValueError):
                page_number = len(page_markdown) + start_page_number

            spans = page.get('spans') if isinstance(page.get('spans'), list) else []
            page_markdown[page_number] = _slice_markdown_by_spans(markdown_text, spans)

            span_starts = []
            span_ends = []
            for span in spans:
                if not isinstance(span, dict):
                    continue
                try:
                    offset = int(span.get('offset', 0))
                    length = int(span.get('length', 0))
                except (TypeError, ValueError):
                    continue
                span_starts.append(offset)
                span_ends.append(offset + length)

            if span_starts:
                page_ranges.append((page_number, min(span_starts), max(span_ends)))

        figures_by_page = _assign_figures_to_pages(_build_figure_summaries(content), page_ranges)

        for page_number in sorted(page_markdown.keys()):
            page_text = page_markdown.get(page_number, '')
            figure_blocks = []
            for summary in figures_by_page.get(page_number, []):
                rendered_summary = _render_figure_summary(summary, page_text)
                if rendered_summary:
                    figure_blocks.append(rendered_summary)

            if figure_blocks:
                page_text = f"{page_text.rstrip()}\n\n" + "\n\n".join(figure_blocks)

            page_text = page_text.strip()
            if not page_text:
                continue

            pages_data.append({
                'page_number': page_number,
                'content': page_text,
            })

    return pages_data


def extract_content_with_content_understanding(file_path, pages=None, settings=None):
    """Extract page-by-page content with Content Understanding.

    Mirrors the return contract of ``functions_content.extract_content_with_azure_di`` so the
    ingestion pipeline can switch engines without reshaping downstream chunking.
    """
    result = analyze_file_with_content_understanding(
        file_path,
        page_range=str(pages) if pages else None,
        settings=settings,
    )

    pages_data = build_pages_from_content_understanding_result(result)
    debug_print(
        f"[CONTENT_UNDERSTANDING] Extracted {len(pages_data)} page(s) from "
        f"{os.path.basename(file_path)}"
    )
    return pages_data


def analyze_image_with_content_understanding(image_path, settings=None):
    """Analyze a standalone image and return its description text, or an empty string."""
    resolved_settings = settings if settings is not None else _get_settings()
    config = _resolve_config(settings=resolved_settings)

    result = analyze_file_with_content_understanding(
        image_path,
        analyzer_id=config['image_analyzer_id'],
        settings=resolved_settings,
    )

    text_blocks = []
    for content in _iter_document_contents(result):
        markdown_text = str(content.get('markdown') or '').strip()
        if markdown_text:
            text_blocks.append(markdown_text)

        for summary in _build_figure_summaries(content):
            rendered_summary = _render_figure_summary(summary, markdown_text)
            if rendered_summary:
                text_blocks.append(rendered_summary)

    return "\n\n".join(block for block in text_blocks if block).strip()


def test_content_understanding_connection(config_override, sample_file_path=None):
    """Validate Content Understanding connectivity and return ``(ok, message)``."""
    if not functions_settings.is_content_understanding_supported_environment():
        return False, (
            f"Content Understanding is not available in the {AZURE_ENVIRONMENT} cloud. "
            "Enhanced extraction uses Document Intelligence Layout here instead."
        )

    config = _resolve_config(config_override=config_override)

    try:
        _validate_config(config)
    except ContentUnderstandingNotConfiguredError as config_error:
        return False, str(config_error)
    if config['authentication_type'] == 'key' and not config['key']:
        return False, "Content Understanding key is required when key authentication is selected."

    try:
        headers = _build_auth_headers(config)
    except ContentUnderstandingError as auth_error:
        return False, str(auth_error)

    analyzer_id = quote(config['analyzer_id'], safe='-._~')
    analyzer_url = f"{config['endpoint']}/contentunderstanding/analyzers/{analyzer_id}"

    try:
        # codeql[py/partial-ssrf]
        response = requests.get(
            analyzer_url,
            headers=headers,
            params={'api-version': config['api_version']},
            timeout=CONTENT_UNDERSTANDING_POLL_TIMEOUT_SECONDS,
            allow_redirects=False,
        )
    except requests.RequestException as request_error:
        return False, f"Content Understanding connection error: {request_error}"

    if response.status_code == 404:
        return False, (
            f"Content Understanding reached the endpoint but analyzer '{analyzer_id}' was not found. "
            "Verify the analyzer id and API version."
        )
    if response.status_code in (401, 403):
        return False, (
            "Content Understanding rejected the credentials. For managed identity, assign the "
            "Cognitive Services User role on the Foundry resource."
        )
    if response.status_code >= 400:
        return False, _describe_http_error(response)

    if not sample_file_path or not os.path.exists(sample_file_path):
        return True, (
            f"Content Understanding connection successful. Analyzer '{analyzer_id}' is reachable."
        )

    try:
        analyze_file_with_content_understanding(
            sample_file_path,
            analyzer_id=analyzer_id,
            config_override=config,
            max_wait_seconds=180,
        )
    except (ContentUnderstandingError, TimeoutError) as analyze_error:
        return False, str(analyze_error)
    except Exception as analyze_error:  # noqa: BLE001 - surface any client failure to the admin
        log_event(
            f"[CONTENT_UNDERSTANDING] Test analysis failed: {analyze_error}",
            level=logging.WARNING,
        )
        return False, f"Content Understanding test analysis failed: {analyze_error}"

    return True, (
        f"Content Understanding connection successful. Analyzer '{analyzer_id}' analyzed the test document."
    )
