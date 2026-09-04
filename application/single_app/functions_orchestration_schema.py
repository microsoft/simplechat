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
    What the planner returns and the executor runs. Versioned by
    ``ORCHESTRATION_PLAN_CONTRACT_VERSION`` so a plan persisted by an older build is
    recognised rather than misread.

``elicitation``
    What the planner returns *instead* when it cannot plan without more information. The
    schema half is deliberately MCP-elicitation-shaped -- a restricted JSON Schema of a
    flat object with primitive properties -- so a future MCP server asking a question can
    render through the very same card. Our own paging lives in a sibling ``ui_hints``
    field rather than inside the schema, which keeps the schema itself MCP-clean.

Version: 0.261.085
"""

import hashlib
import json
import logging
import uuid

from functions_appinsights import log_event
from functions_orchestration_registry import (
    TERMINAL_CAPABILITY_ID,
    get_capability,
    get_capability_document_limit,
    phase_index,
    resolve_available_capability_ids,
)

ORCHESTRATION_PLAN_CONTRACT_VERSION = 1
ORCHESTRATION_ELICITATION_CONTRACT_VERSION = 1

# Plan lifecycle.
PLAN_STATUS_DRAFT = 'draft'
PLAN_STATUS_AWAITING_APPROVAL = 'awaiting_approval'
PLAN_STATUS_APPROVED = 'approved'
PLAN_STATUS_RUNNING = 'running'
PLAN_STATUS_COMPLETED = 'completed'
PLAN_STATUS_FAILED = 'failed'
PLAN_STATUS_CANCELLED = 'cancelled'
PLAN_STATUS_SUPERSEDED = 'superseded'

PLAN_STATUSES = (
    PLAN_STATUS_DRAFT,
    PLAN_STATUS_AWAITING_APPROVAL,
    PLAN_STATUS_APPROVED,
    PLAN_STATUS_RUNNING,
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
STEP_STATUS_COMPLETED = 'completed'
STEP_STATUS_FAILED = 'failed'
STEP_STATUS_SKIPPED = 'skipped'
STEP_STATUS_CANCELLED = 'cancelled'

STEP_STATUSES = (
    STEP_STATUS_PENDING,
    STEP_STATUS_RUNNING,
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

# Hard ceilings, independent of the administrator's own limits. These bound what the
# validator will even consider, so a malformed plan cannot cost anything to reject.
PLAN_HARD_MAX_STEPS = 30
PLAN_MAX_TITLE_LENGTH = 200
PLAN_MAX_RATIONALE_LENGTH = 600
PLAN_MAX_SUMMARY_LENGTH = 600
PLAN_MAX_ASSUMPTIONS = 8


class PlanValidationError(ValueError):
    """Raised when a plan cannot be repaired into something safe to run."""


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
# Argument validation against a capability's input schema
# --------------------------------------------------------------------------------------

def _coerce_scalar(value, expected_type):
    """Best-effort coercion of a planner-supplied scalar.

    A model routinely returns "12" where the schema says integer. Rejecting that would
    discard an otherwise good plan over a quoting habit, so the narrow and unambiguous
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


def validate_step_arguments(capability, arguments):
    """Check one step's arguments against its capability's input schema.

    Returns ``(cleaned_arguments, errors)``. Only the properties the schema declares
    survive: ``additionalProperties`` is false throughout the registry, and a planner that
    invents an argument must not have it forwarded to an adapter that would either ignore
    it or, worse, pass it on.
    """
    schema = (capability or {}).get('inputs') or {}
    properties = schema.get('properties') or {}
    required = set(schema.get('required') or ())
    arguments = arguments if isinstance(arguments, dict) else {}

    cleaned = {}
    errors = []

    for name, rules in properties.items():
        if name not in arguments or arguments[name] is None:
            if 'default' in rules:
                cleaned[name] = rules['default']
            continue

        raw = arguments[name]
        expected_type = rules.get('type')

        if expected_type == 'array':
            items_rules = rules.get('items') or {}
            values = raw if isinstance(raw, (list, tuple)) else [raw]
            coerced = []
            for item in values:
                item_value = _coerce_scalar(item, items_rules.get('type', 'string'))
                if item_value is None or item_value == '':
                    continue
                if item_value not in coerced:
                    coerced.append(item_value)
            min_items = rules.get('minItems')
            if min_items is not None and len(coerced) < min_items:
                errors.append(f"'{name}' needs at least {min_items} value(s)")
                continue
            cleaned[name] = coerced
            continue

        value = _coerce_scalar(raw, expected_type)
        if value is None or (expected_type == 'string' and value == ''):
            errors.append(f"'{name}' is not a valid {expected_type}")
            continue

        enum_values = rules.get('enum')
        if enum_values and value not in enum_values:
            # A default is a better answer than a rejection when the model picked an
            # out-of-range enum: the step is still meaningful, just less specific.
            if 'default' in rules:
                value = rules['default']
            else:
                errors.append(f"'{name}' must be one of {sorted(enum_values)}")
                continue

        if expected_type == 'string':
            min_length = rules.get('minLength')
            if min_length is not None and len(value) < min_length:
                errors.append(f"'{name}' is empty")
                continue

        if expected_type in ('integer', 'number'):
            minimum = rules.get('minimum')
            maximum = rules.get('maximum')
            if minimum is not None:
                value = max(minimum, value)
            if maximum is not None:
                value = min(maximum, value)

        cleaned[name] = value

    for name in required:
        if name not in cleaned:
            errors.append(f"'{name}' is required")

    return cleaned, errors


