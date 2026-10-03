# functions_workflow_drafts.py
"""Workflow draft service: validate, build and create workflows proposed from chat.

Chat orchestration proposes a workflow as a *blueprint*: a small, closed JSON document with a
name, a trigger, one to five tasks, alert preferences and a Run as choice. This module

* validates a blueprint against a closed JSON Schema (Draft 2020-12) that names no destinations,
  endpoints, URLs, deployments, models, secrets or raw document ids. Documents, agents and File
  Sync sources are request-local *handles*: the caller maps each handle to a record the server
  already authorized, and a handle the caller did not map is an error;
* maps a valid blueprint to a version 2 task-based workflow payload, deterministically: the same
  blueprint, handles and proposal always produce the same definition;
* dry-runs that payload through the same build step a save uses, returning the normalized
  workflow document or stable, repairable errors. A dry run writes nothing: no workflow record,
  no conversation, no notification and no blob, Key Vault or Microsoft 365 call. It needs no
  Flask request or application context, so it can run on an executor thread; identity, roles
  and settings are passed in;
* creates the accepted workflow at most once per proposal, under an id derived from the user and
  the proposal, with server-only ``origin`` provenance and the per-user cap on workflows created
  from chat.

Every error is ``{'code', 'message', 'path'}``: a stable machine code, a bounded message built
only from fixed text and schema limits, never from caller input, and an RFC 6901 JSON pointer
into the blueprint or payload. Two failures raise instead, because no repair can fix them: a
malformed handle map or origin (``ValueError``, a caller bug) and a misconfigured administrator
limit (``WorkflowLoopLimitError``, a server fault).
"""

import copy
import json
import logging
import re
import uuid

from jsonschema import Draft202012Validator

from content_screening.contracts import DocumentHeldError
from functions_appinsights import log_event
from functions_document_actions import (
    DOCUMENT_ACTION_TYPE_ANALYZE,
    DOCUMENT_ACTION_TYPE_MERGE,
    MERGE_KIND_OPTION_KEYS,
    MERGE_KIND_OUTPUT_FORMATS,
    MERGE_KIND_TABULAR,
    MERGE_KINDS_AVAILABLE,
    get_enabled_document_action_types,
    is_document_action_enabled,
    normalize_document_action_config,
)
from functions_file_sync import (
    FILE_SYNC_SCOPE_GROUP,
    FILE_SYNC_SCOPE_PERSONAL,
    FILE_SYNC_SCOPE_PUBLIC,
    get_authorized_sync_source,
    is_file_sync_enabled_for_group,
    is_file_sync_enabled_for_public_workspace,
    is_file_sync_enabled_for_user,
)
from functions_group_workflows import build_group_workflow_document
from functions_personal_workflows import (
    WORKFLOW_FILE_SYNC_MAX_SOURCES,
    build_personal_workflow_document,
    count_personal_orchestration_workflows,
    create_personal_workflow_if_absent,
    get_personal_workflow,
    get_workflow_max_tasks,
    normalize_personal_workflow_task_runner,
)
from functions_settings import is_user_workflows_enabled_for_user, read_user_settings_snapshot
from functions_workflow_bindings import authorize_workflow_reference
from functions_workflow_definitions import (
    WorkflowCadenceError,
    WorkflowDefinitionConflict,
    WorkflowDefinitionError,
    WorkflowPublicValidationError,
    WorkflowSourceUnavailableError,
    existing_server_created_workflow,
    normalize_workflow_origin,
    workflow_definition_for_editor,
)
from functions_workflow_limits import (
    WorkflowLoopLimitError,
    get_chat_orchestration_max_workflows_per_user,
    get_orchestration_workflow_min_interval_seconds,
)
from functions_workflow_schedules import (
    SCHEDULE_TIMEZONE_ERROR,
    WORKFLOW_SCHEDULE_DAYS,
    WORKFLOW_SCHEDULE_FREQUENCIES,
    enforce_orchestration_workflow_cadence,
    normalize_workflow_schedule,
)


WORKFLOW_BLUEPRINT_SCHEMA_ID = 'urn:simplechat:workflow-blueprint:1'
# Namespace for every id this module derives, so a proposal always maps to the same workflow.
WORKFLOW_DRAFT_NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, 'urn:simplechat:workflow-drafts')
WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION = 'orchestration'

BLUEPRINT_MAX_TASKS = 5
# Serialized as UTF-8, so a blueprint in any script still fits at its full field limits.
BLUEPRINT_MAX_BYTES = 131072
BLUEPRINT_MAX_DEPTH = 16
BLUEPRINT_NAME_MAX_LENGTH = 120
BLUEPRINT_DESCRIPTION_MAX_LENGTH = 1000
BLUEPRINT_TASK_TITLE_MAX_LENGTH = 120
BLUEPRINT_TASK_INSTRUCTIONS_MAX_LENGTH = 4000
BLUEPRINT_TASK_MAX_INPUTS = 10
BLUEPRINT_MAX_SOURCES = WORKFLOW_FILE_SYNC_MAX_SOURCES
BLUEPRINT_TIMEZONE_MAX_LENGTH = 64
BLUEPRINT_MAX_HANDLES = 100
BLUEPRINT_HANDLE_PATTERN = r'^[a-z][a-z0-9_-]{0,63}$'
BLUEPRINT_TIME_PATTERN = r'^([01][0-9]|2[0-3]):[0-5][0-9]$'
BLUEPRINT_TEXT_PATTERN = r'\S'
BLUEPRINT_TRIGGER_TYPES = ('manual', 'calendar', 'interval', 'file_sync')
BLUEPRINT_INTERVAL_UNITS = ('minutes', 'hours')
BLUEPRINT_RUNNER_TYPES = ('agent', 'model')
BLUEPRINT_ALERT_MODES = ('every_run', 'failures_only')
BLUEPRINT_ALERT_SEVERITIES = ('info', 'low')
BLUEPRINT_RUN_AS = ('self', 'none')
BLUEPRINT_SCOPE_TYPES = (FILE_SYNC_SCOPE_PERSONAL, FILE_SYNC_SCOPE_GROUP, FILE_SYNC_SCOPE_PUBLIC)
BLUEPRINT_HANDLE_KINDS = ('documents', 'agents', 'sources')
# Where a merge task's files come from: its inputs, a sync, or the user's personal workspace.
BLUEPRINT_MERGE_FILES = ('inputs', 'changed', 'all', 'recent')
BLUEPRINT_MERGE_FILE_NAME_MAX_LENGTH = 100

DRAFT_MAX_ERRORS = 10
DRAFT_MESSAGE_MAX_LENGTH = 240
DRAFT_HANDLE_ID_MAX_LENGTH = 128
DRAFT_DOCUMENT_ID_MAX_LENGTH = 256

DRAFT_DEFAULT_ERROR_MESSAGE = 'The workflow draft is not valid.'
DRAFT_ERROR_MESSAGES = {
    'blueprint_invalid': 'The workflow blueprint is not valid.',
    'unsupported_field': 'This field is not supported. Remove it.',
    'too_many_tasks': 'This workflow has more tasks than allowed.',
    'trigger_invalid': 'The workflow trigger is not valid.',
    'cadence_below_minimum': 'Workflows created from chat cannot run this often.',
    'quota_exceeded': 'You already have the most workflows created from chat allowed.',
    'agent_unavailable': 'This agent is not available to you. Choose another agent, or use the default model.',
    'reference_unknown': 'This handle does not name anything provided with this request.',
    'reference_unauthorized': 'This document is not available to you.',
    'file_sync_source_unavailable': 'This File Sync source is not available to you.',
    'workflow_conflict': 'A different workflow already uses this id.',
    'workflows_unavailable': 'Personal workflows are not available for this account.',
    'merge_unavailable': 'File merging is turned off by an administrator. Remove merge from this task.',
    'merge_inputs_required': 'A merge of input documents needs at least two input documents, in merge order.',
    'merge_trigger_required': 'Merging the files a sync changed needs a File Sync trigger.',
    'merge_runner_invalid': 'A merge task merges files with code, so it has no agent runner. Remove the runner.',
    'merge_options_invalid': (
        'These merge options cannot be used: each kind takes only its own options ('
        + '; '.join(
            f"{kind} takes {', '.join(MERGE_KIND_OPTION_KEYS[kind])}"
            for kind in MERGE_KINDS_AVAILABLE if kind != MERGE_KIND_TABULAR
        )
        + '), mapped needs columns, key_columns needs dedupe_columns, a sheet name cannot be combined '
        'with all sheets, and a column is named once.'
    ),
    'merge_format_invalid': 'Choose an output_format this merge kind creates: ' + '; '.join(
        f"{kind} creates {' or '.join(MERGE_KIND_OUTPUT_FORMATS[kind])}" for kind in MERGE_KINDS_AVAILABLE
    ) + '.',
}
DRAFT_UNAVAILABLE_REFERENCE_MESSAGE = 'A document or source in this blueprint is not available to you.'
DRAFT_HANDLE_MAP_ERROR = 'The workflow draft handle map is malformed.'
DRAFT_URL_ACCESS_MESSAGE = 'URL Access is not available for workflows created from chat. Turn it off.'
# The save route sets these from the user's roles; the runner trusts them, so no caller may supply them.
URL_ACCESS_AUTHORIZATION_FIELDS = ('url_access_authorized', 'url_access_authorized_by', 'url_access_authorized_at')

