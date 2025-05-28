# route_backend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_public_workspace import *

def register_route_backend_public_workspaces(app):
    @app.route('/api/public_workspaces', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_list_public_workspaces():
        """
        Retrieve a list of all public workspaces.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        search_query = request.args.get('q')
        all_public_workspaces = search_public_workspaces(search_query)

        return jsonify(all_public_workspaces), 200


    @app.route('/api/public_workspaces/my', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_list_my_public_workspaces():
        """
        Retrieve a list of public workspaces that the current user manages.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        my_public_workspaces = get_user_public_workspaces(user_id)
        public_workspaces_data = map_public_workspace_list_for_frontend(my_public_workspaces, user_id)

        return jsonify(public_workspaces_data), 200


    @app.route('/api/public_workspaces', methods=['POST'])
    @login_required
    @user_required
    @create_public_workspace_role_required
    @enabled_required("enable_public_workspaces")
    def api_create_public_workspace():
        """
        Create a new public workspace.
        """
        data = request.get_json()
        
        if not data or not data.get('name'):
            return jsonify({'error': 'Public workspace name is required'}), 400

        name = data.get('name')
        description = data.get('description', '')
        
        try:
            workspace_doc = create_public_workspace(name, description)
            return jsonify(workspace_doc), 201
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/api/public_workspaces/<workspace_id>', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_workspace(workspace_id):
        """
        Retrieve details for a specific public workspace.
        """
        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Public workspace not found'}), 404

        return jsonify(workspace_doc), 200


    @app.route('/api/public_workspaces/<workspace_id>', methods=['PUT'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_update_public_workspace(workspace_id):
        """
        Update a public workspace's details.
        Only owners and admins can update workspace details.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin']:
            return jsonify({'error': 'You do not have permission to update this public workspace'}), 403

        data = request.get_json()
        
        if 'name' in data:
            workspace_doc['name'] = data['name']
        
        if 'description' in data:
            workspace_doc['description'] = data['description']
        
        workspace_doc['modifiedDate'] = datetime.utcnow().isoformat()
        
        cosmos_public_workspaces_container.replace_item(
            item=workspace_doc['id'], 
            body=workspace_doc
        )
        
        return jsonify(workspace_doc), 200


    @app.route('/api/public_workspaces/<workspace_id>', methods=['DELETE'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_delete_public_workspace(workspace_id):
        """
        Delete a public workspace.
        Only the owner can delete a workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Public workspace not found'}), 404

        if workspace_doc.get('owner', {}).get('id') != user_id:
            return jsonify({'error': 'Only the owner can delete this public workspace'}), 403

        try:
            delete_public_workspace(workspace_id)
            return jsonify({'success': True}), 200
        except Exception as e:
            return jsonify({'error': str(e)}), 500


    @app.route('/api/public_workspaces/<workspace_id>/set_active', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_set_active_public_workspace(workspace_id):
        """
        Set a public workspace as active for the current user.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Public workspace not found'}), 404

        update_active_public_workspace_for_user(workspace_id)
        
        return jsonify({'success': True}), 200


    @app.route('/api/public_workspaces/<workspace_id>/role', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_set_public_workspace_role(workspace_id):
        """
        Set a user's role in a public workspace.
        Only owners and admins can set roles.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Public workspace not found'}), 404

        current_role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if current_role not in ['Owner', 'Admin']:
            return jsonify({'error': 'You do not have permission to set roles in this public workspace'}), 403

        data = request.get_json()
        if not data or not data.get('userId') or not data.get('role'):
            return jsonify({'error': 'User ID and role are required'}), 400

        target_user_id = data.get('userId')
        new_role = data.get('role')
        
        # Cannot change owner's role
        if workspace_doc.get('owner', {}).get('id') == target_user_id:
            return jsonify({'error': 'Cannot change the owner\'s role'}), 400
            
        # Only owner can set admin role
        if new_role == 'Admin' and current_role != 'Owner':
            return jsonify({'error': 'Only the owner can set admin roles'}), 403

        # Remove from all role arrays
        if target_user_id in workspace_doc.get('admins', []):
            workspace_doc['admins'].remove(target_user_id)
        if target_user_id in workspace_doc.get('documentManagers', []):
            workspace_doc['documentManagers'].remove(target_user_id)

        # Add to appropriate role array
        if new_role == 'Admin':
            if 'admins' not in workspace_doc:
                workspace_doc['admins'] = []
            workspace_doc['admins'].append(target_user_id)
        elif new_role == 'DocumentManager':
            if 'documentManagers' not in workspace_doc:
                workspace_doc['documentManagers'] = []
            workspace_doc['documentManagers'].append(target_user_id)
        
        workspace_doc['modifiedDate'] = datetime.utcnow().isoformat()
        
        cosmos_public_workspaces_container.replace_item(
            item=workspace_doc['id'], 
            body=workspace_doc
        )
        
        return jsonify(workspace_doc), 200