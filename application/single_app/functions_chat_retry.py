# functions_chat_retry.py
"""Canonical inputs and attempt identities for message retry and edit."""

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import time
import uuid

from azure.core import MatchConditions
from azure.cosmos.exceptions import (
    CosmosAccessConditionFailedError, CosmosBatchOperationError, CosmosHttpResponseError,
    CosmosResourceExistsError, CosmosResourceNotFoundError,
)

from collaboration_models import is_shared_conversation_backing
from cosmos_document_utils import normalize_cosmos_document
from functions_assist_submissions import normalize_submission_id
from functions_chat_message_metadata import patch_message_metadata
from functions_message_deletion import is_soft_deleted_message
from functions_orchestration_planning import PLANNING_METADATA


MODEL_FIELDS = (
    'model_deployment',
    'model_id',
    'model_endpoint_id',
    'model_provider',
    'model_scope_type',
    'model_scope_id',
)
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
            'model_scope_type': 'scope_type', 'model_scope_id': 'scope_id',
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
    if isinstance(metadata.get('conversation_references'), list) and 'conversation_references' not in request_body:
        replay_references = [
            {
                'kind': 'conversation',
                'id': str(item.get('id')).strip(),
                **(
                    {
                        'message_ids': [
                            str(message_id).strip()
                            for message_id in item.get('message_ids')
                            if str(message_id or '').strip()
                        ]
                    }
                    if isinstance(item.get('message_ids'), list) and item.get('message_ids')
                    else {}
                ),
            }
            for item in metadata['conversation_references']
            if isinstance(item, dict) and item.get('kind') == 'conversation' and str(item.get('id') or '').strip()
        ]
        if replay_references:
            request_body['conversation_references'] = replay_references
    return request_body


