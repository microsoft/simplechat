# functions_orchestration_visuals.py
"""Charts, Mermaid diagrams and image proposals in orchestrated answers.

Ordinary chat attaches chart, Mermaid and image-proposal guidance to a request and lets
the model that holds the tool results draw the chart. An orchestrated run splits that
work: gathering steps hold the raw results, and only the final answer step writes the
reply. This module decides which visuals a run should consider, builds the guidance each
step needs, and carries charts created during gathering into the answer.

Saved instruction memories are respected by the same rule the memory system already
states: an explicit ask in the current message wins, otherwise a saved instruction about
visuals overrides proactive or suggested visuals, and style preferences apply wherever a
visual is authored.

Version: 0.261.132
"""

import hashlib
import json
import re

from functions_chart_operations import (
    INLINE_CHART_BLOCK_LANGUAGE,
    build_proactive_chart_guidance_message,
    collect_inline_chart_blocks,
    normalize_inline_chart_markdown,
    user_request_supports_proactive_charts,
    user_requested_chart_visualization,
)
from functions_diagram_operations import build_diagram_guidance_message, user_requested_diagram
from functions_image_proposals import (
    INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE,
    build_image_proposal_guidance_message,
    image_generation_is_enabled,
    user_request_supports_image_proposals,
)


VISUAL_OUTPUT_POLICY_MARKER = '[ORCHESTRATION_VISUAL_OUTPUT_POLICY]'
CHART_PLACEHOLDER_PATTERN = re.compile(r'`?\[\[chart:([A-Za-z0-9_-]{1,64})\]\]`?')
MAX_CARRIED_CHARTS = 8
MAX_CARRIED_CHART_MARKDOWN_LENGTH = 200000
# ``functions_fact_memory_context.build_instruction_memory_payload`` wraps saved instruction
# memories in this tag. Matching it keeps the recalled facts, which are only background
# context, out of the chart sub-step.
INSTRUCTION_MEMORY_TAG = '<Instruction Memory>'

_PLANNED_CHART_PATTERN = re.compile(r'\b(?:chart|charts|charted|charting|plot|plots|plotted|graph|graphs)\b')
_PLANNED_IMAGE_PATTERN = re.compile(
    r'\b(?:image|images|illustration|illustrations|picture|pictures|poster|posters|infographic|'
    r'infographics|storyboard|concept art)\b'
)
_NON_VISUAL_CHART_PHRASES = ('chart of accounts', 'org chart', 'organization chart', 'organizational chart')


def _joined_text(texts):
    return '\n'.join(str(value).strip() for value in (texts or ()) if str(value or '').strip())


def image_proposals_available(settings):
    """Whether image proposal cards can be offered; approval needs image generation on."""
    return image_generation_is_enabled(settings)


def image_requested_by_user(seeds):
    """Whether the user selected Image in the composer for this orchestration request."""
    return isinstance(seeds, dict) and seeds.get('image_generation') is True


def planner_visual_outputs(settings):
    """The visual output kinds the planner may ask the answer to include."""
    return {
        'charts': True,
        'diagrams': True,
        'image_proposals': image_proposals_available(settings),
    }


def _planned_chart(text):
    lowered = text.lower()
    if any(phrase in lowered for phrase in _NON_VISUAL_CHART_PHRASES):
        return False
    return bool(_PLANNED_CHART_PATTERN.search(lowered))


def requested_visual_outputs(user_texts=(), planned_texts=(), *, settings=None, seeds=None):
    """Which visuals a step should consider for this request.

    ``user_texts`` are the user's own words and their contextualized form; an explicit
    visual request there is the user's current instruction. ``planned_texts`` are what the
    planner wrote for this run (a step task or the answer instruction); the planner already
    weighed saved memory, so a visual it asked for is deliberate. Proactive chart markers
    only come from the user's words and never create a chart during gathering.
    """
    user_text = _joined_text(user_texts)
    planned_text = _joined_text(planned_texts)
    images_available = image_proposals_available(settings)
    image_selected = images_available and image_requested_by_user(seeds)
    explicit_chart = user_requested_chart_visualization(user_text)
    planned_chart = bool(planned_text) and (
        user_requested_chart_visualization(planned_text) or _planned_chart(planned_text)
    )
    return {
        'explicit_chart': explicit_chart,
        'chart': explicit_chart or planned_chart,
        'proactive_chart': not explicit_chart and user_request_supports_proactive_charts(user_text),
        'diagram': user_requested_diagram(user_text) or (
            bool(planned_text) and (user_requested_diagram(planned_text) or 'mermaid' in planned_text.lower())
        ),
        'image': images_available and (
            image_selected
            or user_request_supports_image_proposals(user_text)
            or bool(_PLANNED_IMAGE_PATTERN.search(planned_text.lower()))
        ),
        'image_required': image_selected,
    }


