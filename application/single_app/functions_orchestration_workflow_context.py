# functions_orchestration_workflow_context.py
"""Planning context for workflow proposals, runs and results from chat orchestration.

Version: 0.261.217

Chat orchestration can propose a personal workflow (the ``workflow_propose`` capability), start
one the user already has (the ``workflow_run`` capability) and read the stored result of one of
the user's finished workflow runs (the ``workflow_results`` capability). The planner writes a
workflow blueprint, or names the workflow to start or read, by request-local handles such as
``agent-mail-helper-3f2a1c``. This module builds those handles from what the requesting user may
use and keeps the map from each handle to its stored record on the server. The planner sees names,
kinds and limits as bounded data, never record ids, task instructions or credentials.

Everything here reads and never writes. Nothing is read unless at least one of the three
capabilities is configured, the user may use personal workflows, and the conversation is private
to the requester. They are independent: with only proposals on, a request plans exactly as it
did before workflow runs existed, and with all of them off it plans as it did before any existed.
"""

import hashlib
import json
import logging
import re
import time
import unicodedata
from copy import deepcopy
from datetime import datetime, timezone

from functions_action_catalog import _eligible_record, _private_values, _safe_text, _stored_actions
from functions_action_manifest import resolve_action_type
from functions_appinsights import log_event
from functions_m365_operations import (
    M365_ACTION_DEFINITIONS,
    M365_LEGACY_OPERATION_SOURCES,
    get_m365_enabled_function_names,
)
from functions_msgraph_operations import get_msgraph_enabled_function_names, resolve_msgraph_action_capabilities
from functions_orchestration_memory import conversation_is_private
# One definition of each: the step schema, the deliverables and this module read the same values.
from functions_orchestration_registry import (
    CAPABILITY_WORKFLOW_PROPOSE as WORKFLOW_PROPOSE_CAPABILITY_ID,
    CAPABILITY_WORKFLOW_RESULTS as WORKFLOW_RESULTS_CAPABILITY_ID,
    CAPABILITY_WORKFLOW_RUN as WORKFLOW_RUN_CAPABILITY_ID,
    WORKFLOW_PROPOSAL_MAX_TASKS as WORKFLOW_BLUEPRINT_MAX_TASKS,
    WORKFLOW_PROPOSALS_SETTING,
    WORKFLOW_RESULTS_SETTING,
    WORKFLOW_RUNS_SETTING,
    WORKFLOW_TASK_ACTION_KINDS as WORKFLOW_ACTION_KINDS,
)
from functions_workflow_limits import (
    get_chat_orchestration_max_workflows_per_user,
    get_orchestration_workflow_min_interval_seconds,
)
from functions_workflow_schedules import (
    workflow_run_time_context,
    workflow_schedule_label,
    workflow_schedule_summary,
    workflow_schedule_timezones,
)


# Closed reasons. They are mapped to application-owned text; none of them carries caller data.
WORKFLOW_REASON_DISABLED = 'workflow_proposals_disabled'
WORKFLOW_RUNS_REASON_DISABLED = 'workflow_runs_disabled'
WORKFLOW_RESULTS_REASON_DISABLED = 'workflow_results_disabled'
WORKFLOW_RESULTS_REASON_NO_WORKFLOWS = 'workflow_results_no_workflows'
WORKFLOW_REASON_ROLE_REQUIRED = 'workflow_role_required'
WORKFLOW_REASON_SHARED_CONVERSATION = 'workflow_shared_conversation'
WORKFLOW_REASON_QUOTA_REACHED = 'workflow_quota_reached'
WORKFLOW_REASON_CONTEXT_UNAVAILABLE = 'workflow_context_unavailable'

WORKFLOW_DEFAULT_TIME_ZONE = 'UTC'

CATALOG_MAX_AGENTS = 25
CATALOG_MAX_SOURCES = 25
CATALOG_MAX_DOCUMENTS = 25
CATALOG_MAX_WORKFLOWS = 20
CATALOG_MIN_WORKFLOWS = 5
CATALOG_MAX_AGENT_ACTIONS = 8
CATALOG_MAX_CHARACTERS = 12000
WORKFLOW_SCAN_LIMIT = 500
# The shortest workflow name that counts as named by a request, so "Go" does not match every "go".
WORKFLOW_NAME_MATCH_MIN_LENGTH = 3

NAME_MAX_LENGTH = 80
AGENT_DESCRIPTION_MAX_LENGTH = 200
WORKFLOW_DESCRIPTION_MAX_LENGTH = 160
DOCUMENT_NAME_MAX_LENGTH = 120
ACTION_NAME_MAX_LENGTH = 80
SOURCE_TYPE_MAX_LENGTH = 40
RECORD_ID_MAX_LENGTH = 128
DOCUMENT_ID_MAX_LENGTH = 256
HANDLE_SLUG_MAX_LENGTH = 40
TIME_ZONE_MAX_LENGTH = 64

# WORKFLOW_ACTION_KINDS, imported above, is the closed set of action kinds a task can be matched against.
WORKFLOW_M365_ACTION_KINDS = frozenset({'email', 'calendar', 'onedrive', 'sharepoint', 'directory'})
WORKFLOW_SEND_FUNCTIONS = frozenset({'send_mail', 'create_calendar_invite'})

WORKFLOW_SCOPE_TYPES = ('personal', 'group', 'public')

_HANDLE_PREFIXES = {'agents': 'agent', 'documents': 'doc', 'sources': 'source', 'workflows': 'workflow'}
_HANDLE_RE = re.compile(r'^[a-z][a-z0-9_-]{0,63}$')
# Control, zero-width, line/paragraph separator and bidirectional formatting characters.
_TEXT_NOISE = re.compile('[\x00-\x1f\x7f-\x9f\u200b-\u200f\u2028-\u202e\u2060-\u2069\ufeff]')
_M365_TYPE_KINDS = {
    'm365_calendar': 'calendar',
    'm365_email': 'email',
    'm365_onedrive': 'onedrive',
    'm365_sharepoint': 'sharepoint',
}
_DRAFT_HANDLE_KINDS = ('agents', 'documents', 'sources')


# ---------------------------------------------------------------------------
# Text, time zones and handles
# ---------------------------------------------------------------------------