_HANDLE_RE = re.compile(BLUEPRINT_HANDLE_PATTERN)
_SAFE_PATH_KEY_RE = re.compile(r'[A-Za-z0-9_-]{1,64}')


# ---------------------------------------------------------------------------
# Errors
# ---------------------------------------------------------------------------

def json_pointer(parts):
    """Return the RFC 6901 pointer for a sequence of object keys and array indexes; root is ''."""
    return ''.join('/' + str(part).replace('~', '~0').replace('/', '~1') for part in parts)


def _bounded_message(message):
    text = ' '.join(str(message or '').split())
    if len(text) > DRAFT_MESSAGE_MAX_LENGTH:
        text = text[:DRAFT_MESSAGE_MAX_LENGTH - 3].rstrip() + '...'
    return text


def draft_error(code, path='', message=None):
    """Build one draft error: a stable code, a bounded message and a JSON pointer.

    ``path`` is a pointer string or a sequence of keys and indexes. Without a message, the code's
    default message is used. Callers pass only fixed text or reviewed public messages.
    """
    code = str(code or 'blueprint_invalid')
    text = _bounded_message(message) if message else ''
    return {
        'code': code,
        'message': text or DRAFT_ERROR_MESSAGES.get(code, DRAFT_DEFAULT_ERROR_MESSAGE),
        'path': path if isinstance(path, str) else json_pointer(path),
    }


def _pointer_sort_key(path):
    if not path:
        return ()
    key = []
    for part in path[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        # Array indexes sort numerically and before object keys, so /tasks/2 precedes /tasks/10.
        key.append((0, int(part), '') if part.isascii() and part.isdigit() else (1, 0, part))
    return tuple(key)


def _finalize_errors(errors):
    unique = {}
    for error in errors:
        unique.setdefault((error['path'], error['code'], error['message']), error)
    ordered = sorted(
        unique.values(),
        key=lambda error: (_pointer_sort_key(error['path']), error['code'], error['message']),
    )
    return ordered[:DRAFT_MAX_ERRORS]


def _failure(errors, **extra):
    return {'ok': False, 'workflow': None, **extra, 'errors': _finalize_errors(errors)}


def _success(workflow, **extra):
    return {'ok': True, 'workflow': workflow, **extra, 'errors': []}


# ---------------------------------------------------------------------------
# Handles and derived ids
# ---------------------------------------------------------------------------

def _handle_text(value, max_length, required=True):
    if value is None and not required:
        return ''
    if not isinstance(value, str):
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    text = value.strip()
    if (required and not text) or len(text) > max_length:
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    return text


def _handle_scope_id(entry, scope_type, user_id):
    if scope_type == FILE_SYNC_SCOPE_PERSONAL:
        # A personal handle always belongs to the requesting user, never to another account.
        if entry.get('scope_id') not in (None, '', str(user_id)):
            raise ValueError(DRAFT_HANDLE_MAP_ERROR)
        return str(user_id)
    return _handle_text(entry.get('scope_id'), DRAFT_HANDLE_ID_MAX_LENGTH)


def _normalize_document_handle(entry, user_id):
    if entry.keys() - {'document_id', 'scope_type', 'scope_id'}:
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    scope_type = entry.get('scope_type')
    if scope_type not in BLUEPRINT_SCOPE_TYPES:
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    return {
        'document_id': _handle_text(entry.get('document_id'), DRAFT_DOCUMENT_ID_MAX_LENGTH),
        'scope_type': scope_type,
        'scope_id': _handle_scope_id(entry, scope_type, user_id),
    }


def _normalize_agent_handle(entry, user_id):
    if entry.keys() - {'id', 'name', 'is_global'}:
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    agent = {'id': _handle_text(entry.get('id'), DRAFT_HANDLE_ID_MAX_LENGTH)}
    name = _handle_text(entry.get('name'), DRAFT_HANDLE_ID_MAX_LENGTH, required=False)
    if name:
        agent['name'] = name
    is_global = entry.get('is_global', False)
    if not isinstance(is_global, bool):
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    agent['is_global'] = is_global
    return agent


def _normalize_source_handle(entry, user_id):
    if entry.keys() - {'scope_type', 'scope_id', 'source_id'}:
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    scope_type = entry.get('scope_type')
    if scope_type not in BLUEPRINT_SCOPE_TYPES:
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    return {
        'scope_type': scope_type,
        'scope_id': _handle_scope_id(entry, scope_type, user_id),
        'source_id': _handle_text(entry.get('source_id'), DRAFT_HANDLE_ID_MAX_LENGTH),
    }


_HANDLE_NORMALIZERS = {
    'documents': _normalize_document_handle,
    'agents': _normalize_agent_handle,
    'sources': _normalize_source_handle,
}


def normalize_workflow_draft_handles(handles, *, user_id):
    """Validate the caller's handle map and return a normalized copy.

    ``handles`` maps request-local names to records the caller already chose for this user::

        {'documents': {'q3_report': {'document_id', 'scope_type', 'scope_id'}},
         'agents': {'mail_agent': {'id', 'name', 'is_global'}},
         'sources': {'contracts': {'scope_type', 'scope_id', 'source_id'}}}

    Personal entries always belong to ``user_id``. The map is built by server code, not by a
    model, so a malformed map raises ``ValueError`` instead of returning draft errors. Mapping a
    handle does not authorize it: the dry run checks every mapped record for this user.
    """
    if handles is None:
        handles = {}
    if not isinstance(handles, dict) or handles.keys() - set(BLUEPRINT_HANDLE_KINDS):
        raise ValueError(DRAFT_HANDLE_MAP_ERROR)
    normalized = {}
    for kind in BLUEPRINT_HANDLE_KINDS:
        entries = handles.get(kind)
        entries = {} if entries is None else entries
        if not isinstance(entries, dict) or len(entries) > BLUEPRINT_MAX_HANDLES:
            raise ValueError(DRAFT_HANDLE_MAP_ERROR)
        normalized[kind] = {}
        for handle, entry in entries.items():
            if not isinstance(handle, str) or not _HANDLE_RE.fullmatch(handle) or not isinstance(entry, dict):
                raise ValueError(DRAFT_HANDLE_MAP_ERROR)
            normalized[kind][handle] = _HANDLE_NORMALIZERS[kind](entry, user_id)
    return normalized


def _required_id(value, label):
    text = str(value or '').strip()
    if not text:
        raise ValueError(f'A {label} is required.')
    return text


def orchestration_workflow_id(user_id, proposal_id):
    """Return the workflow id chat orchestration uses for a proposal.

    The id depends only on the user and the proposal, so accepting the same proposal twice finds
    the first workflow instead of creating a second.
    """
    user_id = _required_id(user_id, 'user id')
    proposal_id = _required_id(proposal_id, 'proposal id')
    return str(uuid.uuid5(WORKFLOW_DRAFT_NAMESPACE, f'orchestration-workflow:{user_id}:{proposal_id}'))


def _derived_id(workflow_id, *parts):
    return str(uuid.uuid5(WORKFLOW_DRAFT_NAMESPACE, ':'.join([workflow_id, *(str(part) for part in parts)])))


# ---------------------------------------------------------------------------
# Blueprint schema
# ---------------------------------------------------------------------------

_CALENDAR_FIELDS = ('frequency', 'days_of_week', 'day_of_month', 'time_of_day', 'timezone')
_INTERVAL_FIELDS = ('unit', 'value')


def _forbid(*fields):
    # ``not: {required: [field]}`` rather than a ``false`` subschema, because jsonschema reports a
    # false subschema at its parent's path, which would hide the field to remove.
    return [{'not': {'required': [field]}} for field in fields]


def _when(field, values, then):
    values = [values] if isinstance(values, str) else list(values)
    condition = {'const': values[0]} if len(values) == 1 else {'enum': values}
    return {'if': {'required': [field], 'properties': {field: condition}}, 'then': then}


def _text_schema(max_length, required_text=True):
    schema = {'type': 'string', 'maxLength': max_length}
    if required_text:
        schema.update({'minLength': 1, 'pattern': BLUEPRINT_TEXT_PATTERN})
    return schema


def _calendar_properties():
    return {
        'frequency': {'enum': list(WORKFLOW_SCHEDULE_FREQUENCIES)},
        'days_of_week': {
            'type': 'array', 'minItems': 1, 'maxItems': len(WORKFLOW_SCHEDULE_DAYS), 'uniqueItems': True,
            'items': {'enum': list(WORKFLOW_SCHEDULE_DAYS)},
        },
        'day_of_month': {'type': 'integer', 'minimum': 1, 'maximum': 31},
        'time_of_day': {'type': 'string', 'pattern': BLUEPRINT_TIME_PATTERN},
        'timezone': {'type': 'string', 'minLength': 1, 'maxLength': BLUEPRINT_TIMEZONE_MAX_LENGTH},
    }


def _interval_properties():
    return {
        'unit': {'enum': list(BLUEPRINT_INTERVAL_UNITS)},
        'value': {'type': 'integer', 'minimum': 1, 'maximum': 59},
    }


def _calendar_rules():
    other_than = lambda frequency: [value for value in WORKFLOW_SCHEDULE_FREQUENCIES if value != frequency]
    return {
        'required': ['frequency', 'time_of_day', 'timezone'],
        'allOf': [
            _when('frequency', 'weekly', {'required': ['days_of_week']}),
            _when('frequency', other_than('weekly'), {'allOf': _forbid('days_of_week')}),
            _when('frequency', 'monthly', {'required': ['day_of_month']}),
            _when('frequency', other_than('monthly'), {'allOf': _forbid('day_of_month')}),
        ],
    }


def _interval_rules():
    return {
        'required': list(_INTERVAL_FIELDS),
        'allOf': [_when('unit', 'hours', {'properties': {'value': {'maximum': 24}}})],
    }


def _only(all_fields, *allowed):
    return _forbid(*[field for field in all_fields if field not in allowed])


def _file_sync_schedule_schema():
    properties = {'kind': {'enum': ['calendar', 'interval']}, **_calendar_properties(), **_interval_properties()}
    fields = tuple(field for field in properties if field != 'kind')
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['kind'],
        'properties': properties,
        'allOf': [
            _when('kind', 'calendar', {'allOf': _only(fields, *_CALENDAR_FIELDS) + [_calendar_rules()]}),
            _when('kind', 'interval', {'allOf': _only(fields, *_INTERVAL_FIELDS) + [_interval_rules()]}),
        ],
    }


