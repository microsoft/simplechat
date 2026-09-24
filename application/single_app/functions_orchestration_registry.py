# functions_orchestration_registry.py

"""
The capability registry: what a chat orchestration plan is allowed to contain.

This is the deliberate opposite of Semantic Kernel's function-calling loop. SK hands a
model every registered tool and lets it choose; with 44 plugin classes and 27 actions in
this application that is both unreliable and expensive, and it is the specific problem
this framework exists to avoid.

Instead the planner model is shown a short list of *capability descriptors* -- a dozen
sentences, not a tool catalogue -- and returns a plan naming them. It never invokes
anything. Dispatch is deterministic, in ``functions_orchestration_executor.py``, through
adapters over functions that already exist.

A descriptor is data, not code, for two reasons. Adding a capability should be a table
entry rather than a new branch in a planner prompt, and the same table is what the
validator checks a plan against, so a capability cannot be executable without also being
describable and gated.

Gating deserves a note. Three forms are supported because the real conditions in this
application are genuinely of three shapes:

- ``settings_gates`` -- every named setting must be truthy.
- ``settings_gates_any`` -- at least one must be, which is how "the user has *some*
  workspace" is expressed without contorting an AND list.
- ``gate`` -- a callable, for the conditions that are not settings lookups at all.
  Document analysis and comparison are gated by ``is_document_action_enabled``, which
  reads a nested capability record rather than a flag.

Every capability belongs to one server-owned purpose (``role``): Gather acquires sources,
Reason prepares content, and Render delivers a file. Purposes are not ordered phases; a
plan can gather, reason, and gather again. Steps exchange typed, retained results named in
their ``inputs`` and ``outputs``.

Version: 0.261.139
"""

import logging
from copy import deepcopy

from functions_appinsights import log_event
from functions_orchestration_result_contracts import (
    IMAGE_ASSET_KIND, RESULT_KINDS, ResultContractError, canonical_bytes,
)

# The schema marker every saved plan carries. A plan without it, or with the earlier value,
# was written by the removed legacy contract and is never opened or run.
DEPENDENCY_PLAN_CONTRACT_VERSION = 2
ROLE_GATHER = 'gather'
ROLE_REASON = 'reason'
ROLE_RENDER = 'render'

# Document action vocabulary, duplicated as literals rather than imported.
#
# `functions_document_actions` reaches `functions_document_analysis` and `functions_search`,
# and through them `config.py`, which builds a Cosmos client at import time. This module is
# read by the validator and by tests that have no Azure to talk to, so it stays importable
# on its own and pulls that chain in lazily inside the gate instead. The same reasoning
# produced the `_load_orchestration_helper` shim in `functions_tabular_analysis.py`.
DOCUMENT_ACTION_TYPE_ANALYZE = 'analyze'
DOCUMENT_ACTION_TYPE_COMPARISON = 'comparison'
DOCUMENT_ACTION_CONTEXT_CHAT = 'chat'

COST_CLASS_LOW = 'low'
COST_CLASS_MEDIUM = 'medium'
COST_CLASS_HIGH = 'high'

COST_CLASSES = (COST_CLASS_LOW, COST_CLASS_MEDIUM, COST_CLASS_HIGH)

# What a step leaves behind. Gather and Reason steps retain typed, named results for later
# steps; Render delivers a file through the output service instead.
PRODUCES_RETAINED_RESULTS = 'retained_results'
PRODUCES_ARTIFACTS = 'artifacts'

# Capability identifiers. Referenced by plans, adapters and tests, so they are constants
# rather than repeated string literals.
CAPABILITY_DOCUMENT_SEARCH = 'document_search'
CAPABILITY_DOCUMENT_ANALYZE = 'document_analyze'
CAPABILITY_DOCUMENT_COMPARE = 'document_compare'
CAPABILITY_TABULAR_ANALYZE = 'tabular_analyze'
CAPABILITY_WEB_SEARCH = 'web_search'
CAPABILITY_URL_FETCH = 'url_fetch'
CAPABILITY_DEEP_RESEARCH = 'deep_research'
CAPABILITY_AGENT_INVOKE = 'agent_invoke'
CAPABILITY_ACTION_INVOKE = 'action_invoke'
CAPABILITY_COMPOSE = 'compose'
CAPABILITY_GENERATE_IMAGE = 'generate_image'
CAPABILITY_RENDER_FILE = 'render_file'

# Explicitly requested images are generated as planned steps. The executor is serial, so a
# plan may generate at most this many images; a larger ask is reported, never silently cut.
MAX_GENERATED_IMAGES_PER_PLAN = 4
# Characters the planner may spend on an image prompt; named text inputs may add visual
# details up to the image service's own prompt limit.
GENERATE_IMAGE_PROMPT_MAX_LENGTH = 3000

# What an answer-writing step may rely on. The planner declares one per compose step; the
# step's policy follows it. Stable, widely established facts can come from the model's own
# knowledge, while time-sensitive, local, private or source-specific facts need sources.
KNOWLEDGE_BASIS_GENERAL = 'general_knowledge'
KNOWLEDGE_BASIS_SOURCES = 'sources'
KNOWLEDGE_BASIS_MIXED = 'sources_and_general_knowledge'
KNOWLEDGE_BASES = (KNOWLEDGE_BASIS_GENERAL, KNOWLEDGE_BASIS_SOURCES, KNOWLEDGE_BASIS_MIXED)
GENERAL_KNOWLEDGE_BASES = (KNOWLEDGE_BASIS_GENERAL, KNOWLEDGE_BASIS_MIXED)

# Visual output kinds a planned step can be asked to author, named by the planner rather than
# guessed from keywords in the request.
VISUAL_CHART = 'chart'
VISUAL_DIAGRAM = 'diagram'
VISUAL_IMAGE_PROPOSAL = 'image_proposal'
VISUAL_KINDS = (VISUAL_CHART, VISUAL_DIAGRAM, VISUAL_IMAGE_PROPOSAL)

# Workspace scopes a capability may need at least one of.
SCOPE_PERSONAL = 'personal'
SCOPE_GROUP = 'group'
SCOPE_PUBLIC = 'public'

# The settings key behind each workspace scope, used to answer "does this deployment have
# anywhere for documents to live at all".
WORKSPACE_SCOPE_SETTINGS = {
    SCOPE_PERSONAL: 'enable_user_workspace',
    SCOPE_GROUP: 'enable_group_workspaces',
    SCOPE_PUBLIC: 'enable_public_workspaces',
}