# --------------------------------------------------------------------------------------
# Plan validation
# --------------------------------------------------------------------------------------

def _enforce_phase_order(steps):
    """Sort steps into phase order and drop dependencies that point backwards.

    Returns ``(ordered_steps, repairs)``.

    A plan runs knowledge, then reasoning, then output. A step that gathers after the
    answer has been written is not merely out of order -- it would run, cost money, and
    contribute nothing, because the answer it was meant to inform has already been
    composed. The same is true of a dependency pointing from an earlier phase to a later
    one: honouring it would drag the later step forward, which is the very inversion the
    phase order exists to prevent.

    The sort is stable, so within a phase the planner's own ordering survives untouched and
    the topological pass that follows still decides what actually depends on what.
    """
    repairs = []

    ordered = sorted(steps, key=lambda step: phase_index(step.get('capability_id')))
    position = {
        step['step_id']: phase_index(step.get('capability_id')) for step in ordered
    }

    for step in ordered:
        own_phase = position.get(step['step_id'], 0)
        kept = []
        for dependency in step.get('depends_on') or ():
            if position.get(dependency, own_phase) > own_phase:
                repairs.append(
                    f"Step '{step['step_id']}' waited on '{dependency}', which runs in a "
                    f"later phase; the dependency was dropped."
                )
                continue
            kept.append(dependency)
        step['depends_on'] = kept

    return ordered, repairs


def _order_steps(steps):
    """Topologically order steps, or report the ids caught in a cycle.

    Returns ``(ordered_steps, cyclic_step_ids)``. A cycle is not repairable by reordering,
    so the caller drops the dependencies rather than the steps -- a plan that runs its
    steps in a defensible order is more useful than no plan at all.
    """
    by_id = {step['step_id']: step for step in steps}
    resolved = []
    permanent = set()
    temporary = set()
    cyclic = set()

    def visit(step_id):
        if step_id in permanent:
            return
        if step_id in temporary:
            cyclic.add(step_id)
            return
        temporary.add(step_id)
        for dependency in by_id[step_id].get('depends_on') or ():
            if dependency in by_id:
                visit(dependency)
        temporary.discard(step_id)
        permanent.add(step_id)
        resolved.append(by_id[step_id])

    for step in steps:
        visit(step['step_id'])

    return resolved, cyclic


