# functions_orchestration_usage.py
"""Attribute what an orchestration plan spent to the models that spent it.

A plan is many model requests: planning, each model-backed step, and the final answer. With
Auto routing the steps can run on different models, so one total against one model would
misstate both. This module splits a finished run's usage by model from facts the run already
records, and writes one activity log row per model so usage reporting includes plans.

Each step record carries the usage of the requests made during that step. Whatever the run
spent beyond its steps is planning and composing the answer, which use the answer model.
"""

import logging

from functions_appinsights import log_event


USAGE_FIELDS = ('prompt_tokens', 'completion_tokens', 'total_tokens')
ROLE_STEPS = 'steps'
ROLE_PLANNING_AND_ANSWER = 'planning_and_answer'
# A run that stopped to wait for approval or input finalizes again when it finishes.
NON_TERMINAL_STATUSES = frozenset({'waiting'})


def _count(value):
    return value if type(value) is int and value >= 0 else 0


def observe_model_request(observations, model, usage, *, label=None, limit=None, single_request=True):
    """Note which model a request ran on, what it spent and how large it was. Never raises.

    ``observations`` is the run's own record of this, kept on its context and apart from the
    usage totals, which hold counts only. ``single_request`` is false when ``usage`` is itself
    a sum over several requests (an agent that called tools): its size then says nothing about
    any one request, so it sets no peak.
    """
    try:
        name = str(model or '').strip()
        if not isinstance(observations, dict) or not name:
            return
        counts = _usage_fields(usage if isinstance(usage, dict) else {
            field: getattr(usage, field, None) for field in USAGE_FIELDS
        })
        if not any(counts.values()):
            return
        entry = observations.setdefault(name, {
            **{field: 0 for field in USAGE_FIELDS},
            'request_count': 0, 'peak_request': 0, 'label': '', 'limit': None,
        })
        for field in USAGE_FIELDS:
            entry[field] += counts[field]
        entry['request_count'] += 1
        if single_request:
            entry['peak_request'] = max(entry['peak_request'], counts['prompt_tokens'])
        if label:
            entry['label'] = str(label)
        if type(limit) is int and limit > 0:
            entry['limit'] = limit
    except Exception:
        return


def begin_step_observations(*observation_sets):
    """Snapshot the observations before a step and clear the peaks, which are per step."""
    snapshot = {}
    for observations in observation_sets:
        if not isinstance(observations, dict):
            continue
        for name, entry in observations.items():
            if not isinstance(entry, dict):
                continue
            before = snapshot.setdefault(name, {**{field: 0 for field in USAGE_FIELDS}, 'request_count': 0})
            for field in (*USAGE_FIELDS, 'request_count'):
                before[field] += _count(entry.get(field))
            entry['peak_request'] = 0
    return snapshot


def end_step_observations(snapshot, *observation_sets):
    """Return what each model spent during the step, with its largest single request."""
    merged = {}
    for observations in observation_sets:
        if not isinstance(observations, dict):
            continue
        for name, entry in observations.items():
            if not isinstance(entry, dict):
                continue
            row = merged.setdefault(name, {
                'model': name, 'label': '', 'limit': None, 'peak_request': 0,
                **{field: 0 for field in USAGE_FIELDS}, 'request_count': 0,
            })
            for field in (*USAGE_FIELDS, 'request_count'):
                row[field] += _count(entry.get(field))
            row['peak_request'] = max(row['peak_request'], _count(entry.get('peak_request')))
            row['label'] = row['label'] or str(entry.get('label') or '')
            if type(entry.get('limit')) is int:
                row['limit'] = entry['limit']
    rows = []
    for name, row in merged.items():
        before = (snapshot or {}).get(name) or {}
        for field in (*USAGE_FIELDS, 'request_count'):
            row[field] = max(0, row[field] - _count(before.get(field)))
        if row['request_count'] or row['total_tokens'] or row['prompt_tokens']:
            row['label'] = row['label'] or name
            rows.append(row)
    return sorted(rows, key=lambda row: (-row['total_tokens'], row['model']))


