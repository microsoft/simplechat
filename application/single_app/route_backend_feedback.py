# route_backend_feedback.py

import csv
import io
import logging

from azure.core import MatchConditions
from flask import make_response

from config import *
from functions_appinsights import log_event
from functions_authentication import *
from functions_notifications import create_notification
from functions_review_assist import FEEDBACK_THEMES, ReviewAssistError, present_suggestion
from functions_review_assist_runtime import (
    ReviewRecordStore,
    handle_review_assist_request,
    review_assist_error_response,
)
from functions_review_center import (
    REVIEW_RECORD_CHANGED_CODE,
    REVIEW_WRITE_ATTEMPTS,
    ReviewRecordConflict,
    ReviewRequestError,
    apply_suggested_review,
    cap_review_ids,
    daily_counts,
    dismiss_review_suggestion,
    in_review_window,
    normalize_review_search,
    parse_review_bulk_operations,
    parse_review_date,
    parse_review_window,
    refuse_suggestion_operations_while_off,
    replace_review_record,
    resolve_review_users,
    review_bulk_result,
    review_day,
    review_excerpt,
    review_text_matches,
    review_window,
    summarize_review_bulk_results,
)
from functions_review_lifecycle import (
    ARCHIVE_STATE_ALL,
    apply_archive_state,
    append_archive_query_filter,
    log_review_lifecycle_action,
    normalize_archive_state,
    serialize_archive_metadata,
)
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security   


ALLOWED_FEEDBACK_TYPES = {"Positive", "Negative", "Neutral"}
ALLOWED_PAGE_SIZES = {10, 20, 50, 100}
FEEDBACK_TYPE_NORMALIZATION = {
    "positive": "Positive",
    "negative": "Negative",
    "neutral": "Neutral",
}
FEEDBACK_REVIEW_TEXT_FIELDS = ('analysisNotes', 'responseToUser', 'actionTaken')
FEEDBACK_REVIEW_TEXT_MAX_LENGTH = 8000
FEEDBACK_OLDEST_AWAITING_LIMIT = 5
FEEDBACK_RECORD_CHANGED_MESSAGE = (
    'This feedback changed after you opened it. Reload it to see the latest version, then try again.'
)
# The notice a user receives when a reviewer chooses to tell them about the review. The link
# opens the user's own feedback list: classic Profile, and V2 Settings, which reads it too.
FEEDBACK_RESPONSE_NOTIFICATION_TYPE = 'feedback_response'
FEEDBACK_RESPONSE_NOTIFICATION_TITLE = 'An administrator responded to your feedback'
FEEDBACK_RESPONSE_NOTIFICATION_FALLBACK = 'An administrator reviewed the feedback you sent about an AI response.'
FEEDBACK_RESPONSE_NOTIFICATION_LINK = '/profile?tab=feedback'
FEEDBACK_RESPONSE_NOTIFICATION_MAX_LENGTH = 1000
# Review fields for reviewers only: who reviewed the feedback, and how it was classified.
FEEDBACK_REVIEWER_ONLY_FIELDS = frozenset({'analyzedBy', 'theme'})
FEEDBACK_AI_FILTER_PENDING = 'pending'


def _authorize_feedback_conversation(user_id, conversation_id):
    """Load the target conversation and ensure the caller owns it."""
    try:
        conversation_item = cosmos_conversations_container.read_item(
            item=conversation_id,
            partition_key=conversation_id,
        )
    except CosmosResourceNotFoundError as exc:
        raise LookupError(f"Conversation {conversation_id} not found") from exc

    if conversation_item.get("user_id") != user_id:
        raise PermissionError("Forbidden")

    return conversation_item


def _get_feedback_session_user_id():
    if "user" not in session:
        return None

    return session["user"].get("oid") or session["user"].get("sub")


def _normalize_feedback_page_size(page_size):
    return page_size if page_size in ALLOWED_PAGE_SIZES else 10


def _normalize_feedback_type(feedback_type):
    if not isinstance(feedback_type, str):
        return None

    return FEEDBACK_TYPE_NORMALIZATION.get(feedback_type.strip().lower())


def _parse_feedback_filters(include_archive_state=False):
    filter_type = _normalize_feedback_type(request.args.get('type', None, type=str))

    filter_ack_str = request.args.get('ack', None, type=str)
    filter_ack_bool = None
    if filter_ack_str == 'true':
        filter_ack_bool = True
    elif filter_ack_str == 'false':
        filter_ack_bool = False

    archive_state = None
    if include_archive_state:
        archive_state = normalize_archive_state(request.args.get('archive', None, type=str))

    return filter_type, filter_ack_bool, archive_state


def _serialize_feedback_item(item, include_suggestion=False):
    normalized_feedback_type = _normalize_feedback_type(item.get("feedbackType"))

    serialized_item = {
        "id": item.get("id"),
        "userId": item.get("userId"),
        "prompt": item.get("prompt"),
        "aiResponse": item.get("aiResponse"),
        "feedbackType": normalized_feedback_type or item.get("feedbackType"),
        "reason": item.get("reason"),
        "timestamp": item.get("timestamp"),
        "adminReview": item.get("adminReview", {}),
    }
    serialized_item.update(serialize_archive_metadata(item))
    if include_suggestion:
        # Reviewers see the AI suggestion as it stands now; the stored fingerprint stays here.
        serialized_item["ai_suggestion"] = present_suggestion('feedback', item)
    return serialized_item


