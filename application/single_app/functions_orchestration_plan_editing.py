# functions_orchestration_plan_editing.py
"""
Planner-assisted changes to a saved, unexecuted plan.

The revision store owns concurrency and publication. This module prepares the scoped
request, reuses the planner and source authorization boundaries, and never executes work
or writes conversation messages.

Version: 0.261.140
"""

import json
from copy import deepcopy
from datetime import datetime, timezone

from functions_assist_references import REQUEST_REFERENCE_LIMIT
from functions_mixed_source_orchestration import resolve_authorized_source_manifest
from functions_orchestration_context import (
    ELICITATION_REFERENCE_LIMIT,
    ScopeReferenceError,
    build_capability_request_context,
    build_conversation_signals,
    build_elicitation_user_request,
    build_planner_context,
    conversation_user_urls,
    conversation_workspace_lock,
    merge_elicitation_context,
    normalize_elicitation_answer,
    resolve_action_catalog,
    resolve_agent_catalog,
    resolve_candidate_documents,
    resolve_elicitation_references,
    resolve_scope_references,
    validate_clarification_answers,
)
from functions_model_catalog import ModelCatalogError
from functions_orchestration_model_routing import assign_step_models, authorized_routing_candidates
from functions_orchestration_models import OrchestrationModelError, resolve_orchestration_model
from functions_orchestration_memory import load_orchestration_memory, validate_memory_audience
from functions_orchestration_events import merge_reasoning_adjustments
from functions_orchestration_plan_revisions import (
    PlanRevisionError,
    plan_revision_contract_version,
    read_revision_run,
    resolve_revision_export_catalog,
    resolve_revision_result_aliases,
)
from functions_orchestration_planner import plan_request
from functions_orchestration_registry import resolve_available_capabilities
from functions_orchestration_schema import (
    PlanValidationError,
    apply_plan_edits,
    normalize_plan,
    plan_document_ids,
    validate_plan_document_source_kinds,
    validate_plan_requirements,
)
from functions_orchestration_workflow_context import workflow_planning_option, workflow_proposals_configured

TURN_CONTEXT_FIELDS = (
    'conversation_id', 'turn_id', 'user_message', 'user_message_id',
    'user_message_fingerprint', 'seeds', 'original_seeds', 'answered_questions',
    'conversation_context', 'request_resolution', 'resolved_message',
    'planning_token_usage', 'prompt_selection', 'edit_user_urls',
    'reasoning_adjustments', 'memory_audience', 'memory_scope',
    'planner_contract_version', 'result_aliases', 'time_zone', 'workflow_planning',
)


def _turn_context(record):
    context = {key: deepcopy(record[key]) for key in TURN_CONTEXT_FIELDS if key in record}
    context['planner_contract_version'] = plan_revision_contract_version(record['plan'], record)
    return context


def _chat_turn(role, content, submission_id=None, references=None, scope_notice=None):
    turn = {
        'role': role, 'content': content,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    # The request's id travels with the turns it produced, so the editor can match the message
    # it showed before the planner answered to the one stored here. Never shown to the planner.
    if submission_id:
        turn['submission_id'] = submission_id
    # So do a user turn's `#` chips and what they limited searches to: display data for the
    # thread, never shown to the planner, which reads the authorized seeds instead.
    if references:
        turn['references'] = [
            {
                'kind': item['kind'], 'id': item['id'], 'label': item.get('label') or '',
                'scope': {'kind': item['scope']['kind'], 'id': item['scope'].get('id')},
            }
            for item in references
        ]
    if scope_notice:
        turn['scope_notice'] = deepcopy(scope_notice)
    return turn


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


def _authorized_manifest(context, ids, user_id):
    """The authorized manifest entries for ``ids`` under the context's current seeds."""
    seeds = context.get('seeds') or {}
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
    return {
        item['document_id']: item for item in manifest
        if item.get('authorization_status') == 'authorized'
    }


def _plan_source_ids(seeds, plan):
    return [
        *(seeds.get('document_ids') or []),
        *plan_document_ids(plan, include_disabled=True),
        *(item.get('document_id') for item in seeds.get('image_reference_documents') or [] if isinstance(item, dict)),
    ]


def _available_sources(context, plan, user_id, settings, candidates=()):
    seeds = context.get('seeds') or {}
    offered = {item['document_id']: item for item in candidates}
    ids = list(dict.fromkeys([*_plan_source_ids(seeds, plan), *offered]))
    if not ids:
        return []
    available = _authorized_manifest(context, ids, user_id)
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
            'source_kind': item.get('source_kind'),
            'selected_by_user': document_id in (seeds.get('document_ids') or []),
        }
        for document_id, item in available.items()
    ]


