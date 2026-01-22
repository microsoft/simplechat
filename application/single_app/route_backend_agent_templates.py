"""Backend routes for agent template management."""

from flask import Blueprint, jsonify, request, session
from swagger_wrapper import swagger_route, get_auth_security

from functions_authentication import (
    admin_required,
    login_required,
    get_current_user_info,
)
from functions_agent_templates import (
    STATUS_APPROVED,
    validate_template_payload,
    list_agent_templates,
    create_agent_template,
    update_agent_template,
    approve_agent_template,
    reject_agent_template,
    delete_agent_template,
    get_agent_template,
)
from functions_settings import get_settings

bp_agent_templates = Blueprint('agent_templates', __name__)


def _feature_flags():
    settings = get_settings()
    enabled = settings.get('enable_agent_template_gallery', False)
    allow_submissions = settings.get('agent_templates_allow_user_submission', True)
    require_approval = settings.get('agent_templates_require_approval', True)
    return enabled, allow_submissions, require_approval, settings


def _is_admin() -> bool:
    user = session.get('user') or {}
    return 'Admin' in (user.get('roles') or [])


@bp_agent_templates.route('/api/agent-templates', methods=['GET'])
@login_required
@swagger_route(security=get_auth_security())
def list_public_agent_templates():
    enabled, _, _, _ = _feature_flags()
    if not enabled:
        return jsonify({'templates': []})
    templates = list_agent_templates(status=STATUS_APPROVED, include_internal=False)
    return jsonify({'templates': templates})


@bp_agent_templates.route('/api/agent-templates', methods=['POST'])
@login_required
@swagger_route(security=get_auth_security())
def submit_agent_template():
    enabled, allow_submissions, require_approval, settings = _feature_flags()
    if not enabled:
        return jsonify({'error': 'Agent template gallery is disabled.'}), 403
    if not settings.get('allow_user_agents') and not _is_admin():
        return jsonify({'error': 'Agent creation is disabled for your workspace.'}), 403
    if not allow_submissions and not _is_admin():
        return jsonify({'error': 'Template submissions are disabled for users.'}), 403

    data = request.get_json(silent=True) or {}
    payload = data.get('template') or data
    validation_error = validate_template_payload(payload)
    # validate_template_payload returns false if valid, returns the simple error otherwise.
    if validation_error:
        return jsonify({'error': validation_error}), 400

    is_admin_user = _is_admin()
    payload['source_agent_id'] = payload.get('source_agent_id') or data.get('source_agent_id')
    submission_scope = (
        payload.get('source_scope')
        or data.get('source_scope')
        or ('global' if is_admin_user else 'personal')
    )
    submission_scope = str(submission_scope).lower()
    payload['source_scope'] = submission_scope

    admin_context_submission = is_admin_user and submission_scope == 'global'
    auto_approve = admin_context_submission or not require_approval

    try:
        template = create_agent_template(payload, get_current_user_info(), auto_approve=auto_approve)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception:
        return jsonify({'error': 'Failed to submit template.'}), 500

    if not is_admin_user:
        for field in ('submission_notes', 'review_notes', 'rejection_reason', 'created_by_email'):
            template.pop(field, None)

    status_code = 201 if template.get('status') == STATUS_APPROVED else 202
    return jsonify({'template': template}), status_code


@bp_agent_templates.route('/api/admin/agent-templates', methods=['GET'])
@login_required
@admin_required
@swagger_route(security=get_auth_security())
def admin_list_agent_templates():
    status = request.args.get('status')
    if status == 'all':
        status = None
    templates = list_agent_templates(status=status, include_internal=True)
    return jsonify({'templates': templates})


@bp_agent_templates.route('/api/admin/agent-templates/<template_id>', methods=['GET'])
@login_required
@admin_required
@swagger_route(security=get_auth_security())
def admin_get_agent_template(template_id):
    template = get_agent_template(template_id)
    if not template:
        return jsonify({'error': 'Template not found.'}), 404
    return jsonify({'template': template})


@bp_agent_templates.route('/api/admin/agent-templates/<template_id>', methods=['PATCH'])
@login_required
@admin_required
@swagger_route(security=get_auth_security())
def admin_update_agent_template(template_id):
    payload = request.get_json(silent=True) or {}
    try:
        template = update_agent_template(template_id, payload)
    except ValueError as exc:
        return jsonify({'error': str(exc)}), 400
    except Exception:
        return jsonify({'error': 'Failed to update template.'}), 500

    if not template:
        return jsonify({'error': 'Template not found.'}), 404
    return jsonify({'template': template})


@bp_agent_templates.route('/api/admin/agent-templates/<template_id>/approve', methods=['POST'])
@login_required
@admin_required
@swagger_route(security=get_auth_security())
def admin_approve_agent_template(template_id):
    data = request.get_json(silent=True) or {}
    notes = data.get('notes')
    try:
        template = approve_agent_template(template_id, get_current_user_info(), notes)
    except Exception:
        return jsonify({'error': 'Failed to approve template.'}), 500

    if not template:
        return jsonify({'error': 'Template not found.'}), 404
    return jsonify({'template': template})


@bp_agent_templates.route('/api/admin/agent-templates/<template_id>/reject', methods=['POST'])
@login_required
@admin_required
@swagger_route(security=get_auth_security())
def admin_reject_agent_template(template_id):
    data = request.get_json(silent=True) or {}
    reason = (data.get('reason') or '').strip()
    if not reason:
        return jsonify({'error': 'A rejection reason is required.'}), 400
    notes = data.get('notes')
    try:
        template = reject_agent_template(template_id, get_current_user_info(), reason, notes)
    except Exception:
        return jsonify({'error': 'Failed to reject template.'}), 500

    if not template:
        return jsonify({'error': 'Template not found.'}), 404
    return jsonify({'template': template})


@bp_agent_templates.route('/api/admin/agent-templates/<template_id>', methods=['DELETE'])
@login_required
@admin_required
@swagger_route(security=get_auth_security())
def admin_delete_agent_template(template_id):
    try:
        deleted = delete_agent_template(template_id)
    except Exception:
        return jsonify({'error': 'Failed to delete template.'}), 500

    if not deleted:
        return jsonify({'error': 'Template not found.'}), 404
    return jsonify({'success': True})