def _query_feedback_items(
    user_id=None,
    filter_type=None,
    filter_ack_bool=None,
    archive_state='active',
):
    query = "SELECT * FROM c"
    where_clauses = []
    parameters = []

    if user_id:
        where_clauses.append("c.userId = @userId")
        parameters.append({"name": "@userId", "value": user_id})

    if filter_ack_bool is not None:
        where_clauses.append("c.adminReview.acknowledged = @ack")
        parameters.append({"name": "@ack", "value": filter_ack_bool})

    append_archive_query_filter(where_clauses, archive_state)

    if where_clauses:
        query += " WHERE " + " AND ".join(where_clauses)

    query += " ORDER BY c.timestamp DESC"

    items = list(cosmos_feedback_container.query_items(
        query=query,
        parameters=parameters,
        enable_cross_partition_query=True,
    ))

    serialized_items = [_serialize_feedback_item(item, include_suggestion=not user_id) for item in items]
    if user_id:
        # Who reviewed the feedback, and how it was classified, is for reviewers; the user
        # sees the review itself.
        for serialized_item in serialized_items:
            review = serialized_item.get("adminReview")
            if isinstance(review, dict) and FEEDBACK_REVIEWER_ONLY_FIELDS.intersection(review):
                serialized_item["adminReview"] = {
                    key: value for key, value in review.items() if key not in FEEDBACK_REVIEWER_ONLY_FIELDS
                }

    if filter_type:
        serialized_items = [
            item for item in serialized_items
            if item.get("feedbackType") == filter_type
        ]

    return serialized_items


def _paginate_feedback_items(items, page, page_size):
    if page < 1:
        page = 1

    page_size = _normalize_feedback_page_size(page_size)
    offset = (page - 1) * page_size
    return items[offset: offset + page_size], page, page_size


def _build_feedback_stats(items):
    stats = {
        "total_count": len(items),
        "positive_count": 0,
        "negative_count": 0,
        "neutral_count": 0,
        "acknowledged_count": 0,
        "unacknowledged_count": 0,
        "recent_30_day_count": 0,
        "latest_timestamp": items[0].get('timestamp') if items else None,
    }

    recent_cutoff = datetime.utcnow() - timedelta(days=30)

    for item in items:
        feedback_type = _normalize_feedback_type(item.get('feedbackType')) or item.get('feedbackType')
        if feedback_type == 'Positive':
            stats['positive_count'] += 1
        elif feedback_type == 'Negative':
            stats['negative_count'] += 1
        elif feedback_type == 'Neutral':
            stats['neutral_count'] += 1

        acknowledged = bool((item.get('adminReview') or {}).get('acknowledged'))
        if acknowledged:
            stats['acknowledged_count'] += 1
        else:
            stats['unacknowledged_count'] += 1

        timestamp = item.get('timestamp')
        if timestamp:
            try:
                parsed_timestamp = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                if parsed_timestamp.replace(tzinfo=None) >= recent_cutoff:
                    stats['recent_30_day_count'] += 1
            except ValueError:
                pass

    return stats


def _build_feedback_export_response(items, filename_prefix, include_user_id=False):
    output = io.StringIO()
    writer = csv.writer(output)

    headers = [
        'Timestamp',
        'Feedback Type',
        'Reason',
        'Prompt',
        'AI Response',
        'Acknowledged',
        'Admin Notes',
        'Admin Response',
        'Admin Action',
        'Archived',
        'Archived At',
        'Archived By',
    ]
    if include_user_id:
        headers.insert(1, 'User ID')

    writer.writerow(headers)

    for item in items:
        admin_review = item.get('adminReview') or {}
        row = [
            item.get('timestamp') or '',
            item.get('feedbackType') or '',
            item.get('reason') or '',
            item.get('prompt') or '',
            item.get('aiResponse') or '',
            'Yes' if admin_review.get('acknowledged') else 'No',
            admin_review.get('analysisNotes') or '',
            admin_review.get('responseToUser') or '',
            admin_review.get('actionTaken') or '',
            'Yes' if item.get('isArchived') else 'No',
            item.get('archivedAt') or '',
            item.get('archivedBy') or '',
        ]
        if include_user_id:
            row.insert(1, item.get('userId') or '')
        writer.writerow(row)

    response = make_response(output.getvalue())
    response.headers['Content-Type'] = 'text/csv'
    response.headers['Content-Disposition'] = (
        f'attachment; filename={filename_prefix}_{datetime.utcnow().strftime("%Y%m%d_%H%M%S")}.csv'
    )
    return response


def _get_feedback_admin_actor():
    user = session.get('user', {}) or {}
    actor_id = _get_feedback_session_user_id()
    return {
        'id': actor_id,
        'email': user.get('preferred_username') or user.get('email') or '',
        'name': user.get('name') or user.get('preferred_username') or '',
    }


def _feedback_lifecycle_body(message, audit_logged):
    response = {
        'success': True,
        'message': message,
        'audit_logged': audit_logged,
    }
    if not audit_logged:
        response['audit_warning'] = (
            'The record was updated, but the audit activity could not be recorded.'
        )
    return response


def _feedback_lifecycle_response(message, audit_logged):
    return jsonify(_feedback_lifecycle_body(message, audit_logged))


def _log_feedback_audit_failure(feedback_id, lifecycle_action):
    log_event(
        '[FEEDBACK_LIFECYCLE] Failed to persist lifecycle audit event',
        {
            'feedback_id': feedback_id,
            'lifecycle_action': lifecycle_action,
        },
        level=logging.ERROR,
    )


def _feedback_record_changed_body():
    return {'error': FEEDBACK_RECORD_CHANGED_MESSAGE, 'code': REVIEW_RECORD_CHANGED_CODE}