def any_visual(visuals):
    """Whether any visual kind is in play."""
    return bool(visuals) and any(
        visuals.get(kind) for kind in ('chart', 'proactive_chart', 'diagram', 'image')
    )


def build_visual_output_policy(visuals, *, has_existing_charts=False):
    """The orchestration-specific rules that frame the shared visual guidance."""
    lines = [
        VISUAL_OUTPUT_POLICY_MARKER,
        'This answer can include SimpleChat visuals: inline charts in '
        f'```{INLINE_CHART_BLOCK_LANGUAGE}``` blocks and diagrams in ```mermaid``` blocks'
        + (
            f', plus image proposal cards in ```{INLINE_IMAGE_PROPOSAL_BLOCK_LANGUAGE}``` blocks that the '
            'user approves before any image is generated.'
            if visuals.get('image') else '.'
        ),
        '- Saved instruction memories about visuals (for example avoiding charts or images, preferred '
        'chart types, colors, or diagram styles) take precedence over the visual guidance in this '
        "conversation unless the user's current message explicitly asks otherwise. Apply saved style "
        'preferences to every visual you write.',
        "- Base every chart value, diagram node, and image detail on the gathered evidence or the user's "
        'own description.',
    ]
    if has_existing_charts:
        lines.append(
            '- Charts listed as already created were built from the exact retrieved data. Place them with '
            'their tokens instead of rewriting them, and never say a chart could not be produced.'
        )
    if visuals.get('image'):
        lines.append(
            '- Propose images only where a picture adds what text, tables, charts, and diagrams cannot, such '
            'as an illustration, scene, poster, concept art, or visual explainer. Never propose an image of '
            'data that is already charted or of structure that is already diagrammed. When the user asks '
            'for images, propose as many distinct images as the request needs.'
        )
    if visuals.get('image_required'):
        lines.append(
            '- The user selected Image for this request: include at least one image proposal that supports '
            'it, and more when the request calls for several.'
        )
    return '\n'.join(lines)


def build_answer_visual_guidance(visuals, *, has_existing_charts=False):
    """System messages for the answer step, in the order they should be applied."""
    if not (any_visual(visuals) or has_existing_charts):
        return []
    messages = [build_visual_output_policy(visuals, has_existing_charts=has_existing_charts)]
    if visuals.get('chart') or visuals.get('proactive_chart') or has_existing_charts:
        messages.append(build_proactive_chart_guidance_message())
    if visuals.get('diagram'):
        messages.append(build_diagram_guidance_message())
    if visuals.get('image'):
        messages.append(build_image_proposal_guidance_message())
    return messages


def gathering_visual_addendum(visuals, *, charts_follow=False):
    """What a gathering step should keep in its findings for the requested visuals."""
    lines = []
    if visuals.get('chart'):
        if charts_follow:
            lines.append(
                'The answer will chart the retrieved values. Retrieve them at the granularity the request '
                'asks for; a separate chart step draws them from the exact results, so do not report '
                'whether a plot can be produced.'
            )
        else:
            lines.append('The answer will chart these values: keep the exact numbers it needs in your findings.')
    if visuals.get('diagram'):
        lines.append(
            'The answer will include a diagram: keep the entities, relationships, direction, and order it '
            'needs in your findings.'
        )
    if visuals.get('image'):
        lines.append(
            'The answer may propose images: keep the concrete visual details, such as subjects, labels, '
            'layout, and style, that they should depict.'
        )
    return ' '.join(lines)


def agent_visual_note(visuals):
    """A short note appended to an agent task when the answer needs a visual."""
    parts = []
    if visuals.get('chart'):
        parts.append('If your tools return the values, create the requested chart with your chart tool from them.')
    if visuals.get('diagram'):
        parts.append('Include the entities and relationships a diagram of the result needs.')
    if visuals.get('image'):
        parts.append('Include the concrete visual details an illustrative image would need.')
    return f"Visual output for this request: {' '.join(parts)}" if parts else ''


