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
from functions_appinsights import log_event

STATUS_PENDING = "pending"
STATUS_APPROVED = "approved"
STATUS_REJECTED = "rejected"
STATUS_ARCHIVED = "archived"
ALLOWED_STATUSES = {STATUS_PENDING, STATUS_APPROVED, STATUS_REJECTED, STATUS_ARCHIVED}


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
    return None


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
    template['updated_at'] = _utc_now()
    template['additional_settings'] = payload['additional_settings']

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
    return _sanitize_template(doc, include_internal=True)


def delete_agent_template(template_id: str) -> bool:
    try:
        cosmos_agent_templates_container.delete_item(item=template_id, partition_key=template_id)
        log_event("Agent template deleted", extra={"template_id": template_id})
        return True
    except exceptions.CosmosResourceNotFoundError:
        return False
    except Exception as exc:
        current_app.logger.error("Failed to delete agent template %s: %s", template_id, exc)
        raise
