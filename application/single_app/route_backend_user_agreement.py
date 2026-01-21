# route_backend_user_agreement.py

from config import *
from functions_authentication import *
from functions_settings import get_settings
from functions_public_workspaces import find_public_workspace_by_id
from functions_activity_logging import log_user_agreement_accepted, has_user_accepted_agreement_today
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print


def register_route_backend_user_agreement(app):
    """
    Register user agreement API endpoints under '/api/user_agreement/...'
    These endpoints handle checking and recording user agreement acceptance.
    """

    @app.route("/api/user_agreement/check", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_check_user_agreement():
        """
        GET /api/user_agreement/check
        Check if the current user needs to accept a user agreement for a workspace.
        
        Query params:
            workspace_id: The workspace ID
            workspace_type: The workspace type ('personal', 'group', 'public', 'chat')
            action_context: The action context ('file_upload', 'chat') - optional
        
        Returns:
            {
                needsAgreement: bool,
                agreementText: str (if needs agreement),
                enableDailyAcceptance: bool
            }
        """
        info = get_current_user_info()
        user_id = info["userId"]

        workspace_id = request.args.get("workspace_id")
        workspace_type = request.args.get("workspace_type")
        action_context = request.args.get("action_context", "file_upload")

        if not workspace_id or not workspace_type:
            return jsonify({"error": "workspace_id and workspace_type are required"}), 400

        # Validate workspace type
        valid_types = ["personal", "group", "public", "chat"]
        if workspace_type not in valid_types:
            return jsonify({"error": f"Invalid workspace_type. Must be one of: {', '.join(valid_types)}"}), 400

        # Get global user agreement settings from app settings
        settings = get_settings()
        
        # Check if user agreement is enabled globally
        if not settings.get("enable_user_agreement", False):
            return jsonify({
                "needsAgreement": False,
                "agreementText": "",
                "enableDailyAcceptance": False
            }), 200

        apply_to = settings.get("user_agreement_apply_to", [])
        
        # Check if the agreement applies to this workspace type or action
        applies = False
        if workspace_type in apply_to:
            applies = True
        elif action_context == "chat" and "chat" in apply_to:
            applies = True

        if not applies:
            return jsonify({
                "needsAgreement": False,
                "agreementText": "",
                "enableDailyAcceptance": False
            }), 200

        # Check if daily acceptance is enabled and user already accepted today
        enable_daily_acceptance = settings.get("enable_user_agreement_daily", False)
        
        if enable_daily_acceptance:
            already_accepted = has_user_accepted_agreement_today(user_id, workspace_type, workspace_id)
            if already_accepted:
                debug_print(f"[USER_AGREEMENT] User {user_id} already accepted today for {workspace_type} workspace {workspace_id}")
                return jsonify({
                    "needsAgreement": False,
                    "agreementText": "",
                    "enableDailyAcceptance": True,
                    "alreadyAcceptedToday": True
                }), 200

        # User needs to accept the agreement
        return jsonify({
            "needsAgreement": True,
            "agreementText": settings.get("user_agreement_text", ""),
            "enableDailyAcceptance": enable_daily_acceptance
        }), 200

    @app.route("/api/user_agreement/accept", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_accept_user_agreement():
        """
        POST /api/user_agreement/accept
        Record that a user has accepted the user agreement for a workspace.
        
        Body JSON:
            {
                workspace_id: str,
                workspace_type: str ('personal', 'group', 'public'),
                action_context: str (optional, e.g., 'file_upload', 'chat')
            }
        
        Returns:
            { success: bool, message: str }
        """
        info = get_current_user_info()
        user_id = info["userId"]

        data = request.get_json() or {}
        workspace_id = data.get("workspace_id")
        workspace_type = data.get("workspace_type")
        action_context = data.get("action_context", "file_upload")

        if not workspace_id or not workspace_type:
            return jsonify({"error": "workspace_id and workspace_type are required"}), 400

        # Validate workspace type
        valid_types = ["personal", "group", "public"]
        if workspace_type not in valid_types:
            return jsonify({"error": f"Invalid workspace_type. Must be one of: {', '.join(valid_types)}"}), 400

        # Get workspace name for logging
        workspace_name = None
        if workspace_type == "public":
            ws = find_public_workspace_by_id(workspace_id)
            if ws:
                workspace_name = ws.get("name", "")

        # Log the acceptance
        try:
            log_user_agreement_accepted(
                user_id=user_id,
                workspace_type=workspace_type,
                workspace_id=workspace_id,
                workspace_name=workspace_name,
                action_context=action_context
            )
            
            debug_print(f"[USER_AGREEMENT] Recorded acceptance: user {user_id}, {workspace_type} workspace {workspace_id}")
            
            return jsonify({
                "success": True,
                "message": "User agreement acceptance recorded"
            }), 200
            
        except Exception as e:
            debug_print(f"[USER_AGREEMENT] Error recording acceptance: {str(e)}")
            log_event(f"Error recording user agreement acceptance: {str(e)}", level=logging.ERROR)
            return jsonify({
                "success": False,
                "error": f"Failed to record acceptance: {str(e)}"
            }), 500