def _trigger_schema():
    properties = {
        'type': {'enum': list(BLUEPRINT_TRIGGER_TYPES)},
        **_calendar_properties(),
        **_interval_properties(),
        'source_ids': {
            'type': 'array', 'minItems': 1, 'maxItems': BLUEPRINT_MAX_SOURCES, 'uniqueItems': True,
            'items': {'$ref': '#/$defs/handle'},
        },
        'schedule': {'$ref': '#/$defs/file_sync_schedule'},
    }
    fields = tuple(field for field in properties if field != 'type')
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['type'],
        'properties': properties,
        'allOf': [
            _when('type', 'manual', {'allOf': _only(fields)}),
            _when('type', 'calendar', {'allOf': _only(fields, *_CALENDAR_FIELDS) + [_calendar_rules()]}),
            _when('type', 'interval', {'allOf': _only(fields, *_INTERVAL_FIELDS) + [_interval_rules()]}),
            _when('type', 'file_sync', {
                'required': ['source_ids', 'schedule'],
                'allOf': _only(fields, 'source_ids', 'schedule'),
            }),
        ],
    }


def _merge_schema():
    return {
        'type': 'object',
        'additionalProperties': False,
        'required': ['files'],
        'description': (
            'Makes this task merge files with code instead of running a model. kind tabular appends the '
            'rows of CSV and Excel files into one CSV or Excel file; workbook puts each CSV or Excel file '
            'on its own sheet of one Excel workbook; pdf joins PDFs, in order, into one PDF; docx appends '
            'Word documents, in order, into one Word document. files: inputs '
            "merges the task's inputs (two or more document handles) in order; changed merges the files a "
            "File Sync trigger added or changed; all merges every matching file in the user's personal "
            'workspace; recent merges those added in the last recent_window_minutes. Rows are appended; '
            'rows are never matched on a key.'
        ),
        'properties': {
            'kind': {'enum': list(MERGE_KINDS_AVAILABLE)},
            'files': {'enum': list(BLUEPRINT_MERGE_FILES)},
            'output_format': {'enum': list(dict.fromkeys(
                output_format for kind in MERGE_KINDS_AVAILABLE for output_format in MERGE_KIND_OUTPUT_FORMATS[kind]
            ))},
            'file_name': _text_schema(BLUEPRINT_MERGE_FILE_NAME_MAX_LENGTH),
            'recent_window_minutes': {'type': 'integer', 'minimum': 1, 'maximum': 1440},
            'options': {'$ref': '#/$defs/merge_options'},
        },
    }


def _merge_options_schema():
    name = {'type': 'string', 'minLength': 1, 'maxLength': 256}
    names = {'type': 'array', 'items': name, 'minItems': 1, 'uniqueItems': True}
    return {
        'type': 'object',
        'additionalProperties': False,
        'description': (
            'The same column, sheet, duplicate and sort settings a chat merge accepts, for kind tabular. '
            'kind workbook takes only sheets and sheet; kind pdf takes only bookmarks; kind docx takes only '
            'formatting, page_breaks and source_headings.'
        ),
        'properties': {
            'bookmarks': {'type': 'boolean'},
            'formatting': {'enum': ['keep_source', 'use_first']},
            'page_breaks': {'type': 'boolean'},
            'source_headings': {'type': 'boolean'},
            'schema_policy': {'enum': ['by_name', 'exact_order', 'union', 'mapped']},
            'columns': {**names, 'maxItems': 255},
            # A list of closed objects rather than a map, so every object in the blueprint stays closed.
            'column_aliases': {
                'type': 'array', 'minItems': 1, 'maxItems': 256,
                'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['column', 'aliases'],
                    'properties': {'column': name, 'aliases': {**names, 'maxItems': 32}},
                },
            },
            'sheet': {'type': 'string', 'minLength': 1, 'maxLength': 31},
            'sheets': {'enum': ['first', 'all']},
            'header_row': {'type': 'integer', 'minimum': 1, 'maximum': 1000},
            'include_source_column': {'type': 'boolean'},
            'source_column_name': {'type': 'string', 'minLength': 1, 'maxLength': 128},
            'on_incompatible': {'enum': ['fail', 'exclude']},
            'dedupe': {'enum': ['none', 'exact_rows', 'key_columns']},
            'dedupe_columns': {**names, 'maxItems': 16},
            'dedupe_keep': {'enum': ['first', 'last']},
            'sort_by': {
                'type': 'array', 'maxItems': 3,
                'items': {
                    'type': 'object', 'additionalProperties': False, 'required': ['column'],
                    'properties': {
                        'column': name,
                        'descending': {'type': 'boolean'},
                        'value_type': {'enum': ['text', 'number', 'date']},
                    },
                },
            },
        },
    }


def _build_blueprint_schema():
    return {
        '$schema': 'https://json-schema.org/draft/2020-12/schema',
        '$id': WORKFLOW_BLUEPRINT_SCHEMA_ID,
        'title': 'Workflow blueprint',
        'description': (
            'A workflow proposed from chat. Documents, agents and File Sync sources are handles '
            'supplied with the request; the blueprint never names ids, models, endpoints or URLs.'
        ),
        'type': 'object',
        'additionalProperties': False,
        'required': ['name', 'trigger', 'tasks'],
        'properties': {
            'name': _text_schema(BLUEPRINT_NAME_MAX_LENGTH),
            'description': _text_schema(BLUEPRINT_DESCRIPTION_MAX_LENGTH, required_text=False),
            'trigger': _trigger_schema(),
            'tasks': {
                'type': 'array', 'minItems': 1, 'maxItems': BLUEPRINT_MAX_TASKS,
                'items': {
                    'type': 'object',
                    'additionalProperties': False,
                    'required': ['title', 'instructions'],
                    'properties': {
                        'title': _text_schema(BLUEPRINT_TASK_TITLE_MAX_LENGTH),
                        'instructions': _text_schema(BLUEPRINT_TASK_INSTRUCTIONS_MAX_LENGTH),
                        'runner': {'$ref': '#/$defs/runner'},
                        'inputs': {
                            'type': 'array', 'maxItems': BLUEPRINT_TASK_MAX_INPUTS, 'uniqueItems': True,
                            'items': {'$ref': '#/$defs/handle'},
                        },
                        'merge': {'$ref': '#/$defs/merge'},
                    },
                },
            },
            'alerts': {
                'type': 'object',
                'additionalProperties': False,
                'properties': {
                    'mode': {'enum': list(BLUEPRINT_ALERT_MODES)},
                    'severity': {'enum': list(BLUEPRINT_ALERT_SEVERITIES)},
                },
            },
            'run_as': {'enum': list(BLUEPRINT_RUN_AS)},
            'durable': {'const': True},
        },
        '$defs': {
            # The pattern alone bounds a handle's length.
            'handle': {'type': 'string', 'pattern': BLUEPRINT_HANDLE_PATTERN},
            'runner': {
                'type': 'object',
                'additionalProperties': False,
                'required': ['type'],
                'properties': {
                    'type': {'enum': list(BLUEPRINT_RUNNER_TYPES)},
                    'agent_ref': {'$ref': '#/$defs/handle'},
                },
                'allOf': [
                    _when('type', 'agent', {'required': ['agent_ref']}),
                    _when('type', 'model', {'allOf': _forbid('agent_ref')}),
                ],
            },
            'file_sync_schedule': _file_sync_schedule_schema(),
            'merge': _merge_schema(),
            'merge_options': _merge_options_schema(),
        },
    }


