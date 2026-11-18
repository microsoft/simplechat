# functions_orchestration_progress.py

"""
The progress ledger: what a running plan observed, and the typed recoveries it applied.

The approved plan is a ledger of intent and is never changed while it runs; every durable
fence (plan binding, step fingerprints, checkpoints) depends on that. What can change is how
a step is attempted. When a required step fails with a typed failure, the executor consults
this module instead of failing the run at once:

- ``RECOVERIES`` maps a failure code to the recoveries the server defines for it. A recovery
  is admitted by policy read from the capability registry, never from request wording.
- A recovery is applied only when it is the single one admitted for that failure, and only
  within the approved plan: it adds no capability, source or effect.
- The ledger bounds the loop. The same failure observed again after a recovery is a stall and
  ends the loop; so does the round limit (``chat_orchestration_max_recovery_rounds``).

Everything recorded here is server vocabulary (step and capability identifiers, failure and
recovery codes), so entries are safe to log and to keep with the run.

The loop is off unless ``enable_chat_orchestration_reactive_loop`` is set.

Version: 0.261.458
Implemented in: 0.261.457
"""

import logging

from functions_appinsights import log_event, workflow_log_context
from functions_orchestration_registry import (
    DEPENDENCY_PLAN_CONTRACT_VERSION, external_effect_capability_ids, get_capability,
)

REACTIVE_LOOP_SETTING = 'enable_chat_orchestration_reactive_loop'
ROUND_LIMIT_SETTING = 'chat_orchestration_max_recovery_rounds'
DEFAULT_ROUND_LIMIT = 2
MAX_ROUND_LIMIT = 5

RECOVERY_ACCEPT_PARTIAL_INPUT = 'accept_partial_input'
RECOVERY_CONTINUE_ATTEMPT = 'continue_attempt'
RECOVERY_CONTINUE_AVAILABLE = 'continue_available_information'

OUTCOME_APPLIED = 'applied'
OUTCOME_RECOVERED = 'recovered'
OUTCOME_NOT_RECOVERED = 'not_recovered'
OUTCOME_STALLED = 'stalled'
OUTCOME_ROUND_LIMIT = 'round_limit'
OUTCOME_AMBIGUOUS = 'ambiguous'

_LOG_PREFIX = '[ORCHESTRATION_PROGRESS]'
_RECOVERED_STATUSES = ('completed', 'partial', 'waiting')


def _partial_input_admitted(step, observation):
    """The consumer's capability reads partial results, and the partial producer is known."""
    capability = get_capability(step.get('capability_id'), contract_version=DEPENDENCY_PLAN_CONTRACT_VERSION)
    return (
        bool(capability) and capability.get('partial_inputs_supported') is True
        and isinstance(observation.get('producer_step_id'), str) and bool(observation['producer_step_id'])
    )


def _accept_partial_input(step, observation, context):
    """Let this step read that producer's partial result; it must disclose the limitations."""
    accepted = getattr(context, 'accepted_partial_inputs', None)
    if not isinstance(accepted, set):
        accepted = context.accepted_partial_inputs = set()
    accepted.add((step['step_id'], observation['producer_step_id']))


# failure code -> ((recovery id, admission policy, application, progress summary), ...)
RECOVERIES = {
    'input_partial_not_accepted': ((
        RECOVERY_ACCEPT_PARTIAL_INPUT, _partial_input_admitted, _accept_partial_input,
        'Earlier work finished with limitations. Continuing with what it produced and stating the limits.',
    ),),
}


def reactive_loop_enabled(settings):
    return (settings or {}).get(REACTIVE_LOOP_SETTING) is True


def round_limit(settings):
    raw = (settings or {}).get(ROUND_LIMIT_SETTING)
    if isinstance(raw, bool):
        return DEFAULT_ROUND_LIMIT
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_ROUND_LIMIT
    return value if 0 <= value <= MAX_ROUND_LIMIT else DEFAULT_ROUND_LIMIT


def partial_input_accepted(context, step_id, producer_step_id):
    """Whether a recovery let this step read that producer's partial result."""
    accepted = getattr(context, 'accepted_partial_inputs', None)
    return isinstance(accepted, set) and (step_id, producer_step_id) in accepted


def _failed_steps(record):
    return frozenset(
        (step.get('step_id'), (step.get('failure') or {}).get('code'))
        for step in (record or {}).get('execution_steps') or []
        if isinstance(step, dict) and step.get('status') == 'failed'
    )


def automatic_continuation(record, recovery, settings, *, parent=None):
    """Whether a failed attempt may be followed by the next one without the user's sign-off.

    The user approved a plan; the next attempt is admitted here only while it stays inside that
    approval. It is one of the two successors the server already defines for a failed attempt:
    the same plan run again from its failed step, or the server-derived plan that answers from
    what was retrieved. Neither adds a capability or a source. An attempt that would run an
    external action again, or that needs the user's confirmation, is never continued here.

    Returns ``(decision, reason)``: a decision dict with ``kind``, ``recovery``, ``round`` and
    ``round_limit``, or ``None`` with the server code for why not.
    """
    if not reactive_loop_enabled(settings) or not isinstance(record, dict) or not isinstance(recovery, dict):
        return None, 'disabled'
    if record.get('status') != 'failed' or record.get('cancellation_requested_at'):
        return None, 'not_failed'
    if recovery.get('eligible') is True:
        kind, recovery_id = 'retry', RECOVERY_CONTINUE_ATTEMPT
    elif recovery.get('can_use_available_information') is True:
        kind, recovery_id = 'available_information', RECOVERY_CONTINUE_AVAILABLE
    else:
        return None, 'not_eligible'
    if recovery.get('requires_confirmation') is not False:
        return None, 'confirmation_required'
    rerun = set(recovery.get('retry_step_ids') or ())
    effects = external_effect_capability_ids()
    if any(
        step.get('step_id') in rerun and step.get('capability_id') in effects
        for step in (record.get('plan') or {}).get('steps') or [] if isinstance(step, dict)
    ):
        return None, 'external_effect'
    limit = round_limit(settings)
    rounds = max(0, int(record.get('attempt_index') or 1) - 1)
    if rounds >= limit:
        return None, OUTCOME_ROUND_LIMIT
    if record.get('retry_of_run_id'):
        # The attempt before this one failed the same steps for the same reasons: another
        # attempt of the same kind would be a third. Unreadable history is treated the same.
        if not isinstance(parent, dict) or parent.get('id') != record['retry_of_run_id']:
            return None, OUTCOME_STALLED
        failed = _failed_steps(record)
        if failed and failed == _failed_steps(parent):
            return None, OUTCOME_STALLED
    return {'kind': kind, 'recovery': recovery_id, 'round': rounds + 1, 'round_limit': limit}, None


