# functions_orchestration_deliverables.py
"""What the user asked to receive, and whether the plan can actually deliver each part.

Version: 0.261.141
Implemented in: 0.261.138

The planner lists its plan's deliverables first: the answer, files, images, charts, and
diagrams the user asked for (``requested: explicit``) and anything it adds on its own
(``suggested``). Each step names the deliverables it produces in ``delivers``.

The server owns the truth about what can be produced. ``build_deliverable_availability``
describes it for the planner from the live capability resolution and export catalog, and
``compile_deliverables`` checks every plan against it:

- a planned deliverable must come from a step whose capability can produce that kind and
  format (a file only from ``render_file`` in the same format, an explicit image only from
  ``generate_image``);
- an unavailable deliverable must carry the exact reason the server reports, and the planner
  cannot call something unavailable that the server can produce.

Nothing here reads the request text, the plan's prose, or its assumptions. Every rule is a
structural comparison between declared deliverables, declared steps, and server state.

The module also owns what deliverables mean at run time: the brief each answer-writing step
receives, the ``[[image:<step_id>]]`` placement tokens, the chat projection of generated
images, and the deterministic delivery notes added after the answer.
"""

import json
import re
from copy import deepcopy

from functions_orchestration_registry import (
    CAPABILITY_ACTION_INVOKE,
    CAPABILITY_COMPOSE,
    CAPABILITY_DOCUMENT_ANALYZE,
    CAPABILITY_DOCUMENT_COMPARE,
    CAPABILITY_GENERATE_IMAGE,
    CAPABILITY_RENDER_FILE,
    MAX_GENERATED_IMAGES_PER_PLAN,
    VISUAL_CHART,
    VISUAL_DIAGRAM,
    VISUAL_IMAGE_PROPOSAL,
    VISUAL_KINDS,
    resolve_admitted_export_catalog,
)
from functions_orchestration_result_contracts import (
    IMAGE_ASSET_KIND, InputBinding, ResultContractError, output_name,
)


KIND_ANSWER = 'answer'
KIND_FILE = 'file'
KIND_IMAGE = 'image'
KIND_CHART = 'chart'
KIND_DIAGRAM = 'diagram'
DELIVERABLE_KINDS = (KIND_ANSWER, KIND_FILE, KIND_IMAGE, KIND_CHART, KIND_DIAGRAM)
REQUESTED_EXPLICIT = 'explicit'
REQUESTED_SUGGESTED = 'suggested'
STATUS_PLANNED = 'planned'
STATUS_UNAVAILABLE = 'unavailable'
IMPLICIT_ANSWER_ID = 'answer'
MAX_DELIVERABLES = 12
MAX_DELIVERABLE_QUANTITY = 12
MAX_DESCRIPTION_LENGTH = 300
MAX_FORMAT_LENGTH = 40
AI_ILLUSTRATION_LABEL = 'AI-generated illustration'

# The closed set of reasons a deliverable can be unavailable. Each one is a condition the
# server can check; the text is application-owned and is what users see.
UNAVAILABLE_REASONS = {
    'capability_not_enabled_for_orchestration': (
        'The capability that produces this is not enabled for orchestration.'
    ),
    'file_rendering_unavailable': 'Downloadable files cannot be created here right now.',
    'format_not_admitted': 'This file format is not available for this plan.',
    'format_not_supported': 'SimpleChat cannot create files in this format.',
    'image_generation_disabled': 'Image generation is turned off for this deployment.',
    'image_generation_unavailable': 'The configured image model cannot generate images right now.',
    'image_budget_exceeded': (
        f'One plan can generate at most {MAX_GENERATED_IMAGES_PER_PLAN} images.'
    ),
}
_KIND_LABELS = {
    KIND_ANSWER: 'answer', KIND_FILE: 'file', KIND_IMAGE: 'image',
    KIND_CHART: 'chart', KIND_DIAGRAM: 'diagram',
}
_FIELDS = frozenset({
    'id', 'kind', 'format', 'requested', 'quantity', 'description', 'status', 'unavailable_reason',
})
_SERVER_FIELDS = frozenset({'implicit', 'unavailable_message'})
_RESULT_KIND_FOR_SOURCE = {
    'records': 'records-v1', 'text': 'text-v1', 'markdown': 'markdown-v1',
    'structured_value': 'structured-v1',
}
_TEXT_OUTPUT_KINDS = ('text-v1', 'markdown-v1')
_ANSWER_PRODUCERS = frozenset({CAPABILITY_COMPOSE, CAPABILITY_DOCUMENT_ANALYZE, CAPABILITY_DOCUMENT_COMPARE})
_IMAGE_OPTION_NAMES = (('size', 'sizes'), ('quality', 'qualities'), ('background', 'backgrounds'))

IMAGE_TOKEN_PATTERN = re.compile(r'`?\[\[image:([A-Za-z][A-Za-z0-9_-]{0,63})\]\]`?')
ASSET_IMAGE_PATTERN = re.compile(r'!\[([^\]\n]{0,300})\]\(asset:([A-Za-z0-9][A-Za-z0-9._-]{0,127})\)')


class DeliverableError(ValueError):
    """A deliverables declaration the server cannot accept; the message is planner-facing."""

    def __init__(self, message, code='deliverables_invalid', *, rule=None):
        super().__init__(message)
        self.message = message
        self.code = code
        self.rule = rule


# --------------------------------------------------------------------------------------
# Server truth
# --------------------------------------------------------------------------------------

def _unavailable(reason):
    return {'status': STATUS_UNAVAILABLE, 'reason': reason}


def _available(**facts):
    return {'status': 'available', **facts}


def _file_reason(unavailable):
    if unavailable.get(CAPABILITY_RENDER_FILE) == 'not_enabled_for_orchestration':
        return 'capability_not_enabled_for_orchestration'
    return 'file_rendering_unavailable'