WORKFLOW_BLUEPRINT_SCHEMA = _build_blueprint_schema()
_BLUEPRINT_VALIDATOR = Draft202012Validator(WORKFLOW_BLUEPRINT_SCHEMA)


def workflow_blueprint_schema():
    """Return a copy of the closed blueprint schema, for a planner prompt or documentation."""
    return copy.deepcopy(WORKFLOW_BLUEPRINT_SCHEMA)


_TYPE_WORDS = {
    'object': 'an object', 'array': 'a list', 'string': 'text', 'integer': 'a whole number',
    'number': 'a number', 'boolean': 'true or false', 'null': 'null',
}


def _literal(value):
    return json.dumps(value, ensure_ascii=True)


def _schema_error_code(error, parts):
    if error.validator in ('additionalProperties', 'not') or error.validator is None:
        return 'unsupported_field'
    if error.validator == 'pattern' and error.validator_value == BLUEPRINT_HANDLE_PATTERN:
        return 'reference_unknown'
    if error.validator == 'maxItems' and parts == ['tasks']:
        return 'too_many_tasks'
    if parts and parts[0] == 'trigger':
        return 'trigger_invalid'
    return 'blueprint_invalid'


def _schema_error_details(error, parts):
    """Yield ``(extra path parts, message)`` for one schema error, from schema values only."""
    validator, value, instance = error.validator, error.validator_value, error.instance
    if validator == 'required':
        missing = [field for field in value if isinstance(instance, dict) and field not in instance]
        return [((field,), 'This field is required.') for field in missing] or [((), 'A required field is missing.')]
    if validator == 'additionalProperties':
        known = (error.schema or {}).get('properties') or {}
        extras = sorted(key for key in instance if key not in known) if isinstance(instance, dict) else []
        details = []
        for key in extras:
            if isinstance(key, str) and _SAFE_PATH_KEY_RE.fullmatch(key):
                details.append(((key,), 'This field is not supported. Remove it.'))
            else:
                # Never echo an unusual key; point at its object instead.
                details.append(((), 'This object has a field that is not supported. Remove it.'))
        return details or [((), 'This object has a field that is not supported. Remove it.')]
    if validator == 'not':
        fields = value.get('required') if isinstance(value, dict) else None
        if fields:
            return [((fields[0],), 'This field does not apply here. Remove it.')]
        return [((), 'This field does not apply here. Remove it.')]
    if validator is None:
        return [((), 'This field does not apply here. Remove it.')]
    if validator == 'type':
        types = value if isinstance(value, list) else [value]
        return [((), 'Must be ' + ' or '.join(_TYPE_WORDS.get(name, str(name)) for name in types) + '.')]
    if validator == 'enum':
        return [((), 'Must be one of: ' + ', '.join(_literal(item) for item in value) + '.')]
    if validator == 'const':
        return [((), f'Must be {_literal(value)}.')]
    if validator == 'minLength':
        return [((), 'Must not be empty.' if value == 1 else f'Must be at least {value} characters.')]
    if validator == 'maxLength':
        return [((), f'Must be {value} characters or fewer.')]
    if validator == 'pattern':
        if value == BLUEPRINT_TIME_PATTERN:
            return [((), 'Use 24-hour HH:MM time, such as 08:00.')]
        if value == BLUEPRINT_TEXT_PATTERN:
            return [((), 'Must contain text, not only spaces.')]
        if value == BLUEPRINT_HANDLE_PATTERN:
            return [((), 'This handle is not one provided with this request.')]
        return [((), 'This value has an invalid format.')]
    if validator == 'minItems':
        if parts == ['tasks']:
            return [((), 'Add at least one task.')]
        return [((), 'Must not be empty.' if value == 1 else f'Must have at least {value} items.')]
    if validator == 'maxItems':
        if parts == ['tasks']:
            return [((), f'A workflow created from chat can have up to {value} tasks.')]
        return [((), f'Must have {value} items or fewer.')]
    if validator == 'uniqueItems':
        return [((), 'Must not repeat an item.')]
    if validator == 'minimum':
        return [((), f'Must be at least {value}.')]
    if validator == 'maximum':
        return [((), f'Must be {value} or less.')]
    return [((), 'This value is not valid.')]


def _map_schema_error(error):
    parts = list(error.absolute_path)
    for extra, message in _schema_error_details(error, parts):
        path = parts + list(extra)
        yield draft_error(_schema_error_code(error, path if error.validator == 'required' else parts), path, message)


def _nested_too_deeply(value, limit=BLUEPRINT_MAX_DEPTH):
    stack = [(value, 1)]
    while stack:
        node, depth = stack.pop()
        if isinstance(node, (dict, list)):
            if depth > limit:
                return True
            stack.extend((child, depth + 1) for child in (node.values() if isinstance(node, dict) else node))
    return False


def _prepare_blueprint(blueprint):
    """Return ``(blueprint, errors)``: a JSON round-tripped copy of a valid blueprint, or its errors."""
    if not isinstance(blueprint, dict):
        return None, [draft_error('blueprint_invalid', '', 'The workflow blueprint must be a JSON object.')]
    try:
        encoded = json.dumps(blueprint, ensure_ascii=False, allow_nan=False)
        size = len(encoded.encode('utf-8'))
    except (TypeError, ValueError, RecursionError):
        # ValueError covers NaN, circular references and unpaired surrogates.
        return None, [draft_error('blueprint_invalid', '', 'The workflow blueprint must contain only JSON values.')]
    if size > BLUEPRINT_MAX_BYTES:
        return None, [draft_error(
            'blueprint_invalid', '', f'The workflow blueprint must be {BLUEPRINT_MAX_BYTES} bytes or smaller.',
        )]
    candidate = json.loads(encoded)
    if _nested_too_deeply(candidate):
        return None, [draft_error('blueprint_invalid', '', 'The workflow blueprint is nested too deeply.')]
    errors = [mapped for error in _BLUEPRINT_VALIDATOR.iter_errors(candidate) for mapped in _map_schema_error(error)]
    return (None, errors) if errors else (candidate, [])


def validate_workflow_blueprint(blueprint):
    """Check a blueprint against the closed schema alone. Returns a list of draft errors, empty when valid.

    This reads nothing: handles, agents, documents, sources, schedules and limits are checked by
    ``dry_run_workflow_blueprint``.
    """
    _prepared, errors = _prepare_blueprint(blueprint)
    return _finalize_errors(errors)


# ---------------------------------------------------------------------------
# Read-only seams
# ---------------------------------------------------------------------------

def _memoized_user_settings_reader(reader=None):
    """Read each user's settings once per draft, without repairing them, and hand out copies.

    ``get_user_settings`` writes a missing or incomplete settings document back to Cosmos, so a
    dry run reads a snapshot instead.
    """
    source = reader or read_user_settings_snapshot
    cache = {}

    def read(user_id):
        key = str(user_id)
        if key not in cache:
            cache[key] = source(user_id)
        return copy.deepcopy(cache[key])

    return read


