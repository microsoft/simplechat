# route_backend_public_prompts.py

from config import *

from functions_authentication import *
from functions_settings import *
from functions_public_workspaces import *
from functions_prompts import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_public_prompts(app):
    """
    Backend routes for public-workspace–scoped prompts management
    """

    @app.route('/api/public_prompts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_list_public_prompts():
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400
        ws = find_public_workspace_by_id(active_ws)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404
        if not get_user_role_in_public_workspace(ws, user_id):
            return jsonify({'error': 'Access denied'}), 403

        try:
            items, total, page, page_size = list_prompts(
                user_id=user_id,
                prompt_type='public_prompt',
                args=request.args,
                group_id=active_ws  # list_prompts uses this key generically
            )
            return jsonify({
                'prompts': items,
                'page': page,
                'page_size': page_size,
                'total_count': total
            }), 200
        except Exception as e:
            app.logger.error(f"Error listing public prompts: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @app.route('/api/public_prompts', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_create_public_prompt():
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400
        ws = find_public_workspace_by_id(active_ws)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404
        if not get_user_role_in_public_workspace(ws, user_id):
            return jsonify({'error': 'Access denied'}), 403

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
                group_id=active_ws
            )
            return jsonify(result), 201
        except Exception as e:
            app.logger.error(f"Error creating public prompt: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @app.route('/api/public_prompts/<prompt_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_get_public_prompt(prompt_id):
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400
        ws = find_public_workspace_by_id(active_ws)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404
        if not get_user_role_in_public_workspace(ws, user_id):
            return jsonify({'error': 'Access denied'}), 403

        try:
            item = get_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                prompt_type='public_prompt',
                group_id=active_ws
            )
            if not item:
                return jsonify({'error':'Not found'}), 404
            return jsonify(item), 200
        except Exception as e:
            app.logger.error(f"Error fetching public prompt {prompt_id}: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @app.route('/api/public_prompts/<prompt_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_update_public_prompt(prompt_id):
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400
        ws = find_public_workspace_by_id(active_ws)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404
        if not get_user_role_in_public_workspace(ws, user_id):
            return jsonify({'error': 'Access denied'}), 403

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
                group_id=active_ws
            )
            if not result:
                return jsonify({'error':'Not found'}), 404
            return jsonify(result), 200
        except Exception as e:
            app.logger.error(f"Error updating public prompt {prompt_id}: {e}")
            return jsonify({'error':'Unexpected error'}), 500

    @app.route('/api/public_prompts/<prompt_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_public_workspaces')
    def api_delete_public_prompt(prompt_id):
        user_id = get_current_user_id()
        settings = get_user_settings(user_id)
        active_ws = settings['settings'].get('activePublicWorkspaceOid')
        if not active_ws:
            return jsonify({'error': 'No active public workspace selected'}), 400
        ws = find_public_workspace_by_id(active_ws)
        if not ws:
            return jsonify({'error': 'Workspace not found'}), 404
        if not get_user_role_in_public_workspace(ws, user_id):
            return jsonify({'error': 'Access denied'}), 403

        try:
            success = delete_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                group_id=active_ws
            )
            if not success:
                return jsonify({'error':'Not found'}), 404
            return jsonify({'message':'Deleted'}), 200
        except Exception as e:
            app.logger.error(f"Error deleting public prompt {prompt_id}: {e}")
            return jsonify({'error':'Unexpected error'}), 500