def clean_catalog_text(value, limit):
    """Return user-authored text as one bounded, printable line, or '' for anything else."""
    if not isinstance(value, str):
        return ''
    text = ' '.join(_TEXT_NOISE.sub(' ', value).split())
    if len(text) <= limit:
        return text
    return text[:limit - 1].rstrip() + '\u2026'


def validated_request_time_zone(value):
    """Return an exact IANA time zone name a calendar schedule may use, or None."""
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text or len(text) > TIME_ZONE_MAX_LENGTH or text not in workflow_schedule_timezones():
        return None
    return text


def resolve_turn_time_zone(*candidates):
    """Return the first valid time zone among ``candidates``, falling back to UTC."""
    for candidate in candidates:
        zone = validated_request_time_zone(candidate)
        if zone:
            return zone
    return WORKFLOW_DEFAULT_TIME_ZONE


def request_local_time_line(time_zone, now=None):
    """Name the current local time with the same wording a calendar workflow run uses.

    A scheduled run adds ``workflow_run_time_context`` to every task, so a preview answered now and
    the workflow's later runs resolve phrases such as "this week" the same way.
    """
    zone = resolve_turn_time_zone(time_zone)
    schedule = {'kind': 'calendar', 'frequency': 'daily', 'time_of_day': '00:00', 'timezone': zone}
    return workflow_run_time_context(schedule, now or datetime.now(timezone.utc))


def workflow_handle(kind, object_key, name, taken):
    """Return a new handle for one record, deterministic for the same record and name.

    The handle is a readable slug of ``name`` and a short digest of the record's key, so it never
    contains a record id. ``taken`` is the set of handles already issued for this request; a
    collision gets a numeric suffix, and the new handle is added to it.
    """
    prefix = _HANDLE_PREFIXES[kind]
    digest = hashlib.sha256(f'{kind}:{object_key}'.encode('utf-8')).hexdigest()[:6]
    slug = unicodedata.normalize('NFKD', name if isinstance(name, str) else '')
    slug = slug.encode('ascii', 'ignore').decode('ascii').lower()
    slug = re.sub(r'[^a-z0-9]+', '-', slug).strip('-')[:HANDLE_SLUG_MAX_LENGTH].strip('-')
    base = f'{prefix}-{slug}-{digest}' if slug else f'{prefix}-{digest}'
    handle = base
    suffix = 2
    while handle in taken:
        handle = f'{base}-{suffix}'
        suffix += 1
    if not _HANDLE_RE.fullmatch(handle):
        raise ValueError('A workflow handle could not be generated.')
    taken.add(handle)
    return handle


def _record_id(value, limit=RECORD_ID_MAX_LENGTH):
    if not isinstance(value, str):
        return ''
    text = value.strip()
    return text if len(text) <= limit else ''


# ---------------------------------------------------------------------------
# Gates
# ---------------------------------------------------------------------------

def workflow_proposals_configured(settings):
    """Whether an administrator turned on workflow proposals for chat orchestration.

    Only a real boolean ``True`` turns them on, so a stored string such as ``"false"`` leaves them off.
    """
    settings = settings if isinstance(settings, dict) else {}
    return bool(settings.get('enable_chat_orchestration')) and settings.get(WORKFLOW_PROPOSALS_SETTING) is True


def workflow_runs_configured(settings):
    """Whether an administrator turned on starting saved workflows from chat orchestration.

    Only a real boolean ``True`` turns it on. It is independent of workflow proposals: either can be
    on without the other.
    """
    settings = settings if isinstance(settings, dict) else {}
    return bool(settings.get('enable_chat_orchestration')) and settings.get(WORKFLOW_RUNS_SETTING) is True


def workflow_results_configured(settings):
    """Whether an administrator lets chat orchestration read stored workflow results.

    Only a real boolean ``True`` for Use Workflow Results In Chat turns it on. It is independent of
    workflow proposals and runs: any of the three can be on without the others.
    """
    settings = settings if isinstance(settings, dict) else {}
    return bool(settings.get('enable_chat_orchestration')) and settings.get(WORKFLOW_RESULTS_SETTING) is True


def workflow_planning_configured(settings):
    """Whether any workflow capability is configured, so a turn may need a workflow planning context."""
    return (
        workflow_proposals_configured(settings) or workflow_runs_configured(settings)
        or workflow_results_configured(settings)
    )


def workflow_time_zone_configured(settings):
    """Whether a turn's workflow planning needs the user's time zone.

    A proposal schedules in it and a workflow results step names the local day a run finished on.
    Starting a saved workflow needs neither, so with only runs on a turn is exactly what it was.
    """
    return workflow_proposals_configured(settings) or workflow_results_configured(settings)


def workflow_planning_option(workflow_planning):
    """``{'workflow_planning': ...}`` when the turn has one, else ``{}``.

    Callers spread this into their keyword arguments, so a request without workflow proposals
    calls every context builder with exactly the arguments it used before they existed.
    """
    return {'workflow_planning': workflow_planning} if isinstance(workflow_planning, dict) else {}


def workflow_run_options(workflow_planning, time_zone):
    """The optional run-context keywords for a turn's workflow planning and time zone."""
    options = workflow_planning_option(workflow_planning)
    if isinstance(time_zone, str) and time_zone:
        options['time_zone'] = time_zone
    return options


def workflow_planning_gate(settings, user_roles):
    """Return None when this user may be offered workflow proposals, else a closed reason."""
    settings = settings if isinstance(settings, dict) else {}
    if not workflow_proposals_configured(settings) or not settings.get('allow_user_workflows'):
        return WORKFLOW_REASON_DISABLED
    # Imported here because the registry's workflow capability gate imports this module.
    from functions_orchestration_registry import capability_allowlisted
    if not capability_allowlisted(settings, WORKFLOW_PROPOSE_CAPABILITY_ID):
        return WORKFLOW_REASON_DISABLED
    # Settings initialize application storage, so they are imported only once a gate is reached.
    from functions_settings import is_user_workflows_enabled_for_user
    roles = list(user_roles) if isinstance(user_roles, (list, tuple, set)) else []
    if not is_user_workflows_enabled_for_user(settings, user_roles=roles):
        return WORKFLOW_REASON_ROLE_REQUIRED
    return None


