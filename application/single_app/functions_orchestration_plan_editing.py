# functions_orchestration_plan_editing.py
"""
Planner-assisted changes to a saved, unexecuted plan.

The revision store owns concurrency and publication. This module prepares the scoped
request, reuses the planner and source authorization boundaries, and never executes work
or writes conversation messages.

Version: 0.261.102
"""

import json
from copy import deepcopy
from datetime import datetime, timezone

from functions_mixed_source_orchestration import resolve_authorized_source_manifest
from functions_orchestration_context import (
    build_capability_request_context,
    build_conversation_signals,
    build_elicitation_user_request,
    build_planner_context,
    conversation_user_urls,
    merge_elicitation_context,
    normalize_elicitation_answer,
    resolve_action_catalog,
    resolve_agent_catalog,
    resolve_candidate_documents,
    resolve_elicitation_references,
    validate_clarification_answers,
)
from functions_orchestration_plan_revisions import PlanRevisionError, read_revision_run
from functions_orchestration_planner import plan_request
from functions_orchestration_registry import resolve_available_capabilities
from functions_orchestration_schema import (
    PlanValidationError,
    apply_plan_edits,
    normalize_plan,
    plan_document_ids,
)

TURN_CONTEXT_FIELDS = (
    'conversation_id', 'turn_id', 'user_message', 'user_message_id',
    'user_message_fingerprint', 'seeds', 'original_seeds', 'answered_questions',
    'conversation_context', 'request_resolution', 'resolved_message',
    'planning_token_usage', 'prompt_selection', 'edit_user_urls',
)


def _turn_context(record):
    return {key: deepcopy(record[key]) for key in TURN_CONTEXT_FIELDS if key in record}


def _chat_turn(role, content):
    return {
        'role': role, 'content': content,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }


def _add_usage(context, usage):
    previous = context.get('planning_token_usage') or {}
    context['planning_token_usage'] = {
        key: (previous.get(key) or 0) + ((usage or {}).get(key) or 0)
        for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')
    }


def _editor_urls(context, instruction='', chat=()):
    prior_user_urls = [
        url
        for turn in reversed(chat[-20:])
        if isinstance(turn, dict) and turn.get('role') == 'user' and isinstance(turn.get('content'), str)
        for url in conversation_user_urls(turn.get('content'))
    ]
    return list(dict.fromkeys([
        *conversation_user_urls(instruction),
        *prior_user_urls,
        *(context.get('edit_user_urls') or []),
    ]))[:8]


def revision_allowed_urls(context):
    """Only actual user edits and accepted answers can authorize an additional URL."""
    snapshot = context.get('conversation_context') or {}
    resolution = context.get('request_resolution') or {}
    return list(dict.fromkeys([
        *(context.get('edit_user_urls') or []),
        *conversation_user_urls(
            context['user_message'], snapshot, resolution.get('message_ids'),
            context.get('answered_questions'),
        ),
    ]))[:8]


def _available_sources(context, plan, user_id, settings, candidates=()):
    seeds = context.get('seeds') or {}
    offered = {item['document_id']: item for item in candidates}
    ids = list(dict.fromkeys([
        *(seeds.get('document_ids') or []),
        *plan_document_ids(plan, include_disabled=True),
        *offered,
    ]))
    if not ids:
        return []
    try:
        manifest = resolve_authorized_source_manifest(
            ids, user_id, conversation_id=context['conversation_id'],
            doc_scope=seeds.get('doc_scope') or 'all',
            active_group_ids=seeds.get('active_group_ids') or None,
            active_public_workspace_ids=seeds.get('active_public_workspace_ids') or None,
        )
    except ValueError as exc:
        raise PlanRevisionError(
            'The selected sources could not be used. Start a new request with fewer sources.',
            code='invalid_request', status_code=400,
        ) from exc
    available = {
        item['document_id']: item for item in manifest
        if item.get('authorization_status') == 'authorized'
    }
    if set(seeds.get('document_ids') or []) - set(available):
        raise PlanRevisionError(
            'A selected source is no longer available. Start a new request with accessible sources.',
            code='source_changed',
        )
    return [
        {
            **offered.get(document_id, {}),
            'document_id': document_id,
            'file_name': item.get('file_name') or item.get('display_name') or document_id,
            'title': item.get('display_name') or item.get('file_name') or document_id,
            'scope': item.get('scope'),
            'selected_by_user': document_id in (seeds.get('document_ids') or []),
        }
        for document_id, item in available.items()
    ]


