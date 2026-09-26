# functions_orchestration_schema.py

"""
The plan and elicitation contracts, and the validator that enforces them.

**Planner output is untrusted input.** That is the single most important property in this
framework and the reason this module exists as a hard boundary rather than a set of
convenience helpers. A plan arrives as JSON written by a language model. It may name a
capability that does not exist, one the administrator has switched off, or a document the
user is not allowed to read. It may contain a dependency cycle, or twenty steps when the
deployment allows eight. None of that is exceptional; it is the expected range of a
generative system, and every one of those cases has to be caught here, before an adapter
is reached.

The validator therefore *repairs where repair is honest and drops where it is not*, and
records what it did in ``validation.repairs`` so the plan card can show the user a plan
that differs from what the model proposed and say why. Silently executing a repaired plan
would be as bad as executing an invalid one.

Two contracts live here:

``plan``
    What the planner returns and the executor runs: Gather / Reason / Render steps that
    exchange typed, retained results. Every saved plan carries the schema marker
    ``planner_contract_version`` (``DEPENDENCY_PLAN_CONTRACT_VERSION``). A plan without it,
    or with the earlier value, was written by the removed legacy contract; it is recognised
    and refused with ``LegacyPlanError`` rather than misread.

``elicitation``
    What the planner returns *instead* when it cannot plan without more information. The
    schema half is deliberately MCP-elicitation-shaped -- a restricted JSON Schema of a
    flat object with primitive properties -- so a future MCP server asking a question can
    render through the very same card. Our own paging lives in a sibling ``ui_hints``
    field rather than inside the schema, which keeps the schema itself MCP-clean.

Version: 0.261.140
"""

import hashlib
import json
import math
import uuid
from copy import deepcopy

from azure.core.exceptions import ServiceRequestError
from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError
from openai import APIConnectionError, APITimeoutError

from agent_execution_context import AgentDelegationTimeout
from functions_model_catalog import ModelCatalogError
from functions_orchestration_registry import (
    CAPABILITY_ACTION_INVOKE,
    CAPABILITY_COMPOSE,
    CAPABILITY_TABULAR_ANALYZE,
    DEPENDENCY_PLAN_CONTRACT_VERSION,
    GENERAL_KNOWLEDGE_BASES,
    admitted_export_pairs,
    get_capability,
    get_capability_document_limit,
    get_capability_result_outputs,
    required_capability_ids,
    resolve_available_capability_ids,
)
from functions_orchestration_result_contracts import (
    IMAGE_ASSET_KIND, InputBinding, InputSpec, OutputSpec, RecordColumn, ResultContractError,
    StepBindings, TaskResult, canonical_bytes, output_name, validate_input_bindings,
)
from functions_orchestration_deliverables import DeliverableError, compile_deliverables

ORCHESTRATION_ELICITATION_CONTRACT_VERSION = 2

# Shown wherever a saved plan from the removed legacy contract is opened, rerun, edited,
# restored or continued. One stable sentence, so every surface says the same thing.
LEGACY_PLAN_MESSAGE = (
    "This plan was created by an earlier orchestration version and can't be opened or "
    "rerun. Start a new request."
)
LEGACY_PLAN_CODE = 'legacy_plan'

# Plan lifecycle.
PLAN_STATUS_DRAFT = 'draft'
PLAN_STATUS_AWAITING_APPROVAL = 'awaiting_approval'
PLAN_STATUS_APPROVED = 'approved'
PLAN_STATUS_RUNNING = 'running'
PLAN_STATUS_WAITING = 'waiting'
PLAN_STATUS_COMPLETED = 'completed'
PLAN_STATUS_FAILED = 'failed'
PLAN_STATUS_CANCELLED = 'cancelled'
PLAN_STATUS_SUPERSEDED = 'superseded'

PLAN_STATUSES = (
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_AWAITING_APPROVAL,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_RUNNING,
    PLAN_STATUS_WAITING,
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_FAILED,
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_SUPERSEDED,
)

TERMINAL_PLAN_STATUSES = (
    PLAN_STATUS_COMPLETED,
    PLAN_STATUS_FAILED,
    PLAN_STATUS_CANCELLED,
    PLAN_STATUS_SUPERSEDED,
)

# Step lifecycle.
STEP_STATUS_PENDING = 'pending'
STEP_STATUS_RUNNING = 'running'
STEP_STATUS_WAITING = 'waiting'
STEP_STATUS_PARTIAL = 'partial'
STEP_STATUS_COMPLETED = 'completed'
STEP_STATUS_FAILED = 'failed'
STEP_STATUS_SKIPPED = 'skipped'
STEP_STATUS_CANCELLED = 'cancelled'

STEP_STATUSES = (
    STEP_STATUS_PENDING,
    STEP_STATUS_RUNNING,
    STEP_STATUS_WAITING,
    STEP_STATUS_PARTIAL,
    STEP_STATUS_COMPLETED,
    STEP_STATUS_FAILED,
    STEP_STATUS_SKIPPED,
    STEP_STATUS_CANCELLED,
)

# Approval.
APPROVAL_MODE_MANUAL = 'manual'
APPROVAL_MODE_TIMED = 'timed'
APPROVAL_MODE_AUTO = 'auto'
APPROVAL_MODES = (APPROVAL_MODE_MANUAL, APPROVAL_MODE_TIMED, APPROVAL_MODE_AUTO)

APPROVAL_STATE_PENDING = 'pending'
APPROVAL_STATE_APPROVED = 'approved'
APPROVAL_STATE_REJECTED = 'rejected'
APPROVAL_STATE_EXPIRED = 'expired'
APPROVAL_STATES = (
    APPROVAL_STATE_PENDING,
    APPROVAL_STATE_APPROVED,
    APPROVAL_STATE_REJECTED,
    APPROVAL_STATE_EXPIRED,
)

# Complexity, as reported by triage.
COMPLEXITY_TRIVIAL = 'trivial'
COMPLEXITY_SIMPLE = 'simple'
COMPLEXITY_COMPLEX = 'complex'
COMPLEXITIES = (COMPLEXITY_TRIVIAL, COMPLEXITY_SIMPLE, COMPLEXITY_COMPLEX)

# MCP elicitation response actions, named exactly as the specification names them.
ELICITATION_ACTION_ACCEPT = 'accept'
ELICITATION_ACTION_DECLINE = 'decline'
ELICITATION_ACTION_CANCEL = 'cancel'
ELICITATION_ACTIONS = (
    ELICITATION_ACTION_ACCEPT,
    ELICITATION_ACTION_DECLINE,
    ELICITATION_ACTION_CANCEL,
)

# MCP restricts elicitation schemas to a flat object of primitives so any client can render
# one without a general JSON Schema implementation. Enforced rather than assumed, because
# the planner writes these and a nested schema would reach a card that cannot draw it.
ELICITATION_PRIMITIVE_TYPES = ('string', 'number', 'integer', 'boolean')
ELICITATION_MAX_PROPERTIES = 12
ELICITATION_MAX_ENUM_VALUES = 40
ELICITATION_MAX_ARRAY_ITEMS = 100

# Hard ceilings, independent of the administrator's own limits. These bound what the
# validator will even consider, so a malformed plan cannot cost anything to reject.
PLAN_HARD_MAX_STEPS = 30
PLAN_MAX_TITLE_LENGTH = 200
PLAN_MAX_RATIONALE_LENGTH = 600
PLAN_MAX_SUMMARY_LENGTH = 600
PLAN_MAX_ASSUMPTIONS = 8


class PlanValidationError(ValueError):
    """Raised when a plan cannot be repaired into something safe to run."""

    def __init__(self, message, *, code='plan_invalid', rule=None):
        self.code = code
        self.rule = rule
        super().__init__(message)


class LegacyPlanError(PlanValidationError):
    """A saved plan from the removed legacy contract. It is never interpreted."""

    def __init__(self):
        super().__init__(LEGACY_PLAN_MESSAGE, code=LEGACY_PLAN_CODE)
        self.message = LEGACY_PLAN_MESSAGE