def workflow_run_settings_gate(settings):
    """Return None when the deployment lets a plan start a saved workflow, else a closed reason.

    Settings and the capability allowlist only. The caller's WorkflowUser role is checked by
    ``workflow_run_gate``; linking a run that already started needs only this part.
    """
    settings = settings if isinstance(settings, dict) else {}
    if not workflow_runs_configured(settings) or not settings.get('allow_user_workflows'):
        return WORKFLOW_RUNS_REASON_DISABLED
    # Imported here because the registry's workflow capability gates import this module.
    from functions_orchestration_registry import capability_allowlisted
    if not capability_allowlisted(settings, WORKFLOW_RUN_CAPABILITY_ID):
        return WORKFLOW_RUNS_REASON_DISABLED
    return None


def workflow_run_gate(settings, user_roles):
    """Return None when this user may be offered starting a saved workflow, else a closed reason."""
    reason = workflow_run_settings_gate(settings)
    if reason:
        return reason
    # Settings initialize application storage, so they are imported only once a gate is reached.
    from functions_settings import is_user_workflows_enabled_for_user
    roles = list(user_roles) if isinstance(user_roles, (list, tuple, set)) else []
    if not is_user_workflows_enabled_for_user(settings, user_roles=roles):
        return WORKFLOW_REASON_ROLE_REQUIRED
    return None


def workflow_results_settings_gate(settings):
    """Return None when the deployment lets a plan read stored workflow results, else a closed reason.

    Settings and the capability allowlist only; ``workflow_results_gate`` adds the caller's roles.
    """
    settings = settings if isinstance(settings, dict) else {}
    if not workflow_results_configured(settings) or not settings.get('allow_user_workflows'):
        return WORKFLOW_RESULTS_REASON_DISABLED
    # Imported here because the registry's workflow capability gates import this module.
    from functions_orchestration_registry import capability_allowlisted
    if not capability_allowlisted(settings, WORKFLOW_RESULTS_CAPABILITY_ID):
        return WORKFLOW_RESULTS_REASON_DISABLED
    return None


def workflow_results_gate(settings, user_roles):
    """Return None when this user may be offered reading their workflow results, else a closed reason.

    The role check is the one that decides whether chat shows a finished run's result card at all,
    so a plan never reads a result the user could not ask about in chat.
    """
    reason = workflow_results_settings_gate(settings)
    if reason:
        return reason
    # Settings initialize application storage, so they are imported only once a gate is reached.
    from functions_settings import is_chat_workflow_results_enabled_for_user
    roles = list(user_roles) if isinstance(user_roles, (list, tuple, set)) else []
    if not is_chat_workflow_results_enabled_for_user(settings, user_roles=roles):
        return WORKFLOW_REASON_ROLE_REQUIRED
    return None


# ---------------------------------------------------------------------------
# Default readers (lazy: each one needs initialized application storage)
# ---------------------------------------------------------------------------

_AGENT_FIELDS = (
    'c.id, c.name, c.display_name, c.description, c.is_enabled, c.actions_to_load, '
    'c.other_settings.action_capabilities AS action_capabilities'
)


def _read_personal_agents(user_id):
    # A projected read: the agent getters hydrate Key Vault references, which a catalog never needs.
    from config import cosmos_personal_agents_container
    return list(cosmos_personal_agents_container.query_items(
        query=f'SELECT {_AGENT_FIELDS}, c.user_id FROM c WHERE c.user_id = @user_id',
        parameters=[{'name': '@user_id', 'value': user_id}],
        partition_key=user_id,
    ))


def _read_global_agents():
    from config import cosmos_global_agents_container
    return list(cosmos_global_agents_container.query_items(
        query=f'SELECT {_AGENT_FIELDS} FROM c WHERE NOT IS_DEFINED(c.is_enabled) OR c.is_enabled = true',
        enable_cross_partition_query=True,
    ))


def _read_actions(scope_type, scope_id):
    return list(_stored_actions(scope_type, scope_id))


def _govern_actions(user_id, scope_type, actions):
    import functions_governance
    if scope_type == 'global':
        return functions_governance.filter_governed_global_actions_for_user(user_id, actions)
    return functions_governance.filter_actions_by_action_type_access(
        user_id, actions, 'governance_user_actions', 'personal',
    )


def _read_sources(user_id, settings, user_info):
    from functions_settings import read_user_settings_snapshot
    from functions_workflow_file_sync_sources import (
        collect_personal_workflow_file_sync_sources,
        project_workflow_file_sync_source,
    )
    _enabled, sources = collect_personal_workflow_file_sync_sources(
        user_id, settings, user_info,
        serialize=project_workflow_file_sync_source,
        user_settings_reader=read_user_settings_snapshot,
    )
    return sources


def _read_workflows(user_id):
    from config import cosmos_personal_workflows_container
    return list(cosmos_personal_workflows_container.query_items(
        query=(
            f'SELECT TOP {WORKFLOW_SCAN_LIMIT} c.id, c.name, c.description, c.trigger_type, c.schedule, '
            'c.is_enabled, c.durable_execution, c.deleting, c.updated_at, c.created_at, c.file_sync '
            'FROM c WHERE c.user_id = @user_id'
        ),
        parameters=[{'name': '@user_id', 'value': user_id}],
        partition_key=user_id,
    ))


def _count_quota(user_id):
    from functions_personal_workflows import count_personal_orchestration_workflows
    return count_personal_orchestration_workflows(user_id, 'orchestration')


def _max_tasks(settings):
    from functions_personal_workflows import get_workflow_max_tasks
    return get_workflow_max_tasks(settings)


def _default_model_valid(settings):
    from functions_personal_workflows import _build_default_model_summary
    return bool(_build_default_model_summary(settings).get('valid'))


_DEFAULT_READERS = {
    'personal_agents': _read_personal_agents,
    'global_agents': _read_global_agents,
    'actions': _read_actions,
    'govern': _govern_actions,
    'sources': _read_sources,
    'workflows': _read_workflows,
    'quota_count': _count_quota,
    'max_tasks': _max_tasks,
    'default_model': _default_model_valid,
}


def _readers(overrides):
    readers = dict(_DEFAULT_READERS)
    if isinstance(overrides, dict):
        readers.update({key: value for key, value in overrides.items() if key in readers and callable(value)})
    return readers


# ---------------------------------------------------------------------------
# Agents and the actions they can use
# ---------------------------------------------------------------------------

def _requested_actions(agent):
    requested = set()
    references = agent.get('actions_to_load')
    for reference in references if isinstance(references, (list, tuple)) else ():
        if isinstance(reference, str):
            requested.add(reference)
        elif isinstance(reference, dict):
            requested.update(value for value in (reference.get('id'), reference.get('name')) if isinstance(value, str))
    requested.discard('')
    return requested