class CapabilityResolutionError(RuntimeError):
    """Capability access could not be checked, rather than being denied."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


def required_capability_ids(seeds):
    """Read positive selections without treating unchecked controls as restrictions."""
    seeds = seeds or {}
    values = seeds.get('required_capabilities') or []
    if not isinstance(values, (list, tuple, set)):
        raise ValueError('Capability selections must be a list.')
    required = [value.strip() for value in values if isinstance(value, str) and value.strip()]
    if seeds.get('web_search') is True:
        required.append(CAPABILITY_WEB_SEARCH)
    if isinstance(seeds.get('agent'), dict) and seeds['agent'].get('name'):
        required.append(CAPABILITY_AGENT_INVOKE)
    return list(dict.fromkeys(required))


def _document_action_gate(action_type):
    """Build a gate for a document action, whose enablement is a nested record."""

    def _gate(settings):
        try:
            from functions_document_actions import is_document_action_enabled

            return bool(is_document_action_enabled(action_type, settings=settings))
        except Exception as exc:
            log_event(
                '[ORCHESTRATION_REGISTRY] Could not check document action availability.',
                level=logging.WARNING,
                extra={'reason': 'capability_check_failed', 'error_type': type(exc).__name__},
            )
            raise CapabilityResolutionError('Document capabilities could not be checked.') from exc

    return _gate


# --------------------------------------------------------------------------------------
# Request-level gates
# --------------------------------------------------------------------------------------
#
# Separate from the settings gates above, and the separation matters. A settings gate asks
# "has this deployment configured the capability at all", which is what the admin page and
# the bootstrap payload need to know. A request gate asks "may *this* request use it", which
# depends on the caller's app roles and on what they actually typed.
#
# Collapsing the two would break both surfaces: the admin Capabilities list would hide a
# capability the deployment plainly has because the current request has no URL in it, and
# the planner would be offered capabilities the caller has no role for. So request gates run
# only when a request context is supplied, and the deployment view never sees them.
#
# Every one of these fails CLOSED. `user_roles` reaches the executor's worker thread by being
# captured in the request and carried on the run context; if that plumbing ever breaks, the
# roles arrive as None, and a gate that treated None as "no restriction" would quietly hand
# every user a capability their app role was meant to withhold.


def _url_access_request_gate(settings, context):
    """Whether this caller may read URLs, and whether there are any to read."""
    try:
        from functions_source_review import is_url_access_enabled_for_user

        if not is_url_access_enabled_for_user(settings, user_roles=context.get('user_roles')):
            return False
    except Exception as exc:
        log_event(
            '[ORCHESTRATION_REGISTRY] Could not check URL access.',
            level=logging.WARNING,
            extra={'reason': 'capability_check_failed', 'error_type': type(exc).__name__},
        )
        raise CapabilityResolutionError('URL access could not be checked.') from exc

    # Offering "read URLs" when the message contains none invites a step that can only
    # report having nothing to do. The classic composer hides the button on the same
    # condition; expressing it here means the rule lives with the capability rather than
    # being restated in the browser.
    return bool(context.get('message_urls'))


def _deep_research_request_gate(settings, context):
    """Whether this caller may run a deep research crawl."""
    try:
        from functions_source_review import is_source_review_enabled_for_user

        return bool(is_source_review_enabled_for_user(
            settings,
            context.get('user_id'),
            user_email=context.get('user_email'),
            user_roles=context.get('user_roles'),
        ))
    except Exception as exc:
        log_event(
            '[ORCHESTRATION_REGISTRY] Could not check Deep Research access.',
            level=logging.WARNING,
            extra={'reason': 'capability_check_failed', 'error_type': type(exc).__name__},
        )
        raise CapabilityResolutionError('Deep Research access could not be checked.') from exc


def _agent_request_gate(settings, context):
    """Whether this caller has an agent to invoke.

    Agents are per-user in a way the other capabilities are not: the deployment can have
    Semantic Kernel on while a given user has agents switched off in their own settings, or
    simply has none they can reach. Offering the capability in either case produces plans
    naming agents that cannot run.
    """
    if not context.get('user_enable_agents', True):
        return False
    return bool(context.get('agent_catalog'))


def _action_request_gate(settings, context):
    return bool(context.get('action_catalog'))


def resolve_admitted_export_catalog(export_catalog=None):
    """Narrow real shared format/profile declarations without redefining a renderer."""
    # The shared export registry is read only when render work is actually resolved.
    from functions_generated_export_registry import get_generated_file_export_catalog

    current = get_generated_file_export_catalog()
    if export_catalog is None:
        return current
    known = {entry['format_id']: entry for entry in current}
    selected = {}
    try:
        if type(export_catalog) is not list:
            raise ValueError('Invalid catalog.')
        for entry in export_catalog:
            if type(entry) is not dict or type(entry.get('format_id')) is not str:
                raise ValueError('Invalid format.')
            format_id = entry['format_id']
            if format_id not in known or format_id in selected or type(entry.get('profiles')) is not list:
                raise ValueError('Unknown or duplicate format.')
            supplied_fields = {key: value for key, value in entry.items() if key != 'profiles'}
            shared_fields = {key: value for key, value in known[format_id].items() if key != 'profiles'}
            if canonical_bytes(supplied_fields) != canonical_bytes(shared_fields):
                raise ValueError('Changed format definition.')
            profiles = {profile['profile']: profile for profile in known[format_id]['profiles']}
            selected[format_id] = set()
            for profile in entry['profiles']:
                if type(profile) is not dict or type(profile.get('profile')) is not str:
                    raise ValueError('Invalid profile.')
                profile_id = profile['profile']
                if (
                    profile_id not in profiles or profile_id in selected[format_id]
                    or canonical_bytes(profile) != canonical_bytes(profiles[profile_id])
                ):
                    raise ValueError('Unknown, duplicate or changed profile.')
                selected[format_id].add(profile_id)
    except (ValueError, ResultContractError) as exc:
        log_event(
            '[ORCHESTRATION_REGISTRY] Invalid admitted export catalog.',
            level=logging.WARNING, extra={'error_type': type(exc).__name__},
        )
        raise CapabilityResolutionError('The admitted export catalog is invalid.') from exc
    return [
        {
            **entry,
            'profiles': [
                profile for profile in entry['profiles'] if profile['profile'] in selected[entry['format_id']]
            ],
        }
        for entry in current if selected.get(entry['format_id'])
    ]


def admitted_export_pairs(export_catalog=None):
    """Return exact admitted identities after checking the shared exporter definitions."""
    return frozenset(
        (entry['format_id'], profile['profile'])
        for entry in resolve_admitted_export_catalog(export_catalog) for profile in entry['profiles']
    )


def render_file_arguments_schema(catalog):
    """Project the real format/profile option contracts without inventing a format."""
    return {
        'type': 'object',
        'properties': {
            'file_name': {'type': 'string', 'minLength': 1, 'maxLength': 200},
            'output_format': {'type': 'string', 'enum': [entry['format_id'] for entry in catalog]},
            'profile': {'type': 'string', 'minLength': 1},
            'options': {'type': 'object'},
        },
        'required': ['file_name', 'output_format', 'profile'],
        'additionalProperties': False,
        'oneOf': [
            {
                'properties': {
                    'output_format': {'const': entry['format_id']},
                    'profile': {'const': profile['profile']},
                    'options': deepcopy(profile['options_schema']),
                },
                'required': ['options'] if profile['required_options'] else [],
            }
            for entry in catalog for profile in entry['profiles']
        ],
    }


def generate_image_arguments_schema(options=None):
    """Image step arguments; options, when known, are the configured model's exact values."""
    properties = {
        'prompt': {
            'type': 'string', 'minLength': 1, 'maxLength': GENERATE_IMAGE_PROMPT_MAX_LENGTH,
            'description': (
                'A self-contained image prompt: subject, setting, composition, style, and any text '
                'the image shows. Ask for an illustration, not a photograph.'
            ),
        },
        'title': {
            'type': 'string', 'minLength': 1, 'maxLength': 120,
            'description': 'A short caption naming what the illustration shows.',
        },
    }
    for name, plural in (('size', 'sizes'), ('quality', 'qualities'), ('background', 'backgrounds')):
        if options is None:
            properties[name] = {'type': 'string', 'minLength': 1}
        elif options.get(plural):
            properties[name] = {'type': 'string', 'enum': list(options[plural])}
    return {
        'type': 'object', 'properties': properties,
        'required': ['prompt', 'title'], 'additionalProperties': False,
    }


