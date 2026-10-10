# functions_chat_retry.py
"""Canonical inputs and attempt identities for message retry and edit."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import uuid

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError, CosmosResourceExistsError, CosmosResourceNotFoundError,
)

from collaboration_models import is_shared_conversation_backing
from functions_assist_submissions import normalize_submission_id
from functions_chat_message_metadata import patch_message_metadata
from functions_message_deletion import is_soft_deleted_message


MODEL_FIELDS = ('model_deployment', 'model_id', 'model_endpoint_id', 'model_provider')
AGENT_FIELDS = ('id', 'name', 'display_name', 'is_global', 'is_group', 'group_id', 'group_name', 'catalog_key')


class ChatRetryError(ValueError):
    """An actionable, public-safe retry refusal."""

    def __init__(self, message, *, code='retry_unavailable', status_code=409):
        super().__init__(message)
        self.public_message = message
        self.code = code
        self.status_code = status_code


def _mapping(value):
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise ChatRetryError('The saved message settings are invalid. Review your selections and send a new request.')
    return value


def _text(value):
    if value is None:
        return ''
    if not isinstance(value, str):
        raise ChatRetryError('The message selection is invalid. Review your selections and retry explicitly.')
    return value.strip()


def agent_request_from_metadata(selection):
    """Stored agent metadata is not the schema accepted by the chat endpoint."""
    selection = _mapping(selection)
    agent = {key: deepcopy(selection[key]) for key in AGENT_FIELDS if key in selection}
    for target, saved in (
        ('id', 'agent_id'), ('name', 'selected_agent'), ('display_name', 'agent_display_name'),
    ):
        if not agent.get(target) and selection.get(saved):
            agent[target] = selection[saved]
    return agent


def has_replay_agent_selection(metadata, overrides):
    explicit_model = any(_text(overrides.get(key)) for key in (*MODEL_FIELDS, 'model'))
    if overrides.get('agent_info'):
        return True
    agent = agent_request_from_metadata(_mapping(metadata.get('agent_selection')))
    return not explicit_model and bool(_text(agent.get('id')) or _text(agent.get('name')))


def _agent_scope(selection):
    for field in ('is_global', 'is_group'):
        if field in selection and type(selection[field]) is not bool:
            raise ChatRetryError('The agent scope is invalid.', code='invalid_retry_selection', status_code=400)
    if selection.get('is_group'):
        return 'group', _text(selection.get('group_id'))
    return ('global', '') if selection.get('is_global') else ('personal', '')


def resolve_replay_selection(metadata, overrides, *, models, agents, allow_legacy_default=False, image_generation=False):
    metadata, overrides = _mapping(metadata), _mapping(overrides)
    explicit_model = any(_text(overrides.get(key)) for key in (*MODEL_FIELDS, 'model'))
    explicit_agent = overrides.get('agent_info')
    if explicit_agent and explicit_model:
        raise ChatRetryError('Choose either an agent or a model.', code='invalid_retry_selection', status_code=400)
    saved_agent = _mapping(metadata.get('agent_selection'))
    requested_agent = (
        agent_request_from_metadata(explicit_agent) if explicit_agent
        else agent_request_from_metadata(saved_agent) if has_replay_agent_selection(metadata, overrides)
        else {}
    )
    if requested_agent:
        agent_id, name = _text(requested_agent.get('id')), _text(requested_agent.get('name'))
        scope = _agent_scope(requested_agent)
        catalog_key = _text(requested_agent.get('catalog_key'))
        candidates = [
            agent for agent in agents
            if agent.get('enabled', True) and _agent_scope(agent) == scope
            and (not catalog_key or agent.get('catalog_key') == catalog_key)
            and (agent.get('id') == agent_id if agent_id else bool(name) and agent.get('name') == name)
        ]
        if len(candidates) != 1:
            raise ChatRetryError(
                'The original agent is unavailable or ambiguous. Choose an available agent or model explicitly.',
                code='retry_agent_unavailable',
            )
        return {'agent_info': {key: deepcopy(candidates[0][key]) for key in AGENT_FIELDS if key in candidates[0]}}

    model = _mapping(metadata.get('model_selection'))
    identity = {
        'model_deployment': _text(model.get('selected_model') or model.get('frontend_requested_model')),
        **{key: _text(model.get(key)) for key in MODEL_FIELDS if key != 'model_deployment'},
    }
    if explicit_model:
        identity = {key: _text(overrides.get(key)) for key in MODEL_FIELDS}
        identity['model_deployment'] = identity['model_deployment'] or _text(overrides.get('model'))
    identity = {key: value for key, value in identity.items() if value}

    if identity.get('model_id') and not identity.get('model_endpoint_id'):
        raise ChatRetryError('The saved model has no endpoint identity. Choose a model explicitly.', code='retry_model_unavailable')
    if not identity.get('model_endpoint_id'):
        if explicit_model and identity.get('model_provider'):
            raise ChatRetryError('Choose a model together with its endpoint.', code='invalid_retry_selection', status_code=400)
        # Legacy metadata records a provider, but legacy picker entries have no endpoint tuple.
        identity.pop('model_provider', None)
    if image_generation:
        selected = identity
    elif not identity and allow_legacy_default:
        selected = {}
    else:
        catalog_fields = {
            'model_deployment': 'deployment_name', 'model_id': 'model_id',
            'model_endpoint_id': 'endpoint_id', 'model_provider': 'provider',
        }
        candidates = [
            candidate for candidate in models
            if candidate.get('enabled', True)
            and all(
                _text(candidate.get(catalog_fields[key])).lower() == value.lower()
                if key == 'model_provider' else candidate.get(catalog_fields[key]) == value
                for key, value in identity.items()
            )
        ]
        if len(candidates) != 1:
            raise ChatRetryError(
                'The original model or endpoint is unavailable or ambiguous. Choose an available model explicitly.',
                code='retry_model_unavailable',
            )
        selected = {
            key: candidates[0][field]
            for key, field in catalog_fields.items()
            if candidates[0].get(field)
        }
    reasoning = (
        overrides.get('reasoning_effort') if 'reasoning_effort' in overrides
        else metadata.get('requested_reasoning_effort')
        or model.get('reasoning_effort') or metadata.get('reasoning_effort')
    )
    if reasoning:
        selected['reasoning_effort'] = _text(reasoning)
    return selected


def build_replay_request(source, overrides, *, document_context, models, agents, allow_legacy_default=False):
    metadata = _mapping(source.get('metadata'))
    if metadata.get('masked') or metadata.get('masked_ranges'):
        raise ChatRetryError('This question is masked. Unmask and review it, or send a new request.', code='retry_message_masked')
    buttons = _mapping(metadata.get('button_states'))
    usage = _mapping(metadata.get('capability_usage'))
    image_generation = bool(_mapping(metadata.get('image_generation')).get('enabled', buttons.get('image_generation', False)))
    selection = resolve_replay_selection(
        metadata, overrides, models=models, agents=agents,
        allow_legacy_default=allow_legacy_default, image_generation=image_generation,
    )
    context = _mapping(metadata.get('chat_context'))
    request_body = {
        'message': source.get('content', ''),
        'conversation_id': source['conversation_id'],
        **deepcopy(document_context),
        **selection,
        'image_generation': image_generation,
        'chat_type': context.get('chat_type') or context.get('type') or 'user',
        'active_group_id': context.get('group_id'),
        'active_public_workspace_id': context.get('public_workspace_id'),
    }
    for name in ('web_search', 'url_access', 'deep_research'):
        request_body[f'{name}_enabled'] = bool(buttons.get(name, _mapping(usage.get(name)).get('enabled', False)))
    request_body['source_review_enabled'] = bool(
        buttons.get('source_review', False)
        or _mapping(usage.get('url_access')).get('source_review_enabled', False)
        or _mapping(usage.get('deep_research')).get('source_review_enabled', request_body['deep_research_enabled'])
    )
    if metadata.get('prompt_selection'):
        request_body['prompt_info'] = deepcopy(metadata['prompt_selection'])
    if metadata.get('time_zone'):
        request_body['time_zone'] = metadata['time_zone']
    return request_body


def build_replay_metadata(source_metadata, request_body):
    """Carry input intent, never previous execution approvals, receipts, or failures."""
    source_metadata = _mapping(source_metadata)
    metadata = {
        key: deepcopy(source_metadata[key])
        for key in ('user_info', 'prompt_selection', 'image_references', 'image_generation', 'time_zone')
        if key in source_metadata
    }
    metadata['chat_context'] = {
        'conversation_id': request_body['conversation_id'],
        'chat_type': request_body.get('chat_type', 'user'),
        'group_id': request_body.get('active_group_id'),
        'public_workspace_id': request_body.get('active_public_workspace_id'),
    }
    metadata['button_states'] = {
        'image_generation': request_body.get('image_generation', False),
        'document_search': request_body.get('document_context_requested', False),
        **{name: request_body.get(f'{name}_enabled', False) for name in ('web_search', 'url_access', 'source_review', 'deep_research')},
    }
    document_fields = {
        'search_enabled': 'document_context_requested', 'document_context_requested': 'document_context_requested',
        'hybrid_search_preference': 'hybrid_search', 'selection_mode': 'selection_mode',
        'document_scope': 'doc_scope', 'public_workspace_selection': 'public_workspace_selection',
        'selected_document_id': 'selected_document_id', 'selected_document_ids': 'selected_document_ids',
        'requested_document_ids': 'selected_document_ids', 'tags': 'tags', 'classifications': 'classifications',
        'active_group_ids': 'active_group_ids', 'active_public_workspace_ids': 'active_public_workspace_ids',
        'document_filter_mode': 'document_filter_mode', 'top_n': 'top_n',
    }
    metadata['workspace_search'] = {
        stored: deepcopy(request_body[request_field])
        for stored, request_field in document_fields.items() if request_field in request_body
    }
    agent = request_body.get('agent_info')
    if agent:
        metadata['agent_selection'] = {
            'selected_agent': agent.get('name'), 'agent_id': agent.get('id'),
            'agent_display_name': agent.get('display_name'),
            **{key: deepcopy(agent[key]) for key in AGENT_FIELDS if key not in ('name', 'id', 'display_name') and key in agent},
        }
    else:
        metadata['model_selection'] = {
            'selected_model': request_body.get('model_deployment'),
            **{key: request_body[key] for key in MODEL_FIELDS if key != 'model_deployment' and key in request_body},
            'reasoning_effort': request_body.get('reasoning_effort'),
        }
        if request_body.get('reasoning_effort'):
            metadata['requested_reasoning_effort'] = request_body['reasoning_effort']
    return metadata


def load_owned_retry_message(messages, conversations, user_id, message_id):
    found = list(messages.query_items(
        query='SELECT * FROM c WHERE c.id = @message_id',
        parameters=[{'name': '@message_id', 'value': message_id}],
        enable_cross_partition_query=True,
    ))
    if not found or is_soft_deleted_message(found[0]):
        raise ChatRetryError('Message not found.', code='message_not_found', status_code=404)
    message = found[0]
    try:
        conversation = conversations.read_item(item=message['conversation_id'], partition_key=message['conversation_id'])
    except CosmosResourceNotFoundError:
        raise ChatRetryError('Conversation not found.', code='conversation_not_found', status_code=404) from None
    author_id = _mapping(_mapping(message.get('metadata')).get('user_info')).get('user_id')
    if conversation.get('user_id') != user_id or author_id and author_id != user_id:
        raise ChatRetryError('You can only retry messages from your own conversations.', code='forbidden', status_code=403)
    if is_shared_conversation_backing(conversation):
        raise ChatRetryError('Retry and edit are not available in shared conversations.', code='shared_retry_unsupported')
    return message, conversation


def retry_source_user(messages, clicked):
    if clicked.get('role') == 'user':
        return clicked
    thread = _mapping(_mapping(clicked.get('metadata')).get('thread_info'))
    thread_id, attempt = thread.get('thread_id'), thread.get('thread_attempt')
    if not thread_id or attempt is None:
        raise ChatRetryError('This response has no saved question identity. Retry its original question.', code='retry_source_unavailable')
    questions = list(messages.query_items(
        query=(
            "SELECT * FROM c WHERE c.conversation_id = @conversation_id "
            "AND c.metadata.thread_info.thread_id = @thread_id AND c.role = 'user'"
        ),
        parameters=[
            {'name': '@conversation_id', 'value': clicked['conversation_id']},
            {'name': '@thread_id', 'value': thread_id},
        ],
        partition_key=clicked['conversation_id'],
    ))
    candidates = [
        question for question in questions
        if not is_soft_deleted_message(question)
        and _attempt_number(_mapping(_mapping(question.get('metadata')).get('thread_info')).get('thread_attempt')) == _attempt_number(attempt)
    ]
    if len(candidates) != 1:
        raise ChatRetryError('The question for this attempt is unavailable. Select an existing attempt.', code='retry_source_unavailable')
    return candidates[0]


def retry_source_fingerprint(source):
    metadata = _mapping(source.get('metadata'))
    inputs = {
        key: metadata[key] for key in (
            'model_selection', 'agent_selection', 'workspace_search', 'document_search',
            'button_states', 'prompt_selection', 'image_references', 'image_generation',
            'requested_reasoning_effort', 'time_zone', 'masked', 'masked_ranges',
            'orchestration', 'orchestration_turn_id', 'orchestration_inputs', 'orchestration_clarification_answers',
        ) if key in metadata
    }
    return hashlib.sha256(json.dumps(
        {'id': source['id'], 'content': source.get('content'), 'inputs': inputs},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')).hexdigest()


def retry_thread_messages(messages, conversation_id, thread_id):
    return list(messages.query_items(
        query='SELECT * FROM c WHERE c.conversation_id = @conversation_id AND c.metadata.thread_info.thread_id = @thread_id',
        parameters=[
            {'name': '@conversation_id', 'value': conversation_id},
            {'name': '@thread_id', 'value': thread_id},
        ],
        partition_key=conversation_id,
    ))


def available_retry_attempts(messages, conversation_id, thread_id):
    return sorted({
        _attempt_number(_mapping(_mapping(message.get('metadata')).get('thread_info')).get('thread_attempt')) or 1
        for message in retry_thread_messages(messages, conversation_id, thread_id)
        if message.get('role') == 'user' and not is_soft_deleted_message(message)
    })


def reconcile_prepared_retry(messages, conversations, user_id, question, *, kind='chat'):
    current, _ = load_owned_retry_message(messages, conversations, user_id, question['id'])
    metadata = _mapping(current.get('metadata'))
    attempt = _mapping(metadata.get('response_attempt'))
    if (
        current.get('role') != 'user' or attempt.get('kind') != kind
        or attempt.get('state') != 'prepared'
        or _mapping(metadata.get('thread_info')).get('active_thread') is False
    ):
        raise ChatRetryError('The prepared attempt changed. Reload it.', code='retry_attempt_changed')
    try:
        source = messages.read_item(item=attempt['source_user_message_id'], partition_key=current['conversation_id'])
    except CosmosResourceNotFoundError:
        raise ChatRetryError('The source question is unavailable. Review a new request.', code='retry_source_changed') from None
    if is_soft_deleted_message(source) or retry_source_fingerprint(source) != attempt.get('source_fingerprint'):
        raise ChatRetryError('The original question changed. Review a new request.', code='retry_source_changed')
    return _publish_retry_attempt(messages, conversations, current)


def _attempt_number(value):
    if value is None:
        return 0
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise ChatRetryError('The saved attempt identity is invalid. Reload the conversation.', code='retry_attempt_changed')
    try:
        number = int(value)
    except ValueError:
        raise ChatRetryError('The saved attempt identity is invalid. Reload the conversation.', code='retry_attempt_changed') from None
    if number < 0:
        raise ChatRetryError('The saved attempt identity is invalid. Reload the conversation.', code='retry_attempt_changed')
    return number


def order_retry_messages(messages):
    """Keep a retried answer beside its question, without moving unrelated legacy turns."""
    roots = {
        _mapping(_mapping(message.get('metadata')).get('thread_info')).get('thread_id')
        for message in messages
        if _mapping(message.get('metadata')).get('response_attempt')
        or _mapping(message.get('metadata')).get('retried')
        or _mapping(message.get('metadata')).get('edited')
    } - {None, ''}
    if not roots:
        return list(messages)
    groups, positions = {}, {}
    entries = []
    for index, message in enumerate(messages):
        thread = _mapping(_mapping(message.get('metadata')).get('thread_info'))
        root = thread.get('thread_id')
        timestamp = message.get('timestamp') or ''
        if root not in roots:
            entries.append((timestamp, index, [message]))
            continue
        groups.setdefault(root, []).append(message)
        anchor = thread.get('root_timestamp') or timestamp
        previous = positions.get(root)
        if previous is None or anchor < previous[0]:
            positions[root] = (anchor, index)
    entries.extend((*positions[root], group) for root, group in groups.items())
    entries.sort(key=lambda entry: (entry[0], entry[1]))
    return [message for _timestamp, _index, group in entries for message in group]


def retry_history_prefix(messages, user_message_id):
    """A replay uses prior logical turns and its own question, never later answers."""
    target = next((message for message in messages if message.get('id') == user_message_id), None)
    if not target:
        raise ChatRetryError('The retry question is unavailable. Reload the conversation.', code='retry_source_unavailable')
    thread_id = _mapping(_mapping(target.get('metadata')).get('thread_info')).get('thread_id')
    if not thread_id:
        raise ChatRetryError('The retry question has no thread identity.', code='retry_source_unavailable')
    ordered = order_retry_messages(messages)
    for index, message in enumerate(ordered):
        if _mapping(_mapping(message.get('metadata')).get('thread_info')).get('thread_id') == thread_id:
            return [*ordered[:index], target]
    raise ChatRetryError('The retry thread is unavailable.', code='retry_source_unavailable')


def _publish_retry_attempt(messages, conversations, question):
    conversation_id = question['conversation_id']
    thread_id = question['metadata']['thread_info']['thread_id']
    conversation = conversations.read_item(item=conversation_id, partition_key=conversation_id)
    counter = _mapping(conversation.get('retry_threads')).get(thread_id) or {}
    if counter.get('user_message_id') != question['id']:
        raise ChatRetryError('The attempt changed during preparation. Reload it.', code='retry_attempt_changed')
    if counter.get('published'):
        return question
    for message in retry_thread_messages(messages, conversation_id, thread_id):
        if message['id'] == question['id']:
            continue
        message.setdefault('metadata', {}).setdefault('thread_info', {})['active_thread'] = False
        patch_message_metadata(
            messages, message,
            conflict_error=lambda: ChatRetryError(
                'The message changed during preparation. Reload before retrying.',
                code='retry_attempt_changed',
            ),
        )
    for _attempt in range(3):
        conversation = conversations.read_item(item=conversation_id, partition_key=conversation_id)
        updated = deepcopy(conversation)
        counter = _mapping(updated.get('retry_threads')).get(thread_id) or {}
        if counter.get('user_message_id') != question['id']:
            raise ChatRetryError('The attempt changed during preparation. Reload it.', code='retry_attempt_changed')
        counter['published'] = True
        try:
            conversations.replace_item(
                item=conversation_id, body=updated, etag=conversation['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
            return question
        except CosmosAccessConditionFailedError:
            continue
    raise ChatRetryError('The retry question was saved, but preparation needs reconciliation. Reload it.', code='retry_attempt_changed')


def prepare_retry_attempt(messages, conversations, user_id, source, request_body, *, submission_id=None, edited=False, kind='chat', extra_metadata=None):
    """Reserve an attempt with a conditional counter, then publish its question once."""
    submission_id = normalize_submission_id(submission_id) or str(uuid.uuid4())
    metadata = _mapping(source.get('metadata'))
    thread = _mapping(metadata.get('thread_info'))
    thread_id = thread.get('thread_id')
    if not thread_id:
        raise ChatRetryError('This question has no saved thread identity. Review it and send a new request.', code='retry_source_unavailable')
    conversation_id = source['conversation_id']
    source_now = messages.read_item(item=source['id'], partition_key=conversation_id)
    if is_soft_deleted_message(source_now) or retry_source_fingerprint(source_now) != retry_source_fingerprint(source):
        raise ChatRetryError('This question changed. Reload it before retrying.', code='retry_source_changed')
    user_message_id = f"user_retry_{uuid.uuid5(uuid.NAMESPACE_URL, f'{conversation_id}:{thread_id}:{submission_id}').hex}"
    request_fingerprint = hashlib.sha256(json.dumps(
        {'source_id': source['id'], 'request': request_body, 'edited': edited, 'kind': kind},
        sort_keys=True, ensure_ascii=False, separators=(',', ':'),
    ).encode('utf-8')).hexdigest()
    try:
        existing = messages.read_item(item=user_message_id, partition_key=conversation_id)
    except CosmosResourceNotFoundError:
        existing = None
    if existing:
        attempt = _mapping(_mapping(existing.get('metadata')).get('response_attempt'))
        if is_soft_deleted_message(existing) or attempt.get('request_fingerprint') != request_fingerprint:
            raise ChatRetryError('This retry submission changed. Review the message and retry again.', code='submission_conflict')
        return _publish_retry_attempt(messages, conversations, existing) if attempt.get('state') == 'prepared' else existing

    existing_messages = retry_thread_messages(messages, conversation_id, thread_id)
    maximum = max((
        _attempt_number(_mapping(_mapping(message.get('metadata')).get('thread_info')).get('thread_attempt'))
        for message in existing_messages
    ), default=0)
    for _attempt in range(3):
        conversation = conversations.read_item(item=conversation_id, partition_key=conversation_id)
        if conversation.get('user_id') != user_id:
            raise ChatRetryError('This conversation is unavailable.', code='forbidden', status_code=403)
        updated = deepcopy(conversation)
        counters = updated.setdefault('retry_threads', {})
        previous = counters.get(thread_id) or {}
        if previous.get('submission_id') == submission_id:
            if previous.get('request_fingerprint') != request_fingerprint:
                raise ChatRetryError('This retry submission changed.', code='submission_conflict')
            number = previous['attempt']
            break
        if previous.get('user_message_id'):
            try:
                pending = messages.read_item(item=previous['user_message_id'], partition_key=conversation_id)
            except CosmosResourceNotFoundError:
                pending = None
            if pending is None and not previous.get('published'):
                if previous.get('request_fingerprint') != request_fingerprint:
                    raise ChatRetryError(
                        'A retry is still being prepared. Reload before changing this request.',
                        code='retry_preparation_pending',
                    )
                submission_id = previous['submission_id']
                user_message_id = previous['user_message_id']
                number = previous['attempt']
                break
            state = _mapping(_mapping((pending or {}).get('metadata')).get('response_attempt')).get('state')
            if pending and not is_soft_deleted_message(pending) and state == 'prepared' and previous.get('request_fingerprint') == request_fingerprint:
                return _publish_retry_attempt(messages, conversations, pending)
            if pending and not is_soft_deleted_message(pending) and state in ('prepared', 'running', 'planning', 'awaiting_clarification'):
                raise ChatRetryError(
                    'This question already has an unfinished attempt. Reload or reconnect to it before retrying.',
                    code='retry_in_progress',
                )
        number = max(maximum, _attempt_number(previous.get('attempt'))) + 1
        counters[thread_id] = {
            'submission_id': submission_id, 'request_fingerprint': request_fingerprint,
            'attempt': number, 'user_message_id': user_message_id, 'published': False,
        }
        try:
            conversations.replace_item(
                item=conversation_id, body=updated, etag=conversation['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
            break
        except CosmosAccessConditionFailedError:
            continue
    else:
        raise ChatRetryError('The attempt changed. Reload the conversation and retry.', code='retry_attempt_changed')

    now = datetime.now(timezone.utc).isoformat()
    new_metadata = build_replay_metadata(metadata, request_body)
    new_metadata.update(deepcopy(extra_metadata or {}))
    new_metadata['edited' if edited else 'retried'] = True
    new_metadata['thread_info'] = {
        'thread_id': thread_id, 'previous_thread_id': thread.get('previous_thread_id'),
        'thread_attempt': number, 'active_thread': True,
        'root_timestamp': min((
            _mapping(_mapping(message.get('metadata')).get('thread_info')).get('root_timestamp')
            or message.get('timestamp') or now
            for message in existing_messages if message.get('role') == 'user'
        ), default=source.get('timestamp') or now),
    }
    new_metadata['response_attempt'] = {
        'kind': kind, 'state': 'prepared', 'submission_id': submission_id,
        'source_user_message_id': source['id'],
        'source_fingerprint': retry_source_fingerprint(source),
        'request_fingerprint': request_fingerprint, 'created_at': now, 'updated_at': now,
    }
    question = {
        'id': user_message_id, 'conversation_id': conversation_id, 'role': 'user',
        'content': request_body['message'], 'timestamp': now,
        'model_deployment_name': None, 'metadata': new_metadata,
    }
    try:
        question = messages.create_item(body=question)
    except CosmosResourceExistsError:
        question = messages.read_item(item=user_message_id, partition_key=conversation_id)
        attempt = _mapping(_mapping(question.get('metadata')).get('response_attempt'))
        if attempt.get('request_fingerprint') != request_fingerprint:
            raise ChatRetryError('This retry submission changed.', code='submission_conflict') from None
    return _publish_retry_attempt(messages, conversations, question)


def claim_retry_attempt(messages, conversations, user_id, conversation_id, user_message_id, *, kind='chat', thread_id=None, thread_attempt=None):
    """Only one invocation can consume a prepared retry, including after reconnect."""
    try:
        question = messages.read_item(item=user_message_id, partition_key=conversation_id)
    except CosmosResourceNotFoundError:
        raise ChatRetryError('Retry question not found.', code='message_not_found', status_code=404) from None
    if (
        question.get('role') != 'user' or question.get('conversation_id') != conversation_id
        or is_soft_deleted_message(question)
    ):
        raise ChatRetryError('Retry question not found.', code='message_not_found', status_code=404)
    conversation = conversations.read_item(item=conversation_id, partition_key=conversation_id)
    if conversation.get('user_id') != user_id or is_shared_conversation_backing(conversation):
        raise ChatRetryError('This conversation is unavailable.', code='forbidden', status_code=403)
    metadata = _mapping(question.get('metadata'))
    author_id = _mapping(metadata.get('user_info')).get('user_id')
    if author_id and author_id != user_id:
        raise ChatRetryError('This question is unavailable.', code='forbidden', status_code=403)
    if metadata.get('masked') or metadata.get('masked_ranges'):
        raise ChatRetryError('This question is masked. Review it before retrying.', code='retry_message_masked')
    attempt, thread = _mapping(metadata.get('response_attempt')), _mapping(metadata.get('thread_info'))
    counter = _mapping(conversation.get('retry_threads')).get(thread.get('thread_id')) or {}
    if counter.get('user_message_id') == user_message_id and counter.get('published') is False:
        raise ChatRetryError('This attempt is still being prepared. Retry the same preparation.', code='retry_preparation_pending')
    if thread.get('active_thread') is False or (
        thread_id is not None and thread.get('thread_id') != thread_id
    ) or (
        thread_attempt is not None and _attempt_number(thread.get('thread_attempt')) != _attempt_number(thread_attempt)
    ) or (
        counter.get('user_message_id') and counter['user_message_id'] != user_message_id
    ):
        raise ChatRetryError('The selected attempt changed. Reload the conversation.', code='retry_attempt_changed')
    if not attempt:
        if not (metadata.get('retried') or metadata.get('edited')) or metadata.get('orchestration'):
            raise ChatRetryError('Prepare a new retry before generating its response.', code='retry_not_prepared')
        attempt = {
            'kind': 'chat', 'state': 'prepared', 'source_user_message_id': question['id'],
            'source_fingerprint': retry_source_fingerprint(question),
        }
    if attempt.get('kind') != kind or attempt.get('state') != 'prepared':
        raise ChatRetryError(
            'This attempt was already submitted. Reload or reconnect to its existing response; retry deliberately to create another.',
            code='retry_already_submitted',
        )
    try:
        source = messages.read_item(item=attempt['source_user_message_id'], partition_key=conversation_id)
    except CosmosResourceNotFoundError:
        raise ChatRetryError('The source question is unavailable. Review a new request.', code='retry_source_changed') from None
    if (
        is_soft_deleted_message(source)
        or retry_source_fingerprint(source) != attempt.get('source_fingerprint')
    ):
        raise ChatRetryError('The source question changed. Review it before retrying.', code='retry_source_changed')
    attempt.update({
        'state': 'planning' if kind == 'orchestration' else 'running',
        'updated_at': datetime.now(timezone.utc).isoformat(),
    })
    updated = deepcopy(question)
    updated.setdefault('metadata', {})['response_attempt'] = attempt
    try:
        return messages.replace_item(
            item=user_message_id, body=updated, etag=question['_etag'],
            match_condition=MatchConditions.IfNotModified,
        )
    except CosmosAccessConditionFailedError:
        raise ChatRetryError('This attempt changed or was already submitted. Reload it.', code='retry_attempt_changed') from None


def set_retry_attempt_state(messages, conversation_id, user_message_id, state, *, error=None, code=None, run_id=None, expected_states=None):
    if not user_message_id:
        return
    for _attempt in range(3):
        question = messages.read_item(item=user_message_id, partition_key=conversation_id)
        attempt = _mapping(_mapping(question.get('metadata')).get('response_attempt'))
        if not attempt or attempt.get('state') in ('completed', 'failed', 'interrupted'):
            return
        if expected_states is not None and attempt.get('state') not in expected_states:
            return
        if state in ('awaiting_review', 'awaiting_clarification') and attempt.get('state') not in (
            'prepared', 'planning', 'awaiting_clarification', 'awaiting_review',
        ):
            return
        updated = deepcopy(question)
        attempt.update({'state': state, 'updated_at': datetime.now(timezone.utc).isoformat()})
        for key, value in (('error', error), ('code', code), ('run_id', run_id)):
            if value:
                attempt[key] = value
        updated.setdefault('metadata', {})['response_attempt'] = attempt
        try:
            messages.replace_item(
                item=user_message_id, body=updated, etag=question['_etag'],
                match_condition=MatchConditions.IfNotModified,
            )
            return
        except CosmosAccessConditionFailedError:
            continue
    raise ChatRetryError('The attempt status changed. Reload the conversation.', code='retry_attempt_changed')