def _requests(action, requested):
    return any(isinstance(value, str) and value in requested for value in (action.get('id'), action.get('name')))


def _m365_functions(action, overrides):
    """The enabled functions of a Microsoft 365 action, resolved exactly as a workflow run does."""
    action_type = action.get('type')
    fields = action.get('additionalFields') or {}
    if action_type == 'msgraph':
        defaults = fields.get('msgraph_capabilities', action.get('msgraph_capabilities'))
        saved = set(get_msgraph_enabled_function_names(defaults))
        if action.get('msgraph_capabilities') is not None:
            saved.intersection_update(get_msgraph_enabled_function_names(action['msgraph_capabilities']))
        if action.get('enabled_functions') is not None:
            saved.intersection_update(action['enabled_functions'])
        capabilities = resolve_msgraph_action_capabilities(
            overrides, action_defaults=defaults, action_id=action.get('id'), action_name=action.get('name'),
        )
        return sorted(saved.intersection(get_msgraph_enabled_function_names(capabilities)))
    override = overrides.get(action.get('id'), overrides.get(action.get('name')))
    return sorted(get_m365_enabled_function_names(action_type, action, agent_capabilities=override))


def _is_m365_action(action):
    action_type = action.get('type')
    return action_type == 'msgraph' or action_type in M365_ACTION_DEFINITIONS


def _m365_kinds(action, functions):
    action_type = action.get('type')
    if action_type in _M365_TYPE_KINDS:
        return {_M365_TYPE_KINDS[action_type]} if functions else set()
    return {M365_LEGACY_OPERATION_SOURCES.get(name, 'directory') for name in functions}


def _other_action_kinds(action):
    action_type = resolve_action_type(action)
    if action_type == 'mcp':
        return {'mcp'}
    if action_type.strip().lower() == 'openapi':
        return {'openapi'}
    return {'other'}


def _ordered_kinds(kinds):
    return [kind for kind in WORKFLOW_ACTION_KINDS if kind in kinds]


def _action_label(action):
    private_values = _private_values(action)
    for field in ('display_name', 'displayName', 'name'):
        label = clean_catalog_text(_safe_text(action.get(field), 200, private_values), ACTION_NAME_MAX_LENGTH)
        if label:
            return label
    return 'Action'


def _agent_overrides(agent):
    if 'action_capabilities' in agent:
        return agent.get('action_capabilities') or {}
    return (agent.get('other_settings') or {}).get('action_capabilities') or {}


def _agent_profile(agent, runtime_pool, governed_keys):
    """Describe what an agent can do in a workflow; raises when its actions cannot be resolved.

    ``runtime_pool`` is every ``(scope, action)`` a workflow run resolves for this agent, the pool
    the run's Microsoft 365 Run-as requirement comes from. ``governed_keys`` names the
    ``(scope, action id)`` pairs this user may use under governance, which is what the planner is
    told the agent can do.
    """
    requested = _requested_actions(agent)
    overrides = _agent_overrides(agent)
    kinds = set()
    actions = []
    m365_sources = set()
    can_send = False
    needs_run_as = False
    for scope, action in runtime_pool:
        if not _requests(action, requested):
            continue
        governed = (scope, action.get('id')) in governed_keys
        if _is_m365_action(action):
            functions = _m365_functions(action, overrides)
            if not functions:
                continue
            needs_run_as = True
            m365_sources.update(_m365_kinds(action, functions))
            can_send = can_send or bool(WORKFLOW_SEND_FUNCTIONS.intersection(functions))
            action_kinds = _m365_kinds(action, functions)
        elif governed:
            action_kinds = _other_action_kinds(action)
        else:
            continue
        if not governed or not action_kinds:
            continue
        kinds.update(action_kinds)
        if len(actions) < CATALOG_MAX_AGENT_ACTIONS:
            actions.append({'name': _action_label(action), 'kinds': _ordered_kinds(action_kinds)})
    return {
        'action_kinds': _ordered_kinds(kinds),
        'actions': actions,
        'm365_sources': _ordered_kinds(m365_sources),
        'can_send': can_send,
        'needs_run_as': needs_run_as,
    }


def _agent_entries(user_id, settings, readers, taken):
    if not (settings.get('enable_semantic_kernel') and settings.get('allow_user_agents')):
        return []
    merge_global = bool(settings.get('merge_global_semantic_kernel_with_workspace'))
    personal_agents = [agent for agent in readers['personal_agents'](user_id) or () if isinstance(agent, dict)]
    global_agents = []
    if settings.get('per_user_semantic_kernel') and merge_global:
        global_agents = [agent for agent in readers['global_agents']() or () if isinstance(agent, dict)]
    candidates = [(agent, False) for agent in personal_agents] + [(agent, True) for agent in global_agents]
    candidates = [
        (agent, is_global) for agent, is_global in candidates
        if agent.get('is_enabled', True)
        and _record_id(agent.get('id'))
        and len(str(agent.get('name') or '').strip()) <= RECORD_ID_MAX_LENGTH
        and (is_global or agent.get('user_id') in (None, user_id))
    ]
    if not candidates:
        return []

    wants_actions = any(_requested_actions(agent) for agent, _is_global in candidates)
    wants_global = wants_actions and (bool(global_agents) or merge_global)
    personal_actions = [
        action for action in (readers['actions']('personal', user_id) if wants_actions else ()) or ()
        if isinstance(action, dict)
    ]
    global_actions = [
        action for action in (readers['actions']('global', 'global') if wants_global else ()) or ()
        if isinstance(action, dict)
    ]
    governed_keys = set()
    if personal_actions and settings.get('allow_user_plugins') and settings.get('enable_user_workspace', True):
        eligible = [action for action in personal_actions if _eligible_record(action, 'personal', user_id)]
        governed = readers['govern'](user_id, 'personal', eligible) or ()
        governed_keys.update(('personal', action.get('id')) for action in governed if isinstance(action, dict))
    if global_actions:
        eligible = [action for action in global_actions if _eligible_record(action, 'global', 'global')]
        governed = readers['govern'](user_id, 'global', eligible) or ()
        governed_keys.update(('global', action.get('id')) for action in governed if isinstance(action, dict))
    personal_pool = [('personal', action) for action in personal_actions]
    global_pool = [('global', action) for action in global_actions]

    entries = []
    for agent, is_global in sorted(
        candidates,
        key=lambda item: (item[1], str(item[0].get('display_name') or item[0].get('name') or '').casefold(),
                          str(item[0].get('id'))),
    ):
        runtime_pool = global_pool if is_global else [*personal_pool, *(global_pool if merge_global else ())]
        try:
            profile = _agent_profile(agent, runtime_pool, governed_keys)
        except (ValueError, TypeError, AttributeError, KeyError):
            # A run would fail to resolve this agent's actions too, so it is not offered.
            continue
        agent_id = _record_id(agent.get('id'))
        stored_name = str(agent.get('name') or '').strip()
        label = (
            clean_catalog_text(agent.get('display_name'), NAME_MAX_LENGTH)
            or clean_catalog_text(stored_name, NAME_MAX_LENGTH) or 'Agent'
        )
        handle = workflow_handle('agents', f"{'global' if is_global else 'personal'}:{agent_id}", label, taken)
        record = {'id': agent_id, 'is_global': is_global}
        if stored_name:
            record['name'] = stored_name
        entries.append({
            'entry': {
                'handle': handle,
                'name': label,
                'description': clean_catalog_text(agent.get('description'), AGENT_DESCRIPTION_MAX_LENGTH),
                'action_kinds': profile['action_kinds'],
                'actions': profile['actions'],
            },
            'record': record,
            'capabilities': {
                'action_kinds': profile['action_kinds'],
                'm365_sources': profile['m365_sources'],
                'can_send': profile['can_send'],
                'needs_run_as': profile['needs_run_as'],
            },
        })
        if len(entries) >= CATALOG_MAX_AGENTS:
            break
    return entries