def validate_plan(
    plan,
    settings=None,
    authorized_document_ids=None,
    available_capability_ids=None,
    agent_names=None,
):
    """Make a planner-authored plan safe to run, or refuse it.

    ``authorized_document_ids`` is the set of documents this user may read *right now*. It
    is applied here and applied again before finalization in the executor, because the two
    moments are not the same moment and access can be revoked between them.

    ``agent_names`` is the set of agents this user can actually reach. A planner naming
    anything else is treated exactly like a planner naming an unknown capability: the step
    is dropped rather than handed to an adapter that would go looking for an agent nobody
    offered. ``None`` means the caller resolved no catalog, so agent steps cannot be
    checked and are refused outright -- an agent step with no catalog behind it has no way
    to succeed.

    Returns the plan with ``steps``, ``validation`` and ``status`` settled. Raises
    ``PlanValidationError`` only when nothing runnable survives.
    """
    settings = settings if isinstance(settings, dict) else {}
    plan = plan if isinstance(plan, dict) else {}

    errors = []
    repairs = []

    if available_capability_ids is None:
        available_capability_ids = resolve_available_capability_ids(
            settings,
            allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        )
    available = set(available_capability_ids or ())

    known_agents = None
    if agent_names is not None:
        known_agents = {
            str(value).strip() for value in agent_names if str(value).strip()
        }

    authorized = None
    if authorized_document_ids is not None:
        authorized = {str(value) for value in authorized_document_ids}

    try:
        max_steps = int(settings.get('chat_orchestration_max_steps') or 8)
    except (TypeError, ValueError):
        max_steps = 8
    max_steps = max(1, min(max_steps, PLAN_HARD_MAX_STEPS))

    raw_steps = plan.get('steps')
    raw_steps = raw_steps if isinstance(raw_steps, list) else []

    accepted = []
    used_counts = {}
    seen_ids = set()

    for index, raw in enumerate(raw_steps):
        if not isinstance(raw, dict):
            errors.append(f"Step {index + 1} is not an object and was dropped.")
            continue

        capability_id = _text(raw.get('capability_id'))
        capability = get_capability(capability_id)

        if capability is None:
            errors.append(f"Step {index + 1} names an unknown capability '{capability_id}'.")
            continue

        if capability_id not in available:
            errors.append(
                f"Step {index + 1} uses '{capability_id}', which is not enabled here."
            )
            continue

        cap_limit = capability.get('max_per_plan')
        if cap_limit is not None and used_counts.get(capability_id, 0) >= cap_limit:
            repairs.append(
                f"Dropped an extra '{capability_id}' step; at most {cap_limit} are allowed."
            )
            continue

        arguments, argument_errors = validate_step_arguments(capability, raw.get('arguments'))
        if argument_errors:
            errors.append(
                f"Step {index + 1} ({capability_id}): " + '; '.join(argument_errors)
            )
            continue

        # An agent step may only name an agent the caller can actually reach. A planner
        # inventing a plausible-sounding agent is as likely as one inventing a capability,
        # and is caught the same way rather than being discovered by an adapter searching a
        # catalog that never contained it.
        if 'agent_name' in arguments:
            if known_agents is None:
                errors.append(
                    f"Step {index + 1} asks for an agent, but no agent catalog was "
                    f"resolved for this request."
                )
                continue
            if arguments['agent_name'] not in known_agents:
                errors.append(
                    f"Step {index + 1} names an agent this user cannot reach: "
                    f"'{arguments['agent_name']}'."
                )
                continue

        # Document authorization, and the administrator's per-action document ceiling.
        for field in ('document_ids', 'right_document_ids'):
            if field not in arguments:
                continue
            if authorized is not None:
                permitted = [value for value in arguments[field] if value in authorized]
                if len(permitted) != len(arguments[field]):
                    repairs.append(
                        f"Step {index + 1} referenced documents this user cannot read; "
                        f"they were removed."
                    )
                arguments[field] = permitted
            limit = get_capability_document_limit(capability, settings=settings)
            if limit and len(arguments[field]) > limit:
                repairs.append(
                    f"Step {index + 1} was trimmed to {limit} document(s), the configured "
                    f"maximum for this action."
                )
                arguments[field] = arguments[field][:limit]

        if 'left_document_id' in arguments and authorized is not None:
            if arguments['left_document_id'] not in authorized:
                errors.append(
                    f"Step {index + 1} compares against a document this user cannot read."
                )
                continue

        # A step whose documents have all been removed has nothing left to do.
        emptied = [
            field
            for field in ('document_ids', 'right_document_ids')
            if field in arguments
            and not arguments[field]
            and field in set((capability.get('inputs') or {}).get('required') or ())
        ]
        if emptied:
            errors.append(
                f"Step {index + 1} ({capability_id}) has no readable documents left."
            )
            continue

        step_id = _text(raw.get('step_id')) or new_step_id(len(accepted))
        if step_id in seen_ids:
            step_id = new_step_id(len(accepted))
            repairs.append(f"Renamed a duplicate step id to '{step_id}'.")
        seen_ids.add(step_id)

        accepted.append({
            'step_id': step_id,
            'capability_id': capability_id,
            'title': _text(raw.get('title'), PLAN_MAX_TITLE_LENGTH) or capability['label'],
            'rationale': _text(raw.get('rationale'), PLAN_MAX_RATIONALE_LENGTH),
            'arguments': arguments,
            'depends_on': _string_list(raw.get('depends_on'), limit=max_steps),
            'optional': bool(raw.get('optional', False)),
            'enabled': bool(raw.get('enabled', True)),
            'estimated_cost': capability['cost_class'],
            'phase': capability['phase'],
            'status': STEP_STATUS_PENDING,
        })
        used_counts[capability_id] = used_counts.get(capability_id, 0) + 1

    # Dependencies pointing at steps that did not survive are simply dropped: the step
    # itself is still meaningful, it just no longer waits for something that is not coming.
    surviving = {step['step_id'] for step in accepted}
    for step in accepted:
        kept = [value for value in step['depends_on'] if value in surviving and value != step['step_id']]
        if len(kept) != len(step['depends_on']):
            repairs.append(f"Step '{step['step_id']}' waited on a step that was removed.")
        step['depends_on'] = kept

    # Phase order first, so the topological pass below sorts within a plan that already
    # runs knowledge before reasoning before output rather than one that merely could.
    accepted, phase_repairs = _enforce_phase_order(accepted)
    repairs.extend(phase_repairs)

    ordered, cyclic = _order_steps(accepted)
    if cyclic:
        repairs.append(
            "Removed circular dependencies between steps: " + ', '.join(sorted(cyclic)) + '.'
        )
        for step in ordered:
            if step['step_id'] in cyclic:
                step['depends_on'] = []
        ordered, _ = _order_steps(ordered)

    # Every plan ends by answering. A planner that forgot is repaired rather than refused,
    # because the gathering it did choose is usually right and re-planning costs a round
    # trip to fix something mechanical.
    terminal_steps = [
        step for step in ordered if step['capability_id'] == TERMINAL_CAPABILITY_ID
    ]
    non_terminal = [
        step for step in ordered if step['capability_id'] != TERMINAL_CAPABILITY_ID
    ]

    if len(non_terminal) > max_steps - 1:
        dropped = len(non_terminal) - (max_steps - 1)
        non_terminal = non_terminal[: max_steps - 1]
        repairs.append(
            f"Dropped {dropped} step(s); this deployment allows at most {max_steps} per plan."
        )

    if terminal_steps:
        # Keep exactly one, and keep it last regardless of where it was proposed.
        terminal = terminal_steps[0]
        if len(terminal_steps) > 1:
            repairs.append("Removed a duplicate answering step; a plan ends only once.")
    else:
        terminal = {
            'step_id': new_step_id(len(non_terminal)),
            'capability_id': TERMINAL_CAPABILITY_ID,
            'title': get_capability(TERMINAL_CAPABILITY_ID)['label'],
            'rationale': '',
            'arguments': {},
            'depends_on': [],
            'optional': False,
            'enabled': True,
            'estimated_cost': get_capability(TERMINAL_CAPABILITY_ID)['cost_class'],
            'status': STEP_STATUS_PENDING,
        }
        repairs.append("Added the answering step the plan ended without.")

    surviving = {step['step_id'] for step in non_terminal}
    terminal['depends_on'] = [
        value for value in terminal.get('depends_on') or () if value in surviving
    ] or list(surviving)
    terminal['enabled'] = True
    terminal['optional'] = False

    final_steps = non_terminal + [terminal]

    if not final_steps:
        raise PlanValidationError('The plan contained no runnable steps.')

    plan['steps'] = final_steps
    plan['validation'] = {
        'ok': not errors,
        'errors': errors,
        'repairs': repairs,
    }
    plan.setdefault('planner_contract_version', ORCHESTRATION_PLAN_CONTRACT_VERSION)

    if errors or repairs:
        log_event(
            f"[ORCHESTRATION_SCHEMA] Plan validated with {len(errors)} error(s) and "
            f"{len(repairs)} repair(s).",
            level=logging.INFO,
        )

    return plan


