# route_backend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_public_workspaces import *
from swagger_wrapper import swagger_route, get_auth_security


def get_user_details_from_graph(user_id):
    """
    Get user details (displayName, email) from Microsoft Graph API by user ID.
    Returns a dict with displayName and email, or empty strings if not found.
    """
    try:
        token = get_valid_access_token()
        if not token:
            return {"displayName": "", "email": ""}

        if AZURE_ENVIRONMENT == "usgovernment":
            user_endpoint = f"https://graph.microsoft.us/v1.0/users/{user_id}"
        elif AZURE_ENVIRONMENT == "custom":
            user_endpoint = f"{CUSTOM_GRAPH_URL_VALUE}/{user_id}"
        else:
            user_endpoint = f"https://graph.microsoft.com/v1.0/users/{user_id}"
            
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        params = {
            "$select": "id,displayName,mail,userPrincipalName"
        }

        response = requests.get(user_endpoint, headers=headers, params=params)
        response.raise_for_status()

        user_data = response.json()
        email = user_data.get("mail") or user_data.get("userPrincipalName") or ""
        
        return {
            "displayName": user_data.get("displayName", ""),
            "email": email
        }

    except Exception as e:
        print(f"Failed to get user details for {user_id}: {e}")
        return {"displayName": "", "email": ""}