def _image_reason(settings, unavailable):
    reason = unavailable.get(CAPABILITY_GENERATE_IMAGE)
    if reason == 'not_enabled_for_orchestration':
        return 'capability_not_enabled_for_orchestration'
    if reason in ('image_generation_disabled', 'image_generation_unavailable'):
        return reason
    if reason == 'feature_disabled' or not (isinstance(settings, dict) and settings.get('enable_image_generation')):
        return 'image_generation_disabled'
    return 'image_generation_unavailable'


def _compose_reason(unavailable):
    # compose has no feature gate; only the administrator's allowlist can withhold it.
    return 'capability_not_enabled_for_orchestration'


def _image_options(capabilities):
    """The exact size, quality, and background values the configured image model accepts."""
    for capability in capabilities or ():
        if capability.get('id') != CAPABILITY_GENERATE_IMAGE:
            continue
        properties = (capability.get('inputs') or {}).get('properties') or {}
        return {
            plural: list(properties[name]['enum'])
            for name, plural in _IMAGE_OPTION_NAMES
            if isinstance(properties.get(name), dict) and isinstance(properties[name].get('enum'), list)
        }
    return {}


def build_deliverable_availability(settings, *, capabilities, unavailable=None, export_catalog=None):
    """What this caller's plan can deliver, by kind and file format, and why not when not.

    ``capabilities`` and ``unavailable`` come from the same ``resolve_available_capabilities``
    call that decides what the planner may use, so the two can never disagree. A supplied
    ``export_catalog`` is the admitted format catalog; ``None`` means the shared one.
    """
    # Export declarations are read only when a dependency plan is being described.
    from functions_generated_export_registry import get_generated_file_export_catalog

    settings = settings if isinstance(settings, dict) else {}
    unavailable = dict(unavailable or {})
    available = {capability['id'] for capability in capabilities or ()}
    shared = get_generated_file_export_catalog()
    admitted = {
        entry['format_id']: entry for entry in (
            resolve_admitted_export_catalog(export_catalog) if export_catalog is not None else shared
        )
    }
    rendering = CAPABILITY_RENDER_FILE in available
    file_reason = None if rendering else _file_reason(unavailable)
    formats = {}
    for entry in shared:
        current = admitted.get(entry['format_id'], entry)
        record = {
            'source_kinds': sorted({
                _RESULT_KIND_FOR_SOURCE[kind] for profile in current['profiles']
                for kind in profile['source_kinds'] if kind in _RESULT_KIND_FOR_SOURCE
            }),
            'profiles': [profile['profile'] for profile in current['profiles']],
            'embeds_images': bool(entry.get('rich_media')),
        }
        if not rendering:
            record.update(_unavailable(file_reason))
        elif entry['format_id'] not in admitted:
            record.update(_unavailable('format_not_admitted'))
        else:
            record['status'] = 'available'
        formats[entry['format_id']] = record
    compose = CAPABILITY_COMPOSE in available
    images_enabled = bool(settings.get('enable_image_generation'))
    explicit_images = _available(
        produced_by=[CAPABILITY_GENERATE_IMAGE], max_per_plan=MAX_GENERATED_IMAGES_PER_PLAN,
        options=_image_options(capabilities),
    ) if CAPABILITY_GENERATE_IMAGE in available else _unavailable(_image_reason(settings, unavailable))
    if not images_enabled:
        suggested_images = _unavailable('image_generation_disabled')
    elif not compose:
        suggested_images = _unavailable(_compose_reason(unavailable))
    else:
        suggested_images = _available(produced_by=[CAPABILITY_COMPOSE], visual=VISUAL_IMAGE_PROPOSAL)
    chart_producers = [
        capability_id for capability_id in (CAPABILITY_COMPOSE, CAPABILITY_ACTION_INVOKE)
        if capability_id in available
    ]
    facts = [
        'Only render_file creates a downloadable file. Text, CSV, or Markdown written into the chat '
        'answer is not a file.',
        'web_search, url_fetch, and deep_research return text and links only. They cannot retrieve, '
        'download, or embed existing images or photographs.',
    ]
    recipes = []
    if rendering:
        recipes.extend([
            {'for': 'CSV or XLSX file', 'steps': (
                'compose a records-v1 output with explicit columns, then render_file with csv and '
                'tabular_records_v1, or xlsx and tabular_workbook_v1, and options.columns in the same '
                'order (xlsx also needs options.sheet_name).'
            )},
            {'for': 'DOCX or PDF document', 'steps': (
                'compose a complete markdown-v1 document, then render_file with docx or pdf and '
                'prepared_report_v1 (options.title is optional).'
            )},
            {'for': 'PPTX deck', 'steps': (
                'compose a structured-v1 output with profile prepared_slide_deck_v1, then render_file '
                'with pptx and prepared_slide_deck_v1.'
            )},
        ])
    if explicit_images['status'] == 'available':
        facts.extend([
            'generate_image creates a new AI-generated illustration, not a photograph. Title every '
            'generated image as an illustration, especially for real people and historical figures.',
            'DOCX, PDF, and PPTX files embed the generated images their prepared content places. '
            'Other formats do not contain images.',
        ])
        recipes.append({'for': 'Images the user asked for', 'steps': (
            'one generate_image step per image, each with a self-contained prompt and title; bind '
            'each "image" output to the compose step that writes the answer or file content as an '
            'optional named input; that step places [[image:<step_id>]] where each image belongs.'
        )})
    if suggested_images['status'] == 'available':
        facts.append(
            'Image proposal cards are suggestions the user approves after the answer arrives, so '
            'they never appear in a file.'
        )
    if CAPABILITY_ACTION_INVOKE in available:
        recipes.append({'for': 'Chart of data an action retrieves', 'steps': (
            'action_invoke with visuals ["chart"] charts the exact rows it retrieves; the compose '
            'step that binds it places the chart.'
        )})
    return {
        KIND_ANSWER: _available(produced_by=[CAPABILITY_COMPOSE]) if compose else _unavailable(
            _compose_reason(unavailable),
        ),
        KIND_FILE: {
            **(_available() if rendering else _unavailable(file_reason)),
            'produced_by': [CAPABILITY_RENDER_FILE], 'formats': formats,
        },
        KIND_IMAGE: {'explicit': explicit_images, 'suggested': suggested_images},
        KIND_CHART: _available(produced_by=chart_producers) if chart_producers else _unavailable(
            _compose_reason(unavailable),
        ),
        KIND_DIAGRAM: _available(produced_by=[CAPABILITY_COMPOSE]) if compose else _unavailable(
            _compose_reason(unavailable),
        ),
        'unavailable_reasons': dict(UNAVAILABLE_REASONS),
        'facts': facts,
        'recipes': recipes,
    }