def _review_assist_client(settings):
    """The draft-instructions deployment's client and model name, as the other AI assistants use."""
    # Lazy: route_backend_agents loads the agent stack, which app.py has already imported by the
    # time a request arrives. Importing it when this module loads would make the feedback routes
    # depend on that whole stack.
    from route_backend_agents import _create_agent_instruction_client, _resolve_agent_instruction_model
    return _create_agent_instruction_client(settings), _resolve_agent_instruction_model(settings)


def _feedback_write_attempts(expected_etag):
    """How often a save may write: once when it names the version it read, so a conflict is
    refused rather than merged onto a newer version; otherwise it is merged field by field."""
    return 1 if expected_etag else REVIEW_WRITE_ATTEMPTS


def _feedback_acknowledged(item):
    return bool((item.get('adminReview') or {}).get('acknowledged'))


def _parse_feedback_list_filters():
    """Read the Review center list filters. Raises ValueError for a value that can't be used."""
    filter_type, filter_ack_bool, archive_state = _parse_feedback_filters(include_archive_state=True)
    theme = (request.args.get('theme') or '').strip().lower() or None
    if theme and theme not in FEEDBACK_THEMES:
        raise ReviewRequestError('Unknown feedback theme.', code='invalid_theme')
    ai_state = (request.args.get('ai') or '').strip().lower() or None
    if ai_state and ai_state != FEEDBACK_AI_FILTER_PENDING:
        raise ReviewRequestError('Unknown AI suggestion state.', code='invalid_ai_state')
    return {
        'type': filter_type,
        'ack': filter_ack_bool,
        'archive': archive_state,
        'search': normalize_review_search(request.args.get('search')),
        'user_id': (request.args.get('user_id') or '').strip() or None,
        'date': parse_review_date(request.args.get('date')),
        'days': parse_review_window(request.args.get('days')),
        'theme': theme,
        'ai': ai_state,
    }


def _feedback_matches(item, filters, users, window):
    if filters['user_id'] and item.get('userId') != filters['user_id']:
        return False
    if filters['date'] and review_day(item.get('timestamp')) != filters['date']:
        return False
    if window and not in_review_window(item.get('timestamp'), window):
        return False
    if filters.get('theme') and (item.get('adminReview') or {}).get('theme') != filters['theme']:
        return False
    # The AI suggestions queue: suggestions still waiting for a reviewer, stale ones included so
    # they can be dismissed.
    if filters.get('ai') == FEEDBACK_AI_FILTER_PENDING and (
        (item.get('ai_suggestion') or {}).get('status') not in ('pending', 'stale')
    ):
        return False
    if filters['search']:
        review = item.get('adminReview') or {}
        user = users.get(item.get('userId')) or {}
        return review_text_matches(
            filters['search'],
            item.get('id'),
            item.get('prompt'),
            item.get('aiResponse'),
            item.get('reason'),
            item.get('userId'),
            review.get('analysisNotes'),
            review.get('responseToUser'),
            review.get('actionTaken'),
            user.get('display_name'),
            user.get('email'),
        )
    return True


def _load_admin_feedback(filters):
    """The feedback a Review center list or "select all matching" covers, newest first."""
    items = _query_feedback_items(
        filter_type=filters['type'],
        filter_ack_bool=filters['ack'],
        archive_state=filters['archive'],
    )
    users = resolve_review_users([item.get('userId') for item in items]) if filters['search'] else {}
    window = review_window(filters['days']) if filters['days'] else None
    return [item for item in items if _feedback_matches(item, filters, users, window)], users


def _with_feedback_user_names(items, users=None):
    """Add each record's user display name and email, looked up in one batch."""
    names = dict(users or {})
    missing = [item.get('userId') for item in items if item.get('userId') not in names]
    if missing:
        names.update(resolve_review_users(missing))
    for item in items:
        entry = names.get(item.get('userId')) or {}
        item['userDisplayName'] = entry.get('display_name') or None
        item['userEmail'] = entry.get('email') or None
    return items


def _build_feedback_window_stats(days):
    """The Feedback dashboard for the last ``days`` days, read across active and archived records."""
    window = review_window(days)
    items = _query_feedback_items(archive_state=ARCHIVE_STATE_ALL)
    in_window = [item for item in items if in_review_window(item.get('timestamp'), window)]
    awaiting = [item for item in items if not item.get('isArchived') and not _feedback_acknowledged(item)]
    oldest = sorted(awaiting, key=lambda item: str(item.get('timestamp') or ''))[:FEEDBACK_OLDEST_AWAITING_LIMIT]
    names = resolve_review_users([item.get('userId') for item in oldest])
    acknowledged_in_window = sum(1 for item in in_window if _feedback_acknowledged(item))
    theme_counts = {}
    for item in in_window:
        theme = (item.get('adminReview') or {}).get('theme')
        if theme in FEEDBACK_THEMES:
            theme_counts[theme] = theme_counts.get(theme, 0) + 1
    return {
        'window': {
            'days': window['days'],
            'start_date': window['start_date'],
            'end_date': window['end_date'],
        },
        'received_count': len(in_window),
        'awaiting_review_count': len(awaiting),
        'negative_count_in_window': sum(1 for item in in_window if item.get('feedbackType') == 'Negative'),
        'acknowledged_count_in_window': acknowledged_in_window,
        'acknowledgement_rate': round(acknowledged_in_window / len(in_window), 4) if in_window else None,
        'archived_count': sum(1 for item in items if item.get('isArchived')),
        'daily_by_rating': daily_counts(
            in_window,
            window,
            lambda item: item.get('timestamp'),
            lambda item: item.get('feedbackType') or 'Unknown',
        ),
        # What the reviewed feedback was about, as reviewers classified it.
        'theme_mix': [
            {'theme': theme, 'count': count}
            for theme, count in sorted(theme_counts.items(), key=lambda pair: (-pair[1], pair[0]))
        ],
        'unthemed_count_in_window': len(in_window) - sum(theme_counts.values()),
        'oldest_awaiting': [
            {
                'id': item.get('id'),
                'feedbackType': item.get('feedbackType'),
                'timestamp': item.get('timestamp'),
                'userId': item.get('userId'),
                'userDisplayName': (names.get(item.get('userId')) or {}).get('display_name') or None,
                'promptExcerpt': review_excerpt(item.get('prompt')),
            }
            for item in oldest
        ],
    }