# How an Ask AI reference the authorizer refused is reported. Any other refusal means the
# reference is stale, deleted or no longer readable, which the user fixes by removing it.
_REFERENCE_ERROR_CODES = {
    'too_many': ('reference_limit', 400),
    'invalid_reference': ('invalid_request', 400),
    'unsupported_kind': ('invalid_request', 400),
    'verification_failed': ('reference_check_failed', 503),
}
_ACTIVE_WORKSPACE_FIELDS = {'group': 'active_group_ids', 'public': 'active_public_workspace_ids'}


def _reference_key(reference):
    scope = reference.get('scope') or {}
    return (reference.get('kind'), reference.get('id'), scope.get('kind'), scope.get('id'))


def resolve_plan_edit_references(record, references, user_id, settings, *, conversation):
    """Authorize an Ask AI request's `#` documents and tags for the acting user, as of now.

    Returns them in the question card's normalized shape, labeled from the server's
    records, ready for ``build_plan_edit_outcome``. A reference that cannot be used fails
    the whole request with a PlanRevisionError that names it by the label the user picked,
    before the planner runs, so a refused request changes no plan, seed or turn. The
    conversation's workspace lock applies exactly as it does to the question card.
    """
    if not references:
        return []
    try:
        resolved = resolve_scope_references(
            references, user_id, settings,
            allowed_workspaces=conversation_workspace_lock(conversation),
            limit=REQUEST_REFERENCE_LIMIT,
        )
    except ScopeReferenceError as exc:
        code, status = _REFERENCE_ERROR_CODES.get(exc.reason, ('reference_unavailable', 400))
        raise PlanRevisionError(exc.message, code=code, status_code=status) from exc
    unique = {}
    for reference in resolved:
        unique.setdefault(_reference_key(reference), reference)
    existing = {
        _reference_key(item)
        for item in (record.get('seeds') or {}).get('elicitation_references') or []
        if isinstance(item, dict)
    }
    if len(existing | set(unique)) > ELICITATION_REFERENCE_LIMIT:
        raise PlanRevisionError(
            f'This plan already uses as many documents and tags as it can '
            f'({ELICITATION_REFERENCE_LIMIT}). Start a new request to use others.',
            code='reference_limit', status_code=400,
        )
    return list(unique.values())


def _merge_ask_references(context, plan, references, user_id):
    """Add authorized Ask AI references to a revision's seeds, keeping the plan's sources.

    ``merge_elicitation_context`` narrows the search scope and the active workspace lists
    to the new references' workspaces when the plan had no selection. A source the current
    plan already relies on in another workspace would then stop resolving and the revision
    would fail, so the scope is widened back just enough to keep every one of them.
    Widening never grants access: each source is authorized again for this user.
    """
    ids = list(dict.fromkeys(_plan_source_ids(context.get('seeds') or {}, plan)))
    covered = list(_authorized_manifest(context, ids, user_id).values()) if ids else []
    merged = merge_elicitation_context(context.get('seeds'), {'instruction': {'references': references}})
    scope = merged.get('doc_scope') or 'all'
    if scope != 'all' and any(item.get('scope') != scope for item in covered):
        merged['doc_scope'] = 'all'
    for item in covered:
        field = _ACTIVE_WORKSPACE_FIELDS.get(item.get('scope'))
        scope_id = item.get('scope_id')
        # An empty list already means every workspace of that kind the user can read.
        if field and scope_id and merged.get(field) and scope_id not in merged[field]:
            merged[field] = [*merged[field], scope_id]
    return merged


