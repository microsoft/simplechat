# route_backend_conversations.py

import logging
import math
import re
import uuid
from functools import partial

from azure.core.exceptions import AzureError

from content_screening.access import build_available_document_response, public_history_messages, read_available_document_bytes
from content_screening.contracts import ScreeningError
from collaboration_models import (
    GROUP_MULTI_USER_CHAT_TYPE,
    PERSONAL_MULTI_USER_CHAT_TYPE,
    is_shared_conversation_backing,
)
from config import *
from functions_appinsights import log_event
from functions_chat_content_checks import CHECK_METADATA, attach_chat_check, check_chat_content, strip_private_chat_checks
from functions_chat_content_review import patch_chat_message_metadata, record_blocked_chat_attempt
from functions_agent_catalog import build_accessible_agent_catalog
from functions_assist_submissions import SubmissionIdError
from functions_chat_model_catalog import build_chat_model_catalog
from functions_chat_retry import (
    ChatRetryError, available_retry_attempts, build_replay_request, has_replay_agent_selection, load_owned_retry_message,
    order_retry_messages, prepare_retry_attempt, reconcile_prepared_retry, retry_source_user, set_retry_attempt_state,
)
from functions_governance import ensure_governance_access
from functions_model_catalog import ModelCatalogError
from functions_authentication import *
from functions_collaboration import (
    assert_user_can_view_collaboration_conversation,
    assert_user_can_participate_in_collaboration_conversation,
    ensure_collaboration_source_conversation,
    get_collaboration_conversation,
    list_group_collaboration_conversations_for_user,
    list_collaboration_messages,
    list_personal_collaboration_conversations_for_user,
    serialize_collaboration_conversation,
)
from functions_settings import *
from functions_conversation_feed import (
    CONVERSATION_FEED_SOURCE_COLLABORATION,
    CONVERSATION_FEED_SOURCE_LEGACY,
    build_conversation_feed_page,
    decode_conversation_feed_cursor,
    get_conversation_feed_source_offsets,
    is_conversation_feed_cursor_compatible,
    normalize_conversation_feed_page_size,
    sort_conversation_feed_recent,
    tag_conversation_feed_source,
)
from functions_conversation_metadata import get_conversation_metadata, update_conversation_with_metadata
from functions_citation_tracking import rebuild_conversation_used_documents
from functions_m365_citations import used_m365_items_for_viewer
from functions_conversation_unread import clear_conversation_unread, normalize_conversation_unread_state
from functions_conversation_cache import (
    build_conversation_cache_key,
    bump_conversation_cache_version,
    get_cached_conversation_payload,
    get_conversation_cache_settings,
    invalidate_conversation_cache_for_item,
    set_cached_conversation_payload,
)
from functions_image_messages import decode_image_content, get_complete_image_content, hydrate_image_messages, is_blob_backed_image_message, is_external_image_url
from functions_message_image_revisions import resolve_served_revision
from functions_image_edit import load_image_bytes_from_blob
from functions_image_formats import ImageFormatError, PREVIEW_VARIANTS, is_image_file_name, to_browser_image
from functions_image_references import references_from_metadata
from functions_notifications import mark_chat_response_notifications_read_for_conversation
from flask import Response, current_app, request, stream_with_context
from werkzeug.utils import secure_filename
from functions_debug import debug_print
from functions_collaboration_generated_documents import (
    authorize_generated_document_download,
    can_download_generated_document,
    collect_generated_documents,
)
from functions_documents import (
    build_document_download_response,
    delete_chat_upload_workspace_documents_for_conversation,
    serialize_chat_upload_workspace_documents_for_conversation,
)
from functions_group import get_user_groups
from functions_public_workspaces import get_user_visible_public_workspace_ids_from_settings, resolve_public_chat_workspace_ids
from public_chat_scope_state import PublicChatScopeError
from functions_azure_maps import refresh_azure_maps_message_citations
from functions_message_artifacts import (
    build_message_artifact_payload_map,
    filter_assistant_artifact_items,
    hydrate_agent_citations_from_artifacts,
)
from functions_message_deletion import (
    exclude_soft_deleted_messages,
    is_soft_deleted_message,
    strip_soft_delete_metadata,
)
from functions_m365_context import M365PolicyError
from functions_m365_pending_delivery import cancel_m365_conversation_deliveries
import functions_msgraph_pending_actions
from functions_simplechat_operations import (
    ConversationForkConflictError,
    create_personal_conversation_for_current_user,
    delete_blob_backed_chat_message_files,
    derive_conversation_title_from_message,
    fork_personal_conversation_for_user,
)
from swagger_wrapper import swagger_route, get_auth_security
from functions_activity_logging import log_conversation_creation, log_conversation_deletion, log_conversation_archival
from functions_thoughts import archive_thoughts_for_conversation, delete_thoughts_for_conversation
from functions_orchestration_recovery import (
    cleanup_conversation_checkpoints,
    conversation_cleanup_failure_context,
)
from functions_orchestration_artifacts import is_retained_orchestration_file
from functions_orchestration_external_configuration import ExternalConfigurationServiceError
from functions_orchestration_external_identity import ExternalIdentityServiceError
from functions_orchestration_output_store import OutputError, OutputStorageError
from functions_orchestration_result_contracts import ResultContractError
from functions_saved_analysis import (
    cleanup_chat_analysis_conversation,
    cleanup_chat_analysis_messages,
    is_saved_analysis_unavailable,
    sanitize_saved_analysis_messages,
)
from functions_workflow_chat_delivery import (
    DELIVERY_EDIT_UNSUPPORTED,
    DELIVERY_RETRY_UNSUPPORTED,
    is_workflow_delivery_message,
    workflow_delivery_refusal_payload,
)
from functions_workflow_result_masking import message_asks_about_workflow_result, message_uses_workflow_result
from functions_workflow_result_reader import WorkflowResultUnavailable, workflow_result_error_payload
from functions_workflow_result_store import WorkflowResultIntegrityError, WorkflowResultStorageUnavailableError
from utils_cache import invalidate_personal_search_cache


def _is_retained_orchestration_file(message):
    """Leave retained file records and bytes to conditional output cleanup."""
    return is_retained_orchestration_file(message)


def _enroll_retained_orchestration_outputs(user_id, conversation_id, run_id):
    """Initialize deletion-only resources only for admitted retained outputs."""
    # Legacy conversations must not construct harness clients during deletion.
    from functions_orchestration_bootstrap import build_orchestration_cleanup_service

    return build_orchestration_cleanup_service(user_id, conversation_id).enroll_run_cleanup(run_id)


def _conversation_delete_failure(error, conversation_id, *, stage, is_bulk=False):
    """Map failures to trusted browser text and sanitized cleanup telemetry."""
    code = 'conversation_delete_failed'
    message = 'The conversation could not be deleted. Please retry deletion.'
    status_code = 500
    event = '[CONVERSATION_DELETE] Conversation deletion failed.'
    if stage == 'm365_cancellation':
        code = 'conversation_pending_actions_cleanup_failed'
        message = 'Pending Microsoft 365 actions could not be stopped. The conversation was not deleted.'
        status_code = 503
        event = '[CONVERSATION_DELETE] Unable to stop outgoing Microsoft 365 actions.'
    elif stage in {'orchestration_cleanup', 'chat_analysis_cleanup'}:
        code = 'conversation_execution_cleanup_failed'
        message = (
            'Execution data could not be removed. Please retry deletion. '
            'If this continues, contact your administrator.'
        )
        status_code = 503
        event = (
            '[ORCHESTRATION_RUNS] Conversation recovery cleanup failed.'
            if stage == 'orchestration_cleanup'
            else '[CONVERSATION_DELETE] Saved analysis cleanup failed.'
        )
        if isinstance(error, WorkflowResultIntegrityError):
            code = 'conversation_execution_integrity_failed'
            message = (
                'Saved execution data could not be verified for deletion. '
                'Contact your administrator, then retry deletion.'
            )
        elif isinstance(error, (AzureError, WorkflowResultStorageUnavailableError, OutputStorageError)):
            code = 'conversation_execution_storage_unavailable'
            message = (
                'Execution data storage is unavailable. Please retry deletion. '
                'If this continues, ask your administrator to check storage access.'
            )
    log_event(
        event,
        extra={
            **conversation_cleanup_failure_context(error, conversation_id, stage=stage),
            'response_failure': code,
            'response_status_code': status_code,
            'is_bulk_operation': is_bulk,
        },
        level=logging.ERROR, exceptionTraceback=False,
    )
    return {'error': message, 'code': code}, status_code


def normalize_chat_type(conversation_item):
    chat_type = conversation_item.get('chat_type')
    if chat_type:
        if chat_type == 'personal':
            conversation_item['chat_type'] = 'personal_single_user'
            return conversation_item['chat_type'], True
        return chat_type, False

    primary_context = next(
        (ctx for ctx in conversation_item.get('context', []) if ctx.get('type') == 'primary'),
        None
    )
    if primary_context:
        if primary_context.get('scope') == 'group':
            chat_type = 'group-single-user'
        elif primary_context.get('scope') == 'public':
            chat_type = 'public'
        else:
            chat_type = 'personal_single_user'
    else:
        chat_type = 'personal_single_user'

    conversation_item['chat_type'] = chat_type
    return chat_type, True


SEARCH_MATCH_CONTAINS = 'contains'
SEARCH_MATCH_ALL_WORDS = 'all_words'
SEARCH_MATCH_ANY_WORD = 'any_word'
SEARCH_MATCH_WHOLE_WORD = 'whole_word'
SEARCH_MATCH_MODES = {
    SEARCH_MATCH_CONTAINS,
    SEARCH_MATCH_ALL_WORDS,
    SEARCH_MATCH_ANY_WORD,
    SEARCH_MATCH_WHOLE_WORD,
}

SEARCH_CHAT_TYPE_ALIASES = {
    'personal': {'personal_single_user', PERSONAL_MULTI_USER_CHAT_TYPE},
    'personal-single-user': {'personal_single_user'},
    'personal_single_user': {'personal_single_user'},
    'personal-multi-user': {PERSONAL_MULTI_USER_CHAT_TYPE},
    PERSONAL_MULTI_USER_CHAT_TYPE: {PERSONAL_MULTI_USER_CHAT_TYPE},
    'group': {'group-single-user', GROUP_MULTI_USER_CHAT_TYPE},
    'group-single-user': {'group-single-user'},
    'group_single_user': {'group-single-user'},
    'group-multi-user': {GROUP_MULTI_USER_CHAT_TYPE},
    GROUP_MULTI_USER_CHAT_TYPE: {GROUP_MULTI_USER_CHAT_TYPE},
    'public': {'public'},
}


def _build_conversation_cache_access_parameters(user_id):
    """Return current group-access inputs that affect collaboration feed/search visibility."""
    try:
        group_docs = get_user_groups(user_id)
    except Exception as exc:
        log_event(
            f"[CONVERSATION_CACHE] Failed to build group access cache fingerprint for {user_id}: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
            debug_only=True,
        )
        return None

    groups = []
    for group_doc in group_docs or []:
        if not isinstance(group_doc, dict):
            continue
        group_id = str(group_doc.get('id') or '').strip()
        if not group_id:
            continue
        groups.append({
            'id': group_id,
            'status': str(group_doc.get('status') or 'active'),
            'updated_at': str(
                group_doc.get('updated_at')
                or group_doc.get('last_updated')
                or group_doc.get('_ts')
                or ''
            ),
        })

    groups.sort(key=lambda group_item: group_item['id'])
    return {
        'groups': groups,
    }


def _normalize_workspace_document_delete_ids(raw_document_ids):
    if raw_document_ids is None:
        return []
    if not isinstance(raw_document_ids, list):
        raise ValueError('delete_workspace_document_ids must be an array')

    normalized_document_ids = []
    seen_document_ids = set()
    for raw_document_id in raw_document_ids:
        document_id = str(raw_document_id or '').strip()
        if not document_id or document_id in seen_document_ids:
            continue
        seen_document_ids.add(document_id)
        normalized_document_ids.append(document_id)

    return normalized_document_ids


def _build_replayed_document_context(original_metadata):
    """Rebuild document-context intent from stored metadata for retry and edit."""
    metadata = original_metadata if isinstance(original_metadata, dict) else {}
    workspace_search = metadata.get('workspace_search')
    if not isinstance(workspace_search, dict):
        workspace_search = metadata.get('document_search')
    workspace_search = workspace_search if isinstance(workspace_search, dict) else {}

    selected_document_ids = (
        workspace_search.get('requested_document_ids')
        if 'requested_document_ids' in workspace_search
        else workspace_search.get('selected_document_ids') or []
    )
    if not isinstance(selected_document_ids, list):
        selected_document_ids = [selected_document_ids]
    selected_document_ids = [
        str(document_id or '').strip()
        for document_id in selected_document_ids
        if str(document_id or '').strip()
    ]
    selected_document_id = str(
        workspace_search.get('selected_document_id')
        or workspace_search.get('document_id')
        or ''
    ).strip()
    if (
        selected_document_id and selected_document_id not in selected_document_ids
        and 'requested_document_ids' not in workspace_search
    ):
        selected_document_ids.insert(0, selected_document_id)

    selection_mode = str(workspace_search.get('selection_mode') or '').strip().lower()
    if selection_mode not in {'selected', 'all', 'history', 'relevance'}:
        selection_mode = 'selected' if selected_document_ids else 'relevance'
    document_context_requested = workspace_search.get('document_context_requested')
    if not isinstance(document_context_requested, bool):
        document_context_requested = bool(
            workspace_search.get('search_enabled')
            or workspace_search.get('enabled')
            or selected_document_ids
        )

    return {
        'hybrid_search': bool(
            workspace_search.get('hybrid_search_preference')
            if 'hybrid_search_preference' in workspace_search
            else workspace_search.get('enabled')
            or workspace_search.get('search_enabled')
        ),
        'selection_mode': selection_mode,
        'document_context_requested': document_context_requested,
        'selected_document_id': selected_document_ids[0] if selected_document_ids else None,
        'selected_document_ids': selected_document_ids,
        'doc_scope': workspace_search.get('document_scope') or workspace_search.get('scope'),
        'public_workspace_selection': workspace_search.get('public_workspace_selection'),
        'top_n': workspace_search.get('top_n'),
        'document_filter_mode': workspace_search.get('document_filter_mode') or 'intersection',
        'classifications': (
            workspace_search.get('classification')
            or workspace_search.get('classifications')
        ),
        # Restored alongside the document ids so a retry or edit reproduces the same search.
        # A tag filter dropped here silently widens the replay, which reads as the assistant
        # answering a different question the second time it is asked.
        'tags': (
            workspace_search.get('tags')
            or workspace_search.get('tags_filter')
            or []
        ),
        'active_group_ids': workspace_search.get('active_group_ids') or [],
        'active_public_workspace_ids': workspace_search.get('active_public_workspace_ids') or [],
    }