def _validate_feedback_review_changes(data):
    """Return an error message for review changes the API refuses, or None."""
    if 'acknowledged' in data and not isinstance(data.get('acknowledged'), bool):
        return 'Acknowledged must be true or false.'
    for field in FEEDBACK_REVIEW_TEXT_FIELDS:
        value = data.get(field)
        if value is not None and not isinstance(value, str):
            return f'{field} must be text.'
        if isinstance(value, str) and len(value) > FEEDBACK_REVIEW_TEXT_MAX_LENGTH:
            return f'{field} is too long.'
    if 'notify_user' in data and not isinstance(data.get('notify_user'), bool):
        return 'notify_user must be true or false.'
    theme = data.get('theme')
    if theme not in (None, '') and theme not in FEEDBACK_THEMES:
        return f'theme must be one of: {", ".join(FEEDBACK_THEMES)}.'
    return None


def _notify_feedback_user(feedback_doc, actor):
    """Tell the user who sent the feedback that a reviewer responded. Returns a warning or None."""
    user_id = feedback_doc.get('userId')
    if not user_id:
        return 'The user could not be notified because the feedback has no user.'
    response_text = str(((feedback_doc.get('adminReview') or {}).get('responseToUser')) or '').strip()
    message = response_text[:FEEDBACK_RESPONSE_NOTIFICATION_MAX_LENGTH] or FEEDBACK_RESPONSE_NOTIFICATION_FALLBACK
    notification = create_notification(
        user_id=user_id,
        notification_type=FEEDBACK_RESPONSE_NOTIFICATION_TYPE,
        title=FEEDBACK_RESPONSE_NOTIFICATION_TITLE,
        message=message,
        link_url=FEEDBACK_RESPONSE_NOTIFICATION_LINK,
        link_context={'tab': 'feedback', 'feedback_id': feedback_doc.get('id')},
        metadata={'feedback_id': feedback_doc.get('id')},
    )
    if notification is None:
        log_event('[FEEDBACK_REVIEW] The feedback response notification could not be created.', {
            'feedback_id': feedback_doc.get('id'),
            'actor_id': actor.get('id'),
        }, level=logging.WARNING)
        return 'The review was saved, but the user could not be notified.'
    log_event('[FEEDBACK_REVIEW] The user was notified about a feedback review.', {
        'feedback_id': feedback_doc.get('id'),
        'actor_id': actor.get('id'),
        'notification_id': notification.get('id'),
    })
    return None


def _apply_feedback_review_update(feedback_id, data, actor):
    """Save a reviewer's review of one feedback record. Returns ``(body, status)``.

    Shared by PATCH /feedback/review/<id> and the bulk ``update`` operation. Only the fields
    sent change; the reviewer is recorded as ``adminReview.analyzedBy``. ``etag``, when
    sent, must match the stored record. ``notify_user: true`` sends the user a notification
    with the response once the review is saved.
    """
    if not isinstance(data, dict):
        return {"error": "The request body must be an object."}, 400
    problem = _validate_feedback_review_changes(data)
    if problem:
        return {"error": problem}, 400
    expected_etag = data.get('etag')
    if expected_etag is not None and not isinstance(expected_etag, str):
        return {"error": "The etag must be text."}, 400
    if not actor.get('id'):
        return {'error': 'No user ID found in session'}, 403

    try:
        feedback_doc = cosmos_feedback_container.read_item(item=feedback_id, partition_key=feedback_id)
    except CosmosResourceNotFoundError:
        return {"error": "Feedback not found"}, 404
    except Exception as e:
        log_event('[FEEDBACK_REVIEW] A feedback record could not be read for review.', {
            'feedback_id': feedback_id,
            'error_type': type(e).__name__,
        }, level=logging.ERROR)
        return {"error": "Failed to read feedback item"}, 500
    if expected_etag and feedback_doc.get('_etag') != expected_etag:
        return _feedback_record_changed_body(), 409

    notify_user = data.get('notify_user') is True
    reviewed_at = datetime.utcnow().isoformat()

    def apply_review(record):
        admin_review = dict(record.get("adminReview") or {})
        admin_review["acknowledged"] = data.get("acknowledged", admin_review.get("acknowledged", False))
        for field in FEEDBACK_REVIEW_TEXT_FIELDS:
            admin_review[field] = data.get(field, admin_review.get(field))
        if 'theme' in data:
            admin_review["theme"] = data.get('theme') or None
        admin_review["reviewTimestamp"] = reviewed_at
        admin_review["analyzedBy"] = {'id': actor['id'], 'displayName': actor.get('name') or actor.get('email') or ''}
        if notify_user:
            admin_review["userNotifiedAt"] = reviewed_at
        record["adminReview"] = admin_review

    try:
        # A save that names the version it read is written on that version or not at all;
        # one that doesn't is merged field by field onto a newer version.
        stored = replace_review_record(
            cosmos_feedback_container,
            feedback_id,
            apply_review,
            base_item=feedback_doc,
            attempts=_feedback_write_attempts(expected_etag),
        )
    except ReviewRecordConflict:
        return _feedback_record_changed_body(), 409
    except CosmosResourceNotFoundError:
        return {"error": "Feedback not found"}, 404
    except Exception as e:
        log_event('[FEEDBACK_REVIEW] A feedback review could not be saved.', {
            'feedback_id': feedback_id,
            'error_type': type(e).__name__,
        }, level=logging.ERROR)
        return {"error": "Failed to save changes"}, 500

    body = {"success": True, "etag": stored.get('_etag'), "notified": False}
    if notify_user:
        warning = _notify_feedback_user(stored, actor)
        body["notified"] = warning is None
        if warning:
            body["notification_warning"] = warning
    return body, 200