def _scope_notice(committed_seeds, seeds):
    """What the plan's searches are now limited to, when this revision newly limited them.

    Selected documents replace the default search, and selected tags filter it, so a plan
    that searched everything the user can read now searches only these. Nothing is shown
    when the plan was already limited, or when a whole selected workspace is still searched.
    """
    committed_seeds = committed_seeds or {}
    if committed_seeds.get('document_ids') or committed_seeds.get('tags'):
        return None
    references = [item for item in seeds.get('elicitation_references') or [] if isinstance(item, dict)]
    if any(item.get('kind') == 'scope' for item in references):
        return None
    document_ids = seeds.get('document_ids') or []
    tags = seeds.get('tags') or []
    if not document_ids and not tags:
        return None
    labels = seeds.get('document_labels') or {}
    reference_labels = {item.get('id'): item.get('label') for item in references if item.get('kind') != 'tag'}
    documents = [
        labels.get(document_id) or reference_labels.get(document_id) or 'Selected document'
        for document_id in document_ids
    ]
    listed_documents = documents[:REQUEST_REFERENCE_LIMIT]
    listed_tags = list(tags)[:REQUEST_REFERENCE_LIMIT]
    return {
        'kind': 'search_limited', 'documents': listed_documents, 'tags': listed_tags,
        'more': len(documents) - len(listed_documents) + len(tags) - len(listed_tags),
    }


def _revision_catalogs(
    context, user_id, settings, identity, *, contract_version=2, native_bridge_for_step=None,
    rendering_service=None, external_source_preflight=None,
    external_source_admission=None, external_source_authorizer=None,
    capture_external_source_configuration=None,
):
    seeds = context.get('seeds') or {}
    identity = dict(identity or {})
    if (seeds.get('agent') or {}).get('name'):
        identity['user_enable_agents'] = True
    agents = resolve_agent_catalog(
        user_id, seeds=seeds, settings=settings,
        user_groups=seeds.get('active_group_ids') or None,
    ) if identity.get('user_enable_agents', True) else []
    actions = resolve_action_catalog(
        user_id, seeds=seeds, settings=settings,
        user_groups=seeds.get('active_group_ids') or None,
    )
    runtime_options = {}
    if callable(native_bridge_for_step):
        runtime_options['native_bridge_for_step'] = native_bridge_for_step
    if rendering_service is not None:
        runtime_options['rendering_service'] = rendering_service
    external_bindings = {
        'external_source_preflight': external_source_preflight,
        'external_source_admission': external_source_admission,
        'external_source_authorizer': external_source_authorizer,
        'capture_external_source_configuration': capture_external_source_configuration,
    }
    if any(callback is not None for callback in external_bindings.values()):
        runtime_options.update(external_bindings)
    caller = build_capability_request_context(
        user_id, identity, context.get('resolved_message') or context['user_message'],
        agents, actions, allowed_user_urls=revision_allowed_urls(context),
        **workflow_planning_option(
            context.get('workflow_planning') if workflow_proposals_configured(settings) else None,
        ),
        **runtime_options,
    )
    caller['image_reference_documents'] = list(seeds.get('image_reference_documents') or [])
    caller['image_reference_messages'] = list(seeds.get('image_reference_messages') or [])
    return agents, actions, caller