# Everything an external Gather step needs from the running application before it may run.
# They are request-time callables, so a capability is offered only when all are present.
_EXTERNAL_GATHER_BINDINGS = (
    'external_source_admission', 'external_source_preflight', 'capture_external_source_configuration',
    'external_source_authorizer',
)
_EXTERNAL_GATHER_UNAVAILABLE_REASON = 'external_result_lineage_unavailable'
_GATHERED_CONTENT_CONTRACT = 'orchestration-gathered-content-v1'
_NARRATIVE_ONLY_NOTE = (
    ' This step reads narrative documents; native tabular handoff is not admitted.'
)


# The registry itself, in the order a plan tends to read: gather, then reason, then render.
#
# `when_to_use` is the free text the planner is shown per capability, so it is written as
# guidance to a reader deciding between options rather than as a restatement of the label.
# `inputs` is a JSON Schema fragment, and is what the validator enforces -- a plan whose
# arguments do not satisfy it never reaches an adapter. `result_outputs` are the typed,
# named results a step retains for later steps. The parts owned by other services -- the
# native tabular argument contract and the export catalog -- are resolved by
# `_build_capabilities` when the registry is read, so importing this module stays cheap.
CAPABILITY_REGISTRY = (
    {
        'id': CAPABILITY_DOCUMENT_SEARCH,
        'label': 'Search documents',
        'role': ROLE_GATHER,
        'request_gate': None,
        'summary': "Find relevant passages across the documents this user can read.",
        'when_to_use': (
            "The question asks about information likely held in the user's own documents, "
            "and no particular document has been named. Prefer this over analysing a whole "
            "document when a few passages would answer the question."
        ),
        'settings_gates': (),
        'settings_gates_any': (
            'enable_user_workspace',
            'enable_group_workspaces',
            'enable_public_workspaces',
        ),
        'gate': None,
        'requires_scope': (SCOPE_PERSONAL, SCOPE_GROUP, SCOPE_PUBLIC),
        'inputs': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'The search phrasing, which need not match the user wording.',
                },
                'document_ids': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': 'Restrict to these documents. Omit to search everything in scope.',
                },
                'doc_scope': {
                    'type': 'string',
                    'enum': ['all', 'personal', 'group', 'public'],
                    'default': 'all',
                },
                'top_n': {'type': 'integer', 'minimum': 1, 'maximum': 50, 'default': 12},
            },
            'required': ['query'],
            'additionalProperties': False,
        },
        'result_contract_version': _GATHERED_CONTENT_CONTRACT,
        'result_outputs': {
            'evidence': 'evidence-set-v1', 'sources': 'source-set-v1', 'prepared': 'structured-v1',
        },
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 3,
        'adapter': CAPABILITY_DOCUMENT_SEARCH,
        # Read-only and idempotent: one bounded retry on a transient provider failure.
        'retry_on_transient': True,
    },
    {
        'id': CAPABILITY_DOCUMENT_ANALYZE,
        'label': 'Analyse documents',
        'role': ROLE_REASON,
        'request_gate': None,
        'summary': "Read one or more documents end to end and answer a question about them.",
        'when_to_use': (
            "The question needs whole-document coverage rather than a few passages -- "
            "summarising, extracting every instance of something, or answering where a "
            "search would miss material. Considerably more expensive than searching."
            + _NARRATIVE_ONLY_NOTE
        ),
        'settings_gates': (),
        'settings_gates_any': (),
        'gate': _document_action_gate(DOCUMENT_ACTION_TYPE_ANALYZE),
        'requires_scope': (SCOPE_PERSONAL, SCOPE_GROUP, SCOPE_PUBLIC),
        'inputs': {
            'type': 'object',
            'properties': {
                'analysis_prompt': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'What to determine from each document.',
                },
                'document_ids': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'minItems': 1,
                    'description': 'The documents to read. Must be named explicitly.',
                },
                'doc_scope': {
                    'type': 'string',
                    'enum': ['all', 'personal', 'group', 'public'],
                    'default': 'all',
                },
            },
            'required': ['analysis_prompt'],
            'additionalProperties': False,
        },
        'result_contract_version': 'analyze-final-v1',
        'result_outputs': {'findings': 'records-v1', 'coverage': 'structured-v1'},
        'optional_result_outputs': {'records': 'records-v1', 'report': 'markdown-v1'},
        # Documents a search found can be read by binding its source set by name.
        'result_input_kinds': {'sources': ('source-set-v1',)},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_HIGH,
        'max_per_plan': 2,
        'adapter': CAPABILITY_DOCUMENT_ANALYZE,
        # Enforced by the validator against the administrator's chat limit.
        'document_action_type': DOCUMENT_ACTION_TYPE_ANALYZE,
    },
    {
        'id': CAPABILITY_DOCUMENT_COMPARE,
        'label': 'Compare documents',
        'role': ROLE_REASON,
        'request_gate': None,
        'summary': "Compare one document against one or more others.",
        'when_to_use': (
            "The question is explicitly comparative -- what changed, how two versions "
            "differ, which of several documents says something. Needs a single left-hand "
            "document and at least one to compare it against."
            + _NARRATIVE_ONLY_NOTE
        ),
        'settings_gates': (),
        'settings_gates_any': (),
        'gate': _document_action_gate(DOCUMENT_ACTION_TYPE_COMPARISON),
        'requires_scope': (SCOPE_PERSONAL, SCOPE_GROUP, SCOPE_PUBLIC),
        'inputs': {
            'type': 'object',
            'properties': {
                'comparison_prompt': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'What the comparison should establish.',
                },
                'left_document_id': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'The document the others are compared against.',
                },
                'right_document_ids': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'minItems': 1,
                },
                'doc_scope': {
                    'type': 'string',
                    'enum': ['all', 'personal', 'group', 'public'],
                    'default': 'all',
                },
            },
            'required': ['comparison_prompt', 'left_document_id', 'right_document_ids'],
            'additionalProperties': False,
        },
        'result_contract_version': 'comparison-v1',
        'result_outputs': {'comparison': 'comparison-v1', 'coverage': 'structured-v1'},
        'optional_result_outputs': {'report': 'markdown-v1'},
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_HIGH,
        'max_per_plan': 1,
        'adapter': CAPABILITY_DOCUMENT_COMPARE,
        'document_action_type': DOCUMENT_ACTION_TYPE_COMPARISON,
    },
    {
        'id': CAPABILITY_TABULAR_ANALYZE,
        'label': 'Analyse spreadsheets',
        'role': ROLE_REASON,
        'request_gate': None,
        'summary': "Compute over CSV or Excel data rather than reading it as prose.",
        'when_to_use': (
            'Compute over exactly one authorized replayable CSV or workbook without publishing files. '
            'Query requires a row-local query_expression and explicit columns; transformations require '
            'an executable transformation_spec or explicit schema. Analysis-only returns analysis, '
            'not implicit source rows. Declare exactly the selected result_output_variants outputs. '
            'Mixed/multiple sources and bare prose aggregate plans are unsupported.'
        ),
        'settings_gates': (),
        'settings_gates_any': (
            'enable_user_workspace',
            'enable_group_workspaces',
            'enable_public_workspaces',
        ),
        'gate': None,
        'requires_scope': (SCOPE_PERSONAL, SCOPE_GROUP, SCOPE_PUBLIC),
        # The native computation contract owns these arguments; see `_build_capabilities`.
        'inputs': None,
        'runtime_binding': 'native_bridge_for_step',
        'runtime_binding_unavailable_reason': 'native_typed_result_bridge_unavailable',
        'result_contract_version': 'native-tabular-result-v1',
        'result_outputs': {'coverage': 'structured-v1'},
        'optional_result_outputs': {'records': 'records-v1', 'analysis': 'structured-v1'},
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_MEDIUM,
        'max_per_plan': 2,
        'adapter': CAPABILITY_TABULAR_ANALYZE,
    },
    {
        'id': CAPABILITY_WEB_SEARCH,
        'label': 'Search the web',
        'role': ROLE_GATHER,
        'request_gate': None,
        'summary': "Look the question up on the public web.",
        'when_to_use': (
            "Use for focused external lookups, current facts, or limited discovery that "
            "search results can adequately support. One search can return several sources; "
            "that alone does not require deep research. Do not use it to answer questions "
            "about the user's own material."
        ),
        'settings_gates': ('enable_web_search',),
        'settings_gates_any': (),
        'gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'minLength': 1},
            },
            'required': ['query'],
            'additionalProperties': False,
        },
        'runtime_bindings': _EXTERNAL_GATHER_BINDINGS,
        'runtime_binding_unavailable_reason': _EXTERNAL_GATHER_UNAVAILABLE_REASON,
        'result_contract_version': _GATHERED_CONTENT_CONTRACT,
        'result_outputs': {'prepared': 'structured-v1'},
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 2,
        'adapter': CAPABILITY_WEB_SEARCH,
        'retry_on_transient': True,
    },
    {
        'id': CAPABILITY_URL_FETCH,
        'label': 'Read linked pages',
        'role': ROLE_GATHER,
        'request_gate': _url_access_request_gate,
        'summary': "Read the web pages the user linked to in their message.",
        'when_to_use': (
            "The user pasted one or more links and is asking about what they contain. This "
            "reads those pages and nothing else -- it does not search, so use web search "
            "when the question needs sources the user has not already named."
        ),
        'settings_gates': ('enable_url_access',),
        'settings_gates_any': (),
        'gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {
                'urls': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'description': (
                        'Restrict to these links. Omit to read every link in the message. '
                        'Only links the user actually pasted can be read.'
                    ),
                },
            },
            'required': [],
            'additionalProperties': False,
        },
        'runtime_bindings': _EXTERNAL_GATHER_BINDINGS,
        'runtime_binding_unavailable_reason': _EXTERNAL_GATHER_UNAVAILABLE_REASON,
        'result_contract_version': _GATHERED_CONTENT_CONTRACT,
        'result_outputs': {'prepared': 'structured-v1'},
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 1,
        'adapter': CAPABILITY_URL_FETCH,
        'retry_on_transient': True,
    },
    {
        'id': CAPABILITY_DEEP_RESEARCH,
        'label': 'Research in depth',
        'role': ROLE_GATHER,
        'request_gate': _deep_research_request_gate,
        'summary': "Discover sources with bounded web queries, then read and follow relevant pages.",
        'when_to_use': (
            "Use when exploring distinct perspectives or alternatives, reading sources in "
            "detail, or reconciling evidence would materially improve the answer enough to "
            "justify the added cost. Prefer focused web search when that coverage is "
            "sufficient. Includes its own bounded multi-query discovery, so a separate web "
            "search should not duplicate it. Discovery respects web-search settings; when "
            "web search is disabled, only supplied or already discovered sources can be read."
        ),
        'settings_gates': ('enable_source_review',),
        'settings_gates_any': (),
        'gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {
                'query': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'What to establish. Phrase it as the question to answer.',
                },
            },
            'required': ['query'],
            'additionalProperties': False,
        },
        'runtime_bindings': _EXTERNAL_GATHER_BINDINGS,
        'runtime_binding_unavailable_reason': _EXTERNAL_GATHER_UNAVAILABLE_REASON,
        'result_contract_version': _GATHERED_CONTENT_CONTRACT,
        'result_outputs': {'prepared': 'structured-v1'},
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_HIGH,
        'max_per_plan': 1,
        'adapter': CAPABILITY_DEEP_RESEARCH,
        'retry_on_transient': True,
    },
    {
        'id': CAPABILITY_ACTION_INVOKE,
        'label': 'Use an action',
        'role': ROLE_GATHER,
        'request_gate': _action_request_gate,
        'summary': "Gather knowledge using one of this user's accessible actions.",
        'when_to_use': (
            "An action in the list reaches the information needed for this task. Prefer "
            "using it directly when no agent-specific instructions or knowledge are needed. "
            "The step can use the selected action's functions within execution limits. "
            "Do not duplicate work delegated to an agent or use this to plan output tasks."
        ),
        'settings_gates': (
            'enable_chat_orchestration',
            'enable_semantic_kernel',
            'enable_chat_orchestration_actions',
        ),
        'settings_gates_any': (),
        'gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {
                'action_ref': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'The exact scoped reference from the actions catalog.',
                },
                'task': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'The knowledge to gather with this action.',
                },
                'visuals': {
                    'type': 'array', 'items': {'type': 'string', 'enum': [VISUAL_CHART]},
                    'uniqueItems': True, 'maxItems': 1,
                    'description': (
                        'Include "chart" to have this step chart the exact rows its functions '
                        'return. The chart is drawn from the retrieved data, not from the prose findings.'
                    ),
                },
            },
            'required': ['action_ref', 'task'],
            'additionalProperties': False,
        },
        'runtime_bindings': _EXTERNAL_GATHER_BINDINGS,
        'runtime_binding_unavailable_reason': _EXTERNAL_GATHER_UNAVAILABLE_REASON,
        'result_contract_version': _GATHERED_CONTENT_CONTRACT,
        'result_outputs': {'prepared': 'structured-v1'},
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_MEDIUM,
        'max_per_plan': None,
        'adapter': CAPABILITY_ACTION_INVOKE,
    },
    {
        'id': CAPABILITY_AGENT_INVOKE,
        'label': 'Ask an agent',
        'role': ROLE_GATHER,
        'request_gate': _agent_request_gate,
        'summary': "Hand the task to one of this user's configured agents.",
        'when_to_use': (
            "An agent in the list has tools or knowledge built for exactly this task -- "
            "reaching a system none of the other capabilities can, or following a procedure "
            "somebody configured deliberately. Name only an agent from the list. An agent "
            "runs its own tools, so do not also plan the work it would do itself."
        ),
        'settings_gates': ('enable_semantic_kernel',),
        'settings_gates_any': (),
        'gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {
                'agent_name': {
                    'type': 'string',
                    'minLength': 1,
                    'description': "The agent's name, exactly as it appears in the list.",
                },
                'task': {
                    'type': 'string',
                    'minLength': 1,
                    'description': 'What to ask the agent to do, in a sentence or two.',
                },
                'visuals': {
                    'type': 'array', 'items': {'type': 'string', 'enum': list(VISUAL_KINDS)},
                    'uniqueItems': True, 'maxItems': len(VISUAL_KINDS),
                    'description': (
                        'Visuals the answer will include, so the agent keeps the values, '
                        'relationships or visual details they need.'
                    ),
                },
            },
            'required': ['agent_name', 'task'],
            'additionalProperties': False,
        },
        'runtime_bindings': _EXTERNAL_GATHER_BINDINGS,
        'runtime_binding_unavailable_reason': _EXTERNAL_GATHER_UNAVAILABLE_REASON,
        'result_contract_version': _GATHERED_CONTENT_CONTRACT,
        'result_outputs': {'prepared': 'structured-v1'},
        'result_input_kinds': {},
        'partial_inputs_supported': False,
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_HIGH,
        # One per plan. Every agent step loads a kernel from scratch -- resolving Key Vault
        # secrets, hydrating each plugin the agent declares, introspecting SQL and Cosmos
        # schemas -- and there is no live kernel cache to amortise it. Two agent steps means
        # paying all of that twice.
        'max_per_plan': 1,
        'adapter': CAPABILITY_AGENT_INVOKE,
    },
    {
        'id': CAPABILITY_COMPOSE,
        'label': 'Prepare content',
        'role': ROLE_REASON,
        'result_contract_version': 'compose-v1',
        'summary': 'Compose reusable text, Markdown, records, or structured content.',
        'when_to_use': (
            'Explicitly draft an answer or report, or prepare structured data. Bind every '
            'retained input by name. Source-free content is supported. This does not create '
            'files, infer a file format, retrieve sources, or call tools. Declare each output '
            'and select final_response when its text should become the chat answer. Set '
            'knowledge_basis: general_knowledge for stable, widely known facts that need no '
            'retrieval; sources when every claim must come from the named inputs (private '
            'documents, current or local facts); sources_and_general_knowledge when named inputs '
            'lead but stable general knowledge may fill gaps. Mark an input optional only when '
            'the answer can still be written from general knowledge if that input fails. Name '
            'the visuals the Markdown answer should author: chart, diagram (Mermaid), or '
            'image_proposal (cards the user approves before generation). Place bound '
            'generate_image outputs with [[image:<step_id>]] tokens in Markdown, or as '
            '"asset:<step_id>" image sources in a prepared slide deck.'
        ),
        'settings_gates': (),
        'settings_gates_any': (),
        'gate': None,
        'request_gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {
                'instruction': {'type': 'string', 'minLength': 1},
                'knowledge_basis': {'type': 'string', 'enum': list(KNOWLEDGE_BASES)},
                'visuals': {
                    'type': 'array', 'items': {'type': 'string', 'enum': list(VISUAL_KINDS)},
                    'uniqueItems': True, 'maxItems': len(VISUAL_KINDS),
                },
            },
            'required': ['instruction'],
            'additionalProperties': False,
        },
        'result_input_kinds': {'*': tuple(sorted(RESULT_KINDS))},
        'partial_inputs_supported': True,
        'optional_inputs_supported': True,
        'result_outputs': {},
        'result_output_kinds': ('text-v1', 'markdown-v1', 'records-v1', 'structured-v1'),
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': None,
        'adapter': CAPABILITY_COMPOSE,
    },
    {
        'id': CAPABILITY_GENERATE_IMAGE,
        'label': 'Generate image',
        'role': ROLE_REASON,
        'result_contract_version': 'generate-image-v1',
        'summary': 'Generate one new AI illustration and keep it for the answer and for DOCX, PDF, or PPTX files.',
        'when_to_use': (
            'Use one step for each image the user explicitly asked for, including through the Image '
            'control. The result is a new AI-generated illustration, never a photograph or a picture '
            'found on the web: for a real person or historical figure, ask for an illustrated portrait '
            'and caption it as an AI illustration. Bind the "image" output to the compose step that '
            'writes the answer or file content, as an optional named input, so the answer and any '
            'DOCX, PDF, or PPTX file include it. Named text inputs may add visual details to the '
            'prompt. Images the user did not ask for stay image proposal cards on compose.'
        ),
        'settings_gates': ('enable_image_generation',),
        'settings_gates_any': (),
        'gate': None,
        'request_gate': None,
        'requires_scope': (),
        'runtime_readiness': 'image_generation',
        'inputs': generate_image_arguments_schema(),
        'result_input_kinds': {'*': ('text-v1', 'markdown-v1')},
        'partial_inputs_supported': False,
        'result_outputs': {'image': IMAGE_ASSET_KIND},
        'produces': (PRODUCES_RETAINED_RESULTS,),
        'cost_class': COST_CLASS_HIGH,
        'max_per_plan': MAX_GENERATED_IMAGES_PER_PLAN,
        'adapter': CAPABILITY_GENERATE_IMAGE,
        # Persisting the image is this step's approved output, so it may publish one chat
        # image like Render publishes a file. It runs no tools; any other file fails closed.
        'publishes_generated_images': True,
    },
)