def log_automatic_continuation(decision, reason, record, *, successor_run_id=None):
    """One ledger line per automatic successor, or per refusal of one. Server codes only."""
    failure = record.get('failure') if isinstance(record.get('failure'), dict) else {}
    log_event(
        f'{_LOG_PREFIX} Progress recorded.',
        level=logging.INFO if decision else logging.WARNING,
        extra={
            **workflow_log_context(
                run_id=successor_run_id or record.get('id'), conversation_id=record.get('conversation_id'),
            ),
            'stage': 'automatic_continuation', 'failure_code': failure.get('code'),
            'capability_id': failure.get('capability_id'),
            'recovery': (decision or {}).get('recovery'),
            'progress_outcome': OUTCOME_APPLIED if decision else reason,
            'round': (decision or {}).get('round'), 'round_limit': (decision or {}).get('round_limit'),
        },
    )


class ProgressLedger:
    """One run's observations and recoveries, in the order they happened."""

    def __init__(self, settings, context=None):
        self.enabled = reactive_loop_enabled(settings)
        self.limit = round_limit(settings)
        self.context = context
        self.entries = []
        self._observed = set()

    @property
    def rounds(self):
        return sum(1 for entry in self.entries if entry['recovery'] is not None)

    def _record(self, step, failure_code, recovery, outcome, observation):
        producer = getattr(self.context, 'task_results', {}).get(observation.get('producer_step_id'))
        entry = {
            'round': self.rounds + (1 if recovery is not None else 0),
            'step_id': step['step_id'], 'capability_id': step['capability_id'],
            'failure_code': failure_code, 'recovery': recovery, 'outcome': outcome,
        }
        producer_capability = getattr(getattr(producer, 'producer', None), 'capability_id', None)
        if producer_capability:
            entry['producer_capability_id'] = producer_capability
        self.entries.append(entry)
        self._log(entry)
        return entry

    def _log(self, entry):
        log_event(
            f'{_LOG_PREFIX} Progress recorded.',
            level=logging.INFO if entry['outcome'] in (OUTCOME_APPLIED, OUTCOME_RECOVERED) else logging.WARNING,
            extra={
                **workflow_log_context(
                    run_id=getattr(self.context, 'run_id', None),
                    conversation_id=getattr(self.context, 'conversation_id', None),
                    step_id=entry['step_id'],
                ),
                'stage': 'progress_ledger', 'capability_id': entry['capability_id'],
                'failure_code': entry['failure_code'], 'recovery': entry['recovery'],
                'progress_outcome': entry['outcome'], 'round': entry['round'], 'round_limit': self.limit,
                'producer_capability_id': entry.get('producer_capability_id'),
            },
        )

    def recover(self, step, result, context):
        """Apply the one admitted recovery for a failed step, or return ``None`` to let it fail.

        Returns the ledger entry of an applied recovery; the caller runs the step again and
        reports the result with ``settle``.
        """
        if not self.enabled or not isinstance(result, dict):
            return None
        failure_code = (result.get('failure') or {}).get('code')
        observation = result.get('observation') if isinstance(result.get('observation'), dict) else {}
        admitted = [
            recovery for recovery in RECOVERIES.get(failure_code, ())
            if recovery[1](step, observation)
        ]
        if not admitted:
            return None
        signature = (step['step_id'], failure_code, observation.get('producer_step_id'))
        if signature in self._observed:
            # The recovery ran and the same failure came back: no progress is being made.
            self._record(step, failure_code, None, OUTCOME_STALLED, observation)
            return None
        if self.rounds >= self.limit:
            self._record(step, failure_code, None, OUTCOME_ROUND_LIMIT, observation)
            return None
        if len(admitted) != 1:
            # More than one valid recovery is a decision, and nothing here guesses one.
            self._record(step, failure_code, None, OUTCOME_AMBIGUOUS, observation)
            return None
        self._observed.add(signature)
        recovery_id, _admitted, apply, summary = admitted[0]
        apply(step, observation, context)
        entry = self._record(step, failure_code, recovery_id, OUTCOME_APPLIED, observation)
        return {**entry, 'summary': summary, 'entry': entry}

    def settle(self, applied, result):
        """Record whether the step completed after a recovery."""
        entry = applied['entry']
        status = result.get('status') if isinstance(result, dict) else None
        entry['outcome'] = OUTCOME_RECOVERED if status in _RECOVERED_STATUSES else OUTCOME_NOT_RECOVERED
        self._log(entry)

    def to_list(self):
        return [dict(entry) for entry in self.entries]