def _archive_feedback(feedback_id, archived, actor, expected_etag=None):
    """Archive or restore one feedback record. Returns ``(body, status)``.

    Shared by the archive route and the bulk ``archive`` operation. Only the archive fields
    change, conditionally on the stored version, so a concurrent review save survives.
    """
    if not isinstance(archived, bool):
        return {'error': 'The archived field must be a boolean.'}, 400
    if not actor.get('id'):
        return {'error': 'No user ID found in session'}, 403

    try:
        feedback_doc = cosmos_feedback_container.read_item(item=feedback_id, partition_key=feedback_id)
        if expected_etag and feedback_doc.get('_etag') != expected_etag:
            return _feedback_record_changed_body(), 409
        was_archived = bool(feedback_doc.get('is_archived'))

        def apply_archive(record):
            apply_archive_state(record, archived, actor['id'])

        stored = replace_review_record(
            cosmos_feedback_container,
            feedback_id,
            apply_archive,
            base_item=feedback_doc,
            attempts=_feedback_write_attempts(expected_etag),
        )
    except CosmosResourceNotFoundError:
        return {'error': 'Feedback not found'}, 404
    except ReviewRecordConflict:
        return _feedback_record_changed_body(), 409
    except Exception as e:
        log_event(
            '[FEEDBACK_LIFECYCLE] Failed to update feedback archive state',
            {'feedback_id': feedback_id, 'error_type': type(e).__name__},
            level=logging.ERROR,
        )
        return {'error': 'Failed to update feedback archive state'}, 500

    lifecycle_action = 'archive' if archived else 'unarchive'
    audit_logged = log_review_lifecycle_action(
        'feedback',
        lifecycle_action,
        stored,
        actor,
        was_archived=was_archived,
    )
    if not audit_logged:
        _log_feedback_audit_failure(feedback_id, lifecycle_action)

    message = 'Feedback archived successfully.' if archived else 'Feedback unarchived successfully.'
    return _feedback_lifecycle_body(message, audit_logged), 200


def _delete_feedback(feedback_id, actor, expected_etag=None):
    """Permanently delete one feedback record, keeping its audit entry. Returns ``(body, status)``."""
    if not actor.get('id'):
        return {'error': 'No user ID found in session'}, 403

    try:
        feedback_doc = cosmos_feedback_container.read_item(item=feedback_id, partition_key=feedback_id)
        if expected_etag and feedback_doc.get('_etag') != expected_etag:
            return _feedback_record_changed_body(), 409
        if feedback_doc.get('_etag'):
            cosmos_feedback_container.delete_item(
                item=feedback_id,
                partition_key=feedback_id,
                etag=feedback_doc.get('_etag'),
                match_condition=MatchConditions.IfNotModified,
            )
        else:
            cosmos_feedback_container.delete_item(item=feedback_id, partition_key=feedback_id)
    except CosmosResourceNotFoundError:
        return {'error': 'Feedback not found'}, 404
    except exceptions.CosmosAccessConditionFailedError:
        return _feedback_record_changed_body(), 409
    except Exception as e:
        log_event(
            '[FEEDBACK_LIFECYCLE] Failed to delete feedback',
            {'feedback_id': feedback_id, 'error_type': type(e).__name__},
            level=logging.ERROR,
        )
        return {'error': 'Failed to delete feedback'}, 500

    audit_logged = log_review_lifecycle_action(
        'feedback',
        'delete',
        feedback_doc,
        actor,
    )
    if not audit_logged:
        _log_feedback_audit_failure(feedback_id, 'delete')

    return _feedback_lifecycle_body('Feedback permanently deleted.', audit_logged), 200