_RENDER_SOURCE_KINDS = {
    'records-v1': 'records', 'text-v1': 'text', 'markdown-v1': 'markdown',
    'structured-v1': 'structured_value', 'comparison-v1': 'structured_value',
}


def _resolve_descriptor(descriptor):
    """One registered descriptor with the parts another service owns filled in."""
    capability = deepcopy(descriptor)
    capability['plan_contract_version'] = DEPENDENCY_PLAN_CONTRACT_VERSION
    if capability['id'] == CAPABILITY_TABULAR_ANALYZE:
        # The native computation contract is read only when a tabular step is considered.
        from functions_orchestration_native_results import (
            native_orchestration_arguments_schema, native_orchestration_output_specs,
        )

        capability['inputs'] = native_orchestration_arguments_schema()
        capability['result_output_variants'] = [
            {
                'native_operation': operation, 'task_type': task_type,
                'outputs': [
                    {'name': spec.name, 'kind': spec.kind}
                    for spec in native_orchestration_output_specs(operation, task_type=task_type)
                ],
            }
            for operation, task_type in (
                ('query', 'structured_export'), ('transform', 'structured_export'),
                ('analysis', 'hierarchical_analysis'), ('transform', 'combined'),
            )
        ]
    return capability


def _render_file_descriptor():
    """The Render capability, built from the shared export catalog and output service."""
    # Export and output services are imported only when render work is considered.
    from functions_generated_export_registry import get_generated_file_export_catalog
    from functions_orchestration_output_store import OUTPUT_CONTRACT_VERSION
    import functions_orchestration_rendering as rendering

    render_capability = {
        'id': CAPABILITY_RENDER_FILE,
        'label': 'Render prepared file',
        'plan_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
        'result_contract_version': OUTPUT_CONTRACT_VERSION,
        'role': ROLE_RENDER,
        'summary': 'Create one downloadable file from an explicitly prepared retained result.',
        'when_to_use': (
            'Bind exactly one complete retained source. Select an explicit file name, format, '
            'profile, and supported options. Draft content with Reason first when necessary; '
            'Render does not compose, retrieve, select a model, or infer a representation. '
            'Its outputs are durable file deliveries, not named data results. DOCX, PDF, and '
            'PPTX files embed the generated images their prepared source places.'
        ),
        'settings_gates': (),
        'settings_gates_any': (),
        'gate': None,
        'request_gate': None,
        'requires_scope': (),
        'runtime_service': 'rendering_service',
        'inputs': render_file_arguments_schema(get_generated_file_export_catalog()),
        'result_input_kinds': {'source': tuple(_RENDER_SOURCE_KINDS)},
        'required_result_inputs': ('source',),
        'render_source_kinds': dict(_RENDER_SOURCE_KINDS),
        'partial_inputs_supported': False,
        'result_outputs': {},
        'produces': (PRODUCES_ARTIFACTS,),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': None,
        'adapter': CAPABILITY_RENDER_FILE,
    }
    if not callable(getattr(rendering, 'resume_render_file', None)):
        render_capability['runtime_unavailable_reason'] = 'rendering_service_unavailable'
    return render_capability


