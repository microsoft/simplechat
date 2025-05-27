# route_backend_public_prompts.py

from config import *
from functions_authentication import *
from functions_public_workspace import *

@app.route('/api/public_workspaces/<workspace_id>/prompts', methods=['GET'])
@login_required
def api_get_public_prompts(workspace_id):
    try:
        # Check if the workspace exists
        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({"error": "Public workspace not found"}), 404
        
        # Anyone can view public workspace prompts
        
        query = "SELECT * FROM c WHERE c.public_workspace_id = @workspace_id AND c.type = 'public_prompt'"
        params = [{"name": "@workspace_id", "value": workspace_id}]
        
        prompts = list(cosmos_public_prompts_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        ))
        
        return jsonify({"prompts": prompts}), 200
        
    except Exception as e:
        print(f"Error retrieving public prompts: {str(e)}")
        return jsonify({"error": f"Failed to retrieve prompts: {str(e)}"}), 500


@app.route('/api/public_workspaces/<workspace_id>/prompts', methods=['POST'])
@login_required
def api_create_public_prompt(workspace_id):
    try:
        # Check if the workspace exists
        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({"error": "Public workspace not found"}), 404
        
        # Only owners, admins, and document managers can create prompts
        user_id = get_current_user_id()
        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if not role or role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({"error": "Insufficient permissions to create prompts in this workspace"}), 403
        
        # Extract prompt data from request body
        data = request.get_json()
        if not data or not data.get('name') or not data.get('content'):
            return jsonify({"error": "Missing required fields: 'name' and 'content'"}), 400
        
        # Create new prompt
        new_prompt_id = str(uuid.uuid4())
        now_str = datetime.utcnow().isoformat() + 'Z'
        
        prompt_doc = {
            "id": new_prompt_id,
            "public_workspace_id": workspace_id,
            "uploaded_by_user_id": user_id,
            "name": data['name'],
            "content": data['content'],
            "type": "public_prompt",
            "created_at": now_str,
            "updated_at": now_str
        }
        
        cosmos_public_prompts_container.create_item(prompt_doc)
        
        return jsonify({
            "message": "Prompt created successfully", 
            "prompt_id": new_prompt_id,
            "prompt": prompt_doc
        }), 201
        
    except Exception as e:
        print(f"Error creating public prompt: {str(e)}")
        return jsonify({"error": f"Failed to create prompt: {str(e)}"}), 500


@app.route('/api/public_workspaces/<workspace_id>/prompts/<prompt_id>', methods=['PUT'])
@login_required
def api_update_public_prompt(workspace_id, prompt_id):
    try:
        # Check if the workspace exists
        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({"error": "Public workspace not found"}), 404
        
        # Only owners, admins, and document managers can update prompts
        user_id = get_current_user_id()
        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if not role or role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({"error": "Insufficient permissions to update prompts in this workspace"}), 403
        
        # Extract prompt data from request body
        data = request.get_json()
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        # Try to retrieve the prompt
        try:
            prompt = cosmos_public_prompts_container.read_item(
                item=prompt_id,
                partition_key=prompt_id
            )
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({"error": "Prompt not found"}), 404
            
        # Verify the prompt belongs to the specified workspace
        if prompt.get("public_workspace_id") != workspace_id:
            return jsonify({"error": "Prompt does not belong to this workspace"}), 403
        
        # Update prompt fields
        now_str = datetime.utcnow().isoformat() + 'Z'
        
        if 'name' in data:
            prompt['name'] = data['name']
        if 'content' in data:
            prompt['content'] = data['content']
        
        prompt['updated_at'] = now_str
        
        # Save updated prompt
        cosmos_public_prompts_container.replace_item(item=prompt_id, body=prompt)
        
        return jsonify({
            "message": "Prompt updated successfully", 
            "prompt": prompt
        }), 200
        
    except Exception as e:
        print(f"Error updating public prompt: {str(e)}")
        return jsonify({"error": f"Failed to update prompt: {str(e)}"}), 500


@app.route('/api/public_workspaces/<workspace_id>/prompts/<prompt_id>', methods=['DELETE'])
@login_required
def api_delete_public_prompt(workspace_id, prompt_id):
    try:
        # Check if the workspace exists
        workspace_doc = find_public_workspace_by_id(workspace_id)
        if not workspace_doc:
            return jsonify({"error": "Public workspace not found"}), 404
        
        # Only owners, admins, and document managers can delete prompts
        user_id = get_current_user_id()
        role = get_user_role_in_public_workspace(workspace_doc, user_id)
        if not role or role not in ["Owner", "Admin", "DocumentManager"]:
            return jsonify({"error": "Insufficient permissions to delete prompts from this workspace"}), 403
        
        # Try to retrieve the prompt
        try:
            prompt = cosmos_public_prompts_container.read_item(
                item=prompt_id,
                partition_key=prompt_id
            )
        except exceptions.CosmosResourceNotFoundError:
            return jsonify({"error": "Prompt not found"}), 404
            
        # Verify the prompt belongs to the specified workspace
        if prompt.get("public_workspace_id") != workspace_id:
            return jsonify({"error": "Prompt does not belong to this workspace"}), 403
        
        # Delete the prompt
        cosmos_public_prompts_container.delete_item(item=prompt_id, partition_key=prompt_id)
        
        return jsonify({"message": "Prompt deleted successfully"}), 200
        
    except Exception as e:
        print(f"Error deleting public prompt: {str(e)}")
        return jsonify({"error": f"Failed to delete prompt: {str(e)}"}), 500