def validate_edited_plan(
    plan, context, user_id, settings, identity, *,
    result_alias_resolver=None, export_catalog=None, composition_profiles=None,
    native_bridge_for_step=None, rendering_service=None,
    external_source_preflight=None,
    external_source_admission=None, external_source_authorizer=None,
    capture_external_source_configuration=None,
):
    """Recheck a restored/generated plan using its saved contract and current access.

    Optional catalogs and the alias resolver are supplied by the server, never
    extracted from browser edits or model output. The resolver contract is
    ``resolve_revision_result_aliases``; profiles use the shared renderer schemas.
    A supplied export catalog narrows canonical format/profile pairs without
    redefining shared exporters: None uses shared defaults, while [] admits no
    Render work. The native factory, typed rendering
    service, and external-source callbacks are forwarded only for capability
    discovery, never executed or saved in admission context. The shared context helper
    validates the service instance and requires all four external callbacks to
    be callable together, without acquiring sources or reading configuration.
    """
    contract_version = plan_revision_contract_version(plan, context)
    existing_results = resolve_revision_result_aliases(
        context, user_id, result_alias_resolver=result_alias_resolver,
    )
    admitted_catalog = resolve_revision_export_catalog(export_catalog)
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
    agents, actions, caller = _revision_catalogs(
        context, user_id, settings, identity, contract_version=contract_version,
        native_bridge_for_step=native_bridge_for_step,
        rendering_service=rendering_service,
        external_source_preflight=external_source_preflight,
        external_source_admission=external_source_admission,
        external_source_authorizer=external_source_authorizer,
        capture_external_source_configuration=capture_external_source_configuration,
    )
    capabilities = resolve_available_capabilities(
        settings, allowed_ids=settings.get('chat_orchestration_enabled_capabilities'),
        request_context=caller, contract_version=contract_version, export_catalog=admitted_catalog,
    )
    try:
        checked = normalize_plan(
            deepcopy(plan), context['conversation_id'], user_id, settings=settings,
            approval_mode='manual', authorized_document_ids=authorized,
            available_capability_ids=[item['id'] for item in capabilities],
            turn_id=context['turn_id'], seeds=seeds,
            document_labels={item['document_id']: item['file_name'] for item in candidates},
            agent_names=[item['name'] for item in agents], actions=actions,
            contract_version=contract_version, existing_results=existing_results,
            composition_profiles=composition_profiles, export_catalog=admitted_catalog,
        )
        validate_plan_document_source_kinds(checked, {
            item['document_id']: item['source_kind']
            for item in candidates if item.get('source_kind')
        })
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
    validate_plan_requirements(checked, seeds, allow_changes=True)
    if seeds.get('model_routing') == 'auto':
        # normalize_plan strips server-owned bindings. Re-bind an Auto plan to the current
        # authorized inventory instead of letting an edit silently turn Auto routing off.
        try:
            assign_step_models(checked, authorized_routing_candidates(settings, user_id))
        except ModelCatalogError as exc:
            raise PlanRevisionError(
                'No eligible model is available for that version. Your current plan is unchanged.',
                code='model_unavailable', status_code=403,
            ) from exc
    return checked