def _build_capabilities(candidate_ids=None):
    """Registered descriptors in registry order, resolved; optionally only some of them.

    The native tabular contract and the export catalog belong to other services and are
    read only for the descriptors requested, so looking up one capability does not load
    the rendering and native computation stacks.
    """
    capabilities = [
        _resolve_descriptor(descriptor) for descriptor in CAPABILITY_REGISTRY
        if candidate_ids is None or descriptor['id'] in candidate_ids
    ]
    if candidate_ids is None or CAPABILITY_RENDER_FILE in candidate_ids:
        capabilities.append(_render_file_descriptor())
    return capabilities


def _require_contract(contract_version):
    """Only the Gather / Reason / Render contract exists; anything else is a caller error."""
    if type(contract_version) is not int or contract_version != DEPENDENCY_PLAN_CONTRACT_VERSION:
        raise ValueError('Unsupported orchestration plan contract.')


def capabilities_for_contract(contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION):
    """Every registered capability, resolved, regardless of whether it is enabled."""
    _require_contract(contract_version)
    return _build_capabilities()


def get_capability_result_outputs(capability, arguments):
    """Resolve server-owned output requirements for an approved operation."""
    if capability['id'] == CAPABILITY_TABULAR_ANALYZE:
        from functions_orchestration_native_results import native_orchestration_output_specs

        outputs = native_orchestration_output_specs(
            arguments.get('native_operation'), task_type=arguments.get('task_type'),
        )
        return {output.name: output.kind for output in outputs}, {}
    return capability['result_outputs'], capability.get('optional_result_outputs', {})


