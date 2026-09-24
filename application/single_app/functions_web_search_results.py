# functions_web_search_results.py
"""Import-light helpers for turning a Foundry web search reply into usable context.

``perform_web_search`` in ``route_backend_chats`` owns the Foundry call. These helpers only
read what it returned: they replace Foundry's citation placeholders with links to the
sources they annotate, and they describe a provider failure by its type and HTTP status
without keeping any provider text. Both ordinary chat and orchestration use them.

Version: 0.261.133
"""

import asyncio
import re


# Foundry agent annotation placeholders, e.g. 【3:1†source】. Bounded so ordinary text using
# the same brackets is not consumed.
FOUNDRY_CITATION_MARKER_PATTERN = re.compile(r'【[^】]{0,40}†[^】]{0,80}】')

_CONNECTION_ERROR_NAMES = frozenset({
    'ServiceRequestError', 'APIConnectionError', 'ClientConnectorError', 'ClientConnectionError',
})


def link_foundry_citation_markers(content, citations):
    """Replace Foundry citation placeholders with numbered links to the sources they annotate.

    Returns the linked text and the ordered sources, one per distinct URL. A placeholder whose
    annotation carries no usable URL is removed rather than left for the answer to repeat.
    """
    text = str(content or '')
    sources = []
    numbers = {}
    for citation in citations or []:
        if not isinstance(citation, dict):
            continue
        url = str(citation.get('url') or '').strip()
        if not url.lower().startswith(('http://', 'https://')):
            continue
        if url not in numbers:
            numbers[url] = len(numbers) + 1
            sources.append({
                'number': numbers[url],
                'title': str(citation.get('title') or url).strip()[:300] or url,
                'url': url,
            })
        marker = str(citation.get('quote') or citation.get('text') or '').strip()
        if marker and FOUNDRY_CITATION_MARKER_PATTERN.fullmatch(marker):
            text = text.replace(marker, f' [{numbers[url]}]({url})')
    return FOUNDRY_CITATION_MARKER_PATTERN.sub('', text), sources


def format_linked_search_results(heading, content, citations):
    """The augmentation text for one search: linked findings plus a numbered source list."""
    linked, sources = link_foundry_citation_markers(content, citations)
    lines = [f"[{source['number']}] {source['title']} - {source['url']}" for source in sources]
    return f'{heading}:\n{linked}' + (
        '\n\nSources (cite by number as markdown links):\n' + '\n'.join(lines) if lines else ''
    )


def describe_web_search_exception(exc):
    """Structured facts about a provider failure: its type and HTTP status, never its text."""
    status = None
    timeout = False
    connection = False
    current = exc
    for _depth in range(4):
        if current is None:
            break
        code = getattr(current, 'status_code', None)
        if not isinstance(code, int):
            code = getattr(getattr(current, 'response', None), 'status_code', None)
        if status is None and isinstance(code, int) and not isinstance(code, bool) and 400 <= code <= 599:
            status = code
        name = type(current).__name__
        if isinstance(current, (TimeoutError, asyncio.TimeoutError)) or 'Timeout' in name:
            timeout = True
        if isinstance(current, ConnectionError) or name in _CONNECTION_ERROR_NAMES:
            connection = True
        current = current.__cause__ or current.__context__
    return {
        'error_type': type(exc).__name__,
        'provider_status': status,
        'provider_timeout': timeout,
        'provider_connection': connection,
    }
