# route_frontend_search.py
"""Search routes exposing hybrid search as an API endpoint."""

from config import *
from functions_authentication import *
from functions_search import hybrid_search
from functions_debug import debug_print
from swagger_wrapper import swagger_route, get_auth_security


def register_route_frontend_search(app):
    @app.route('/api/search', methods=['POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_search():
        """
        Perform a hybrid search across user, group, and/or public document indexes.

        Expects JSON body:
            query (str, required): The search query text.
            doc_scope (str, optional): One of "all", "personal", "group", "public". Default "all".
            document_id (str, optional): Restrict search to a specific document.
            top_n (int, optional): Max results to return. Default 12.
            active_group_id (str, optional): Group ID when doc_scope is "group" or "all".
            active_public_workspace_id (str, optional): Public workspace ID when doc_scope is "public" or "all".

        Returns JSON:
            { "results": [...], "count": int }
        """
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "User not authenticated"}), 401

        data = request.get_json(silent=True) or {}
        query = (data.get("query") or "").strip()
        if not query:
            return jsonify({"error": "Missing required field: query"}), 400

        doc_scope = data.get("doc_scope", "all")
        if doc_scope not in ("all", "personal", "group", "public"):
            return jsonify({"error": f"Invalid doc_scope: {doc_scope}. Must be one of: all, personal, group, public"}), 400

        document_id = data.get("document_id")
        top_n = data.get("top_n", 12)
        active_group_id = data.get("active_group_id")
        active_public_workspace_id = data.get("active_public_workspace_id")

        try:
            top_n = int(top_n)
        except (TypeError, ValueError):
            return jsonify({"error": "top_n must be an integer"}), 400

        debug_print(
            f"API search request",
            "SEARCH_API",
            user_id=user_id,
            query=query[:40],
            doc_scope=doc_scope,
            top_n=top_n
        )

        try:
            results = hybrid_search(
                query=query,
                user_id=user_id,
                document_id=document_id,
                top_n=top_n,
                doc_scope=doc_scope,
                active_group_id=active_group_id,
                active_public_workspace_id=active_public_workspace_id,
            )
        except Exception as e:
            debug_print(f"Search error: {e}", "SEARCH_API")
            return jsonify({"error": "Search failed", "message": str(e)}), 500

        if results is None:
            return jsonify({"error": "Search failed — could not generate embedding"}), 500

        return jsonify({"results": results, "count": len(results)}), 200