def _document_resolver(reader, resolve_document=None):
    cache = {}
    visible_workspaces = {}

    def resolve_default(arguments):
        # Search initializes application clients, so import it only when a draft resolves a document.
        from functions_public_workspaces import visible_public_workspace_ids_from_user_settings
        from functions_search_service import resolve_document_context

        options = {}
        if arguments.get('doc_scope') == FILE_SYNC_SCOPE_PUBLIC:
            # The resolver's own visibility lookup can repair the settings document; use the snapshot.
            user_id = str(arguments.get('user_id') or '')
            if user_id not in visible_workspaces:
                visible_workspaces[user_id] = visible_public_workspace_ids_from_user_settings(reader(user_id))
            options['visible_public_workspace_ids'] = list(visible_workspaces[user_id])
        return resolve_document_context(**arguments, **options)

    def resolve(**arguments):
        key = json.dumps(arguments, sort_keys=True, default=str)
        if key not in cache:
            cache[key] = resolve_document(**arguments) if resolve_document is not None else resolve_default(arguments)
        return copy.deepcopy(cache[key])

    return resolve


def read_only_document_resolver(*, user_settings_reader=None, resolve_document=None):
    """Return a memoized document resolver that reads and never writes, for dry runs and creates.

    Pass ``resolve_document`` to wrap another resolver; the default resolves shared documents with
    the search service, taking public workspace visibility from a settings snapshot.
    """
    return _document_resolver(_memoized_user_settings_reader(user_settings_reader), resolve_document)


def _draft_seams(user_settings_reader=None, resolve_document=None):
    reader = _memoized_user_settings_reader(user_settings_reader)
    return reader, _document_resolver(reader, resolve_document)


def _project_source(source):
    # The workflow stores only a source's name and type. The full sanitizer would also resolve the
    # source's workspace identity, which can read Key Vault; its name and type are the same.
    source = source if isinstance(source, dict) else {}
    return {'name': source.get('name'), 'source_type': source.get('source_type')}


# ---------------------------------------------------------------------------
# Deterministic builder
# ---------------------------------------------------------------------------

def _calendar_schedule_payload(fields):
    schedule = {
        'kind': 'calendar',
        'frequency': fields['frequency'],
        'time_of_day': fields['time_of_day'],
        'timezone': fields['timezone'],
    }
    if fields['frequency'] == 'weekly':
        schedule['days_of_week'] = list(fields['days_of_week'])
    if fields['frequency'] == 'monthly':
        schedule['day_of_month'] = int(fields['day_of_month'])
    return schedule


def _interval_schedule_payload(fields):
    return {'unit': fields['unit'], 'value': int(fields['value'])}


def _blueprint_schedule(trigger):
    """Return ``(schedule payload, path parts)`` for a scheduled trigger, or ``(None, ())``."""
    if trigger['type'] == 'calendar':
        return _calendar_schedule_payload(trigger), ('trigger',)
    if trigger['type'] == 'interval':
        return _interval_schedule_payload(trigger), ('trigger',)
    if trigger['type'] == 'file_sync':
        schedule = trigger['schedule']
        if schedule['kind'] == 'calendar':
            return _calendar_schedule_payload(schedule), ('trigger', 'schedule')
        return _interval_schedule_payload(schedule), ('trigger', 'schedule')
    return None, ()


def _trigger_fields(trigger, handles):
    schedule, _path = _blueprint_schedule(trigger)
    if trigger['type'] == 'manual':
        return {'trigger_type': 'manual'}
    if trigger['type'] in ('calendar', 'interval'):
        # Calendar schedules are stored under the interval trigger, beside interval schedules.
        return {'trigger_type': 'interval', 'schedule': schedule}
    return {
        'trigger_type': 'file_sync',
        'schedule': schedule,
        'file_sync': {
            'enabled': True,
            'wait_mode': 'complete',
            'continue_mode': 'changed',
            'use_changed_documents': True,
            'sources': [dict(handles['sources'][handle]) for handle in trigger['source_ids']],
        },
    }


def _alert_rule(workflow_id, key, name, severity, statuses):
    return {
        'id': _derived_id(workflow_id, 'alert', key),
        'name': name,
        'enabled': True,
        'severity': severity,
        'delivery': 'notify_only',
        'scope': {'type': 'final', 'task_id': ''},
        'condition': {'type': 'run_status', 'statuses': list(statuses)},
    }


def _alert_fields(alerts, workflow_id):
    # The stored every_run mode always opens a pop-up, so a digest uses rules delivered to the bell.
    rules = []
    if alerts.get('mode', 'every_run') == 'every_run':
        rules.append(_alert_rule(workflow_id, 'completed', 'Run completed', alerts.get('severity', 'info'), ['completed']))
    rules.append(_alert_rule(workflow_id, 'errors', 'Run had errors', 'low', ['failed', 'completed_with_task_errors']))
    return {
        'alert_mode': 'rules',
        'alert_priority': 'none',
        'alert_rules': rules,
        'alert_evaluation': {'on_error': 'skip'},
    }


def _merge_options(options, *, aliases_as_pairs=False):
    """A blueprint's merge options in the stored form: column aliases become a column-to-names map.

    Validation reads the aliases as ordered pairs, so a column named twice is reported rather
    than silently overwritten.
    """
    options = copy.deepcopy(options or {})
    if 'column_aliases' in options:
        pairs = [(entry['column'], list(entry['aliases'])) for entry in options['column_aliases']]
        options['column_aliases'] = pairs if aliases_as_pairs else dict(pairs)
    return options


def _merge_kind(merge):
    return merge.get('kind') or MERGE_KIND_TABULAR


def _merge_document_action(merge, task, handles):
    """The workflow Merge action a blueprint task describes; its files are never reference documents."""
    kind = _merge_kind(merge)
    action = {
        'type': DOCUMENT_ACTION_TYPE_MERGE,
        'merge_kind': kind,
        'output_format': merge.get('output_format') or MERGE_KIND_OUTPUT_FORMATS[kind][0],
        'document_ids': [],
        'active_group_ids': [],
        'active_public_workspace_id': [],
    }
    if merge.get('file_name'):
        action['output_file_name'] = merge['file_name']
    if merge.get('options'):
        action['merge_options'] = _merge_options(merge['options'])
    files = merge['files']
    if files == 'inputs':
        documents = [handles['documents'][handle] for handle in task.get('inputs') or []]
        scopes = {document['scope_type'] for document in documents}
        action.update({
            'target_mode': 'selected',
            'document_ids': [document['document_id'] for document in documents],
            'doc_scope': next(iter(scopes)) if len(scopes) == 1 else 'all',
            'active_group_ids': list(dict.fromkeys(
                document['scope_id'] for document in documents if document['scope_type'] == FILE_SYNC_SCOPE_GROUP
            )),
            'active_public_workspace_id': list(dict.fromkeys(
                document['scope_id'] for document in documents if document['scope_type'] == FILE_SYNC_SCOPE_PUBLIC
            )),
        })
    elif files == 'changed':
        action.update({'target_mode': 'changed', 'doc_scope': 'all'})
    else:
        # A chat-created workflow is personal, so run-time discovery stays in the personal workspace.
        action.update({'target_mode': files, 'doc_scope': FILE_SYNC_SCOPE_PERSONAL})
        if files == 'recent' and merge.get('recent_window_minutes'):
            action['recent_window_minutes'] = merge['recent_window_minutes']
    return action


def _merge_errors(blueprint, settings):
    """Merge task rules that read no storage, so a planner can repair them in one round."""
    errors = []
    merging = [(index, task) for index, task in enumerate(blueprint['tasks']) if task.get('merge')]
    if not merging:
        return errors
    if not is_document_action_enabled(DOCUMENT_ACTION_TYPE_MERGE, settings=settings):
        return [draft_error('merge_unavailable', ('tasks', index, 'merge')) for index, _ in merging]

    for index, task in merging:
        merge = task['merge']
        kind = _merge_kind(merge)
        if (task.get('runner') or {}).get('type') == 'agent':
            errors.append(draft_error('merge_runner_invalid', ('tasks', index, 'runner')))
        if merge['files'] == 'inputs' and len(task.get('inputs') or []) < 2:
            errors.append(draft_error('merge_inputs_required', ('tasks', index, 'inputs')))
        if merge['files'] == 'changed' and blueprint['trigger']['type'] != 'file_sync':
            errors.append(draft_error('merge_trigger_required', ('tasks', index, 'merge', 'files')))
        if merge.get('output_format') and merge['output_format'] not in MERGE_KIND_OUTPUT_FORMATS[kind]:
            errors.append(draft_error('merge_format_invalid', ('tasks', index, 'merge', 'output_format')))
            continue
        try:
            # The save's own rules, including the merge engine's, for this kind of merge.
            normalize_document_action_config(
                {
                    'type': DOCUMENT_ACTION_TYPE_MERGE, 'merge_kind': kind, 'target_mode': 'all',
                    'merge_options': _merge_options(merge.get('options'), aliases_as_pairs=True),
                },
                allowed_action_types={DOCUMENT_ACTION_TYPE_MERGE},
            )
        except ValueError:
            # Engine messages can quote column names from the blueprint; draft errors never echo input.
            errors.append(draft_error('merge_options_invalid', ('tasks', index, 'merge', 'options')))
    return errors