def build_replay_metadata(source_metadata, request_body):
    """Carry input intent, never previous execution approvals, receipts, or failures."""
    source_metadata = _mapping(source_metadata)
    metadata = {
        key: deepcopy(source_metadata[key])
        for key in (
            'user_info', 'prompt_selection', 'image_references', 'image_generation',
            'time_zone', 'conversation_references', 'conversation_reference_revision',
        )
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
        'public_source_policy': 'public_source_policy',
        'document_source_selection': 'document_source_selection',
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
            PLANNING_METADATA,
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


def select_retry_thread_attempt(messages, conversation_id, thread_id, target_attempt):
    """Select with the same question ETag fence used by late reply publication.

    Questions and replies share the messages container/partition. A publisher
    touches its question in the same batch as creating its reply; selection must
    therefore retry its query if that question changes before its own batch.
    """
    for _ in range(12):
        rows = retry_thread_messages(messages, conversation_id, thread_id)
        target = next((
            row for row in rows if row.get('role') == 'user'
            and _attempt_number(_mapping(_mapping(row.get('metadata')).get('thread_info')).get('thread_attempt'))
            == _attempt_number(target_attempt)
            and not is_soft_deleted_message(row)
        ), None)
        if target is None:
            raise ChatRetryError('This attempt is no longer available.', code='message_not_found', status_code=404)
        operations = []
        for row in rows:
            thread = _mapping(_mapping(row.get('metadata')).get('thread_info'))
            active = (
                _attempt_number(thread.get('thread_attempt')) == _attempt_number(target_attempt)
                and not is_soft_deleted_message(row)
            )
            if row['id'] != target['id'] and thread.get('active_thread') is active:
                continue
            updated = deepcopy(normalize_cosmos_document(row))
            updated.setdefault('metadata', {}).setdefault('thread_info', {})['active_thread'] = active
            operations.append(('replace', (row['id'], updated), {'if_match_etag': row['_etag']}))
        try:
            messages.execute_item_batch(batch_operations=operations, partition_key=conversation_id)
            return messages.read_item(item=target['id'], partition_key=conversation_id)
        except CosmosBatchOperationError as error:
            if error.status_code not in (404, 409, 412):
                raise
    raise ChatRetryError('The selected attempt changed. Reload it.', code='retry_attempt_changed')


def _verify_attempt_reply(saved, candidate):
    """Check immutable binding only; edits, retractions and deletion markers win."""
    expected = _mapping(_mapping(candidate.get('metadata')).get('response_attempt'))
    actual = _mapping(_mapping(saved.get('metadata')).get('response_attempt'))
    expected_thread = _mapping(_mapping(candidate.get('metadata')).get('thread_info'))
    actual_thread = _mapping(_mapping(saved.get('metadata')).get('thread_info'))
    retracted = saved.get('role') == 'safety' and (
        _mapping(saved.get('metadata')).get('content_moderation') or {}
    ).get('removed') is True
    if (
        saved.get('id') != candidate.get('id')
        or saved.get('conversation_id') != candidate.get('conversation_id')
        or (saved.get('role') != candidate.get('role') and not retracted)
        or any(actual.get(key) != expected.get(key) for key in ('submission_id', 'user_message_id'))
        or any(actual_thread.get(key) != expected_thread.get(key) for key in ('thread_id', 'thread_attempt'))
    ):
        raise ChatRetryError('This response changed.', code='submission_conflict')
    return saved


def publish_chat_attempt_message(messages, candidate, *, authorize):
    """Create once, atomically recording publication on the existing question.

    The receipt survives hard deletion of the answer. It is not a second retry
    identity or terminal authority: it only fences cross-container outbox
    materialization and shares the existing response_attempt binding.
    """
    conversation_id = candidate['conversation_id']
    attempt = _mapping(_mapping(candidate.get('metadata')).get('response_attempt'))
    question_id = attempt.get('user_message_id')
    for _ in range(12):
        authorize()
        try:
            saved = normalize_cosmos_document(messages.read_item(
                item=candidate['id'], partition_key=conversation_id,
            ))
        except CosmosResourceNotFoundError:
            saved = None
        if saved is not None:
            return _verify_attempt_reply(saved, candidate)
        try:
            question = normalize_cosmos_document(messages.read_item(
                item=question_id, partition_key=conversation_id,
            ))
        except CosmosResourceNotFoundError:
            raise ChatRetryError('This question is no longer available.', code='message_not_found', status_code=404) from None
        if question.get('role') != 'user' or is_soft_deleted_message(question):
            raise ChatRetryError('This question is no longer available.', code='message_not_found', status_code=404)
        current_attempt = _mapping(_mapping(question.get('metadata')).get('response_attempt'))
        if current_attempt.get('submission_id') != attempt.get('submission_id'):
            raise ChatRetryError('This submission changed.', code='submission_conflict')
        if current_attempt.get('message_id'):
            if current_attempt['message_id'] != candidate['id']:
                raise ChatRetryError('This response identity changed.', code='submission_conflict')
            # An earlier publisher may have won after our original absent read.
            try:
                return _verify_attempt_reply(normalize_cosmos_document(messages.read_item(
                    item=candidate['id'], partition_key=conversation_id,
                )), candidate)
            except CosmosResourceNotFoundError:
                return None  # The committed answer was subsequently hard-deleted.
        document = deepcopy(candidate)
        thread = _mapping(_mapping(question.get('metadata')).get('thread_info'))
        document.setdefault('metadata', {})['thread_info'] = deepcopy(thread)
        question['metadata']['response_attempt'] = {
            **current_attempt, 'message_id': candidate['id'],
        }
        try:
            messages.execute_item_batch(batch_operations=[
                ('replace', (question_id, question), {'if_match_etag': question['_etag']}),
                ('create', (document,)),
            ], partition_key=conversation_id)
            return normalize_cosmos_document(messages.read_item(
                item=candidate['id'], partition_key=conversation_id,
            ))
        except CosmosBatchOperationError as error:
            if error.status_code not in (404, 409, 412):
                raise
    raise ChatRetryError('Response publication changed. Reload it.', code='retry_attempt_changed')


def _publish_retry_attempt(messages, conversations, question):
    conversation_id = question['conversation_id']
    thread_id = question['metadata']['thread_info']['thread_id']
    conversation = conversations.read_item(item=conversation_id, partition_key=conversation_id)
    counter = _mapping(conversation.get('retry_threads')).get(thread_id) or {}
    if counter.get('user_message_id') != question['id']:
        raise ChatRetryError('The attempt changed during preparation. Reload it.', code='retry_attempt_changed')
    if counter.get('published'):
        return question
    question = select_retry_thread_attempt(
        messages, conversation_id, thread_id,
        question['metadata']['thread_info']['thread_attempt'],
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


class ChatAttemptStore:
    """Submission-scoped terminal authority in the existing destination-control container.

    The control container partitions on destination_conversation_id; messages live
    in a *different* container. A conditional terminal decision therefore retains
    an outbox until idempotent message materialization succeeds. Cancellation can
    win before that decision, never between the decision and its publication.
    No cache or process-local fallback is allowed. Callers supply fresh object
    authorization and screen the candidate before committing it. Materialization
    is create-only under the existing question's transactional publication fence.
    """

    INTENT_SECONDS = 600
    MAX_PENDING_INTENTS = 32
    TERMINAL = frozenset(("completed", "interrupted", "failed"))

    def __init__(self, controls, messages, *, actor_id, conversation_id, submission_id,
                 authorize, clock=time.time, publish=None, destination_id=None):
        self.controls = controls
        self.messages = messages
        self.actor_id = actor_id
        self.conversation_id = conversation_id
        self.destination_id = destination_id or conversation_id
        self.submission_id = normalize_submission_id(submission_id)
        if not actor_id or not self.destination_id or not self.submission_id:
            raise ChatRetryError(
                'The response submission identity is required. Reload before stopping.',
                code='submission_required', status_code=400,
            )
        self.authorize = authorize
        self.clock = clock
        self.publish = publish
        identity = json.dumps([actor_id, self.submission_id], separators=(',', ':'))
        self.item_id = f"chat_submission_{hashlib.sha256(identity.encode()).hexdigest()}"

    def read(self):
        self.authorize()
        try:
            record = normalize_cosmos_document(self.controls.read_item(
                item=self.item_id, partition_key=self.destination_id,
            ))
        except CosmosResourceNotFoundError:
            return None
        if (
            record.get('kind') != 'chat_submission'
            or record.get('user_id') != self.actor_id
            or record.get('submission_id') != self.submission_id
            or record.get('destination_conversation_id') != self.destination_id
        ):
            raise ChatRetryError('This response is unavailable.', code='forbidden', status_code=403)
        if self.conversation_id and record.get('conversation_id') not in (None, self.conversation_id):
            raise ChatRetryError('This submission destination changed.', code='submission_conflict')
        self.conversation_id = self.conversation_id or record.get('conversation_id')
        return record

    def _new(self):
        return {
            'id': self.item_id, 'kind': 'chat_submission', 'user_id': self.actor_id,
            'destination_conversation_id': self.destination_id, 'conversation_id': self.conversation_id,
            'submission_id': self.submission_id, 'created_at': self.clock(),
            'expires_at': self.clock() + self.INTENT_SECONDS,
            'state': 'prepared', 'admitted': False, 'dispatched': False,
        }

    def _replace(self, record):
        self.authorize()
        if not record.get('_etag'):
            raise ChatRetryError(
                'Response state could not be confirmed. Reload before retrying.',
                code='chat_attempt_storage_unavailable', status_code=503,
            )
        return normalize_cosmos_document(self.controls.replace_item(
            item=self.item_id, body=record, etag=record['_etag'],
            match_condition=MatchConditions.IfNotModified,
        ))

    @staticmethod
    def _conflict(error):
        return isinstance(error, CosmosHttpResponseError) and error.status_code in (409, 412)

    def _attempt_metadata(self, record):
        return {
            'kind': 'chat', 'submission_id': self.submission_id,
            'state': record['state'],
            'user_message_id': record.get('user_message_id'),
            'updated_at': datetime.now(timezone.utc).isoformat(),
        }

    def _acknowledge(self, **fields):
        for _ in range(12):
            latest = self.read()
            if not latest:
                return None
            latest.update(fields)
            if fields.get('question_state') is not None:
                latest.pop('question', None)
            if fields.get('materialized'):
                latest.pop('outbox', None)
            try:
                return self._replace(latest)
            except CosmosHttpResponseError as error:
                if not self._conflict(error):
                    raise
        raise ChatRetryError('Response state changed. Reload it.', code='retry_attempt_changed')

    def _materialize_question(self, record):
        if record.get('question_state') == record['state'] and not record.get('question'):
            return
        question = record.get('question')
        if not question and not record.get('user_message_id'):
            return
        question = question or {'id': record['user_message_id'], 'conversation_id': self.conversation_id}
        for _ in range(12):
            try:
                current = normalize_cosmos_document(self.messages.read_item(
                    item=question['id'], partition_key=self.conversation_id,
                ))
            except CosmosResourceNotFoundError:
                if not record.get('question') or record.get('question_requires_existing'):
                    raise ChatRetryError('This question is no longer available.', code='message_not_found', status_code=404) from None
                try:
                    self.messages.create_item(body=question)
                except CosmosResourceExistsError:
                    pass
                continue
            attempt = _mapping(_mapping(current.get('metadata')).get('response_attempt'))
            if attempt.get('submission_id') not in (None, self.submission_id):
                raise ChatRetryError('This submission changed.', code='submission_conflict')
            if is_soft_deleted_message(current):
                raise ChatRetryError('This question is no longer available.', code='message_not_found', status_code=404)
            current.setdefault('metadata', {})['response_attempt'] = {
                **attempt, **self._attempt_metadata(record),
            }
            try:
                self.messages.replace_item(
                    item=current['id'], body=current, etag=current['_etag'],
                    match_condition=MatchConditions.IfNotModified,
                )
                self._acknowledge(question_state=record['state'])
                return
            except CosmosAccessConditionFailedError:
                continue
        raise ChatRetryError('Response state changed. Reload it.', code='retry_attempt_changed')

    def begin(self, request_body, question, *, assistant_message_id=None):
        """Bind the existing submission/thread convention to server-created IDs once."""
        self.authorize()
        if question.get('conversation_id') != self.conversation_id or question.get('role') != 'user':
            raise ChatRetryError('This question is unavailable.', code='invalid_request', status_code=400)
        fingerprint = hashlib.sha256(json.dumps(
            request_body, sort_keys=True, ensure_ascii=False, separators=(',', ':'),
        ).encode()).hexdigest()
        for _ in range(12):
            existing = self.read()
            record = existing or self._new()
            if record.get('admitted'):
                if record.get('request_fingerprint') != fingerprint:
                    raise ChatRetryError('This submission was used for another request.', code='submission_conflict')
                if record.get('question_deleted'):
                    raise ChatRetryError('This question is no longer available.', code='message_not_found', status_code=404)
                if record['state'] != 'interrupted' and not (
                    record['state'] == 'prepared' and not record.get('dispatched')
                ):
                    raise ChatRetryError(
                        'This response was already submitted. Reload its saved state.',
                        code='retry_already_submitted',
                    )
                self.materialize()
                return self.read()
            if record['expires_at'] <= self.clock():
                raise ChatRetryError(
                    'This stopped submission expired. Send a new request explicitly.',
                    code='submission_expired',
                )
            question = deepcopy(normalize_cosmos_document(question))
            question.setdefault('metadata', {})['response_attempt'] = {
                **_mapping(_mapping(question.get('metadata')).get('response_attempt')),
                **self._attempt_metadata(record),
            }
            record.update({
                'conversation_id': self.conversation_id,
                'admitted': True, 'request_fingerprint': fingerprint,
                'user_message_id': question['id'], 'question': question,
                'question_requires_existing': bool(
                    question['metadata']['response_attempt'].get('source_user_message_id')
                ),
                'thread_info': deepcopy(question['metadata'].get('thread_info') or {}),
                'assistant_message_id': assistant_message_id,
                'destination_user_message_id': request_body.get('m365_collaboration_message_id'),
            })
            try:
                record = self._replace(record) if existing else normalize_cosmos_document(
                    self.controls.create_item(body=record),
                )
                self._materialize_question(record)
                return record
            except CosmosHttpResponseError as error:
                if not self._conflict(error):
                    raise
        raise ChatRetryError('Response state changed. Reload it.', code='retry_attempt_changed')

    def dispatch(self):
        """A duplicate, expired or canceled worker cannot acquire dispatch permission."""
        for _ in range(12):
            record = self.read()
            if not record or not record.get('admitted'):
                raise ChatRetryError('This submission is unavailable.', code='submission_required')
            if record['state'] in self.TERMINAL:
                self._materialize_question(record)
                return False
            if record.get('dispatched'):
                raise ChatRetryError('This response was already started.', code='retry_already_submitted')
            record.update({'state': 'running', 'dispatched': True})
            try:
                record = self._replace(record)
                self._materialize_question(record)
                return True
            except CosmosHttpResponseError as error:
                if not self._conflict(error):
                    raise
        raise ChatRetryError('Response state changed. Reload it.', code='retry_attempt_changed')

    def cancel(self, reason='user_requested'):
        """Persist a bounded pre-admission intent, or serialize against completion."""
        for _ in range(12):
            existing = self.read()
            record = existing or self._new()
            if record['state'] in self.TERMINAL and not record.get('cancel_reason'):
                return {
                    'outcome': 'already_completed', 'cancel_requested': False,
                    'message_id': record.get('message_id'), 'submission_id': self.submission_id,
                }
            if record.get('cancel_reason'):
                return self._cancel_result(record)
            if existing is None:
                rows = self.controls.query_items(
                    query=(
                        'SELECT TOP 33 * FROM c WHERE c.kind = "chat_submission" '
                        'AND c.user_id = @user_id AND c.admitted = false AND c.expires_at > @now'
                    ),
                    parameters=[{'name': '@user_id', 'value': self.actor_id}, {'name': '@now', 'value': self.clock()}],
                    partition_key=self.destination_id,
                )
                pending = [
                    row for row in rows if row.get('kind') == 'chat_submission'
                    and not row.get('admitted') and row.get('expires_at', 0) > self.clock()
                ]
                if len(pending) >= self.MAX_PENDING_INTENTS:
                    raise ChatRetryError('Too many pending stop requests. Please wait.', code='submission_limit', status_code=429)
            record.update({
                'state': 'interrupted', 'cancel_reason': (
                    reason if reason in ('user_requested', 'client_disconnect_timeout', 'replaced') else 'user_requested'
                ),
            })
            try:
                record = self._replace(record) if existing else normalize_cosmos_document(
                    self.controls.create_item(body=record),
                )
                self._materialize_question(record)
                return self._cancel_result(record)
            except CosmosHttpResponseError as error:
                if not self._conflict(error):
                    raise
        raise ChatRetryError('Stopping could not be confirmed. Please retry.', code='chat_attempt_storage_unavailable', status_code=503)

    def _cancel_result(self, record):
        return {
            'outcome': 'accepted', 'cancel_requested': True,
            'dispatch_prevented': not record.get('dispatched'),
            'submission_id': self.submission_id, 'user_message_id': record.get('user_message_id'),
        }

    def commit(self, message):
        """Fence success before publication; retain its outbox on a materialization failure."""
        incomplete = bool((message.get('metadata') or {}).get('incomplete'))
        for _ in range(12):
            record = self.read()
            if not record or not record.get('admitted'):
                raise ChatRetryError('This response is unavailable.', code='submission_required')
            safety_replacement = message.get('role') == 'safety' and (
                (message.get('metadata') or {}).get('content_moderation') or {}
            ).get('removed') is True
            if message.get('conversation_id') != self.conversation_id or (
                message.get('role') != 'assistant' and not safety_replacement
            ):
                raise ChatRetryError('This response changed.', code='submission_conflict')
            if record.get('assistant_message_id') and record['assistant_message_id'] != message['id']:
                raise ChatRetryError('This response identity changed.', code='submission_conflict')
            if record['state'] == 'completed' or record.get('message_id'):
                if record.get('message_id') != message['id']:
                    raise ChatRetryError('This submission already has a response.', code='submission_conflict')
                return self.materialize()
            if record['state'] in self.TERMINAL and not record.get('cancel_reason'):
                raise ChatRetryError('This response already finished.', code='chat_attempt_terminal')
            if record.get('cancel_reason') and not incomplete and not safety_replacement:
                raise ChatRetryError('This response was stopped.', code='chat_attempt_canceled')
            candidate = deepcopy(normalize_cosmos_document(message))
            metadata = candidate.setdefault('metadata', {})
            # Legacy aliases in a candidate are not cancellation authority.
            for field in ('canceled', 'cancel_reason', 'stop_reason'):
                metadata.pop(field, None)
            canceled = bool(record.get('cancel_reason'))
            record['state'] = 'interrupted' if incomplete or canceled else 'failed' if safety_replacement else 'completed'
            metadata.update({
                'response_attempt': self._attempt_metadata(record),
                'thread_info': deepcopy(record['thread_info']),
                'stream_status': 'blocked' if safety_replacement else 'stopped' if canceled else 'interrupted' if incomplete else 'completed',
                'complete': not incomplete and not canceled,
                'stopped_user_message_id': record['user_message_id'],
            })
            if incomplete or canceled:
                metadata.update({
                    'incomplete': True, 'canceled': canceled,
                    'stop_reason': 'user_cancelled' if record.get('cancel_reason') == 'user_requested'
                    else record.get('cancel_reason') or 'provider_interrupted',
                })
                if canceled:
                    metadata['cancel_reason'] = record['cancel_reason']
            record.update({'outbox': candidate, 'message_id': candidate['id'], 'materialized': False})
            try:
                self._replace(record)
                return self.materialize()
            except CosmosHttpResponseError as error:
                if not self._conflict(error):
                    raise
        raise ChatRetryError('Response state changed. Reload it.', code='retry_attempt_changed')

    def materialize(self):
        record = self.read()
        if not record:
            return None
        if not record.get('materialized'):
            self._materialize_question(record)
        if not record.get('message_id'):
            return None
        candidate = record.get('outbox')
        if candidate:
            # A legacy mutating publisher cannot preserve an absent precondition.
            # The screened outbox is always create-only under its question fence.
            saved = publish_chat_attempt_message(
                self.messages, candidate, authorize=self.authorize,
            )
        else:
            try:
                saved = normalize_cosmos_document(self.messages.read_item(
                    item=record['message_id'], partition_key=self.conversation_id,
                ))
            except CosmosResourceNotFoundError:
                if record.get('materialized'):
                    return None
                raise ChatRetryError('The saved response is unavailable.', code='chat_result_unavailable', status_code=503) from None
        if saved is not None and (
            _mapping(_mapping(saved.get('metadata')).get('response_attempt')).get('submission_id') != self.submission_id
        ):
            raise ChatRetryError('This response changed.', code='submission_conflict')
        self._acknowledge(materialized=True)
        return saved

    def finish_without_reply(self, state):
        if state not in ('completed', 'failed', 'interrupted'):
            raise ValueError('Invalid response terminal state.')
        for _ in range(12):
            record = self.read()
            if not record or record['state'] in self.TERMINAL:
                if record:
                    self._materialize_question(record)
                return record
            record['state'] = state
            try:
                record = self._replace(record)
                self._materialize_question(record)
                return record
            except CosmosHttpResponseError as error:
                if not self._conflict(error):
                    raise
        raise ChatRetryError('Response state changed. Reload it.', code='retry_attempt_changed')


def reconcile_chat_attempts(controls, messages, *, actor_id, conversation_id, authorize,
                            publish=None, destination_id=None, publish_destination=None):
    """Recover committed cross-container outboxes only after current destination access."""
    authorize()
    rows = controls.query_items(
        query=(
            'SELECT * FROM c WHERE c.kind = @kind AND c.conversation_id = @conversation_id '
            + ('AND c.user_id = @user_id ' if actor_id else '')
            + 'AND c.admitted = true AND (IS_DEFINED(c.outbox) OR IS_DEFINED(c.question) '
            'OR NOT IS_DEFINED(c.question_state) OR c.question_state != c.state '
            'OR (c.destination_conversation_id != c.conversation_id AND '
            '(NOT IS_DEFINED(c.destination_question_state) OR c.destination_question_state != c.state '
            'OR (IS_DEFINED(c.message_id) AND NOT IS_DEFINED(c.destination_materialized)))))'
        ),
        parameters=[
            {'name': '@kind', 'value': 'chat_submission'},
            {'name': '@conversation_id', 'value': conversation_id},
            *([{'name': '@user_id', 'value': actor_id}] if actor_id else []),
        ],
        partition_key=destination_id or conversation_id,
    )
    for row in rows:
        if (
            row.get('kind') != 'chat_submission' or not row.get('user_id')
            or (actor_id and row.get('user_id') != actor_id)
            or row.get('conversation_id') != conversation_id
            or row.get('destination_conversation_id') != (destination_id or conversation_id)
            or not row.get('admitted')
        ):
            continue
        source_pending = (
            row.get('question') or row.get('outbox') or row.get('question_state') != row.get('state')
        )
        destination_pending = publish_destination and (
            row.get('destination_question_state') != row.get('state')
            or (row.get('message_id') and not row.get('destination_materialized'))
        )
        if not source_pending and not destination_pending:
            continue
        store = ChatAttemptStore(
            controls, messages, actor_id=row['user_id'], conversation_id=conversation_id,
            destination_id=destination_id or conversation_id,
            submission_id=row['submission_id'], authorize=authorize, publish=publish,
        )
        try:
            saved = store.materialize()
        except ChatRetryError as error:
            if error.code != 'message_not_found':
                raise
            # A previously acknowledged question was intentionally removed.
            # This is not a storage-outage fallback and must not recreate it.
            store._acknowledge(
                question_state=row['state'], question_deleted=True, materialized=True,
                destination_question_state=row['state'], destination_materialized=True,
            )
            continue
        if destination_pending:
            publish_destination(store, saved)
