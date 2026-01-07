# route_backend_groups.py

from config import *
from functions_authentication import *
from functions_group import *
from functions_debug import debug_print
from functions_notifications import create_notification
from swagger_wrapper import swagger_route, get_auth_security

def register_route_backend_groups(app):
    """
    Register all group-related API endpoints under '/api/groups/...'
    """

    @app.route("/api/groups/discover", methods=["GET"])
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
                    "isActive": (g["id"] == db_active_group_id),
                    "status": g.get("status", "active")  # Include group status
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
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @create_group_role_required
    @enabled_required("enable_group_creation")
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
        user_email = user_info.get("email", "unknown")

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

        # Get role from request, default to 'user'
        member_role = data.get("role", "user").lower()
        
        # Validate role
        valid_roles = ['admin', 'document_manager', 'user']
        if member_role not in valid_roles:
            return jsonify({"error": f"Invalid role. Must be: {', '.join(valid_roles)}"}), 400

        new_member_doc = {
            "userId": new_user_id,
            "email": data.get("email", ""),
            "displayName": data.get("displayName", "New User")
        }
        group_doc["users"].append(new_member_doc)
        
        # Add to appropriate role array
        if member_role == 'admin':
            if new_user_id not in group_doc.get('admins', []):
                group_doc.setdefault('admins', []).append(new_user_id)
        elif member_role == 'document_manager':
            if new_user_id not in group_doc.get('documentManagers', []):
                group_doc.setdefault('documentManagers', []).append(new_user_id)
        
        group_doc["modifiedDate"] = datetime.utcnow().isoformat()

        cosmos_groups_container.upsert_item(group_doc)
        
        # Log activity for member addition
        try:
            activity_record = {
                'id': str(uuid.uuid4()),
                'activity_type': 'add_member_directly',
                'timestamp': datetime.utcnow().isoformat(),
                'added_by_user_id': user_id,
                'added_by_email': user_email,
                'added_by_role': role,
                'group_id': group_id,
                'group_name': group_doc.get('name', 'Unknown'),
                'member_user_id': new_user_id,
                'member_email': new_member_doc.get('email', ''),
                'member_name': new_member_doc.get('displayName', ''),
                'member_role': member_role,
                'description': f"{role} {user_email} added member {new_member_doc.get('displayName', '')} ({new_member_doc.get('email', '')}) to group {group_doc.get('name', group_id)} as {member_role}"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
        except Exception as log_error:
            debug_print(f"Failed to log member addition activity: {log_error}")
        
        # Create notification for the new member
        try:
            from functions_notifications import create_notification
            role_display = {
                'admin': 'Admin',
                'document_manager': 'Document Manager',
                'user': 'Member'
            }.get(member_role, 'Member')
            
            create_notification(
                user_id=new_user_id,
                notification_type='system_announcement',
                title='Added to Group',
                message=f"You have been added to the group '{group_doc.get('name', 'Unknown')}' as {role_display} by {user_email}.",
                link_url=f"/manage_group/{group_id}",
                metadata={
                    'group_id': group_id,
                    'group_name': group_doc.get('name', 'Unknown'),
                    'added_by': user_email,
                    'role': member_role
                }
            )
        except Exception as notif_error:
            debug_print(f"Failed to create member addition notification: {notif_error}")
        
        return jsonify({"message": "Member added", "success": True}), 200

    @app.route("/api/groups/<group_id>/members/<member_id>", methods=["DELETE"])
    @swagger_route(security=get_auth_security())
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
            removed_member_info = None
            updated_users = []
            for u in group_doc["users"]:
                if u["userId"] == member_id:
                    removed = True
                    removed_member_info = u
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
                # Log activity for self-removal
                from functions_activity_logging import log_group_member_deleted
                user_email = user_info.get("email", "unknown")
                member_name = removed_member_info.get('displayName', '') if removed_member_info else ''
                member_email = removed_member_info.get('email', '') if removed_member_info else ''
                description = f"Member {user_email} left group {group_doc.get('name', group_id)}"
                
                log_group_member_deleted(
                    removed_by_user_id=user_id,
                    removed_by_email=user_email,
                    removed_by_role='Member',
                    member_user_id=member_id,
                    member_email=member_email,
                    member_name=member_name,
                    group_id=group_id,
                    group_name=group_doc.get('name', 'Unknown'),
                    action='member_left_group',
                    description=description
                )
                
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
            removed_member_info = None
            updated_users = []
            for u in group_doc["users"]:
                if u["userId"] == member_id:
                    removed = True
                    removed_member_info = u
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
                # Log activity for admin/owner removal
                from functions_activity_logging import log_group_member_deleted
                user_email = user_info.get("email", "unknown")
                member_name = removed_member_info.get('displayName', '') if removed_member_info else ''
                member_email = removed_member_info.get('email', '') if removed_member_info else ''
                description = f"{role} {user_email} removed member {member_name} ({member_email}) from group {group_doc.get('name', group_id)}"
                
                log_group_member_deleted(
                    removed_by_user_id=user_id,
                    removed_by_email=user_email,
                    removed_by_role=role,
                    member_user_id=member_id,
                    member_email=member_email,
                    member_name=member_name,
                    group_id=group_id,
                    group_name=group_doc.get('name', 'Unknown'),
                    action='admin_removed_member',
                    description=description
                )
                
                return jsonify({"message": "User removed"}), 200
            else:
                return jsonify({"error": "User not found in group"}), 404


    @app.route("/api/groups/<group_id>/members/<member_id>", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
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
        user_email = user_info.get("email", "unknown")
        
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

        # Get member details for logging
        member_name = "Unknown"
        member_email = "unknown"
        for u in group_doc.get("users", []):
            if u.get("userId") == member_id:
                member_name = u.get("displayName", "Unknown")
                member_email = u.get("email", "unknown")
                break

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

        # Log activity for role change
        try:
            activity_record = {
                'id': str(uuid.uuid4()),
                'type': 'group_member_role_changed',
                'activity_type': 'update_member_role',
                'timestamp': datetime.utcnow().isoformat(),
                'changed_by_user_id': user_id,
                'changed_by_email': user_email,
                'changed_by_role': current_role,
                'group_id': group_id,
                'group_name': group_doc.get('name', 'Unknown'),
                'member_user_id': member_id,
                'member_email': member_email,
                'member_name': member_name,
                'old_role': target_role,
                'new_role': new_role,
                'description': f"{current_role} {user_email} changed {member_name} ({member_email}) role from {target_role} to {new_role} in group {group_doc.get('name', group_id)}"
            }
            cosmos_activity_logs_container.create_item(body=activity_record)
        except Exception as log_error:
            debug_print(f"Failed to log role change activity: {log_error}")
        
        # Create notification for the member whose role was changed
        try:
            from functions_notifications import create_notification
            create_notification(
                user_id=member_id,
                notification_type='system_announcement',
                title='Role Changed',
                message=f"Your role in group '{group_doc.get('name', 'Unknown')}' has been changed from {target_role} to {new_role} by {user_email}.",
                link_url=f"/manage_group/{group_id}",
                metadata={
                    'group_id': group_id,
                    'group_name': group_doc.get('name', 'Unknown'),
                    'changed_by': user_email,
                    'old_role': target_role,
                    'new_role': new_role
                }
            )
        except Exception as notif_error:
            debug_print(f"Failed to create role change notification: {notif_error}")

        return jsonify({"message": f"User {member_id} updated to {new_role}"}), 200

    @app.route("/api/groups/<group_id>/members", methods=["GET"])
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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
    @swagger_route(security=get_auth_security())
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

    @app.route("/api/groups/<group_id>/activity", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_group_activity(group_id):
        """
        GET /api/groups/<group_id>/activity
        Returns recent activity timeline for the group.
        Only accessible by owner and admins.
        """
        from functions_debug import debug_print
        
        info = get_current_user_info()
        user_id = info["userId"]
        
        group = find_group_by_id(group_id)
        if not group:
            return jsonify({"error": "Not found"}), 404

        # Check user is owner or admin (NOT document managers or regular members)
        is_owner = group["owner"]["id"] == user_id
        is_admin = user_id in (group.get("admins", []))
        
        if not (is_owner or is_admin):
            return jsonify({"error": "Forbidden - Only group owners and admins can view activity timeline"}), 403

        # Get pagination parameters
        limit = request.args.get('limit', 50, type=int)
        if limit not in [10, 20, 50]:
            limit = 50

        # Get recent activity
        query = f"""
            SELECT TOP {limit} *
            FROM a
            WHERE a.workspace_context.group_id = @groupId
            ORDER BY a.timestamp DESC
        """
        params = [{"name": "@groupId", "value": group_id}]
        
        debug_print(f"[GROUP_ACTIVITY] Group ID: {group_id}")
        debug_print(f"[GROUP_ACTIVITY] Query: {query}")
        debug_print(f"[GROUP_ACTIVITY] Params: {params}")
        
        activities = []
        try:
            activity_iter = cosmos_activity_logs_container.query_items(
                query=query,
                parameters=params,
                enable_cross_partition_query=True
            )
            activities = list(activity_iter)
            debug_print(f"[GROUP_ACTIVITY] Found {len(activities)} activity records")
        except Exception as e:
            debug_print(f"[GROUP_ACTIVITY] Error querying activity: {e}")
            return jsonify({"error": "Failed to retrieve activity"}), 500
        
        return jsonify(activities), 200

    @app.route("/api/groups/<group_id>/stats", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_group_stats(group_id):
        """
        GET /api/groups/<group_id>/stats
        Returns statistics for the group including documents, storage, tokens, and members.
        Only accessible by owner and admins.
        """
        from functions_debug import debug_print
        from datetime import datetime, timedelta
        
        info = get_current_user_info()
        user_id = info["userId"]
        
        group = find_group_by_id(group_id)
        if not group:
            return jsonify({"error": "Not found"}), 404

        # Check user is owner or admin
        is_owner = group["owner"]["id"] == user_id
        is_admin = user_id in (group.get("admins", []))
        
        if not (is_owner or is_admin):
            return jsonify({"error": "Forbidden"}), 403

        # Get metrics from group record
        metrics = group.get("metrics", {})
        document_metrics = metrics.get("document_metrics", {})
        
        total_documents = document_metrics.get("total_documents", 0)
        storage_used = document_metrics.get("storage_account_size", 0)
        ai_search_size = document_metrics.get("ai_search_size", 0)
        storage_account_size = document_metrics.get("storage_account_size", 0)

        # Get member count
        total_members = len(group.get("users", []))

        # Get token usage from activity logs (last 30 days)
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        
        debug_print(f"[GROUP_STATS] Group ID: {group_id}")
        debug_print(f"[GROUP_STATS] Start date: {thirty_days_ago}")
        
        token_query = """
            SELECT a.usage
            FROM a 
            WHERE a.workspace_context.group_id = @groupId 
            AND a.timestamp >= @startDate
            AND a.activity_type = 'token_usage'
        """
        token_params = [
            {"name": "@groupId", "value": group_id},
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
            debug_print(f"[GROUP_STATS] Total tokens accumulated: {total_tokens}")
        except Exception as e:
            debug_print(f"[GROUP_STATS] Error querying total tokens: {e}")

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
            WHERE a.workspace_context.group_id = @groupId
            AND a.timestamp >= @startDate
            AND a.activity_type = 'document_creation'
        """
        try:
            activity_iter = cosmos_activity_logs_container.query_items(
                query=doc_upload_query,
                parameters=token_params,
                enable_cross_partition_query=True
            )
            for item in activity_iter:
                timestamp = item.get("timestamp") or item.get("created_at")
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        day_date = dt.strftime("%m/%d")
                        if day_date in doc_activity_labels:
                            idx = doc_activity_labels.index(day_date)
                            doc_upload_data[idx] += 1
                    except Exception as e:
                        debug_print(f"[GROUP_STATS] Error parsing timestamp: {e}")
        except Exception as e:
            debug_print(f"[GROUP_STATS] Error querying document uploads: {e}")

        # Get document delete activity by day
        doc_delete_query = """
            SELECT a.timestamp, a.created_at
            FROM a
            WHERE a.workspace_context.group_id = @groupId
            AND a.timestamp >= @startDate
            AND a.activity_type = 'document_deletion'
        """
        try:
            delete_iter = cosmos_activity_logs_container.query_items(
                query=doc_delete_query,
                parameters=token_params,
                enable_cross_partition_query=True
            )
            for item in delete_iter:
                timestamp = item.get("timestamp") or item.get("created_at")
                if timestamp:
                    try:
                        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
                        day_date = dt.strftime("%m/%d")
                        if day_date in doc_activity_labels:
                            idx = doc_activity_labels.index(day_date)
                            doc_delete_data[idx] += 1
                    except Exception as e:
                        debug_print(f"[GROUP_STATS] Error parsing timestamp: {e}")
        except Exception as e:
            debug_print(f"[GROUP_STATS] Error querying document deletes: {e}")

        # Get token usage by day
        token_activity_query = """
            SELECT a.timestamp, a.created_at, a.usage
            FROM a
            WHERE a.workspace_context.group_id = @groupId
            AND a.timestamp >= @startDate
            AND a.activity_type = 'token_usage'
        """
        try:
            token_activity_iter = cosmos_activity_logs_container.query_items(
                query=token_activity_query,
                parameters=token_params,
                enable_cross_partition_query=True
            )
            for item in token_activity_iter:
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
                    except Exception as e:
                        debug_print(f"[GROUP_STATS] Error parsing timestamp: {e}")
        except Exception as e:
            debug_print(f"[GROUP_STATS] Error querying token usage: {e}")

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

        return jsonify(stats), 200