def _blueprint_payload(blueprint, handles, *, workflow_id, user_id, settings, enabled):
    trigger = blueprint['trigger']
    analyze_changed_documents = (
        trigger['type'] == 'file_sync'
        and DOCUMENT_ACTION_TYPE_ANALYZE in get_enabled_document_action_types(settings=settings)
    )
    references = []
    reference_ids = {}
    tasks = []
    for index, task in enumerate(blueprint['tasks']):
        task_reference_ids = []
        merge = task.get('merge')
        for handle in [] if merge else task.get('inputs') or []:
            if handle not in reference_ids:
                reference_ids[handle] = _derived_id(workflow_id, 'reference', handle)
                references.append({'id': reference_ids[handle], 'name': handle, **handles['documents'][handle]})
            task_reference_ids.append(reference_ids[handle])
        runner = task.get('runner') or {'type': 'model'}
        if runner['type'] == 'agent':
            task_runner = {'type': 'agent', 'selected_agent': dict(handles['agents'][runner['agent_ref']])}
        else:
            # The workflow runs on the default model; a blueprint never names one.
            task_runner = {'type': 'inherit'}
        if merge:
            document_action = _merge_document_action(merge, task, handles)
        elif index == 0 and analyze_changed_documents:
            # The first task of a File Sync workflow analyzes the documents each sync changed.
            document_action = {'type': DOCUMENT_ACTION_TYPE_ANALYZE, 'document_ids': []}
        else:
            document_action = {'type': 'none'}
        tasks.append({
            'id': _derived_id(workflow_id, 'task', index),
            'type': 'instructions',
            'name': task['title'],
            'instructions': task['instructions'],
            'runner': task_runner,
            'document_action': document_action,
            'reference_ids': task_reference_ids,
        })

    return {
        'name': blueprint['name'],
        'description': blueprint.get('description', ''),
        'definition_version': 2,
        'durable_execution': True,
        'runner_type': 'model',
        'model_endpoint_id': '',
        'model_id': '',
        'chat_capabilities_enabled': False,
        'error_handling': {'strategy': 'halt', 'retry_count': 0},
        'is_enabled': bool(enabled),
        'tasks': tasks,
        'reference_inputs': references,
        **_trigger_fields(trigger, handles),
        **_alert_fields(blueprint.get('alerts') or {}, workflow_id),
        'm365_run_as_user_id': str(user_id) if blueprint.get('run_as') == 'self' else '',
    }


def _handle_uses(blueprint):
    """Return where each handle is used: ``{kind: {handle: [path parts, ...]}}``, in blueprint order."""
    uses = {kind: {} for kind in BLUEPRINT_HANDLE_KINDS}
    for index, task in enumerate(blueprint['tasks']):
        for position, handle in enumerate(task.get('inputs') or []):
            uses['documents'].setdefault(handle, []).append(('tasks', index, 'inputs', position))
        runner = task.get('runner') or {}
        if runner.get('type') == 'agent':
            uses['agents'].setdefault(runner['agent_ref'], []).append(('tasks', index, 'runner', 'agent_ref'))
    trigger = blueprint['trigger']
    if trigger['type'] == 'file_sync':
        for position, handle in enumerate(trigger['source_ids']):
            uses['sources'].setdefault(handle, []).append(('trigger', 'source_ids', position))
    return uses


_UNKNOWN_HANDLE_MESSAGES = {
    'documents': 'No document was provided for this handle.',
    'agents': 'No agent was provided for this handle.',
    'sources': 'No File Sync source was provided for this handle.',
}


def _unknown_handle_errors(blueprint, handles):
    errors = []
    for kind, uses in _handle_uses(blueprint).items():
        for handle, paths in uses.items():
            if handle not in handles[kind]:
                errors.extend(draft_error('reference_unknown', path, _UNKNOWN_HANDLE_MESSAGES[kind]) for path in paths)
    return errors


def build_workflow_blueprint_payload(blueprint, handles, *, workflow_id, user_id, settings, enabled=False):
    """Map a valid blueprint to the version 2 workflow payload a save accepts.

    Deterministic: task, reference and alert rule ids derive from ``workflow_id``, so the same
    blueprint, handles and workflow id always give the same payload. It reads only ``settings``
    and authorizes nothing; ``dry_run_workflow_blueprint`` authorizes the result. Raises
    ``ValueError`` for a blueprint that fails the schema or names a handle not in ``handles``.
    """
    user_id = _required_id(user_id, 'user id')
    prepared, errors = _prepare_blueprint(blueprint)
    if errors:
        raise ValueError('The workflow blueprint is not valid.')
    normalized_handles = normalize_workflow_draft_handles(handles, user_id=user_id)
    if _unknown_handle_errors(prepared, normalized_handles):
        raise ValueError('The workflow blueprint names a handle that was not provided.')
    return _blueprint_payload(
        prepared, normalized_handles, workflow_id=str(uuid.UUID(str(workflow_id))),
        user_id=user_id, settings=settings, enabled=enabled,
    )


# ---------------------------------------------------------------------------
# Draft checks
# ---------------------------------------------------------------------------

def _required_settings(settings):
    # Without settings, the helpers below would load them, and loading settings can write defaults.
    if not isinstance(settings, dict) or not settings:
        raise ValueError('Pass the application settings to a workflow draft.')
    return settings


def _workflows_available(settings, user_info):
    # Chat orchestration reaches this service without the save routes' decorators, so it applies
    # their personal workflow gate itself: allow_user_workflows, and the WorkflowUser role if required.
    return is_user_workflows_enabled_for_user(settings, user_roles=(user_info or {}).get('roles'))


def _schedule_errors(trigger, settings):
    schedule, parts = _blueprint_schedule(trigger)
    if schedule is None:
        return []
    try:
        normalized = normalize_workflow_schedule(schedule)
    except WorkflowPublicValidationError as exc:
        if exc.public_message == SCHEDULE_TIMEZONE_ERROR:
            return [draft_error('trigger_invalid', parts + ('timezone',), exc.public_message)]
        return [draft_error('trigger_invalid', parts, exc.public_message)]
    try:
        enforce_orchestration_workflow_cadence(normalized, get_orchestration_workflow_min_interval_seconds(settings))
    except WorkflowCadenceError as exc:
        return [draft_error('cadence_below_minimum', parts, exc.public_message)]
    return []


def _agent_errors(uses, handles, *, user_id, settings, reader):
    errors = []
    for handle, paths in uses['agents'].items():
        try:
            # The same resolution a save applies: an enabled personal agent, or a merged global one.
            normalize_personal_workflow_task_runner(
                user_id, {'type': 'agent', 'selected_agent': dict(handles['agents'][handle])}, settings, reader,
            )
        except ValueError:
            errors.extend(draft_error('agent_unavailable', path) for path in paths)
    return errors


def _document_errors(uses, handles, *, user_id, resolver):
    errors = []
    for handle, paths in uses['documents'].items():
        reference = {'id': 'draft-reference', 'name': handle, **handles['documents'][handle]}
        try:
            authorize_workflow_reference(
                {'user_id': user_id}, reference, actor_user_id=user_id, resolve_document=resolver,
            )
        except (ValueError, PermissionError, LookupError, DocumentHeldError):
            errors.extend(draft_error('reference_unauthorized', path) for path in paths)
    return errors


def _file_sync_enabled_for(source, settings, user_id, user_info):
    if source['scope_type'] == FILE_SYNC_SCOPE_PERSONAL:
        return is_file_sync_enabled_for_user(settings, user_id, user_info=user_info)
    if source['scope_type'] == FILE_SYNC_SCOPE_GROUP:
        return is_file_sync_enabled_for_group(settings, source['scope_id'], user_info=user_info)
    return is_file_sync_enabled_for_public_workspace(settings, source['scope_id'], user_info=user_info)


def _source_errors(uses, handles, *, user_id, settings, user_info):
    errors = []
    for handle, paths in uses['sources'].items():
        source = handles['sources'][handle]
        try:
            if not _file_sync_enabled_for(source, settings, user_id, user_info):
                raise PermissionError('File Sync is not enabled for this source.')
            get_authorized_sync_source(source['scope_type'], source['source_id'], user_id, scope_id=source['scope_id'])
        except (LookupError, PermissionError, ValueError):
            errors.extend(draft_error('file_sync_source_unavailable', path) for path in paths)
    return errors


