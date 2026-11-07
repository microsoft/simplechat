# route_backend_group_prompts.py

from config import *
from flask import current_app

from functions_authentication import *
from functions_group import require_active_group
from functions_settings import *
from functions_prompts import *
from swagger_wrapper import swagger_route, get_auth_security


# Every group role may read prompts.
GROUP_PROMPT_MEMBER_ROLES = ("Owner", "Admin", "DocumentManager", "User")
# Prompt writes are limited to managers, mirroring V1's canManageGroupPrompts()
# and the policy public prompts already enforce. Reads keep the four-role default.
GROUP_PROMPT_WRITE_ROLES = ("Owner", "Admin", "DocumentManager")


def _get_active_group_or_error(user_id, allowed_roles=GROUP_PROMPT_MEMBER_ROLES):
    try:
        return require_active_group(
            user_id,
            allowed_roles=allowed_roles,
        ), None
    except ValueError:
        return None, (jsonify({"error": "No active group selected"}), 400)
    except LookupError:
        return None, (jsonify({"error": "Active group not found"}), 404)
    except PermissionError:
        # Tell a member who lacks the role apart from a non-member. Checking
        # membership directly, rather than matching the exception's wording,
        # keeps this correct if that wording ever changes.
        if tuple(allowed_roles) != GROUP_PROMPT_MEMBER_ROLES and _is_active_group_member(user_id):
            return None, (jsonify({
                "error": "Only group owners, admins, and document managers can change group prompts",
            }), 403)
        return None, (jsonify({"error": "You are not a member of the active group"}), 403)


def _is_active_group_member(user_id):
    try:
        require_active_group(user_id, allowed_roles=GROUP_PROMPT_MEMBER_ROLES)
    except (ValueError, LookupError, PermissionError):
        return False
    return True


def register_route_backend_group_prompts(bp):
    @bp.route('/api/group_prompts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def get_group_prompts():
        user_id = get_current_user_id()
        active_group, error_response = _get_active_group_or_error(user_id)
        if error_response:
            return error_response

        try:
            items, total, page, page_size = list_prompts(
                user_id=user_id,
                prompt_type="group_prompt",
                args=request.args,
                group_id=active_group
            )
            return jsonify({
                "prompts":     items,
                "page":        page,
                "page_size":   page_size,
                "total_count": total
            }), 200
        except Exception as e:
            current_app.logger.error(f"Error fetching group prompts: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @bp.route('/api/group_prompts', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def create_group_prompt():
        user_id = get_current_user_id()
        active_group, error_response = _get_active_group_or_error(user_id, allowed_roles=GROUP_PROMPT_WRITE_ROLES)
        if error_response:
            return error_response

        data    = request.get_json() or {}
        name    = data.get("name","").strip()
        content = data.get("content","")
        if not name or not content:
            return jsonify({"error":"Missing 'name' or 'content'"}), 400

        options, option_error = build_prompt_create_options(data)
        if option_error:
            return jsonify({"error": option_error}), 400

        try:
            result = create_prompt_doc(
                name=name,
                content=content,
                prompt_type="group_prompt",
                user_id=user_id,
                group_id=active_group,
                **options
            )
            return jsonify(result), 201
        except Exception as e:
            current_app.logger.error(f"Error creating group prompt: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @bp.route('/api/group_prompts/<prompt_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def get_group_prompt(prompt_id):
        user_id = get_current_user_id()
        active_group, error_response = _get_active_group_or_error(user_id)
        if error_response:
            return error_response

        try:
            item = get_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                prompt_type="group_prompt",
                group_id=active_group
            )
            if not item:
                return jsonify({"error":"Prompt not found or access denied"}), 404
            return jsonify(item), 200
        except Exception as e:
            current_app.logger.error(f"Unexpected error getting group prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @bp.route('/api/group_prompts/<prompt_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def update_group_prompt(prompt_id):
        user_id = get_current_user_id()
        active_group, error_response = _get_active_group_or_error(user_id, allowed_roles=GROUP_PROMPT_WRITE_ROLES)
        if error_response:
            return error_response

        data = request.get_json() or {}
        updates, error = build_prompt_updates(data)
        if error:
            return jsonify({"error": error}), 400

        try:
            result = update_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                prompt_type="group_prompt",
                updates=updates,
                group_id=active_group
            )
            if not result:
                return jsonify({"error":"Prompt not found or access denied"}), 404
            return jsonify(result), 200
        except Exception as e:
            current_app.logger.error(f"Unexpected error updating group prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @bp.route('/api/group_prompts/<prompt_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def delete_group_prompt(prompt_id):
        user_id = get_current_user_id()
        active_group, error_response = _get_active_group_or_error(user_id, allowed_roles=GROUP_PROMPT_WRITE_ROLES)
        if error_response:
            return error_response

        try:
            success = delete_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                group_id=active_group
            )
            if not success:
                return jsonify({"error":"Prompt not found or access denied"}), 404
            return jsonify({"message":"Prompt deleted successfully"}), 200
        except Exception as e:
            current_app.logger.error(f"Unexpected error deleting group prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500