def _build_authorized_message_replay_request(user_id, source, options, settings, *, allow_auto_selection=False):
    metadata = source.get('metadata') or {}
    agent_requested = has_replay_agent_selection(metadata, options)
    groups = get_user_groups(user_id) if settings.get('enable_group_workspaces', False) else []
    document_context = _build_replayed_document_context(metadata)
    models, agents = [], []
    if agent_requested:
        if not settings.get('enable_semantic_kernel', False):
            raise ChatRetryError('Agent chat is no longer enabled. Choose an available model explicitly.', code='retry_agent_unavailable')
        agents = build_accessible_agent_catalog(user_id, settings=settings, user_groups=groups)
    elif not isinstance(metadata.get('image_generation'), dict) or not metadata['image_generation'].get('enabled'):
        user_settings = get_user_settings(user_id) if settings.get('allow_user_custom_endpoints', False) else {}
        models = build_chat_model_catalog(
            user_id=user_id, settings=settings,
            user_settings_dict=(user_settings or {}).get('settings', {}),
            user_groups_raw=groups,
        )
        if allow_auto_selection and not models:
            raise ChatRetryError('No enabled chat model is available for Auto routing. Review your selections.', code='retry_model_unavailable')
    body = build_replay_request(
        source, options, document_context=document_context, models=models, agents=agents,
        allow_legacy_default=allow_auto_selection or not settings.get('enable_multi_model_endpoints', False),
    )
    if body.get('agent_info'):
        agent = body['agent_info']
        if agent.get('is_global'):
            ensure_governance_access(
                'governance_global_agents_usage', user_id,
                item_entity_type='global_agent', item_id=str(agent.get('id') or agent.get('name') or ''),
            )
        else:
            ensure_governance_access(
                'governance_group_agents' if agent.get('is_group') else 'governance_user_agents',
                user_id,
            )
    requested_groups = set(body.get('active_group_ids') or [])
    if body.get('active_group_id'):
        requested_groups.add(body['active_group_id'])
    if requested_groups - {group['id'] for group in groups if group.get('id')}:
        raise ChatRetryError('An original group workspace is unavailable. Review the message sources.', code='retry_source_unavailable')
    requested_public = set(body.get('active_public_workspace_ids') or [])
    if body.get('active_public_workspace_id'):
        requested_public.add(body['active_public_workspace_id'])
    if requested_public:
        available_public = (
            resolve_public_chat_workspace_ids(user_id, body['public_workspace_selection'], settings=settings)
            if body.get('public_workspace_selection')
            else get_user_visible_public_workspace_ids_from_settings(user_id) or []
        )
        if requested_public - set(available_public):
            raise ChatRetryError('An original public workspace is unavailable. Review the message sources.', code='retry_source_unavailable')
    image_references = references_from_metadata(metadata)
    if image_references:
        body['image_references'] = image_references
    if metadata.get('image_reference_mask'):
        body['image_mask_dropped'] = True
    return body


def _message_attempt_payload(question, body, *, edited=False):
    thread = question['metadata']['thread_info']
    body.update({
        'edited_user_message_id' if edited else 'retry_user_message_id': question['id'],
        'retry_thread_id': thread['thread_id'], 'retry_thread_attempt': thread['thread_attempt'],
        'retry_source_user_message_id': question['metadata']['response_attempt']['source_user_message_id'],
    })
    return {
        'success': True, 'message': 'Edit initiated' if edited else 'Retry initiated',
        'thread_id': thread['thread_id'], 'new_attempt': thread['thread_attempt'],
        'user_message_id': question['id'], 'user_message': question,
        'attempt_state': question['metadata']['response_attempt']['state'],
        'available_attempts': available_retry_attempts(cosmos_messages_container, question['conversation_id'], thread['thread_id']),
        'edited': edited, 'chat_request': body,
    }


def _refuse_prepared_message_attempt(question, message, code):
    if question:
        set_retry_attempt_state(
            cosmos_messages_container, question['conversation_id'], question['id'],
            'failed', error=message, code=code, expected_states={'prepared'},
        )


def _prepare_message_attempt_response(message_id, *, edited=False):
    user_id = get_current_user_id()
    if not user_id:
        return jsonify({'error': 'User not authenticated'}), 401
    prepared_question = None
    try:
        data = request.get_json(silent=True)
        if data is None and not request.get_data():
            data = {}
        if not isinstance(data, dict):
            raise ChatRetryError('A retry request must be an object.', code='invalid_request', status_code=400)
        clicked, _conversation = load_owned_retry_message(
            cosmos_messages_container, cosmos_conversations_container, user_id, message_id,
        )
        attempt = (clicked.get('metadata') or {}).get('response_attempt') or {}
        if not edited and attempt.get('kind') == 'chat' and attempt.get('state') == 'prepared':
            if any(data.get(key) for key in ('model', 'model_deployment', 'model_id', 'model_endpoint_id', 'agent_info', 'reasoning_effort')):
                raise ChatRetryError('This attempt is already prepared. Generate its saved response before changing selections.', code='retry_in_progress')
            prepared_question = clicked
            body = _build_authorized_message_replay_request(user_id, clicked, {}, get_settings())
            question = reconcile_prepared_retry(cosmos_messages_container, cosmos_conversations_container, user_id, clicked)
            return jsonify(_message_attempt_payload(question, body, edited=bool(clicked['metadata'].get('edited')))), 200
        if is_workflow_delivery_message(clicked):
            payload, status = workflow_delivery_refusal_payload(
                DELIVERY_EDIT_UNSUPPORTED if edited else DELIVERY_RETRY_UNSUPPORTED,
            )
            return jsonify(payload), status
        if edited and clicked.get('role') != 'user':
            raise ChatRetryError('Only user messages can be edited.', code='invalid_request', status_code=400)
        source = retry_source_user(cosmos_messages_container, clicked)
        source_author = (source.get('metadata') or {}).get('user_info', {}).get('user_id')
        if source_author and source_author != user_id:
            raise ChatRetryError('You can only retry your own questions.', code='forbidden', status_code=403)
        if (source.get('metadata') or {}).get('orchestration'):
            raise ChatRetryError(
                'Regenerate an orchestration plan from this message instead of replaying it as ordinary chat.',
                code='retry_requires_orchestration',
            )
        if message_asks_about_workflow_result(clicked) or message_asks_about_workflow_result(source):
            payload, status = workflow_result_error_payload(WorkflowResultUnavailable('workflow_result_retry_unsupported'))
            return jsonify(payload), status
        content = data.get('content') if edited else source.get('content')
        if not isinstance(content, str) or not content.strip():
            raise ChatRetryError('Message content cannot be empty.', code='invalid_request', status_code=400)
        settings = get_settings()
        input_check = check_chat_content(content, 'chat_input', user_id=user_id, settings=settings)
        if input_check.blocked:
            record_blocked_chat_attempt(input_check, user_id, source['conversation_id'])
            return jsonify({'error': input_check.notice, 'blocked': True}), 422
        body = _build_authorized_message_replay_request(user_id, source, {} if edited else data, settings)
        body['message'] = content.strip() if edited else content
        submission_id = data.get('submission_id') or str(uuid.uuid4())
        question = prepare_retry_attempt(
            cosmos_messages_container, cosmos_conversations_container, user_id, source, body,
            submission_id=submission_id, edited=edited,
        )
        attach_chat_check(question, input_check)
        patch_chat_message_metadata(cosmos_messages_container, question, fields=(CHECK_METADATA,))
        _rebuild_authorized_personal_conversation_used_documents(user_id, source['conversation_id'])
        _invalidate_conversation_cache_after_message_mutation(
            source['conversation_id'], user_id, 'message_edit_created' if edited else 'message_retry_created',
        )
        return jsonify(_message_attempt_payload(question, body, edited=edited)), 200
    except ChatRetryError as error:
        _refuse_prepared_message_attempt(prepared_question, error.public_message, error.code)
        log_event('[CHAT_RETRY] Retry refused.', extra={'code': error.code, 'user_id': user_id}, level=logging.INFO)
        return jsonify({'error': error.public_message, 'code': error.code}), error.status_code
    except (SubmissionIdError, ModelCatalogError) as error:
        message = 'The retry selection or request identifier is invalid. Review your selections.'
        _refuse_prepared_message_attempt(prepared_question, message, 'invalid_retry_selection')
        log_event('[CHAT_RETRY] Invalid retry selection.', extra={'error_type': type(error).__name__}, level=logging.WARNING)
        return jsonify({'error': message, 'code': 'invalid_retry_selection'}), 400
    except PermissionError:
        message = 'An original selection is no longer authorized. Review your selections.'
        _refuse_prepared_message_attempt(prepared_question, message, 'forbidden')
        log_event('[CHAT_RETRY] Retry selection is no longer authorized.', extra={'user_id': user_id}, level=logging.WARNING)
        return jsonify({'error': message, 'code': 'forbidden'}), 403
    except ScreeningError as error:
        return jsonify({'error': error.public_message, 'error_code': error.code}), error.status_code
    except PublicChatScopeError as error:
        _refuse_prepared_message_attempt(prepared_question, error.public_message, error.code)
        return jsonify({'error': error.public_message, 'code': error.code}), error.status_code
    except AzureError as error:
        log_event(
            '[CHAT_RETRY] Retry preparation storage is unavailable.',
            extra={'error_type': type(error).__name__, 'user_id': user_id}, level=logging.ERROR,
        )
        return jsonify({
            'error': 'The retry could not be prepared. Reload to check the attempt before retrying.',
            'code': 'retry_storage_unavailable',
        }), 503


def _get_requested_workspace_document_delete_ids_for_conversation(payload, conversation_id):
    if not isinstance(payload, dict):
        return []

    if 'delete_workspace_document_ids' in payload:
        return _normalize_workspace_document_delete_ids(payload.get('delete_workspace_document_ids'))

    delete_ids_by_conversation = payload.get('delete_workspace_document_ids_by_conversation')
    if isinstance(delete_ids_by_conversation, dict):
        return _normalize_workspace_document_delete_ids(delete_ids_by_conversation.get(conversation_id))

    return []


def _normalize_search_match_mode(match_mode):
    normalized_mode = str(match_mode or SEARCH_MATCH_CONTAINS).strip().lower().replace('-', '_')
    if normalized_mode in SEARCH_MATCH_MODES:
        return normalized_mode
    return SEARCH_MATCH_CONTAINS


def _tokenize_search_terms(search_term):
    return [term for term in re.split(r'\s+', str(search_term or '').strip()) if term]


def _get_message_query_terms(search_term, match_mode):
    normalized_mode = _normalize_search_match_mode(match_mode)
    if normalized_mode in (SEARCH_MATCH_ALL_WORDS, SEARCH_MATCH_ANY_WORD):
        return _tokenize_search_terms(search_term)
    return [str(search_term or '').strip()]


def _normalize_search_chat_type_value(chat_type):
    normalized_type = str(chat_type or '').strip().lower()
    if not normalized_type:
        return 'personal_single_user'

    if normalized_type == 'personal':
        return 'personal_single_user'
    if normalized_type == 'group':
        return 'group-single-user'
    if normalized_type == 'group-multi-user':
        return GROUP_MULTI_USER_CHAT_TYPE
    if normalized_type == 'group_single_user':
        return 'group-single-user'
    if normalized_type == 'personal-multi-user':
        return PERSONAL_MULTI_USER_CHAT_TYPE
    if normalized_type == 'personal-single-user':
        return 'personal_single_user'
    return normalized_type


def _expand_search_chat_type_filters(chat_types):
    normalized_filters = set()
    for chat_type in chat_types or []:
        normalized_key = str(chat_type or '').strip().lower()
        if not normalized_key:
            continue
        normalized_filters.update(
            SEARCH_CHAT_TYPE_ALIASES.get(
                normalized_key,
                {_normalize_search_chat_type_value(normalized_key)},
            )
        )
    return normalized_filters


def _get_search_conversation_chat_type(conversation_item):
    raw_chat_type = str((conversation_item or {}).get('chat_type') or '').strip()
    if raw_chat_type:
        return _normalize_search_chat_type_value(raw_chat_type)

    normalized_item = dict(conversation_item or {})
    inferred_chat_type, _ = normalize_chat_type(normalized_item)
    return _normalize_search_chat_type_value(inferred_chat_type)


def _conversation_matches_selected_chat_types(conversation_item, selected_chat_types):
    if not selected_chat_types:
        return True
    return _get_search_conversation_chat_type(conversation_item) in selected_chat_types


def _conversation_matches_classifications(conversation_item, classifications):
    if not classifications:
        return True
    conversation_classifications = conversation_item.get('classification', []) or []
    return any(classification in conversation_classifications for classification in classifications)


def _conversation_timestamp(conversation_item):
    return (
        conversation_item.get('last_updated')
        or conversation_item.get('updated_at')
        or conversation_item.get('last_message_at')
        or conversation_item.get('created_at')
        or ''
    )


def _conversation_matches_date_range(conversation_item, date_from='', date_to=''):
    timestamp = _conversation_timestamp(conversation_item)
    if date_from and (not timestamp or timestamp < date_from):
        return False
    if date_to and (not timestamp or timestamp > f'{date_to}T23:59:59'):
        return False
    return True


def _matches_search_text(text, search_term, match_mode=SEARCH_MATCH_CONTAINS):
    normalized_mode = _normalize_search_match_mode(match_mode)
    text_value = str(text or '')
    text_lower = text_value.lower()
    normalized_search = str(search_term or '').strip()
    search_lower = normalized_search.lower()

    if not search_lower:
        return False

    if normalized_mode == SEARCH_MATCH_ALL_WORDS:
        terms = [term.lower() for term in _tokenize_search_terms(normalized_search)]
        return bool(terms) and all(term in text_lower for term in terms)

    if normalized_mode == SEARCH_MATCH_ANY_WORD:
        terms = [term.lower() for term in _tokenize_search_terms(normalized_search)]
        return bool(terms) and any(term in text_lower for term in terms)

    if normalized_mode == SEARCH_MATCH_WHOLE_WORD:
        whole_word_pattern = re.compile(rf'(?<!\w){re.escape(normalized_search)}(?!\w)', re.IGNORECASE)
        return whole_word_pattern.search(text_value) is not None

    return search_lower in text_lower


def _find_search_match(text, search_term, match_mode=SEARCH_MATCH_CONTAINS):
    normalized_mode = _normalize_search_match_mode(match_mode)
    text_value = str(text or '')
    text_lower = text_value.lower()
    normalized_search = str(search_term or '').strip()
    search_lower = normalized_search.lower()

    if not search_lower:
        return -1, 0

    if normalized_mode in (SEARCH_MATCH_ALL_WORDS, SEARCH_MATCH_ANY_WORD):
        matches = []
        for term in _tokenize_search_terms(normalized_search):
            position = text_lower.find(term.lower())
            if position != -1:
                matches.append((position, len(term)))
        if matches:
            return min(matches, key=lambda item: item[0])
        return -1, 0

    if normalized_mode == SEARCH_MATCH_WHOLE_WORD:
        whole_word_pattern = re.compile(rf'(?<!\w){re.escape(normalized_search)}(?!\w)', re.IGNORECASE)
        match = whole_word_pattern.search(text_value)
        if match:
            return match.start(), match.end() - match.start()
        return -1, 0

    position = text_lower.find(search_lower)
    return position, len(normalized_search) if position != -1 else 0


def _build_message_search_query(search_term, match_mode):
    query_terms = _get_message_query_terms(search_term, match_mode)
    query_terms = [term for term in query_terms if term]
    if not query_terms:
        return None, []

    operator = ' OR ' if _normalize_search_match_mode(match_mode) == SEARCH_MATCH_ANY_WORD else ' AND '
    contains_conditions = []
    parameters = []
    for index, term in enumerate(query_terms):
        parameter_name = f'@term{index}'
        contains_conditions.append(f'CONTAINS(m.content, {parameter_name}, true)')
        parameters.append({'name': parameter_name, 'value': term})

    query = (
        'SELECT * FROM m WHERE '
        f'({operator.join(contains_conditions)}) '
        "AND (m.role = 'user' OR m.role = 'assistant')"
    )
    return query, parameters