def is_legacy_plan(plan):
    """Whether a saved plan predates the current contract: no marker, or the earlier one.

    A missing marker is never read as the current contract, and a legacy plan is never
    interpreted, so every caller that finds one refuses it with ``LEGACY_PLAN_MESSAGE``.
    """
    if not isinstance(plan, dict):
        return True
    version = plan.get('planner_contract_version')
    return version is None or (type(version) is int and version == 1)


def plan_contract_version(plan):
    """The current contract marker of a saved plan, or a refusal.

    Raises ``LegacyPlanError`` for a plan written by the removed legacy contract and
    ``PlanValidationError`` for any other unrecognized marker.
    """
    if is_legacy_plan(plan):
        raise LegacyPlanError()
    version = plan['planner_contract_version']
    if type(version) is not int or version != DEPENDENCY_PLAN_CONTRACT_VERSION:
        raise PlanValidationError('Unsupported orchestration plan contract.', code='plan_version_unsupported')
    return version


def _text(value, limit=None):
    """Coerce to a trimmed string, optionally truncated."""
    if value is None:
        return ''
    text = str(value).strip()
    if limit is not None and len(text) > limit:
        text = text[:limit].rstrip()
    return text


def _string_list(value, limit=None):
    """Coerce to a list of non-empty trimmed strings, preserving order."""
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        value = [value]
    if not isinstance(value, (list, tuple, set)):
        return []
    seen = set()
    out = []
    for item in value:
        text = _text(item)
        if not text or text in seen:
            continue
        seen.add(text)
        out.append(text)
        if limit is not None and len(out) >= limit:
            break
    return out


def new_plan_id():
    return f"plan_{uuid.uuid4().hex}"


def new_run_id():
    return f"run_{uuid.uuid4().hex}"


def new_step_id(index):
    return f"step_{index + 1}"


def new_turn_id():
    """Identity for one user turn, stable across every re-plan of it.

    Distinct from ``plan_id`` and ``run_id``, both of which are minted afresh each time a
    turn is planned again -- after an elicitation is answered, or after a step asks for a
    re-plan. A client keying its card on either would lose track of the card it is already
    showing the moment the plan it describes is replaced.
    """
    return f"turn_{uuid.uuid4().hex}"


def build_request_fingerprint(user_message, seeds=None, revision=0):
    """A stable identity for "this request, planned this way".

    Used for idempotency, matching the ``request_fingerprint`` idea already proven in
    ``functions_tabular_orchestration.py``: a retried plan request for an unchanged
    question should be recognisable rather than producing a second run.
    """
    payload = json.dumps(
        {
            'message': _text(user_message),
            'seeds': seeds if isinstance(seeds, dict) else {},
            'revision': int(revision or 0),
        },
        sort_keys=True,
        default=str,
    )
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


# --------------------------------------------------------------------------------------
# Scalar coercion for elicitation answers
# --------------------------------------------------------------------------------------

def _coerce_scalar(value, expected_type):
    """Best-effort coercion of a submitted scalar.

    A form routinely returns "12" where the schema says integer. Rejecting that would
    discard an otherwise good answer over a quoting habit, so the narrow and unambiguous
    coercions are performed and anything else is refused.
    """
    if expected_type == 'string':
        return _text(value) if not isinstance(value, bool) else None
    if expected_type == 'integer':
        if isinstance(value, bool):
            return None
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None
    if expected_type == 'number':
        if isinstance(value, bool):
            return None
        try:
            return float(str(value).strip())
        except (TypeError, ValueError):
            return None
    if expected_type == 'boolean':
        if isinstance(value, bool):
            return value
        text = _text(value).lower()
        if text in ('true', 'yes', '1'):
            return True
        if text in ('false', 'no', '0'):
            return False
        return None
    return value


# --------------------------------------------------------------------------------------
# Plan validation
# --------------------------------------------------------------------------------------

def order_dependency_steps(steps):
    """Stable topological order that keeps every declared edge."""
    pending = list(steps)
    ordered = []
    completed = set()
    while pending:
        ready = next((
            step for step in pending if set(step.get('depends_on') or ()).issubset(completed)
        ), None)
        if ready is None:
            raise PlanValidationError('The plan has a cycle or missing dependency.', code='result_binding_cycle')
        ordered.append(ready)
        completed.add(ready['step_id'])
        pending.remove(ready)
    return ordered


def validate_inline_output_schema(schema):
    """Only self-contained JSON schemas; validation cannot fetch remote definitions."""
    if type(schema) is not dict or len(canonical_bytes(schema)) > 32768:
        raise PlanValidationError('The prepared output schema is invalid.')
    pending = [schema]
    while pending:
        value = pending.pop()
        if isinstance(value, dict):
            if any(key in value for key in ('$ref', '$dynamicRef', '$recursiveRef')):
                raise PlanValidationError('Prepared output schemas must be self-contained.')
            pending.extend(value.values())
        elif isinstance(value, list):
            pending.extend(value)
    try:
        Draft202012Validator.check_schema(schema)
    except SchemaError as exc:
        raise PlanValidationError('The prepared output schema is invalid.') from exc


def step_input_specs(step):
    capability = get_capability(step.get('capability_id'), contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION)
    if capability is None or type(step.get('inputs', {})) is not dict:
        raise PlanValidationError('The step has invalid named inputs.')
    accepted = capability['result_input_kinds']
    if not set(capability.get('required_result_inputs') or ()).issubset(step.get('inputs', {})):
        raise PlanValidationError('The capability requires an explicit named input.')
    specs = []
    for name, value in step.get('inputs', {}).items():
        if type(value) is not dict or set(value) - {'binding', 'allow_partial', 'optional'} or 'binding' not in value:
            raise PlanValidationError('Each named input requires an explicit result binding.')
        kinds = accepted.get(name, accepted.get('*'))
        if not kinds:
            raise PlanValidationError('This capability does not accept that named input.')
        if value.get('allow_partial') is True and not capability['partial_inputs_supported']:
            raise PlanValidationError('This capability requires complete named inputs.')
        if type(value.get('optional', False)) is not bool:
            raise PlanValidationError('Input optionality must be a boolean.')
        if value.get('optional') is True and not capability.get('optional_inputs_supported'):
            raise PlanValidationError('This capability cannot proceed without a named input.')
        specs.append(InputSpec(
            name, InputBinding.from_dict(value['binding']), tuple(kinds), value.get('allow_partial', False),
            value.get('optional', False),
        ))
    return tuple(specs)


def optional_input_producers(step):
    """Producers a step can run without, because every binding to them is optional."""
    required, optional = set(), set()
    for spec in step_input_specs(step):
        if spec.binding.step_id is not None:
            (optional if spec.optional else required).add(spec.binding.step_id)
    return optional - required


def step_result_bindings(step):
    return StepBindings(
        step['step_id'], step.get('enabled', True),
        tuple(OutputSpec(item['name'], item['kind']) for item in step['outputs']),
        step_input_specs(step), tuple(step.get('depends_on', [])),
    )


