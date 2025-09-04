# route_backend_groups.py

from config import *
from functions_authentication import *
from functions_group import *

def register_route_backend_groups(app):
    """
    Register all group-related API endpoints under '/api/groups/...'
    """

    @app.route("/api/groups/discover", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def discover_groups():
        """
        GET /api/groups/discover?search=<term>&showAll=<true|false>
        Returns a list of ALL groups (or only those the user is not a member of),
        based on 'showAll' query param. Defaults to NOT showing the groups
        the user is already in.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]

        search_query = request.args.get("search", "").lower()
        show_all_str = request.args.get("showAll", "false").lower()
        show_all = (show_all_str == "true")

        query = "SELECT * FROM c WHERE c.type = 'group' or NOT IS_DEFINED(c.type)"
        all_items = list(cosmos_groups_container.query_items(
            query=query,
            enable_cross_partition_query=True
        ))

        results = []
        for g in all_items:
            name = g.get("name", "").lower()
            desc = g.get("description", "").lower()

            if search_query:
                if search_query not in name and search_query not in desc:
                    continue

            if not show_all:
                if is_user_in_group(g, user_id):
                    continue

            results.append({
                "id": g["id"],
                "name": g.get("name", ""),
                "description": g.get("description", ""),
                "owner": g.get("owner", {}),
                "member_count": len(g.get("users", []))
            })

        return jsonify(results), 200

    @app.route("/api/groups", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_list_groups():
        """
        Returns the user's groups with server-side pagination and search.
        Query Parameters:
            page (int): Page number (default: 1).
            page_size (int): Items per page (default: 10).
            search (str): Search term for group name/description.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]

        try:
            # --- Pagination Parameters ---
            page = int(request.args.get('page', 1))
            page_size = int(request.args.get('page_size', 10))
            if page < 1: page = 1
            if page_size < 1: page_size = 10
            offset = (page - 1) * page_size

            # --- Search Parameter ---
            search_query = request.args.get("search", "").strip()

            # --- Fetch ALL relevant groups first ---
            # The existing functions get all groups for the user or filtered by search
            # We'll do pagination *after* getting the full relevant list.
            if search_query:
                # Assuming search_groups returns all groups for the user matching the query
                all_matching_groups = search_groups(search_query, user_id)
            else:
                # Assuming get_user_groups returns all groups for the user
                all_matching_groups = get_user_groups(user_id)

            # --- Calculate total count and apply pagination ---
            total_count = len(all_matching_groups)
            paginated_groups = all_matching_groups[offset : offset + page_size]

            # --- Get active group ID ---
            user_settings_data = get_user_settings(user_id)
            db_active_group_id = user_settings_data["settings"].get("activeGroupOid", "")

            # --- Map results ---
            mapped_results = []
            for g in paginated_groups:
                role = get_user_role_in_group(g, user_id)
                mapped_results.append({
                    "id": g["id"],
                    "name": g.get("name", "Untitled Group"), # Provide default name
                    "description": g.get("description", ""),
                    "userRole": role,
                    "isActive": (g["id"] == db_active_group_id)
                })

            return jsonify({
                "groups": mapped_results,
                "page": page,
                "page_size": page_size,
                "total_count": total_count
            }), 200

        except Exception as e:
            print(f"Error in api_list_groups: {str(e)}")
            return jsonify({"error": f"An error occurred while fetching your groups: {str(e)}"}), 500


    @app.route("/api/groups", methods=["POST"])
    @login_required
    @user_required
    @create_group_role_required
    @enabled_required("enable_group_workspaces")
    def api_create_group():
        """
        POST /api/groups
        Expects JSON: { "name": "", "description": "" }
        Creates a new group with the current user as the owner.
        """        
        data = request.get_json()
        name = data.get("name", "Untitled Group")
        description = data.get("description", "")

        try:
            group_doc = create_group(name, description)
            return jsonify({"id": group_doc["id"], "name": group_doc["name"]}), 201
        except Exception as ex:
            return jsonify({"error": str(ex)}), 400

    @app.route("/api/groups/<group_id>", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_group_details(group_id):
        """
        GET /api/groups/<group_id>
        Returns the full group details for that group.
        """        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404
        return jsonify(group_doc), 200

    @app.route("/api/groups/<group_id>", methods=["DELETE"])
    @login_required
    @user_required
    @create_group_role_required
    @enabled_required("enable_group_workspaces")
    def api_delete_group(group_id):
        """
        DELETE /api/groups/<group_id>
        Only the owner can delete the group by default.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if group_doc["owner"]["id"] != user_id:
            return jsonify({"error": "Only the owner can delete the group"}), 403

        delete_group(group_id)
        return jsonify({"message": "Group deleted successfully"}), 200

    @app.route("/api/groups/<group_id>", methods=["PATCH", "PUT"])
    @login_required
    @user_required
    @create_group_role_required
    @enabled_required("enable_group_workspaces")
    def api_update_group(group_id):
        """
        PATCH /api/groups/<group_id> or PUT /api/groups/<group_id>
        Allows the owner to modify group name, description, etc.
        Expects JSON: { "name": "...", "description": "..." }
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if group_doc["owner"]["id"] != user_id:
            return jsonify({"error": "Only the owner can rename/edit the group"}), 403

        data = request.get_json()
        name = data.get("name", group_doc.get("name"))
        description = data.get("description", group_doc.get("description"))

        group_doc["name"] = name
        group_doc["description"] = description
        group_doc["modifiedDate"] = datetime.utcnow().isoformat()
        try:
            cosmos_groups_container.upsert_item(group_doc)
        except exceptions.CosmosHttpResponseError as ex:
            return jsonify({"error": str(ex)}), 400

        return jsonify({"message": "Group updated", "id": group_id}), 200

    @app.route("/api/groups/setActive", methods=["PATCH"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_set_active_group():
        """
        PATCH /api/groups/setActive
        Expects JSON: { "groupId": "<id>" }
        """
        data = request.get_json()
        group_id = data.get("groupId")
        if not group_id:
            return jsonify({"error": "Missing groupId"}), 400

        user_info = get_current_user_info()
        user_id = user_info["userId"]

        group_doc = find_group_by_id(group_id)
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if not role:
            return jsonify({"error": "You are not a member of this group"}), 403

        update_active_group_for_user(group_id)

        return jsonify({"message": f"Active group set to {group_id}"}), 200

    @app.route("/api/groups/<group_id>/requests", methods=["POST"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def request_to_join(group_id):
        """
        POST /api/groups/<group_id>/requests
        Creates a membership request. 
        We add the user to the group's 'pendingUsers' list if not already a member.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        existing_role = get_user_role_in_group(group_doc, user_id)
        if existing_role:
            return jsonify({"error": "User is already a member"}), 400

        for p in group_doc.get("pendingUsers", []):
            if p["userId"] == user_id:
                return jsonify({"error": "User has already requested to join"}), 400

        group_doc["pendingUsers"].append({
            "userId": user_id,
            "email": user_info["email"],
            "displayName": user_info["displayName"]
        })

        group_doc["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_groups_container.upsert_item(group_doc)

        return jsonify({"message": "Membership request created"}), 201

    @app.route("/api/groups/<group_id>/requests", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def view_pending_requests(group_id):
        """
        GET /api/groups/<group_id>/requests
        Allows Owner or Admin to see pending membership requests.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Only the owner or admin can view requests"}), 403

        return jsonify(group_doc.get("pendingUsers", [])), 200

    @app.route("/api/groups/<group_id>/requests/<request_id>", methods=["PATCH"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def approve_reject_request(group_id, request_id):
        """
        PATCH /api/groups/<group_id>/requests/<request_id>
        Body can contain { "action": "approve" } or { "action": "reject" }
        Only Owner or Admin can do so.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Only the owner or admin can approve/reject requests"}), 403

        data = request.get_json()
        action = data.get("action")
        if action not in ["approve", "reject"]:
            return jsonify({"error": "Invalid or missing 'action'. Must be 'approve' or 'reject'."}), 400

        pending_list = group_doc.get("pendingUsers", [])
        user_index = None
        for i, pending_user in enumerate(pending_list):
            if pending_user["userId"] == request_id:
                user_index = i
                break
        if user_index is None:
            return jsonify({"error": "Request not found"}), 404

        if action == "approve":
            member_to_add = pending_list.pop(user_index)
            group_doc["users"].append(member_to_add)
            msg = "User approved and added as a member"
        else:
            pending_list.pop(user_index)
            msg = "User rejected"

        group_doc["pendingUsers"] = pending_list
        group_doc["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_groups_container.upsert_item(group_doc)

        return jsonify({"message": msg}), 200

    @app.route("/api/groups/<group_id>/members", methods=["POST"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def add_member_directly(group_id):
        """
        POST /api/groups/<group_id>/members
        Body: { "userId": "<some_user_id>", "displayName": "...", etc. }
        Only Owner or Admin can add members directly (bypass request flow).
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]

        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if role not in ["Owner", "Admin"]:
            return jsonify({"error": "Only the owner or admin can add members"}), 403

        data = request.get_json()
        new_user_id = data.get("userId")
        if not new_user_id:
            return jsonify({"error": "Missing userId"}), 400

        if get_user_role_in_group(group_doc, new_user_id):
            return jsonify({"error": "User is already a member"}), 400

        new_member_doc = {
            "userId": new_user_id,
            "email": data.get("email", ""),
            "displayName": data.get("displayName", "New User")
        }
        group_doc["users"].append(new_member_doc)
        group_doc["modifiedDate"] = datetime.utcnow().isoformat()

        cosmos_groups_container.upsert_item(group_doc)
        return jsonify({"message": "Member added"}), 200

    @app.route("/api/groups/<group_id>/members/<member_id>", methods=["DELETE"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def remove_member(group_id, member_id):
        """
        DELETE /api/groups/<group_id>/members/<member_id>
        Remove a user from the group.
        - If the requestor == member_id, they can remove themselves (unless they are the owner).
        - Otherwise, only Owner or Admin can remove members.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if user_id == member_id:
            if group_doc["owner"]["id"] == user_id:
                return jsonify({"error": "The owner cannot leave the group. "
                                        "Transfer ownership or delete the group."}), 403

            removed = False
            updated_users = []
            for u in group_doc["users"]:
                if u["userId"] == member_id:
                    removed = True
                    continue
                updated_users.append(u)

            group_doc["users"] = updated_users
            
            if member_id in group_doc.get("admins", []):
                group_doc["admins"].remove(member_id)
            if member_id in group_doc.get("documentManagers", []):
                group_doc["documentManagers"].remove(member_id)

            group_doc["modifiedDate"] = datetime.utcnow().isoformat()
            cosmos_groups_container.upsert_item(group_doc)

            if removed:
                return jsonify({"message": "You have left the group"}), 200
            else:
                return jsonify({"error": "You are not in this group"}), 404

        else:
            role = get_user_role_in_group(group_doc, user_id)
            if role not in ["Owner", "Admin"]:
                return jsonify({"error": "Only the owner or admin can remove other members"}), 403

            if member_id == group_doc["owner"]["id"]:
                return jsonify({"error": "Cannot remove the group owner"}), 403

            removed = False
            updated_users = []
            for u in group_doc["users"]:
                if u["userId"] == member_id:
                    removed = True
                    continue
                updated_users.append(u)
            group_doc["users"] = updated_users

            if member_id in group_doc.get("admins", []):
                group_doc["admins"].remove(member_id)
            if member_id in group_doc.get("documentManagers", []):
                group_doc["documentManagers"].remove(member_id)

            group_doc["modifiedDate"] = datetime.utcnow().isoformat()
            cosmos_groups_container.upsert_item(group_doc)

            if removed:
                return jsonify({"message": "User removed"}), 200
            else:
                return jsonify({"error": "User not found in group"}), 404


    @app.route("/api/groups/<group_id>/members/<member_id>", methods=["PATCH"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def update_member_role(group_id, member_id):
        """
        PATCH /api/groups/<group_id>/members/<member_id>
        Body: { "role": "Admin" | "DocumentManager" | "User" }
        Only Owner or Admin can do so (but only Owner can promote Admins if you want).
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        current_role = get_user_role_in_group(group_doc, user_id)
        if current_role not in ["Owner", "Admin"]:
            return jsonify({"error": "Only the owner or admin can update roles"}), 403

        data = request.get_json()
        new_role = data.get("role")
        if new_role not in ["Admin", "DocumentManager", "User"]:
            return jsonify({"error": "Invalid role. Must be Admin, DocumentManager, or User"}), 400

        target_role = get_user_role_in_group(group_doc, member_id)
        if not target_role:
            return jsonify({"error": "Member is not in the group"}), 404

        if member_id in group_doc.get("admins", []):
            group_doc["admins"].remove(member_id)
        if member_id in group_doc.get("documentManagers", []):
            group_doc["documentManagers"].remove(member_id)

        if new_role == "Admin":
            group_doc["admins"].append(member_id)
        elif new_role == "DocumentManager":
            group_doc["documentManagers"].append(member_id)
        else:
            pass

        group_doc["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_groups_container.upsert_item(group_doc)

        return jsonify({"message": f"User {member_id} updated to {new_role}"}), 200

    @app.route("/api/groups/<group_id>/members", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def view_group_members(group_id):
        """
        GET /api/groups/<group_id>/members?search=<term>&role=<role>
        Returns the list of members with their roles, optionally filtered.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if not get_user_role_in_group(group_doc, user_id):
            return jsonify({"error": "You are not a member of this group"}), 403

        search = request.args.get("search", "").strip().lower()
        role_filter = request.args.get("role", "").strip()

        results = []
        for u in group_doc["users"]:
            uid = u["userId"]
            user_role = (
                "Owner" if uid == group_doc["owner"]["id"] else
                "Admin" if uid in group_doc.get("admins", []) else
                "DocumentManager" if uid in group_doc.get("documentManagers", []) else
                "User"
            )

            if role_filter and role_filter != user_role:
                continue

            dn = u.get("displayName", "").lower()
            em = u.get("email", "").lower()

            if search and (search not in dn and search not in em):
                continue

            results.append({
                "userId": uid,
                "displayName": u.get("displayName", ""),
                "email": u.get("email", ""),
                "role": user_role
            })

        return jsonify(results), 200

    @app.route("/api/groups/<group_id>/transferOwnership", methods=["PATCH"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def transfer_ownership(group_id):
        """
        PATCH /api/groups/<group_id>/transferOwnership
        Expects JSON: { "newOwnerId": "<userId>" }

        Only the current group Owner can do this.
        The newOwnerId must already be in the group's users[].
        After transferring ownership, we automatically
        "demote" the old owner so they are just a user.
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        data = request.get_json()
        new_owner_id = data.get("newOwnerId")

        if not new_owner_id:
            return jsonify({"error": "Missing newOwnerId"}), 400
        
        group_doc = find_group_by_id(group_id)

        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if group_doc["owner"]["id"] != user_id:
            return jsonify({"error": "Only the current owner can transfer ownership"}), 403

        matching_member = None
        for m in group_doc["users"]:
            if m["userId"] == new_owner_id:
                matching_member = m
                break
        if not matching_member:
            return jsonify({"error": "The specified new owner is not a member of the group"}), 400

        old_owner_id = group_doc["owner"]["id"]

        group_doc["owner"] = {
            "id": new_owner_id,
            "email": matching_member.get("email", ""),
            "displayName": matching_member.get("displayName", "")
        }

        if new_owner_id in group_doc.get("admins", []):
            group_doc["admins"].remove(new_owner_id)
        if new_owner_id in group_doc.get("documentManagers", []):
            group_doc["documentManagers"].remove(new_owner_id)

        found_old_owner = False
        for member in group_doc["users"]:
            if member["userId"] == old_owner_id:
                found_old_owner = True
                break

        if not found_old_owner:
            group_doc["users"].append({
                "userId": old_owner_id,
            })

        if old_owner_id in group_doc.get("admins", []):
            group_doc["admins"].remove(old_owner_id)
        if old_owner_id in group_doc.get("documentManagers", []):
            group_doc["documentManagers"].remove(old_owner_id)

        group_doc["modifiedDate"] = datetime.utcnow().isoformat()
        cosmos_groups_container.upsert_item(group_doc)

        return jsonify({"message": "Ownership transferred successfully"}), 200

    @app.route("/api/groups/<group_id>/fileCount", methods=["GET"])
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def get_group_file_count(group_id):
        """
        GET /api/groups/<group_id>/fileCount
        Returns JSON: { "fileCount": <int> }
        Only accessible by the owner (or if you prefer, admin as well).
        """
        user_info = get_current_user_info()
        user_id = user_info["userId"]
        
        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if group_doc["owner"]["id"] != user_id:
            return jsonify({"error": "Only the owner can check file count"}), 403
        
        query = """
        SELECT VALUE COUNT(1)
        FROM f
        WHERE f.groupId = @groupId
        """
        params = [{ "name": "@groupId", "value": group_id }]

        result_iter = cosmos_group_documents_container.query_items(
            query=query,
            parameters=params,
            enable_cross_partition_query=True
        )
        file_count = 0
        for item in result_iter:
            file_count = item

        return jsonify({ "fileCount": file_count }), 200