def canonical_file_format(value, catalog=None):
    """A catalog format id for a declared format or alias, or the lowercased value unchanged."""
    text = str(value or '').strip().lower().lstrip('.')
    if catalog is None:
        # Export declarations are read only when a file deliverable is compiled.
        from functions_generated_export_registry import get_generated_file_export_catalog

        catalog = get_generated_file_export_catalog()
    for entry in catalog:
        if text == entry['format_id'] or text in entry.get('aliases', ()):
            return entry['format_id']
    return text


def _verdict(availability, deliverable, *, planned_images=0):
    """The server's reason a deliverable cannot be produced, or None when it can."""
    kind = deliverable['kind']
    if kind == KIND_FILE:
        entry = availability[KIND_FILE]['formats'].get(deliverable['format'])
        if entry is None:
            return 'format_not_supported'
        return entry.get('reason') if entry['status'] != 'available' else None
    if kind == KIND_IMAGE:
        requested = deliverable['requested']
        entry = availability[KIND_IMAGE]['explicit' if requested == REQUESTED_EXPLICIT else 'suggested']
        if entry['status'] != 'available':
            return entry.get('reason')
        # The budget is a reason only once the plan already generates as many images as allowed.
        if (
            requested == REQUESTED_EXPLICIT and deliverable['status'] == STATUS_UNAVAILABLE
            and planned_images >= MAX_GENERATED_IMAGES_PER_PLAN
        ):
            return 'image_budget_exceeded'
        return None
    entry = availability[kind]
    return entry.get('reason') if entry['status'] != 'available' else None


# --------------------------------------------------------------------------------------
# Plan validation
# --------------------------------------------------------------------------------------

def _label(deliverable):
    kind = deliverable['kind']
    if kind == KIND_FILE:
        return f"file deliverable \"{deliverable['id']}\" ({deliverable['format']})"
    return f"{_KIND_LABELS[kind]} deliverable \"{deliverable['id']}\""


def _sentence_label(deliverable):
    label = _label(deliverable)
    return label[:1].upper() + label[1:]


def _parse_deliverables(raw):
    if raw is None:
        return []
    if type(raw) is not list:
        raise DeliverableError(
            '"deliverables" must be a list of deliverable objects.', rule='deliverables_not_list',
        )
    # The server-added answer of a plan that declared nothing is derived again, unless the
    # planner kept it beside real deliverables; then it is an ordinary declared answer.
    declared = any(type(entry) is dict and entry.get('implicit') is not True for entry in raw)
    parsed, seen = [], set()
    for entry in raw:
        if type(entry) is not dict:
            raise DeliverableError('Each deliverable must be an object.', rule='deliverable_not_object')
        if entry.get('implicit') is True and not declared:
            continue
        unknown = set(entry) - _FIELDS - _SERVER_FIELDS
        if unknown:
            raise DeliverableError(
                'A deliverable has unsupported fields. Use only id, kind, format, requested, '
                'quantity, description, status, and unavailable_reason.',
                rule='unsupported_deliverable_field',
            )
        try:
            identifier = output_name(entry.get('id'))
        except ResultContractError as exc:
            raise DeliverableError(
                'Each deliverable needs an id of letters, digits, "_" or "-", starting with a letter.',
                rule='invalid_deliverable_id',
            ) from exc
        if identifier in seen:
            raise DeliverableError(
                f'Deliverable id "{identifier}" is used more than once.', rule='duplicate_deliverable_id',
            )
        seen.add(identifier)
        kind = entry.get('kind')
        if kind not in DELIVERABLE_KINDS:
            raise DeliverableError(
                f'Deliverable "{identifier}" needs kind answer, file, image, chart, or diagram.',
                rule='invalid_deliverable_kind',
            )
        requested = entry.get('requested')
        if requested not in (REQUESTED_EXPLICIT, REQUESTED_SUGGESTED):
            raise DeliverableError(
                f'Deliverable "{identifier}" needs requested explicit or suggested.', rule='invalid_requested_value',
            )
        status = entry.get('status')
        if status not in (STATUS_PLANNED, STATUS_UNAVAILABLE):
            raise DeliverableError(
                f'Deliverable "{identifier}" needs status planned or unavailable.', rule='invalid_deliverable_status',
            )
        description = entry.get('description')
        if type(description) is not str or not description.strip():
            raise DeliverableError(
                f'Deliverable "{identifier}" needs a short description.', rule='missing_description',
            )
        deliverable = {
            'id': identifier, 'kind': kind, 'requested': requested, 'status': status,
            'description': description.strip()[:MAX_DESCRIPTION_LENGTH].rstrip(),
        }
        if kind == KIND_FILE:
            value = entry.get('format')
            if type(value) is not str or not value.strip() or len(value) > MAX_FORMAT_LENGTH:
                raise DeliverableError(
                    f'File deliverable "{identifier}" needs its file format id.', rule='invalid_file_format',
                )
            deliverable['format'] = canonical_file_format(value)
        elif entry.get('format') not in (None, ''):
            raise DeliverableError(
                f'Only file deliverables declare a format; remove it from "{identifier}".', rule='non_file_format',
            )
        if 'quantity' in entry and entry['quantity'] is not None:
            quantity = entry['quantity']
            if (
                kind not in (KIND_FILE, KIND_IMAGE) or type(quantity) is not int
                or not 1 <= quantity <= MAX_DELIVERABLE_QUANTITY
            ):
                raise DeliverableError(
                    f'quantity counts files or images from 1 to {MAX_DELIVERABLE_QUANTITY}; '
                    f'fix or remove it on "{identifier}".', rule='invalid_quantity',
                )
            deliverable['quantity'] = quantity
        reason = entry.get('unavailable_reason')
        if status == STATUS_UNAVAILABLE:
            if reason not in UNAVAILABLE_REASONS:
                raise DeliverableError(
                    f'Unavailable deliverable "{identifier}" needs an unavailable_reason from '
                    'capability_availability.deliverables.unavailable_reasons.', rule='invalid_unavailable_reason',
                )
            deliverable['unavailable_reason'] = reason
            deliverable['unavailable_message'] = UNAVAILABLE_REASONS[reason]
        elif reason not in (None, ''):
            raise DeliverableError(
                f'Planned deliverable "{identifier}" cannot have an unavailable_reason.',
                rule='unexpected_unavailable_reason',
            )
        parsed.append(deliverable)
    if len(parsed) > MAX_DELIVERABLES:
        raise DeliverableError(
            f'A plan can declare at most {MAX_DELIVERABLES} deliverables.', rule='deliverable_limit',
        )
    return parsed


