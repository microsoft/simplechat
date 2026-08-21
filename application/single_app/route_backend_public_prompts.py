# route_backend_public_prompts.py

from config import *
from flask import current_app

from functions_authentication import *
from functions_settings import *
from functions_public_workspaces import *
from functions_prompts import *
from swagger_wrapper import swagger_route, get_auth_security


def _get_active_public_workspace_or_error(
    user_id,
    allowed_roles=("Owner", "Admin", "DocumentManager", "User"),
):
    try:
        return require_active_public_workspace(
            user_id,
            allowed_roles=allowed_roles,
        ), None
    except ValueError:
        return None, (jsonify({'error': 'No active public workspace selected'}), 400)
    except LookupError:
        return None, (jsonify({'error': 'Workspace not found'}), 404)
    except PermissionError:
        return None, (jsonify({'error': 'Access denied'}), 403)

def register_route_backend_public_prompts(bp):
    """
    Backend routes for public-workspace–scoped prompts management
    """

    @bp.route('/api/public_prompts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_list_public_prompts():
        user_id = get_current_user_id()
        active_workspace_context, error_response = _get_active_public_workspace_or_error(user_id)
        if error_response:
            return error_response
        active_ws, _, _ = active_workspace_context

        try:
            items, total, page, page_size = list_prompts(
                user_id=user_id,
                prompt_type='public_prompt',
                args=request.args,
                public_workspace_id=active_ws
            )
            return jsonify({
                'prompts': items,
                'page': page,
                'page_size': page_size,
                'total_count': total
            }), 200
        except Exception as e:
            current_app.logger.error(f"Error listing public prompts: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @bp.route('/api/public_prompts', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_create_public_prompt():
        user_id = get_current_user_id()
        active_workspace_context, error_response = _get_active_public_workspace_or_error(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
        )
        if error_response:
            return error_response
        active_ws, _, _ = active_workspace_context

        data = request.get_json() or {}
        name = data.get('name','').strip()
        content = data.get('content','').strip()
        if not name or not content:
            return jsonify({'error': "Missing 'name' or 'content'"}), 400

        try:
            result = create_prompt_doc(
                name=name,
                content=content,
                prompt_type='public_prompt',
                user_id=user_id,
                public_workspace_id=active_ws
            )
            return jsonify(result), 201
        except Exception as e:
            current_app.logger.error(f"Error creating public prompt: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @bp.route('/api/public_prompts/<prompt_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_get_public_prompt(prompt_id):
        user_id = get_current_user_id()
        active_workspace_context, error_response = _get_active_public_workspace_or_error(user_id)
        if error_response:
            return error_response
        active_ws, _, _ = active_workspace_context

        try:
            item = get_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                prompt_type='public_prompt',
                public_workspace_id=active_ws
            )
            if not item:
                return jsonify({'error':'Not found'}), 404
            return jsonify(item), 200
        except Exception as e:
            current_app.logger.error(f"Error fetching public prompt {prompt_id}: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @bp.route('/api/public_prompts/<prompt_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_update_public_prompt(prompt_id):
        user_id = get_current_user_id()
        active_workspace_context, error_response = _get_active_public_workspace_or_error(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
        )
        if error_response:
            return error_response
        active_ws, _, _ = active_workspace_context

        data = request.get_json() or {}
        updates = {}
        if 'name' in data:
            if not isinstance(data['name'], str) or not data['name'].strip():
                return jsonify({'error':'Invalid name'}), 400
            updates['name'] = data['name'].strip()
        if 'content' in data:
            if not isinstance(data['content'], str):
                return jsonify({'error':'Invalid content'}), 400
            updates['content'] = data['content']
        if not updates:
            return jsonify({'error':'No updates'}), 400

        try:
            result = update_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                prompt_type='public_prompt',
                updates=updates,
                public_workspace_id=active_ws
            )
            if not result:
                return jsonify({'error':'Not found'}), 404
            return jsonify(result), 200
        except Exception as e:
            current_app.logger.error(f"Error updating public prompt {prompt_id}: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @bp.route('/api/public_prompts/<prompt_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_delete_public_prompt(prompt_id):
        user_id = get_current_user_id()
        active_workspace_context, error_response = _get_active_public_workspace_or_error(
            user_id,
            allowed_roles=("Owner", "Admin", "DocumentManager"),
        )
        if error_response:
            return error_response
        active_ws, _, _ = active_workspace_context

        try:
            success = delete_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                public_workspace_id=active_ws
            )
            if not success:
                return jsonify({'error':'Not found'}), 404
            return jsonify({'message':'Deleted'}), 200
        except Exception as e:
            current_app.logger.error(f"Error deleting public prompt {prompt_id}: {e}")
            return jsonify({'error':'Unexpected error'}), 500