def build_plan_inputs(plan, seeds=None, document_labels=None):
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

    document_ids = []
    uses_web = False
    for step in (plan or {}).get('steps') or ():
        if not step.get('enabled', True):
            continue
        if step.get('capability_id') == 'web_search':
            uses_web = True
        arguments = step.get('arguments') or {}
        for field in ('document_ids', 'right_document_ids'):
            for value in arguments.get(field) or ():
                if value not in document_ids:
                    document_ids.append(value)
        single = arguments.get('left_document_id')
        if single and single not in document_ids:
            document_ids.append(single)

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
        'agent': seeds.get('agent'),
        'model': seeds.get('model'),
        'prompt': prompt,
    }


def build_plan_outputs(plan):
    """What the run will produce. Every plan produces an answer; some also produce files."""
    outputs = [{'kind': 'message'}]
    for step in (plan or {}).get('steps') or ():
        if not step.get('enabled', True):
            continue
        capability = get_capability(step.get('capability_id'))
        if capability and 'artifacts' in (capability.get('produces') or ()):
            outputs.append({'kind': 'artifact', 'source_step_id': step.get('step_id')})
    return outputs


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
):
    """Turn raw planner output into a complete, validated plan document."""
    settings = settings if isinstance(settings, dict) else {}
    plan = dict(plan) if isinstance(plan, dict) else {}

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
        'planner_contract_version': ORCHESTRATION_PLAN_CONTRACT_VERSION,
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
    )

    plan['inputs'] = build_plan_inputs(plan, seeds=seeds, document_labels=document_labels)
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