def implicit_answer_deliverable():
    return {
        'id': IMPLICIT_ANSWER_ID, 'kind': KIND_ANSWER, 'requested': REQUESTED_EXPLICIT,
        'status': STATUS_PLANNED, 'description': 'An answer to your request.', 'implicit': True,
    }


def _markdown_outputs(step):
    return [output['name'] for output in step.get('outputs') or () if output.get('kind') == 'markdown-v1']


def _final_step_id(final_response):
    if not final_response:
        return None, False
    binding = InputBinding.from_dict(final_response)
    return binding.step_id, binding.existing_result is not None


def _render_source(step):
    source = ((step.get('inputs') or {}).get('source') or {}).get('binding')
    if not isinstance(source, dict):
        return None, None
    binding = InputBinding.from_dict(source)
    return binding.step_id, binding.output_name


def _image_inputs(step, by_id):
    """Named inputs of a step that bind a generate_image step's image output."""
    images = []
    for name, value in (step.get('inputs') or {}).items():
        binding = InputBinding.from_dict(value['binding'])
        producer = by_id.get(binding.step_id) if binding.step_id else None
        if producer is not None and producer['capability_id'] == CAPABILITY_GENERATE_IMAGE:
            images.append((name, producer))
    return images


def _check_producer(step, deliverable, final_step):
    """Raise unless this step's capability can produce the deliverable's kind and format."""
    kind, capability = deliverable['kind'], step['capability_id']
    step_id = step['step_id']
    if kind == KIND_FILE:
        if capability != CAPABILITY_RENDER_FILE:
            raise DeliverableError(
                f'Step "{step_id}" cannot deliver {_label(deliverable)}: only a render_file step creates a file.',
                rule='file_producer_mismatch',
            )
        if step['arguments'].get('output_format') != deliverable['format']:
            raise DeliverableError(
                f'Step "{step_id}" renders {step["arguments"].get("output_format")}, but '
                f'{_label(deliverable)} is {deliverable["format"]}. The output_format must match.',
                rule='file_format_mismatch',
            )
    elif kind == KIND_IMAGE and deliverable['requested'] == REQUESTED_EXPLICIT:
        if capability != CAPABILITY_GENERATE_IMAGE:
            raise DeliverableError(
                f'Step "{step_id}" cannot deliver {_label(deliverable)}: explicitly requested images '
                'come only from generate_image steps.', rule='image_producer_mismatch',
            )
    elif kind == KIND_IMAGE:
        if capability != CAPABILITY_COMPOSE or not _markdown_outputs(step):
            raise DeliverableError(
                f'Step "{step_id}" cannot deliver suggested {_label(deliverable)}: suggested images are '
                'image proposal cards in a compose step with a markdown-v1 output.',
                rule='suggested_image_producer_mismatch',
            )
    elif kind == KIND_CHART:
        if capability == CAPABILITY_ACTION_INVOKE:
            return
        if capability != CAPABILITY_COMPOSE or not _markdown_outputs(step):
            raise DeliverableError(
                f'Step "{step_id}" cannot deliver {_label(deliverable)}: charts come from a compose step '
                'with a markdown-v1 output, or from action_invoke charting its rows.',
                rule='chart_producer_mismatch',
            )
    elif kind == KIND_DIAGRAM:
        if capability != CAPABILITY_COMPOSE or not _markdown_outputs(step):
            raise DeliverableError(
                f'Step "{step_id}" cannot deliver {_label(deliverable)}: diagrams come from a compose '
                'step with a markdown-v1 output.', rule='diagram_producer_mismatch',
            )
    elif kind == KIND_ANSWER:
        if capability not in _ANSWER_PRODUCERS or step_id != final_step:
            raise DeliverableError(
                f'Step "{step_id}" cannot deliver {_label(deliverable)}: the answer comes from the '
                'step final_response selects.', rule='answer_producer_mismatch',
            )


def _link_unambiguous(deliverables, steps, final_step):
    """Fill ``delivers`` only where exactly one deliverable can be meant; never guess between two.

    The answer comes from the final_response producer by definition. A render step with no
    ``delivers`` belongs to the only planned file deliverable of its exact format, and an
    image step to the plan's only explicit image deliverable.
    """
    planned = [deliverable for deliverable in deliverables if deliverable['status'] == STATUS_PLANNED]
    claimed = {identifier for step in steps for identifier in step['delivers']}
    by_step = {step['step_id']: step for step in steps}
    if final_step in by_step:
        for deliverable in planned:
            if deliverable['kind'] == KIND_ANSWER and deliverable['id'] not in claimed:
                by_step[final_step]['delivers'].append(deliverable['id'])
    explicit_images = [
        deliverable for deliverable in planned
        if deliverable['kind'] == KIND_IMAGE and deliverable['requested'] == REQUESTED_EXPLICIT
    ]
    for step in steps:
        if step['delivers']:
            continue
        if step['capability_id'] == CAPABILITY_RENDER_FILE:
            matches = [
                deliverable for deliverable in planned
                if deliverable['kind'] == KIND_FILE
                and deliverable['format'] == step['arguments'].get('output_format')
            ]
            if len(matches) == 1:
                step['delivers'].append(matches[0]['id'])
        elif step['capability_id'] == CAPABILITY_GENERATE_IMAGE and len(explicit_images) == 1:
            step['delivers'].append(explicit_images[0]['id'])


