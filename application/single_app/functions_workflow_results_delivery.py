# functions_workflow_results_delivery.py
"""Per-run result publication using the ordinary conversation and invitation services."""

from copy import deepcopy
from datetime import datetime, timezone
from uuid import NAMESPACE_URL, uuid5
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from flask import session

from collaboration_models import normalize_collaboration_user
from cosmos_document_utils import normalize_cosmos_document
from functions_collaboration import (
    create_group_collaboration_conversation_record,
    create_personal_collaboration_conversation_record,
    ensure_collaboration_source_conversation,
)
from functions_conversation_cache import invalidate_conversation_cache_for_item
from functions_group import check_group_status_allows_operation
from functions_m365_history import history_sources, prepare_m365_history_publication
from functions_notifications import create_notification
from functions_simplechat_operations import (
    _build_invited_participants,
    _group_member_summaries,
    _require_collaboration_feature_enabled,
    _resolve_group_doc_for_current_user,
    create_personal_conversation_for_current_user,
)
from functions_workflow_configuration import normalize_results_delivery


RESULTS_RECEIPT_KEY = 'results_delivery_receipt'
_MONTH_NAMES = ('Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec')
RESULT_MESSAGE_FIELDS = (
    'content', 'model_deployment_name', 'augmented', 'hybrid_citations', 'web_search_citations',
    'citation_tracking_version', 'cited_hybrid_citations', 'cited_web_search_citations',
    'agent_citations', 'm365_citations', 'agent_display_name', 'agent_name',
    'generated_artifacts',
)


def workflow_run_title(workflow, run_record):
    """Use the immutable run name/start, never the completion clock or current title."""
    name = str(run_record.get('workflow_name') or workflow.get('name') or 'Untitled Workflow').strip()
    started = run_record.get('started_at')
    if isinstance(started, str):
        started = datetime.fromisoformat(started.replace('Z', '+00:00'))
    if not isinstance(started, datetime):
        raise ValueError('A workflow conversation requires its run start time.')
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    schedule = workflow.get('schedule') or {}
    zone_name = run_record.get('time_zone') or schedule.get('timezone') or workflow.get('time_zone') or 'UTC'
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError, TypeError):
        zone = timezone.utc
    local = started.astimezone(zone)
    # Seconds keep repeated manual runs in the same minute distinguishable.
    stamp = (
        f'{_MONTH_NAMES[local.month - 1]} {local.day}, {local.year}, '
        f'{local.hour % 12 or 12}:{local.minute:02d}:{local.second:02d} '
        f'{"AM" if local.hour < 12 else "PM"}'
    )
    return f'{name} · {stamp}'


def workflow_result_identity(workflow, run_record):
    return str(uuid5(NAMESPACE_URL, f"workflow-results:{workflow['id']}:{run_record['id']}"))


def build_workflow_result_message(workflow, run_record, source_message, *, shared=False):
    """Copy the outcome and retained presentation fields, not private execution metadata."""
    result = {key: deepcopy(source_message[key]) for key in RESULT_MESSAGE_FIELDS if key in source_message}
    metadata = source_message.get('metadata') or {}
    result['role'] = 'assistant'
    result['timestamp'] = source_message.get('timestamp') or run_record['started_at']
    result['metadata'] = {
        'source': 'workflow_result',
        'workflow': {'workflow_id': workflow['id'], 'run_id': run_record['id']},
        **{
            key: deepcopy(metadata[key])
            for key in ('generated_analysis_artifacts', 'generated_tabular_outputs', 'm365_source_policies')
            if key in metadata
        },
    }
    if not shared:
        for key in ('saved_analysis', 'saved_analyses', 'analysis_result_contexts'):
            if key in metadata:
                result['metadata'][key] = deepcopy(metadata[key])
    generated_images = (metadata.get('orchestration') or {}).get('generated_images') or []
    if generated_images:
        result['metadata']['orchestration'] = {'generated_images': deepcopy(generated_images)}
    return result


def _delivery_audience(workflow, config, creator, previous_receipt):
    group_id = str(workflow.get('group_id') or '').strip()
    group_doc = None
    if group_id:
        group_doc = _resolve_group_doc_for_current_user(
            creator['user_id'], group_id=group_id,
            allowed_roles=('Owner', 'Admin', 'DocumentManager', 'User'),
        )
        allowed, reason = check_group_status_allows_operation(group_doc, 'chat')
        if not allowed:
            raise PermissionError(reason)
    member_lookup = {member['user_id']: member for member in _group_member_summaries(group_doc)}
    recipient_ids = previous_receipt.get('recipient_ids')
    if recipient_ids is None:
        recipient_ids = (
            sorted(member_lookup) if config['all_group_members'] else config['recipient_ids']
        )
    recipient_ids = [user_id for user_id in recipient_ids if user_id != creator['user_id']]
    if group_id:
        if any(user_id not in member_lookup for user_id in recipient_ids):
            raise PermissionError('Results can only be shared with current members of the workflow group.')
        participants = [member_lookup[user_id] for user_id in recipient_ids]
    else:
        # Canonical ids come from the editor's directory choices. The ordinary
        # invitation service accepts those identities without requiring a live
        # browser's Graph token again when a scheduled run publishes.
        participants = _build_invited_participants(
            creator_user=creator, participants=[{'user_id': user_id} for user_id in recipient_ids],
        ) if recipient_ids else []
    return group_doc, participants, recipient_ids