def _dependency_outputs(raw, capability, composition_profiles, arguments):
    required, optional = get_capability_result_outputs(capability, arguments)
    fixed = [{'name': name, 'kind': kind} for name, kind in required.items()]
    outputs = raw.get('outputs', fixed)
    if capability['role'] == 'render':
        if outputs != []:
            raise PlanValidationError('Render delivers files, not named retained data outputs.')
        return []
    if type(outputs) is not list or not 1 <= len(outputs) <= 32:
        raise PlanValidationError('Each step must declare its supported named outputs.')
    if capability['id'] != CAPABILITY_COMPOSE:
        allowed = {**required, **optional}
        for output in outputs:
            if type(output) is not dict or set(output) != {'name', 'kind'}:
                raise PlanValidationError('The output declaration does not match the producing capability.')
            OutputSpec(output['name'], output['kind'])
            if allowed.get(output['name']) != output['kind']:
                raise PlanValidationError('The output declaration does not match the producing capability.')
        if not set(required).issubset({output['name'] for output in outputs}):
            raise PlanValidationError('The output declaration does not match the producing capability.')
        return deepcopy(outputs)
    supported = capability['result_output_kinds']
    for item in outputs:
        if (
            type(item) is not dict or set(item) - {'name', 'kind', 'columns', 'schema', 'profile'}
            or not {'name', 'kind'}.issubset(item)
        ):
            raise PlanValidationError('The composition output declaration is invalid.')
        OutputSpec(item['name'], item['kind'])
        if item['kind'] not in supported:
            raise PlanValidationError('The composition output kind is unsupported.')
        if item['kind'] == 'records-v1':
            columns = item.get('columns')
            if type(columns) is not list or not columns:
                raise PlanValidationError('Records require an explicit ordered column schema.')
            parsed = tuple(RecordColumn.from_dict(column) for column in columns)
            if len(parsed) > 256 or len({column.name for column in parsed}) != len(parsed):
                raise PlanValidationError('The record column schema is invalid.')
        elif 'columns' in item:
            raise PlanValidationError('Only records may declare columns.')
        if 'schema' in item:
            if item['kind'] != 'structured-v1':
                raise PlanValidationError('An inline schema requires structured content.')
            validate_inline_output_schema(item['schema'])
        if 'profile' in item:
            if (
                item['kind'] != 'structured-v1' or type(item['profile']) is not str
                or item['profile'] not in (composition_profiles or {})
            ):
                raise PlanValidationError('The prepared-content profile is unavailable.')
    return deepcopy(outputs)


def _validate_render_requests(steps, existing_results, export_catalog=None):
    admitted_pairs = admitted_export_pairs(export_catalog) if export_catalog is not None else None
    renders = [step for step in steps if step['capability_id'] == 'render_file']
    if not renders:
        return
    # The shared registry validates representation compatibility without rendering.
    from functions_generated_file_exports import GeneratedFileExportError, GeneratedFileExportRequest
    from functions_generated_export_registry import resolve_generated_file_export_format

    produced = {
        (step['step_id'], output['name']): output['kind']
        for step in steps for output in step['outputs']
    }
    for step in renders:
        source = step_input_specs(step)[0].binding
        kind = (
            existing_results[source.existing_result].kind if source.existing_result is not None
            else produced[(source.step_id, source.output_name)]
        )
        capability = get_capability('render_file', contract_version=2)
        arguments = step['arguments']
        if admitted_pairs is not None and (arguments['output_format'], arguments['profile']) not in admitted_pairs:
            raise PlanValidationError(
                'The requested file format and profile are not admitted for this plan.',
                code='capability_unavailable',
            )
        options = deepcopy(arguments.get('options') or {})
        if 'columns' in options:
            options['columns'] = tuple(options['columns'])
        request = GeneratedFileExportRequest(
            output_format=arguments['output_format'], profile=arguments['profile'], **options,
        )
        try:
            resolve_generated_file_export_format(request, capability['render_source_kinds'][kind])
        except GeneratedFileExportError as exc:
            raise PlanValidationError(
                'The requested file representation does not support its bound source or options.',
                code='result_kind_incompatible',
            ) from exc


def _optional_input_kind(spec, produced, existing_results):
    if spec.binding.existing_result is not None:
        reference = (existing_results or {}).get(spec.binding.existing_result)
        return getattr(reference, 'kind', None)
    return produced.get((spec.binding.step_id, spec.binding.output_name))


def _apply_image_input_policy(steps, existing_results):
    """A generated image is illustrative: its consumer can always be written without it.

    Image inputs are therefore optional, so one failed image never blocks the answer or a
    file; the delivery notes report it. Only the answer basis rules the other inputs.
    """
    produced = {
        (step['step_id'], output['name']): output['kind'] for step in steps for output in step['outputs']
    }
    for step in steps:
        for value in step['inputs'].values():
            if type(value) is not dict or type(value.get('binding')) is not dict:
                continue
            binding = InputBinding.from_dict(value['binding'])
            if (
                step['capability_id'] == CAPABILITY_COMPOSE and binding.step_id is not None
                and produced.get((binding.step_id, binding.output_name)) == IMAGE_ASSET_KIND
            ):
                value['optional'] = True
    for step in steps:
        specs = step_input_specs(step)
        knowledge_optional = [
            spec for spec in specs
            if spec.optional and _optional_input_kind(spec, produced, existing_results) != IMAGE_ASSET_KIND
        ]
        if knowledge_optional and step['arguments'].get('knowledge_basis') not in GENERAL_KNOWLEDGE_BASES:
            raise PlanValidationError(
                'An optional input requires an answer basis that allows general knowledge.',
            )