def _derive_visuals(step, deliverables):
    """Chart, diagram, and suggested-image deliverables become the step's structured visuals."""
    wanted = set(step['arguments'].get('visuals') or ())
    for deliverable in deliverables:
        if deliverable['status'] != STATUS_PLANNED:
            continue
        if deliverable['kind'] == KIND_CHART:
            wanted.add(VISUAL_CHART)
        elif deliverable['kind'] == KIND_DIAGRAM and step['capability_id'] == CAPABILITY_COMPOSE:
            wanted.add(VISUAL_DIAGRAM)
        elif (
            deliverable['kind'] == KIND_IMAGE and deliverable['requested'] == REQUESTED_SUGGESTED
            and step['capability_id'] == CAPABILITY_COMPOSE
        ):
            wanted.add(VISUAL_IMAGE_PROPOSAL)
    if wanted:
        step['arguments']['visuals'] = [kind for kind in VISUAL_KINDS if kind in wanted]


def _brief_entry(deliverable, relation, **extra):
    entry = {
        'relation': relation, 'id': deliverable['id'], 'kind': deliverable['kind'],
        'requested': deliverable['requested'], 'description': deliverable['description'],
        **({'format': deliverable['format']} if 'format' in deliverable else {}),
        **({'quantity': deliverable['quantity']} if 'quantity' in deliverable else {}),
    }
    entry.update(extra)
    return entry


def _deliverable_briefs(deliverables, steps, final_step):
    """Attach to each compose step the deliverables its content is for."""
    by_id = {step['step_id']: step for step in steps}
    lookup = {deliverable['id']: deliverable for deliverable in deliverables}
    for step in steps:
        step.pop('deliverable_context', None)
    for step in steps:
        if step['capability_id'] != CAPABILITY_COMPOSE:
            continue
        brief = [
            _brief_entry(lookup[identifier], 'delivers') for identifier in step.get('delivers') or ()
            if identifier in lookup and lookup[identifier]['status'] == STATUS_PLANNED
        ]
        for render in steps:
            if render['capability_id'] != CAPABILITY_RENDER_FILE:
                continue
            source_step, source_output = _render_source(render)
            if source_step != step['step_id']:
                continue
            for identifier in render.get('delivers') or ():
                deliverable = lookup.get(identifier)
                if deliverable is not None and deliverable['status'] == STATUS_PLANNED:
                    brief.append(_brief_entry(
                        deliverable, 'rendered_as', output=source_output,
                        file_name=render['arguments'].get('file_name'), enabled=render.get('enabled', True),
                    ))
        for _name, producer in _image_inputs(step, by_id):
            for identifier in producer.get('delivers') or ():
                deliverable = lookup.get(identifier)
                if deliverable is not None and not any(
                    entry['relation'] == 'images' and entry['id'] == identifier for entry in brief
                ):
                    brief.append(_brief_entry(deliverable, 'images'))
        if step['step_id'] == final_step:
            brief.extend(
                _brief_entry(
                    deliverable, 'unavailable', reason=deliverable['unavailable_reason'],
                    message=deliverable['unavailable_message'],
                )
                for deliverable in deliverables
                if deliverable['status'] == STATUS_UNAVAILABLE and deliverable['requested'] == REQUESTED_EXPLICIT
            )
        if brief:
            step['deliverable_context'] = brief


