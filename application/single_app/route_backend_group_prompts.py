# route_backend_group_prompts.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_prompts import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_group_prompts(app):
    @app.route('/api/group_prompts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def get_group_prompts():
        user_id      = get_current_user_id()
        active_group = get_user_settings(user_id)["settings"].get("activeGroupOid")
        if not active_group:
            return jsonify({"error":"No active group selected"}), 400

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
            app.logger.error(f"Error fetching group prompts: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @app.route('/api/group_prompts', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def create_group_prompt():
        user_id      = get_current_user_id()
        active_group = get_user_settings(user_id)["settings"].get("activeGroupOid")
        if not active_group:
            return jsonify({"error":"No active group selected"}), 400

        data    = request.get_json() or {}
        name    = data.get("name","").strip()
        content = data.get("content","")
        if not name or not content:
            return jsonify({"error":"Missing 'name' or 'content'"}), 400

        try:
            result = create_prompt_doc(
                name=name,
                content=content,
                prompt_type="group_prompt",
                user_id=user_id,
                group_id=active_group
            )
            return jsonify(result), 201
        except Exception as e:
            app.logger.error(f"Error creating group prompt: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @app.route('/api/group_prompts/<prompt_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def get_group_prompt(prompt_id):
        user_id      = get_current_user_id()
        active_group = get_user_settings(user_id)["settings"].get("activeGroupOid")
        if not active_group:
            return jsonify({"error":"No active group selected"}), 400

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
            app.logger.error(f"Unexpected error getting group prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @app.route('/api/group_prompts/<prompt_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def update_group_prompt(prompt_id):
        user_id      = get_current_user_id()
        active_group = get_user_settings(user_id)["settings"].get("activeGroupOid")
        if not active_group:
            return jsonify({"error":"No active group selected"}), 400

        data = request.get_json() or {}
        updates = {}
        if "name" in data:
            if not isinstance(data["name"], str) or not data["name"].strip():
                return jsonify({"error":"Invalid 'name' provided"}), 400
            updates["name"] = data["name"].strip()
        if "content" in data:
            if not isinstance(data["content"], str):
                return jsonify({"error":"Invalid 'content' provided"}), 400
            updates["content"] = data["content"]
        if not updates:
            return jsonify({"error":"No fields provided for update"}), 400

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
            app.logger.error(f"Unexpected error updating group prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @app.route('/api/group_prompts/<prompt_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def delete_group_prompt(prompt_id):
        user_id      = get_current_user_id()
        active_group = get_user_settings(user_id)["settings"].get("activeGroupOid")
        if not active_group:
            return jsonify({"error":"No active group selected"}), 400

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
            app.logger.error(f"Unexpected error deleting group prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500