def all_capability_ids(*, contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION):
    """Every capability identifier, regardless of whether it is currently enabled."""
    return [capability['id'] for capability in capabilities_for_contract(contract_version)]


def get_capability(capability_id, *, contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION):
    """Look up one descriptor, or None when the id is not registered.

    Returning None rather than raising is deliberate: the caller is usually the validator
    checking planner output, where an unknown capability is an expected kind of bad input
    rather than a programming error.
    """
    _require_contract(contract_version)
    if not isinstance(capability_id, str):
        return None
    return next(iter(_build_capabilities({capability_id.strip()})), None)


def _gates_pass(capability, settings):
    """Whether a capability's three deployment-level gate forms all allow it."""
    settings = settings if isinstance(settings, dict) else {}

    for key in capability.get('settings_gates') or ():
        if not settings.get(key):
            return False

    any_gates = capability.get('settings_gates_any') or ()
    if any_gates and not any(settings.get(key) for key in any_gates):
        return False

    gate = capability.get('gate')
    if callable(gate) and not gate(settings):
        return False

    return True


def _request_gate_passes(capability, settings, request_context):
    """Whether this particular request may use a capability the deployment allows.

    Skipped entirely when no request context is supplied, which is what the admin page and
    the bootstrap payload want: they are describing the deployment, not a caller.

    A failed check prevents planning, rather than pretending access was checked and denied.
    """
    gate = capability.get('request_gate')
    if not callable(gate) or request_context is None:
        return True
    try:
        return bool(gate(settings, request_context))
    except CapabilityResolutionError:
        raise
    except Exception as exc:
        log_event(
            '[ORCHESTRATION_REGISTRY] A capability access check failed.',
            level=logging.WARNING,
            extra={'reason': 'capability_check_failed', 'error_type': type(exc).__name__},
        )
        raise CapabilityResolutionError('Capability access could not be checked.') from exc