def check_orchestration_workflow_quota(user_id, settings):
    """Return a ``quota_exceeded`` draft error when the user has reached the cap, else ``None``.

    The cap counts the user's workflows that chat orchestration created and that are not being
    deleted. Two accepts at the same moment can both pass, so the cap can be exceeded by the number
    of concurrent accepts. A failed count raises, so the cap fails closed.
    """
    user_id = _required_id(user_id, 'user id')
    limit = get_chat_orchestration_max_workflows_per_user(_required_settings(settings))
    if count_personal_orchestration_workflows(user_id, WORKFLOW_ORIGIN_SOURCE_ORCHESTRATION) < limit:
        return None
    noun = 'workflow' if limit == 1 else 'workflows'
    return draft_error(
        'quota_exceeded', '',
        f'You already have {limit} {noun} created from chat, the most allowed. Delete one before adding another.',
    )


def _checked_blueprint(user_id, blueprint, handles, *, workflow_id, settings, user_info, enabled, check_quota,
                       reader, resolver):
    """Return ``(payload, errors)``: the payload for a blueprint that passes every draft check."""
    handles = normalize_workflow_draft_handles(handles, user_id=user_id)
    if check_quota:
        # Before the schema, so a user at the cap is not asked to repair a blueprint that cannot be created.
        quota_error = check_orchestration_workflow_quota(user_id, settings)
        if quota_error:
            return None, [quota_error]
    prepared, errors = _prepare_blueprint(blueprint)
    if errors:
        return None, errors
    task_limit = min(BLUEPRINT_MAX_TASKS, get_workflow_max_tasks(settings))
    if len(prepared['tasks']) > task_limit:
        return None, [draft_error('too_many_tasks', ('tasks',), f'This workflow can have up to {task_limit} tasks.')]
    errors = _unknown_handle_errors(prepared, handles)
    if errors:
        return None, errors
    uses = _handle_uses(prepared)
    # Collected together, so one repair round can fix every problem at once.
    errors = [
        *_schedule_errors(prepared['trigger'], settings),
        *_merge_errors(prepared, settings),
        *_agent_errors(uses, handles, user_id=user_id, settings=settings, reader=reader),
        *_document_errors(uses, handles, user_id=user_id, resolver=resolver),
        *_source_errors(uses, handles, user_id=user_id, settings=settings, user_info=user_info),
    ]
    if errors:
        return None, errors
    payload = _blueprint_payload(
        prepared, handles, workflow_id=workflow_id, user_id=user_id, settings=settings, enabled=enabled,
    )
    return payload, []


def check_workflow_blueprint(blueprint, *, settings, handle_names=None):
    """Check a blueprint against every draft rule that reads nothing, and return ``(blueprint, errors)``.

    The rules are the closed schema, the task limit and the schedule, including the floor on how
    often a workflow created from chat may run, and, when ``handle_names`` maps each handle kind
    (``agents``, ``documents``, ``sources``) to the handles offered with the request, that every
    handle the blueprint names is one of them. It returns a JSON round-tripped copy of a blueprint
    that passes and ``[]``, or ``None`` and up to ten draft errors. It reads no storage, so a
    planner can call it while it validates a plan; the quota, and whether each agent, document and
    File Sync source is still available to the user, are checked by ``dry_run_workflow_blueprint``.
    """
    settings = _required_settings(settings)
    prepared, errors = _prepare_blueprint(blueprint)
    if errors:
        return None, _finalize_errors(errors)
    task_limit = min(BLUEPRINT_MAX_TASKS, get_workflow_max_tasks(settings))
    if len(prepared['tasks']) > task_limit:
        return None, [draft_error('too_many_tasks', ('tasks',), f'This workflow can have up to {task_limit} tasks.')]
    errors = list(_schedule_errors(prepared['trigger'], settings))
    errors.extend(_merge_errors(prepared, settings))
    if handle_names is not None:
        names = {kind: set(handle_names.get(kind) or ()) for kind in BLUEPRINT_HANDLE_KINDS}
        errors = [*_unknown_handle_errors(prepared, names), *errors]
    if errors:
        return None, _finalize_errors(errors)
    return prepared, []


def _blueprint_build_errors(exc):
    """Map a build failure after the draft checks passed, which is rare, to a draft error."""
    if isinstance(exc, WorkflowCadenceError):
        return [draft_error('cadence_below_minimum', ('trigger',), exc.public_message)]
    if isinstance(exc, WorkflowSourceUnavailableError):
        return [draft_error('file_sync_source_unavailable', ('trigger', 'source_ids'))]
    if isinstance(exc, WorkflowDefinitionConflict):
        return [draft_error('workflow_conflict', '', exc.public_message)]
    if isinstance(exc, (WorkflowPublicValidationError, WorkflowDefinitionError)):
        return [draft_error('blueprint_invalid', '', exc.public_message)]
    if isinstance(exc, (PermissionError, LookupError, DocumentHeldError)):
        return [draft_error('reference_unauthorized', '', DRAFT_UNAVAILABLE_REFERENCE_MESSAGE)]
    return [draft_error('blueprint_invalid')]


def _log_draft_outcome(operation, user_id, result):
    # Codes only: never the blueprint, its text or the documents it names.
    log_event(
        f'[WorkflowDrafts] {operation} {"accepted" if result["ok"] else "rejected"}',
        extra={
            'operation': operation,
            'user_id': user_id,
            'workflow_id': (result.get('workflow') or {}).get('id', ''),
            'created': bool(result.get('created')),
            'error_codes': sorted({error['code'] for error in result['errors']}),
        },
        level=logging.INFO,
    )
    return result


def dry_run_workflow_blueprint(user_id, blueprint, handles, *, origin, settings, user_info=None, enabled=False,
                               check_quota=True, resolve_document=None, user_settings_reader=None):
    """Validate a blueprint and build the personal workflow it would create, writing nothing.

    Returns ``{'ok', 'workflow', 'errors'}``: the normalized workflow document, exactly as the
    create would store it, or up to ten draft errors, sorted by path. It creates no workflow or
    conversation, sends no notification and makes no blob, Key Vault or Microsoft 365 call. It
    needs no Flask context, so it can run on an executor thread; pass the application
    ``settings`` and the requesting user's ``user_info`` (their ``roles`` gate personal
    workflows and File Sync).

    ``origin`` is the provenance the create would record; its ``proposal_id`` fixes the workflow
    id. ``resolve_document`` and ``user_settings_reader`` replace the default read-only seams, for
    tests. A malformed ``handles`` map or ``origin`` is a caller bug and raises ``ValueError``.
    """
    user_id = _required_id(user_id, 'user id')
    settings = _required_settings(settings)
    origin = normalize_workflow_origin(origin)
    workflow_id = orchestration_workflow_id(user_id, origin['proposal_id'])
    if not _workflows_available(settings, user_info):
        return _log_draft_outcome('dry_run', user_id, _failure([draft_error('workflows_unavailable')]))

    reader, resolver = _draft_seams(user_settings_reader, resolve_document)
    payload, errors = _checked_blueprint(
        user_id, blueprint, handles, workflow_id=workflow_id, settings=settings, user_info=user_info,
        enabled=enabled, check_quota=check_quota, reader=reader, resolver=resolver,
    )
    if errors:
        return _log_draft_outcome('dry_run', user_id, _failure(errors))
    try:
        workflow, _existing = build_personal_workflow_document(
            user_id, payload, user_id, settings=settings, workflow_id=workflow_id, origin=origin,
            user_settings_reader=reader, resolve_document=resolver, sanitize_source=_project_source,
        )
    except WorkflowLoopLimitError:
        # A misconfigured administrator limit is a server fault, not something a repair can fix.
        raise
    except (ValueError, PermissionError, LookupError, DocumentHeldError) as exc:
        return _log_draft_outcome('dry_run', user_id, _failure(_blueprint_build_errors(exc)))
    return _log_draft_outcome('dry_run', user_id, _success(workflow))


# ---------------------------------------------------------------------------
# Workflow payload dry runs
# ---------------------------------------------------------------------------

def _payload_errors(exc):
    """Map a build failure for an editor payload to a draft error, with the code a save route returns."""
    if isinstance(exc, (WorkflowDefinitionError, WorkflowPublicValidationError)):
        return [draft_error(exc.code, '', exc.public_message)]
    if isinstance(exc, DocumentHeldError):
        return [draft_error('reference_unauthorized', '', DRAFT_UNAVAILABLE_REFERENCE_MESSAGE)]
    if isinstance(exc, LookupError):
        return [draft_error('workflow_unavailable', '', 'This workflow or one of its inputs is no longer available.')]
    if isinstance(exc, PermissionError):
        return [draft_error('not_allowed', '', 'Workflow settings or sources are not allowed for this account.')]
    return [draft_error(
        'invalid_workflow', '', 'Invalid workflow settings. Review the task, runner, trigger, and document inputs.',
    )]


