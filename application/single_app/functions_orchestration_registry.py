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

Version: 0.261.127
"""

import logging
from copy import deepcopy

from functions_appinsights import log_event
from functions_orchestration_result_contracts import RESULT_KINDS, ResultContractError, canonical_bytes

# Bumped when the descriptor shape changes in a way a stored plan could not survive.
CAPABILITY_REGISTRY_CONTRACT_VERSION = 1
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

PHASE_KNOWLEDGE = 'knowledge'
PHASE_REASONING = 'reasoning'
PHASE_OUTPUT = 'output'

# Ordered, and the order is the point. A plan runs in phase order, so a capability's phase
# is really its index: "may this step follow that one" becomes an integer comparison rather
# than a table of special cases.
#
# This replaces the earlier `kind` (retrieval / analysis / synthesis), which was carried all
# the way to the browser and read by nothing -- not the validator, not the executor, not one
# React component. A second decorative taxonomy alongside this one is how a field ends up
# meaning nothing, so `kind` is gone rather than kept.
#
# The boundary is drawn on what a capability *produces*, not on how hard it thinks. Analysing
# and comparing documents emit the same evidence envelopes as searching them, and the answer
# is the only step that consumes evidence -- so they are knowledge and it is reasoning.
CAPABILITY_PHASES = (
    PHASE_KNOWLEDGE,
    PHASE_REASONING,
    PHASE_OUTPUT,
)

COST_CLASS_LOW = 'low'
COST_CLASS_MEDIUM = 'medium'
COST_CLASS_HIGH = 'high'

COST_CLASSES = (COST_CLASS_LOW, COST_CLASS_MEDIUM, COST_CLASS_HIGH)

# What a step can leave behind in the run context for later steps to consume.
PRODUCES_EVIDENCE = 'evidence'
PRODUCES_CITATIONS = 'citations'
PRODUCES_ARTIFACTS = 'artifacts'
PRODUCES_MESSAGE = 'message'
# Gathered text rather than document evidence.
#
# An agent, a URL read and a deep research crawl all return prose and citations tied to no
# document id. `build_evidence_envelope` refuses that shape outright -- it requires a
# non-empty `document_id`, a `source_kind` of tabular or narrative, and one of three named
# engines. Calling their output evidence would mean either lying to that validator or
# loosening it, and neither is worth it: `RunContext` already accumulates `notes`, and the
# respond adapter already folds notes into its prompt. So they produce notes, and notes
# reach the answer by the path that exists.
PRODUCES_NOTES = 'notes'

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
CAPABILITY_RESPOND = 'respond'
CAPABILITY_COMPOSE = 'compose'

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


# The registry itself. Ordered as a plan tends to read: gather, then reason, then answer.
#
# `when_to_use` is the only free text the planner is shown per capability, so it is written
# as guidance to a reader deciding between options rather than as a restatement of the
# label. `inputs` is a JSON Schema fragment, and is what the validator enforces -- a plan
# whose arguments do not satisfy it never reaches an adapter.
CAPABILITY_REGISTRY = (
    {
        'id': CAPABILITY_DOCUMENT_SEARCH,
        'label': 'Search documents',
        'phase': PHASE_KNOWLEDGE,
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
        'produces': (PRODUCES_EVIDENCE, PRODUCES_CITATIONS),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 3,
        'adapter': CAPABILITY_DOCUMENT_SEARCH,
        'terminal': False,
    },
    {
        'id': CAPABILITY_DOCUMENT_ANALYZE,
        'label': 'Analyse documents',
        'phase': PHASE_KNOWLEDGE,
        'request_gate': None,
        'summary': "Read one or more documents end to end and answer a question about them.",
        'when_to_use': (
            "The question needs whole-document coverage rather than a few passages -- "
            "summarising, extracting every instance of something, or answering where a "
            "search would miss material. Considerably more expensive than searching."
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
                'documents_from_step': {
                    'type': 'string',
                    'description': (
                        'Instead of naming documents, read whichever ones an earlier '
                        'step found. Give that step\'s step_id. Use this when the '
                        'documents worth reading are not known until a search has run; '
                        'name documents directly whenever they are already known.'
                    ),
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
        'produces': (PRODUCES_EVIDENCE, PRODUCES_CITATIONS),
        'cost_class': COST_CLASS_HIGH,
        'max_per_plan': 2,
        'adapter': CAPABILITY_DOCUMENT_ANALYZE,
        'terminal': False,
        # Enforced by the validator against the administrator's chat limit.
        'document_action_type': DOCUMENT_ACTION_TYPE_ANALYZE,
    },
    {
        'id': CAPABILITY_DOCUMENT_COMPARE,
        'label': 'Compare documents',
        'phase': PHASE_KNOWLEDGE,
        'request_gate': None,
        'summary': "Compare one document against one or more others.",
        'when_to_use': (
            "The question is explicitly comparative -- what changed, how two versions "
            "differ, which of several documents says something. Needs a single left-hand "
            "document and at least one to compare it against."
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
        'produces': (PRODUCES_EVIDENCE, PRODUCES_CITATIONS),
        'cost_class': COST_CLASS_HIGH,
        'max_per_plan': 1,
        'adapter': CAPABILITY_DOCUMENT_COMPARE,
        'terminal': False,
        'document_action_type': DOCUMENT_ACTION_TYPE_COMPARISON,
    },
    {
        'id': CAPABILITY_TABULAR_ANALYZE,
        'label': 'Analyse spreadsheets',
        'phase': PHASE_KNOWLEDGE,
        'request_gate': None,
        'summary': "Compute over CSV or Excel data rather than reading it as prose.",
        'when_to_use': (
            "The named documents are spreadsheets or CSV files and the question needs "
            "counting, filtering, aggregating or per-row work. Reading a workbook as text "
            "gives wrong numbers, so prefer this whenever the source is tabular."
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
                'question': {'type': 'string', 'minLength': 1},
                'document_ids': {
                    'type': 'array',
                    'items': {'type': 'string'},
                    'minItems': 1,
                },
            },
            'required': ['question', 'document_ids'],
            'additionalProperties': False,
        },
        'produces': (PRODUCES_EVIDENCE, PRODUCES_CITATIONS, PRODUCES_ARTIFACTS),
        'cost_class': COST_CLASS_MEDIUM,
        'max_per_plan': 2,
        'adapter': CAPABILITY_TABULAR_ANALYZE,
        'terminal': False,
    },
    {
        'id': CAPABILITY_WEB_SEARCH,
        'label': 'Search the web',
        'phase': PHASE_KNOWLEDGE,
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
        'produces': (PRODUCES_NOTES, PRODUCES_CITATIONS),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 2,
        'adapter': CAPABILITY_WEB_SEARCH,
        'terminal': False,
    },
    {
        'id': CAPABILITY_URL_FETCH,
        'label': 'Read linked pages',
        'phase': PHASE_KNOWLEDGE,
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
        'produces': (PRODUCES_NOTES, PRODUCES_CITATIONS),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 1,
        'adapter': CAPABILITY_URL_FETCH,
        'terminal': False,
    },
    {
        'id': CAPABILITY_DEEP_RESEARCH,
        'label': 'Research in depth',
        'phase': PHASE_KNOWLEDGE,
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
        'produces': (PRODUCES_NOTES, PRODUCES_CITATIONS),
        'cost_class': COST_CLASS_HIGH,
        'max_per_plan': 1,
        'adapter': CAPABILITY_DEEP_RESEARCH,
        'terminal': False,
    },
    {
        'id': CAPABILITY_ACTION_INVOKE,
        'label': 'Use an action',
        'phase': PHASE_KNOWLEDGE,
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
            },
            'required': ['action_ref', 'task'],
            'additionalProperties': False,
        },
        'produces': (PRODUCES_NOTES, PRODUCES_CITATIONS, PRODUCES_ARTIFACTS),
        'cost_class': COST_CLASS_MEDIUM,
        'max_per_plan': None,
        'adapter': CAPABILITY_ACTION_INVOKE,
        'terminal': False,
    },
    {
        'id': CAPABILITY_AGENT_INVOKE,
        'label': 'Ask an agent',
        'phase': PHASE_KNOWLEDGE,
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
            },
            'required': ['agent_name', 'task'],
            'additionalProperties': False,
        },
        'produces': (PRODUCES_NOTES, PRODUCES_CITATIONS, PRODUCES_ARTIFACTS),
        'cost_class': COST_CLASS_HIGH,
        # One per plan. Every agent step loads a kernel from scratch -- resolving Key Vault
        # secrets, hydrating each plugin the agent declares, introspecting SQL and Cosmos
        # schemas -- and there is no live kernel cache to amortise it. Two agent steps means
        # paying all of that twice.
        'max_per_plan': 1,
        'adapter': CAPABILITY_AGENT_INVOKE,
        'terminal': False,
    },
    {
        'id': CAPABILITY_RESPOND,
        'label': 'Answer',
        'phase': PHASE_REASONING,
        'request_gate': None,
        'summary': "Write the answer from whatever the earlier steps gathered.",
        'when_to_use': (
            "Always the last step. Every plan ends with exactly one of these, including a "
            "plan that gathers nothing and simply answers from the model's own knowledge."
        ),
        'settings_gates': (),
        'settings_gates_any': (),
        'gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {
                'instruction': {
                    'type': 'string',
                    'description': 'How to shape the answer. Omit to answer the question directly.',
                },
            },
            'required': [],
            'additionalProperties': False,
        },
        'produces': (PRODUCES_MESSAGE,),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 1,
        'adapter': CAPABILITY_RESPOND,
        'terminal': True,
    },
)

CAPABILITY_BY_ID = {capability['id']: capability for capability in CAPABILITY_REGISTRY}

_DEPENDENCY_OUTPUTS = {
    CAPABILITY_DOCUMENT_SEARCH: {
        'evidence': 'evidence-set-v1', 'sources': 'source-set-v1', 'prepared': 'structured-v1',
    },
    CAPABILITY_DOCUMENT_ANALYZE: {'findings': 'records-v1', 'coverage': 'structured-v1'},
    CAPABILITY_DOCUMENT_COMPARE: {'comparison': 'comparison-v1', 'coverage': 'structured-v1'},
    CAPABILITY_TABULAR_ANALYZE: {'records': 'records-v1'},
    CAPABILITY_WEB_SEARCH: {'prepared': 'structured-v1'},
    CAPABILITY_URL_FETCH: {'prepared': 'structured-v1'},
    CAPABILITY_DEEP_RESEARCH: {'prepared': 'structured-v1'},
    CAPABILITY_AGENT_INVOKE: {'prepared': 'structured-v1'},
    CAPABILITY_ACTION_INVOKE: {'prepared': 'structured-v1'},
}
_DEPENDENCY_RESULT_CONTRACTS = {
    CAPABILITY_DOCUMENT_SEARCH: 'orchestration-gathered-content-v1',
    CAPABILITY_DOCUMENT_ANALYZE: 'analyze-final-v1',
    CAPABILITY_DOCUMENT_COMPARE: 'comparison-v1',
    CAPABILITY_TABULAR_ANALYZE: 'native-tabular-result-v1',
    CAPABILITY_WEB_SEARCH: 'orchestration-gathered-content-v1',
    CAPABILITY_URL_FETCH: 'orchestration-gathered-content-v1',
    CAPABILITY_DEEP_RESEARCH: 'orchestration-gathered-content-v1',
    CAPABILITY_AGENT_INVOKE: 'orchestration-gathered-content-v1',
    CAPABILITY_ACTION_INVOKE: 'orchestration-gathered-content-v1',
    CAPABILITY_COMPOSE: 'compose-v1',
}
_REASON_CAPABILITIES = {
    CAPABILITY_DOCUMENT_ANALYZE, CAPABILITY_DOCUMENT_COMPARE, CAPABILITY_TABULAR_ANALYZE,
}
_EXTERNAL_GATHER_CAPABILITIES = {
    CAPABILITY_WEB_SEARCH, CAPABILITY_URL_FETCH, CAPABILITY_DEEP_RESEARCH,
    CAPABILITY_AGENT_INVOKE, CAPABILITY_ACTION_INVOKE,
}


def resolve_admitted_export_catalog(export_catalog=None):
    """Narrow real shared format/profile declarations without redefining a renderer."""
    # Export metadata belongs to explicit v2 admission, not legacy registry bootstrap.
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


def _dependency_capabilities():
    """Opt-in descriptors; legacy phases and the default catalog remain unchanged."""
    # Service metadata is needed only for explicit v2 discovery, not legacy bootstrap.
    from functions_orchestration_native_results import (
        native_orchestration_arguments_schema, native_orchestration_output_specs,
    )
    from functions_generated_export_registry import get_generated_file_export_catalog
    from functions_orchestration_output_store import OUTPUT_CONTRACT_VERSION
    import functions_orchestration_rendering as rendering

    capabilities = []
    for legacy in CAPABILITY_REGISTRY:
        if legacy['id'] == CAPABILITY_RESPOND:
            continue
        capability = deepcopy(legacy)
        capability.pop('phase')
        capability.update({
            'plan_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
            'result_contract_version': _DEPENDENCY_RESULT_CONTRACTS[capability['id']],
            'role': ROLE_REASON if capability['id'] in _REASON_CAPABILITIES else ROLE_GATHER,
            'result_outputs': dict(_DEPENDENCY_OUTPUTS[capability['id']]),
            'result_input_kinds': {},
            'partial_inputs_supported': False,
            'produces': ('retained_results',),
        })
        if capability['id'] in _EXTERNAL_GATHER_CAPABILITIES:
            capability.update({
                'runtime_bindings': (
                    'external_source_admission', 'external_source_preflight', 'capture_external_source_configuration',
                    'external_source_authorizer',
                ),
                'runtime_binding_unavailable_reason': 'external_result_lineage_unavailable',
            })
        capability['inputs']['properties'].pop('documents_from_step', None)
        if capability['id'] == CAPABILITY_DOCUMENT_ANALYZE:
            capability['when_to_use'] += ' This contract currently accepts narrative documents; native tabular handoff is not admitted.'
            capability['result_input_kinds'] = {'sources': ('source-set-v1',)}
            capability['optional_result_outputs'] = {'records': 'records-v1', 'report': 'markdown-v1'}
        elif capability['id'] == CAPABILITY_DOCUMENT_COMPARE:
            capability['when_to_use'] += ' This contract currently accepts narrative documents; native tabular handoff is not admitted.'
            capability['optional_result_outputs'] = {'report': 'markdown-v1'}
        elif capability['id'] == CAPABILITY_TABULAR_ANALYZE:
            capability.update({
                'runtime_binding': 'native_bridge_for_step',
                'runtime_binding_unavailable_reason': 'native_typed_result_bridge_unavailable',
                'inputs': native_orchestration_arguments_schema(),
                'result_outputs': {'coverage': 'structured-v1'},
                'optional_result_outputs': {'records': 'records-v1', 'analysis': 'structured-v1'},
                'result_output_variants': [
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
                ],
                'when_to_use': (
                    'Compute over exactly one authorized replayable CSV or workbook without publishing files. '
                    'Query requires a row-local query_expression and explicit columns; transformations require '
                    'an executable transformation_spec or explicit schema. Analysis-only returns analysis, '
                    'not implicit source rows. Declare exactly the selected result_output_variants outputs. '
                    'Mixed/multiple sources and bare prose aggregate plans are unsupported.'
                ),
            })
        capabilities.append(capability)
    capabilities.append({
        'id': CAPABILITY_COMPOSE,
        'label': 'Prepare content',
        'plan_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
        'result_contract_version': _DEPENDENCY_RESULT_CONTRACTS[CAPABILITY_COMPOSE],
        'role': ROLE_REASON,
        'summary': 'Compose reusable text, Markdown, records, or structured content.',
        'when_to_use': (
            'Explicitly draft an answer or report, or prepare structured data. Bind every '
            'retained input by name. Source-free content is supported. This does not create '
            'files, infer a file format, retrieve sources, or call tools. Declare each output '
            'and select final_response when its text should become the chat answer.'
        ),
        'settings_gates': (),
        'settings_gates_any': (),
        'gate': None,
        'request_gate': None,
        'requires_scope': (),
        'inputs': {
            'type': 'object',
            'properties': {'instruction': {'type': 'string', 'minLength': 1}},
            'required': ['instruction'],
            'additionalProperties': False,
        },
        'result_input_kinds': {'*': tuple(sorted(RESULT_KINDS))},
        'partial_inputs_supported': True,
        'result_outputs': {},
        'result_output_kinds': ('text-v1', 'markdown-v1', 'records-v1', 'structured-v1'),
        'produces': ('retained_results',),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': None,
        'adapter': CAPABILITY_COMPOSE,
        'terminal': False,
    })
    catalog = get_generated_file_export_catalog()
    source_kinds = {
        'records-v1': 'records', 'text-v1': 'text', 'markdown-v1': 'markdown',
        'structured-v1': 'structured_value', 'comparison-v1': 'structured_value',
    }
    render_capability = {
        'id': 'render_file',
        'label': 'Render prepared file',
        'plan_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
        'result_contract_version': OUTPUT_CONTRACT_VERSION,
        'role': ROLE_RENDER,
        'summary': 'Create one downloadable file from an explicitly prepared retained result.',
        'when_to_use': (
            'Bind exactly one complete retained source. Select an explicit file name, format, '
            'profile, and supported options. Draft content with Reason first when necessary; '
            'Render does not compose, retrieve, select a model, or infer a representation. '
            'Its outputs are durable file deliveries, not named data results.'
        ),
        'settings_gates': (),
        'settings_gates_any': (),
        'gate': None,
        'request_gate': None,
        'requires_scope': (),
        'runtime_service': 'rendering_service',
        'inputs': render_file_arguments_schema(catalog),
        'result_input_kinds': {'source': tuple(source_kinds)},
        'required_result_inputs': ('source',),
        'render_source_kinds': source_kinds,
        'partial_inputs_supported': False,
        'result_outputs': {},
        'produces': ('artifacts',),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': None,
        'adapter': 'render_file',
        'terminal': False,
    }
    if not callable(getattr(rendering, 'resume_render_file', None)):
        render_capability['runtime_unavailable_reason'] = 'rendering_service_unavailable'
    capabilities.append(render_capability)
    return capabilities


def capabilities_for_contract(contract_version=1):
    if type(contract_version) is not int or contract_version not in (1, DEPENDENCY_PLAN_CONTRACT_VERSION):
        raise ValueError('Unsupported orchestration plan contract.')
    return CAPABILITY_REGISTRY if contract_version == 1 else _dependency_capabilities()


def get_capability_result_outputs(capability, arguments):
    """Resolve server-owned output requirements for an approved operation."""
    if capability.get('plan_contract_version') == 2 and capability['id'] == CAPABILITY_TABULAR_ANALYZE:
        from functions_orchestration_native_results import native_orchestration_output_specs

        outputs = native_orchestration_output_specs(
            arguments.get('native_operation'), task_type=arguments.get('task_type'),
        )
        return {output.name: output.kind for output in outputs}, {}
    return capability['result_outputs'], capability.get('optional_result_outputs', {})


# Every plan ends with this, so the planner never has to be told to include it and a plan
# that omits it is repaired rather than rejected.
TERMINAL_CAPABILITY_ID = CAPABILITY_RESPOND


def all_capability_ids(*, contract_version=1):
    """Every capability identifier, regardless of whether it is currently enabled."""
    return [capability['id'] for capability in capabilities_for_contract(contract_version)]


def get_capability(capability_id, *, contract_version=1):
    """Look up one descriptor, or None when the id is not registered.

    Returning None rather than raising is deliberate: the caller is usually the validator
    checking planner output, where an unknown capability is an expected kind of bad input
    rather than a programming error.
    """
    if not isinstance(capability_id, str):
        return None
    if contract_version != 1 or type(contract_version) is not int:
        return next((
            capability for capability in capabilities_for_contract(contract_version)
            if capability['id'] == capability_id.strip()
        ), None)
    return CAPABILITY_BY_ID.get(capability_id.strip())


def phase_index(capability_or_id):
    """Where a capability sits in the run, as a sortable integer.

    Accepts a descriptor or an id so callers do not have to look one up first. An unknown
    capability sorts to the end rather than the front: whatever it is, running it before
    everything that gathers would be the more damaging guess.
    """
    capability = capability_or_id
    if isinstance(capability_or_id, str):
        capability = get_capability(capability_or_id)
    phase = (capability or {}).get('phase')
    try:
        return CAPABILITY_PHASES.index(phase)
    except ValueError:
        return len(CAPABILITY_PHASES)


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


def _dependency_allowed_ids(settings, allowed_ids):
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
                '[ORCHESTRATION_REGISTRY] Invalid harness capability allowlist.',
                level=logging.WARNING, extra={'source': source, 'plan_contract_version': 2},
            )
            raise CapabilityResolutionError('The orchestration capability configuration is invalid.')
        if not values:
            continue
        identifiers = {value.strip() for value in values}
        narrowed = identifiers if narrowed is None else narrowed & identifiers
    return narrowed


def resolve_available_capabilities(
    settings, allowed_ids=None, request_context=None, candidate_ids=None, unavailable=None,
    *, contract_version=1, export_catalog=None,
):
    """The capabilities this deployment currently permits, in registry order.

    ``allowed_ids`` is the administrator's ``chat_orchestration_enabled_capabilities``
    narrowing. An empty or missing list means "everything the other gates already allow",
    because an administrator who has not expressed an opinion should not thereby disable
    the feature entirely.

    ``request_context`` narrows further to what *this caller, asking this question* may use
    -- app roles, whether they have any agents, whether their message contains a link.
    Omitted, the answer describes the deployment, which is what the admin surface needs.

    For v1, the terminal capability is never removed by the narrowing. For v2, the
    saved settings and caller narrowing are intersected, with no mandatory capability
    or aliases for legacy IDs. A nonempty legacy list does not opt into composition
    or file rendering. Malformed v2 allowlists fail closed.

    ``candidate_ids`` limits an internal lookup to specific descriptors, avoiding unrelated
    gates and their storage/import work when an executor checks one capability.

    ``unavailable`` optionally receives stable reasons from the same checks. It never
    infers permissions from a manual control or from model-authored text.

    An explicit v2 ``export_catalog`` narrows supported format/profile pairs. Empty
    means no Render work, not the shared default. None preserves shared definitions.
    """
    settings = settings if isinstance(settings, dict) else {}

    if type(contract_version) is int and contract_version == DEPENDENCY_PLAN_CONTRACT_VERSION:
        narrowed = _dependency_allowed_ids(settings, allowed_ids)
        admitted_catalog = resolve_admitted_export_catalog(export_catalog) if export_catalog is not None else None
    else:
        narrowed = None
        admitted_catalog = None
        if isinstance(allowed_ids, (list, tuple, set)):
            narrowed = {str(value).strip() for value in allowed_ids if str(value).strip()}
            if not narrowed:
                narrowed = None

    available = []
    for capability in capabilities_for_contract(contract_version):
        if candidate_ids is not None and capability['id'] not in candidate_ids:
            continue
        if narrowed is not None and capability['id'] not in narrowed:
            if contract_version != 1 or capability['id'] != TERMINAL_CAPABILITY_ID:
                if unavailable is not None:
                    unavailable[capability['id']] = 'not_enabled_for_orchestration'
                continue
        if capability['id'] == 'render_file' and admitted_catalog is not None:
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
        if capability.get('runtime_service') == 'rendering_service':
            # The legacy catalog must not import or initialize concrete output services.
            from functions_orchestration_rendering import OrchestrationRenderingService

            if not isinstance((request_context or {}).get('rendering_service'), OrchestrationRenderingService):
                if unavailable is not None:
                    unavailable[capability['id']] = 'rendering_service_unavailable'
                continue
        bindings = capability.get('runtime_bindings') or (
            (capability['runtime_binding'],) if capability.get('runtime_binding') else ()
        )
        if any(not callable((request_context or {}).get(name)) for name in bindings):
            if unavailable is not None:
                unavailable[capability['id']] = capability['runtime_binding_unavailable_reason']
            continue
        if not _gates_pass(capability, settings):
            if unavailable is not None:
                unavailable[capability['id']] = 'feature_disabled'
            continue
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
    settings, allowed_ids=None, request_context=None, candidate_ids=None, *, contract_version=1,
    export_catalog=None,
):
    """Identifiers only, for the validator and for the bootstrap payload."""
    return [
        capability['id']
        for capability in resolve_available_capabilities(
            settings, allowed_ids=allowed_ids, request_context=request_context,
            candidate_ids=candidate_ids,
            contract_version=contract_version, export_catalog=export_catalog,
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
            **({'role': capability['role']} if 'role' in capability else {'phase': capability['phase']}),
            'summary': capability['summary'],
            'when_to_use': capability['when_to_use'],
            'inputs': capability['inputs'],
            'cost': capability['cost_class'],
            'produces': list(capability.get('produces') or ()),
            'max_per_plan': capability.get('max_per_plan'),
            **({
                'plan_contract_version': capability['plan_contract_version'],
                'result_contract_version': capability['result_contract_version'],
                'result_input_kinds': {
                    name: list(kinds) for name, kinds in capability['result_input_kinds'].items()
                },
                'partial_inputs_supported': capability['partial_inputs_supported'],
                **({'required_result_inputs': list(capability['required_result_inputs'])}
                   if capability.get('required_result_inputs') else {}),
                'result_outputs': capability['result_outputs'],
                'optional_result_outputs': capability.get('optional_result_outputs', {}),
                'result_output_kinds': list(capability.get('result_output_kinds') or ()),
                **({'result_output_variants': capability['result_output_variants']}
                   if 'result_output_variants' in capability else {}),
            } if 'role' in capability else {}),
        })
    return projection


def build_capability_client_projection(capabilities):
    """What the browser is shown, so the plan card can label and cost a step.

    Narrower than the planner's view: the card renders a step the planner already chose,
    so it needs naming and cost but not the guidance that drove the choice.
    """
    projection = []
    for capability in capabilities or ():
        projection.append({
            'id': capability['id'],
            'label': capability['label'],
            **({'role': capability['role']} if 'role' in capability else {'phase': capability['phase']}),
            'summary': capability['summary'],
            'cost': capability['cost_class'],
            'terminal': bool(capability.get('terminal')),
            **({'plan_contract_version': capability['plan_contract_version']} if 'role' in capability else {}),
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
        if capability.get('plan_contract_version') == DEPENDENCY_PLAN_CONTRACT_VERSION:
            raise CapabilityResolutionError('Document limits could not be checked.') from exc
        log_event(
            f"[ORCHESTRATION_REGISTRY] Could not resolve the document limit for "
            f"{action_type}: {exc}",
            level=logging.WARNING,
        )
        return None


def describe_registry(*, contract_version=1):
    """A stable summary for tests and for the documentation inventory."""
    capability_ids = all_capability_ids(contract_version=contract_version)
    if contract_version == DEPENDENCY_PLAN_CONTRACT_VERSION:
        return {
            'contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
            'capability_ids': capability_ids,
            'terminal_capability_id': None,
            'roles': [ROLE_GATHER, ROLE_REASON, ROLE_RENDER],
        }
    return {
        'contract_version': CAPABILITY_REGISTRY_CONTRACT_VERSION,
        'capability_ids': capability_ids,
        'terminal_capability_id': TERMINAL_CAPABILITY_ID,
        'phases': list(CAPABILITY_PHASES),
    }