def _allowed_ids(settings, allowed_ids):
    narrowed = None
    for source, values in (
        ('settings', settings.get('chat_orchestration_enabled_capabilities')),
        ('allowed_ids', allowed_ids),
    ):
        if values is None:
            continue
        if type(values) not in (list, tuple, set, frozenset) or any(
            type(value) is not str or not value.strip() for value in values
        ):
            log_event(
                '[ORCHESTRATION_REGISTRY] Invalid orchestration capability allowlist.',
                level=logging.WARNING, extra={'source': source},
            )
            raise CapabilityResolutionError('The orchestration capability configuration is invalid.')
        if not values:
            continue
        identifiers = {value.strip() for value in values}
        narrowed = identifiers if narrowed is None else narrowed & identifiers
    return narrowed


def resolve_available_capabilities(
    settings, allowed_ids=None, request_context=None, candidate_ids=None, unavailable=None,
    *, contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION, export_catalog=None,
    include_runtime_bindings=True,
):
    """The capabilities this deployment currently permits, in registry order.

    ``allowed_ids`` is the administrator's ``chat_orchestration_enabled_capabilities``
    narrowing. An empty or missing list means "everything the other gates already allow",
    because an administrator who has not expressed an opinion should not thereby disable
    the feature entirely.

    ``request_context`` narrows further to what *this caller, asking this question* may use
    -- app roles, whether they have any agents, whether their message contains a link.
    Omitted, the answer describes the deployment, which is what the admin surface needs.
    Capabilities that need request-time services (external source bindings, the native
    tabular bridge, the rendering service) are offered only when the context supplies them.
    ``include_runtime_bindings=False`` skips only those service checks, for a caller asking
    whether settings, the allowlist and request gates permit a capability at all -- catalog
    discovery, the bootstrap payload, and the source preflight that is itself one of those
    services. Planning and execution always keep them.

    The saved settings and caller narrowing are intersected, with no mandatory capability.
    A malformed allowlist fails closed.

    ``candidate_ids`` limits an internal lookup to specific descriptors, avoiding unrelated
    gates and their storage/import work when an executor checks one capability.

    ``unavailable`` optionally receives stable reasons from the same checks. It never
    infers permissions from a manual control or from model-authored text.

    An explicit ``export_catalog`` narrows supported format/profile pairs. Empty means no
    Render work, not the shared default. None preserves shared definitions.
    """
    _require_contract(contract_version)
    settings = settings if isinstance(settings, dict) else {}
    narrowed = _allowed_ids(settings, allowed_ids)
    admitted_catalog = resolve_admitted_export_catalog(export_catalog) if export_catalog is not None else None

    available = []
    for capability in _build_capabilities(candidate_ids):
        if narrowed is not None and capability['id'] not in narrowed:
            if unavailable is not None:
                unavailable[capability['id']] = 'not_enabled_for_orchestration'
            continue
        if capability['id'] == CAPABILITY_RENDER_FILE and admitted_catalog is not None:
            if not admitted_catalog:
                if unavailable is not None:
                    unavailable[capability['id']] = 'export_catalog_unavailable'
                continue
            capability = deepcopy(capability)
            capability['inputs'] = render_file_arguments_schema(admitted_catalog)
            source_kinds = {
                kind for entry in admitted_catalog for profile in entry['profiles']
                for kind in profile['source_kinds']
            }
            capability['result_input_kinds']['source'] = tuple(
                kind for kind, exported_kind in capability['render_source_kinds'].items()
                if exported_kind in source_kinds
            )
        if capability.get('runtime_unavailable_reason'):
            if unavailable is not None:
                unavailable[capability['id']] = capability['runtime_unavailable_reason']
            continue
        if include_runtime_bindings and capability.get('runtime_service') == 'rendering_service':
            # The concrete output service is imported only when render work is considered.
            from functions_orchestration_rendering import OrchestrationRenderingService

            if not isinstance((request_context or {}).get('rendering_service'), OrchestrationRenderingService):
                if unavailable is not None:
                    unavailable[capability['id']] = 'rendering_service_unavailable'
                continue
        bindings = capability.get('runtime_bindings') or (
            (capability['runtime_binding'],) if capability.get('runtime_binding') else ()
        )
        if include_runtime_bindings and any(not callable((request_context or {}).get(name)) for name in bindings):
            if unavailable is not None:
                unavailable[capability['id']] = capability['runtime_binding_unavailable_reason']
            continue
        if not _gates_pass(capability, settings):
            if unavailable is not None:
                unavailable[capability['id']] = 'feature_disabled'
            continue
        if capability.get('runtime_readiness') == 'image_generation':
            # Image service metadata is read only when image steps are actually considered.
            from functions_orchestration_images import image_generation_readiness

            readiness = image_generation_readiness(settings)
            if readiness['status'] != 'available':
                if unavailable is not None:
                    unavailable[capability['id']] = readiness['reason']
                continue
            capability = deepcopy(capability)
            capability['inputs'] = generate_image_arguments_schema(readiness)
        if not _request_gate_passes(capability, settings, request_context):
            if unavailable is not None:
                reason = 'caller_access_required'
                if capability['id'] == CAPABILITY_URL_FETCH and not request_context.get('message_urls'):
                    reason = 'missing_user_url'
                elif capability['id'] == CAPABILITY_AGENT_INVOKE:
                    reason = (
                        'no_accessible_agents' if request_context.get('user_enable_agents', True)
                        else 'agents_disabled_for_user'
                    )
                elif capability['id'] == CAPABILITY_ACTION_INVOKE:
                    reason = 'no_accessible_actions'
                unavailable[capability['id']] = reason
            continue
        available.append(capability)

    return available