def compile_deliverables(
    raw_deliverables, steps, *, final_response=None, availability=None, image_selected=False,
):
    """Validate declared deliverables against compiled steps and return their normal form.

    ``steps`` are the accepted, dependency-compiled plan steps. Their ``delivers`` lists are
    normalized in place, chart, diagram, and suggested-image deliverables become structured
    visuals, and each compose step receives the ``deliverable_context`` it writes for.

    ``availability`` is the server truth from ``build_deliverable_availability``. It is
    supplied while planning: then planned deliverables must be delivered by enabled steps,
    unavailable claims must match the server exactly, and ``image_selected`` (the composer's
    Image control) requires an explicit image deliverable. Saved plans are revalidated without
    it, so a later change in availability or a step the user turned off never invalidates
    an approved plan; the delivery notes report such gaps instead.
    """
    deliverables = _parse_deliverables(raw_deliverables)
    final_step, final_is_existing = _final_step_id(final_response)
    strict = availability is not None
    for step in steps:
        step.pop('deliverable_context', None)
        values = step.get('delivers', [])
        if type(values) is not list or any(type(value) is not str for value in values):
            raise DeliverableError(
                f'Step "{step["step_id"]}" delivers must be a list of deliverable ids.', rule='invalid_delivers',
            )
        if len(set(values)) != len(values):
            raise DeliverableError(
                f'Step "{step["step_id"]}" lists a deliverable more than once.', rule='duplicate_step_deliverable',
            )
        step['delivers'] = list(values)
    if not deliverables:
        if strict and image_selected:
            raise DeliverableError(
                'The user selected the Image control: declare at least one explicit image deliverable.',
                rule='missing_selected_image',
            )
        for step in steps:
            step['delivers'] = [value for value in step['delivers'] if value != IMPLICIT_ANSWER_ID]
            if step['delivers']:
                raise DeliverableError(
                    f'Step "{step["step_id"]}" delivers an undeclared deliverable. Declare it in "deliverables".',
                    rule='undeclared_step_deliverable',
                )
            step.pop('delivers')
        return [implicit_answer_deliverable()]
    lookup = {deliverable['id']: deliverable for deliverable in deliverables}
    for step in steps:
        unknown = [value for value in step['delivers'] if value not in lookup]
        if unknown:
            raise DeliverableError(
                f'Step "{step["step_id"]}" delivers "{unknown[0]}", which is not a declared deliverable.',
                rule='undeclared_step_deliverable',
            )
    _link_unambiguous(deliverables, steps, final_step)
    delivering = {deliverable['id']: [] for deliverable in deliverables}
    for step in steps:
        for identifier in step['delivers']:
            deliverable = lookup[identifier]
            if deliverable['status'] == STATUS_UNAVAILABLE:
                raise DeliverableError(
                    f'Step "{step["step_id"]}" delivers {_label(deliverable)}, which is marked unavailable.',
                    rule='unavailable_deliverable_produced',
                )
            _check_producer(step, deliverable, final_step)
            delivering[identifier].append(step)
    for step in steps:
        if not step['delivers']:
            if step['capability_id'] == CAPABILITY_RENDER_FILE:
                raise DeliverableError(
                    f'render_file step "{step["step_id"]}" creates a file that no deliverable declares. '
                    'Declare the file as an explicit or suggested file deliverable and list it in delivers.',
                    rule='undeclared_file_output',
                )
            if step['capability_id'] == CAPABILITY_GENERATE_IMAGE:
                raise DeliverableError(
                    f'generate_image step "{step["step_id"]}" makes an image that no deliverable declares. '
                    'Declare it as an explicit image deliverable and list it in delivers.',
                    rule='undeclared_image_output',
                )
    planned_images = sum(
        1 for step in steps if step['capability_id'] == CAPABILITY_GENERATE_IMAGE and step.get('enabled', True)
    )
    for deliverable in deliverables:
        producers = delivering[deliverable['id']]
        verdict = _verdict(availability, deliverable, planned_images=planned_images) if strict else None
        if deliverable['status'] == STATUS_PLANNED:
            if verdict is not None:
                raise DeliverableError(
                    f'{_sentence_label(deliverable)} cannot be produced here: {verdict}. Mark it '
                    f'unavailable with unavailable_reason "{verdict}".', rule='planned_deliverable_unavailable',
                )
            if deliverable['kind'] == KIND_ANSWER and final_is_existing and not producers:
                continue
            if strict:
                producers = [step for step in producers if step.get('enabled', True)]
            if not producers and deliverable['kind'] == KIND_ANSWER:
                raise DeliverableError(
                    f'The planned {_label(deliverable)} needs final_response to select the prepared '
                    'answer text of the step that writes it.', rule='missing_final_response',
                )
            if not producers:
                raise DeliverableError(
                    f'No step delivers the planned {_label(deliverable)}. Add a step that can produce '
                    'it and list the deliverable in that step\'s delivers, or mark it unavailable with '
                    'the reason capability_availability.deliverables gives.', rule='missing_deliverable_producer',
                )
            quantity = deliverable.get('quantity')
            counted = deliverable['kind'] == KIND_FILE or (
                deliverable['kind'] == KIND_IMAGE and deliverable['requested'] == REQUESTED_EXPLICIT
            )
            if quantity is not None and counted and len(producers) < quantity:
                raise DeliverableError(
                    f'{_sentence_label(deliverable)} asks for {quantity} but only {len(producers)} '
                    'steps deliver it. Plan one step per item, or split the deliverable and mark the '
                    'remainder unavailable with its reason.', rule='insufficient_producers',
                )
        elif strict:
            if verdict is None:
                raise DeliverableError(
                    f'The server can produce {_label(deliverable)}. Plan it with a capable step '
                    'instead of marking it unavailable.', rule='available_deliverable_declined',
                )
            if verdict != deliverable['unavailable_reason']:
                raise DeliverableError(
                    f'{_sentence_label(deliverable)} is unavailable because of "{verdict}", not '
                    f'"{deliverable["unavailable_reason"]}".', rule='unavailable_reason_mismatch',
                )
    if strict and image_selected and not any(
        deliverable['kind'] == KIND_IMAGE and deliverable['requested'] == REQUESTED_EXPLICIT
        for deliverable in deliverables
    ):
        raise DeliverableError(
            'The user selected the Image control: declare at least one explicit image deliverable.',
            rule='missing_selected_image',
        )
    if strict:
        options = ((availability.get(KIND_IMAGE) or {}).get('explicit') or {}).get('options') or {}
        for step in steps:
            if step['capability_id'] != CAPABILITY_GENERATE_IMAGE:
                continue
            for name, plural in _IMAGE_OPTION_NAMES:
                value = step['arguments'].get(name)
                if value and value not in (options.get(plural) or ()):
                    raise DeliverableError(
                        f'Step "{step["step_id"]}" sets {name} "{value}", which the configured image '
                        f'model does not support. Use one of {options.get(plural) or []} or omit it.',
                        rule='unsupported_image_option',
                    )
    for step in steps:
        if step['delivers'] and step['capability_id'] in (CAPABILITY_COMPOSE, CAPABILITY_ACTION_INVOKE):
            _derive_visuals(step, [lookup[identifier] for identifier in step['delivers']])
    _deliverable_briefs(deliverables, steps, final_step)
    for step in steps:
        if not step['delivers']:
            step.pop('delivers')
    return deliverables


# --------------------------------------------------------------------------------------
# The answer step
# --------------------------------------------------------------------------------------

def _format_label(value):
    return {
        'docx': 'Word document (.docx)', 'pdf': 'PDF', 'pptx': 'PowerPoint deck (.pptx)',
        'xlsx': 'Excel workbook (.xlsx)', 'csv': 'CSV file', 'md': 'Markdown file',
        'txt': 'text file', 'json': 'JSON file', 'yaml': 'YAML file', 'xml': 'XML file',
    }.get(value, f'{value} file')