def validate_dependency_plan(
    plan, *, settings=None, authorized_document_ids=None, available_capability_ids=None,
    agent_names=None, action_refs=None, existing_results=None, composition_profiles=None,
    export_catalog=None, deliverable_availability=None, image_selected=False,
):
    """Compile a plan without dropping required work, arguments, outputs, or dependencies.

    ``deliverable_availability`` is the server truth a new plan is checked against; see
    ``functions_orchestration_deliverables.compile_deliverables``.
    """
    settings = settings or {}
    canonical_bytes(composition_profiles or {})
    try:
        max_steps = min(PLAN_HARD_MAX_STEPS, max(1, int(settings.get('chat_orchestration_max_steps') or 8)))
    except (TypeError, ValueError):
        max_steps = 8
    raw_steps = plan.get('steps')
    if type(raw_steps) is not list or not raw_steps or len(raw_steps) > max_steps:
        raise PlanValidationError('The complete plan exceeds the available step budget.', code='result_step_limit')
    if available_capability_ids is None:
        available_capability_ids = resolve_available_capability_ids(
            settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
            contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION,
            export_catalog=export_catalog,
        )
    available = set(available_capability_ids)
    accepted = []
    counts = {}
    fields = {
        'step_id', 'capability_id', 'title', 'rationale', 'arguments', 'depends_on',
        'optional', 'enabled', 'estimated_cost', 'role', 'status', 'inputs', 'outputs',
        # Auto routing: the planner may name a task category; only the server assigns a binding.
        'model_task', 'model_binding',
        # Deliverables: the planner names what a step delivers; the server derives its brief.
        'delivers', 'deliverable_context',
    }
    try:
        for raw in raw_steps:
            if type(raw) is not dict or set(raw) - fields:
                raise PlanValidationError('The plan contains an invalid step field.')
            output_name(raw.get('step_id'))
            capability = get_capability(raw.get('capability_id'), contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION)
            if capability is None or capability['id'] not in available or capability.get('runtime_unavailable_reason'):
                raise PlanValidationError('A required capability is unknown or disabled.', code='capability_unavailable')
            capability_id = capability['id']
            if 'role' in raw and raw['role'] != capability['role']:
                raise PlanValidationError('Capability purpose is server-owned.')
            if any(type(raw.get(key, default)) is not bool for key, default in (('enabled', True), ('optional', False))):
                raise PlanValidationError('Step enablement and optionality must be booleans.')
            if type(raw.get('depends_on', [])) is not list:
                raise PlanValidationError('Dependencies must be a list of step IDs.')
            if 'model_task' in raw and (type(raw['model_task']) is not str or not raw['model_task'].strip()):
                raise PlanValidationError('A model task must be a named task category.')
            if 'model_binding' in raw and type(raw['model_binding']) is not dict:
                raise PlanValidationError('A model binding is server-owned structured data.')
            counts[capability_id] = counts.get(capability_id, 0) + 1
            if capability['max_per_plan'] is not None and counts[capability_id] > capability['max_per_plan']:
                raise PlanValidationError('The plan exceeds a capability work limit.', code='result_step_limit')
            arguments = raw.get('arguments', {})
            if type(arguments) is not dict:
                raise PlanValidationError('Step arguments must be an object.')
            canonical_bytes(arguments)
            if not Draft202012Validator(capability['inputs']).is_valid(arguments):
                raise PlanValidationError('Step arguments do not match the capability contract.')
            arguments = deepcopy(arguments)
            if capability_id == CAPABILITY_TABULAR_ANALYZE:
                # Native query/transform validators run only for explicitly admitted native work.
                from functions_orchestration_native_results import validate_native_orchestration_arguments

                try:
                    arguments = validate_native_orchestration_arguments(arguments)
                except ValueError as exc:
                    raise PlanValidationError('The native computation arguments are unsupported.') from exc
            if any(isinstance(value, str) and not value.strip() for value in arguments.values()):
                raise PlanValidationError('String arguments must not be empty or whitespace.')
            for name, rule in capability['inputs']['properties'].items():
                if name not in arguments and 'default' in rule:
                    arguments[name] = deepcopy(rule['default'])
            if 'agent_name' in arguments and arguments['agent_name'] not in (agent_names or ()):
                raise PlanValidationError('The selected agent is unavailable.')
            if 'action_ref' in arguments and arguments['action_ref'] not in (action_refs or ()):
                raise PlanValidationError('The selected action is unavailable.')
            limit = get_capability_document_limit(capability, settings=settings)
            for name in ('document_ids', 'right_document_ids'):
                if name in arguments:
                    if any(not value or value != value.strip() for value in arguments[name]):
                        raise PlanValidationError('Document IDs must be exact, nonempty identifiers.')
                    if len(set(arguments[name])) != len(arguments[name]):
                        raise PlanValidationError('Document selections must not contain duplicates.')
                    if limit and len(arguments[name]) > limit:
                        raise PlanValidationError('The complete source selection exceeds the document limit.')
                    if authorized_document_ids is not None and set(arguments[name]) - set(authorized_document_ids):
                        raise PlanValidationError('A required source is unavailable.')
            if (
                'left_document_id' in arguments
                and arguments['left_document_id'] != arguments['left_document_id'].strip()
            ):
                raise PlanValidationError('Document IDs must be exact, nonempty identifiers.')
            if (
                'left_document_id' in arguments and authorized_document_ids is not None
                and arguments['left_document_id'] not in authorized_document_ids
            ):
                raise PlanValidationError('A required comparison source is unavailable.')
            if arguments.get('left_document_id') in arguments.get('right_document_ids', []):
                raise PlanValidationError('A comparison source and its targets must be distinct.')
            step = {
                'step_id': raw['step_id'], 'capability_id': capability_id,
                'title': _text(raw.get('title'), PLAN_MAX_TITLE_LENGTH) or capability['label'],
                'rationale': _text(raw.get('rationale'), PLAN_MAX_RATIONALE_LENGTH),
                'arguments': arguments, 'depends_on': list(raw.get('depends_on', [])),
                'inputs': deepcopy(raw.get('inputs', {})),
                'outputs': _dependency_outputs(raw, capability, composition_profiles, arguments),
                'optional': raw.get('optional', False), 'enabled': raw.get('enabled', True),
                'estimated_cost': capability['cost_class'], 'role': capability['role'],
                'status': STEP_STATUS_PENDING,
                **({'model_task': raw['model_task'].strip()} if 'model_task' in raw else {}),
                **({'model_binding': deepcopy(raw['model_binding'])} if 'model_binding' in raw else {}),
                **({'delivers': deepcopy(raw['delivers'])} if 'delivers' in raw else {}),
            }
            step_input_specs(step)
            if capability_id == 'document_analyze' and not arguments.get('document_ids') and 'sources' not in step['inputs']:
                raise PlanValidationError(
                    'Analyze requires arguments.document_ids with the selected IDs, or an inputs.sources '
                    'source-set binding. Mentioning a filename in analysis_prompt is not a source binding.',
                    code='source_binding_required', rule='document_sources_required',
                )
            if capability_id == 'document_analyze' and arguments.get('document_ids') and 'sources' in step['inputs']:
                raise PlanValidationError('Use either explicit document IDs or a named source-set input.')
            accepted.append(step)
        if not any(step['enabled'] for step in accepted):
            raise PlanValidationError('The plan contains no enabled work.')
        _apply_image_input_policy(accepted, existing_results)
        bindings = [step_result_bindings(step) for step in accepted]
        dependencies = validate_input_bindings(bindings, existing_results=existing_results, max_steps=max_steps)
        _validate_render_requests(accepted, existing_results, export_catalog=export_catalog)
        final_binding = None
        if plan.get('final_response') is not None:
            final_binding = InputBinding.from_dict(plan['final_response'])
            validate_input_bindings(
                [*bindings, StepBindings(
                    '__final_response__', True, inputs=(
                        InputSpec('answer', final_binding, ('text-v1', 'markdown-v1'), allow_partial=True),
                    ),
                )],
                existing_results=existing_results, max_steps=max_steps + 1,
            )
        for step in accepted:
            step['depends_on'] = list(dependencies[step['step_id']])
        # A producer that only feeds optional inputs is not required work: its failure is
        # disclosed by the consumer instead of failing the whole plan. The final response and
        # any required binding keep it required.
        final_producer = final_binding.step_id if final_binding is not None else None
        consumers = {}
        for step in accepted:
            for spec in step_input_specs(step):
                if spec.binding.step_id is not None:
                    consumers.setdefault(spec.binding.step_id, []).append(spec.optional)
        for step in accepted:
            uses = consumers.get(step['step_id'])
            if uses and all(uses) and step['step_id'] != final_producer:
                step['optional'] = True
        deliverables = compile_deliverables(
            plan.get('deliverables'), accepted, final_response=plan.get('final_response'),
            availability=deliverable_availability, image_selected=image_selected,
        )
    except ResultContractError as exc:
        raise PlanValidationError('The plan has an invalid or unavailable result binding.', code=exc.code) from exc
    except DeliverableError as exc:
        raise PlanValidationError(exc.message, code=exc.code, rule=exc.rule) from exc
    compiled = deepcopy(plan)
    if final_binding is None:
        compiled.pop('final_response', None)
    compiled.update({
        'planner_contract_version': DEPENDENCY_PLAN_CONTRACT_VERSION,
        'deliverables': deliverables,
        'steps': order_dependency_steps(accepted),
        'validation': {'ok': True, 'errors': [], 'repairs': []},
    })
    return compiled


def validate_plan(
    plan,
    settings=None,
    authorized_document_ids=None,
    available_capability_ids=None,
    agent_names=None,
    action_refs=None,
    *,
    existing_results=None,
    composition_profiles=None,
    export_catalog=None,
    contract_version=None,
    deliverable_availability=None,
    image_selected=False,
):
    """Make a planner-authored plan safe to run, or refuse it.

    ``authorized_document_ids`` is the set of documents this user may read *right now*. It
    is applied here and applied again before finalization in the executor, because the two
    moments are not the same moment and access can be revoked between them.

    ``agent_names`` and ``action_refs`` are the agents and actions this user can actually
    reach. A planner naming anything else is refused exactly like a planner naming an
    unknown capability, rather than handed to an adapter that would go looking for an
    integration nobody offered.

    Required work, arguments, outputs and dependencies are never dropped to make a plan
    fit: a plan that cannot run as written raises ``PlanValidationError``. A plan without
    the current schema marker was written by the removed legacy contract and raises
    ``LegacyPlanError``.
    """
    version = plan_contract_version(plan)
    if contract_version is not None and (type(contract_version) is not int or contract_version != version):
        raise PlanValidationError('The saved plan contract does not match the admitted contract.')
    return validate_dependency_plan(
        plan, settings=settings, authorized_document_ids=authorized_document_ids,
        available_capability_ids=available_capability_ids, agent_names=agent_names,
        action_refs=action_refs, existing_results=existing_results,
        composition_profiles=composition_profiles,
        export_catalog=export_catalog,
        deliverable_availability=deliverable_availability, image_selected=image_selected,
    )


def plan_document_ids(plan, *, include_disabled=False):
    """Read named sources before authorization, without treating their presence as access."""
    document_ids = []
    for step in (plan or {}).get('steps') or ():
        if not isinstance(step, dict) or (
            not include_disabled and not step.get('enabled', True)
        ):
            continue
        arguments = step.get('arguments')
        if not isinstance(arguments, dict):
            continue
        for field in ('document_ids', 'right_document_ids', 'left_document_id'):
            document_ids.extend(_string_list(arguments.get(field)))
    return list(dict.fromkeys(document_ids))