def step_context_fill(model_usage):
    """The step's fullest single request: the model, its size, and the share of that model's limit.

    Returns None when no single request was observed. ``percent`` is None when the model's
    limits are not known.
    """
    best = None
    for row in model_usage or []:
        peak = _count((row or {}).get('peak_request'))
        if not peak:
            continue
        limit = row.get('limit') if type(row.get('limit')) is int and row['limit'] > 0 else None
        percent = min(100, round(peak / limit * 100)) if limit else None
        candidate = {
            'model': row.get('label') or row.get('model') or '',
            'peak_request': peak, 'limit': limit, 'percent': percent,
        }
        rank = (percent if percent is not None else -1, peak)
        if best is None or rank > best[0]:
            best = (rank, candidate)
    return best[1] if best else None


def _usage_fields(usage):
    usage = usage if isinstance(usage, dict) else {}
    return {field: _count(usage.get(field)) for field in USAGE_FIELDS}


def _binding_model(binding):
    """The model a step's approved binding names, or None when the step has no binding."""
    if not isinstance(binding, dict):
        return None
    selection = binding.get('selection') if isinstance(binding.get('selection'), dict) else {}
    deployment = str(selection.get('model_deployment') or '').strip()
    if not deployment:
        return None
    return {
        'model': deployment,
        'label': str(binding.get('label') or '').strip() or deployment,
        'model_id': str(selection.get('model_id') or '').strip(),
        'endpoint_id': str(selection.get('model_endpoint_id') or '').strip(),
        'provider': str(selection.get('model_provider') or '').strip(),
    }


def _answer_model(model_metadata):
    model_metadata = model_metadata if isinstance(model_metadata, dict) else {}
    deployment = str(model_metadata.get('model_deployment_name') or '').strip()
    return {
        'model': deployment or 'unknown',
        'label': deployment or 'Unknown model',
        'model_id': str(model_metadata.get('model_id') or '').strip(),
        'endpoint_id': str(model_metadata.get('model_endpoint_id') or '').strip(),
        'provider': str(model_metadata.get('model_provider') or '').strip(),
    }


def summarize_plan_usage_by_model(plan, execution_steps, combined_usage, answer_model_metadata):
    """Return one row per model the run used, largest first. Rows add up to ``combined_usage``.

    A step runs on the model its approved binding names; a step without one (a plan that did
    not use Auto routing, or an agent step) is counted under the answer model, because the run
    does not record which model an agent's own configuration chose.
    """
    plan_steps = {
        step.get('step_id'): step
        for step in ((plan or {}).get('steps') or [])
        if isinstance(step, dict)
    }
    answer = _answer_model(answer_model_metadata)
    rows = {}

    def add(model, usage, role, step_count):
        if not any(usage.values()) and not step_count:
            return
        identity = (model['model'], model['endpoint_id'])
        row = rows.setdefault(identity, {
            **model,
            **{field: 0 for field in USAGE_FIELDS},
            'step_count': 0,
            'roles': [],
        })
        for field in USAGE_FIELDS:
            row[field] += usage[field]
        row['step_count'] += step_count
        if role not in row['roles']:
            row['roles'].append(role)

    stepped = {field: 0 for field in USAGE_FIELDS}
    for record in execution_steps or []:
        if not isinstance(record, dict):
            continue
        usage = _usage_fields(record.get('token_usage'))
        if not any(usage.values()):
            # A reused step and a step that called no model spent nothing in this run.
            continue
        bound = (
            _binding_model(record.get('model_binding'))
            or _binding_model((plan_steps.get(record.get('step_id')) or {}).get('model_binding'))
            or answer
        )
        # Where the step noted which model each request ran on, that is the truth: an agent
        # runs on its own model, and its delegates on theirs. The rest counts under the bound model.
        unobserved = dict(usage)
        counted = False
        for observed in record.get('model_usage') or []:
            if not isinstance(observed, dict) or not str(observed.get('model') or '').strip():
                continue
            share = {
                field: min(unobserved[field], _count(observed.get(field))) for field in USAGE_FIELDS
            }
            if not any(share.values()):
                continue
            name = str(observed['model']).strip()
            model = bound if name == bound['model'] else {
                'model': name, 'label': str(observed.get('label') or '') or name,
                'model_id': '', 'endpoint_id': '', 'provider': '',
            }
            add(model, share, ROLE_STEPS, 0 if counted else 1)
            counted = True
            for field in USAGE_FIELDS:
                unobserved[field] -= share[field]
        if any(unobserved.values()) or not counted:
            add(bound, unobserved, ROLE_STEPS, 0 if counted else 1)
        for field in USAGE_FIELDS:
            stepped[field] += usage[field]

    total = _usage_fields(combined_usage)
    remainder = {field: max(0, total[field] - stepped[field]) for field in USAGE_FIELDS}
    add(answer, remainder, ROLE_PLANNING_AND_ANSWER, 0)

    return sorted(
        (row for row in rows.values() if row['total_tokens'] or row['prompt_tokens']),
        key=lambda row: (-row['total_tokens'], row['model']),
    )