def image_alt_text(title):
    return f'{AI_ILLUSTRATION_LABEL}: {title}'[:300]


def _rendered_output_guidance(entry, kind):
    """How to write an output a later step saves, by the kind of value that step reads.

    Rows and structured values are data the file is built from. Asking for "the finished
    file" there invites CSV or file text where the declared output needs JSON rows.
    """
    output = entry.get('output') or 'the output'
    name = entry.get('file_name') or 'the file'
    target = f'A later step saves output "{output}" as {name}, a {_format_label(entry.get("format"))}'
    if kind == 'records-v1':
        return (
            f'{target}, from the rows you return. Return "{output}" as rows, not as file text: '
            'that step writes the file. Never say files cannot be created.'
        )
    if kind == 'structured-v1':
        return (
            f'{target}, from the value you return. Return "{output}" as the structured value its '
            'schema or profile describes, not as file text: that step builds the file. Never say '
            'files cannot be created.'
        )
    return (
        f'{target}. Write its complete content as the finished file: no preamble about the file, '
        'and no notes about saving, attaching, converting, or downloading it. Never say files '
        'cannot be created.'
    )


def compose_deliverable_guidance(step, images):
    """System guidance for an answer step, from its deliverables and its bound images.

    ``images`` lists the generated images this step received as inputs, each a dict with
    ``asset_id`` and ``title``. The guidance is built from structured plan data only.
    """
    brief = step.get('deliverable_context') or []
    kinds = {
        output.get('name'): output.get('kind')
        for output in step.get('outputs') or () if isinstance(output, dict)
    }
    lines = []
    rendered = [entry for entry in brief if entry['relation'] == 'rendered_as' and entry.get('enabled', True)]
    for entry in rendered:
        lines.append(_rendered_output_guidance(entry, kinds.get(entry.get('output'))))
    wanted = [entry for entry in brief if entry['relation'] in ('delivers', 'images')]
    if wanted:
        lines.append('This content must include what the user asked for:')
        lines.extend(
            f"- {entry['description']}" + (f" ({entry['quantity']})" if entry.get('quantity') else '')
            for entry in wanted
        )
    if images:
        tokens = ', '.join(f"[[image:{image['asset_id']}]] ({image['title']})" for image in images)
        lines.append(
            f'These AI-generated illustrations were created for this answer: {tokens}. Put each token '
            'on its own line where that image belongs in Markdown content, at most once. A caption '
            'labelling it as an AI-generated illustration is added automatically. In a prepared slide '
            'deck, use an image shape whose source is "asset:<step_id>". Do not describe an image as a '
            'photograph, and do not refer to images other than these.'
        )
    unavailable = [entry for entry in brief if entry['relation'] == 'unavailable']
    for entry in unavailable:
        lines.append(
            f"The user asked for {entry['description']}, which is not available here: {entry['message']} "
            'Do not claim, promise, or apologize for it; a delivery note is added after the answer. '
            'Deliver the rest of the request as well as you can.'
        )
    return ['\n'.join(lines)] if lines else []


def _caption(title):
    return f'*{AI_ILLUSTRATION_LABEL}: {_safe_markdown_text(title)}*'


def _safe_markdown_text(value):
    return re.sub(r'[\[\]()`*_<>\n\r]+', ' ', str(value or '')).strip()


def place_image_tokens(text, images):
    """Replace ``[[image:<id>]]`` with the image and its caption; append any it did not place.

    ``images`` maps an asset id to its title, in the order the step received them. Unknown
    tokens and asset references are removed, so prepared content can only reference images
    this step actually received. Content without tokens, references, or images is unchanged.
    """
    source = str(text or '')
    placed = set()
    changed = False

    def image_block(asset_id):
        title = images[asset_id]
        placed.add(asset_id)
        return f'\n\n![{_safe_markdown_text(image_alt_text(title))}](asset:{asset_id})\n\n{_caption(title)}\n\n'

    def from_token(match):
        nonlocal changed
        changed = True
        asset_id = match.group(1)
        return image_block(asset_id) if asset_id in images and asset_id not in placed else ''

    def from_reference(match):
        nonlocal changed
        changed = True
        asset_id = match.group(2)
        return image_block(asset_id) if asset_id in images and asset_id not in placed else ''

    # Model-written references first, so the images this pass inserts are never revisited.
    value = ASSET_IMAGE_PATTERN.sub(from_reference, source)
    value = IMAGE_TOKEN_PATTERN.sub(from_token, value)
    remaining = [asset_id for asset_id in images if asset_id not in placed]
    if not changed and not remaining:
        return source
    value = re.sub(r'\n{3,}', '\n\n', value).strip()
    if remaining:
        value = '\n\n'.join([value, *(image_block(asset_id).strip() for asset_id in remaining)]).strip()
    return value


def place_deck_images(deck, images):
    """Keep only slide images that reference a received asset, and add a slide for any not placed.

    Every image shape gets the server's alt text. An image the deck did not place gets its
    own slide, so a requested image is never left out of the file.
    """
    if type(deck) is not dict or type(deck.get('slides')) is not list:
        return deck
    placed = set()
    for slide in deck['slides']:
        if type(slide) is not dict or type(slide.get('shapes')) is not list:
            continue
        kept = []
        for shape in slide['shapes']:
            if type(shape) is dict and shape.get('type') == 'image':
                source = str(shape.get('source') or '')
                asset_id = source[len('asset:'):] if source.startswith('asset:') else ''
                if asset_id not in images:
                    continue
                placed.add(asset_id)
                shape = {**shape, 'alt': image_alt_text(images[asset_id])}
            kept.append(shape)
        slide['shapes'] = kept
    missing = [asset_id for asset_id in images if asset_id not in placed]
    if missing:
        counted = deck.get('slide_count') == len(deck['slides'])
        width = 10 if deck.get('size') == 'standard' else 40 / 3
        for asset_id in missing:
            title = str(images[asset_id] or '').strip()[:60] or AI_ILLUSTRATION_LABEL
            deck['slides'].append({
                'layout': 'title_and_content', 'title': title, 'notes': image_alt_text(images[asset_id]),
                'shapes': [{
                    'type': 'image', 'source': f'asset:{asset_id}', 'alt': image_alt_text(images[asset_id]),
                    'box': {'left': 0.75, 'top': 1.5, 'width': round(width - 1.5, 2), 'height': 5.5},
                }],
            })
        if counted:
            deck['slide_count'] = len(deck['slides'])
    return deck