def register_route_backend_public_workspaces(app):
    """
    Register all public-workspace–related API endpoints under '/api/public_workspaces/...'
    """

    @app.route("/api/public_workspaces/discover", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def discover_public_workspaces():
        """
        GET /api/public_workspaces/discover?search=<term>
        Returns a list of all public workspaces, filtered by search term.
        """
        search_query = request.args.get("search", "").lower().strip()
        all_items = list(cosmos_public_workspaces_container.query_items(
            query="SELECT * FROM c",
            enable_cross_partition_query=True
        ))

        results = []
        for ws in all_items:
            name = ws.get("name", "").lower()
            desc = ws.get("description", "").lower()
            if search_query and search_query not in name and search_query not in desc:
                continue
            results.append({
                "id": ws["id"],
                "name": ws.get("name", ""),
                "description": ws.get("description", "")
            })

        return jsonify(results), 200

    @app.route("/api/public_workspaces", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_list_public_workspaces():
        """
        GET /api/public_workspaces
        Paginated list of the user's public workspaces.
        Query params:
          - page (int), page_size (int), search (str)
        """
        info = get_current_user_info()
        user_id = info["userId"]

        # pagination
        # safe parsing of page / page_size
        try:
            page = int(request.args.get("page", 1))
            if page < 1:
                page = 1
        except (ValueError, TypeError):
            page = 1

        try:
            page_size = int(request.args.get("page_size", 10))
            if page_size < 1:
                page_size = 10
        except (ValueError, TypeError):
            page_size = 10
            
        offset = (page - 1) * page_size

        search_term = request.args.get("search", "").strip()

        # fetch user’s workspaces
        if search_term:
            all_ws = search_public_workspaces(search_term, user_id)
        else:
            all_ws = get_user_public_workspaces(user_id)

        total_count = len(all_ws)
        slice_ws = all_ws[offset: offset + page_size]

        # get active from user settings
        settings = get_user_settings(user_id)
        active_id = settings["settings"].get("activePublicWorkspaceOid", "")

        mapped = []
        for ws in slice_ws:
            # determine userRole
            if ws["owner"]["userId"] == user_id:
                role = "Owner"
            elif user_id in ws.get("admins", []):
                role = "Admin"
            else:
                # documentManagers list of dicts
                dm_ids = [dm["userId"] for dm in ws.get("documentManagers", [])]
                role = "DocumentManager" if user_id in dm_ids else None

            mapped.append({
                "id": ws["id"],
                "name": ws.get("name", ""),
                "description": ws.get("description", ""),
                "userRole": role,
                "isActive": (ws["id"] == active_id)
            })

        return jsonify({
            "workspaces": mapped,
            "page": page,
            "page_size": page_size,
            "total_count": total_count
        }), 200

    @app.route("/api/public_workspaces", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @create_public_workspace_role_required
    @enabled_required("enable_public_workspaces")
    def api_create_public_workspace():
        """
        POST /api/public_workspaces
        Body JSON: { "name": "", "description": "" }
        """
        data = request.get_json() or {}
        name = data.get("name", "Untitled Workspace")
        description = data.get("description", "")

        try:
            ws = create_public_workspace(name, description)
            return jsonify({"id": ws["id"], "name": ws["name"]}), 201
        except Exception as ex:
            return jsonify({"error": str(ex)}), 400

    @app.route("/api/public_workspaces/<ws_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_get_public_workspace(ws_id):
        """
        GET /api/public_workspaces/<ws_id>
        Returns full workspace document.
        """
        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Workspace not found"}), 404
        return jsonify(ws), 200

    @app.route("/api/public_workspaces/<ws_id>", methods=["PATCH", "PUT"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_update_public_workspace(ws_id):
        """
        PATCH /api/public_workspaces/<ws_id>
        Body JSON: { "name": "", "description": "" }
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Workspace not found"}), 404
        if ws["owner"]["userId"] != user_id:
            return jsonify({"error": "Only owner can update"}), 403

        data = request.get_json() or {}
        ws["name"] = data.get("name", ws.get("name"))
        ws["description"] = data.get("description", ws.get("description"))
        ws["modifiedDate"] = datetime.utcnow().isoformat()

        try:
            cosmos_public_workspaces_container.upsert_item(ws)
            return jsonify({"message": "Updated"}), 200
        except exceptions.CosmosHttpResponseError as ex:
            return jsonify({"error": str(ex)}), 400

    @app.route("/api/public_workspaces/<ws_id>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_delete_public_workspace(ws_id):
        """
        DELETE /api/public_workspaces/<ws_id>
        Only owner may delete.
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Workspace not found"}), 404
        if ws["owner"]["userId"] != user_id:
            return jsonify({"error": "Only owner can delete"}), 403

        delete_public_workspace(ws_id)
        return jsonify({"message": "Deleted"}), 200

    @app.route("/api/public_workspaces/setActive", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_set_active_public_workspace():
        """
        PATCH /api/public_workspaces/setActive
        Body JSON: { "workspaceId": "<id>" }
        """
        data = request.get_json() or {}
        ws_id = data.get("workspaceId")
        if not ws_id:
            return jsonify({"error": "Missing workspaceId"}), 400

        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Workspace not found"}), 404

        # verify membership
        is_member = (
            ws["owner"]["userId"] == user_id or
            user_id in ws.get("admins", []) or
            any(dm["userId"] == user_id for dm in ws.get("documentManagers", []))
        )
        if not is_member:
            return jsonify({"error": "Not a member"}), 403

        update_active_public_workspace_for_user(user_id, ws_id)
        return jsonify({"message": f"Active set to {ws_id}"}), 200

    @app.route("/api/public_workspaces/<ws_id>/requests", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_view_public_requests(ws_id):
        """
        GET /api/public_workspaces/<ws_id>/requests
        Owner/Admin see pending document-manager requests.
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        role = (
            "Owner" if ws["owner"]["userId"] == user_id else
            "Admin" if user_id in ws.get("admins", []) else
            None
        )
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Forbidden"}), 403

        return jsonify(ws.get("pendingDocumentManagers", [])), 200

    @app.route("/api/public_workspaces/<ws_id>/requests", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_request_public_workspace(ws_id):
        """
        POST /api/public_workspaces/<ws_id>/requests
        User requests document-manager role.
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        # already manager?
        if any(dm["userId"] == user_id for dm in ws.get("documentManagers", [])):
            return jsonify({"error": "Already a document manager"}), 400

        # already requested?
        if any(p["userId"] == user_id for p in ws.get("pendingDocumentManagers", [])):
            return jsonify({"error": "Already requested"}), 400

        ws.setdefault("pendingDocumentManagers", []).append({
            "userId": user_id,
            "email": info["email"],
            "displayName": info["displayName"]
        })
        ws["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_public_workspaces_container.upsert_item(ws)
        return jsonify({"message": "Requested"}), 201

    @app.route("/api/public_workspaces/<ws_id>/requests/<req_id>", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_handle_public_request(ws_id, req_id):
        """
        PATCH /api/public_workspaces/<ws_id>/requests/<req_id>
        Body JSON: { "action": "approve" | "reject" }
        """
        info = get_current_user_info()
        user_id = info["userId"]
        data = request.get_json() or {}
        action = data.get("action")

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        role = (
            "Owner" if ws["owner"]["userId"] == user_id else
            "Admin" if user_id in ws.get("admins", []) else
            None
        )
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Forbidden"}), 403

        pend = ws.get("pendingDocumentManagers", [])
        idx = next((i for i, p in enumerate(pend) if p["userId"] == req_id), None)
        if idx is None:
            return jsonify({"error": "Request not found"}), 404

        if action == "approve":
            dm = pend.pop(idx)
            ws.setdefault("documentManagers", []).append(dm)
            msg = "Approved"
        elif action == "reject":
            pend.pop(idx)
            msg = "Rejected"
        else:
            return jsonify({"error": "Invalid action"}), 400

        ws["pendingDocumentManagers"] = pend
        ws["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_public_workspaces_container.upsert_item(ws)
        return jsonify({"message": msg}), 200

    @app.route("/api/public_workspaces/<ws_id>/members", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_list_public_members(ws_id):
        """
        GET /api/public_workspaces/<ws_id>/members?search=&role=
        List members and their roles.
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        # must be member
        is_member = (
            ws["owner"]["userId"] == user_id or
            user_id in ws.get("admins", []) or
            any(dm["userId"] == user_id for dm in ws.get("documentManagers", []))
        )
        if not is_member:
            return jsonify({"error": "Forbidden"}), 403

        search = request.args.get("search", "").strip().lower()
        role_filter = request.args.get("role", "").strip()

        results = []
        # owner
        results.append({
            "userId": ws["owner"]["userId"],
            "displayName": ws["owner"].get("displayName", ""),
            "email": ws["owner"].get("email", ""),
            "role": "Owner"
        })
        # admins
        for aid in ws.get("admins", []):
            admin_details = get_user_details_from_graph(aid)
            results.append({
                "userId": aid, 
                "displayName": admin_details["displayName"], 
                "email": admin_details["email"], 
                "role": "Admin"
            })
        # doc managers
        for dm in ws.get("documentManagers", []):
            results.append({
                "userId": dm["userId"],
                "displayName": dm.get("displayName", ""),
                "email": dm.get("email", ""),
                "role": "DocumentManager"
            })

        # filter
        def keep(m):
            if role_filter and m["role"] != role_filter:
                return False
            if search:
                dn = m["displayName"].lower()
                em = m["email"].lower()
                return search in dn or search in em
            return True

        return jsonify([m for m in results if keep(m)]), 200

    @app.route("/api/public_workspaces/<ws_id>/members", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_add_public_member(ws_id):
        """
        POST /api/public_workspaces/<ws_id>/members
        Body JSON: { "userId": "", "displayName": "", "email": "" }
        Owner/Admin only: bypass request flow.
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        role = (
            "Owner" if ws["owner"]["userId"] == user_id else
            "Admin" if user_id in ws.get("admins", []) else
            None
        )
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Forbidden"}), 403

        data = request.get_json() or {}
        new_id = data.get("userId")
        if not new_id:
            return jsonify({"error": "Missing userId"}), 400

        # prevent dup
        if any(dm["userId"] == new_id for dm in ws.get("documentManagers", [])):
            return jsonify({"error": "Already a manager"}), 400

        ws.setdefault("documentManagers", []).append({
            "userId": new_id,
            "displayName": data.get("displayName", ""),
            "email": data.get("email", "")
        })
        ws["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_public_workspaces_container.upsert_item(ws)
        return jsonify({"message": "Member added"}), 200

    @app.route("/api/public_workspaces/<ws_id>/members/<member_id>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_remove_public_member(ws_id, member_id):
        """
        DELETE /api/public_workspaces/<ws_id>/members/<member_id>
        - Owner cannot remove self.
        - Owner/Admin remove documentManagers.
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        # if self-removal
        if member_id == user_id:
            return jsonify({"error": "Cannot leave public workspace"}), 403

        # only Owner/Admin can remove others
        role = (
            "Owner" if ws["owner"]["userId"] == user_id else
            "Admin" if user_id in ws.get("admins", []) else
            None
        )
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Forbidden"}), 403

        # remove from admins if present
        if member_id in ws.get("admins", []):
            ws["admins"].remove(member_id)
        # remove from doc managers
        ws["documentManagers"] = [
            dm for dm in ws.get("documentManagers", [])
            if dm["userId"] != member_id
        ]
        ws["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_public_workspaces_container.upsert_item(ws)
        return jsonify({"message": "Removed"}), 200

    @app.route("/api/public_workspaces/<ws_id>/members/<member_id>", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_update_public_member_role(ws_id, member_id):
        """
        PATCH /api/public_workspaces/<ws_id>/members/<member_id>
        Body JSON: { "role": "Admin" | "DocumentManager" }
        Owner/Admin only.
        """
        info = get_current_user_info()
        user_id = info["userId"]
        data = request.get_json() or {}
        new_role = data.get("role")

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        role = (
            "Owner" if ws["owner"]["userId"] == user_id else
            "Admin" if user_id in ws.get("admins", []) else
            None
        )
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Forbidden"}), 403

        # clear any existing
        if member_id in ws.get("admins", []):
            ws["admins"].remove(member_id)
        ws["documentManagers"] = [
            dm for dm in ws.get("documentManagers", [])
            if dm["userId"] != member_id
        ]

        if new_role == "Admin":
            ws.setdefault("admins", []).append(member_id)
        elif new_role == "DocumentManager":
            # need displayName/email from pending or empty
            ws.setdefault("documentManagers", []).append({
                "userId": member_id,
                "email": "",
                "displayName": ""
            })
        else:
            return jsonify({"error": "Invalid role"}), 400

        ws["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_public_workspaces_container.upsert_item(ws)
        return jsonify({"message": "Role updated"}), 200

    @app.route("/api/public_workspaces/<ws_id>/transferOwnership", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_transfer_public_ownership(ws_id):
        """
        PATCH /api/public_workspaces/<ws_id>/transferOwnership
        Body JSON: { "newOwnerId": "<userId>" }
        Only current owner may transfer.
        """
        info = get_current_user_info()
        user_id = info["userId"]
        data = request.get_json() or {}
        new_owner = data.get("newOwnerId")

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404
        if ws["owner"]["userId"] != user_id:
            return jsonify({"error": "Forbidden"}), 403

        # must be existing documentManager or admin
        is_member = (
            any(dm["userId"] == new_owner for dm in ws.get("documentManagers", [])) or
            new_owner in ws.get("admins", [])
        )
        if not is_member:
            return jsonify({"error": "New owner must be a manager or admin"}), 400

        # swap
        old_owner = ws["owner"]["userId"]
        
        # Get the new owner details - check if they're a documentManager first, then admin
        new_owner_dm = next(
            (dm for dm in ws.get("documentManagers", []) if dm["userId"] == new_owner), 
            None
        )
        
        if new_owner_dm:
            # New owner is a documentManager
            ws["owner"] = new_owner_dm
        else:
            # New owner must be an admin - get their details from Microsoft Graph
            admin_details = get_user_details_from_graph(new_owner)
            ws["owner"] = {
                "userId": new_owner,
                "displayName": admin_details["displayName"],
                "email": admin_details["email"]
            }
        # remove new_owner from docManagers/admins
        ws["documentManagers"] = [dm for dm in ws["documentManagers"] if dm["userId"] != new_owner]
        if new_owner in ws.get("admins", []):
            ws["admins"].remove(new_owner)

        # legacy: old owner stays as documentManager
        ws.setdefault("documentManagers", []).append({
            "userId": old_owner,
            "displayName": "",
            "email": ""
        })

        ws["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_public_workspaces_container.upsert_item(ws)
        return jsonify({"message": "Ownership transferred"}), 200

    @app.route("/api/public_workspaces/<ws_id>/fileCount", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_public_file_count(ws_id):
        """
        GET /api/public_workspaces/<ws_id>/fileCount
        Returns count of documents in this workspace.
        """
        info = get_current_user_info()
        user_id = info["userId"]

        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404
        # Allow any logged-in user to view file count for public workspaces

        query = "SELECT VALUE COUNT(1) FROM d WHERE d.public_workspace_id = @wsId"
        params = [{"name": "@wsId", "value": ws_id}]
        count_iter = cosmos_public_documents_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        )
        file_count = next(count_iter, 0)
        return jsonify({"fileCount": file_count}), 200

    @app.route("/api/public_workspaces/<ws_id>/promptCount", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_public_prompt_count(ws_id):
        """
        GET /api/public_workspaces/<ws_id>/promptCount
        Returns count of prompts in this workspace.
        """
        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        query = "SELECT VALUE COUNT(1) FROM p WHERE p.public_workspace_id = @wsId"
        params = [{"name": "@wsId", "value": ws_id}]
        count_iter = cosmos_public_prompts_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        )
        prompt_count = next(count_iter, 0)
        return jsonify({"promptCount": prompt_count}), 200