def instruction_memory_messages(memory_context):
    """Only the saved instruction memories from an orchestration memory context."""
    memory_context = memory_context if isinstance(memory_context, dict) else {}
    messages = memory_context.get('instruction_messages')
    if not isinstance(messages, list):
        messages = [
            message for message in memory_context.get('context_messages') or ()
            if isinstance(message, dict) and INSTRUCTION_MEMORY_TAG in str(message.get('content') or '')
        ]
    return [
        str(message.get('content') or '').strip() for message in messages
        if isinstance(message, dict) and str(message.get('content') or '').strip()
    ]


def is_inline_chart_citation(citation):
    """Whether a tool citation carries a chart block that must not be truncated."""
    if not isinstance(citation, dict):
        return False
    result = citation.get('function_result')
    return isinstance(result, dict) and normalize_inline_chart_markdown(result.get('chart_markdown')) is not None


def _chart_payload(chart_markdown):
    body = chart_markdown.strip()[len(f'```{INLINE_CHART_BLOCK_LANGUAGE}'):]
    if body.endswith('```'):
        body = body[:-3]
    try:
        payload = json.loads(body.strip())
    except (TypeError, ValueError):
        return {}
    return payload if isinstance(payload, dict) else {}


def collect_run_charts(citations, *, limit=MAX_CARRIED_CHARTS):
    """Charts gathering steps created in this run, deduplicated and bounded."""
    blocks = collect_inline_chart_blocks(citations or [], [])
    charts = []
    seen = set()
    for block in blocks:
        markdown = block.get('chart_markdown') or ''
        if not markdown or len(markdown) > MAX_CARRIED_CHART_MARKDOWN_LENGTH:
            continue
        payload = _chart_payload(markdown)
        chart_id = str(block.get('chart_id') or payload.get('chartId') or '').strip()
        if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', chart_id):
            chart_id = hashlib.sha256(markdown.encode('utf-8')).hexdigest()[:12]
        if chart_id in seen:
            continue
        seen.add(chart_id)
        data = payload.get('data') if isinstance(payload.get('data'), dict) else {}
        labels = data.get('labels') if isinstance(data.get('labels'), list) else []
        datasets = data.get('datasets') if isinstance(data.get('datasets'), list) else []
        points = len(labels) or max(
            (len(dataset.get('data') or []) for dataset in datasets if isinstance(dataset, dict)), default=0,
        )
        charts.append({
            'chart_id': chart_id,
            'chart_markdown': markdown,
            'title': str(payload.get('title') or '').strip()[:160],
            'subtitle': str(payload.get('subtitle') or '').strip()[:160],
            'kind': str(payload.get('kind') or '').strip()[:40],
            'points': points,
        })
        if len(charts) >= limit:
            break
    return charts


def build_existing_charts_note(charts):
    """The answer-prompt section that lists charts and their placement tokens."""
    if not charts:
        return ''
    lines = [
        'Charts already created from the retrieved data. They are shown with your answer; put each '
        'token on its own line where that chart belongs:',
    ]
    for chart in charts:
        details = ', '.join(part for part in (
            f"{chart['kind']} chart" if chart.get('kind') else 'chart',
            f"{chart['points']} points" if chart.get('points') else '',
            chart.get('subtitle') or '',
        ) if part)
        title = chart.get('title') or 'Untitled chart'
        lines.append(f"- [[chart:{chart['chart_id']}]] {title} ({details})")
    lines.append('Do not recreate these charts, and do not say a chart could not be produced.')
    return '\n'.join(lines)


def strip_chart_placeholders(text):
    """The answer text without chart placement tokens, for summaries and previews."""
    return CHART_PLACEHOLDER_PATTERN.sub('', str(text or '')).strip()


def place_chart_blocks(reply, charts):
    """Put each chart where the answer placed its token, then append any it did not place."""
    if not charts:
        return reply
    by_id = {chart['chart_id']: chart for chart in charts}
    placed = set()

    def substitute(match):
        chart_id = match.group(1)
        chart = by_id.get(chart_id)
        if chart is None or chart_id in placed:
            return ''
        placed.add(chart_id)
        return f"\n\n{chart['chart_markdown']}\n\n"

    text = CHART_PLACEHOLDER_PATTERN.sub(substitute, str(reply or ''))
    for chart in charts:
        if chart['chart_id'] in placed:
            continue
        if f'"chartId":"{chart["chart_id"]}"' in text or chart['chart_markdown'] in text:
            placed.add(chart['chart_id'])
    remaining = [chart['chart_markdown'] for chart in charts if chart['chart_id'] not in placed]
    text = text.strip()
    if remaining:
        text = '\n\n'.join([text, *remaining]) if text else '\n\n'.join(remaining)
    return text
