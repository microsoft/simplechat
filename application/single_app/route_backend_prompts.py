# route_backend_prompts.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_prompts import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_prompts(app):
    @app.route('/api/prompts', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def get_prompts():
        user_id = get_current_user_id()
        try:
            items, total, page, page_size = list_prompts(
                user_id=user_id,
                prompt_type="user_prompt",
                args=request.args
            )
            return jsonify({
                "prompts":     items,
                "page":        page,
                "page_size":   page_size,
                "total_count": total
            }), 200
        except Exception as e:
            app.logger.error(f"Error fetching prompts: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @app.route('/api/prompts', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def create_prompt():
        user_id = get_current_user_id()
        data = request.get_json() or {}
        name    = data.get("name", "").strip()
        content = data.get("content", "")
        if not name:
            return jsonify({"error":"Missing or invalid 'name'"}), 400
        if not content:
            return jsonify({"error":"Missing or invalid 'content'"}), 400

        try:
            result = create_prompt_doc(
                name=name,
                content=content,
                prompt_type="user_prompt",
                user_id=user_id
            )
            return jsonify(result), 201
        except Exception as e:
            app.logger.error(f"Error creating prompt: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @app.route('/api/prompts/<prompt_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def get_prompt(prompt_id):
        user_id = get_current_user_id()
        try:
            item = get_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id,
                prompt_type="user_prompt"
            )
            if not item:
                return jsonify({"error":"Prompt not found or access denied"}), 404
            return jsonify(item), 200
        except Exception as e:
            app.logger.error(f"Unexpected error getting prompt {prompt_id}: {e}")
            return jsonify({"error": "An unexpected error occurred"}), 500

    @app.route('/api/prompts/<prompt_id>', methods=['PATCH'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def update_prompt(prompt_id):
        user_id = get_current_user_id()
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
                prompt_type="user_prompt",
                updates=updates
            )
            if not result:
                return jsonify({"error":"Prompt not found or access denied"}), 404
            return jsonify(result), 200
        except Exception as e:
            app.logger.error(f"Unexpected error updating prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500

    @app.route('/api/prompts/<prompt_id>', methods=['DELETE'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_user_workspace")
    def delete_prompt(prompt_id):
        user_id = get_current_user_id()
        try:
            success = delete_prompt_doc(
                user_id=user_id,
                prompt_id=prompt_id
            )
            if not success:
                return jsonify({"error":"Prompt not found or access denied"}), 404
            return jsonify({"message":"Prompt deleted successfully"}), 200
        except Exception as e:
            app.logger.error(f"Unexpected error deleting prompt {prompt_id}: {e}")
            return jsonify({"error":"An unexpected error occurred"}), 500
