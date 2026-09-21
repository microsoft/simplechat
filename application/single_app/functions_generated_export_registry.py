# functions_generated_export_registry.py
"""Static, source-aware capabilities for the explicit serialization branch."""

from copy import deepcopy
from dataclasses import asdict, dataclass
from typing import Tuple

from jsonschema import Draft202012Validator, ValidationError

from functions_generated_export_contracts import (
    GeneratedFileExportError,
    GeneratedFileExportLimits,
    GeneratedFileExportRequest,
)


@dataclass(frozen=True)
class GeneratedFileExportProfile:
    profile: str
    source_kinds: Tuple[str, ...]
    required_options: Tuple[str, ...] = ()
    optional_options: Tuple[str, ...] = ()


@dataclass(frozen=True)
class GeneratedFileExportFormat:
    format_id: str
    aliases: Tuple[str, ...]
    file_extension: str
    media_type: str
    profiles: Tuple[GeneratedFileExportProfile, ...]
    renderer_id: str
    dependencies: Tuple[str, ...] = ()
    renderer_version: int = 1
    streaming: bool = True
    rich_media: bool = False


PREPARED_SLIDE_DECK_VERSION = 'prepared_slide_deck_v1'
GENERATED_IMAGE_REFERENCE_PATTERN = r'^asset:[A-Za-z0-9][A-Za-z0-9._-]{0,127}$'
_OPTION_SCHEMAS = {
    'columns': {
        'type': 'array', 'minItems': 1, 'uniqueItems': True,
        'items': {'type': 'string', 'minLength': 1},
        'description': 'Ordered public field names; every record must have exactly these keys.',
    },
    'title': {'type': 'string', 'maxLength': 255},
    'sheet_name': {
        'type': 'string', 'minLength': 1, 'maxLength': 31,
        'pattern': r'^[^\[\]:*?/\\]+$',
        'not': {'anyOf': [{'pattern': "^'"}, {'pattern': "'$"}]},
        'description': 'One explicit sheet name; at most 31 UTF-16 code units, not only whitespace.',
    },
}
_PREPARED_SLIDE_DECK_SCHEMA = {
    '$schema': 'https://json-schema.org/draft/2020-12/schema',
    'title': 'SimpleChat prepared slide deck v1',
    'type': 'object',
    'additionalProperties': False,
    'required': ['schema_version', 'slide_count', 'slides'],
    'properties': {
        'schema_version': {'const': PREPARED_SLIDE_DECK_VERSION},
        'slide_count': {'type': 'integer', 'minimum': 1},
        'title': {'type': 'string', 'maxLength': 255, 'default': ''},
        'size': {'enum': ['wide', 'standard'], 'default': 'wide'},
        'slides': {'type': 'array', 'minItems': 1, 'items': {'$ref': '#/$defs/slide'}},
    },
    '$defs': {
        'box': {
            'type': 'object', 'additionalProperties': False,
            'required': ['left', 'top', 'width', 'height'],
            'description': 'Position and dimensions in inches. Boxes must fit the slide and not overlap.',
            'properties': {
                'left': {'type': 'number', 'minimum': 0},
                'top': {'type': 'number', 'minimum': 0},
                'width': {'type': 'number', 'exclusiveMinimum': 0},
                'height': {'type': 'number', 'exclusiveMinimum': 0},
            },
        },
        'paragraph': {
            'type': 'object', 'additionalProperties': False, 'required': ['text'],
            'properties': {
                'text': {'type': 'string'},
                'list_kind': {'enum': ['none', 'bullet', 'number'], 'default': 'none'},
                'level': {'type': 'integer', 'minimum': 0, 'maximum': 8, 'default': 0},
                'bold': {'type': 'boolean', 'default': False},
                'italic': {'type': 'boolean', 'default': False},
                'url': {
                    'anyOf': [{'type': 'null'}, {'type': 'string', 'pattern': r'^(https?://|mailto:)'}],
                    'default': None,
                },
            },
            'anyOf': [
                {'properties': {'level': {'const': 0}}},
                {'required': ['list_kind'], 'properties': {'list_kind': {'enum': ['bullet', 'number']}}},
            ],
        },
        'text_box': {
            'type': 'object', 'additionalProperties': False,
            'required': ['type', 'box', 'paragraphs'],
            'properties': {
                'type': {'const': 'text_box'},
                'box': {'$ref': '#/$defs/box'},
                'paragraphs': {
                    'type': 'array', 'minItems': 1, 'items': {'$ref': '#/$defs/paragraph'},
                },
                'font_size': {'type': 'number', 'minimum': 8, 'maximum': 40, 'default': 18},
            },
        },
        'table': {
            'type': 'object', 'additionalProperties': False, 'required': ['type', 'box', 'rows'],
            'properties': {
                'type': {'const': 'table'},
                'box': {'$ref': '#/$defs/box'},
                'rows': {
                    'type': 'array', 'minItems': 1,
                    'items': {'type': 'array', 'minItems': 1, 'items': {'type': 'string'}},
                    'description': 'A rectangular table of prepared literal strings; no scalar coercion.',
                },
                'header': {'type': 'boolean', 'default': True},
                'font_size': {'type': 'number', 'minimum': 8, 'maximum': 32, 'default': 12},
            },
        },
        'image': {
            'type': 'object', 'additionalProperties': False, 'required': ['type', 'box', 'source'],
            'properties': {
                'type': {'const': 'image'},
                'box': {'$ref': '#/$defs/box'},
                'source': {'type': 'string', 'pattern': GENERATED_IMAGE_REFERENCE_PATTERN},
                'alt': {'type': 'string', 'default': ''},
            },
        },
        'slide': {
            'type': 'object', 'additionalProperties': False,
            'required': ['layout', 'title', 'shapes'],
            'properties': {
                'layout': {'enum': ['title_and_content', 'blank']},
                'title': {'type': 'string'},
                'notes': {'type': 'string', 'default': ''},
                'shapes': {
                    'type': 'array',
                    'items': {
                        'oneOf': [
                            {'$ref': '#/$defs/text_box'}, {'$ref': '#/$defs/table'}, {'$ref': '#/$defs/image'},
                        ],
                    },
                },
            },
            'if': {'properties': {'layout': {'const': 'blank'}}},
            'then': {'properties': {'title': {'const': ''}}},
            'else': {'properties': {'title': {'minLength': 1}}},
        },
    },
}