def public_usage_by_model(rows):
    """The fields a reader's interface needs. Endpoint identifiers stay on the server."""
    return [
        {
            'model': row['model'],
            'label': row['label'],
            'prompt_tokens': row['prompt_tokens'],
            'completion_tokens': row['completion_tokens'],
            'total_tokens': row['total_tokens'],
            'step_count': row['step_count'],
            'roles': list(row['roles']),
        }
        for row in rows or []
    ]


def log_plan_token_usage(record, rows, *, status, message_id, log_token_usage=None):
    """Write one token usage activity row per model for a finished run. Never raises.

    The row id is derived from the run and the model, so publishing the same run again
    (a redelivery, a recovered finalization) cannot count it twice. A retry is a new run and
    is counted for what it spent itself: the steps it reused report no usage.
    """
    if status in NON_TERMINAL_STATUSES or not rows:
        return 0
    try:
        if log_token_usage is None:
            from functions_activity_logging import log_token_usage
        seeds = record.get('seeds') if isinstance(record.get('seeds'), dict) else {}
        group_id = (seeds.get('active_group_ids') or [None])[0]
        public_workspace_id = (seeds.get('active_public_workspace_ids') or [None])[0]
        workspace_type = 'public' if public_workspace_id else 'group' if group_id else 'personal'
        written = 0
        for row in rows:
            log_token_usage(
                user_id=record['user_id'],
                token_type='chat',
                total_tokens=row['total_tokens'],
                model=row['model'],
                workspace_type=workspace_type,
                prompt_tokens=row['prompt_tokens'],
                completion_tokens=row['completion_tokens'],
                conversation_id=record.get('conversation_id'),
                message_id=message_id,
                group_id=group_id,
                public_workspace_id=public_workspace_id,
                additional_context={
                    'execution_path': 'orchestration',
                    'run_id': record.get('id'),
                    'turn_id': record.get('turn_id'),
                    'attempt_index': record.get('attempt_index') or 1,
                    'run_status': status,
                    'model_label': row['label'],
                    'model_roles': list(row['roles']),
                    'step_count': row['step_count'],
                },
                idempotency_key=f"orchestration:{record.get('id')}:{row['model']}:{row['endpoint_id']}",
            )
            written += 1
        return written
    except Exception as exc:
        log_event(
            '[ORCHESTRATION] Plan token usage could not be recorded.',
            level=logging.WARNING,
            extra={'run_id': record.get('id') if isinstance(record, dict) else None, 'error_type': type(exc).__name__},
        )
        return 0