def _notify_result_invites(conversation, creator, participants, run_id):
    scope = conversation.get('scope') or {}
    for participant in participants:
        notification = create_notification(
            user_id=participant['user_id'],
            notification_type='conversation_created',
            title=f"Shared workflow results: {conversation['title']}",
            message=f"{creator.get('display_name') or 'A teammate'} shared workflow results with you.",
            link_url=f"/chats?conversationId={conversation['id']}",
            link_context={
                'workspace_type': 'group' if scope.get('group_id') else 'personal',
                'group_id': scope.get('group_id'),
                'conversation_kind': conversation.get('conversation_kind'),
                'conversation_id': conversation['id'],
                'chat_type': conversation.get('chat_type'),
            },
            metadata={'conversation_id': conversation['id'], 'audience': 'participant'},
            idempotency_key=f"workflow-result-invite:{run_id}:{conversation['id']}",
            strict=True,
        )
        if not notification:
            raise RuntimeError('The results invitation could not be delivered.')


def publish_workflow_results(
    workflow, run_record, source_message, *, deliver_message, save_run, hide_audit,
):
    """Publish once; a failed/restarted delivery resumes its saved destination/audience."""
    if 'results_delivery' not in workflow:
        return None
    config = normalize_results_delivery(
        workflow['results_delivery'], workflow_scope='group' if workflow.get('group_id') else 'personal',
    )
    if config['mode'] != 'conversation':
        return None
    # Chat-origin post-back already owns publication and its durable delivery worker.
    if run_record.get('chat_delivery') and run_record.get('chat_invocation'):
        return None
    if not str(source_message.get('content') or '').strip() and not (
        source_message.get('agent_citations') or
        source_message.get('generated_artifacts') or
        (source_message.get('metadata') or {}).get('generated_analysis_artifacts') or
        (source_message.get('metadata') or {}).get('generated_tabular_outputs') or
        ((source_message.get('metadata') or {}).get('orchestration') or {}).get('generated_images')
    ):
        return None
    owner_id = str(workflow.get('user_id') or '').strip()
    current_user = session.get('user') or {}
    if current_user.get('oid') != owner_id:
        raise PermissionError('Results must be published as the workflow owner.')
    creator = normalize_collaboration_user({
        'user_id': owner_id, 'display_name': current_user.get('name') or owner_id,
        'email': current_user.get('preferred_username') or '',
    })
    receipt = deepcopy(run_record.get(RESULTS_RECEIPT_KEY) or {})
    conversation_id = workflow_result_identity(workflow, run_record)
    if receipt and receipt.get('conversation_id') != conversation_id:
        raise PermissionError('The result delivery receipt does not match this run.')
    if receipt and receipt.get('conversation_type') != config['conversation_type']:
        raise PermissionError('The result delivery destination cannot change while this run is being delivered.')
    shared = config['conversation_type'] in ('shared', 'group_shared')
    group_doc, participants, recipient_ids = _delivery_audience(workflow, config, creator, receipt)
    provenance = {'workflow_id': workflow['id'], 'run_id': run_record['id']}
    title = workflow_run_title(workflow, run_record)
    if shared:
        _require_collaboration_feature_enabled()
        # Apply existing source-publication policy; never turn a shared result into
        # permission to read the run's private audit/evidence.
        if history_sources([source_message]):
            prepare_m365_history_publication(
                owner_id, run_record['conversation_id'],
                'group' if group_doc else 'personal', participants,
            )
    if not receipt:
        receipt = {
            'version': 1, 'mode': 'conversation', 'status': 'pending',
            'conversation_type': config['conversation_type'], 'conversation_id': conversation_id,
            'message_id': str(uuid5(NAMESPACE_URL, f"workflow-result-message:{run_record['id']}:{conversation_id}")),
            'recipient_ids': recipient_ids,
        }
        run_record[RESULTS_RECEIPT_KEY] = receipt
        save_run(workflow, run_record)
    if shared:
        if group_doc:
            conversation, _states = create_group_collaboration_conversation_record(
                title, creator, group_doc, participants, conversation_id=conversation_id,
                workflow_provenance=provenance,
            )
        else:
            conversation, _states = create_personal_collaboration_conversation_record(
                title, creator, participants, conversation_id=conversation_id,
                workflow_provenance=provenance,
            )
        backing, conversation = ensure_collaboration_source_conversation(
            conversation, creator,
            source_conversation_id=str(uuid5(NAMESPACE_URL, f'workflow-results-backing:{conversation_id}')),
        )
    else:
        conversation = create_personal_conversation_for_current_user(
            title, conversation_id=conversation_id,
            group_id=str(workflow.get('group_id') or ''), workflow_provenance=provenance,
        )
        backing = conversation
    # Storage responses cross a strict presentation contract here, not at every read.
    conversation = normalize_cosmos_document(conversation)
    backing = normalize_cosmos_document(backing)
    if receipt.get('status') != 'delivered':
        result_message = build_workflow_result_message(workflow, run_record, source_message, shared=shared)
        delivered_message = deliver_message(
            workflow, run_record, source_message, result_message, conversation, backing, receipt,
        )
        if not delivered_message:
            raise RuntimeError('The workflow result could not be published.')
        if shared:
            _notify_result_invites(conversation, creator, participants, run_record['id'])
        receipt.update(status='delivered', delivered_at=datetime.now(timezone.utc).isoformat())
        run_record[RESULTS_RECEIPT_KEY] = receipt
        save_run(workflow, run_record)
    invalidate_conversation_cache_for_item(conversation, reason='workflow_results_delivered')
    hide_audit(run_record.get('conversation_id'))
    return receipt