def effective_plan_document_ids(plan, seeds=None):
    """Include an implicit search filter supplied by the user's selected sources."""
    document_ids = plan_document_ids(plan)
    if any(
        step.get('enabled', True) and step.get('capability_id') == 'document_search'
        and not (step.get('arguments') or {}).get('document_ids')
        for step in (plan or {}).get('steps') or ()
    ):
        document_ids.extend(_string_list((seeds or {}).get('document_ids')))
    return list(dict.fromkeys(document_ids))


def validate_plan_document_source_kinds(plan, document_source_kinds):
    """Check known source kinds without treating model-supplied labels as authority."""
    if not isinstance(document_source_kinds, dict):
        raise PlanValidationError('Document type metadata is unavailable.', code='source_metadata_invalid')
    for step in plan.get('steps') or []:
        if not step.get('enabled', True) or step.get('capability_id') not in (
            'document_analyze', 'document_compare',
        ):
            continue
        if any(
            document_source_kinds.get(document_id) in ('tabular', 'unsupported', 'unresolved')
            for document_id in plan_document_ids({'steps': [step]})
        ):
            raise PlanValidationError(
                f'Step "{step["step_id"]}" uses a source kind that narrative document analysis '
                'cannot process. Use offered tabular_analyze work for tabular sources, then '
                'compose across the prepared results. Keep every selected source.',
                code='source_kind_invalid', rule='narrative_source_required',
            )


def validate_plan_requirements(plan, seeds=None, *, allow_changes=False):
    """Do not silently lose selected operations or sources during normalization.

    Editor revisions require explicit review and may change earlier selections. Make
    those changes visible rather than blocking a user's later narrowing instruction.
    """
    seeds = seeds or {}
    steps = [step for step in plan.get('steps') or () if step.get('enabled', True)]
    used = {step.get('capability_id') for step in steps}
    missing = set(required_capability_ids(seeds)) - used
    selected_documents = set(_string_list(seeds.get('document_ids')))
    used_documents = set(effective_plan_document_ids(plan, seeds))
    messages = [
        f"The plan does not use the selected {get_capability(value)['label']} operation."
        if get_capability(value) else 'A selected operation is not available.'
        for value in sorted(missing)
    ]
    if selected_documents - used_documents:
        messages.append('The plan does not use all selected documents.')
    if messages and not allow_changes:
        raise PlanValidationError(' '.join(messages))
    if messages:
        repairs = plan.setdefault('validation', {}).setdefault('repairs', [])
        for message in messages:
            warning = f'{message} Review this change before running.'
            if warning not in repairs:
                repairs.append(warning)
    return plan


def build_plan_inputs(plan, seeds=None, document_labels=None, actions=None):
    """Describe what the plan will actually act on, for the approval card.

    Derived from the validated steps rather than from what the planner claimed, because
    the two can differ: a step may have had unauthorized documents removed, or been
    dropped entirely. The card has to show the plan that will run, not the one proposed.

    ``document_labels`` maps ids to display names. It is optional because a plan is still
    describable without it -- an id is a poor label but an honest one, and failing to
    resolve a name is not a reason to refuse to show the plan.
    """
    seeds = seeds if isinstance(seeds, dict) else {}
    labels = document_labels if isinstance(document_labels, dict) else {}

    document_ids = effective_plan_document_ids(plan, seeds)
    action_refs = []
    uses_web = False
    for step in (plan or {}).get('steps') or ():
        if not step.get('enabled', True):
            continue
        if step.get('capability_id') == 'web_search':
            uses_web = True
        arguments = step.get('arguments') or {}
        if step.get('capability_id') == CAPABILITY_ACTION_INVOKE:
            action_ref = arguments.get('action_ref')
            if action_ref and action_ref not in action_refs:
                action_refs.append(action_ref)
    selected = set(seeds.get('document_ids') or ())

    # Named, not quoted. The plan document is stored and shown, and the prompt's full wording
    # is already in the message the plan was built from; repeating it here would duplicate an
    # unbounded string into every plan that used a prompt.
    seed_prompt = seeds.get('prompt')
    prompt = None
    if isinstance(seed_prompt, dict):
        prompt = {'id': seed_prompt.get('id'), 'name': seed_prompt.get('name')}

    return {
        'documents': [
            {
                'document_id': document_id,
                'display_name': labels.get(document_id) or document_id,
                'selected_by_user': document_id in selected,
            }
            for document_id in document_ids
        ],
        'web': uses_web,
        'required_capabilities': required_capability_ids(seeds),
        'actions': [
            {
                'action_ref': action['action_ref'],
                'display_name': _text(action.get('display_name') or action.get('name'), 200),
                'scope_label': _text(action.get('scope_label'), 200),
            }
            for action in actions or ()
            if isinstance(action, dict) and action.get('action_ref') in action_refs
        ],
        'agent': seeds.get('agent'),
        'model': seeds.get('model'),
        'prompt': prompt,
    }


def build_plan_outputs(plan):
    """What the run will produce: the answer, plus every enabled step's retained results."""
    return [{'kind': 'message'}] + [
        {'kind': 'retained_result', 'source_step_id': step['step_id'], **deepcopy(output)}
        for step in plan['steps'] if step.get('enabled', True) for output in step['outputs']
    ]


def normalize_plan(
    plan,
    conversation_id,
    user_id,
    settings=None,
    approval_mode=None,
    authorized_document_ids=None,
    available_capability_ids=None,
    turn_id=None,
    seeds=None,
    document_labels=None,
    agent_names=None,
    actions=None,
    *,
    contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION,
    existing_results=None,
    composition_profiles=None,
    export_catalog=None,
    deliverable_availability=None,
    image_selected=False,
):
    """Turn raw planner output into a complete, validated plan document.

    ``deliverable_availability`` and ``image_selected`` check a new plan's deliverables
    against what the server can produce right now.
    """
    settings = settings if isinstance(settings, dict) else {}
    plan = dict(plan) if isinstance(plan, dict) else {}
    requested_version = plan.get('planner_contract_version', contract_version)
    if type(requested_version) is not int or requested_version != contract_version:
        raise PlanValidationError('A model cannot change the admitted plan contract.')
    plan_contract_version({'planner_contract_version': contract_version})

    # Bindings are server-owned. A planner response cannot authorize a deployment.
    plan.pop('model_routing', None)
    for step in plan.get('steps') or []:
        if isinstance(step, dict):
            step.pop('model_binding', None)

    intent = plan.get('intent') if isinstance(plan.get('intent'), dict) else {}
    complexity = _text(intent.get('complexity')).lower()
    if complexity not in COMPLEXITIES:
        complexity = COMPLEXITY_SIMPLE

    mode = _text(approval_mode).lower()
    if mode not in APPROVAL_MODES:
        mode = _text(settings.get('chat_orchestration_default_approval_mode')).lower()
    if mode not in APPROVAL_MODES:
        mode = APPROVAL_MODE_MANUAL

    try:
        timeout_seconds = int(settings.get('chat_orchestration_timed_approval_seconds') or 10)
    except (TypeError, ValueError):
        timeout_seconds = 10

    plan.update({
        'plan_id': plan.get('plan_id') or new_plan_id(),
        'run_id': plan.get('run_id') or new_run_id(),
        # Identifies the user's turn rather than this attempt at planning it. Re-planning
        # after an elicitation mints a new plan_id and run_id, so a client keying anything
        # on those would lose track of the card it is already showing.
        'turn_id': _text(turn_id) or _text(plan.get('turn_id')) or new_turn_id(),
        'revision': int(plan.get('revision') or 0),
        'conversation_id': conversation_id,
        'user_id': user_id,
        'planner_contract_version': contract_version,
        'intent': {
            'summary': _text(intent.get('summary'), PLAN_MAX_SUMMARY_LENGTH),
            'complexity': complexity,
            'confidence': intent.get('confidence'),
        },
        'assumptions': _string_list(plan.get('assumptions'), limit=PLAN_MAX_ASSUMPTIONS),
        'approval': {
            'mode': mode,
            'timeout_seconds': max(3, min(timeout_seconds, 120)),
            'state': APPROVAL_STATE_PENDING,
            'approved_at': None,
            'approved_by': None,
            'edited': False,
        },
    })

    plan = validate_plan(
        plan,
        settings=settings,
        authorized_document_ids=authorized_document_ids,
        available_capability_ids=available_capability_ids,
        agent_names=agent_names,
        action_refs=[
            action.get('action_ref') for action in actions or () if isinstance(action, dict)
        ],
        existing_results=existing_results,
        composition_profiles=composition_profiles,
        export_catalog=export_catalog,
        contract_version=contract_version,
        deliverable_availability=deliverable_availability,
        image_selected=image_selected,
    )

    plan['inputs'] = build_plan_inputs(
        plan, seeds=seeds, document_labels=document_labels, actions=actions,
    )
    plan['outputs'] = build_plan_outputs(plan)

    # A plan nobody has to look at is approved on arrival; everything else waits. Timed
    # mode waits too, because the countdown belongs to the browser -- a server that
    # pre-approved it would leave the user watching a countdown that could not be stopped.
    plan['status'] = (
        PLAN_STATUS_APPROVED if mode == APPROVAL_MODE_AUTO else PLAN_STATUS_AWAITING_APPROVAL
    )
    if mode == APPROVAL_MODE_AUTO:
        plan['approval']['state'] = APPROVAL_STATE_APPROVED

    return plan