_STRUCTURED_PROFILES = (
    GeneratedFileExportProfile('structured_records_v1', ('records',)),
    GeneratedFileExportProfile('structured_value_v1', ('structured_value',)),
)
GENERATED_FILE_EXPORT_REGISTRY = (
    GeneratedFileExportFormat(
        'csv', ('csv',), 'csv', 'text/csv; charset=utf-8',
        (GeneratedFileExportProfile('tabular_records_v1', ('records',), ('columns',)),),
        'csv',
    ),
    GeneratedFileExportFormat(
        'json', ('json',), 'json', 'application/json',
        (GeneratedFileExportProfile('exact_records_v1', ('records',)),) + _STRUCTURED_PROFILES,
        'json',
    ),
    GeneratedFileExportFormat(
        'xml', ('xml',), 'xml', 'application/xml',
        (GeneratedFileExportProfile('typed_xml_v1', ('records', 'structured_value')),),
        'xml',
    ),
    GeneratedFileExportFormat(
        'yaml', ('yaml', 'yml'), 'yaml', 'application/yaml',
        _STRUCTURED_PROFILES, 'yaml', ('PyYAML',),
    ),
    GeneratedFileExportFormat(
        'md', ('md', 'markdown'), 'md', 'text/markdown; charset=utf-8',
        (GeneratedFileExportProfile('prepared_text_v1', ('markdown',)),),
        'text',
    ),
    GeneratedFileExportFormat(
        'txt', ('txt', 'text'), 'txt', 'text/plain; charset=utf-8',
        (GeneratedFileExportProfile('prepared_text_v1', ('text',)),),
        'text',
    ),
    GeneratedFileExportFormat(
        'xlsx', ('xlsx',), 'xlsx', 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        (GeneratedFileExportProfile('tabular_workbook_v1', ('records',), ('columns', 'sheet_name')),),
        'office', ('openpyxl',),
    ),
    GeneratedFileExportFormat(
        'docx', ('docx',), 'docx', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        (GeneratedFileExportProfile('prepared_report_v1', ('text', 'markdown'), optional_options=('title',)),),
        'office', ('python-docx', 'markdown2', 'beautifulsoup4', 'Pillow'),
        streaming=False, rich_media=True,
    ),
    GeneratedFileExportFormat(
        'pdf', ('pdf',), 'pdf', 'application/pdf',
        (GeneratedFileExportProfile('prepared_report_v1', ('text', 'markdown'), optional_options=('title',)),),
        'office', ('PyMuPDF', 'markdown2', 'beautifulsoup4', 'Pillow'),
        streaming=False, rich_media=True,
    ),
    GeneratedFileExportFormat(
        'pptx', ('pptx',), 'pptx', 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
        (GeneratedFileExportProfile(PREPARED_SLIDE_DECK_VERSION, ('structured_value',)),),
        'office', ('python-pptx', 'PyMuPDF', 'Pillow'),
        streaming=False, rich_media=True,
    ),
)
_OFFICE_FAILURE_CODES = (
    'invalid_input', 'unsupported_content', 'limit_exceeded', 'layout_overflow',
    'cancelled', 'access_denied', 'source_changed', 'source_unavailable',
    'check_failed', 'render_io', 'render_failed',
)