# ---------------------------------------------------------------------------
# File Sync sources, documents and existing workflows
# ---------------------------------------------------------------------------

def _source_entries(user_id, settings, user_info, readers, taken):
    entries = []
    seen = set()
    for source in readers['sources'](user_id, settings, user_info) or ():
        if not isinstance(source, dict) or source.get('enabled') is False:
            continue
        scope_type = source.get('scope_type')
        scope_id = _record_id(source.get('scope_id'))
        source_id = _record_id(source.get('source_id'))
        if scope_type not in WORKFLOW_SCOPE_TYPES or not scope_id or not source_id:
            continue
        if scope_type == 'personal' and scope_id != user_id:
            continue
        key = f'{scope_type}:{scope_id}:{source_id}'
        if key in seen:
            continue
        seen.add(key)
        name = clean_catalog_text(source.get('name'), NAME_MAX_LENGTH) or 'File Sync source'
        entries.append({
            'entry': {
                'handle': workflow_handle('sources', key, name, taken),
                'name': name,
                'source_type': clean_catalog_text(source.get('source_type'), SOURCE_TYPE_MAX_LENGTH),
                'scope': scope_type,
            },
            'record': {'scope_type': scope_type, 'scope_id': scope_id, 'source_id': source_id},
            'key': key,
        })
        if len(entries) >= CATALOG_MAX_SOURCES:
            break
    return entries


def workflow_planning_documents(source_scopes, labels=None, selected_ids=()):
    """The documents the user named in this turn, in their order, for the document catalog.

    Only the documents the user picked or referenced with ``#`` (the turn's ``document_ids`` seed)
    are offered: never a document the candidate probe found by searching, and never a workspace
    listing. ``source_scopes`` is the map ``enrich_planner_candidates`` filled from its current
    authority check, so a named document that failed it is left out; ``labels`` are the
    candidates' display names.
    """
    source_scopes = source_scopes if isinstance(source_scopes, dict) else {}
    labels = labels if isinstance(labels, dict) else {}
    named = [value for value in selected_ids or () if isinstance(value, str) and value in source_scopes]
    documents = []
    for document_id in dict.fromkeys(named):
        scope = source_scopes.get(document_id)
        if not isinstance(scope, dict):
            continue
        documents.append({
            'document_id': document_id,
            'scope': scope.get('scope'),
            'scope_id': scope.get('scope_id'),
            'name': labels.get(document_id) or scope.get('file_name'),
        })
    return documents


def _document_entries(user_id, documents, taken):
    entries = []
    seen = set()
    for document in documents or ():
        if not isinstance(document, dict):
            continue
        document_id = _record_id(document.get('document_id'), DOCUMENT_ID_MAX_LENGTH)
        scope_type = document.get('scope')
        scope_id = _record_id(document.get('scope_id'))
        if not document_id or scope_type not in WORKFLOW_SCOPE_TYPES or not scope_id:
            continue
        # A personal workflow can name the user's own personal documents, not ones shared with them.
        if scope_type == 'personal' and scope_id != user_id:
            continue
        key = f'{scope_type}:{scope_id}:{document_id}'
        if key in seen:
            continue
        seen.add(key)
        name = clean_catalog_text(document.get('name'), DOCUMENT_NAME_MAX_LENGTH) or 'Document'
        entries.append({
            'entry': {'handle': workflow_handle('documents', key, name, taken), 'name': name},
            'record': {'document_id': document_id, 'scope_type': scope_type, 'scope_id': scope_id},
        })
        if len(entries) >= CATALOG_MAX_DOCUMENTS:
            break
    return entries


def _trigger_summary(trigger_type, schedule):
    trigger = str(trigger_type or 'manual').strip().lower()
    if trigger == 'manual':
        return 'Manual'
    label = workflow_schedule_label(trigger, schedule)
    if trigger == 'file_sync':
        return label or 'Monitor File Sync'
    if trigger == 'interval':
        return label or 'Scheduled'
    return 'Unknown trigger'


def _workflow_source_keys(workflow):
    config = workflow.get('file_sync') if isinstance(workflow.get('file_sync'), dict) else {}
    keys = []
    for source in config.get('sources') if isinstance(config.get('sources'), list) else ():
        if isinstance(source, dict):
            keys.append(f"{source.get('scope_type')}:{source.get('scope_id')}:{source.get('source_id')}")
    return keys


def _match_text(value):
    """Casefolded text with whitespace runs collapsed, for finding a workflow's name in a request."""
    if not isinstance(value, str):
        return ''
    return ' '.join(_TEXT_NOISE.sub(' ', unicodedata.normalize('NFKC', value)).split()).casefold()