# --------------------------------------------------------------------------------------
# The chat answer and delivery notes
# --------------------------------------------------------------------------------------

def _no_fence(value):
    return str(value or '').replace('`', "'")


def generated_image_block(asset):
    """A ``simpleimage`` block the chat renders as the already generated image."""
    payload = {
        'version': 1, 'visualId': asset['asset_id'], 'title': _no_fence(asset['title']),
        'description': AI_ILLUSTRATION_LABEL, 'prompt': _no_fence(asset['prompt']),
        'visualType': 'illustration', 'context': AI_ILLUSTRATION_LABEL,
    }
    return '```simpleimage\n' + json.dumps(payload, ensure_ascii=False) + '\n```'


def project_generated_images(text, assets):
    """Show this run's generated images in the chat answer where the content placed them.

    ``assets`` maps asset ids to retained image descriptors. Images the content did not
    place are added after it, so a generated image is never left out of the answer. Text
    without image references is returned unchanged when the run generated no images.
    """
    source = str(text or '')
    placed = set()
    changed = False

    def block(asset_id):
        placed.add(asset_id)
        return f'\n\n{generated_image_block(assets[asset_id])}\n\n'

    def from_reference(match):
        nonlocal changed
        changed = True
        asset_id = match.group(2)
        return block(asset_id) if asset_id in assets and asset_id not in placed else ''

    def from_token(match):
        nonlocal changed
        changed = True
        asset_id = match.group(1)
        return block(asset_id) if asset_id in assets and asset_id not in placed else ''

    value = ASSET_IMAGE_PATTERN.sub(from_reference, source)
    value = IMAGE_TOKEN_PATTERN.sub(from_token, value)
    remaining = [asset_id for asset_id in assets if asset_id not in placed]
    if not changed and not remaining:
        return source
    value = re.sub(r'\n{3,}', '\n\n', value).strip()
    if remaining:
        blocks = []
        for asset_id in remaining:
            blocks.append(generated_image_block(assets[asset_id]))
            blocks.append(_caption(assets[asset_id]['title']))
        value = '\n\n'.join(part for part in (value, *blocks) if part).strip()
    return value


def explicit_image_shortfalls(plan, statuses):
    """Explicit planned image deliverables whose enabled image steps did not all complete."""
    shortfalls = []
    steps = [step for step in plan.get('steps') or () if step.get('enabled', True)]
    for deliverable in plan.get('deliverables') or ():
        if (
            deliverable.get('kind') != KIND_IMAGE or deliverable.get('requested') != REQUESTED_EXPLICIT
            or deliverable.get('status') != STATUS_PLANNED
        ):
            continue
        producers = [step for step in steps if deliverable['id'] in (step.get('delivers') or ())]
        completed = [step for step in producers if statuses.get(step['step_id']) == 'completed']
        if len(completed) < len(producers):
            shortfalls.append({
                'id': deliverable['id'], 'expected': len(producers), 'delivered': len(completed),
            })
    return shortfalls


def delivery_notes(plan, statuses, *, file_steps_with_outputs=()):
    """A deterministic note for explicit deliverables that were not delivered or are unavailable.

    ``statuses`` maps step ids to their final status. Files that reached the output service
    are already described by the files summary, so only files that never started are named.
    """
    lines = []
    steps = {step['step_id']: step for step in plan.get('steps') or ()}
    shortfalls = {item['id']: item for item in explicit_image_shortfalls(plan, statuses)}
    for deliverable in plan.get('deliverables') or ():
        if deliverable.get('implicit') or deliverable.get('requested') != REQUESTED_EXPLICIT:
            continue
        description = _safe_markdown_text(deliverable.get('description'))
        if deliverable.get('status') == STATUS_UNAVAILABLE:
            lines.append(
                f"- Not available: {description}. "
                f"{UNAVAILABLE_REASONS.get(deliverable.get('unavailable_reason'), '')}".rstrip()
            )
            continue
        producers = [step for step in steps.values() if deliverable['id'] in (step.get('delivers') or ())]
        if producers and not any(step.get('enabled', True) for step in producers):
            lines.append(f'- Not delivered: {description}. Its step was turned off.')
            continue
        if deliverable['id'] in shortfalls:
            item = shortfalls[deliverable['id']]
            lines.append(
                f"- Not delivered: {description}. {item['delivered']} of {item['expected']} images "
                'were generated.'
            )
            continue
        if deliverable.get('kind') == KIND_FILE:
            missing = [
                step for step in producers
                if step.get('enabled', True) and step['step_id'] not in set(file_steps_with_outputs)
                and statuses.get(step['step_id']) != 'completed'
            ]
            if missing:
                lines.append(f'- Not delivered: {description}. The file was not created.')
    return 'Delivery notes:\n' + '\n'.join(lines) if lines else ''


def generated_image_assets(task_results, read_value):
    """Retained generated images by asset id, in plan-independent producer order.

    ``task_results`` maps step ids to TaskResult objects; ``read_value(reference)`` reads a
    retained descriptor through the owning authorization service.
    """
    assets = {}
    for step_id, task in (task_results or {}).items():
        if task.producer.capability_id != CAPABILITY_GENERATE_IMAGE or task.status != 'complete':
            continue
        for reference in task.outputs:
            if reference.kind == IMAGE_ASSET_KIND and reference.completeness.status == 'complete':
                value = read_value(reference)
                if value.get('asset_id') == step_id:
                    assets[step_id] = deepcopy(value)
    return assets