def dry_run_personal_workflow(user_id, workflow_data, *, actor_user_id=None, settings, resolve_document=None,
                              user_settings_reader=None):
    """Build a personal workflow payload exactly as saving it would, writing nothing.

    For an editor's draft: a new workflow, or an update naming an existing one with its
    ``definition_revision``, so a stale draft returns ``workflow_definition_conflict``. Returns
    ``{'ok', 'workflow', 'errors'}``; error codes and messages match what the save route returns.
    Callers authorize the request as the save route does; this checks what the save checks.
    """
    user_id = _required_id(user_id, 'user id')
    settings = _required_settings(settings)
    reader, resolver = _draft_seams(user_settings_reader, resolve_document)
    try:
        workflow, _existing = build_personal_workflow_document(
            user_id, copy.deepcopy(workflow_data), actor_user_id, settings=settings,
            user_settings_reader=reader, resolve_document=resolver, sanitize_source=_project_source,
        )
    except WorkflowLoopLimitError:
        raise
    except (ValueError, PermissionError, LookupError, DocumentHeldError) as exc:
        return _log_draft_outcome('personal_payload_dry_run', user_id, _failure(_payload_errors(exc)))
    return _log_draft_outcome('personal_payload_dry_run', user_id, _success(workflow))


def dry_run_group_workflow(group_id, workflow_data, actor_user_id, *, user_info, settings, resolve_document=None):
    """Build a group workflow payload exactly as saving it would, writing nothing.

    The group counterpart of ``dry_run_personal_workflow``. ``user_info`` is the acting user's
    identity with their ``roles``, which File Sync enablement reads. Callers authorize the
    request, including the actor's group role, as the group save route does.
    """
    group_id = _required_id(group_id, 'group id')
    actor_user_id = _required_id(actor_user_id, 'user id')
    settings = _required_settings(settings)
    _reader, resolver = _draft_seams(None, resolve_document)
    try:
        workflow, _existing = build_group_workflow_document(
            group_id, copy.deepcopy(workflow_data), actor_user_id, user_info=user_info, settings=settings,
            resolve_document=resolver, sanitize_source=_project_source,
        )
    except WorkflowLoopLimitError:
        raise
    except (ValueError, PermissionError, LookupError, DocumentHeldError) as exc:
        return _log_draft_outcome('group_payload_dry_run', actor_user_id, _failure(_payload_errors(exc)))
    return _log_draft_outcome('group_payload_dry_run', actor_user_id, _success(workflow))


# ---------------------------------------------------------------------------
# Creating accepted drafts
# ---------------------------------------------------------------------------

def _requests_url_access(payload):
    """Return whether a payload turns URL Access on, reading the flag as the workflow build does."""
    value = payload.get('url_access_enabled', False)
    if isinstance(value, str):
        return value.strip().lower() in {'1', 'true', 'yes', 'on'}
    return bool(value)


def _repeated_create(user_id, workflow_id, proposal_id):
    """Return the result for a proposal that was already accepted, or ``None`` for a new one."""
    existing = get_personal_workflow(user_id, workflow_id)
    if not existing:
        return None
    try:
        workflow = existing_server_created_workflow(existing, proposal_id)
    except WorkflowDefinitionConflict as exc:
        return _failure([draft_error('workflow_conflict', '', exc.public_message)], created=False)
    return _success(workflow_definition_for_editor(workflow), created=False)


def create_personal_workflow_from_blueprint(user_id, blueprint, handles, *, origin, settings, user_info=None,
                                            enabled=False, resolve_document=None, user_settings_reader=None):
    """Create the personal workflow a blueprint describes, at most once per proposal.

    Applies every ``dry_run_workflow_blueprint`` check, including the per-user cap, then stores
    the workflow under ``orchestration_workflow_id(user_id, origin['proposal_id'])`` with the
    ``origin`` provenance. Accepting the same proposal again returns the stored workflow with
    ``created`` False, even at the cap. Returns ``{'ok', 'workflow', 'created', 'errors'}``;
    the workflow is paused unless ``enabled``.
    """
    user_id = _required_id(user_id, 'user id')
    settings = _required_settings(settings)
    origin = normalize_workflow_origin(origin)
    workflow_id = orchestration_workflow_id(user_id, origin['proposal_id'])
    normalize_workflow_draft_handles(handles, user_id=user_id)
    if not _workflows_available(settings, user_info):
        return _log_draft_outcome('create', user_id, _failure([draft_error('workflows_unavailable')], created=False))
    repeated = _repeated_create(user_id, workflow_id, origin['proposal_id'])
    if repeated is not None:
        return _log_draft_outcome('create', user_id, repeated)

    reader, resolver = _draft_seams(user_settings_reader, resolve_document)
    payload, errors = _checked_blueprint(
        user_id, blueprint, handles, workflow_id=workflow_id, settings=settings, user_info=user_info,
        enabled=enabled, check_quota=True, reader=reader, resolver=resolver,
    )
    if errors:
        return _log_draft_outcome('create', user_id, _failure(errors, created=False))
    try:
        workflow, created = create_personal_workflow_if_absent(
            user_id, payload, workflow_id=workflow_id, origin=origin, actor_user_id=user_id, settings=settings,
            user_settings_reader=reader, resolve_document=resolver, sanitize_source=_project_source,
        )
    except WorkflowLoopLimitError:
        raise
    except (ValueError, PermissionError, LookupError, DocumentHeldError) as exc:
        return _log_draft_outcome('create', user_id, _failure(_blueprint_build_errors(exc), created=False))
    return _log_draft_outcome(
        'create', user_id, _success(workflow_definition_for_editor(workflow), created=created),
    )


def create_personal_workflow_from_payload(user_id, workflow_data, *, origin, settings, user_info=None,
                                          resolve_document=None, user_settings_reader=None):
    """Create a personal workflow from an editor payload for an accepted proposal, at most once.

    For a proposal the user edited before accepting: the editor's payload is built exactly as a
    save builds it, under the id and ``origin`` a blueprint create would use, so either path
    creates the same workflow once. A payload may omit ``id`` or repeat that derived id; any other
    id is ``workflow_conflict``. The workflow is paused unless the payload enables it. Applies
    the personal workflow gate, the per-user cap and the schedule minimum for workflows created
    from chat. URL Access is refused (``unsupported_field``), and the URL Access authorization
    fields are dropped, because only the save route may authorize URL Access from the user's
    roles. Returns ``{'ok', 'workflow', 'created', 'errors'}``.
    """
    user_id = _required_id(user_id, 'user id')
    settings = _required_settings(settings)
    origin = normalize_workflow_origin(origin)
    workflow_id = orchestration_workflow_id(user_id, origin['proposal_id'])
    payload = copy.deepcopy(workflow_data) if isinstance(workflow_data, dict) else {}
    for field in URL_ACCESS_AUTHORIZATION_FIELDS:
        payload.pop(field, None)
    payload_id = str(payload.pop('id', None) or '').strip()
    if payload_id and payload_id != workflow_id:
        return _log_draft_outcome('create_from_payload', user_id, _failure(
            [draft_error('workflow_conflict', ('id',), 'This draft names a different workflow.')], created=False,
        ))
    payload.setdefault('is_enabled', False)
    if not _workflows_available(settings, user_info):
        return _log_draft_outcome(
            'create_from_payload', user_id, _failure([draft_error('workflows_unavailable')], created=False),
        )
    repeated = _repeated_create(user_id, workflow_id, origin['proposal_id'])
    if repeated is not None:
        return _log_draft_outcome('create_from_payload', user_id, repeated)
    quota_error = check_orchestration_workflow_quota(user_id, settings)
    if quota_error:
        return _log_draft_outcome('create_from_payload', user_id, _failure([quota_error], created=False))
    if _requests_url_access(payload):
        return _log_draft_outcome('create_from_payload', user_id, _failure(
            [draft_error('unsupported_field', ('url_access_enabled',), DRAFT_URL_ACCESS_MESSAGE)], created=False,
        ))

    reader, resolver = _draft_seams(user_settings_reader, resolve_document)
    try:
        workflow, created = create_personal_workflow_if_absent(
            user_id, payload, workflow_id=workflow_id, origin=origin, actor_user_id=user_id, settings=settings,
            user_settings_reader=reader, resolve_document=resolver, sanitize_source=_project_source,
        )
    except WorkflowLoopLimitError:
        raise
    except (ValueError, PermissionError, LookupError, DocumentHeldError) as exc:
        return _log_draft_outcome('create_from_payload', user_id, _failure(_payload_errors(exc), created=False))
    return _log_draft_outcome(
        'create_from_payload', user_id, _success(workflow_definition_for_editor(workflow), created=created),
    )