def _revision_catalogs(context, user_id, settings, identity):
    seeds = context.get('seeds') or {}
    # Resolve current access even for a pinned agent; the ordinary first-plan fast path
    # assumes that the composer's selection is still fresh.
    agents = resolve_agent_catalog(
        user_id, seeds={**seeds, 'agent': None}, settings=settings,
    )
    selected = seeds.get('agent')
    if selected:
        scope = selected.get('scope_type') or (
            'group' if selected.get('is_group') else
            'global' if selected.get('is_global') else 'personal'
        )
        agents = [
            agent for agent in agents
            if agent.get('name') == selected.get('name')
            and agent.get('scope_type') == scope
            and (not selected.get('id') or agent.get('id') == selected['id'])
            and (
                scope != 'group'
                or agent.get('group_id') == (selected.get('group_id') or selected.get('scope_id'))
            )
        ]
        if len(agents) != 1:
            raise PlanRevisionError(
                'The selected agent is no longer available. Start a new request to choose an agent.',
                code='source_changed',
            )
    actions = resolve_action_catalog(user_id, seeds=seeds, settings=settings)
    caller = build_capability_request_context(
        user_id, identity, context.get('resolved_message') or context['user_message'],
        agents, actions, allowed_user_urls=revision_allowed_urls(context),
    )
    return agents, actions, caller


def validate_edited_plan(plan, context, user_id, settings, identity):
    """Recheck a restored/generated plan before committing it, including current access."""
    seeds = context.get('seeds') or {}
    resolve_elicitation_references(
        seeds.get('elicitation_references') or [],
        user_id, context['conversation_id'], settings=settings,
    )
    candidates = _available_sources(context, plan, user_id, settings)
    authorized = {item['document_id'] for item in candidates}
    if set(plan_document_ids(plan, include_disabled=True)) - authorized:
        raise PlanRevisionError(
            'That version names sources that are no longer available. Your current plan is unchanged.',
            code='source_changed',
        )
    agents, actions, caller = _revision_catalogs(context, user_id, settings, identity)
    capabilities = resolve_available_capabilities(
        settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        request_context=caller,
    )
    try:
        checked = normalize_plan(
            deepcopy(plan), context['conversation_id'], user_id, settings=settings,
            approval_mode='manual', authorized_document_ids=authorized,
            available_capability_ids=[item['id'] for item in capabilities],
            turn_id=context['turn_id'], seeds=seeds,
            document_labels={item['document_id']: item['file_name'] for item in candidates},
            agent_names=[item['name'] for item in agents], actions=actions,
        )
    except PlanValidationError as exc:
        raise PlanRevisionError(
            'That version cannot be used with the current capabilities. Your current plan is unchanged.',
            code='source_changed',
        ) from exc
    if checked['validation']['errors']:
        raise PlanRevisionError(
            'That version contains work that is no longer available. Your current plan is unchanged.',
            code='source_changed',
        )
    checked['validation']['repairs'] = list(dict.fromkeys([
        *(plan.get('validation', {}).get('repairs') or []),
        *checked['validation']['repairs'],
    ]))
    return checked