def apply_plan_edits(
    plan, edits, *, existing_results=None, composition_profiles=None,
    export_catalog=None, contract_version=None,
):
    """Apply a user's edits to a plan before it runs.

    Only two things are editable, and both narrow the plan rather than widening it:
    disabling a step, and removing documents from one. A user may not add a capability or
    a document through this path, because doing so would let the browser assemble a plan
    that never passed the planner's own reasoning or the authorization check that followed
    it. Widening belongs to re-planning, which goes back through validation.
    """
    if contract_version is not None and (
        type(contract_version) is not int or contract_version != plan_contract_version(plan)
    ):
        raise PlanValidationError('The saved plan contract does not match the admitted contract.')
    plan_contract_version(plan)
    if not isinstance(edits, dict):
        return plan
    original = plan
    plan = deepcopy(plan)

    disabled = set(_string_list(edits.get('disabled_step_ids')))
    removed_documents = edits.get('removed_document_ids')
    removed_documents = removed_documents if isinstance(removed_documents, dict) else {}

    edited = False
    for step in plan.get('steps') or ():
        if step['step_id'] in disabled and step.get('enabled', True):
            step['enabled'] = False
            edited = True
        drop = set(_string_list(removed_documents.get(step['step_id'])))
        if not drop:
            continue
        for field in ('document_ids', 'right_document_ids'):
            if field not in step.get('arguments', {}):
                continue
            kept = [value for value in step['arguments'][field] if value not in drop]
            if len(kept) != len(step['arguments'][field]):
                step['arguments'][field] = kept
                edited = True

    if edited:
        plan.setdefault('approval', {})['edited'] = True
    try:
        if not any(step['enabled'] for step in plan['steps']):
            raise PlanValidationError('The plan contains no enabled work.')
        for step in plan['steps']:
            capability = get_capability(step['capability_id'])
            if not Draft202012Validator(capability['inputs']).is_valid(step['arguments']):
                raise PlanValidationError('This edit leaves a required source unavailable.')
            if composition_profiles is not None:
                _dependency_outputs(step, capability, composition_profiles, step['arguments'])
            if (
                step['enabled'] and step['capability_id'] == 'document_analyze'
                and not step['arguments'].get('document_ids') and 'sources' not in step['inputs']
            ):
                raise PlanValidationError('This edit leaves Analyze without a source.')
        validate_input_bindings(
            [step_result_bindings(step) for step in plan['steps']], existing_results=existing_results,
            max_steps=PLAN_HARD_MAX_STEPS,
        )
        _validate_render_requests(plan['steps'], existing_results, export_catalog=export_catalog)
        if plan.get('final_response'):
            binding = InputBinding.from_dict(plan['final_response'])
            if binding.step_id and not next(
                step['enabled'] for step in plan['steps'] if step['step_id'] == binding.step_id
            ):
                raise PlanValidationError('The selected answer producer cannot be disabled.')
        # A step the user switched off changes what an answer step writes for, such as a
        # file it no longer feeds. The saved plan must describe exactly what will run, so
        # checkpoints and retries compare the same deliverable briefs the executor derives.
        plan['deliverables'] = compile_deliverables(
            plan.get('deliverables'), plan['steps'], final_response=plan.get('final_response'),
        )
    except ResultContractError as exc:
        raise PlanValidationError('This edit leaves a required result unavailable.', code=exc.code) from exc
    except DeliverableError as exc:
        raise PlanValidationError(exc.message, code=exc.code, rule=exc.rule) from exc
    original.update(plan)
    return original


def summarize_plan(plan):
    """A compact description for the collapsed card, the ledger and message metadata."""
    steps = [step for step in (plan or {}).get('steps') or () if step.get('enabled', True)]
    return {
        'run_id': (plan or {}).get('run_id'),
        'plan_id': (plan or {}).get('plan_id'),
        'turn_id': (plan or {}).get('turn_id'),
        'intent_summary': ((plan or {}).get('intent') or {}).get('summary', ''),
        'step_count': len(steps),
        'capabilities_used': list(dict.fromkeys(
            step.get('capability_id') for step in steps if step.get('capability_id')
        )),
        'status': (plan or {}).get('status'),
    }


# --------------------------------------------------------------------------------------
# Step results
# --------------------------------------------------------------------------------------

FAILURE_CONTRACT_VERSION = 1
FAILURE_MESSAGES = {
    'user_cancelled': 'You stopped this run. Already submitted external actions may still finish.',
    'step_timeout': 'This step did not finish before its time limit.',
    'run_timeout': 'The run reached its total time limit before all work could finish.',
    'step_budget': 'The run reached its step limit before all work could finish.',
    'delegation_timeout': 'The delegated agent did not finish before its time limit.',
    'provider_timeout': 'The service used by this step timed out.',
    'provider_http_error': 'The service used by this step returned an unsuccessful HTTP response.',
    'provider_not_configured': 'The service used by this step is not configured for this deployment.',
    'provider_failed': 'The service used by this step reported an error before returning results.',
    'connection_failed': 'This step could not connect to the service it uses.',
    'execution_interrupted': 'This step stopped unexpectedly. The underlying cause was not recorded.',
    'execution_expired': 'The execution lease expired before the worker recorded a final outcome.',
    'ownership_lost': 'This execution no longer owns the attempt and cannot publish further results.',
    'context_unavailable': 'The original context or access changed. Review the request and create a new plan.',
    'analysis_result_unavailable': 'The saved Analyze result is unavailable. No answer was generated from an incomplete preview.',
    'analysis_result_not_saved': 'The analysis completed, but its final data could not be saved for reuse.',
    'analysis_input_too_large': 'The complete saved analysis exceeds the selected model input budget. No data was truncated or re-analyzed. Select a larger model or use a supported complete-record reader.',
    'result_unavailable': 'A required retained result is unavailable or changed. No preview was substituted.',
    'result_invalid': 'The operation did not produce the complete named results declared by the plan.',
    'result_input_too_large': 'The complete named inputs exceed the selected model budget. No input was truncated. Use a larger model or revise the plan.',
    'result_not_ready': 'Required computation is still pending. Its result is not ready to consume.',
    'result_commit_unconfirmed': 'The producer stopped before its retained completion checkpoint was confirmed. Its work will not be repeated automatically.',
    'result_partial': 'Required work produced only an explicitly limited partial result.',
    'dependency_unavailable': 'A required dependency did not complete. This operation was not executed.',
    'file_publication_not_allowed': 'Gathering and reasoning cannot create downloadable files.',
    'checkpoint_unavailable': 'Progress could not be saved or verified. This attempt cannot safely resume.',
    'checkpoint_storage_unavailable': 'Saved progress storage is temporarily unavailable. Verification can be retried without repeating completed work.',
    'checkpoint_invalid': 'Saved progress could not be verified. Review the request and create a new plan.',
    'recovery_changed': 'Saved step inputs changed. Previously completed work will not be repeated.',
    'model_failed': 'The answering model could not complete the reply.',
    'model_routing_changed': 'The approved model or its capabilities changed. Review a new plan before running.',
    'image_content_refused': 'The image service declined this image prompt under its content policy.',
    'image_generation_unavailable': 'Image generation is not available for this deployment right now.',
    'image_request_invalid': 'The image model did not accept the planned image request.',
    'retry_would_repeat': 'A retry would send the same request that was declined. Ask again with a different description instead.',
    'step_failed': 'This operation could not complete.',
    'message_not_saved': 'The explanation could not be saved. Reload this run to check its durable status.',
    LEGACY_PLAN_CODE: LEGACY_PLAN_MESSAGE,
}