def build_plan_edit_outcome(
    record, data, user_id, settings, *, identity, conversation_context, conversation, ledger=None,
    references=None,
    result_alias_resolver=None, export_catalog=None, composition_profiles=None,
    native_bridge_for_step=None, rendering_service=None,
    external_source_preflight=None,
    external_source_admission=None, external_source_authorizer=None,
    capture_external_source_configuration=None,
):
    """Prepare a revision without changing its admitted contract or executing work.

    The optional resolver, catalogs, native factory, rendering service, and
    external-source callbacks have the same server-only contract as
    ``validate_edited_plan``. Supply current runtime dependencies again for
    restore/replan validation; none are persisted.

    ``references`` are an Ask request's `#` documents and tags as returned by
    ``resolve_plan_edit_references``: already authorized for this user. They are merged
    into this revision's seeds, and shown on its user turn, exactly once.
    """
    context = _turn_context(record)
    context['conversation_context'] = conversation_context
    validate_memory_audience(conversation, user_id, context.get('memory_audience'))
    chat = deepcopy(record.get('edit_chat') or [])
    action = data['action']
    submission_id = data.get('submission_id')
    contract_version = context['planner_contract_version']
    instruction = data.get('instruction', '')
    user_content = instruction
    allow_elicitation = True
    ask_references = list(references or []) if action == 'ask' else []
    if action == 'ask' and data.get('references') and references is None:
        # References are authorized before the planner runs; never drop them silently.
        raise PlanRevisionError(
            'The selected documents or tags could not be checked right now. Please retry.',
            code='reference_check_failed', status_code=503,
        )
    if action == 'discard':
        return {
            'kind': 'discard',
            'chat': [*chat, _chat_turn(
                'assistant', 'The proposed change was cancelled. The current plan is unchanged.', submission_id,
            )],
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
        if restored_context['planner_contract_version'] != contract_version:
            raise PlanRevisionError(
                'A restored version cannot change the saved plan contract.',
                code='source_changed',
            )
        resolve_revision_result_aliases(
            restored_context, user_id, result_alias_resolver=result_alias_resolver,
        )
        note = f"Restored version {int(source.get('revision') or 0) + 1}."
        return {
            'kind': 'plan', 'document': deepcopy(source['plan']),
            'turn_context': restored_context, 'origin': 'restore', 'instruction': note,
            'chat': [*chat, _chat_turn('user', note, submission_id), _chat_turn('assistant', note, submission_id)],
        }
    current_plan = deepcopy(record['plan'])
    if action == 'answer':
        pending = record['edit_pending']
        question = pending['elicitation']
        context = deepcopy(pending['turn_context'])
        context['conversation_context'] = conversation_context
        context.setdefault('planner_contract_version', contract_version)
        current_plan = deepcopy(pending['base_plan'])
        instruction = pending['instruction']
        validated, answer_context = normalize_elicitation_answer(
            question, data['elicitation_response'], data.get('elicitation_context'),
            user_id, context['conversation_id'], settings=settings,
        )
        if validated['action'] == 'cancel':
            return {
                'kind': 'discard',
                'chat': [*chat, _chat_turn(
                    'assistant', 'The proposed change was cancelled. The current plan is unchanged.', submission_id,
                )],
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

    if plan_revision_contract_version(current_plan, context) != contract_version:
        raise PlanRevisionError('The saved plan contract changed.', code='plan_changed')
    existing_results = resolve_revision_result_aliases(
        context, user_id, result_alias_resolver=result_alias_resolver,
    )
    admitted_catalog = resolve_revision_export_catalog(export_catalog)
    narrowing = {} if action == 'answer' else data.get('edits', record.get('edit_narrowing'))
    current_plan = apply_plan_edits(
        current_plan, {} if narrowing is None else narrowing,
        existing_results=existing_results, contract_version=contract_version,
        export_catalog=admitted_catalog, composition_profiles=composition_profiles,
    )
    validate_clarification_answers(context.get('answered_questions') or [])
    if ask_references:
        context['seeds'] = _merge_ask_references(context, current_plan, ask_references, user_id)
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
    memory_context = load_orchestration_memory(
        user_id, conversation,
        build_elicitation_user_request(changed_request, context.get('answered_questions')),
        settings=settings, seeds=seeds, expected_audience=context.get('memory_audience'),
    )
    context['memory_audience'] = memory_context['audience']
    context['memory_scope'] = memory_context['scope']
    candidates, _probed = resolve_candidate_documents(
        build_elicitation_user_request(changed_request, context.get('answered_questions')),
        user_id, seeds=seeds, conversation_id=context['conversation_id'], settings=settings,
    )
    candidates = _available_sources(context, current_plan, user_id, settings, candidates)
    agents, actions, caller = _revision_catalogs(
        context, user_id, settings, identity, contract_version=contract_version,
        native_bridge_for_step=native_bridge_for_step,
        rendering_service=rendering_service,
        external_source_preflight=external_source_preflight,
        external_source_admission=external_source_admission,
        external_source_authorizer=external_source_authorizer,
        capture_external_source_configuration=capture_external_source_configuration,
    )
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
        memory_context=memory_context,
    )
    edit_context = {
        'current_plan': {
            key: deepcopy(current_plan[key])
            for key in ('planner_contract_version', 'intent', 'assumptions', 'deliverables', 'steps', 'final_response')
            if key in current_plan
        },
        'current_request': current_request, 'instruction': instruction,
        'chat': [{key: turn[key] for key in ('role', 'content')} for turn in chat[-20:]],
    }
    # A step's deliverable brief is derived again by validation; the planner edits the plan.
    for step in edit_context['current_plan'].get('steps') or []:
        if isinstance(step, dict):
            step.pop('deliverable_context', None)
    # So is the answer the server assumes for a plan that declared no deliverables.
    if isinstance(edit_context['current_plan'].get('deliverables'), list):
        edit_context['current_plan']['deliverables'] = [
            deliverable for deliverable in edit_context['current_plan']['deliverables']
            if not (isinstance(deliverable, dict) and deliverable.get('implicit') is True)
        ]
    try:
        planner_model = resolve_orchestration_model(
            settings, user_id=user_id, seeds=seeds, planner=True, identity_context=identity,
        )
    except (ValueError, PermissionError) as exc:
        raise PlanRevisionError(
            'The selected model is unavailable. Your previous plan is unchanged.',
            code='model_unavailable',
            status_code=403 if isinstance(exc, (OrchestrationModelError, PermissionError)) else 503,
        ) from exc
    try:
        seeds = context['seeds'] = {
            **seeds, 'model': planner_model.answer_model_selection(),
        }
        context['original_seeds'] = {
            **(context.get('original_seeds') or seeds), 'model': dict(seeds['model']),
        }
        kind, document = plan_request(
            changed_request, planner_context, context['conversation_id'], user_id,
            settings=settings, approval_mode='manual',
            authorized_document_ids={item['document_id'] for item in candidates},
            turn_id=context['turn_id'], seeds=seeds,
            document_labels={item['document_id']: item['file_name'] for item in candidates},
            request_context=caller, edit_context=edit_context, allow_elicitation=allow_elicitation,
            revision=int(record.get('revision') or 0) + 1, planner_model=planner_model,
            contract_version=contract_version, existing_results=existing_results,
            composition_profiles=composition_profiles, export_catalog=admitted_catalog,
        )
    except ModelCatalogError as exc:
        # Auto binds every revised step again; an unreachable inventory keeps the plan as it was.
        raise PlanRevisionError(
            'No eligible model is available for that change. Your previous plan is unchanged.',
            code='model_unavailable', status_code=403,
        ) from exc
    finally:
        planner_model.close()
    _add_usage(context, document.get('token_usage'))
    context['reasoning_adjustments'] = merge_reasoning_adjustments(
        context.get('reasoning_adjustments'), current_plan.get('reasoning_adjustments'),
        document.get('reasoning_adjustments'),
    )
    chat.append(_chat_turn('user', user_content, submission_id, references=ask_references))
    if kind == 'elicitation':
        document.update({
            'conversation_id': context['conversation_id'], 'turn_id': context['turn_id'],
        })
        return {
            'kind': kind, 'document': document, 'turn_context': context,
            'chat': [*chat, _chat_turn('assistant', document['message'], submission_id)],
            'pending': {
                'elicitation': document, 'turn_context': context,
                'instruction': instruction, 'base_plan': current_plan,
            },
        }
    if kind == 'message':
        return {
            'kind': kind, 'turn_context': context,
            'chat': [*chat, _chat_turn('assistant', document['message'], submission_id)],
        }
    context['resolved_message'] = document.pop('revised_request').strip()
    count = sum(step.get('enabled', True) for step in document['steps'])
    summary = f"Updated the plan to {count} {'step' if count == 1 else 'steps'}. Review it before running."
    if document['validation']['repairs']:
        summary += ' Adjustments: ' + ' '.join(document['validation']['repairs'])
    notice = _scope_notice(record.get('seeds'), context.get('seeds') or {})
    return {
        'kind': 'plan', 'document': document, 'turn_context': context,
        'instruction': instruction, 'origin': 'ai',
        'chat': [*chat, _chat_turn('assistant', summary, submission_id, scope_notice=notice)],
    }