def build_plan_edit_outcome(
    record, data, user_id, settings, *, identity, conversation_context, ledger=None,
):
    """Return publication arguments; no model response is a committed revision yet."""
    context = _turn_context(record)
    context['conversation_context'] = conversation_context
    chat = deepcopy(record.get('edit_chat') or [])
    action = data['action']
    current_plan = apply_plan_edits(
        deepcopy(record['plan']), data.get('edits', record.get('edit_narrowing')),
    )
    instruction = data.get('instruction', '')
    user_content = instruction
    allow_elicitation = True
    if action == 'discard':
        return {
            'kind': 'discard',
            'chat': [*chat, _chat_turn('assistant', 'The proposed change was cancelled. The current plan is unchanged.')],
        }
    if action == 'restore':
        source = read_revision_run(data['source_run_id'], user_id, context['conversation_id'])
        if (
            source.get('turn_id') != record['turn_id'] or source.get('started_at')
            or source.get('user_message_id') != record.get('user_message_id')
            or source.get('user_message_fingerprint') != record.get('user_message_fingerprint')
            or (source.get('revision_root_run_id') or source['id'])
            != (record.get('revision_root_run_id') or record['id'])
        ):
            raise PlanRevisionError('Choose a version of this unexecuted plan.', code='invalid_request', status_code=400)
        restored_context = _turn_context(source)
        restored_context['conversation_context'] = conversation_context
        note = f"Restored version {int(source.get('revision') or 0) + 1}."
        return {
            'kind': 'plan', 'document': deepcopy(source['plan']),
            'turn_context': restored_context, 'origin': 'restore', 'instruction': note,
            'chat': [*chat, _chat_turn('user', note), _chat_turn('assistant', note)],
        }
    if action == 'answer':
        pending = record['edit_pending']
        question = pending['elicitation']
        context = deepcopy(pending['turn_context'])
        context['conversation_context'] = conversation_context
        current_plan = deepcopy(pending['base_plan'])
        instruction = pending['instruction']
        validated, answer_context = normalize_elicitation_answer(
            question, data['elicitation_response'], data.get('elicitation_context'),
            user_id, context['conversation_id'], settings=settings,
        )
        if validated['action'] == 'cancel':
            return {
                'kind': 'discard',
                'chat': [*chat, _chat_turn('assistant', 'The proposed change was cancelled. The current plan is unchanged.')],
            }
        context['answered_questions'] = [
            *(context.get('answered_questions') or []),
            {
                'elicitation_id': question['elicitation_id'], 'revision': question['revision'],
                'question': question['message'], 'action': validated['action'],
                'answer': validated['content'], 'context': answer_context,
            },
        ]
        if validated['action'] == 'accept':
            context['seeds'] = merge_elicitation_context(context.get('seeds'), answer_context)
        allow_elicitation = validated['action'] == 'accept'
        answer_text = json.dumps(validated['content'], ensure_ascii=False)
        user_content = (
            'Declined to provide more information.' if validated['action'] == 'decline'
            else f"Answer: {answer_text[:1900]}" + (' (excerpt)' if len(answer_text) > 1900 else '')
        )

    validate_clarification_answers(context.get('answered_questions') or [])
    seeds = context.get('seeds') or {}
    resolve_elicitation_references(
        seeds.get('elicitation_references') or [],
        user_id, context['conversation_id'], settings=settings,
    )
    context['edit_user_urls'] = _editor_urls(context, instruction, chat)
    current_request = context.get('resolved_message') or context['user_message']
    changed_request = (
        f'Current task:\n{current_request}\n\n'
        f'User-requested change (takes precedence where it changes the task):\n{instruction}'
    )
    candidates, _probed = resolve_candidate_documents(
        build_elicitation_user_request(changed_request, context.get('answered_questions')),
        user_id, seeds=seeds, conversation_id=context['conversation_id'], settings=settings,
    )
    candidates = _available_sources(context, current_plan, user_id, settings, candidates)
    agents, actions, caller = _revision_catalogs(context, user_id, settings, identity)
    resolution = context.get('request_resolution') or {}
    signals = build_conversation_signals(
        conversation_context['messages'], context['user_message'],
        truncated=conversation_context.get('truncated', False),
        message_ids=resolution.get('message_ids'),
    )
    signals['urls'] = revision_allowed_urls(context)
    planner_context = build_planner_context(
        changed_request, candidates=candidates, seeds=seeds, ledger=ledger,
        signals=signals, agents=agents, actions=actions,
        original_message=context['user_message'], request_resolution=resolution,
        answered_questions=context.get('answered_questions'),
    )
    edit_context = {
        'current_plan': {
            key: deepcopy(current_plan.get(key)) for key in ('intent', 'assumptions', 'steps')
        },
        'current_request': current_request, 'instruction': instruction,
        'chat': [{key: turn[key] for key in ('role', 'content')} for turn in chat[-20:]],
    }
    kind, document = plan_request(
        changed_request, planner_context, context['conversation_id'], user_id,
        settings=settings, approval_mode='manual',
        authorized_document_ids={item['document_id'] for item in candidates},
        turn_id=context['turn_id'], seeds=seeds,
        document_labels={item['document_id']: item['file_name'] for item in candidates},
        request_context=caller, edit_context=edit_context, allow_elicitation=allow_elicitation,
        revision=int(record.get('revision') or 0) + 1,
    )
    _add_usage(context, document.get('token_usage'))
    chat.append(_chat_turn('user', user_content))
    if kind == 'elicitation':
        document.update({
            'conversation_id': context['conversation_id'], 'turn_id': context['turn_id'],
        })
        return {
            'kind': kind, 'document': document, 'turn_context': context,
            'chat': [*chat, _chat_turn('assistant', document['message'])],
            'pending': {
                'elicitation': document, 'turn_context': context,
                'instruction': instruction, 'base_plan': current_plan,
            },
        }
    if kind == 'message':
        return {
            'kind': kind, 'turn_context': context,
            'chat': [*chat, _chat_turn('assistant', document['message'])],
        }
    context['resolved_message'] = document.pop('revised_request').strip()
    count = sum(step.get('enabled', True) for step in document['steps'])
    summary = f"Updated the plan to {count} {'step' if count == 1 else 'steps'}. Review it before running."
    if document['validation']['repairs']:
        summary += ' Adjustments: ' + ' '.join(document['validation']['repairs'])
    return {
        'kind': 'plan', 'document': document, 'turn_context': context,
        'instruction': instruction, 'origin': 'ai',
        'chat': [*chat, _chat_turn('assistant', summary)],
    }