def _named_by(request_text):
    """Return whether a workflow's whole name appears in ``request_text``, as a predicate."""
    text = _match_text(request_text)

    def named(workflow):
        name = _match_text(workflow.get('name'))
        if len(name) < WORKFLOW_NAME_MATCH_MIN_LENGTH or not text:
            return False
        return re.search(rf'(?<!\w){re.escape(name)}(?!\w)', text) is not None

    return named


def _workflow_entries(user_id, readers, taken, *, rank_for_runs=False, request_text=None):
    workflows = [
        workflow for workflow in readers['workflows'](user_id) or ()
        if isinstance(workflow, dict) and _record_id(workflow.get('id')) and workflow.get('deleting') is not True
    ]
    workflows.sort(
        key=lambda workflow: str(workflow.get('updated_at') or workflow.get('created_at') or ''), reverse=True,
    )
    if rank_for_runs:
        # Only the first CATALOG_MAX_WORKFLOWS can be started, so a workflow the request names comes
        # first, then durable ones; the sort is stable, so each group stays newest first.
        named = _named_by(request_text)
        workflows.sort(key=lambda workflow: (not named(workflow), workflow.get('durable_execution') is not True))
    entries = []
    for workflow in workflows[:CATALOG_MAX_WORKFLOWS]:
        workflow_id = _record_id(workflow.get('id'))
        name = clean_catalog_text(workflow.get('name'), NAME_MAX_LENGTH) or 'Workflow'
        trigger_type = str(workflow.get('trigger_type') or 'manual').strip().lower()
        entries.append({
            'entry': {
                'handle': workflow_handle('workflows', workflow_id, name, taken),
                'name': name,
                'description': clean_catalog_text(workflow.get('description'), WORKFLOW_DESCRIPTION_MAX_LENGTH),
                'trigger_summary': _trigger_summary(trigger_type, workflow.get('schedule')),
                'enabled': workflow.get('is_enabled') is True,
                'durable': workflow.get('durable_execution') is True,
            },
            'record': {'id': workflow_id},
            'snapshot': {
                'name': name,
                'trigger_type': trigger_type,
                'schedule': workflow_schedule_summary(trigger_type, workflow.get('schedule')),
                'schedule_label': workflow_schedule_label(trigger_type, workflow.get('schedule')),
                'source_keys': _workflow_source_keys(workflow),
            },
        })
    return entries


def _catalog_size(catalog):
    return len(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))


def _bounded_catalog(groups):
    """Drop the least useful entries until the planner-facing catalog fits its character budget."""
    def catalog():
        return {kind: [item['entry'] for item in items] for kind, items in groups.items()}

    for kind, floor in (('workflows', CATALOG_MIN_WORKFLOWS), ('documents', 0), ('sources', 0), ('agents', 0)):
        while len(groups[kind]) > floor and _catalog_size(catalog()) > CATALOG_MAX_CHARACTERS:
            groups[kind].pop()
    return catalog()


# ---------------------------------------------------------------------------
# The planning context
# ---------------------------------------------------------------------------

def _log_context(message, level, **fields):
    # Codes, counts and timing only: never names, descriptions or ids from the catalogs.
    log_event(f'[ORCHESTRATION_WORKFLOWS] {message}', extra={'stage': 'workflow_planning', **fields}, level=level)


def build_workflow_planning_context(settings, *, user_id, user_info, conversation, time_zone=None, now=None,
                                    documents=(), readers=None, request_text=None):
    """Build the server-only context the planner needs to propose or start a workflow this turn.

    Returns ``{'conversation_private', 'quota_reached'}`` and nothing else when neither workflow
    capability is open to this user or the conversation is not private; nothing is read in that
    case.

    For proposals, a user at the per-user cap gets ``quota_reached: True`` and no proposal
    catalogs, and a failed read sets ``context_unavailable: True``; either leaves proposals
    unavailable for the turn (they fail closed). Otherwise the context also holds:

    * ``time_zone`` and ``request_local_time``: the validated browser time zone (UTC when it is
      missing or unknown) and the current time there;
    * ``limits``: task, cadence and quota limits;
    * ``catalog``: bounded, handle-only entries for agents, File Sync sources, documents and
      existing workflows, the only part the planner sees;
    * ``handles``, ``agent_capabilities`` and ``workflow_snapshots``: the server-side maps from
      each handle to its record, what each agent can do, and existing workflows' schedules.

    When starting saved workflows is open to the user, the context also carries
    ``workflow_runs: {'ready': True}`` and at least ``catalog.workflows`` and
    ``handles.workflows``. The per-user cap limits proposals only, so a user at the cap, or one
    without proposals, still gets the workflows. They are ranked for starting: a workflow whose
    whole name appears in ``request_text`` comes first, then durable ones, each group newest
    first. A failed workflows read leaves the marker off, so starting a workflow fails closed.

    Reading the results of the user's finished workflow runs works the same way with its own
    ``workflow_results: {'ready': True}`` marker, whether or not proposals or runs are open, and it
    always carries ``time_zone`` and ``request_local_time``: a results step names the local day a
    run finished on.

    ``readers`` replaces the storage reads, for tests.
    """
    settings = settings if isinstance(settings, dict) else {}
    user_info = user_info if isinstance(user_info, dict) else {}
    private = conversation_is_private(conversation, user_id)
    context = {'conversation_private': private, 'quota_reached': None}
    if not user_id or not private:
        return context
    proposals = workflow_planning_gate(settings, user_info.get('roles')) is None
    runs = workflow_run_gate(settings, user_info.get('roles')) is None
    results = workflow_results_gate(settings, user_info.get('roles')) is None
    if not proposals and not runs and not results:
        return context

    readers = _readers(readers)
    # Starting a workflow and reading its results both name a workflow the user already has.
    names_workflows = runs or results
    if proposals:
        context = _proposal_planning_context(
            settings, context, user_id=user_id, user_info=user_info, time_zone=time_zone, now=now,
            documents=documents, readers=readers, rank_for_runs=names_workflows, request_text=request_text,
        )
        if not names_workflows:
            return context
        if workflow_planning_ready(context):
            return _with_workflow_markers(context, runs=runs, results=results, time_zone=time_zone, now=now)
    return _with_run_catalog(
        context, user_id=user_id, readers=readers, request_text=request_text,
        runs=runs, results=results, time_zone=time_zone, now=now,
    )