def _query_matching_messages(container, search_term, match_mode):
    query, parameters = _build_message_search_query(search_term, match_mode)
    if not query:
        return []

    messages = list(container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
        max_item_count=-1,
    ))

    return [
        message for message in exclude_soft_deleted_messages(messages)
        if _matches_search_text(message.get('content', ''), search_term, match_mode)
    ]


def _message_is_in_active_thread(message_item):
    thread_info = (message_item.get('metadata') or {}).get('thread_info', {})
    return thread_info.get('active_thread') is not False


def _message_matches_attachment_filters(message_item, has_files=False, has_images=False):
    if not has_files and not has_images:
        return True

    metadata = message_item.get('metadata') or {}
    if has_files and metadata.get('uploaded_files'):
        return True
    if has_images and metadata.get('generated_images'):
        return True
    return False


def _build_message_snippets(matching_messages, search_term, match_mode, max_messages=5):
    message_snippets = []
    for message_item in matching_messages[:max_messages]:
        content = str(message_item.get('content', '') or '')
        match_pos, match_length = _find_search_match(content, search_term, match_mode)
        if match_pos == -1:
            continue

        start = max(0, match_pos - 50)
        end = min(len(content), match_pos + match_length + 50)
        snippet = content[start:end]

        if start > 0:
            snippet = f'...{snippet}'
        if end < len(content):
            snippet = f'{snippet}...'

        message_snippets.append({
            'message_id': message_item.get('id'),
            'content_snippet': snippet,
            'timestamp': message_item.get('timestamp', ''),
            'role': message_item.get('role', 'unknown'),
        })
    return message_snippets


def _build_search_conversation_payload(conversation_item):
    return {
        'id': conversation_item.get('id'),
        'title': conversation_item.get('title', 'Untitled'),
        'last_updated': _conversation_timestamp(conversation_item),
        'classification': conversation_item.get('classification', []) or [],
        'chat_type': _get_search_conversation_chat_type(conversation_item),
        'is_pinned': bool(conversation_item.get('is_pinned', False)),
        'is_hidden': bool(conversation_item.get('is_hidden', False)),
    }


def _load_accessible_collaboration_search_conversations(user_id):
    conversations = []
    seen_conversation_ids = set()

    for conversation_doc, user_state in list_personal_collaboration_conversations_for_user(user_id):
        serialized = serialize_collaboration_conversation(
            conversation_doc,
            current_user_id=user_id,
            user_state=user_state,
        )
        conversation_id = serialized.get('id')
        if conversation_id and conversation_id not in seen_conversation_ids:
            conversations.append(serialized)
            seen_conversation_ids.add(conversation_id)

    for conversation_doc, user_state in list_group_collaboration_conversations_for_user(user_id):
        serialized = serialize_collaboration_conversation(
            conversation_doc,
            current_user_id=user_id,
            user_state=user_state,
        )
        conversation_id = serialized.get('id')
        if conversation_id and conversation_id not in seen_conversation_ids:
            conversations.append(serialized)
            seen_conversation_ids.add(conversation_id)

    return conversations


def _is_conversation_priority(conversation_item):
    return bool(
        (conversation_item or {}).get('is_pinned', False)
        or (conversation_item or {}).get('has_unread_assistant_response', False)
    )


def _conversation_feed_matches_search(conversation_item, search_term):
    normalized_search = str(search_term or '').strip()
    if not normalized_search:
        return True
    return _matches_search_text((conversation_item or {}).get('title', ''), normalized_search)


def _query_legacy_conversations_for_feed(
    user_id,
    include_hidden=False,
    search_term='',
    extra_conditions=None,
    offset=0,
    limit=None,
):
    query_parts = ['c.user_id = @user_id']
    query_parameters = [{'name': '@user_id', 'value': user_id}]

    if not include_hidden:
        query_parts.append('(NOT IS_DEFINED(c.is_hidden) OR c.is_hidden = false)')

    if search_term:
        query_parts.append('(IS_STRING(c.title) AND CONTAINS(LOWER(c.title), @search_term))')
        query_parameters.append({'name': '@search_term', 'value': str(search_term).lower()})

    for condition in extra_conditions or []:
        query_parts.append(condition)

    normalized_offset = max(0, int(offset or 0))
    normalized_limit = None
    if limit is not None:
        normalized_limit = max(1, int(limit))

    query = f"SELECT * FROM c WHERE {' AND '.join(query_parts)} ORDER BY c.last_updated DESC"
    if normalized_limit is not None:
        query = f'{query} OFFSET {normalized_offset} LIMIT {normalized_limit}'

    items = list(cosmos_conversations_container.query_items(
        query=query,
        parameters=query_parameters,
        enable_cross_partition_query=True,
    ))

    return [
        tag_conversation_feed_source(
            normalize_conversation_unread_state(item),
            CONVERSATION_FEED_SOURCE_LEGACY,
        )
        for item in items
    ]


def _count_hidden_legacy_conversations(user_id):
    # A shared conversation's orchestration backing record is not a hidden conversation.
    query = (
        'SELECT VALUE COUNT(1) FROM c '
        'WHERE c.user_id = @user_id AND c.is_hidden = true '
        'AND (NOT IS_DEFINED(c.collaboration_conversation_id) OR c.collaboration_conversation_id != c.id)'
    )
    results = list(cosmos_conversations_container.query_items(
        query=query,
        parameters=[{'name': '@user_id', 'value': user_id}],
        enable_cross_partition_query=True,
    ))
    return int(results[0]) if results else 0


def _load_unread_collaboration_notification_map(user_id):
    query = """
        SELECT c.metadata.conversation_id AS conversation_id,
               c.metadata.message_id AS message_id,
               c.created_at AS created_at
        FROM c
        WHERE c.user_id = @user_id
        AND c.notification_type = @notification_type
        AND (NOT IS_DEFINED(c.read_by) OR NOT ARRAY_CONTAINS(c.read_by, @user_id))
    """
    notifications = list(cosmos_notifications_container.query_items(
        query=query,
        parameters=[
            {'name': '@user_id', 'value': user_id},
            {'name': '@notification_type', 'value': 'collaboration_message_received'},
        ],
        partition_key=user_id,
    ))

    unread_by_conversation = {}
    for notification in notifications:
        conversation_id = str(notification.get('conversation_id') or '').strip()
        if not conversation_id:
            continue

        current_notification = unread_by_conversation.get(conversation_id)
        if (
            current_notification is None
            or str(notification.get('created_at') or '') > str(current_notification.get('created_at') or '')
        ):
            unread_by_conversation[conversation_id] = notification

    return unread_by_conversation