def register_route_backend_feedback(bp):

    @bp.route("/feedback/submit", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_submit():
        """
        Endpoint to store user feedback:
          POST /feedback/submit
          JSON body: { messageId, conversationId, feedbackType, reason }
        """
        data = request.get_json() or {}
        messageId = data.get("messageId")          # This is the ID of the specific AI message
        conversationId = data.get("conversationId") # This is the ID of the conversation
        feedbackType = _normalize_feedback_type(data.get("feedbackType"))
        reason = data.get("reason", "")
        user_id = None
        if "user" in session:
            user_id = session["user"].get("oid") or session["user"].get("sub")

        if not messageId or not conversationId or not feedbackType:
            return jsonify({"error": "Missing required fields"}), 400

        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            _authorize_feedback_conversation(user_id, conversationId)
        except LookupError:
            return jsonify({"error": "Conversation not found"}), 404
        except PermissionError:
            return jsonify({"error": "Forbidden", "message": "You do not have access to this conversation"}), 403

        ai_message_text = None
        user_prompt_text = None
        all_messages = [] # Initialize an empty list for messages

        try:
            # --- CORRECTED PART ---
            # Query the cosmos_messages_container for all messages in this conversation
            # Order by timestamp to find the preceding message correctly
            query = "SELECT * FROM c WHERE c.conversation_id = @conversationId ORDER BY c.timestamp ASC"
            parameters = [{"name": "@conversationId", "value": conversationId}]

            # Execute the query against the cosmos_messages_container, specifying the partition key
            message_items = list(cosmos_messages_container.query_items(
                query=query,
                parameters=parameters,
                partition_key=conversationId # Use the partition key for efficiency
                # enable_cross_partition_query=False # Not needed if partition_key is specified
            ))
            # --- END CORRECTED PART ---

            if not message_items:
                return jsonify({"error": "Assistant message not found"}), 404

            all_messages = message_items # Assign the query results to all_messages

            # Find the AI message corresponding to the messageId
            ai_msg_index = -1
            for i, msg in enumerate(all_messages):
                # **** IMPORTANT ASSUMPTION ****
                # Assuming the 'messageId' sent from the frontend corresponds to the 'id' field
                # of the message document in cosmos_messages_container.
                # If your message documents use a different field like 'message_id', change 'msg.get("id")' below.
                if msg.get("role") == "assistant" and msg.get("id") == messageId:
                    ai_message_text = msg.get("content")
                    ai_msg_index = i
                    break

            if ai_msg_index == -1:
                return jsonify({"error": "Assistant message not found"}), 404

            # Find the user message immediately preceding the AI message
            if ai_msg_index > 0:
                 # Iterate backwards from the message before the AI's message
                 for i in range(ai_msg_index - 1, -1, -1):
                      if all_messages[i].get("role") == "user":
                          user_prompt_text = all_messages[i].get("content")
                          break # Found the closest preceding user prompt

            # Fallback if direct preceding message not found (or AI message was first)
            if not user_prompt_text and all_messages:
                # Find the *last* user message in the conversation up to the AI message index
                # (or the very last if AI message wasn't found)
                search_limit = ai_msg_index if ai_msg_index != -1 else len(all_messages)
                for i in range(search_limit -1, -1, -1):
                     if all_messages[i].get("role") == "user":
                          user_prompt_text = all_messages[i].get("content")
                          break
        except Exception as e:
            print(f"Error querying messages for conversation {conversationId}: {e}")
            return jsonify({"error": "Failed to load feedback target"}), 500

        # Set default text if messages weren't found
        if ai_message_text is None:
            ai_message_text = "[AI_RESPONSE_TEXT_NOT_FOUND_IN_COSMOS_MESSAGES_CONTAINER]"

        if not user_prompt_text:
            user_prompt_text = "[USER_PROMPT_NOT_FOUND_IN_COSMOS_MESSAGES_CONTAINER]"

        # --- Rest of the feedback saving logic remains the same ---
        feedback_id = str(uuid.uuid4())
        item = {
            "id": feedback_id,
            "partitionKey": feedback_id, # Explicitly set partition key if it's the ID
            "userId": user_id,
            "conversationId": conversationId, # Good practice to store the conversation ID too
            "messageId": messageId, # Store the ID of the message being reviewed
            "prompt": user_prompt_text,
            "aiResponse": ai_message_text,
            "feedbackType": feedbackType,
            "reason": reason,
            "timestamp": datetime.utcnow().isoformat(),
            "adminReview": {
                "acknowledged": False,
                "analyzedBy": None,
                "analysisNotes": None,
                "responseToUser": None,
                "actionTaken": None,
                "reviewTimestamp": None
            }
        }

        try:
            cosmos_feedback_container.upsert_item(item)
            return jsonify({"success": True, "feedbackId": feedback_id})
        except Exception as e:
            print(f"Error saving feedback item {feedback_id}: {e}")
            return jsonify({"error": "Failed to save feedback"}), 500
    

    @bp.route("/feedback/review", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_get():
        """
        Return feedback for admin review with pagination and filtering.

        Query parameters: page, page_size, type, ack and archive as before, plus the Review
        center's search, user_id, date (YYYY-MM-DD) and days (7, 30 or 90). Each record
        carries userDisplayName and userEmail.
        """
        try:
            page = request.args.get('page', 1, type=int)
            page_size = request.args.get('page_size', 10, type=int)
            filters = _parse_feedback_list_filters()
            items, users = _load_admin_feedback(filters)
            paginated_items, page, page_size = _paginate_feedback_items(items, page, page_size)
            _with_feedback_user_names(paginated_items, users)
            total_count = len(items)

            return jsonify({
                "feedback": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": total_count,
                "total_pages": math.ceil(total_count / page_size)
            })

        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
             print(f"Error fetching feedback for review: {e}")
             # Log the full exception traceback if possible
             import traceback
             traceback.print_exc()
             return jsonify({"error": f"Failed to retrieve feedback: {str(e)}"}), 500

    @bp.route("/feedback/review/ids", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_ids():
        """Return the ids of the feedback matching the list filters, for "select all matching".

        Takes the same filters as GET /feedback/review. At most 500 ids are returned:
        ``total`` is how many matched, and ``capped`` says whether the cap applied.
        """
        try:
            filters = _parse_feedback_list_filters()
            items, _users = _load_admin_feedback(filters)
            return jsonify(cap_review_ids([item.get('id') for item in items])), 200
        except ValueError:
            return jsonify({"error": "Invalid request parameters."}), 400
        except Exception as e:
            log_event('[FEEDBACK_REVIEW] Matching feedback ids could not be listed.', {
                'error_type': type(e).__name__,
            }, level=logging.ERROR)
            return jsonify({"error": "The matching feedback could not be listed."}), 500

    @bp.route("/feedback/review/stats", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_stats():
        """Return aggregate feedback review statistics for the admin page.

        With ``days`` (7, 30 or 90) the response also carries the Review center dashboard:
        feedback awaiting review, negative feedback and the acknowledgement rate in the
        window, archived feedback, feedback per day by rating and the oldest feedback
        awaiting review. Every other field is unchanged.
        """
        try:
            filter_type, filter_ack_bool, archive_state = _parse_feedback_filters(
                include_archive_state=True,
            )
            days = parse_review_window(request.args.get('days'))
            items = _query_feedback_items(
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
                archive_state=archive_state,
            )
            stats = _build_feedback_stats(items)
            if days:
                stats.update(_build_feedback_window_stats(days))
            return jsonify(stats)
        except ValueError:
            logging.exception("Invalid request parameters for feedback review stats")
            return jsonify({"error": "Invalid request parameters."}), 400
        except Exception:
            logging.exception("Failed to retrieve feedback stats")
            return jsonify({"error": "Failed to retrieve feedback stats."}), 500

    @bp.route("/feedback/review/export", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_export():
        """Export feedback review rows as CSV for the active filter set.

        Takes the same filters as GET /feedback/review, so an export matches the list.
        """
        try:
            filters = _parse_feedback_list_filters()
            items, _users = _load_admin_feedback(filters)
            return _build_feedback_export_response(items, 'feedback_review_export', include_user_id=True)
        except ValueError as e:
            return jsonify({"error": str(e)}), 400
        except Exception as e:
            return jsonify({"error": f"Failed to export feedback: {str(e)}"}), 500

    @bp.route("/feedback/review/bulk", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_bulk():
        """Apply up to 100 review operations to feedback, each as its single route would.

        Body: ``{"operations": [{"id", "op", "etag"?, ...}]}``. ``update`` carries
        ``changes``, the same fields PATCH /feedback/review/<id> accepts; ``archive`` carries
        ``archived``; ``delete`` carries nothing more. Each result repeats the single route's
        response with ``ok`` and ``status``, in request order; one failure never stops the
        others. An ``update`` with ``suggestion_id`` applies the record's pending AI suggestion
        as the reviewer edited it, and ``dismiss_suggestion`` dismisses one; a suggestion that
        is stale or no longer pending is refused with ``suggestion_stale`` or
        ``suggestion_not_pending``, and while AI assist is off both are refused with
        ``review_assistant_disabled``.
        """
        actor = _get_feedback_admin_actor()
        if not actor.get('id'):
            return jsonify({'error': 'No user ID found in session'}), 403
        try:
            operations = parse_review_bulk_operations(request.get_json(silent=True))
        except ReviewRequestError as error:
            return jsonify({'error': error.message, 'code': error.code}), error.status
        if any(operation.get('suggestion_id') for operation in operations):
            operations = refuse_suggestion_operations_while_off(
                operations, is_admin_review_assistant_enabled(get_settings()),
            )

        results = []
        for operation in operations:
            if operation.get('error'):
                results.append(review_bulk_result(
                    operation, operation['error']['body'], operation['error']['status'],
                ))
                continue
            if operation['op'] == 'update':
                changes = {key: value for key, value in operation['changes'].items() if key != 'etag'}
                if operation['etag']:
                    changes['etag'] = operation['etag']
                if operation.get('suggestion_id'):
                    body, status = apply_suggested_review(
                        cosmos_feedback_container, 'feedback', operation['id'], operation['suggestion_id'], changes, actor,
                        lambda checked, record_id=operation['id']: _apply_feedback_review_update(record_id, checked, actor),
                    )
                else:
                    body, status = _apply_feedback_review_update(operation['id'], changes, actor)
            elif operation['op'] == 'archive':
                body, status = _archive_feedback(operation['id'], operation['archived'], actor, operation['etag'])
            elif operation['op'] == 'dismiss_suggestion':
                body, status = dismiss_review_suggestion(
                    cosmos_feedback_container, 'feedback', operation['id'], operation['suggestion_id'], actor,
                    operation['etag'],
                )
            else:
                body, status = _delete_feedback(operation['id'], actor, operation['etag'])
            results.append(review_bulk_result(operation, body, status))

        summary = summarize_review_bulk_results(results)
        log_event('[FEEDBACK_REVIEW] Bulk feedback review applied.', {
            'actor_id': actor.get('id'),
            'operation_count': len(results),
            'succeeded': summary['succeeded'],
            'failed': summary['failed'],
        })
        return jsonify(summary), 200

    @bp.route("/api/admin/review/feedback/assist", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_assist():
        """Ask AI to suggest reviews for feedback records.

        Body: ``{"mode": "analyze" | "triage", "ids": [...]}``. ``analyze`` takes one record
        and returns a suggested review for the editor's unsaved draft; nothing is stored.
        ``triage`` takes up to 10 records and stores each suggestion on its record for a
        reviewer to apply or dismiss. The model never changes a review. Answers are never cached.
        """
        settings = get_settings()
        actor = _get_feedback_admin_actor()
        if not is_admin_review_assistant_enabled(settings):
            return review_assist_error_response(ReviewAssistError('review_assistant_disabled'), user_id=actor.get('id'))
        store = ReviewRecordStore(
            section='feedback',
            container=cosmos_feedback_container,
            replace=lambda record_id, mutate, base_item: replace_review_record(
                cosmos_feedback_container, record_id, mutate, base_item=base_item,
            ),
            conflict_error=ReviewRecordConflict,
        )
        return handle_review_assist_request(
            section='feedback',
            actor=actor,
            settings=settings,
            store=store,
            client_factory=lambda: _review_assist_client(settings),
        )

    @bp.route("/feedback/review/<feedbackId>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_get_single(feedbackId):
        """
        Fetch a single feedback item by its ID.
        Needed for the edit modal after switching to pagination.

        Also carries ``etag`` (send it back with a save) and the user's display name and email.
        """
        try:
            # Assuming feedbackId is the partition key as well
            feedback_doc = cosmos_feedback_container.read_item(
                item=feedbackId, partition_key=feedbackId
            )

            result = {
                "id": feedback_doc["id"],
                "userId": feedback_doc.get("userId"),
                "prompt": feedback_doc.get("prompt"),
                "aiResponse": feedback_doc.get("aiResponse"),
                "feedbackType": _normalize_feedback_type(feedback_doc.get("feedbackType")) or feedback_doc.get("feedbackType"),
                "reason": feedback_doc.get("reason"),
                "timestamp": feedback_doc.get("timestamp"),
                "adminReview": feedback_doc.get("adminReview", {}),
                "etag": feedback_doc.get("_etag"),
                "ai_suggestion": present_suggestion('feedback', feedback_doc),
            }
            result.update(serialize_archive_metadata(feedback_doc))
            _with_feedback_user_names([result])
            return jsonify(result)

        except CosmosResourceNotFoundError: # Import this if not already done
             return jsonify({"error": "Feedback item not found"}), 404
        except Exception as e:
             print(f"Error fetching single feedback item {feedbackId}: {e}")
             import traceback
             traceback.print_exc()
             return jsonify({"error": f"Failed to retrieve feedback item: {str(e)}"}), 500
        
    @bp.route("/feedback/review/<feedbackId>", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_update(feedbackId):
        """
        Patch admin fields: acknowledged, analysisNotes, responseToUser, actionTaken.

        The reviewer is recorded as adminReview.analyzedBy. ``etag``, when sent, must match
        the stored record, or 409 ``record_changed`` is returned. ``notify_user: true`` sends
        the user a notification with the response to their feedback.
        """
        data = request.get_json()
        body, status = _apply_feedback_review_update(feedbackId, data, _get_feedback_admin_actor())
        return jsonify(body), status

    @bp.route("/feedback/review/<feedbackId>/archive", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_archive(feedbackId):
        """Archive or unarchive a feedback review record.

        ``etag``, when sent, must match the stored record or 409 ``record_changed`` is returned.
        """
        data = request.get_json() or {}
        if not isinstance(data, dict):
            return jsonify({'error': 'The request body must be an object.'}), 400
        body, status = _archive_feedback(
            feedbackId,
            data.get('archived'),
            _get_feedback_admin_actor(),
            data.get('etag') if isinstance(data.get('etag'), str) else None,
        )
        return jsonify(body), status

    @bp.route("/feedback/review/<feedbackId>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_review_delete(feedbackId):
        """Permanently delete a feedback review record."""
        body, status = _delete_feedback(feedbackId, _get_feedback_admin_actor())
        return jsonify(body), status


    @bp.route("/feedback/retest/<feedbackId>", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def feedback_retest(feedbackId):
        """
        Admin retests the prompt. We basically re-run the prompt
        against the current AI chain to see if it's improved.
        """
        data = request.get_json()
        prompt = data.get("prompt")
        if not prompt:
            return jsonify({"error": "Missing prompt"}), 400

        try:
            retestResponse = run_prompt_against_gpt(prompt)
            return jsonify({"retestResponse": retestResponse})
        except Exception as e:
            return jsonify({"error": str(e)}), 500
        
    @bp.route("/feedback/my", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_my():
        """
        Returns the current user's feedback items with server-side pagination and filtering.
        Query Parameters:
            page (int): Page number (default: 1).
            page_size (int): Items per page (default: 10).
            type (str): Filter by feedbackType (Positive, Negative, Neutral).
            ack (str): Filter by acknowledged status ('true', 'false').
        """
        user_id = _get_feedback_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            filter_type, filter_ack_bool, _ = _parse_feedback_filters()
            items = _query_feedback_items(
                user_id=user_id,
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            paginated_items, page, page_size = _paginate_feedback_items(items, page, page_size)

            return jsonify({
                "feedback": paginated_items,
                "page": page,
                "page_size": page_size,
                "total_count": len(items)
            }), 200

        except Exception as e:
            print(f"Error in feedback_my: {str(e)}")
            return jsonify({"error": f"An error occurred while fetching your feedback: {str(e)}"}), 500

    @bp.route("/feedback/my/stats", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_my_stats():
        """Return aggregate feedback statistics for the current user."""
        user_id = _get_feedback_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            filter_type, filter_ack_bool, _ = _parse_feedback_filters()
            items = _query_feedback_items(
                user_id=user_id,
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            return jsonify(_build_feedback_stats(items))
        except Exception as e:
            return jsonify({"error": f"Failed to retrieve feedback stats: {str(e)}"}), 500

    @bp.route("/feedback/my/export", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def feedback_my_export():
        """Export the current user's feedback rows as CSV for the active filter set."""
        user_id = _get_feedback_session_user_id()
        if not user_id:
            return jsonify({"error": "No user ID found in session"}), 403

        try:
            filter_type, filter_ack_bool, _ = _parse_feedback_filters()
            items = _query_feedback_items(
                user_id=user_id,
                filter_type=filter_type,
                filter_ack_bool=filter_ack_bool,
            )
            return _build_feedback_export_response(items, 'my_feedback_export', include_user_id=False)
        except Exception as e:
            return jsonify({"error": f"Failed to export feedback: {str(e)}"}), 500


def run_prompt_against_gpt(prompt):
    # To do -  Replace with the real logic of your chat pipeline
    # Example: Access your LLM client and run the prompt
    # from your_llm_module import llm_client
    # response = llm_client.invoke(prompt)
    # return response.content
    print(f"Retesting prompt (stub): {prompt}")
    return f"[Retested with current model config] Mock AI response for: '{prompt}'"