def build_failure(code='step_failed', *, step_id=None, capability_id=None, provider_status=None):
    """Only application-owned text may cross a failure boundary."""
    code = code if code in FAILURE_MESSAGES else 'step_failed'
    result = {'code': code, 'message': FAILURE_MESSAGES[code]}
    if step_id:
        result['step_id'] = _text(step_id, 200)
    if capability_id:
        result['capability_id'] = _text(capability_id, 100)
    if isinstance(provider_status, int) and not isinstance(provider_status, bool) and 400 <= provider_status <= 599:
        result['provider_status'] = provider_status
        if code == 'provider_http_error':
            result['message'] = f'The service used by this step returned HTTP {provider_status}.'
    return result


def safe_failure(value, *, step_id=None, capability_id=None):
    value = value if isinstance(value, dict) else {}
    return build_failure(
        value.get('code'), step_id=step_id or value.get('step_id'),
        capability_id=capability_id or value.get('capability_id'),
        provider_status=value.get('provider_status'),
    )


def failure_from_exception(exc, *, answering=False, _depth=0):
    """Use types and structured status, never diagnostic prose or model content."""
    if isinstance(exc, ModelCatalogError):
        return build_failure('model_routing_changed')
    status = getattr(exc, 'status_code', None)
    if not isinstance(status, int):
        status = getattr(getattr(exc, 'response', None), 'status_code', None)
    if isinstance(status, int) and 400 <= status <= 599:
        return build_failure('provider_http_error', provider_status=status)
    if isinstance(exc, AgentDelegationTimeout):
        return build_failure('delegation_timeout')
    if isinstance(exc, (TimeoutError, APITimeoutError)):
        return build_failure('provider_timeout')
    if isinstance(exc, (ConnectionError, APIConnectionError, ServiceRequestError)):
        return build_failure('connection_failed')
    cause = getattr(exc, '__cause__', None)
    if cause is not None and cause is not exc and _depth < 3:
        return failure_from_exception(cause, answering=answering, _depth=_depth + 1)
    return build_failure('model_failed' if answering else 'step_failed')


# Failures one bounded retry of a read-only step could plausibly outlast. Configuration,
# authorization and validation failures are never retried; they would fail the same way.
TRANSIENT_FAILURE_CODES = frozenset({'provider_timeout', 'connection_failed', 'provider_failed'})
TRANSIENT_PROVIDER_STATUSES = frozenset({408, 429, 500, 502, 503, 504})


def failure_is_transient(failure):
    """Whether an application-owned failure describes a transient provider condition."""
    failure = failure if isinstance(failure, dict) else {}
    code = failure.get('code')
    if code in TRANSIENT_FAILURE_CODES:
        return True
    return code == 'provider_http_error' and failure.get('provider_status') in TRANSIENT_PROVIDER_STATUSES


# Failures in which a service declined or rejected the planned request itself. A checkpoint
# retry resends exactly the same request, so it would reproduce them.
REQUEST_REFUSAL_FAILURE_CODES = frozenset({'image_content_refused', 'image_request_invalid'})


def failure_repeats_on_retry(failure):
    """Whether resending the same planned request would reproduce this failure."""
    failure = failure if isinstance(failure, dict) else {}
    return failure.get('code') in REQUEST_REFUSAL_FAILURE_CODES


def failure_explanation(failures, *, partial=False, cancelled=False):
    facts = [safe_failure(value)['message'] for value in failures or []]
    facts = list(dict.fromkeys(facts))
    heading = 'The run was stopped.' if cancelled else (
        'The request was only partially completed.' if partial else 'The request could not be completed.'
    )
    return heading + ('\n\n' + '\n'.join(facts) if facts else '') + (
        '\n\nCheck the run details for saved progress and retry availability.'
    )


def build_step_result(
    status=STEP_STATUS_COMPLETED,
    summary='',
    evidence=None,
    citations=None,
    artifacts=None,
    notes=None,
    error=None,
    replan_hint=None,
    message=None,
    failure=None,
    saved_analyses=None,
    analysis_consumption=None,
    task_result=None,
    wait=None,
):
    """The single shape every capability adapter returns.

    Defined here rather than in the executor so that adapters and executor cannot drift:
    the adapters are the widest part of this framework and the easiest place for a
    divergent return shape to go unnoticed until a plan fails at runtime.

    ``evidence`` entries are mixed-source evidence envelopes, which is why nothing here
    tries to re-describe them -- ``functions_mixed_source_orchestration.build_evidence_envelope``
    already owns that contract, complete with its byte bounds.

    ``replan_hint`` is how a step says the plan was wrong: a short sentence about what it
    discovered, handed back to the planner. It is bounded by the run's replan budget, so a
    step cannot loop the plan forever by always asking for another one.
    """
    if status not in STEP_STATUSES:
        status = STEP_STATUS_COMPLETED
    result = {
        'status': status,
        'summary': _text(summary, PLAN_MAX_SUMMARY_LENGTH),
        'evidence': list(evidence or ()),
        'citations': list(citations or ()),
        'artifacts': list(artifacts or ()),
        'notes': _string_list(notes),
        'error': _text(error) or None,
        'replan_hint': _text(replan_hint) or None,
        'message': message,
        'failure': safe_failure(failure) if failure else None,
    }
    if saved_analyses:
        result['saved_analyses'] = [dict(item) for item in saved_analyses]
    if analysis_consumption:
        result['analysis_consumption'] = dict(analysis_consumption)
    if task_result is not None:
        if type(task_result) is not TaskResult:
            raise ResultContractError('result_contract_invalid')
        result['task_result'] = task_result
    if wait is not None:
        if type(wait) is not dict:
            raise ResultContractError('result_wait_invalid')
        if len(canonical_bytes(wait)) > 32768:
            raise ResultContractError('result_wait_invalid')
        result['wait'] = deepcopy(wait)
    return result


# --------------------------------------------------------------------------------------
# Elicitation
# --------------------------------------------------------------------------------------

