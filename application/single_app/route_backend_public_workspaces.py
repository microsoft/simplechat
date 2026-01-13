# route_backend_public_workspaces.py

from config import *
from functions_authentication import *
from functions_public_workspaces import *
from functions_notifications import create_notification
from swagger_wrapper import swagger_route, get_auth_security
from functions_debug import debug_print


def is_user_in_admins(user_id, admins_list):
    """
    Check if user is in admins list (supports both old format ["id1", "id2"] and new format [{userId, email, displayName}])
    """
    if not admins_list:
        return False
    for admin in admins_list:
        if isinstance(admin, str):
            if admin == user_id:
                return True
        elif isinstance(admin, dict):
            if admin.get("userId") == user_id:
                return True
    return False

def remove_user_from_admins(user_id, admins_list):
    """
    Remove user from admins list (supports both old and new format)
    Returns updated admins list
    """
    if not admins_list:
        return []
    return [admin for admin in admins_list if 
            (isinstance(admin, str) and admin != user_id) or
            (isinstance(admin, dict) and admin.get("userId") != user_id)]

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
                "status": ws.get("status", "active"),
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
        Body JSON: { "name": "", "description": "", "heroColor": "" }
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
        ws["heroColor"] = data.get("heroColor", ws.get("heroColor", "#0078d4"))
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
            is_user_in_admins(user_id, ws.get("admins", [])) or
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
        # admins (support both old format ["id"] and new format [{userId, email, displayName}])
        for admin in ws.get("admins", []):
            if isinstance(admin, str):
                # Old format - fetch from Graph
                admin_details = get_user_details_from_graph(admin)
                results.append({
                    "userId": admin, 
                    "displayName": admin_details["displayName"], 
                    "email": admin_details["email"], 
                    "role": "Admin"
                })
            elif isinstance(admin, dict):
                # New format - use stored data
                results.append({
                    "userId": admin.get("userId", ""),
                    "displayName": admin.get("displayName", ""),
                    "email": admin.get("email", ""),
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
        
        # Send notification to the added member
        try:
            create_notification(
                user_id=new_id,
                notification_type='public_workspace_membership_change',
                title='Added to Public Workspace',
                message=f"You have been added to the public workspace '{ws.get('name', 'Unknown')}' as Document Manager.",
                link_url=f"/manage_public_workspace?workspace_id={ws_id}",
                metadata={
                    'workspace_id': ws_id,
                    'workspace_name': ws.get('name', 'Unknown'),
                    'role': 'DocumentManager',
                    'added_by': info.get('email', 'Unknown')
                }
            )
        except Exception as notif_error:
            debug_print(f"Failed to create notification for new member: {notif_error}")
        
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
            "Admin" if is_user_in_admins(user_id, ws.get("admins", [])) else
            None
        )
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Forbidden"}), 403

        # remove from admins if present
        ws["admins"] = remove_user_from_admins(member_id, ws.get("admins", []))
        # remove from doc managers
        ws["documentManagers"] = [
            dm for dm in ws.get("documentManagers", [])
            if dm["userId"] != member_id
        ]
        ws["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_public_workspaces_container.upsert_item(ws)
        return jsonify({"success": True, "message": "Removed"}), 200

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
            "Admin" if is_user_in_admins(user_id, ws.get("admins", [])) else
            None
        )
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Forbidden"}), 403

        # Get member details (from documentManagers or Graph API)
        member_name = ""
        member_email = ""
        for dm in ws.get("documentManagers", []):
            if dm.get("userId") == member_id:
                member_name = dm.get("displayName", "")
                member_email = dm.get("email", "")
                break
        
        # If not found in documentManagers, try to get from existing admins or Graph
        if not member_name:
            for admin in ws.get("admins", []):
                if isinstance(admin, dict) and admin.get("userId") == member_id:
                    member_name = admin.get("displayName", "")
                    member_email = admin.get("email", "")
                    break
            if not member_name:
                # Fetch from Graph API
                try:
                    details = get_user_details_from_graph(member_id)
                    member_name = details.get("displayName", "")
                    member_email = details.get("email", "")
                except:
                    pass

        # clear any existing
        ws["admins"] = remove_user_from_admins(member_id, ws.get("admins", []))
        ws["documentManagers"] = [
            dm for dm in ws.get("documentManagers", [])
            if dm["userId"] != member_id
        ]

        if new_role == "Admin":
            ws.setdefault("admins", []).append({
                "userId": member_id,
                "displayName": member_name,
                "email": member_email
            })
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
        
        # Send notification to the member whose role changed
        try:
            # Determine old role for notification
            old_role = "DocumentManager"  # Default, will be corrected if needed
            for admin in ws.get("admins", []):
                if isinstance(admin, dict) and admin.get("userId") == member_id:
                    old_role = "Admin"
                    break
                elif isinstance(admin, str) and admin == member_id:
                    old_role = "Admin"
                    break
            
            create_notification(
                user_id=member_id,
                notification_type='public_workspace_membership_change',
                title='Workspace Role Changed',
                message=f"Your role in the public workspace '{ws.get('name', 'Unknown')}' has been changed to {new_role}.",
                link_url=f"/manage_public_workspace?workspace_id={ws_id}",
                metadata={
                    'workspace_id': ws_id,
                    'workspace_name': ws.get('name', 'Unknown'),
                    'old_role': old_role,
                    'new_role': new_role,
                    'changed_by': info.get('email', 'Unknown')
                }
            )
        except Exception as notif_error:
            debug_print(f"Failed to create notification for role change: {notif_error}")
        
        return jsonify({"success": True, "message": "Role updated"}), 200

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

    @app.route("/api/public_workspaces/<ws_id>/stats", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_public_workspace_stats(ws_id):
        """
        GET /api/public_workspaces/<ws_id>/stats
        Returns statistics for the workspace including documents, storage, tokens, and members.
        """
        info = get_current_user_info()
        user_id = info["userId"]
        
        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        # Check user has access - must be member
        is_member = (
            ws["owner"]["userId"] == user_id or
            is_user_in_admins(user_id, ws.get("admins", [])) or
            any(dm["userId"] == user_id for dm in ws.get("documentManagers", []))
        )
        if not is_member:
            return jsonify({"error": "Forbidden"}), 403

        # Get metrics from workspace record (pre-calculated)
        metrics = ws.get("metrics", {})
        document_metrics = metrics.get("document_metrics", {})
        
        total_documents = document_metrics.get("total_documents", 0)
        storage_used = document_metrics.get("storage_account_size", 0)

        # Get member count
        owner = ws.get("owner", {})
        admins = ws.get("admins", [])
        doc_managers = ws.get("documentManagers", [])
        total_members = 1 + len(admins) + len(doc_managers)

        # Get token usage from activity logs (last 30 days)
        from datetime import datetime, timedelta
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        
        debug_print(f"[PUBLIC_WORKSPACE_STATS] Workspace ID: {ws_id}")
        debug_print(f"[PUBLIC_WORKSPACE_STATS] Start date: {thirty_days_ago}")
        
        token_query = """
            SELECT a.usage
            FROM a 
            WHERE a.workspace_context.public_workspace_id = @wsId 
            AND a.timestamp >= @startDate
            AND a.activity_type = 'token_usage'
        """
        token_params = [
            {"name": "@wsId", "value": ws_id},
            {"name": "@startDate", "value": thirty_days_ago}
        ]
        
        total_tokens = 0
        try:
            token_iter = cosmos_activity_logs_container.query_items(
                query=token_query,
                parameters=token_params,
                enable_cross_partition_query=True
            )
            for item in token_iter:
                usage = item.get("usage", {})
                total_tokens += usage.get("total_tokens", 0)
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Total tokens accumulated: {total_tokens}")
        except Exception as e:
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Error querying total tokens: {e}")
            import traceback
            traceback.print_exc()

        # Get activity data for charts (last 30 days)
        doc_activity_labels = []
        doc_upload_data = []
        doc_delete_data = []
        token_usage_labels = []
        token_usage_data = []
        
        # Generate labels for last 30 days
        for i in range(29, -1, -1):
            date = datetime.utcnow() - timedelta(days=i)
            doc_activity_labels.append(date.strftime("%m/%d"))
            token_usage_labels.append(date.strftime("%m/%d"))
            doc_upload_data.append(0)
            doc_delete_data.append(0)
            token_usage_data.append(0)

        # Get document upload activity by day
        doc_upload_query = """
            SELECT a.timestamp, a.created_at
            FROM a
            WHERE a.workspace_context.public_workspace_id = @wsId
            AND a.timestamp >= @startDate
            AND a.activity_type = 'document_creation'
        """
        debug_print(f"[PUBLIC_WORKSPACE_STATS] Document upload query: {doc_upload_query}")
        debug_print(f"[PUBLIC_WORKSPACE_STATS] Query params: {token_params}")
        try:
            activity_iter = cosmos_activity_logs_container.query_items(
                query=doc_upload_query,
                parameters=token_params,
                enable_cross_partition_query=True
            )
            upload_results = list(activity_iter)
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Document upload results count: {len(upload_results)}")
            
            for item in upload_results:
                timestamp = item.get("timestamp") or item.get("created_at")
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        day_date = dt.strftime("%m/%d")
                        if day_date in doc_activity_labels:
                            idx = doc_activity_labels.index(day_date)
                            doc_upload_data[idx] += 1
                            debug_print(f"[PUBLIC_WORKSPACE_STATS] Added upload for {day_date}")
                    except Exception as e:
                        debug_print(f"[PUBLIC_WORKSPACE_STATS] Error parsing timestamp {timestamp}: {e}")
        except Exception as e:
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Error querying document uploads: {e}")
            import traceback
            traceback.print_exc()

        # Get document delete activity by day
        doc_delete_query = """
            SELECT a.timestamp, a.created_at
            FROM a
            WHERE a.workspace_context.public_workspace_id = @wsId
            AND a.timestamp >= @startDate
            AND a.activity_type = 'document_deletion'
        """
        debug_print(f"[PUBLIC_WORKSPACE_STATS] Document delete query: {doc_delete_query}")
        try:
            delete_iter = cosmos_activity_logs_container.query_items(
                query=doc_delete_query,
                parameters=token_params,
                enable_cross_partition_query=True
            )
            delete_results = list(delete_iter)
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Document delete results count: {len(delete_results)}")
            
            for item in delete_results:
                timestamp = item.get("timestamp") or item.get("created_at")
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        day_date = dt.strftime("%m/%d")
                        if day_date in doc_activity_labels:
                            idx = doc_activity_labels.index(day_date)
                            doc_delete_data[idx] += 1
                            debug_print(f"[PUBLIC_WORKSPACE_STATS] Added delete for {day_date}")
                    except Exception as e:
                        debug_print(f"[PUBLIC_WORKSPACE_STATS] Error parsing timestamp {timestamp}: {e}")
        except Exception as e:
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Error querying document deletes: {e}")
            import traceback
            traceback.print_exc()

        # Get token usage by day
        token_activity_query = """
            SELECT a.timestamp, a.created_at, a.usage
            FROM a
            WHERE a.workspace_context.public_workspace_id = @wsId
            AND a.timestamp >= @startDate
            AND a.activity_type = 'token_usage'
        """
        debug_print(f"[PUBLIC_WORKSPACE_STATS] Token usage query: {token_activity_query}")
        try:
            token_activity_iter = cosmos_activity_logs_container.query_items(
                query=token_activity_query,
                parameters=token_params,
                enable_cross_partition_query=True
            )
            token_results = list(token_activity_iter)
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Token usage results count: {len(token_results)}")
            
            for item in token_results:
                timestamp = item.get("timestamp") or item.get("created_at")
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        day_date = dt.strftime("%m/%d")
                        if day_date in token_usage_labels:
                            idx = token_usage_labels.index(day_date)
                            usage = item.get("usage", {})
                            tokens = usage.get("total_tokens", 0)
                            token_usage_data[idx] += tokens
                            debug_print(f"[PUBLIC_WORKSPACE_STATS] Added {tokens} tokens for {day_date}")
                    except Exception as e:
                        debug_print(f"[PUBLIC_WORKSPACE_STATS] Error parsing timestamp {timestamp}: {e}")
        except Exception as e:
            debug_print(f"[PUBLIC_WORKSPACE_STATS] Error querying token usage: {e}")
            import traceback
            traceback.print_exc()

        # Get separate storage metrics
        ai_search_size = document_metrics.get("ai_search_size", 0)
        storage_account_size = document_metrics.get("storage_account_size", 0)

        stats = {
            "totalDocuments": total_documents,
            "storageUsed": storage_used,
            "storageLimit": 10737418240,  # 10GB default
            "totalTokens": total_tokens,
            "totalMembers": total_members,
            "storage": {
                "ai_search_size": ai_search_size,
                "storage_account_size": storage_account_size
            },
            "documentActivity": {
                "labels": doc_activity_labels,
                "uploads": doc_upload_data,
                "deletes": doc_delete_data
            },
            "tokenUsage": {
                "labels": token_usage_labels,
                "data": token_usage_data
            }
        }
        
        debug_print(f"[PUBLIC_WORKSPACE_STATS] Final stats: {stats}")

        return jsonify(stats), 200

    @app.route("/api/public_workspaces/<ws_id>/activity", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_public_workspaces")
    def api_public_workspace_activity(ws_id):
        """
        GET /api/public_workspaces/<ws_id>/activity
        Returns recent activity timeline for the workspace.
        Only accessible by owner and admins.
        """
        info = get_current_user_info()
        user_id = info["userId"]
        
        ws = find_public_workspace_by_id(ws_id)
        if not ws:
            return jsonify({"error": "Not found"}), 404

        # Check user is owner or admin (NOT document managers or regular members)
        is_owner = ws["owner"]["userId"] == user_id
        is_admin = is_user_in_admins(user_id, ws.get("admins", []))
        
        if not (is_owner or is_admin):
            return jsonify({"error": "Forbidden - Only workspace owners and admins can view activity timeline"}), 403

        # Get pagination parameters
        limit = request.args.get('limit', 50, type=int)
        if limit not in [10, 20, 50]:
            limit = 50

        # Get recent activity
        query = f"""
            SELECT TOP {limit} *
            FROM a
            WHERE a.workspace_context.public_workspace_id = @wsId
            ORDER BY a.timestamp DESC
        """
        params = [{"name": "@wsId", "value": ws_id}]
        
        debug_print(f"[PUBLIC_WORKSPACE_ACTIVITY] Workspace ID: {ws_id}")
        debug_print(f"[PUBLIC_WORKSPACE_ACTIVITY] Query: {query}")
        debug_print(f"[PUBLIC_WORKSPACE_ACTIVITY] Params: {params}")
        
        activities = []
        try:
            activity_iter = cosmos_activity_logs_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            )
            activities = list(activity_iter)
            debug_print(f"[PUBLIC_WORKSPACE_ACTIVITY] Found {len(activities)} activity records")
            if activities:
                debug_print(f"[PUBLIC_WORKSPACE_ACTIVITY] Sample activity: {activities[0] if activities else 'None'}")
        except Exception as e:
            debug_print(f"[PUBLIC_WORKSPACE_ACTIVITY] Error querying activities: {e}")
            import traceback
            traceback.print_exc()

        return jsonify(activities), 200