def _with_workflow_markers(context, *, runs, results, time_zone=None, now=None):
    """Mark which of starting and reading saved workflows the stored catalog supports.

    Reading results also needs the user's local time, which a ready proposal context already has.
    """
    markers = {}
    if runs:
        markers['workflow_runs'] = {'ready': True}
    if results:
        markers['workflow_results'] = {'ready': True}
        if not context.get('time_zone'):
            zone = resolve_turn_time_zone(time_zone)
            markers['time_zone'] = zone
            markers['request_local_time'] = request_local_time_line(zone, now)
    return {**context, **markers}


def _with_run_catalog(context, *, user_id, readers, request_text, runs=True, results=False, time_zone=None,
                      now=None):
    """Add the saved workflows a plan may start or read to a context that has no ready proposal catalog.

    Proposals may be off, unavailable to this user, at the per-user cap or unreadable; starting an
    existing workflow, or reading its results, needs only the workflows themselves. The proposal
    fields keep their meaning, so proposals stay unavailable for the same reason. A failed read
    returns ``context`` unchanged, without a marker, so both fail closed.
    """
    started = time.monotonic()
    try:
        entries = _workflow_entries(user_id, readers, set(), rank_for_runs=True, request_text=request_text)
    except Exception as exc:
        _log_context(
            'The workflows could not be read; starting a workflow is unavailable for this turn.',
            logging.WARNING, reason=WORKFLOW_REASON_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        return context
    # _bounded_catalog trims ``entries`` in place, so the handle map matches the catalog.
    workflows = _bounded_catalog({'workflows': entries, 'documents': [], 'sources': [], 'agents': []})['workflows']
    _log_context(
        'Workflow run planning context built.', logging.INFO,
        workflow_count=len(workflows), duration_ms=int((time.monotonic() - started) * 1000),
    )
    return _with_workflow_markers({
        **context,
        'catalog': {'workflows': workflows},
        'handles': {'workflows': {item['entry']['handle']: item['record'] for item in entries}},
    }, runs=runs, results=results, time_zone=time_zone, now=now)


def _proposal_planning_context(settings, context, *, user_id, user_info, time_zone, now, documents, readers,
                               rank_for_runs, request_text):
    """The proposal planning context: exactly what it was before workflow runs existed.

    ``rank_for_runs`` orders the workflows catalog for starting a workflow, and is only set when
    that is open to the user as well.
    """
    started = time.monotonic()
    try:
        quota_limit = get_chat_orchestration_max_workflows_per_user(settings)
        quota_used = int(readers['quota_count'](user_id))
    except Exception as exc:
        _log_context(
            'The workflow quota could not be read; proposals are unavailable for this turn.',
            logging.WARNING, reason=WORKFLOW_REASON_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        return {**context, 'context_unavailable': True}
    if quota_used >= quota_limit:
        return {**context, 'quota_reached': True, 'limits': {'quota_used': quota_used, 'quota_limit': quota_limit}}

    zone = resolve_turn_time_zone(time_zone)
    taken = set()
    try:
        limits = {
            'max_tasks': min(WORKFLOW_BLUEPRINT_MAX_TASKS, int(readers['max_tasks'](settings))),
            'min_interval_seconds': get_orchestration_workflow_min_interval_seconds(settings),
            'quota_used': quota_used,
            'quota_limit': quota_limit,
        }
        default_model_valid = bool(readers['default_model'](settings))
        groups = {
            'agents': _agent_entries(user_id, settings, readers, taken),
            'sources': _source_entries(user_id, settings, user_info, readers, taken),
            'documents': _document_entries(user_id, documents, taken),
            'workflows': _workflow_entries(
                user_id, readers, taken, rank_for_runs=rank_for_runs, request_text=request_text,
            ),
        }
    except Exception as exc:
        _log_context(
            'The workflow planning catalogs could not be read; proposals are unavailable for this turn.',
            logging.WARNING, reason=WORKFLOW_REASON_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        return {**context, 'context_unavailable': True}

    catalog = _bounded_catalog(groups)
    context.update({
        'quota_reached': False,
        'time_zone': zone,
        'request_local_time': request_local_time_line(zone, now),
        'limits': limits,
        'default_model_valid': default_model_valid,
        'catalog': catalog,
        'handles': {
            kind: {item['entry']['handle']: item['record'] for item in groups[kind]}
            for kind in ('agents', 'documents', 'sources', 'workflows')
        },
        'agent_capabilities': {item['entry']['handle']: item['capabilities'] for item in groups['agents']},
        'workflow_snapshots': {item['entry']['handle']: item['snapshot'] for item in groups['workflows']},
        'source_keys': {item['entry']['handle']: item['key'] for item in groups['sources']},
    })
    _log_context(
        'Workflow planning context built.', logging.INFO,
        agent_count=len(catalog['agents']), source_count=len(catalog['sources']),
        document_count=len(catalog['documents']), workflow_count=len(catalog['workflows']),
        duration_ms=int((time.monotonic() - started) * 1000),
    )
    return context


def workflow_planning_ready(context):
    """Whether a stored planning context can support a proposal in this turn."""
    return (
        isinstance(context, dict)
        and context.get('conversation_private') is True
        and context.get('quota_reached') is False
        and not context.get('context_unavailable')
        and isinstance(context.get('catalog'), dict)
        and isinstance(context.get('handles'), dict)
    )


def workflow_planning_unavailable_reason(settings, request_context):
    """Return None when this request may propose a workflow, else a closed reason. Never raises.

    ``request_context`` is the capability request context: its ``user_roles`` gate personal
    workflows, and its ``workflow_planning`` is the context stored with the turn. A context that
    is missing or could not be built fails closed, so a proposal is never offered on a guess.
    """
    try:
        request_context = request_context if isinstance(request_context, dict) else {}
        reason = workflow_planning_gate(settings, request_context.get('user_roles'))
        if reason is not None:
            return reason
        planning = request_context.get('workflow_planning')
        if not isinstance(planning, dict):
            return WORKFLOW_REASON_CONTEXT_UNAVAILABLE
        if planning.get('conversation_private') is not True:
            return WORKFLOW_REASON_SHARED_CONVERSATION
        if planning.get('quota_reached') is True:
            return WORKFLOW_REASON_QUOTA_REACHED
        if not workflow_planning_ready(planning):
            return WORKFLOW_REASON_CONTEXT_UNAVAILABLE
        return None
    except Exception as exc:
        _log_context(
            'Workflow proposal access could not be checked; proposals are unavailable for this request.',
            logging.WARNING, reason=WORKFLOW_REASON_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        return WORKFLOW_REASON_CONTEXT_UNAVAILABLE


def workflow_planner_projection(context):
    """The part of the planning context the planner may see: catalogs, limits and the time."""
    if not workflow_planning_ready(context):
        return None
    return deepcopy({
        'time_zone': context.get('time_zone') or WORKFLOW_DEFAULT_TIME_ZONE,
        'request_local_time': context.get('request_local_time') or '',
        'limits': context.get('limits') or {},
        'catalog': context.get('catalog') or {},
    })


def workflow_run_ready(context):
    """Whether a stored planning context can support starting a saved workflow in this turn."""
    if not isinstance(context, dict) or context.get('conversation_private') is not True:
        return False
    marker = context.get('workflow_runs')
    catalog = context.get('catalog')
    handles = context.get('handles')
    return (
        isinstance(marker, dict) and marker.get('ready') is True
        and isinstance(catalog, dict) and isinstance(catalog.get('workflows'), list)
        and isinstance(handles, dict) and isinstance(handles.get('workflows'), dict)
    )


def workflow_run_unavailable_reason(settings, request_context):
    """Return None when this request may start a saved workflow, else a closed reason. Never raises.

    Like ``workflow_planning_unavailable_reason``, but the per-user cap does not apply: it limits
    workflows created from chat, not runs of workflows the user already has.
    """
    try:
        request_context = request_context if isinstance(request_context, dict) else {}
        reason = workflow_run_gate(settings, request_context.get('user_roles'))
        if reason is not None:
            return reason
        planning = request_context.get('workflow_planning')
        if not isinstance(planning, dict):
            return WORKFLOW_REASON_CONTEXT_UNAVAILABLE
        if planning.get('conversation_private') is not True:
            return WORKFLOW_REASON_SHARED_CONVERSATION
        if not workflow_run_ready(planning):
            return WORKFLOW_REASON_CONTEXT_UNAVAILABLE
        return None
    except Exception as exc:
        _log_context(
            'Workflow run access could not be checked; starting a workflow is unavailable for this request.',
            logging.WARNING, reason=WORKFLOW_REASON_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        return WORKFLOW_REASON_CONTEXT_UNAVAILABLE


def workflow_run_projection(context):
    """What the planner may see to start a saved workflow: the handle-only workflows catalog."""
    if not workflow_run_ready(context):
        return None
    return deepcopy({'catalog': {'workflows': context['catalog']['workflows']}})


def workflow_results_ready(context):
    """Whether a stored planning context can support reading a saved workflow's results in this turn."""
    if not isinstance(context, dict) or context.get('conversation_private') is not True:
        return False
    marker = context.get('workflow_results')
    catalog = context.get('catalog')
    handles = context.get('handles')
    return (
        isinstance(marker, dict) and marker.get('ready') is True
        and isinstance(catalog, dict) and isinstance(catalog.get('workflows'), list)
        and isinstance(handles, dict) and isinstance(handles.get('workflows'), dict)
    )


def workflow_results_unavailable_reason(settings, request_context):
    """Return None when this request may read a saved workflow's results, else a closed reason. Never raises.

    Like ``workflow_run_unavailable_reason``, plus at least one saved workflow to name: a user with
    none has no result a plan could read.
    """
    try:
        request_context = request_context if isinstance(request_context, dict) else {}
        reason = workflow_results_gate(settings, request_context.get('user_roles'))
        if reason is not None:
            return reason
        planning = request_context.get('workflow_planning')
        if not isinstance(planning, dict):
            return WORKFLOW_REASON_CONTEXT_UNAVAILABLE
        if planning.get('conversation_private') is not True:
            return WORKFLOW_REASON_SHARED_CONVERSATION
        if not workflow_results_ready(planning):
            return WORKFLOW_REASON_CONTEXT_UNAVAILABLE
        if not planning['catalog']['workflows']:
            return WORKFLOW_RESULTS_REASON_NO_WORKFLOWS
        return None
    except Exception as exc:
        _log_context(
            'Workflow results access could not be checked; reading workflow results is unavailable for this request.',
            logging.WARNING, reason=WORKFLOW_REASON_CONTEXT_UNAVAILABLE, error_type=type(exc).__name__,
        )
        return WORKFLOW_REASON_CONTEXT_UNAVAILABLE


def workflow_results_projection(context):
    """What the planner may see to read a saved workflow's results.

    The same handle-only workflows catalog a plan may start from, and the user's local time, so the
    planner can turn "yesterday" into a date. Nothing else from the stored context.
    """
    if not workflow_results_ready(context) or not context['catalog']['workflows']:
        return None
    return deepcopy({
        'time_zone': context.get('time_zone') or WORKFLOW_DEFAULT_TIME_ZONE,
        'request_local_time': context.get('request_local_time') or '',
        'catalog': {'workflows': context['catalog']['workflows']},
    })


def workflow_answer_time_line(workflow_planning, time_zone, now=None):
    """The user's local time for an answer written in a turn that may propose a workflow, else ''.

    The wording is the line a calendar workflow's run gives each task, so an answer that previews
    a proposed workflow now resolves words such as "this week" the way the workflow's runs will.
    A turn without a ready planning context gets '', so its answers are written exactly as before.
    ``time_zone`` is the turn's validated browser zone; the planning context's zone stands in for
    it. Never raises.
    """
    if not workflow_planning_ready(workflow_planning):
        return ''
    return request_local_time_line(resolve_turn_time_zone(time_zone, workflow_planning.get('time_zone')), now)


def workflow_draft_handles(context):
    """The handle map the workflow draft service accepts: agents, documents and sources only."""
    handles = (context or {}).get('handles') if isinstance(context, dict) else None
    handles = handles if isinstance(handles, dict) else {}
    return {
        kind: deepcopy(handles.get(kind)) if isinstance(handles.get(kind), dict) else {}
        for kind in _DRAFT_HANDLE_KINDS
    }


def refresh_workflow_planning_privacy(context, conversation, user_id):
    """Return a copy of a stored planning context with its privacy re-read from the conversation."""
    if not isinstance(context, dict):
        return None
    refreshed = deepcopy(context)
    refreshed['conversation_private'] = bool(context.get('conversation_private') is True) and conversation_is_private(
        conversation, user_id,
    )
    return refreshed
