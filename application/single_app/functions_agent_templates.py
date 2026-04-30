# functions_agent_templates.py
"""Agent template helper functions.

This module centralizes CRUD operations for agent templates stored in the
Cosmos DB `agent_templates` container. Templates are surfaced as reusable
starting points inside the agent builder UI.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional

from azure.cosmos import exceptions
from flask import current_app

from config import cosmos_agent_templates_container
from functions_activity_logging import (
    log_agent_template_submission,
    log_agent_template_approval,
    log_agent_template_rejection,
    log_agent_template_deletion,
)
from functions_appinsights import log_event
from functions_notifications import create_notification, delete_notifications_by_metadata

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_ARCHIVED = "archived"
ALLOWED_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_ARCHIVED}

TEMPLATE_APPROVAL_ADMIN_NOTIFICATION_TYPES = ['agent_template_pending_admin']

_MAX_TEMPLATE_FIELD_LENGTHS = {
    "title": 200,
    "display_name": 200,
    "helper_text": 140,
    "description": 2000,
    "instructions": 30000,
    "template_key": 128,
}

_MAX_TEMPLATE_LIST_ITEM_LENGTHS = {
    "tags": 64,
    "actions_to_load": 128,
}


def _utc_now() -> str:
    return datetime.utcnow().isoformat()


def _slugify(text: str) -> str:
    if not text:
        return "template"
    slug = text.strip().lower()
    allowed = "abcdefghijklmnopqrstuvwxyz0123456789-_"
    slug = slug.replace(" ", "-")
    slug = ''.join(ch for ch in slug if ch in allowed)
    slug = slug.strip('-')
    return slug or "template"


def _normalize_helper_text(description: str, explicit_helper: Optional[str]) -> str:
    helper = explicit_helper or description or ""
    helper = helper.strip()
    if len(helper) <= 140:
        return helper
    return helper[:137].rstrip() + "..."


def _parse_additional_settings(value: Any) -> Dict[str, Any]:
    if not value:
        return {}
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        trimmed = value.strip()
        if not trimmed:
            return {}
        try:
            return json.loads(trimmed)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON for additional_settings: {exc}") from exc
    raise ValueError("additional_settings must be a JSON string or object")


def _strip_metadata(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v for k, v in doc.items() if not k.startswith('_')}


def _serialize_additional_settings(raw: Any) -> str:
    try:
        parsed = _parse_additional_settings(raw)
    except ValueError:
        return raw if isinstance(raw, str) else ""
    if not parsed:
        return ""
    return json.dumps(parsed, indent=2, sort_keys=True)


def _sanitize_template(doc: Dict[str, Any], include_internal: bool = False) -> Dict[str, Any]:
    cleaned = _strip_metadata(doc)
    cleaned.setdefault('actions_to_load', [])
    cleaned['actions_to_load'] = [a for a in cleaned['actions_to_load'] if a]
    cleaned.setdefault('tags', [])
    cleaned['tags'] = [str(tag)[:64] for tag in cleaned['tags']]
    cleaned['helper_text'] = _normalize_helper_text(
        cleaned.get('description', ''),
        cleaned.get('helper_text')
    )
    cleaned['additional_settings'] = _serialize_additional_settings(cleaned.get('additional_settings'))
    cleaned.setdefault('status', STATUS_PENDING)
    cleaned.setdefault('title', cleaned.get('display_name') or 'Agent Template')
    cleaned.setdefault('template_key', _slugify(cleaned['title']))

    if not include_internal:
        for field in ['submission_notes', 'review_notes', 'rejection_reason', 'created_by', 'created_by_email']:
            cleaned.pop(field, None)

    return cleaned


def _template_detail_link(doc: Dict[str, Any]) -> str:
    scope = (doc.get('source_scope') or 'personal').lower()
    if scope == 'global':
        return '/approvals#agent-template-approvals'
    if scope == 'group':
        return '/group_workspaces'
    return '/workspace'


def _create_submitter_notification(
    doc: Dict[str, Any],
    notification_type: str,
    title: str,
    message: str,
    metadata: Optional[Dict[str, Any]] = None
) -> None:
    submitter_id = doc.get('created_by')
    if not submitter_id:
        return

    create_notification(
        user_id=submitter_id,
        notification_type=notification_type,
        title=title,
        message=message,
        link_url=_template_detail_link(doc),
        link_context={
            'template_id': doc.get('id'),
            'source_scope': doc.get('source_scope')
        },
        metadata={
            'template_id': doc.get('id'),
            'template_title': doc.get('title') or doc.get('display_name'),
            'source_scope': doc.get('source_scope')
        } | (metadata or {})
    )


def _submitter_info(doc: Dict[str, Any]) -> Dict[str, Any]:
    return {
        'userId': doc.get('created_by'),
        'email': doc.get('created_by_email'),
        'displayName': doc.get('created_by_name'),
    }


def _create_pending_notifications(doc: Dict[str, Any]) -> None:
    title = doc.get('title') or doc.get('display_name') or 'Agent Template'
    submitter_name = doc.get('created_by_name') or 'A user'

    create_notification(
        notification_type='agent_template_pending_admin',
        title=f'Template Approval Required: {title}',
        message=f"{submitter_name} submitted '{title}' for review.",
        link_url='/approvals#agent-template-approvals',
        link_context={
            'template_id': doc.get('id')
        },
        metadata={
            'template_id': doc.get('id'),
            'template_title': title,
            'submitter_email': doc.get('created_by_email'),
            'submitter_name': submitter_name
        },
        assignment={
            'roles': ['Admin']
        }
    )

    _create_submitter_notification(
        doc,
        notification_type='agent_template_pending_submitter',
        title=f'Template Submitted: {title}',
        message=(
            f"Your template '{title}' was submitted for admin review. "
            'You will receive another notification when a decision is made.'
        )
    )


def _clear_pending_admin_notifications(template_id: str) -> None:
    delete_notifications_by_metadata(
        metadata_filters={'template_id': template_id},
        notification_types=TEMPLATE_APPROVAL_ADMIN_NOTIFICATION_TYPES
    )


def _validate_template_lengths(payload: Dict[str, Any]) -> None:
    for field, max_len in _MAX_TEMPLATE_FIELD_LENGTHS.items():
        value = payload.get(field, "")
        if isinstance(value, str) and len(value) > max_len:
            raise ValueError(f"{field} exceeds maximum length of {max_len}.")

    for field, max_len in _MAX_TEMPLATE_LIST_ITEM_LENGTHS.items():
        values = payload.get(field) or []
        if not isinstance(values, list):
            continue
        for item in values:
            if isinstance(item, str) and len(item) > max_len:
                raise ValueError(f"{field} entries exceed maximum length of {max_len}.")


def validate_template_payload(payload: Dict[str, Any]) -> Optional[str]:
    if not isinstance(payload, dict):
        return "Template payload must be an object"
    if not (payload.get('display_name') or payload.get('title')):
        return "Display name is required"
    if not payload.get('description'):
        return "Description is required"
    if not payload.get('instructions'):
        return "Instructions are required"
    if payload.get('additional_settings'):
        try:
            _parse_additional_settings(payload['additional_settings'])
        except ValueError as exc:
            return str(exc)
    # Return false if valid to keep with consistency of returning bools or values because we return the error.
    return False


def list_agent_templates(status: Optional[str] = None, include_internal: bool = False) -> List[Dict[str, Any]]:
    query = "SELECT * FROM c"
    parameters = []
    if status:
        query += " WHERE c.status = @status"
        parameters.append({"name": "@status", "value": status})

    try:
        items = list(
            cosmos_agent_templates_container.query_items(
                query=query,
                parameters=parameters or None,
                enable_cross_partition_query=True,
            )
        )
    except Exception as exc:
        current_app.logger.error("Failed to list agent templates: %s", exc)
        return []

    sanitized = [_sanitize_template(item, include_internal) for item in items]
    sanitized.sort(key=lambda tpl: tpl.get('title', '').lower())
    return sanitized


def get_agent_template(template_id: str) -> Optional[Dict[str, Any]]:
    try:
        doc = cosmos_agent_templates_container.read_item(item=template_id, partition_key=template_id)
        return _sanitize_template(doc, include_internal=True)
    except exceptions.CosmosResourceNotFoundError:
        return None
    except Exception as exc:
        current_app.logger.error("Failed to fetch agent template %s: %s", template_id, exc)
        return None


def _base_template_from_payload(payload: Dict[str, Any], user_info: Optional[Dict[str, Any]], auto_approve: bool) -> Dict[str, Any]:
    now = _utc_now()
    title = payload.get('title') or payload.get('display_name') or 'Agent Template'
    helper_text = _normalize_helper_text(payload.get('description', ''), payload.get('helper_text'))
    additional_settings = _parse_additional_settings(payload.get('additional_settings'))
    tags = payload.get('tags') or []
    tags = [str(tag)[:64] for tag in tags]

    actions = [str(action) for action in (payload.get('actions_to_load') or []) if action]

    template = {
        'id': payload.get('id') or str(uuid.uuid4()),
        'template_key': payload.get('template_key') or f"{_slugify(title)}-{uuid.uuid4().hex[:6]}",
        'title': title,
        'display_name': payload.get('display_name') or title,
        'helper_text': helper_text,
        'description': payload.get('description', ''),
        'instructions': payload.get('instructions', ''),
        'additional_settings': additional_settings,
        'actions_to_load': actions,
        'tags': tags,
        'status': STATUS_APPROVED if auto_approve else STATUS_PENDING,
        'created_at': now,
        'updated_at': now,
        'created_by': user_info.get('userId') if user_info else None,
        'created_by_name': user_info.get('displayName') if user_info else None,
        'created_by_email': user_info.get('email') if user_info else None,
        'submission_notes': payload.get('submission_notes'),
        'source_agent_id': payload.get('source_agent_id'),
        'source_scope': payload.get('source_scope') or 'personal',
        'approved_by': user_info.get('userId') if auto_approve and user_info else None,
        'approved_at': now if auto_approve else None,
        'review_notes': payload.get('review_notes'),
        'rejection_reason': None,
    }
    return template


def create_agent_template(payload: Dict[str, Any], user_info: Optional[Dict[str, Any]], auto_approve: bool = False) -> Dict[str, Any]:
    template = _base_template_from_payload(payload, user_info, auto_approve)
    try:
        cosmos_agent_templates_container.upsert_item(template)
    except Exception as exc:
        current_app.logger.error("Failed to save agent template: %s", exc)
        raise

    log_event(
        "Agent template submitted",
        extra={
            "template_id": template['id'],
            "status": template['status'],
            "created_by": template.get('created_by'),
        },
    )

    if not auto_approve:
        _create_pending_notifications(template)

    log_agent_template_submission(
        user_id=template.get('created_by') or 'unknown',
        template_id=template['id'],
        template_name=template.get('title') or template.get('display_name') or 'Agent Template',
        template_display_name=template.get('display_name'),
        scope=template.get('source_scope') or 'personal',
        template_status=template.get('status'),
        submitter=_submitter_info(template),
    )

    return _sanitize_template(template, include_internal=True)


def update_agent_template(template_id: str, updates: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    doc = get_agent_template(template_id)
    if not doc:
        return None

    mutable_fields = {
        'title', 'display_name', 'helper_text', 'description', 'instructions',
        'additional_settings', 'actions_to_load', 'tags', 'status'
    }
    payload = {k: v for k, v in updates.items() if k in mutable_fields}

    if 'additional_settings' in payload:
        payload['additional_settings'] = _parse_additional_settings(payload['additional_settings'])
    else:
        payload['additional_settings'] = _parse_additional_settings(doc.get('additional_settings'))

    if 'tags' in payload:
        payload['tags'] = [str(tag)[:64] for tag in payload['tags']]

    if 'status' in payload:
        status = payload['status']
        if status not in ALLOWED_STATUSES:
            raise ValueError("Invalid template status")
    else:
        payload['status'] = doc.get('status', STATUS_PENDING)

    template = {
        **doc,
        **payload,
    }
    template['helper_text'] = _normalize_helper_text(
        template.get('description', ''),
        template.get('helper_text')
    )
    template['updated_at'] = _utc_now()
    template['additional_settings'] = payload['additional_settings']
    _validate_template_lengths(template)

    try:
        cosmos_agent_templates_container.upsert_item(template)
    except Exception as exc:
        current_app.logger.error("Failed to update agent template %s: %s", template_id, exc)
        raise

    return _sanitize_template(template, include_internal=True)


def approve_agent_template(template_id: str, approver_info: Dict[str, Any], notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    doc = get_agent_template(template_id)
    if not doc:
        return None
    doc['additional_settings'] = _parse_additional_settings(doc.get('additional_settings'))
    doc['status'] = STATUS_APPROVED
    doc['approved_by'] = approver_info.get('userId')
    doc['approved_at'] = _utc_now()
    doc['review_notes'] = notes
    doc['rejection_reason'] = None
    doc['updated_at'] = doc['approved_at']

    try:
        cosmos_agent_templates_container.upsert_item(doc)
    except Exception as exc:
        current_app.logger.error("Failed to approve agent template %s: %s", template_id, exc)
        raise

    log_event(
        "Agent template approved",
        extra={"template_id": template_id, "approved_by": doc['approved_by']},
    )

    _clear_pending_admin_notifications(template_id)
    _create_submitter_notification(
        doc,
        notification_type='agent_template_approved',
        title=f"Template Approved: {doc.get('title') or doc.get('display_name') or 'Agent Template'}",
        message=(
            f"Your template '{doc.get('title') or doc.get('display_name') or 'Agent Template'}' "
            f"was approved by {approver_info.get('displayName') or approver_info.get('email') or 'an admin'}."
        ),
        metadata={
            'review_notes': notes
        }
    )

    log_agent_template_approval(
        user_id=approver_info.get('userId') or 'unknown',
        template_id=template_id,
        template_name=doc.get('title') or doc.get('display_name') or 'Agent Template',
        template_display_name=doc.get('display_name'),
        scope=doc.get('source_scope') or 'personal',
        template_status=doc.get('status'),
        approver=approver_info,
        submitter=_submitter_info(doc),
        review_notes=notes,
    )

    return _sanitize_template(doc, include_internal=True)


def reject_agent_template(template_id: str, approver_info: Dict[str, Any], reason: str, notes: Optional[str] = None) -> Optional[Dict[str, Any]]:
    doc = get_agent_template(template_id)
    if not doc:
        return None
    doc['additional_settings'] = _parse_additional_settings(doc.get('additional_settings'))
    doc['status'] = STATUS_REJECTED
    doc['approved_by'] = approver_info.get('userId')
    doc['approved_at'] = _utc_now()
    doc['review_notes'] = notes
    doc['rejection_reason'] = reason
    doc['updated_at'] = doc['approved_at']

    try:
        cosmos_agent_templates_container.upsert_item(doc)
    except Exception as exc:
        current_app.logger.error("Failed to reject agent template %s: %s", template_id, exc)
        raise

    log_event(
        "Agent template rejected",
        extra={"template_id": template_id, "approved_by": doc['approved_by']},
    )

    _clear_pending_admin_notifications(template_id)
    _create_submitter_notification(
        doc,
        notification_type='agent_template_rejected',
        title=f"Template Declined: {doc.get('title') or doc.get('display_name') or 'Agent Template'}",
        message=(
            f"Your template '{doc.get('title') or doc.get('display_name') or 'Agent Template'}' "
            f"was declined by {approver_info.get('displayName') or approver_info.get('email') or 'an admin'}. "
            f"Reason provided: {reason}"
        ),
        metadata={
            'rejection_reason': reason,
            'review_notes': notes
        }
    )

    log_agent_template_rejection(
        user_id=approver_info.get('userId') or 'unknown',
        template_id=template_id,
        template_name=doc.get('title') or doc.get('display_name') or 'Agent Template',
        template_display_name=doc.get('display_name'),
        scope=doc.get('source_scope') or 'personal',
        template_status=doc.get('status'),
        approver=approver_info,
        submitter=_submitter_info(doc),
        review_reason=reason,
        review_notes=notes,
    )

    return _sanitize_template(doc, include_internal=True)


def delete_agent_template(template_id: str, actor_info: Optional[Dict[str, Any]] = None) -> bool:
    try:
        doc = get_agent_template(template_id)
        if not doc:
            return False

        cosmos_agent_templates_container.delete_item(item=template_id, partition_key=template_id)
        _clear_pending_admin_notifications(template_id)

        if actor_info:
            actor_name = actor_info.get('displayName') or actor_info.get('email') or 'an admin'
            _create_submitter_notification(
                doc,
                notification_type='agent_template_deleted',
                title=f"Template Removed: {doc.get('title') or doc.get('display_name') or 'Agent Template'}",
                message=(
                    f"Your template '{doc.get('title') or doc.get('display_name') or 'Agent Template'}' "
                    f"was removed by {actor_name}."
                ),
                metadata={
                    'removed_by': actor_name,
                    'previous_status': doc.get('status')
                }
            )

        log_agent_template_deletion(
            user_id=(actor_info or {}).get('userId') or doc.get('created_by') or 'unknown',
            template_id=template_id,
            template_name=doc.get('title') or doc.get('display_name') or 'Agent Template',
            template_display_name=doc.get('display_name'),
            scope=doc.get('source_scope') or 'personal',
            template_status=doc.get('status'),
            actor=actor_info,
            submitter=_submitter_info(doc),
        )

        log_event("Agent template deleted", extra={"template_id": template_id})
        return True
    except exceptions.CosmosResourceNotFoundError:
        return False
    except Exception as exc:
        current_app.logger.error("Failed to delete agent template %s: %s", template_id, exc)
        raise