def apply_plan_edits(plan, edits):
    """Apply a user's edits to a plan before it runs.

    Only two things are editable, and both narrow the plan rather than widening it:
    disabling a step, and removing documents from one. A user may not add a capability or
    a document through this path, because doing so would let the browser assemble a plan
    that never passed the planner's own reasoning or the authorization check that followed
    it. Widening belongs to re-planning, which goes back through validation.
    """
    if not isinstance(edits, dict):
        return plan

    disabled = set(_string_list(edits.get('disabled_step_ids')))
    removed_documents = edits.get('removed_document_ids')
    removed_documents = removed_documents if isinstance(removed_documents, dict) else {}

    edited = False
    for step in plan.get('steps') or ():
        if step['capability_id'] == TERMINAL_CAPABILITY_ID:
            continue
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

    return plan


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
    return {
        'status': status,
        'summary': _text(summary, PLAN_MAX_SUMMARY_LENGTH),
        'evidence': list(evidence or ()),
        'citations': list(citations or ()),
        'artifacts': list(artifacts or ()),
        'notes': _string_list(notes),
        'error': _text(error) or None,
        'replan_hint': _text(replan_hint) or None,
        'message': message,
    }


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


def normalize_elicitation(elicitation, run_id, revision=0):
    """Turn raw planner output into a question set the card can render."""
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
    for page in hints.get('pages') or ():
        page_fields = [name for name in _string_list(page) if name in schema['properties']]
        if page_fields:
            pages.append(page_fields)
    covered = {name for page in pages for name in page}
    remainder = [name for name in order if name not in covered]
    pages.extend([[name] for name in remainder])

    return {
        'elicitation_id': elicitation.get('elicitation_id') or f"ask_{uuid.uuid4().hex}",
        'contract_version': ORCHESTRATION_ELICITATION_CONTRACT_VERSION,
        'run_id': run_id,
        'revision': int(revision or 0),
        'message': _text(elicitation.get('message'), PLAN_MAX_SUMMARY_LENGTH)
        or 'I need a little more information before I can plan this.',
        'requested_schema': schema,
        'ui_hints': {'order': order, 'pages': pages},
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
    errors = []

    for name, rules in properties.items():
        if name not in content or content[name] is None:
            continue
        raw = content[name]
        if rules.get('type') == 'array':
            item_type = (rules.get('items') or {}).get('type', 'string')
            allowed = (rules.get('items') or {}).get('enum')
            values = raw if isinstance(raw, (list, tuple)) else [raw]
            coerced = []
            for item in values:
                value = _coerce_scalar(item, item_type)
                if value is None or value == '':
                    continue
                if allowed and value not in allowed:
                    errors.append(f"'{name}' contains a value that was not offered.")
                    continue
                coerced.append(value)
            cleaned[name] = coerced
            continue

        value = _coerce_scalar(raw, rules.get('type', 'string'))
        if value is None or value == '':
            errors.append(f"'{name}' is not a valid {rules.get('type', 'string')}.")
            continue
        allowed = rules.get('enum')
        if allowed and value not in allowed:
            errors.append(f"'{name}' is not one of the offered choices.")
            continue
        cleaned[name] = value

    for name in required:
        if name not in cleaned:
            errors.append(f"'{name}' is required.")

    if errors:
        return None, errors

    return {'action': action, 'content': cleaned}, []
