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

Version: 0.261.085
"""

import logging

from functions_appinsights import log_event

# Bumped when the descriptor shape changes in a way a stored plan could not survive.
CAPABILITY_REGISTRY_CONTRACT_VERSION = 1

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

CAPABILITY_KIND_RETRIEVAL = 'retrieval'
CAPABILITY_KIND_ANALYSIS = 'analysis'
CAPABILITY_KIND_SYNTHESIS = 'synthesis'

CAPABILITY_KINDS = (
    CAPABILITY_KIND_RETRIEVAL,
    CAPABILITY_KIND_ANALYSIS,
    CAPABILITY_KIND_SYNTHESIS,
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

# Capability identifiers. Referenced by plans, adapters and tests, so they are constants
# rather than repeated string literals.
CAPABILITY_DOCUMENT_SEARCH = 'document_search'
CAPABILITY_DOCUMENT_ANALYZE = 'document_analyze'
CAPABILITY_DOCUMENT_COMPARE = 'document_compare'
CAPABILITY_TABULAR_ANALYZE = 'tabular_analyze'
CAPABILITY_WEB_SEARCH = 'web_search'
CAPABILITY_RESPOND = 'respond'

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


def _document_action_gate(action_type):
    """Build a gate for a document action, whose enablement is a nested record."""

    def _gate(settings):
        try:
            from functions_document_actions import is_document_action_enabled

            return bool(is_document_action_enabled(action_type, settings=settings))
        except Exception as exc:
            log_event(
                f"[ORCHESTRATION_REGISTRY] Could not resolve the {action_type} document "
                f"action gate, treating it as disabled: {exc}",
                level=logging.WARNING,
            )
            return False

    return _gate


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
        'kind': CAPABILITY_KIND_RETRIEVAL,
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
        'kind': CAPABILITY_KIND_ANALYSIS,
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
                'doc_scope': {
                    'type': 'string',
                    'enum': ['all', 'personal', 'group', 'public'],
                    'default': 'all',
                },
            },
            'required': ['analysis_prompt', 'document_ids'],
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
        'kind': CAPABILITY_KIND_ANALYSIS,
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
        'kind': CAPABILITY_KIND_ANALYSIS,
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
        'kind': CAPABILITY_KIND_RETRIEVAL,
        'summary': "Look the question up on the public web.",
        'when_to_use': (
            "The question is about current events, or about something no internal document "
            "would hold. Do not use it to answer questions about the user's own material."
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
        'produces': (PRODUCES_EVIDENCE, PRODUCES_CITATIONS),
        'cost_class': COST_CLASS_LOW,
        'max_per_plan': 2,
        'adapter': CAPABILITY_WEB_SEARCH,
        'terminal': False,
    },
    {
        'id': CAPABILITY_RESPOND,
        'label': 'Answer',
        'kind': CAPABILITY_KIND_SYNTHESIS,
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

# Every plan ends with this, so the planner never has to be told to include it and a plan
# that omits it is repaired rather than rejected.
TERMINAL_CAPABILITY_ID = CAPABILITY_RESPOND


def all_capability_ids():
    """Every capability identifier, regardless of whether it is currently enabled."""
    return [capability['id'] for capability in CAPABILITY_REGISTRY]


def get_capability(capability_id):
    """Look up one descriptor, or None when the id is not registered.

    Returning None rather than raising is deliberate: the caller is usually the validator
    checking planner output, where an unknown capability is an expected kind of bad input
    rather than a programming error.
    """
    if not isinstance(capability_id, str):
        return None
    return CAPABILITY_BY_ID.get(capability_id.strip())


def _gates_pass(capability, settings):
    """Whether a capability's three gate forms all allow it."""
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


def resolve_available_capabilities(settings, allowed_ids=None):
    """The capabilities this deployment currently permits, in registry order.

    ``allowed_ids`` is the administrator's ``chat_orchestration_enabled_capabilities``
    narrowing. An empty or missing list means "everything the other gates already allow",
    because an administrator who has not expressed an opinion should not thereby disable
    the feature entirely.

    The terminal capability is never removed by the narrowing. A plan cannot end without
    it, so allowing it to be configured away would only produce plans that fail validation.
    """
    settings = settings if isinstance(settings, dict) else {}

    narrowed = None
    if isinstance(allowed_ids, (list, tuple, set)):
        narrowed = {str(value).strip() for value in allowed_ids if str(value).strip()}
        if not narrowed:
            narrowed = None

    available = []
    for capability in CAPABILITY_REGISTRY:
        if narrowed is not None and capability['id'] not in narrowed:
            if capability['id'] != TERMINAL_CAPABILITY_ID:
                continue
        if not _gates_pass(capability, settings):
            continue
        available.append(capability)

    return available


def resolve_available_capability_ids(settings, allowed_ids=None):
    """Identifiers only, for the validator and for the bootstrap payload."""
    return [
        capability['id']
        for capability in resolve_available_capabilities(settings, allowed_ids=allowed_ids)
    ]


def build_planner_capability_projection(capabilities):
    """Reduce descriptors to what the planner model is actually shown.

    Gates, adapter names and per-plan caps are deliberately withheld. They are the
    application's business, they would spend context the planner needs for the question,
    and a model told about a cap tends to argue with it rather than obey it -- the
    validator enforces caps regardless of what the model was told.
    """
    projection = []
    for capability in capabilities or ():
        projection.append({
            'id': capability['id'],
            'label': capability['label'],
            'kind': capability['kind'],
            'summary': capability['summary'],
            'when_to_use': capability['when_to_use'],
            'inputs': capability['inputs'],
            'cost': capability['cost_class'],
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
            'kind': capability['kind'],
            'summary': capability['summary'],
            'cost': capability['cost_class'],
            'terminal': bool(capability.get('terminal')),
        })
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
        log_event(
            f"[ORCHESTRATION_REGISTRY] Could not resolve the document limit for "
            f"{action_type}: {exc}",
            level=logging.WARNING,
        )
        return None


def describe_registry():
    """A stable summary for tests and for the documentation inventory."""
    return {
        'contract_version': CAPABILITY_REGISTRY_CONTRACT_VERSION,
        'capability_ids': all_capability_ids(),
        'terminal_capability_id': TERMINAL_CAPABILITY_ID,
    }