def get_prepared_slide_deck_schema():
    """Return the same strict, self-contained JSON schema used by composition and Render."""
    return deepcopy(_PREPARED_SLIDE_DECK_SCHEMA)


def _options_schema(profile):
    supported = profile.required_options + profile.optional_options
    return {
        'type': 'object',
        'properties': {name: deepcopy(_OPTION_SCHEMAS[name]) for name in supported},
        'required': list(profile.required_options),
        'additionalProperties': False,
    }


def _input_schema(profile):
    if profile.profile == PREPARED_SLIDE_DECK_VERSION:
        return get_prepared_slide_deck_schema()
    if profile.profile in ('prepared_text_v1', 'prepared_report_v1'):
        return {'type': 'string'}
    if profile.source_kinds == ('records',):
        record = {'type': 'object'}
        if profile.profile in ('tabular_records_v1', 'tabular_workbook_v1'):
            record['additionalProperties'] = {'type': ['string', 'number', 'boolean', 'null']}
        return {'type': 'array', 'items': record}
    return {}


def _office_limits_catalog():
    # Binary dependencies are only loaded when Office capabilities are inspected or rendered.
    from functions_office_file_renderers import OfficeRenderLimits

    return asdict(OfficeRenderLimits())
GENERATED_FILE_EXPORT_FAILURE_CODES = (
    'unsupported_format', 'unsupported_profile', 'unsupported_source',
    'invalid_options', 'invalid_limit', 'invalid_source', 'incomplete_source',
    'invalid_data', 'count_mismatch', 'size_limit', 'record_limit', 'value_limit',
)


def get_generated_file_export_catalog():
    """Return fresh JSON-safe declarations, not an orchestration admission list."""
    return [
        {
            'format_id': entry.format_id,
            'aliases': list(entry.aliases),
            'file_extension': entry.file_extension,
            'media_type': entry.media_type,
            'renderer_version': entry.renderer_version,
            'profiles': [
                {
                    'profile': profile.profile,
                    'source_kinds': list(profile.source_kinds),
                    'required_options': list(profile.required_options),
                    'supported_options': list(profile.required_options + profile.optional_options),
                    'requires_complete': True,
                    'options_schema': _options_schema(profile),
                    'input_schema': _input_schema(profile),
                }
                for profile in entry.profiles
            ],
            'streaming': entry.streaming,
            'rich_media': entry.rich_media,
            'dependencies': ['jsonschema', *entry.dependencies],
            'default_limits': asdict(GeneratedFileExportLimits()),
            **({'office_default_limits': _office_limits_catalog()} if entry.renderer_id == 'office' else {}),
            'max_output_bytes_required': True,
            'failure_codes': list(GENERATED_FILE_EXPORT_FAILURE_CODES) + (
                list(_OFFICE_FAILURE_CODES) if entry.renderer_id == 'office' else []
            ),
            'validation_failures_retryable': False,
            'retryable_failure_codes': ['source_unavailable', 'render_io'] if entry.renderer_id == 'office' else [],
        }
        for entry in GENERATED_FILE_EXPORT_REGISTRY
    ]


def resolve_generated_file_export_format(request, source_kind):
    """Resolve only declared spellings and profiles; never infer or fall back."""
    if not isinstance(request, GeneratedFileExportRequest):
        raise GeneratedFileExportError('invalid_options', 'An explicit export request is required.')
    if type(request.output_format) is not str:
        raise GeneratedFileExportError('unsupported_format', 'This export format is not supported.')
    entry = next(
        (entry for entry in GENERATED_FILE_EXPORT_REGISTRY if request.output_format in entry.aliases),
        None,
    )
    if entry is None:
        raise GeneratedFileExportError('unsupported_format', 'This export format is not supported.')
    profile = next(
        (profile for profile in entry.profiles if request.profile == profile.profile),
        None,
    ) if type(request.profile) is str else None
    if profile is None:
        raise GeneratedFileExportError('unsupported_profile', 'This export profile is not supported.')
    if type(source_kind) is not str or source_kind not in profile.source_kinds:
        raise GeneratedFileExportError('unsupported_source', 'This export source is not supported.')
    options = {
        name: list(value) if name == 'columns' and type(value) is tuple else value
        for name in _OPTION_SCHEMAS
        if (value := getattr(request, name)) is not None
    }
    try:
        Draft202012Validator(_options_schema(profile)).validate(options)
    except ValidationError as exc:
        raise GeneratedFileExportError(
            'invalid_options', 'The export options do not match the selected profile.',
        ) from exc
    return entry