def resolve_available_capability_ids(
    settings, allowed_ids=None, request_context=None, candidate_ids=None, *,
    contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION, export_catalog=None,
    include_runtime_bindings=True,
):
    """Identifiers only, for the validator and for the bootstrap payload."""
    return [
        capability['id']
        for capability in resolve_available_capabilities(
            settings, allowed_ids=allowed_ids, request_context=request_context,
            candidate_ids=candidate_ids,
            contract_version=contract_version, export_catalog=export_catalog,
            include_runtime_bindings=include_runtime_bindings,
        )
    ]


def build_planner_capability_projection(capabilities):
    """Reduce descriptors to what the planner model is actually shown.

    Gate implementation and adapter internals stay private. Outputs and limits help the
    model choose feasible work; the validator still enforces them independently.
    """
    projection = []
    for capability in capabilities or ():
        projection.append({
            'id': capability['id'],
            'label': capability['label'],
            'role': capability['role'],
            'summary': capability['summary'],
            'when_to_use': capability['when_to_use'],
            'inputs': capability['inputs'],
            'cost': capability['cost_class'],
            'produces': list(capability.get('produces') or ()),
            'max_per_plan': capability.get('max_per_plan'),
            'plan_contract_version': capability['plan_contract_version'],
            'result_contract_version': capability['result_contract_version'],
            'result_input_kinds': {
                name: list(kinds) for name, kinds in capability['result_input_kinds'].items()
            },
            'partial_inputs_supported': capability['partial_inputs_supported'],
            **({'optional_inputs_supported': True} if capability.get('optional_inputs_supported') else {}),
            **({'required_result_inputs': list(capability['required_result_inputs'])}
               if capability.get('required_result_inputs') else {}),
            'result_outputs': capability['result_outputs'],
            'optional_result_outputs': capability.get('optional_result_outputs', {}),
            'result_output_kinds': list(capability.get('result_output_kinds') or ()),
            **({'result_output_variants': capability['result_output_variants']}
               if 'result_output_variants' in capability else {}),
        })
    return projection


def build_capability_client_projection(capabilities):
    """What the browser is shown, so the plan card can label and cost a step.

    Narrower than the planner's view: the card renders a step the planner already chose,
    so it needs naming, purpose and cost but not the guidance that drove the choice.
    """
    projection = []
    for capability in capabilities or ():
        projection.append({
            'id': capability['id'],
            'label': capability['label'],
            'role': capability['role'],
            'summary': capability['summary'],
            'cost': capability['cost_class'],
        })
    return projection


# Fields of an agent catalog record the planner may see.
#
# `instructions` is the agent's entire system prompt and is withheld deliberately: it is
# long enough to crowd out the question, and it is the agent's own configuration rather than
# something the planner needs to choose between agents. `actions_to_load`,
# `assigned_knowledge`, `model_endpoint_id` and `scope_id` are withheld on the same
# principle as the capability projection -- the planner is given what it needs to pick, not
# the internals of what it picked.
AGENT_PLANNER_FIELDS = ('name', 'display_name', 'description', 'tags', 'action_labels')


def build_agent_planner_projection(agents, limit=None):
    """Reduce the agent catalog to what the planner is shown when choosing one."""
    projection = []
    for agent in agents or ():
        if not isinstance(agent, dict):
            continue
        name = str(agent.get('name') or '').strip()
        if not name:
            continue
        entry = {'name': name}
        for field in AGENT_PLANNER_FIELDS[1:]:
            value = agent.get(field)
            if value:
                entry[field] = value
        projection.append(entry)
        if limit is not None and len(projection) >= limit:
            break
    return projection


def get_capability_document_limit(capability, settings=None):
    """How many documents this capability may be given in one chat step.

    Only the document actions carry an administrator-configured limit; everything else is
    bounded by its own input schema. Returns None when no limit applies, which the
    validator reads as "the schema is the only constraint".
    """
    action_type = (capability or {}).get('document_action_type')
    if not action_type:
        return None
    try:
        from functions_document_actions import get_document_action_max_documents

        return int(get_document_action_max_documents(
            action_type,
            DOCUMENT_ACTION_CONTEXT_CHAT,
            settings=settings,
        ))
    except Exception as exc:
        raise CapabilityResolutionError('Document limits could not be checked.') from exc


def describe_registry(*, contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION):
    """A stable summary for tests and for the documentation inventory."""
    return {
        'contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
        'capability_ids': all_capability_ids(contract_version=contract_version),
        'roles': [ROLE_GATHER, ROLE_REASON, ROLE_RENDER],
    }