def validate_elicitation_schema(requested_schema):
    """Enforce the MCP restriction: a flat object of primitive properties.

    Returns ``(schema, errors)``. MCP restricts elicitation schemas this way so that any
    client can render one without implementing JSON Schema in general, and this framework
    holds to the restriction rather than merely aiming at it -- the card is a paged form,
    and a nested object would arrive as something it cannot draw.
    """
    errors = []
    requested_schema = requested_schema if isinstance(requested_schema, dict) else {}

    properties = requested_schema.get('properties')
    if not isinstance(properties, dict) or not properties:
        return None, ['The question set declared no fields.']

    clean_properties = {}
    for name, rules in list(properties.items())[:ELICITATION_MAX_PROPERTIES]:
        if not isinstance(rules, dict):
            errors.append(f"Field '{name}' is not an object.")
            continue

        field_type = _text(rules.get('type')).lower() or 'string'
        is_array = field_type == 'array'
        item_type = 'string'

        if is_array:
            items = rules.get('items') if isinstance(rules.get('items'), dict) else {}
            item_type = _text(items.get('type')).lower() or 'string'
            if item_type not in ELICITATION_PRIMITIVE_TYPES:
                errors.append(f"Field '{name}' is an array of a non-primitive type.")
                continue
        elif field_type not in ELICITATION_PRIMITIVE_TYPES:
            errors.append(f"Field '{name}' uses unsupported type '{field_type}'.")
            continue

        clean = {'type': 'array' if is_array else field_type}
        if is_array:
            item_rules = {'type': item_type}
            source_items = rules.get('items') if isinstance(rules.get('items'), dict) else {}
            enum_values = source_items.get('enum')
            if isinstance(enum_values, list) and enum_values:
                item_rules['enum'] = enum_values[:ELICITATION_MAX_ENUM_VALUES]
            clean['items'] = item_rules
            for bound in ('minItems', 'maxItems'):
                value = rules.get(bound)
                if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
                    clean[bound] = min(value, ELICITATION_MAX_ARRAY_ITEMS)
        else:
            enum_values = rules.get('enum')
            if isinstance(enum_values, list) and enum_values:
                clean['enum'] = enum_values[:ELICITATION_MAX_ENUM_VALUES]

        for passthrough in ('title', 'description', 'default'):
            if passthrough in rules:
                clean[passthrough] = rules[passthrough]

        clean_properties[_text(name)] = clean

    if not clean_properties:
        return None, errors or ['No renderable fields survived validation.']

    required = [
        name for name in _string_list(requested_schema.get('required'))
        if name in clean_properties
    ]

    return (
        {'type': 'object', 'properties': clean_properties, 'required': required},
        errors,
    )


def normalize_elicitation(elicitation, run_id, revision=0, candidate_references=None):
    """Normalize questions; resource suggestions come only from resolved candidates."""
    elicitation = elicitation if isinstance(elicitation, dict) else {}

    schema, errors = validate_elicitation_schema(elicitation.get('requested_schema'))
    if schema is None:
        raise PlanValidationError(
            'The planner asked a question that could not be rendered: ' + '; '.join(errors)
        )

    names = list(schema['properties'].keys())
    hints = elicitation.get('ui_hints') if isinstance(elicitation.get('ui_hints'), dict) else {}

    order = [name for name in _string_list(hints.get('order')) if name in schema['properties']]
    order += [name for name in names if name not in order]

    # Paging is ours, not MCP's, so it lives beside the schema rather than inside it. One
    # field per page reads as an interview rather than a form, which is the point of asking
    # in a card instead of in the thread.
    pages = []
    covered = set()
    raw_pages = hints.get('pages') if isinstance(hints.get('pages'), list) else []
    for page in raw_pages[:ELICITATION_MAX_PROPERTIES]:
        page_fields = [
            name for name in _string_list(page)
            if name in schema['properties'] and name not in covered
        ]
        if page_fields:
            pages.append(page_fields)
            covered.update(page_fields)
    remainder = [name for name in order if name not in covered]
    pages.extend([[name] for name in remainder])

    ui_hints = {'order': order, 'pages': pages}
    references = {
        reference['id']: reference
        for reference in (candidate_references or ())
        if isinstance(reference, dict)
        and reference.get('kind') in ('document', 'chat_attachment')
        and isinstance(reference.get('id'), str)
        and isinstance(reference.get('scope'), dict)
    }
    fields = hints.get('fields') if isinstance(hints.get('fields'), dict) else {}
    resource_fields = {}
    for name, hint in fields.items():
        if name not in schema['properties'] or not isinstance(hint, dict):
            continue
        if hint.get('input') != 'files':
            continue
        rules = schema['properties'][name]
        value_rules = rules.get('items', {}) if rules['type'] == 'array' else rules
        if value_rules.get('type') != 'string':
            continue
        # File suggestions are deliberately not an exhaustive enum. An authorized file
        # selected elsewhere (including a new upload) is equally valid.
        value_rules.pop('enum', None)
        candidate_ids = hint.get('candidate_ids')
        if candidate_ids is None:
            candidate_ids = [
                item.get('id') for item in hint.get('candidates') or ()
                if isinstance(item, dict)
            ] if 'candidates' in hint else list(references)
        resource_fields[name] = {
            'input': 'files',
            'candidates': [
                references[document_id]
                for document_id in _string_list(candidate_ids, ELICITATION_MAX_ENUM_VALUES)
                if document_id in references
            ],
        }
    if resource_fields:
        ui_hints['fields'] = resource_fields

    return {
        'elicitation_id': f"ask_{uuid.uuid4().hex}",
        'contract_version': ORCHESTRATION_ELICITATION_CONTRACT_VERSION,
        'run_id': run_id,
        'revision': int(revision or 0),
        'message': _text(elicitation.get('message'), PLAN_MAX_SUMMARY_LENGTH)
        or 'I need a little more information before I can plan this.',
        'requested_schema': schema,
        'ui_hints': ui_hints,
    }


def validate_elicitation_response(elicitation, response):
    """Validate an ``{action, content}`` response against the schema that was asked.

    The shape is MCP's verbatim, so the same validation serves an answer typed into our
    card and one that arrives from an MCP client.
    """
    response = response if isinstance(response, dict) else {}
    action = _text(response.get('action')).lower()
    if action not in ELICITATION_ACTIONS:
        return None, [f"'{action or 'missing'}' is not a valid response action."]

    if action != ELICITATION_ACTION_ACCEPT:
        # Declining or cancelling carries no content, and reading any would be a way to
        # smuggle answers past the user's refusal.
        return {'action': action, 'content': {}}, []

    schema = (elicitation or {}).get('requested_schema') or {}
    properties = schema.get('properties') or {}
    required = set(schema.get('required') or ())
    content = response.get('content') if isinstance(response.get('content'), dict) else {}

    cleaned = {}
    errors = [
        f"'{name}' is not a question field."
        for name in content if name not in properties
    ]
    if 'content' in response and not isinstance(response.get('content'), dict):
        errors.append('Answer content must be an object.')

    for name, rules in properties.items():
        if name not in content or content[name] is None:
            continue
        raw = content[name]
        if rules.get('type') == 'array':
            item_type = (rules.get('items') or {}).get('type', 'string')
            allowed = (rules.get('items') or {}).get('enum')
            values = raw if isinstance(raw, (list, tuple)) else [raw]
            maximum = min(rules.get('maxItems', ELICITATION_MAX_ARRAY_ITEMS), ELICITATION_MAX_ARRAY_ITEMS)
            if len(values) > maximum:
                errors.append(f"'{name}' allows at most {maximum} values.")
                continue
            coerced = []
            for item in values:
                if not isinstance(item, (str, int, float, bool)):
                    errors.append(f"'{name}' contains an invalid value.")
                    continue
                value = _coerce_scalar(item, item_type)
                if value is None or value == '' or (isinstance(value, float) and not math.isfinite(value)):
                    errors.append(f"'{name}' contains an invalid {item_type}.")
                    continue
                if allowed and value not in allowed:
                    errors.append(f"'{name}' contains a value that was not offered.")
                    continue
                coerced.append(value)
            cleaned[name] = coerced
            if len(coerced) < rules.get('minItems', 0):
                errors.append(f"'{name}' needs at least {rules['minItems']} values.")
            continue

        if not isinstance(raw, (str, int, float, bool)):
            errors.append(f"'{name}' must be a primitive value.")
            continue
        value = _coerce_scalar(raw, rules.get('type', 'string'))
        if value is None or value == '' or (isinstance(value, float) and not math.isfinite(value)):
            errors.append(f"'{name}' is not a valid {rules.get('type', 'string')}.")
            continue
        allowed = rules.get('enum')
        if allowed and value not in allowed:
            errors.append(f"'{name}' is not one of the offered choices.")
            continue
        cleaned[name] = value

    for name in required:
        if name not in cleaned or cleaned[name] == []:
            errors.append(f"'{name}' is required.")

    if errors:
        return None, errors

    return {'action': action, 'content': cleaned}, []
