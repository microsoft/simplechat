# route_backend_public_prompts.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_public_workspace import *

def register_route_backend_public_prompts(app):
    @app.route('/api/public_prompts', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_prompts():
        """
        Return all prompts for the active public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        query = """
            SELECT * 
            FROM c 
            WHERE c.public_workspace_id = @public_workspace_id
            ORDER BY c.created_at DESC
        """
        params = [{"name": "@public_workspace_id", "value": active_public_workspace_id}]

        prompts = list(cosmos_public_prompts_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))

        return jsonify(prompts), 200


    @app.route('/api/public_prompts', methods=['POST'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_create_public_prompt():
        """
        Create a new prompt in the active public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to create prompts in this public workspace'}), 403

        data = request.get_json()
        if not data or not data.get('name') or not data.get('content'):
            return jsonify({'error': 'Prompt name and content are required'}), 400

        now = datetime.utcnow().isoformat() + 'Z'
        prompt_id = str(uuid.uuid4())

        prompt_doc = {
            "id": prompt_id,
            "public_workspace_id": active_public_workspace_id,
            "uploaded_by_user_id": user_id,
            "name": data["name"],
            "content": data["content"],
            "type": "public_prompt",
            "created_at": now,
            "updated_at": now
        }

        cosmos_public_prompts_container.create_item(prompt_doc)
        return jsonify(prompt_doc), 201


    @app.route('/api/public_prompts/<prompt_id>', methods=['GET'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_prompt(prompt_id):
        """
        Get a specific prompt from a public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        try:
            prompt_doc = cosmos_public_prompts_container.read_item(
                item=prompt_id,
                partition_key=prompt_id
            )
            
            if prompt_doc["public_workspace_id"] != active_public_workspace_id:
                return jsonify({'error': 'Prompt not found in active public workspace'}), 404
                
            return jsonify(prompt_doc), 200
            
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Prompt not found'}), 404


    @app.route('/api/public_prompts/<prompt_id>', methods=['PUT'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_update_public_prompt(prompt_id):
        """
        Update a prompt in a public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to update prompts in this public workspace'}), 403

        data = request.get_json()
        if not data or not data.get('name') or not data.get('content'):
            return jsonify({'error': 'Prompt name and content are required'}), 400

        try:
            prompt_doc = cosmos_public_prompts_container.read_item(
                item=prompt_id,
                partition_key=prompt_id
            )
            
            if prompt_doc["public_workspace_id"] != active_public_workspace_id:
                return jsonify({'error': 'Prompt not found in active public workspace'}), 404

            prompt_doc["name"] = data["name"]
            prompt_doc["content"] = data["content"]
            prompt_doc["updated_at"] = datetime.utcnow().isoformat() + 'Z'

            cosmos_public_prompts_container.replace_item(
                item=prompt_id,
                body=prompt_doc
            )
            
            return jsonify(prompt_doc), 200
            
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Prompt not found'}), 404


    @app.route('/api/public_prompts/<prompt_id>', methods=['DELETE'])
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_delete_public_prompt(prompt_id):
        """
        Delete a prompt from a public workspace.
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({'error': 'User not authenticated'}), 401

        user_settings = get_user_settings(user_id)
        active_public_workspace_id = user_settings["settings"].get("activePublicWorkspaceOid")

        if not active_public_workspace_id:
            return jsonify({'error': 'No active public workspace selected'}), 400

        workspace_doc = find_public_workspace_by_id(active_public_workspace_id)
        if not workspace_doc:
            return jsonify({'error': 'Active public workspace not found'}), 404

        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if role not in ['Owner', 'Admin', 'DocumentManager']:
            return jsonify({'error': 'You do not have permission to delete prompts in this public workspace'}), 403

        try:
            prompt_doc = cosmos_public_prompts_container.read_item(
                item=prompt_id,
                partition_key=prompt_id
            )
            
            if prompt_doc["public_workspace_id"] != active_public_workspace_id:
                return jsonify({'error': 'Prompt not found in active public workspace'}), 404

            cosmos_public_prompts_container.delete_item(
                item=prompt_id,
                partition_key=prompt_id
            )
            
            return jsonify({"deleted": True}), 200
            
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({'error': 'Prompt not found'}), 404