# route_external_authentication.py
"""External authentication routes for API-to-API SSO."""

from config import *
from functions_authentication import accesstoken_required
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print
from flask import g


def register_route_external_authentication(app):
    @app.route('/external/login', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @accesstoken_required
    def external_login():
        """
        Creates a server-side session using a validated Entra bearer token.
        Returns session details for external clients (e.g., MCP servers).
        """
        claims = getattr(g, "user_claims", None)
        if not isinstance(claims, dict):
            return jsonify({"error": "Unauthorized", "message": "No user claims available"}), 401

        session["user"] = claims

        session_id = getattr(session, "sid", None) or session.get("session_id") or session.get("_id")
        if not session_id:
            session_id = str(uuid4())
            session["session_id"] = session_id

        response_payload = {
            "session_created": True,
            "session_id": session_id,
            "user": {
                "userId": claims.get("oid") or claims.get("sub"),
                "displayName": claims.get("name"),
                "email": claims.get("preferred_username") or claims.get("email")
            },
            "claims": claims
        }

        debug_print(f"External login session created for user {response_payload['user'].get('userId')}")
        return jsonify(response_payload), 200