def _load_collaboration_conversations_for_feed(user_id):
    conversations = _load_accessible_collaboration_search_conversations(user_id)
    try:
        unread_by_conversation = _load_unread_collaboration_notification_map(user_id)
    except Exception as exc:
        log_event(
            f'[CONVERSATION_FEED] Failed to load collaboration unread state: {exc}',
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        unread_by_conversation = {}
    feed_conversations = []

    for conversation in conversations:
        feed_conversation = tag_conversation_feed_source(
            conversation,
            CONVERSATION_FEED_SOURCE_COLLABORATION,
        )
        unread_notification = unread_by_conversation.get(str(feed_conversation.get('id') or ''))
        if unread_notification:
            feed_conversation['has_unread_assistant_response'] = True
            feed_conversation['last_unread_assistant_message_id'] = unread_notification.get('message_id')
            feed_conversation['last_unread_assistant_at'] = unread_notification.get('created_at')
        feed_conversations.append(feed_conversation)

    return feed_conversations


def _filter_collaboration_conversations_for_feed(conversations, include_hidden=False, search_term=''):
    filtered_conversations = []
    for conversation in conversations or []:
        if not include_hidden and conversation.get('is_hidden', False):
            continue
        if not _conversation_feed_matches_search(conversation, search_term):
            continue
        filtered_conversations.append(conversation)
    return filtered_conversations


def _filter_legacy_source_duplicates(conversations, collaboration_source_ids):
    if not collaboration_source_ids:
        return list(conversations or [])

    return [
        conversation for conversation in conversations or []
        if str(conversation.get('id') or '').strip() not in collaboration_source_ids
    ]


def _build_conversation_feed(user_id, page_size, source_offsets, include_priority, include_hidden, search_term):
    recent_fetch_limit = page_size + 1
    hidden_count = _count_hidden_legacy_conversations(user_id)

    try:
        collaboration_conversations = _load_collaboration_conversations_for_feed(user_id)
    except Exception as exc:
        log_event(
            f'[CONVERSATION_FEED] Failed to load collaborative conversations: {exc}',
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        collaboration_conversations = []

    hidden_count += sum(1 for conversation in collaboration_conversations if conversation.get('is_hidden', False))
    # A shared conversation's own id also names its orchestration backing record, and a
    # record an earlier version created there; neither is a separate conversation.
    collaboration_source_ids = {
        str(conversation.get('source_conversation_id') or '').strip()
        for conversation in collaboration_conversations
        if conversation.get('source_conversation_id')
    } | {
        str(conversation.get('id') or '').strip()
        for conversation in collaboration_conversations
        if conversation.get('id')
    }

    filtered_collaboration_conversations = _filter_collaboration_conversations_for_feed(
        collaboration_conversations,
        include_hidden=include_hidden,
        search_term=search_term,
    )
    collaboration_priority_conversations = [
        conversation for conversation in filtered_collaboration_conversations
        if _is_conversation_priority(conversation)
    ]
    collaboration_recent_conversations = [
        conversation for conversation in filtered_collaboration_conversations
        if not _is_conversation_priority(conversation)
    ]
    collaboration_recent_conversations = sort_conversation_feed_recent(collaboration_recent_conversations)
    collaboration_offset = source_offsets.get(CONVERSATION_FEED_SOURCE_COLLABORATION, 0)
    collaboration_recent_window = collaboration_recent_conversations[
        collaboration_offset:collaboration_offset + recent_fetch_limit
    ]

    priority_conversations = list(collaboration_priority_conversations) if include_priority else []
    if include_priority:
        legacy_pinned_conversations = _query_legacy_conversations_for_feed(
            user_id,
            include_hidden=include_hidden,
            search_term=search_term,
            extra_conditions=['c.is_pinned = true'],
        )
        legacy_unread_conversations = _query_legacy_conversations_for_feed(
            user_id,
            include_hidden=include_hidden,
            search_term=search_term,
            extra_conditions=[
                'c.has_unread_assistant_response = true',
                '(NOT IS_DEFINED(c.is_pinned) OR c.is_pinned = false)',
            ],
        )
        priority_conversations.extend(_filter_legacy_source_duplicates(
            legacy_pinned_conversations + legacy_unread_conversations,
            collaboration_source_ids,
        ))

    legacy_recent_conversations = _query_legacy_conversations_for_feed(
        user_id,
        include_hidden=include_hidden,
        search_term=search_term,
        extra_conditions=[
            '(NOT IS_DEFINED(c.is_pinned) OR c.is_pinned = false)',
            '(NOT IS_DEFINED(c.has_unread_assistant_response) OR c.has_unread_assistant_response = false)',
        ],
        offset=source_offsets.get(CONVERSATION_FEED_SOURCE_LEGACY, 0),
        limit=recent_fetch_limit,
    )
    legacy_recent_conversations = _filter_legacy_source_duplicates(
        legacy_recent_conversations,
        collaboration_source_ids,
    )

    return build_conversation_feed_page(
        priority_conversations=priority_conversations,
        recent_conversations_by_source={
            CONVERSATION_FEED_SOURCE_LEGACY: legacy_recent_conversations,
            CONVERSATION_FEED_SOURCE_COLLABORATION: collaboration_recent_window,
        },
        page_size=page_size,
        source_offsets=source_offsets,
        include_priority=include_priority,
        hidden_count=hidden_count,
        search_term=search_term,
        include_hidden=include_hidden,
    )


def _collect_child_message_documents(conversation_id, root_message_ids):
    """Collect child records linked by parent_message_id for the provided message ids."""
    pending_ids = [message_id for message_id in root_message_ids if message_id]
    seen_ids = set(pending_ids)
    child_docs = []

    while pending_ids:
        parent_message_id = pending_ids.pop(0)
        child_query = (
            "SELECT * FROM c "
            "WHERE c.conversation_id = @conversation_id "
            "AND c.parent_message_id = @parent_message_id"
        )
        child_results = list(cosmos_messages_container.query_items(
            query=child_query,
            parameters=[
                {'name': '@conversation_id', 'value': conversation_id},
                {'name': '@parent_message_id', 'value': parent_message_id},
            ],
            partition_key=conversation_id,
        ))

        for child_doc in child_results:
            child_id = child_doc.get('id')
            if not child_id or child_id in seen_ids:
                continue

            seen_ids.add(child_id)
            child_docs.append(child_doc)
            pending_ids.append(child_id)

    return child_docs


def _thread_attempt_number(message_doc):
    """Return a message's thread attempt, defaulting to 0 like the attempt sorts do."""
    metadata = (message_doc or {}).get('metadata') or {}
    thread_info = metadata.get('thread_info') or {}
    return thread_info.get('thread_attempt', 0)


def _promote_remaining_thread_attempt(conversation_id, thread_id, deleted_attempt, deleted_message_ids):
    """Activate another attempt after a delete removes the active attempt's question.

    Deleting only an answer leaves its question, and so its attempt, in place, and nothing is
    promoted. Soft-deleted attempts are never promoted. The promoted attempt becomes the only
    active one, so whatever is left of the deleted attempt stops showing beside it. Returns
    the promoted attempt number, or None when no attempt was promoted.
    """
    thread_messages = list(cosmos_messages_container.query_items(
        query=(
            'SELECT * FROM c WHERE c.conversation_id = @conversation_id '
            'AND c.metadata.thread_info.thread_id = @thread_id'
        ),
        parameters=[
            {'name': '@conversation_id', 'value': conversation_id},
            {'name': '@thread_id', 'value': thread_id},
        ],
        partition_key=conversation_id,
    ))
    remaining_messages = [
        message for message in exclude_soft_deleted_messages(thread_messages)
        if message.get('id') not in deleted_message_ids
    ]
    remaining_attempts = {
        _thread_attempt_number(message)
        for message in remaining_messages
        if message.get('role') == 'user'
    }
    if not remaining_attempts or deleted_attempt in remaining_attempts:
        return None

    promoted_attempt = min(remaining_attempts)
    for message in remaining_messages:
        metadata = message.get('metadata')
        if not isinstance(metadata, dict):
            metadata = {}
            message['metadata'] = metadata
        thread_info = metadata.get('thread_info')
        if not isinstance(thread_info, dict):
            thread_info = {}
            metadata['thread_info'] = thread_info
        should_be_active = _thread_attempt_number(message) == promoted_attempt
        if thread_info.get('active_thread') is should_be_active:
            continue
        thread_info['active_thread'] = should_be_active
        patch_chat_message_metadata(cosmos_messages_container, message)

    return promoted_attempt


def _authorize_personal_conversation_read(user_id, conversation_id):
    """Load a personal conversation and ensure the caller owns it.

    A shared conversation's Orchestrate backing record has the shared conversation's id but is
    part of the shared conversation, so it is reported as not found here. Callers that also
    serve shared conversations then fall through to them.
    """
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    if is_shared_conversation_backing(conversation_item):
        raise LookupError(f"Conversation {conversation_id} not found")
    if conversation_item.get('user_id') != user_id:
        raise PermissionError('Forbidden')

    return conversation_item


def hydrate_m365_pending_action_cards(messages, viewer_user_id, conversation_id):
    """Project current cards only after the caller authorizes message history."""
    return functions_msgraph_pending_actions.hydrate_m365_pending_action_cards(
        messages, viewer_user_id, conversation_id,
    )


def _list_personal_conversation_generated_documents(conversation_item):
    """Return the documents SimpleChat upload actions created in a personal conversation.

    ``conversation_item`` must already be authorized with ``_authorize_personal_conversation_read``.
    Only messages the thread shows are read, filtered the way ``/api/get_messages`` filters them:
    deleted messages, the assistant artifact store, hidden generated chat files and replaced
    thread attempts are left out. A citation stored in compact form is rebuilt from its artifact
    record first, because the created document's id is in the full tool result.
    """
    conversation_id = conversation_item['id']
    raw_messages = list(cosmos_messages_container.query_items(
        query='SELECT * FROM c WHERE c.conversation_id = @conversation_id',
        parameters=[{'name': '@conversation_id', 'value': conversation_id}],
        partition_key=conversation_id,
    ))
    raw_messages.sort(key=lambda item: (
        str(item.get('timestamp') or ''),
        int(item.get('fork_sequence')) if str(item.get('fork_sequence') or '').isdigit() else 0,
        str(item.get('id') or ''),
    ))
    raw_messages = exclude_soft_deleted_messages(raw_messages)
    artifact_payload_map = build_message_artifact_payload_map(raw_messages)

    visible_messages = []
    for item in filter_assistant_artifact_items(raw_messages):
        metadata = item.get('metadata') if isinstance(item.get('metadata'), dict) else {}
        if metadata.get('is_generated_chat_artifact', False):
            continue
        thread_info = metadata.get('thread_info') if isinstance(metadata.get('thread_info'), dict) else {}
        active_thread = thread_info.get('active_thread')
        if active_thread is True or active_thread is None:
            visible_messages.append(item)

    documents = collect_generated_documents(
        hydrate_agent_citations_from_artifacts(visible_messages, artifact_payload_map),
    )
    log_event(
        '[CONVERSATION_GENERATED_DOCUMENTS] Listed generated documents for a personal conversation.',
        extra={
            'conversation_id': conversation_id,
            'message_count': len(visible_messages),
            'document_count': len(documents),
        },
        debug_only=True,
    )
    return documents


def _rebuild_authorized_personal_conversation_used_documents(
    user_id,
    conversation_id,
):
    """Persist exact used documents after an authorized message mutation."""
    try:
        conversation_item = _authorize_personal_conversation_read(
            user_id,
            conversation_id,
        )
        messages = list(cosmos_messages_container.query_items(
            query=(
                "SELECT * FROM c "
                "WHERE c.conversation_id = @conversation_id"
            ),
            parameters=[
                {
                    "name": "@conversation_id",
                    "value": conversation_id,
                },
            ],
            partition_key=conversation_id,
        ))
        rebuild_conversation_used_documents(conversation_item, messages)
        conversation_item.pop('used_documents_rebuild_required', None)
        conversation_item['last_updated'] = datetime.utcnow().isoformat()
        cosmos_conversations_container.upsert_item(conversation_item)
        return conversation_item
    except Exception as rebuild_error:
        if 'conversation_item' in locals() and isinstance(conversation_item, dict):
            conversation_item['used_documents_rebuild_required'] = True
            try:
                cosmos_conversations_container.upsert_item(conversation_item)
            except Exception as marker_error:
                log_event(
                    "[CONVERSATION_METADATA] Failed to mark used documents for rebuild",
                    extra={
                        "conversation_id": conversation_id,
                        "user_id": user_id,
                        "error_type": type(marker_error).__name__,
                    },
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )
        log_event(
            "[CONVERSATION_METADATA] Failed to rebuild used documents after message mutation",
            extra={
                "conversation_id": conversation_id,
                "user_id": user_id,
                "error_type": type(rebuild_error).__name__,
            },
            level=logging.WARNING,
            exceptionTraceback=True,
        )
        return None


def _invalidate_conversation_cache_after_message_mutation(conversation_id, user_id, reason):
    """Invalidate conversation caches after message-level changes without failing the caller."""
    try:
        conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
    except Exception as exc:
        log_event(
            f"[CONVERSATION_CACHE] Failed to load conversation {conversation_id} for message mutation invalidation: {exc}",
            level=logging.WARNING,
            exceptionTraceback=True,
            debug_only=True,
        )
        bump_conversation_cache_version(user_id, reason=reason)
        return

    invalidate_conversation_cache_for_item(conversation_item, reason=reason)


def _authorize_image_conversation_read(user_id, conversation_id):
    """Authorize image reads for either personal or collaborative conversations."""
    try:
        return _authorize_personal_conversation_read(user_id, conversation_id), 'personal'
    except PermissionError:
        raise
    except LookupError:
        pass

    try:
        conversation_item = get_collaboration_conversation(conversation_id)
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    assert_user_can_view_collaboration_conversation(user_id, conversation_item, allow_pending=True)
    return conversation_item, 'collaboration'


def _stream_blob_backed_image_message(message_doc, cache_control='private, max-age=300'):
    """Stream a blob-backed image message through the authenticated image endpoint.

    ``message_doc`` only needs to carry the three blob fields, so a stored image revision --
    which uses the same key names deliberately -- can be streamed through here directly.
    """
    blob_container = str(message_doc.get('blob_container') or '').strip()
    blob_path = str(message_doc.get('blob_path') or '').strip()
    mime_type = str(message_doc.get('mime_type') or '').strip() or 'image/png'
    if not blob_container or not blob_path:
        raise LookupError('Image not found')

    blob_service_client = CLIENTS.get("storage_account_office_docs_client")
    if not blob_service_client:
        raise RuntimeError('Blob storage client not available')

    blob_client = blob_service_client.get_blob_client(
        container=blob_container,
        blob=blob_path,
    )

    content_length = None
    try:
        blob_properties = blob_client.get_blob_properties()
        content_length = getattr(blob_properties, 'size', None)
    except Exception:
        content_length = None

    def stream_blob_chunks():
        blob_stream = blob_client.download_blob()
        for blob_chunk in blob_stream.chunks():
            yield blob_chunk

    headers = {
        'Cache-Control': cache_control,
    }
    if content_length is not None:
        headers['Content-Length'] = str(content_length)

    return Response(
        stream_with_context(stream_blob_chunks()),
        mimetype=mime_type,
        headers=headers,
    )


def _load_scope_lock_conversation(conversation_id, user_id):
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
        # Orchestrate's backing record follows its shared conversation's lock; the lock itself
        # belongs to the shared conversation below.
        if not is_shared_conversation_backing(conversation_item):
            if conversation_item.get('user_id') != user_id:
                raise PermissionError('Forbidden')
            return conversation_item, 'personal'
    except CosmosResourceNotFoundError:
        pass

    try:
        conversation_item = get_collaboration_conversation(conversation_id)
    except CosmosResourceNotFoundError as exc:
        raise LookupError('Conversation not found') from exc

    assert_user_can_participate_in_collaboration_conversation(user_id, conversation_item)
    return conversation_item, 'collaboration'


def _persist_scope_lock_update(conversation_item, conversation_kind, user_id, new_value):
    timestamp = datetime.utcnow().isoformat()
    conversation_item['scope_locked'] = new_value

    if conversation_kind == 'collaboration':
        conversation_item['updated_at'] = timestamp
        cosmos_collaboration_conversations_container.upsert_item(conversation_item)
        current_user = get_current_user_info() or {'userId': user_id}
        _, conversation_item = ensure_collaboration_source_conversation(conversation_item, current_user)
        return conversation_item

    conversation_item['last_updated'] = timestamp
    cosmos_conversations_container.upsert_item(conversation_item)
    return conversation_item


def register_route_backend_conversations(bp):
    @bp.after_request
    def public_conversation_json_response(response):
        if response.is_json:
            response.set_data(current_app.json.dumps(strip_private_chat_checks(response.get_json())))
        return response


    @bp.route('/api/get_messages', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_messages():
        conversation_id = request.args.get('conversation_id')
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        if not conversation_id:
            return jsonify({'error': 'No conversation_id provided'}), 400
        try:
            _authorize_personal_conversation_read(user_id, conversation_id)
            # Query all messages in cosmos_messages_container
            # We'll filter for active_thread in Python since Cosmos DB boolean queries can be tricky
            message_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                ORDER BY c.timestamp ASC
            """
            
            debug_print(f"Executing query: {message_query}")
            
            all_items = list(cosmos_messages_container.query_items(
                query=message_query,
                partition_key=conversation_id
            ))
            all_items.sort(key=lambda item: (
                str(item.get('timestamp') or ''),
                int(item.get('fork_sequence')) if str(item.get('fork_sequence') or '').isdigit() else 0,
                str(item.get('id') or ''),
            ))
            all_items = order_retry_messages(all_items)
            # Deleted while archiving was enabled. They are masked too, but only as a
            # fail-safe: returned here, they would render as masked messages.
            all_items = exclude_soft_deleted_messages(all_items)
            artifact_payload_map = build_message_artifact_payload_map(all_items)
            all_items = filter_assistant_artifact_items(all_items)
            
            debug_print(f"Query returned {len(all_items)} total items (before filtering)")
            
            # Filter for active_thread = True OR active_thread is not defined (backwards compatibility)
            filtered_items = []
            for item in all_items:
                metadata = item.get('metadata', {}) or {}
                if metadata.get('is_generated_chat_artifact', False):
                    debug_print(f"  🫥 Excluding hidden generated artifact: id={item.get('id')}")
                    continue

                thread_info = metadata.get('thread_info', {})
                active = thread_info.get('active_thread')
                debug_print(f"Evaluating item id={item.get('id')}, role={item.get('role')}, active_thread={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
                
                # Include if: active_thread is True, OR active_thread is not defined, OR active_thread is None
                if active is True or active is None or 'active_thread' not in thread_info:
                    filtered_items.append(item)
                    debug_print(f"  ✅ Including: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
                else:
                    debug_print(f"  ❌ Excluding: id={item.get('id')}, role={item.get('role')}, active={active}, attempt={thread_info.get('thread_attempt', 'N/A')}")
            
            all_items = filtered_items
            debug_print(f"After filtering: {len(all_items)} items remaining")

            all_items = sanitize_saved_analysis_messages(all_items, user_id)
            all_items = hydrate_agent_citations_from_artifacts(all_items, artifact_payload_map)
            all_items = refresh_azure_maps_message_citations(all_items)
            try:
                all_items = public_history_messages(all_items, user_id)
            except (
                ScreeningError, OutputError, OutputStorageError, ResultContractError,
                ExternalIdentityServiceError, ExternalConfigurationServiceError,
                AzureError, TimeoutError, ConnectionError,
            ) as error:
                log_event(
                    '[ORCHESTRATION_RUNS] Current file history could not be verified.',
                    extra={'conversation_id': conversation_id, 'error_type': type(error).__name__},
                    level=logging.ERROR,
                )
                return jsonify({
                    'error': 'Current file status is unavailable.',
                    'code': 'output_status_unavailable',
                }), 503

            messages = hydrate_image_messages(
                all_items,
                image_url_builder=lambda image_id: f"/api/image/{image_id}",
            )

            try:
                messages = hydrate_m365_pending_action_cards(messages, user_id, conversation_id)
            except Exception as error:
                log_event(
                    "[CONVERSATION_METADATA] Microsoft 365 action cards could not be loaded.",
                    extra={"conversation_id": conversation_id, "exception_type": type(error).__name__},
                    level=logging.ERROR,
                )
                status_code = 403 if isinstance(error, (M365PolicyError, PermissionError)) else 503
                return jsonify({
                    "error": "m365_pending_actions_unavailable",
                    "message": "Microsoft 365 action cards could not be loaded. Reload the conversation to try again.",
                }), status_code

            return jsonify({'messages': messages})
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except LookupError:
            return jsonify({'messages': []})
        except Exception as e:
            print(f"ERROR: Failed to get messages: {str(e)}")
            return jsonify({'error': 'Conversation not found'}), 404

    @bp.route('/api/image/<image_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_image(image_id):
        """Serve chat images from blob storage or legacy chunked message content."""

        def preview_file_extension(mime_type):
            return {
                'image/png': 'png',
                'image/jpeg': 'jpg',
                'image/gif': 'gif',
                'image/webp': 'webp',
                'image/bmp': 'bmp',
                'image/heic': 'heic',
                'image/heif': 'heif',
            }.get(str(mime_type or '').split(';', 1)[0].strip().lower(), 'png')

        def inline_image_preview_response(image_bytes, preview_variant, *, file_name='image', cache_control='no-store, private'):
            converted = to_browser_image(image_bytes, preview_variant)
            safe_name = secure_filename(str(file_name or 'image').replace('\\', '/').rsplit('/', 1)[-1]) or 'image'
            stem = safe_name.rsplit('.', 1)[0] if '.' in safe_name else safe_name
            stem = secure_filename(stem) or 'image'
            extension = preview_file_extension(converted['mime_type'])
            content = converted['bytes']
            return Response(
                content,
                mimetype=converted['mime_type'],
                headers={
                    'Content-Length': str(len(content)),
                    'Cache-Control': cache_control,
                    'X-Content-Type-Options': 'nosniff',
                    'Content-Disposition': f'inline; filename="{stem}.{extension}"',
                },
            )

        def load_blob_backed_image_bytes(message_doc):
            blob_container = str(message_doc.get('blob_container') or '').strip()
            blob_path = str(message_doc.get('blob_path') or '').strip()
            if not blob_container or not blob_path:
                raise LookupError('Image not found')
            return load_image_bytes_from_blob(blob_container, blob_path)

        user_id = get_current_user_id()
        if not user_id:
            log_event(
                "[CHAT_IMAGE] Authenticated image request had no user id.",
                extra={"image_id": image_id},
                level=logging.WARNING,
            )
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            variant = request.args.get('variant')
            if variant is not None:
                variant = str(variant or '').strip().lower()
                if variant not in PREVIEW_VARIANTS:
                    return jsonify({
                        'error': 'The preview variant is not supported.',
                        'error_code': 'invalid_preview_variant',
                    }), 400

            # Extract conversation_id from image_id (format: conversation_id_image_timestamp_random)
            parts = image_id.split('_')
            if len(parts) < 4:
                return jsonify({'error': 'Invalid image ID format'}), 400

            # Reconstruct conversation_id (everything except the last 3 parts)
            conversation_id = '_'.join(parts[:-3])

            debug_print(f"Serving image {image_id} from conversation {conversation_id}")

            _authorize_image_conversation_read(user_id, conversation_id)
            image_message, complete_content = get_complete_image_content(
                cosmos_messages_container,
                conversation_id,
                image_id,
            )
            if image_message.get("workspace_document_id"):
                if not variant:
                    return build_available_document_response(
                        image_message["workspace_document_id"], user_id=user_id, purpose="image_preview",
                    )
                active_document, content = read_available_document_bytes(
                    image_message["workspace_document_id"], user_id=user_id, purpose="image_preview",
                )
                if not is_image_file_name(active_document.get('file_name')):
                    return jsonify({
                        'error': 'This file is not an image.',
                        'error_code': 'not_an_image',
                    }), 415
                return inline_image_preview_response(
                    content,
                    variant,
                    file_name=active_document.get('file_name') or image_message.get('filename') or image_id,
                    cache_control='no-store, private',
                )

            # An edited image is served from the revision's own blob. `rev` names which version
            # is wanted; it exists because this URL is otherwise identical before and after an
            # edit, and a browser holding a cached response would keep showing the version the
            # reader just replaced. Because the URL is addressed by revision, that response can
            # be cached hard rather than briefly.
            requested_revision = str(request.args.get('rev') or '').strip()
            served_revision = resolve_served_revision(image_message, requested_revision)
            if served_revision:
                cache_control = (
                    'private, max-age=31536000, immutable'
                    if requested_revision
                    else 'private, max-age=60'
                )
                if variant:
                    return inline_image_preview_response(
                        load_blob_backed_image_bytes(served_revision),
                        variant,
                        file_name=served_revision.get('file_name') or image_message.get('filename') or image_id,
                        cache_control=cache_control,
                    )
                return _stream_blob_backed_image_message(
                    served_revision,
                    cache_control=cache_control,
                )

            if is_blob_backed_image_message(image_message):
                if variant:
                    return inline_image_preview_response(
                        load_blob_backed_image_bytes(image_message),
                        variant,
                        file_name=image_message.get('filename') or image_id,
                        cache_control='private, max-age=300',
                    )
                return _stream_blob_backed_image_message(image_message)

            if is_external_image_url(complete_content):
                return redirect(complete_content)

            mime_type, image_data = decode_image_content(complete_content)
            if variant:
                return inline_image_preview_response(
                    image_data,
                    variant,
                    file_name=image_message.get('filename') or image_id,
                    cache_control='private, max-age=3600',
                )
            return Response(
                image_data,
                mimetype=mime_type,
                headers={
                    'Content-Length': len(image_data),
                    'Cache-Control': 'public, max-age=3600'
                }
            )

        except ImageFormatError as error:
            return jsonify({"error": error.public_message, "error_code": error.code}), error.status_code
        except ScreeningError as error:
            return jsonify({"error": error.public_message, "error_code": error.code}), error.status_code
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Image not found'}), 404
        except LookupError:
            return jsonify({'error': 'Image not found'}), 404
        except Exception as e:
            log_event(
                "[CHAT_IMAGE] Failed to serve image.",
                extra={"image_id": image_id, "exception_type": type(e).__name__},
                level=logging.ERROR,
            )
            return jsonify({'error': 'Failed to retrieve image'}), 500
        
    @bp.route('/api/get_conversations', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversations():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        settings = get_settings()
        cache_settings = get_conversation_cache_settings(settings)
        cache_key = None
        if cache_settings.get('enabled'):
            cache_key = build_conversation_cache_key(user_id, "list", parameters={"include_hidden": True})
            if cache_key:
                cached_payload = get_cached_conversation_payload(cache_key, settings=settings)
                if isinstance(cached_payload, dict) and isinstance(cached_payload.get('conversations'), list):
                    return jsonify(cached_payload), 200

        query = "SELECT * FROM c WHERE c.user_id = @user_id ORDER BY c.last_updated DESC"
        items = list(cosmos_conversations_container.query_items(
            query=query,
            parameters=[{'name': '@user_id', 'value': user_id}],
            enable_cross_partition_query=True,
        ))
        normalized_items = [normalize_conversation_unread_state(item) for item in items]
        payload = {
            'conversations': normalized_items
        }
        if cache_key:
            set_cached_conversation_payload(
                cache_key,
                payload,
                ttl_seconds=cache_settings.get('ttl_seconds'),
                settings=settings,
            )
        return jsonify(payload), 200


    @bp.route('/api/conversations/feed', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversations_feed():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            search_term = str(request.args.get('search') or '').strip()
            include_hidden = str(request.args.get('include_hidden', 'false')).strip().lower() in ('1', 'true', 'yes')
            page_size = normalize_conversation_feed_page_size(request.args.get('page_size'))
            cursor_data = decode_conversation_feed_cursor(request.args.get('cursor'))
            cursor_is_compatible = is_conversation_feed_cursor_compatible(
                cursor_data,
                search_term=search_term,
                include_hidden=include_hidden,
            )
            source_offsets = get_conversation_feed_source_offsets(cursor_data) if cursor_is_compatible else {}
            include_priority = not cursor_is_compatible

            settings = get_settings()
            cache_settings = get_conversation_cache_settings(settings)
            access_parameters = _build_conversation_cache_access_parameters(user_id)
            feed_cache_parameters = {
                "search_term": search_term,
                "include_hidden": include_hidden,
                "page_size": page_size,
                "cursor": request.args.get('cursor') or "",
                "include_priority": include_priority,
                "access": access_parameters,
            }
            feed_cache_key = None
            if cache_settings.get('enabled') and access_parameters is not None:
                feed_cache_key = build_conversation_cache_key(
                    user_id,
                    "feed",
                    parameters=feed_cache_parameters,
                )
                if feed_cache_key:
                    cached_feed_payload = get_cached_conversation_payload(feed_cache_key, settings=settings)
                    if isinstance(cached_feed_payload, dict) and isinstance(cached_feed_payload.get('conversations'), list):
                        return jsonify(cached_feed_payload), 200

            feed_payload = _build_conversation_feed(
                user_id=user_id,
                page_size=page_size,
                source_offsets=source_offsets,
                include_priority=include_priority,
                include_hidden=include_hidden,
                search_term=search_term,
            )
            feed_payload['search_term'] = search_term
            feed_payload['include_hidden'] = include_hidden
            if feed_cache_key:
                set_cached_conversation_payload(
                    feed_cache_key,
                    feed_payload,
                    ttl_seconds=cache_settings.get('ttl_seconds'),
                    settings=settings,
                )
            return jsonify(feed_payload), 200
        except Exception as exc:
            log_event(
                f'[CONVERSATION_FEED] Failed to load feed: {exc}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to load conversations'}), 500


    @bp.route('/api/create_conversation', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def create_conversation():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json(silent=True) or {}
        initial_title = derive_conversation_title_from_message(
            data.get('initial_message') or data.get('message') or data.get('title') or ''
        )
        conversation_item = create_personal_conversation_for_current_user(title=initial_title)
        bump_conversation_cache_version(user_id, reason="conversation_created")

        return jsonify({
            'conversation_id': conversation_item.get('id'),
            'title': conversation_item.get('title', 'New Conversation')
        }), 200


    @bp.route('/api/conversations/<conversation_id>/fork', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def fork_conversation(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        request_payload = request.get_json(silent=True) or {}
        selected_message_id = str(request_payload.get('message_id') or '').strip()
        if not selected_message_id:
            return jsonify({'error': 'A persisted assistant message is required'}), 400

        try:
            source_conversation = _authorize_personal_conversation_read(user_id, conversation_id)
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except LookupError:
            return jsonify({'error': 'The source conversation was not found'}), 404

        try:
            fork_result = fork_personal_conversation_for_user(
                source_conversation=source_conversation,
                selected_message_id=selected_message_id,
                user_id=user_id,
            )
            fork_conversation = fork_result['conversation']
            try:
                bump_conversation_cache_version(user_id, reason="conversation_forked")
            except Exception as cache_error:
                log_event(
                    f'[CONVERSATION_FORK] Fork created but cache invalidation failed: {cache_error}',
                    level=logging.WARNING,
                    extra={
                        'fork_conversation_id': fork_conversation['id'],
                        'user_id': user_id,
                    },
                )
            return jsonify({
                'conversation_id': fork_conversation['id'],
                'title': fork_conversation['title'],
                'message_count': fork_result['message_count'],
            }), 201
        except LookupError:
            return jsonify({'error': 'The selected assistant message was not found'}), 404
        except ValueError as validation_error:
            log_event(
                f'[CONVERSATION_FORK] Validation failed while creating conversation fork: {validation_error}',
                level=logging.WARNING,
                exceptionTraceback=True,
                extra={
                    'source_conversation_id': conversation_id,
                    'selected_message_id': selected_message_id,
                    'user_id': user_id,
                },
            )
            return jsonify({'error': 'Invalid request'}), 400
        except ConversationForkConflictError as conflict_error:
            log_event(
                f'[CONVERSATION_FORK] Conflict while creating conversation fork: {conflict_error}',
                level=logging.WARNING,
                extra={
                    'source_conversation_id': conversation_id,
                    'selected_message_id': selected_message_id,
                    'user_id': user_id,
                },
            )
            return jsonify({'error': 'Conversation fork conflict'}), 409
        except Exception as error:
            log_event(
                f'[CONVERSATION_FORK] Failed to create conversation fork: {error}',
                level=logging.ERROR,
                exceptionTraceback=True,
                extra={
                    'source_conversation_id': conversation_id,
                    'selected_message_id': selected_message_id,
                    'user_id': user_id,
                },
            )
            return jsonify({'error': 'Failed to fork conversation'}), 500


    @bp.route('/api/conversations/<conversation_id>', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def update_conversation_title(conversation_id):
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        # Parse the new title from the request body
        data = request.get_json()
        new_title = data.get('title', '').strip()
        if not new_title:
            return jsonify({'error': 'Title is required'}), 400

        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )

            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403

            # Update the title
            conversation_item['title'] = new_title

            # Optionally update the last_updated time
            from datetime import datetime
            conversation_item['last_updated'] = datetime.utcnow().isoformat()

            # Write back to Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)
            bump_conversation_cache_version(user_id, reason="conversation_title_updated")

            return jsonify({
                'message': 'Conversation updated', 
                'title': new_title,
                'classification': conversation_item.get('classification', []),
                'context': conversation_item.get('context', []),
                'chat_type': conversation_item.get('chat_type')
            }), 200
        except Exception as e:
            print(e)
            return jsonify({'error': 'Failed to update conversation'}), 500
        
    @bp.route('/api/conversations/<conversation_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_conversation(conversation_id):
        """
        Delete a conversation. If archiving is enabled, copy it to archived_conversations first.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        settings = get_settings()
        archiving_enabled = settings.get('enable_conversation_archiving', False)

        try:
            request_payload = request.get_json(silent=True) or {}
            delete_workspace_document_ids = _get_requested_workspace_document_delete_ids_for_conversation(
                request_payload,
                conversation_id,
            )
        except ValueError as validation_error:
            return jsonify({'error': str(validation_error)}), 400

        try:
            conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
        except LookupError:
            return jsonify({
                "error": f"Conversation {conversation_id} not found."
            }), 404
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except Exception as error:
            payload, status_code = _conversation_delete_failure(
                error, conversation_id, stage='authorization',
            )
            return jsonify(payload), status_code

        try:
            cancel_m365_conversation_deliveries(conversation_id)
        except Exception as error:
            payload, status_code = _conversation_delete_failure(
                error, conversation_id, stage='m365_cancellation',
            )
            return jsonify(payload), status_code

        try:
            cleanup_conversation_checkpoints(
                conversation_id, user_id,
                lambda: _authorize_personal_conversation_read(user_id, conversation_id),
                message_container=cosmos_messages_container,
                conversation_container=cosmos_conversations_container,
                output_cleanup=partial(_enroll_retained_orchestration_outputs, user_id, conversation_id),
                retain_committed=archiving_enabled,
            )
        except Exception as error:
            payload, status_code = _conversation_delete_failure(
                error, conversation_id, stage='orchestration_cleanup',
            )
            return jsonify(payload), status_code

        if archiving_enabled:
            archived_item = dict(conversation_item)
            archived_item["archived_at"] = datetime.utcnow().isoformat()
            cosmos_archived_conversations_container.upsert_item(archived_item)
            
            # Log conversation archival
            log_conversation_archival(
                user_id=conversation_item.get('user_id'),
                conversation_id=conversation_id,
                title=conversation_item.get('title', 'Untitled'),
                workspace_type='personal',
                context=conversation_item.get('context', []),
                tags=conversation_item.get('tags', [])
            )

        message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}'"
        try:
            results = list(cosmos_messages_container.query_items(
                query=message_query,
                partition_key=conversation_id
            ))
            cleanup_chat_analysis_conversation(conversation_id, conversation_item.get('user_id'), results)
        except Exception as error:
            payload, status_code = _conversation_delete_failure(
                error, conversation_id, stage='chat_analysis_cleanup',
            )
            return jsonify(payload), status_code
        direct_messages = [message for message in results if not _is_retained_orchestration_file(message)]
        direct_message_ids = {message['id'] for message in direct_messages}

        if delete_workspace_document_ids:
            try:
                workspace_delete_result = delete_chat_upload_workspace_documents_for_conversation(
                    conversation_item.get('user_id'),
                    conversation_id,
                    selected_document_ids=delete_workspace_document_ids,
                )
                if workspace_delete_result.get('deleted_document_ids'):
                    invalidate_personal_search_cache(conversation_item.get('user_id'))
                if workspace_delete_result.get('failed_documents'):
                    log_event(
                        f"[CONVERSATION_DELETE] Failed to delete some selected linked workspace documents for {conversation_id}",
                        workspace_delete_result,
                        level=logging.WARNING,
                    )
            except Exception as workspace_delete_error:
                log_event(
                    f"[CONVERSATION_DELETE] Failed to delete selected linked workspace documents for {conversation_id}: {workspace_delete_error}",
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )
                return jsonify({
                    'error': 'Failed to delete selected workspace documents'
                }), 500

        if not archiving_enabled:
            delete_blob_backed_chat_message_files(direct_messages, conversation=conversation_item)

        for doc in results:
            if archiving_enabled:
                archived_doc = dict(doc)
                archived_doc["archived_at"] = datetime.utcnow().isoformat()
                cosmos_archived_messages_container.upsert_item(archived_doc)

            if doc['id'] in direct_message_ids:
                cosmos_messages_container.delete_item(doc['id'], partition_key=conversation_id)

        # Archive/delete thoughts for conversation
        user_id_for_thoughts = conversation_item.get('user_id')
        if archiving_enabled:
            archive_thoughts_for_conversation(conversation_id, user_id_for_thoughts)
        else:
            delete_thoughts_for_conversation(conversation_id, user_id_for_thoughts)

        # Log conversation deletion before actual deletion
        log_conversation_deletion(
            user_id=conversation_item.get('user_id'),
            conversation_id=conversation_id,
            title=conversation_item.get('title', 'Untitled'),
            workspace_type='personal',
            context=conversation_item.get('context', []),
            tags=conversation_item.get('tags', []),
            is_archived=archiving_enabled,
            is_bulk_operation=False
        )
        
        try:
            cosmos_conversations_container.delete_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            bump_conversation_cache_version(user_id, reason="conversation_deleted")
            # TODO: Delete any facts that were stored with this conversation.
        except Exception as error:
            payload, status_code = _conversation_delete_failure(
                error, conversation_id, stage='conversation_delete',
            )
            return jsonify(payload), status_code

        return jsonify({
            "success": True
        }), 200
        
    @bp.route('/api/delete_multiple_conversations', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_multiple_conversations():
        """
        Delete multiple conversations at once. If archiving is enabled, copy them to archived_conversations first.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
            
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
            
        settings = get_settings()
        archiving_enabled = settings.get('enable_conversation_archiving', False)
        
        success_count = 0
        failed_ids = []
        failures = []
        
        for conversation_id in conversation_ids:
            stage = 'authorization'
            try:
                # Verify the conversation exists and belongs to the user
                try:
                    conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
                except (LookupError, PermissionError):
                    failed_ids.append(conversation_id)
                    failures.append({
                        'conversation_id': conversation_id,
                        'error': 'Conversation not found or access denied.',
                        'code': 'conversation_unavailable',
                        'status_code': 404,
                    })
                    continue

                stage = 'm365_cancellation'
                cancel_m365_conversation_deliveries(conversation_id)
                stage = 'orchestration_cleanup'
                cleanup_conversation_checkpoints(
                    conversation_id, user_id,
                    lambda: _authorize_personal_conversation_read(user_id, conversation_id),
                    message_container=cosmos_messages_container,
                    conversation_container=cosmos_conversations_container,
                    output_cleanup=partial(_enroll_retained_orchestration_outputs, user_id, conversation_id),
                    retain_committed=archiving_enabled,
                )
                
                # Archive if enabled
                stage = 'conversation_archive'
                if archiving_enabled:
                    archived_item = dict(conversation_item)
                    archived_item["archived_at"] = datetime.utcnow().isoformat()
                    cosmos_archived_conversations_container.upsert_item(archived_item)
                    
                    # Log conversation archival
                    log_conversation_archival(
                        user_id=user_id,
                        conversation_id=conversation_id,
                        title=conversation_item.get('title', 'Untitled'),
                        workspace_type='personal',
                        context=conversation_item.get('context', []),
                        tags=conversation_item.get('tags', [])
                    )
                
                # Get and archive messages if enabled
                stage = 'chat_analysis_cleanup'
                message_query = f"SELECT * FROM c WHERE c.conversation_id = '{conversation_id}'"
                messages = list(cosmos_messages_container.query_items(
                    query=message_query,
                    partition_key=conversation_id
                ))
                cleanup_chat_analysis_conversation(conversation_id, user_id, messages)
                direct_messages = [
                    message for message in messages if not _is_retained_orchestration_file(message)
                ]
                direct_message_ids = {message['id'] for message in direct_messages}

                stage = 'message_cleanup'
                if not archiving_enabled:
                    delete_blob_backed_chat_message_files(direct_messages, conversation=conversation_item)
                
                for message in messages:
                    if archiving_enabled:
                        archived_message = dict(message)
                        archived_message["archived_at"] = datetime.utcnow().isoformat()
                        cosmos_archived_messages_container.upsert_item(archived_message)
                    
                    if message['id'] in direct_message_ids:
                        cosmos_messages_container.delete_item(message['id'], partition_key=conversation_id)

                # Archive/delete thoughts for conversation
                stage = 'thoughts_cleanup'
                if archiving_enabled:
                    archive_thoughts_for_conversation(conversation_id, user_id)
                else:
                    delete_thoughts_for_conversation(conversation_id, user_id)

                # Log conversation deletion before actual deletion
                log_conversation_deletion(
                    user_id=user_id,
                    conversation_id=conversation_id,
                    title=conversation_item.get('title', 'Untitled'),
                    workspace_type='personal',
                    context=conversation_item.get('context', []),
                    tags=conversation_item.get('tags', []),
                    is_archived=archiving_enabled,
                    is_bulk_operation=True
                )
                
                # Delete the conversation
                stage = 'conversation_delete'
                cosmos_conversations_container.delete_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                success_count += 1
                
            except Exception as error:
                payload, status_code = _conversation_delete_failure(
                    error, conversation_id, stage=stage, is_bulk=True,
                )
                failed_ids.append(conversation_id)
                failures.append({
                    'conversation_id': conversation_id,
                    **payload,
                    'status_code': status_code,
                })

        if success_count:
            bump_conversation_cache_version(user_id, reason="conversations_bulk_deleted")

        return jsonify({
            "success": True,
            "deleted_count": success_count,
            "failed_ids": failed_ids,
            "failures": failures,
        }), 200

    @bp.route('/api/conversations/<conversation_id>/pin', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_conversation_pin(conversation_id):
        """
        Toggle the pinned status of a conversation.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            # Toggle the pinned status
            current_pinned = conversation_item.get('is_pinned', False)
            conversation_item['is_pinned'] = not current_pinned
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Update in Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)
            bump_conversation_cache_version(user_id, reason="conversation_pin_toggled")
            
            return jsonify({
                'success': True,
                'is_pinned': conversation_item['is_pinned']
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error toggling conversation pin: {e}")
            return jsonify({'error': 'Failed to toggle pin status'}), 500
    
    @bp.route('/api/conversations/<conversation_id>/hide', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def toggle_conversation_hide(conversation_id):
        """
        Toggle the hidden status of a conversation.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403
            
            # Toggle the hidden status
            current_hidden = conversation_item.get('is_hidden', False)
            conversation_item['is_hidden'] = not current_hidden
            conversation_item['last_updated'] = datetime.utcnow().isoformat()
            
            # Update in Cosmos DB
            cosmos_conversations_container.upsert_item(conversation_item)
            bump_conversation_cache_version(user_id, reason="conversation_hide_toggled")
            
            return jsonify({
                'success': True,
                'is_hidden': conversation_item['is_hidden']
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error toggling conversation hide: {e}")
            return jsonify({'error': 'Failed to toggle hide status'}), 500

    @bp.route('/api/conversations/bulk-pin', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def bulk_pin_conversations():
        """
        Pin or unpin multiple conversations at once.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        pin_action = data.get('action', 'pin')  # 'pin' or 'unpin'
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
        
        if pin_action not in ['pin', 'unpin']:
            return jsonify({'error': 'Invalid action. Must be "pin" or "unpin"'}), 400
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                # Check if the conversation belongs to the current user
                if conversation_item.get('user_id') != user_id:
                    failed_ids.append(conversation_id)
                    continue
                
                # Set pin status
                conversation_item['is_pinned'] = (pin_action == 'pin')
                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                
                # Update in Cosmos DB
                cosmos_conversations_container.upsert_item(conversation_item)
                success_count += 1
                
            except CosmosResourceNotFoundError:
                failed_ids.append(conversation_id)
            except Exception as e:
                print(f"Error updating conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)

        if success_count:
            bump_conversation_cache_version(user_id, reason="conversations_bulk_pin_updated")

        return jsonify({
            "success": True,
            "updated_count": success_count,
            "failed_ids": failed_ids,
            "action": pin_action
        }), 200

    @bp.route('/api/conversations/bulk-hide', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def bulk_hide_conversations():
        """
        Hide or unhide multiple conversations at once.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        data = request.get_json()
        conversation_ids = data.get('conversation_ids', [])
        hide_action = data.get('action', 'hide')  # 'hide' or 'unhide'
        
        if not conversation_ids:
            return jsonify({'error': 'No conversation IDs provided'}), 400
        
        if hide_action not in ['hide', 'unhide']:
            return jsonify({'error': 'Invalid action. Must be "hide" or "unhide"'}), 400
        
        success_count = 0
        failed_ids = []
        
        for conversation_id in conversation_ids:
            try:
                conversation_item = cosmos_conversations_container.read_item(
                    item=conversation_id,
                    partition_key=conversation_id
                )
                
                # Check if the conversation belongs to the current user
                if conversation_item.get('user_id') != user_id:
                    failed_ids.append(conversation_id)
                    continue
                
                # Set hide status
                conversation_item['is_hidden'] = (hide_action == 'hide')
                conversation_item['last_updated'] = datetime.utcnow().isoformat()
                
                # Update in Cosmos DB
                cosmos_conversations_container.upsert_item(conversation_item)
                success_count += 1
                
            except CosmosResourceNotFoundError:
                failed_ids.append(conversation_id)
            except Exception as e:
                print(f"Error updating conversation {conversation_id}: {str(e)}")
                failed_ids.append(conversation_id)

        if success_count:
            bump_conversation_cache_version(user_id, reason="conversations_bulk_hide_updated")

        return jsonify({
            "success": True,
            "updated_count": success_count,
            "failed_ids": failed_ids,
            "action": hide_action
        }), 200

    @bp.route('/api/conversations/<conversation_id>/metadata', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversation_metadata_api(conversation_id):
        """
        Get detailed metadata for a conversation including context, tags, and other information.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Retrieve the conversation
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            conversation_item = normalize_conversation_unread_state(conversation_item)
            
            # Ensure that the conversation belongs to the current user
            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403

            if conversation_item.get('used_documents_rebuild_required') is True:
                rebuilt_conversation = (
                    _rebuild_authorized_personal_conversation_used_documents(
                        user_id,
                        conversation_id,
                    )
                )
                if rebuilt_conversation:
                    conversation_item = rebuilt_conversation
            
            _, updated = normalize_chat_type(conversation_item)
            if updated:
                cosmos_conversations_container.upsert_item(conversation_item)
                invalidate_conversation_cache_for_item(conversation_item, reason="conversation_chat_type_normalized")

            linked_workspace_documents = []
            try:
                linked_workspace_documents = serialize_chat_upload_workspace_documents_for_conversation(
                    user_id,
                    conversation_id,
                )
            except Exception as linked_documents_error:
                log_event(
                    f"[CONVERSATION_METADATA] Failed to list linked workspace documents for {conversation_id}: {linked_documents_error}",
                    level=logging.WARNING,
                    exceptionTraceback=True,
                )

            # Return the full conversation metadata
            return jsonify({
                "conversation_id": conversation_id,
                "title": conversation_item.get('title', ''),
                "user_id": conversation_item.get('user_id', ''),
                "last_updated": conversation_item.get('last_updated', ''),
                "classification": conversation_item.get('classification', []),
                "context": conversation_item.get('context', []),
                "tags": conversation_item.get('tags', []),
                "used_documents_tracking_version": conversation_item.get('used_documents_tracking_version'),
                "legacy_used_documents": conversation_item.get('legacy_used_documents', []),
                "used_documents": conversation_item.get('used_documents', []),
                "strict": conversation_item.get('strict', False),
                "is_pinned": conversation_item.get('is_pinned', False),
                "is_hidden": conversation_item.get('is_hidden', False),
                "has_unread_assistant_response": conversation_item.get('has_unread_assistant_response', False),
                "last_unread_assistant_message_id": conversation_item.get('last_unread_assistant_message_id'),
                "last_unread_assistant_at": conversation_item.get('last_unread_assistant_at'),
                "scope_locked": conversation_item.get('scope_locked'),
                "locked_contexts": conversation_item.get('locked_contexts', []),
                "chat_type": conversation_item.get('chat_type'),
                "workflow_id": conversation_item.get('workflow_id'),
                "summary": conversation_item.get('summary'),
                "linked_workspace_documents": linked_workspace_documents,
                # Only the signed-in owner's own Microsoft 365 items are listed.
                "used_m365_items": used_m365_items_for_viewer(
                    conversation_item.get('used_m365_items'), user_id,
                ),
            }), 200
            
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            print(f"Error retrieving conversation metadata: {e}")
            return jsonify({'error': 'Failed to retrieve conversation metadata'}), 500

    @bp.route('/api/conversations/<conversation_id>/generated-documents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def list_personal_conversation_generated_documents_api(conversation_id):
        """List the documents agents created in this conversation, and which the reader may download.

        The personal counterpart of the shared conversation list: the same documents, read from the
        SimpleChat upload actions' results, under the same workspace download rules.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
            settings = get_settings()
            documents = [
                {
                    'document_id': document['document_id'],
                    'file_name': document['file_name'],
                    'workspace_scope': document['workspace_scope'],
                    'preview': document['preview'],
                    'message_id': document['message_id'],
                    'created_at': document['created_at'],
                    'can_download': can_download_generated_document(user_id, document, settings=settings),
                }
                for document in _list_personal_conversation_generated_documents(conversation_item)
            ]
            return jsonify({'documents': documents}), 200
        except LookupError:
            return jsonify({'error': 'Conversation not found'}), 404
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except Exception as exc:
            log_event(
                '[CONVERSATION_GENERATED_DOCUMENTS] Failed to list generated documents.',
                extra={'conversation_id': conversation_id, 'exception_type': type(exc).__name__},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to list generated documents'}), 500

    @bp.route(
        '/api/conversations/<conversation_id>/generated-documents/<document_id>/download',
        methods=['GET'],
    )
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def download_personal_conversation_generated_document_api(conversation_id, document_id):
        """Download a document an agent created in this conversation, under its workspace's rules."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
        except LookupError:
            return jsonify({'error': 'Conversation not found'}), 404
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403

        try:
            # Only a document this conversation produced can be fetched through it.
            document = next(
                (
                    candidate
                    for candidate in _list_personal_conversation_generated_documents(conversation_item)
                    if candidate['document_id'] == document_id
                ),
                None,
            )
            if not document:
                return jsonify({'error': 'Document not found'}), 404
            try:
                document_record, group_id = authorize_generated_document_download(user_id, document)
            except LookupError:
                return jsonify({'error': 'Document not found or access denied'}), 404
            return build_document_download_response(
                document_record,
                user_id=user_id,
                group_id=group_id,
            )
        except FileNotFoundError:
            return jsonify({'error': 'This document is not available yet.'}), 404
        except PermissionError:
            return jsonify({'error': 'You do not have permission to download this document'}), 403
        except ScreeningError as error:
            return jsonify({'error': error.public_message, 'error_code': error.code}), error.status_code
        except Exception as exc:
            log_event(
                '[CONVERSATION_GENERATED_DOCUMENTS] Failed to download a generated document.',
                extra={'conversation_id': conversation_id, 'exception_type': type(exc).__name__},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Unable to download document'}), 500

    @bp.route('/api/conversations/<conversation_id>/kind', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_conversation_kind_api(conversation_id):
        """Report whether a conversation is a personal or a shared one, and prove it exists.

        A conversation reached from a link is not in the loaded rail, so the client has nothing
        to tell it which family of endpoints the conversation belongs to. It used to work this
        out by calling the personal metadata endpoint and reading a 404 as "then it must be a
        shared one", which was correct but made the browser log a failed request every time
        somebody opened a link to a shared conversation.

        Existence is part of the answer rather than a separate question. Neither message endpoint
        can be used as an existence check — both answer 200 with an empty list for a conversation
        that is not there — so without this a deleted conversation would open as an empty chat
        and keep its id in the address bar.

        A conversation the caller may not see is reported as absent rather than forbidden. The
        two are indistinguishable to someone who should not know it exists, and the client treats
        them identically.

        A personal record stored under a shared conversation's id is part of that shared
        conversation: Orchestrate's backing record (0.261.270), or a private copy an earlier
        version made there. The shared conversation is reported for anyone who can see it, so
        reopening it never turns it into a personal chat. A private copy stays reachable as
        personal only for an owner who can no longer see the shared conversation.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        personal_response = ({'conversation_id': conversation_id, 'kind': 'personal'}, 200)
        not_found_response = ({'error': 'Conversation not found'}, 404)

        try:
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id,
            )
        except CosmosResourceNotFoundError:
            conversation_item = None
        except Exception as e:
            log_event(
                f"[CONVERSATION_KIND] Failed to read personal conversation {conversation_id}: {e}",
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to resolve conversation'}), 500
        owns_personal = bool(
            conversation_item
            and conversation_item.get('user_id') == user_id
            and not is_shared_conversation_backing(conversation_item)
        )

        def personal_or(response, status):
            if owns_personal:
                return jsonify(personal_response[0]), personal_response[1]
            return jsonify(response), status

        # Checked before answering "collaborative": with the feature off, the collaboration
        # endpoints refuse everything, so naming a conversation as shared would only send the
        # client somewhere it cannot go.
        settings = get_settings() or {}
        if not settings.get('enable_collaborative_conversations', False):
            return personal_or(*not_found_response)

        try:
            collaboration_item = get_collaboration_conversation(conversation_id)
            access_context = assert_user_can_view_collaboration_conversation(
                user_id,
                collaboration_item,
                allow_pending=True,
            )
        except CosmosResourceNotFoundError:
            return personal_or(*not_found_response)
        except LookupError:
            # Raised when the stored document is not a collaboration conversation, which for a
            # question about kind is the same answer as it not being there.
            return personal_or(*not_found_response)
        except PermissionError:
            return personal_or(*not_found_response)
        except Exception as e:
            log_event(
                f"[CONVERSATION_KIND] Failed to resolve shared conversation {conversation_id}: {e}",
                level=logging.WARNING,
                exceptionTraceback=True,
            )
            # A personal conversation still opens while shared conversations can't be read.
            return personal_or({'error': 'Failed to resolve conversation'}, 500)

        # Returned alongside the kind because the caller needs this exact document next, and
        # asking for it twice is the cost the old probe was paying to avoid.
        return jsonify({
            'conversation_id': conversation_id,
            'kind': 'collaborative',
            'conversation': serialize_collaboration_conversation(
                collaboration_item,
                current_user_id=user_id,
                user_state=access_context.get('user_state'),
            ),
        }), 200

    @bp.route('/api/conversations/<conversation_id>/mark-read', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def mark_conversation_read_api(conversation_id):
        """Clear unread assistant-response state and related chat notifications."""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        try:
            conversation_item = cosmos_conversations_container.read_item(
                item=conversation_id,
                partition_key=conversation_id
            )
            conversation_item = normalize_conversation_unread_state(conversation_item)

            if conversation_item.get('user_id') != user_id:
                return jsonify({'error': 'Forbidden'}), 403

            conversation_state_changed = (
                conversation_item.get('has_unread_assistant_response') is True
                or conversation_item.get('last_unread_assistant_message_id') is not None
                or conversation_item.get('last_unread_assistant_at') is not None
            )
            if conversation_state_changed:
                conversation_item = clear_conversation_unread(conversation_item)
                cosmos_conversations_container.upsert_item(conversation_item)
                bump_conversation_cache_version(user_id, reason="conversation_marked_read")

            notifications_marked_read = mark_chat_response_notifications_read_for_conversation(
                user_id,
                conversation_id
            )

            return jsonify({
                'success': True,
                'conversation_id': conversation_id,
                'has_unread_assistant_response': False,
                'notifications_marked_read': notifications_marked_read,
                'conversation_state_changed': conversation_state_changed,
            }), 200
        except CosmosResourceNotFoundError:
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            debug_print(f"Error marking conversation {conversation_id} as read: {e}")
            return jsonify({'error': 'Failed to mark conversation as read'}), 500

    @bp.route('/api/conversations/<conversation_id>/summary', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def generate_conversation_summary_api(conversation_id):
        """
        Generate (or regenerate) a summary for a conversation and persist it.

        Request body (optional):
            { "model_deployment": "gpt-4o" }

        Returns the generated summary dict on success.
        """
        from route_backend_conversation_export import generate_conversation_summary, _normalize_content
        from functions_chat import sort_messages_by_thread

        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        conversation_item = None
        is_collaboration_summary = False

        try:
            conversation_item = _authorize_personal_conversation_read(user_id, conversation_id)
        except LookupError:
            # Orchestrate's backing record shares its shared conversation's id; the summary is
            # the shared conversation's.
            try:
                conversation_item = get_collaboration_conversation(conversation_id)
                assert_user_can_view_collaboration_conversation(
                    user_id,
                    conversation_item,
                    allow_pending=True,
                )
                is_collaboration_summary = True
            except CosmosResourceNotFoundError:
                return jsonify({'error': 'Conversation not found'}), 404
            except PermissionError as exc:
                return jsonify({'error': str(exc)}), 403
            except Exception as e:
                debug_print(f"Error reading collaborative conversation for summary: {e}")
                return jsonify({'error': 'Failed to read conversation'}), 500
        except PermissionError:
            return jsonify({'error': 'Forbidden'}), 403
        except Exception as e:
            debug_print(f"Error reading conversation for summary: {e}")
            return jsonify({'error': 'Failed to read conversation'}), 500

        body = request.get_json(silent=True) or {}
        model_deployment = body.get('model_deployment', '')
        model_endpoint_id = body.get('model_endpoint_id', '')
        model_id = body.get('model_id', '')
        model_provider = body.get('model_provider', '')

        # Query messages for this conversation
        try:
            if is_collaboration_summary:
                raw_messages = list_collaboration_messages(conversation_id)
            else:
                query = "SELECT * FROM c WHERE c.conversation_id = @cid ORDER BY c.timestamp ASC"
                params = [{"name": "@cid", "value": conversation_id}]
                raw_messages = list(cosmos_messages_container.query_items(
                    query=query,
                    parameters=params,
                    enable_cross_partition_query=True
                ))
            raw_messages = filter_assistant_artifact_items(raw_messages)
            raw_messages = exclude_soft_deleted_messages(raw_messages)
        except Exception as e:
            debug_print(f"Error querying messages for summary: {e}")
            return jsonify({'error': 'Failed to query messages'}), 500

        if not raw_messages:
            return jsonify({'error': 'No messages in this conversation'}), 400

        # Build lightweight export-style message list for the summary helper
        ordered_messages = sort_messages_by_thread(raw_messages)
        export_messages = []
        for msg in ordered_messages:
            role = msg.get('role', 'unknown')
            # Content may be a string OR a list of content parts — normalise it
            content = _normalize_content(msg.get('content', ''))
            speaker = 'USER' if role == 'user' else 'ASSISTANT' if role == 'assistant' else role.upper()
            export_messages.append({
                'role': role,
                'content_text': content,
                'speaker_label': speaker
            })

        message_time_start = ordered_messages[0].get('timestamp') if ordered_messages else None
        message_time_end = ordered_messages[-1].get('timestamp') if ordered_messages else None

        settings = get_settings()

        try:
            summary_data = generate_conversation_summary(
                messages=export_messages,
                conversation_title=conversation_item.get('title', 'Untitled'),
                settings=settings,
                model_deployment=model_deployment,
                message_time_start=message_time_start,
                message_time_end=message_time_end,
                conversation_id=conversation_id,
                user_id=user_id,
                model_endpoint_id=model_endpoint_id,
                model_id=model_id,
                model_provider=model_provider,
            )
            return jsonify({'success': True, 'summary': summary_data}), 200

        except (ValueError, RuntimeError) as known_exc:
            return jsonify({'error': str(known_exc)}), 400
        except Exception as exc:
            debug_print(f"Summary generation API error: {exc}")
            return jsonify({'error': 'Summary generation failed'}), 500

    @bp.route('/api/conversations/<conversation_id>/scope_lock', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def patch_conversation_scope_lock(conversation_id):
        """
        Toggle the scope lock on a conversation.
        Unlock is reversible — locked_contexts are preserved for re-locking.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        data = request.get_json()
        if data is None or 'scope_locked' not in data:
            return jsonify({'error': 'Missing scope_locked field'}), 400

        new_value = data['scope_locked']
        if new_value is not True and new_value is not False:
            return jsonify({'error': 'scope_locked must be true or false'}), 400

        # Enforce scope lock if admin setting is enabled
        if new_value is False:
            settings = get_settings()
            if settings.get('enforce_workspace_scope_lock', True):
                return jsonify({'error': 'Scope unlock is disabled by administrator'}), 403

        try:
            conversation_item, conversation_kind = _load_scope_lock_conversation(conversation_id, user_id)
            conversation_item = _persist_scope_lock_update(
                conversation_item,
                conversation_kind,
                user_id,
                new_value,
            )
            invalidate_conversation_cache_for_item(conversation_item, reason="conversation_scope_lock_updated")

            return jsonify({
                "success": True,
                "scope_locked": new_value,
                "locked_contexts": conversation_item.get('locked_contexts', [])
            }), 200
        except PermissionError as exc:
            return jsonify({'error': str(exc) or 'Forbidden'}), 403
        except (CosmosResourceNotFoundError, LookupError):
            return jsonify({'error': 'Conversation not found'}), 404
        except Exception as e:
            debug_print(f"Error updating scope lock: {e}")
            return jsonify({'error': 'Failed to update scope lock'}), 500

    @bp.route('/api/conversations/classifications', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_classifications():
        """
        Get all unique classifications from user's conversations
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            # Query all conversations for this user
            query = f"SELECT c.classification FROM c WHERE c.user_id = '{user_id}'"
            items = list(cosmos_conversations_container.query_items(
                query=query,
                enable_cross_partition_query=True
            ))
            
            # Extract and flatten all classifications
            classifications_set = set()
            for item in items:
                classifications = item.get('classification', [])
                if isinstance(classifications, list):
                    for classification in classifications:
                        if classification and isinstance(classification, str):
                            classifications_set.add(classification.strip())
            
            # Sort alphabetically
            classifications_list = sorted(list(classifications_set))
            
            return jsonify({
                'success': True,
                'classifications': classifications_list
            }), 200
            
        except Exception as e:
            print(f"Error fetching classifications: {e}")
            return jsonify({'error': 'Failed to fetch classifications'}), 500
    
    @bp.route('/api/search_conversations', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def search_conversations():
        """
        Search conversations and messages with filters and pagination
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json(silent=True) or {}
            search_term = data.get('search_term', '').strip()
            match_mode = _normalize_search_match_mode(data.get('match_mode'))
            date_from = data.get('date_from', '')
            date_to = data.get('date_to', '')
            chat_types = data.get('chat_types', [])
            classifications = data.get('classifications', [])
            has_files = data.get('has_files', False)
            has_images = data.get('has_images', False)
            page = int(data.get('page', 1))
            per_page = int(data.get('per_page', 20))
            
            # Validate search term
            if not search_term or len(search_term) < 3:
                return jsonify({
                    'success': False,
                    'error': 'Search term must be at least 3 characters'
                }), 400

            settings = get_settings()
            cache_settings = get_conversation_cache_settings(settings)
            access_parameters = _build_conversation_cache_access_parameters(user_id)
            search_cache_parameters = {
                'search_term': search_term,
                'match_mode': match_mode,
                'date_from': date_from,
                'date_to': date_to,
                'chat_types': sorted([str(item) for item in chat_types or []]),
                'classifications': sorted([str(item) for item in classifications or []]),
                'has_files': bool(has_files),
                'has_images': bool(has_images),
                'page': page,
                'per_page': per_page,
                'access': access_parameters,
                'analysis_result_policy_version': 1,
                # Results cached before soft-deleted messages were excluded must not be served.
                'soft_deleted_message_policy_version': 1,
            }
            search_cache_key = None
            if cache_settings.get('enabled') and access_parameters is not None:
                search_cache_key = build_conversation_cache_key(
                    user_id,
                    "search",
                    parameters=search_cache_parameters,
                )
                if search_cache_key:
                    cached_search_payload = get_cached_conversation_payload(search_cache_key, settings=settings)
                    if isinstance(cached_search_payload, dict) and cached_search_payload.get('success') is True:
                        return jsonify(cached_search_payload), 200
            
            selected_chat_types = _expand_search_chat_type_filters(chat_types)

            # Build conversation query with filters. Find conversations where user is a participant
            # and keep a Python-side pass for collaboration records that live in separate containers.
            query_parts = [
                "(c.user_id = @user_id OR EXISTS(SELECT VALUE t FROM t IN c.tags WHERE t.category = 'participant' AND t.user_id = @user_id))"
            ]
            query_parameters = [
                {'name': '@user_id', 'value': user_id},
            ]
            
            debug_print("🔍 Search parameters:")
            debug_print(f"  user_id: {user_id}")
            debug_print(f"  search_term: {search_term}")
            debug_print(f"  match_mode: {match_mode}")
            debug_print(f"  date_from: {date_from}")
            debug_print(f"  date_to: {date_to}")
            debug_print(f"  chat_types: {chat_types}")
            debug_print(f"  classifications: {classifications}")
            
            if date_from:
                query_parts.append("c.last_updated >= @date_from")
                query_parameters.append({'name': '@date_from', 'value': date_from})
            if date_to:
                query_parts.append("c.last_updated <= @date_to")
                query_parameters.append({'name': '@date_to', 'value': f'{date_to}T23:59:59'})
            
            conversation_query = f"SELECT * FROM c WHERE {' AND '.join(query_parts)}"
            debug_print(f"\n📋 Conversation query: {conversation_query}")
            
            conversations = list(cosmos_conversations_container.query_items(
                query=conversation_query,
                parameters=query_parameters,
                enable_cross_partition_query=True,
                max_item_count=-1  # Get all items, no pagination limit
            ))

            collaboration_conversations = _load_accessible_collaboration_search_conversations(user_id)
            collaboration_conversations = [
                conversation for conversation in collaboration_conversations
                if _conversation_matches_date_range(conversation, date_from, date_to)
            ]
            conversations.extend(collaboration_conversations)

            debug_print(f"Found {len(conversations)} conversations from legacy and collaboration stores")
            
            # Filter by chat types if specified
            if selected_chat_types:
                before_count = len(conversations)
                filtered_out = []
                filtered_in = []
                
                for conversation in conversations:
                    if _conversation_matches_selected_chat_types(conversation, selected_chat_types):
                        filtered_in.append(conversation)
                    else:
                        filtered_out.append(conversation)
                
                conversations = filtered_in
                debug_print(f"After chat_type filter: {len(conversations)} (removed {before_count - len(conversations)})")
                
                # Show some examples of filtered out chat types
                if filtered_out:
                    unique_types = set(_get_search_conversation_chat_type(c) for c in filtered_out[:10])
                    debug_print(f"   Filtered out chat_types (sample): {unique_types}")
            
            # Filter by classifications if specified
            if classifications:
                before_count = len(conversations)
                conversations = [
                    conversation for conversation in conversations
                    if _conversation_matches_classifications(conversation, classifications)
                ]
                debug_print(f"After classification filter: {len(conversations)} (removed {before_count - len(conversations)})")
            
            debug_print(f"🔍 Starting search for term: '{search_term}'")
            debug_print(f"Found {len(conversations)} conversations to search")
            
            # Create a set of conversation IDs for fast lookup
            conversation_ids = {conversation['id'] for conversation in conversations if conversation.get('id')}
            conversation_map = {
                conversation['id']: conversation
                for conversation in conversations
                if conversation.get('id')
            }
            
            # Do cross-partition message searches in both legacy and collaboration stores,
            # then filter to the user's authorized conversation set.
            message_query, _ = _build_message_search_query(search_term, match_mode)
            debug_print(f"\n📋 Cross-partition message query: {message_query}")

            all_matching_messages = _query_matching_messages(
                cosmos_messages_container,
                search_term,
                match_mode,
            )
            all_matching_messages.extend(_query_matching_messages(
                cosmos_collaboration_messages_container,
                search_term,
                match_mode,
            ))
            
            debug_print(f"Found {len(all_matching_messages)} total messages across all conversations")

            accessible_matches = [
                message for message in all_matching_messages
                if message.get('conversation_id') in conversation_ids
            ]
            if any(
                any((message.get('metadata') or {}).get(field) for field in (
                    'saved_analysis', 'saved_analyses', 'analysis_result_contexts',
                ))
                or message_uses_workflow_result(message)
                for message in accessible_matches
            ):
                # Source-bound snippets must recheck access rather than outlive it in a cache.
                search_cache_key = None
            all_matching_messages = [
                message for message in sanitize_saved_analysis_messages(accessible_matches, user_id)
                if not is_saved_analysis_unavailable(message)
            ]
            
            # Group messages by conversation and filter
            messages_by_conversation = {}
            for msg in all_matching_messages:
                conv_id = msg.get('conversation_id')
                
                # Only include messages from conversations we have access to
                if conv_id not in conversation_ids:
                    continue
                
                # Include all messages where active_thread is not explicitly False
                if _message_is_in_active_thread(msg):
                    messages_by_conversation.setdefault(conv_id, []).append(msg)
            
            debug_print(f"After filtering: {len(messages_by_conversation)} conversations have matching messages")
            
            results = []

            # Build results for conversations with matching titles or messages.
            for conv_id, conversation in conversation_map.items():
                matching_messages = messages_by_conversation.get(conv_id, [])
                title_match = _matches_search_text(conversation.get('title', ''), search_term, match_mode)
                
                # Apply file/image filters if specified
                if has_files or has_images:
                    matching_messages = [
                        message for message in matching_messages
                        if _message_matches_attachment_filters(message, has_files, has_images)
                    ]
                
                include_title_only_match = title_match and not (has_files or has_images)
                if not matching_messages and not include_title_only_match:
                    continue

                results.append({
                    'conversation': _build_search_conversation_payload(conversation),
                    'messages': _build_message_snippets(matching_messages, search_term, match_mode),
                    'match_count': len(matching_messages),
                    'title_match': title_match,
                    'match_mode': match_mode,
                })
            
            # Sort by last_updated (most recent first)
            results.sort(key=lambda x: x['conversation']['last_updated'], reverse=True)
            
            # Pagination
            total_results = len(results)
            total_pages = math.ceil(total_results / per_page) if total_results > 0 else 1
            start_idx = (page - 1) * per_page
            end_idx = start_idx + per_page
            paginated_results = results[start_idx:end_idx]
            
            payload = {
                'success': True,
                'total_results': total_results,
                'page': page,
                'total_pages': total_pages,
                'per_page': per_page,
                'results': paginated_results
            }
            if search_cache_key:
                set_cached_conversation_payload(
                    search_cache_key,
                    payload,
                    ttl_seconds=cache_settings.get('ttl_seconds'),
                    settings=settings,
                )
            return jsonify(payload), 200
            
        except Exception as e:
            log_event(
                f'[CONVERSATION_SEARCH] Failed to search conversations: {e}',
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to search conversations'}), 500
    
    @bp.route('/api/user-settings/search-history', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_search_history():
        """Get user's search history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            history = get_user_search_history(user_id)
            return jsonify({
                'success': True,
                'history': history
            }), 200
        except Exception as e:
            print(f"Error retrieving search history: {e}")
            return jsonify({'error': 'Failed to retrieve search history'}), 500
    
    @bp.route('/api/user-settings/search-history', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def save_search_to_history():
        """Save a search term to user's history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json()
            search_term = data.get('search_term', '').strip()
            
            if not search_term:
                return jsonify({'error': 'Search term is required'}), 400
            
            history = add_search_to_history(user_id, search_term)
            return jsonify({
                'success': True,
                'history': history
            }), 200
        except Exception as e:
            print(f"Error saving search to history: {e}")
            return jsonify({'error': 'Failed to save search to history'}), 500
    
    @bp.route('/api/user-settings/search-history', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def clear_search_history():
        """Clear user's search history"""
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            success = clear_user_search_history(user_id)
            if success:
                return jsonify({
                    'success': True,
                    'message': 'Search history cleared'
                }), 200
            else:
                return jsonify({'error': 'Failed to clear search history'}), 500
        except Exception as e:
            print(f"Error clearing search history: {e}")
            return jsonify({'error': 'Failed to clear search history'}), 500
    
    @bp.route('/api/message/<message_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def delete_message(message_id):
        """
        Delete a message or entire thread. Only the message author can delete their messages.
        If archiving is enabled, messages are marked with is_deleted=true and masked.
        If archiving is disabled, messages are permanently deleted.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            delete_thread = data.get('delete_thread', False)
            
            settings = get_settings()
            archiving_enabled = settings.get('enable_conversation_archiving', False)
            
            # Find the message using cross-partition query
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            message_doc = message_results[0]
            if is_soft_deleted_message(message_doc):
                return jsonify({'error': 'Message not found'}), 404
            conversation_id = message_doc.get('conversation_id')
            
            # Verify ownership - only the message author can delete their message
            message_user_id = message_doc.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                # Fallback: check conversation ownership for backwards compatibility
                # All messages in a conversation (user, assistant, system) belong to the conversation owner
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only delete messages from your own conversations'}), 403
                except Exception as ex:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only delete your own messages'}), 403
            
            # Collect messages to delete
            messages_to_delete = []
            
            if delete_thread and message_doc.get('role') == 'user':
                # Delete entire thread: user message + system message + assistant/image messages
                thread_id = message_doc.get('metadata', {}).get('thread_info', {}).get('thread_id')
                thread_previous_id = message_doc.get('metadata', {}).get('thread_info', {}).get('previous_thread_id')
                
                if thread_id:
                    # Query all messages in this thread exchange (user, system, assistant messages with same thread_id)
                    # Do NOT include subsequent threads that reference this thread_id as previous_thread_id
                    thread_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.thread_id = '{thread_id}'
                    """
                    thread_messages = list(cosmos_messages_container.query_items(
                        query=thread_query,
                        partition_key=conversation_id
                    ))
                    messages_to_delete = thread_messages
                    
                    # THREAD CHAIN REPAIR: Update subsequent threads to maintain chain integrity
                    # Find messages where previous_thread_id points to the thread we're deleting
                    subsequent_query = f"""
                        SELECT * FROM c 
                        WHERE c.conversation_id = '{conversation_id}' 
                        AND c.metadata.thread_info.previous_thread_id = '{thread_id}'
                    """
                    subsequent_messages = list(cosmos_messages_container.query_items(
                        query=subsequent_query,
                        partition_key=conversation_id
                    ))
                    
                    # Update each subsequent message to skip over the deleted thread
                    # Point their previous_thread_id to the deleted thread's previous_thread_id
                    for subsequent_msg in subsequent_messages:
                        # Skip messages that are being deleted (they're in the same thread)
                        if subsequent_msg['id'] in [m['id'] for m in messages_to_delete]:
                            continue
                        
                        # Update previous_thread_id to maintain chain
                        if 'metadata' not in subsequent_msg:
                            subsequent_msg['metadata'] = {}
                        if 'thread_info' not in subsequent_msg['metadata']:
                            subsequent_msg['metadata']['thread_info'] = {}
                        
                        subsequent_msg['metadata']['thread_info']['previous_thread_id'] = thread_previous_id
                        
                        # Upsert the updated message
                        patch_chat_message_metadata(cosmos_messages_container, subsequent_msg)
                        print(f"Repaired thread chain: Message {subsequent_msg['id']} now points to thread {thread_previous_id}")
                else:
                    messages_to_delete = [message_doc]
            else:
                # Delete only the specified message
                messages_to_delete = [message_doc]

            child_message_docs = _collect_child_message_documents(
                conversation_id,
                [message.get('id') for message in messages_to_delete],
            )
            if child_message_docs:
                messages_to_delete.extend(child_message_docs)
            
            # THREAD ATTEMPT PROMOTION: if the delete removes the active attempt's question,
            # another attempt takes its place. Deleting only an answer promotes nothing.
            if messages_to_delete:
                first_msg = messages_to_delete[0]
                first_thread_info = first_msg.get('metadata', {}).get('thread_info', {})
                thread_id = first_thread_info.get('thread_id')
                is_active = first_thread_info.get('active_thread', True)
                
                if thread_id and is_active:
                    promoted_attempt = _promote_remaining_thread_attempt(
                        conversation_id,
                        thread_id,
                        _thread_attempt_number(first_msg),
                        {message.get('id') for message in messages_to_delete},
                    )
                    if promoted_attempt is not None:
                        debug_print(
                            f"[THREAD] Promoted thread_attempt {promoted_attempt} to active "
                            f"after deleting the active attempt of thread {thread_id}"
                        )
            
            deleted_message_ids = []

            cleanup_chat_analysis_messages(
                messages_to_delete, conversation_id=conversation_id, owner_user_id=user_id,
            )
            
            for msg in messages_to_delete:
                msg_id = msg['id']
                
                if archiving_enabled:
                    # Mark as deleted and mask the message
                    if 'metadata' not in msg:
                        msg['metadata'] = {}
                    
                    msg['metadata']['is_deleted'] = True
                    msg['metadata']['deleted_by_user_id'] = user_id
                    msg['metadata']['deleted_timestamp'] = datetime.utcnow().isoformat()
                    msg['metadata']['masked'] = True
                    msg['metadata']['masked_by_user_id'] = user_id
                    msg['metadata']['masked_timestamp'] = datetime.utcnow().isoformat()
                    
                    msg = patch_chat_message_metadata(cosmos_messages_container, msg, fields=(
                        "is_deleted", "deleted_by_user_id", "deleted_timestamp",
                        "masked", "masked_by_user_id", "masked_timestamp",
                    ))
                    archived_msg = dict(msg)
                    archived_msg['archived_at'] = datetime.utcnow().isoformat()
                    cosmos_archived_messages_container.upsert_item(archived_msg)
                    
                else:
                    # Permanently delete the message
                    cosmos_messages_container.delete_item(msg_id, partition_key=conversation_id)
                
                deleted_message_ids.append(msg_id)

            _rebuild_authorized_personal_conversation_used_documents(
                user_id,
                conversation_id,
            )
            _invalidate_conversation_cache_after_message_mutation(
                conversation_id,
                user_id,
                "message_deleted",
            )
            return jsonify({
                'success': True,
                'deleted_message_ids': deleted_message_ids,
                'archived': archiving_enabled
            }), 200
            
        except Exception as e:
            print(f"Error deleting message: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to delete message'}), 500
    @bp.route('/api/message/<message_id>/retry', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def retry_message(message_id):
        """Prepare a new attempt using the viewed question's authorized input settings."""
        return _prepare_message_attempt_response(message_id)

    @bp.route('/api/message/<message_id>/edit', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def edit_message(message_id):
        """Prepare an edited attempt without changing the viewed attempt's routing."""
        return _prepare_message_attempt_response(message_id, edited=True)

    @bp.route('/api/message/<message_id>/switch-attempt', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def switch_attempt(message_id):
        """
        Switch between thread attempts by setting active_thread flags.
        Cycles through attempts based on direction (prev/next).
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401
        
        try:
            data = request.get_json() or {}
            direction = data.get('direction', 'next')  # 'prev' or 'next'
            
            # Find the current message
            query = "SELECT * FROM c WHERE c.id = @message_id"
            params = [{"name": "@message_id", "value": message_id}]
            message_results = list(cosmos_messages_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            ))
            
            if not message_results:
                return jsonify({'error': 'Message not found'}), 404
            
            current_msg = message_results[0]
            if is_soft_deleted_message(current_msg):
                return jsonify({'error': 'Message not found'}), 404
            conversation_id = current_msg.get('conversation_id')
            
            # Verify ownership
            message_user_id = current_msg.get('metadata', {}).get('user_info', {}).get('user_id')
            if not message_user_id:
                try:
                    conversation = cosmos_conversations_container.read_item(
                        item=conversation_id,
                        partition_key=conversation_id
                    )
                    if conversation.get('user_id') != user_id:
                        return jsonify({'error': 'You can only switch attempts in your own conversations'}), 403
                except Exception as ex:
                    return jsonify({'error': 'Conversation not found'}), 404
            elif message_user_id != user_id:
                return jsonify({'error': 'You can only switch attempts in your own conversations'}), 403
            
            # Get thread info
            thread_id = current_msg.get('metadata', {}).get('thread_info', {}).get('thread_id')
            current_attempt = current_msg.get('metadata', {}).get('thread_info', {}).get('thread_attempt', 0)
            
            if not thread_id:
                return jsonify({'error': 'Message has no thread_id'}), 400
            
            # Get the attempts for this thread_id whose question still exists. An attempt whose
            # question was deleted is not offered: switching to it would show a deleted turn.
            attempts_results = list(cosmos_messages_container.query_items(
                query=(
                    'SELECT c.metadata FROM c WHERE c.conversation_id = @conversation_id '
                    "AND c.metadata.thread_info.thread_id = @thread_id AND c.role = 'user'"
                ),
                parameters=[
                    {'name': '@conversation_id', 'value': conversation_id},
                    {'name': '@thread_id', 'value': thread_id},
                ],
                partition_key=conversation_id,
            ))
            
            available_attempts = sorted({
                _thread_attempt_number(result)
                for result in exclude_soft_deleted_messages(attempts_results)
            })
            
            if not available_attempts:
                return jsonify({'error': 'No attempts found'}), 404
            
            # Find current index and determine target attempt
            try:
                current_index = available_attempts.index(current_attempt)
            except ValueError:
                current_index = 0
            
            if direction == 'prev':
                target_index = (current_index - 1) % len(available_attempts)
            else:  # 'next'
                target_index = (current_index + 1) % len(available_attempts)
            
            target_attempt = available_attempts[target_index]
            
            # Deactivate all attempts for this thread
            deactivate_query = f"""
                SELECT * FROM c 
                WHERE c.conversation_id = '{conversation_id}' 
                AND c.metadata.thread_info.thread_id = '{thread_id}'
            """
            all_thread_messages = list(cosmos_messages_container.query_items(
                query=deactivate_query,
                partition_key=conversation_id
            ))
            
            # Update active_thread flags
            for msg in all_thread_messages:
                if 'metadata' not in msg:
                    msg['metadata'] = {}
                if 'thread_info' not in msg['metadata']:
                    msg['metadata']['thread_info'] = {}
                
                msg_attempt = msg['metadata']['thread_info'].get('thread_attempt', 0)
                msg['metadata']['thread_info']['active_thread'] = (msg_attempt == target_attempt)
                patch_chat_message_metadata(cosmos_messages_container, msg)

            _rebuild_authorized_personal_conversation_used_documents(
                user_id,
                conversation_id,
            )
            _invalidate_conversation_cache_after_message_mutation(
                conversation_id,
                user_id,
                "message_attempt_switched",
            )
            return jsonify({
                'success': True,
                'target_attempt': target_attempt,
                'available_attempts': available_attempts
            }), 200
            
        except Exception as e:
            print(f"Error switching attempt: {str(e)}")
            import traceback
            traceback.print_exc()
            return jsonify({'error': 'Failed to switch attempt'}), 500
