# route_backend_governance.py

"""Admin API routes for governance policy management."""

from flask import jsonify, request, session

from functions_authentication import admin_required, get_current_user_id, login_required
from functions_governance import (
    DEFAULT_FEATURE_POLICIES,
    bootstrap_default_feature_policies,
    delete_item_policy,
    list_feature_policies,
    list_item_policies,
    upsert_feature_policy,
    upsert_item_policy,
)
from swagger_wrapper import get_auth_security, swagger_route


DEFAULT_GOVERNANCE_REVIEW_PAGE_SIZE = 25
MAX_GOVERNANCE_REVIEW_PAGE_SIZE = 100


def _normalize_actor_email() -> str:
    user = session.get("user") if isinstance(session.get("user"), dict) else {}
    return str(user.get("email") or "").strip()


def _sanitize_policy_payload(payload):
    if not isinstance(payload, dict):
        return {
            "allow_all": True,
            "allowed_users": [],
            "allowed_groups": [],
            "policy_id": "",
            "policy_name": "",
            "resource_label": "",
        }

    allowed_users = payload.get("allowed_users", [])
    if not isinstance(allowed_users, list):
        allowed_users = []

    allowed_groups = payload.get("allowed_groups", [])
    if not isinstance(allowed_groups, list):
        allowed_groups = []

    return {
        "allow_all": bool(payload.get("allow_all", True)),
        "allowed_users": allowed_users,
        "allowed_groups": allowed_groups,
        "policy_id": str(payload.get("policy_id") or "").strip(),
        "policy_name": str(payload.get("policy_name") or "").strip(),
        "resource_label": str(payload.get("resource_label") or "").strip(),
    }


def _normalize_review_pagination(args):
    try:
        page = int(str(args.get("page") or "1").strip())
    except (TypeError, ValueError):
        page = 1

    try:
        per_page = int(str(args.get("per_page") or str(DEFAULT_GOVERNANCE_REVIEW_PAGE_SIZE)).strip())
    except (TypeError, ValueError):
        per_page = DEFAULT_GOVERNANCE_REVIEW_PAGE_SIZE

    page = max(page, 1)
    per_page = max(1, min(per_page, MAX_GOVERNANCE_REVIEW_PAGE_SIZE))
    return page, per_page


def _build_item_policy_search_haystack(policy):
    return " ".join([
        str(policy.get("policy_id") or ""),
        str(policy.get("policy_name") or ""),
        str(policy.get("resource_label") or ""),
        str(policy.get("entity_type") or ""),
        str(policy.get("item_id") or ""),
        str(policy.get("allow_all") or ""),
        " ".join(str(value or "") for value in policy.get("allowed_users", []) if value),
        " ".join(str(value or "") for value in policy.get("allowed_groups", []) if value),
    ]).lower()


def register_route_backend_governance(bp):
    @bp.route('/api/admin/governance/policies', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_governance_policies_route():
        bootstrap_default_feature_policies()
        return jsonify({
            'features': list_feature_policies(),
            'feature_keys': list(DEFAULT_FEATURE_POLICIES.keys()),
        }), 200

    @bp.route('/api/admin/governance/policies/<feature_key>', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def update_governance_feature_policy_route(feature_key):
        if feature_key not in DEFAULT_FEATURE_POLICIES:
            return jsonify({'error': f"Unknown feature policy: {feature_key}"}), 400

        payload = _sanitize_policy_payload(request.get_json(silent=True) or {})
        actor_user_id = str(get_current_user_id() or '').strip()
        actor_email = _normalize_actor_email()

        updated = upsert_feature_policy(
            feature_key=feature_key,
            payload=payload,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
        )
        return jsonify({'policy': updated}), 200

    def _delete_governance_item_policy(entity_type, item_id, policy_id=None):
        normalized_entity_type = str(entity_type or '').strip().lower()
        normalized_item_id = str(item_id or '').strip()
        normalized_policy_id = str(policy_id or '').strip() or None
        if not normalized_entity_type or not normalized_item_id:
            return jsonify({'error': 'entity_type and item_id are required.'}), 400

        actor_user_id = str(get_current_user_id() or '').strip()
        actor_email = _normalize_actor_email()

        try:
            deleted = delete_item_policy(
                entity_type=normalized_entity_type,
                item_id=normalized_item_id,
                policy_id=normalized_policy_id,
                actor_user_id=actor_user_id,
                actor_email=actor_email,
            )
        except Exception:
            return jsonify({'error': 'Item governance policy not found.'}), 404

        return jsonify({'deleted': deleted}), 200

    @bp.route('/api/admin/governance/item-policies/<entity_type>/<item_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def delete_governance_item_policy_route(entity_type, item_id):
        return _delete_governance_item_policy(entity_type, item_id)

    @bp.route('/api/admin/governance/item-policies/<entity_type>/<item_id>/<policy_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def delete_governance_named_item_policy_route(entity_type, item_id, policy_id):
        return _delete_governance_item_policy(entity_type, item_id, policy_id)

    @bp.route('/api/admin/governance/item-policies', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def get_governance_item_policies_route():
        entity_type = str(request.args.get('entity_type') or '').strip() or None
        return jsonify({'item_policies': list_item_policies(entity_type=entity_type)}), 200

    @bp.route('/api/admin/governance/item-policies/review', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def review_governance_item_policies_route():
        entity_type = str(request.args.get('entity_type') or '').strip().lower() or None
        search = str(request.args.get('search') or '').strip().lower()
        page, per_page = _normalize_review_pagination(request.args)

        policies = list_item_policies(entity_type=entity_type)
        if search:
            policies = [
                policy for policy in policies
                if search in _build_item_policy_search_haystack(policy)
            ]

        total_items = len(policies)
        total_pages = (total_items + per_page - 1) // per_page if total_items else 1
        page = min(page, total_pages)
        offset = (page - 1) * per_page
        paged_policies = policies[offset:offset + per_page]

        return jsonify({
            'item_policies': paged_policies,
            'pagination': {
                'page': page,
                'per_page': per_page,
                'total_items': total_items,
                'total_pages': total_pages,
                'has_prev': page > 1,
                'has_next': page < total_pages,
            },
            'search': search,
            'entity_type': entity_type,
        }), 200

    @bp.route('/api/admin/governance/item-policies/<entity_type>/<item_id>', methods=['PUT'])
    @swagger_route(security=get_auth_security())
    @login_required
    @admin_required
    def update_governance_item_policy_route(entity_type, item_id):
        normalized_entity_type = str(entity_type or '').strip().lower()
        normalized_item_id = str(item_id or '').strip()
        if not normalized_entity_type or not normalized_item_id:
            return jsonify({'error': 'entity_type and item_id are required.'}), 400

        payload = _sanitize_policy_payload(request.get_json(silent=True) or {})
        actor_user_id = str(get_current_user_id() or '').strip()
        actor_email = _normalize_actor_email()

        updated = upsert_item_policy(
            entity_type=normalized_entity_type,
            item_id=normalized_item_id,
            payload=payload,
            actor_user_id=actor_user_id,
            actor_email=actor_email,
        )
        return jsonify({'policy': updated}), 200
