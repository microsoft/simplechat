# route_backend_groups.py

from config import *
from functions_authentication import *
from functions_chat_bootstrap_cache import bump_chat_bootstrap_global_cache_version
from functions_group import *
from functions_group_membership_audit import (
    log_group_member_role_change,
    notify_group_member_role_change,
)
from functions_notifications import create_notification
from functions_simplechat_operations import (
    add_group_member_for_current_user,
    create_group_for_current_user,
)
from functions_stats_windows import (
    build_stats_date_series,
    resolve_stats_time_window,
    stats_window_response_payload,
    timestamp_to_stats_date_key,
)
from functions_workspace_branding import (
    DEFAULT_WORKSPACE_HERO_COLOR,
    decode_workspace_logo_base64,
    get_workspace_logo_metadata,
    is_allowed_workspace_logo_file,
    normalize_workspace_hero_color,
    prepare_workspace_logo_image_for_storage,
)
from functions_settings import (
    get_settings,
    is_group_workspace_file_download_admin_enabled,
    is_group_workspace_file_download_enabled,
)
from swagger_wrapper import swagger_route, get_auth_security

# Roles that manage a group's settings, and so read its retention policy.
GROUP_DETAILS_SETTINGS_ROLES = ("Owner", "Admin")


def build_group_details_payload(group_doc, role, app_settings):
    """Project a group document for one of its members.

    The details route used to return the stored group document itself. That
    carried the group's model endpoints, with their credentials inline when Key
    Vault storage is off, along with the pending join requests, the member list
    and the Cosmos system fields, to every member. The projection returns only
    what the group management page reads, plus the caller's role. The retention
    policy is included for the Owners and Admins who manage it.
    """
    owner = group_doc.get("owner") or {}
    payload = {
        "id": group_doc.get("id"),
        "name": group_doc.get("name", ""),
        "description": group_doc.get("description", ""),
        "owner": {
            "id": owner.get("id", ""),
            "displayName": owner.get("displayName", ""),
            "email": owner.get("email", ""),
        },
        "admins": list(group_doc.get("admins") or []),
        "documentManagers": list(group_doc.get("documentManagers") or []),
        "status": group_doc.get("status", "active"),
        "createdDate": group_doc.get("createdDate"),
        "modifiedDate": group_doc.get("modifiedDate"),
        "heroColor": normalize_workspace_hero_color(
            group_doc.get("heroColor"),
            DEFAULT_WORKSPACE_HERO_COLOR,
        ),
        "disable_file_downloads": bool(group_doc.get("disable_file_downloads", False)),
        "file_downloads_admin_enabled": is_group_workspace_file_download_admin_enabled(
            app_settings,
            group_doc,
        ),
        "file_downloads_enabled": is_group_workspace_file_download_enabled(
            app_settings,
            group_doc,
        ),
        "userRole": role,
    }
    payload.update(get_workspace_logo_metadata(group_doc))
    if role in GROUP_DETAILS_SETTINGS_ROLES:
        payload["retention_policy"] = dict(group_doc.get("retention_policy") or {})
    return payload


# The classic membership routes write through the group-document guard, so a
# concurrent change is kept and a group deleted mid-write is not recreated. A group
# that keeps changing is the one response those routes did not have before.
GROUP_WRITE_CONFLICT_RESPONSE = {
    "error": "The group changed while this change was being saved. Try again.",
    "error_code": "group_write_conflict",
}


class _ClassicResponse(Exception):
    """A classic route's own response, raised from inside a guarded change."""

    def __init__(self, payload, status):
        super().__init__(status)
        self.payload = payload
        self.status = status


def _guarded_group_write(group_id, apply_changes, *, cache_reason):
    """Run a classic route's change through ``update_group_document_with_etag_guard``.

    ``apply_changes`` re-checks the route's rules on each fresh copy and raises
    ``_ClassicResponse`` with the route's own refusal. Returns ``(committed, None)``
    after a commit, or ``(None, response)`` with that refusal, the classic 404 for a
    group missing or deleted mid-write, or a 409 for a group that keeps changing.
    """
    try:
        committed = update_group_document_with_etag_guard(group_id, apply_changes, cache_reason=cache_reason)
    except _ClassicResponse as refusal:
        return None, (jsonify(refusal.payload), refusal.status)
    except GroupDocumentWriteConflict:
        return None, (jsonify(GROUP_WRITE_CONFLICT_RESPONSE), 409)
    if committed is None:
        return None, (jsonify({"error": "Group not found"}), 404)
    return committed, None


def register_route_backend_groups(bp):
    """
    Register all group-related API endpoints under '/api/groups/...'
    """

    @bp.route("/api/groups/discover", methods=["GET"])
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

        all_items = discover_group_records(search_query)

        results = []
        for g in all_items:
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

    @bp.route("/api/groups", methods=["GET"])
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

            # --- Get active group ID through the authorization helper ---
            try:
                db_active_group_id = require_active_group(user_id)
            except (ValueError, LookupError, PermissionError):
                db_active_group_id = ""

            # --- Map results ---
            mapped_results = []
            for g in paginated_groups:
                role = get_user_role_in_group(g, user_id)
                logo_metadata = get_workspace_logo_metadata(g)
                owner = g.get("owner", {}) or {}
                mapped_results.append({
                    "id": g["id"],
                    "name": g.get("name", "Untitled Group"), # Provide default name
                    "description": g.get("description", ""),
                    "owner": {
                        "displayName": owner.get("displayName", ""),
                        "email": owner.get("email", ""),
                    },
                    "heroColor": normalize_workspace_hero_color(
                        g.get("heroColor"),
                        DEFAULT_WORKSPACE_HERO_COLOR,
                    ),
                    **logo_metadata,
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


    @bp.route("/api/groups", methods=["POST"])
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
            group_doc = create_group_for_current_user(name, description)
            return jsonify({"id": group_doc["id"], "name": group_doc["name"]}), 201
        except PermissionError as ex:
            return jsonify({"error": str(ex)}), 403
        except Exception as ex:
            return jsonify({"error": str(ex)}), 400

    @bp.route("/api/groups/<group_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_group_details(group_id):
        """
        GET /api/groups/<group_id>
        Returns the full group details for that group.
        """        
        user_info = get_current_user_info()
        user_id = user_info["userId"]

        group_doc = find_group_by_id(group_id)
        
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        role = get_user_role_in_group(group_doc, user_id)
        if not role:
            return jsonify({"error": "You are not a member of this group"}), 403

        return jsonify(build_group_details_payload(group_doc, role, get_settings())), 200

    @bp.route("/api/groups/<group_id>/download-settings", methods=["PATCH"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_update_group_download_settings(group_id):
        user_info = get_current_user_info()
        user_id = user_info["userId"]

        try:
            assert_group_role(user_id, group_id, allowed_roles=("Owner", "Admin"))
        except LookupError:
            return jsonify({"error": "Group not found"}), 404
        except PermissionError:
            return jsonify({"error": "Only group owners and admins can update download settings"}), 403

        group_doc = find_group_by_id(group_id)
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if not is_group_workspace_file_download_admin_enabled(get_settings(), group_doc):
            return jsonify({
                "error": "File downloads have not been enabled for this group by an administrator"
            }), 403

        data = request.get_json(silent=True) or {}
        group_doc["disable_file_downloads"] = bool(data.get("disable_file_downloads", False))
        group_doc["modifiedDate"] = datetime.utcnow().isoformat()
        try:
            cosmos_groups_container.upsert_item(group_doc)
            bump_chat_bootstrap_global_cache_version(reason="group_updated")
        except exceptions.CosmosHttpResponseError as ex:
            return jsonify({"error": str(ex)}), 400

        return jsonify({
            "success": True,
            "message": "Download settings updated",
            "disable_file_downloads": group_doc["disable_file_downloads"],
        }), 200

    @bp.route("/api/groups/<group_id>", methods=["DELETE"])
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

    @bp.route("/api/groups/<group_id>", methods=["PATCH", "PUT"])
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
        hero_color = normalize_workspace_hero_color(
            data.get("heroColor"),
            group_doc.get("heroColor", DEFAULT_WORKSPACE_HERO_COLOR),
        )

        group_doc["name"] = name
        group_doc["description"] = description
        group_doc["heroColor"] = hero_color
        group_doc["modifiedDate"] = datetime.utcnow().isoformat()
        try:
            cosmos_groups_container.upsert_item(group_doc)
        except exceptions.CosmosHttpResponseError as ex:
            return jsonify({"error": str(ex)}), 400

        bump_chat_bootstrap_global_cache_version(reason="group_updated")
        return jsonify({"message": "Group updated", "id": group_id}), 200

    @bp.route("/api/groups/<group_id>/logo", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_get_group_logo(group_id):
        user_info = get_current_user_info()
        user_id = user_info["userId"]

        group_doc = find_group_by_id(group_id)
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if not get_user_role_in_group(group_doc, user_id):
            return jsonify({"error": "You are not a member of this group"}), 403

        logo_base64 = str(group_doc.get("logoBase64") or "").strip()
        if not logo_base64:
            return jsonify({"error": "Group logo not found"}), 404

        try:
            logo_bytes = decode_workspace_logo_base64(logo_base64)
        except (ValueError, TypeError):
            return jsonify({"error": "Stored group logo is invalid"}), 500

        return send_file(
            BytesIO(logo_bytes),
            mimetype="image/png",
            max_age=3600,
            download_name="group-logo.png",
        )

    @bp.route("/api/groups/<group_id>/logo", methods=["POST"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def api_upload_group_logo(group_id):
        user_info = get_current_user_info()
        user_id = user_info["userId"]

        group_doc = find_group_by_id(group_id)
        if not group_doc:
            return jsonify({"error": "Group not found"}), 404

        if group_doc["owner"]["id"] != user_id:
            return jsonify({"error": "Only the owner can update the group logo"}), 403

        logo_file = request.files.get("logo_file")
        if not logo_file or not logo_file.filename:
            return jsonify({"error": "No logo file provided"}), 400

        if not is_allowed_workspace_logo_file(logo_file.filename):
            return jsonify({"error": "Unsupported image type. Allowed: png, jpg, jpeg"}), 400

        try:
            processed_logo = prepare_workspace_logo_image_for_storage(
                logo_file.read(),
                logo_file.filename,
            )
        except (ValueError, OSError) as ex:
            return jsonify({"error": str(ex)}), 400

        current_logo_version = get_workspace_logo_metadata(group_doc)["logoVersion"]
        group_doc["logoBase64"] = processed_logo["base64_str"]
        group_doc["logoVersion"] = current_logo_version + 1
        group_doc["modifiedDate"] = datetime.utcnow().isoformat()

        try:
            cosmos_groups_container.upsert_item(group_doc)
        except exceptions.CosmosHttpResponseError as ex:
            return jsonify({"error": str(ex)}), 400

        return jsonify({
            "message": "Group logo updated",
            "logoVersion": group_doc["logoVersion"],
        }), 200

    @bp.route("/api/groups/setActive", methods=["PATCH"])
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

    @bp.route("/api/groups/<group_id>/requests", methods=["POST"])
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

        def apply(group_doc):
            existing_role = get_user_role_in_group(group_doc, user_id)
            if existing_role:
                raise _ClassicResponse({"error": "User is already a member"}, 400)

            pending_users = group_doc.get("pendingUsers") or []
            for p in pending_users:
                if p["userId"] == user_id:
                    raise _ClassicResponse({"error": "User has already requested to join"}, 400)

            group_doc["pendingUsers"] = [*pending_users, {
                "userId": user_id,
                "email": user_info["email"],
                "displayName": user_info["displayName"]
            }]
            group_doc["modifiedDate"] = datetime.utcnow().isoformat()
            return group_doc

        _committed, refusal = _guarded_group_write(group_id, apply, cache_reason=None)
        if refusal:
            return refusal

        return jsonify({"message": "Membership request created"}), 201

    @bp.route("/api/groups/<group_id>/requests", methods=["GET"])
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

    @bp.route("/api/groups/<group_id>/requests/<request_id>", methods=["PATCH"])
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
        outcome = {}

        def apply(group_doc):
            role = get_user_role_in_group(group_doc, user_id)
            if role not in ["Owner", "Admin"]:
                raise _ClassicResponse({"error": "Only the owner or admin can approve/reject requests"}, 403)

            data = request.get_json()
            action = data.get("action")
            if action not in ["approve", "reject"]:
                raise _ClassicResponse(
                    {"error": "Invalid or missing 'action'. Must be 'approve' or 'reject'."}, 400,
                )

            pending_list = group_doc.get("pendingUsers", [])
            user_index = None
            for i, pending_user in enumerate(pending_list):
                if pending_user["userId"] == request_id:
                    user_index = i
                    break
            if user_index is None:
                raise _ClassicResponse({"error": "Request not found"}, 404)

            if action == "approve":
                member_to_add = pending_list.pop(user_index)
                group_doc["users"].append(member_to_add)
                outcome["message"] = "User approved and added as a member"
            else:
                pending_list.pop(user_index)
                outcome["message"] = "User rejected"
            outcome["action"] = action

            group_doc["pendingUsers"] = pending_list
            group_doc["modifiedDate"] = datetime.utcnow().isoformat()
            return group_doc

        # Only an approval bumps the cache, and the action is read inside the change,
        # after the role check, as it always was, so the bump follows the commit.
        _committed, refusal = _guarded_group_write(group_id, apply, cache_reason=None)
        if refusal:
            return refusal
        if outcome["action"] == "approve":
            bump_chat_bootstrap_global_cache_version(reason="group_member_request_approved")

        return jsonify({"message": outcome["message"]}), 200

    @bp.route("/api/groups/<group_id>/members", methods=["POST"])
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
        data = request.get_json()
        try:
            result = add_group_member_for_current_user(
                group_id=group_id,
                user_id=data.get("userId", ""),
                email=data.get("email", ""),
                display_name=data.get("displayName", ""),
                role=data.get("role", "user"),
            )
            return jsonify({"message": result.get("message", "Member added"), "success": True}), 200
        except PermissionError as exc:
            return jsonify({"error": str(exc)}), 403
        except LookupError as exc:
            return jsonify({"error": str(exc)}), 404
        except ValueError as exc:
            return jsonify({"error": str(exc)}), 400
        except GroupDocumentWriteConflict:
            return jsonify(GROUP_WRITE_CONFLICT_RESPONSE), 409

    @bp.route("/api/groups/<group_id>/members/<member_id>", methods=["DELETE"])
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
        leaving = user_id == member_id
        not_found = {"error": "You are not in this group"} if leaving else {"error": "User not found in group"}
        outcome = {}

        def apply(group_doc):
            if leaving:
                if group_doc["owner"]["id"] == user_id:
                    raise _ClassicResponse({"error": "The owner cannot leave the group. "
                                                     "Transfer ownership or delete the group."}, 403)
                outcome["role"] = None
            else:
                role = get_user_role_in_group(group_doc, user_id)
                if role not in ["Owner", "Admin"]:
                    raise _ClassicResponse({"error": "Only the owner or admin can remove other members"}, 403)
                if member_id == group_doc["owner"]["id"]:
                    raise _ClassicResponse({"error": "Cannot remove the group owner"}, 403)
                outcome["role"] = role

            removed_member_info = None
            updated_users = []
            for u in group_doc["users"]:
                if u["userId"] == member_id:
                    removed_member_info = u
                    continue
                updated_users.append(u)
            changed = removed_member_info is not None
            group_doc["users"] = updated_users

            if member_id in group_doc.get("admins", []):
                group_doc["admins"].remove(member_id)
                changed = True
            if member_id in group_doc.get("documentManagers", []):
                group_doc["documentManagers"].remove(member_id)
                changed = True

            # Nothing to remove: answer the classic 404 without writing.
            if not changed:
                raise _ClassicResponse(not_found, 404)
            outcome["removed_member_info"] = removed_member_info
            group_doc["modifiedDate"] = datetime.utcnow().isoformat()
            return group_doc

        committed, refusal = _guarded_group_write(group_id, apply, cache_reason=None)
        if refusal:
            return refusal

        removed_member_info = outcome["removed_member_info"]
        if removed_member_info is None:
            # Only a stale admins or documentManagers entry was cleaned up.
            return jsonify(not_found), 404

        bump_chat_bootstrap_global_cache_version(reason="group_member_removed")
        from functions_activity_logging import log_group_member_deleted
        user_email = user_info.get("email", "unknown")
        member_name = removed_member_info.get('displayName', '')
        member_email = removed_member_info.get('email', '')
        if leaving:
            removed_by_role, action, message = 'Member', 'member_left_group', "You have left the group"
            description = f"Member {user_email} left group {committed.get('name', group_id)}"
        else:
            removed_by_role, action, message = outcome["role"], 'admin_removed_member', "User removed"
            description = (
                f"{removed_by_role} {user_email} removed member {member_name} ({member_email}) "
                f"from group {committed.get('name', group_id)}"
            )

        log_group_member_deleted(
            removed_by_user_id=user_id,
            removed_by_email=user_email,
            removed_by_role=removed_by_role,
            member_user_id=member_id,
            member_email=member_email,
            member_name=member_name,
            group_id=group_id,
            group_name=committed.get('name', 'Unknown'),
            action=action,
            description=description
        )

        return jsonify({"message": message}), 200


    @bp.route("/api/groups/<group_id>/members/<member_id>", methods=["PATCH"])
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
        outcome = {}

        def apply(group_doc):
            current_role = get_user_role_in_group(group_doc, user_id)
            if current_role not in ["Owner", "Admin"]:
                raise _ClassicResponse({"error": "Only the owner or admin can update roles"}, 403)

            data = request.get_json()
            new_role = data.get("role")
            if new_role not in ["Admin", "DocumentManager", "User"]:
                raise _ClassicResponse({"error": "Invalid role. Must be Admin, DocumentManager, or User"}, 400)

            target_role = get_user_role_in_group(group_doc, member_id)
            if not target_role:
                raise _ClassicResponse({"error": "Member is not in the group"}, 404)

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

            group_doc["modifiedDate"] = datetime.utcnow().isoformat()
            outcome.update(
                current_role=current_role, new_role=new_role, target_role=target_role,
                member_name=member_name, member_email=member_email,
            )
            return group_doc

        group_doc, refusal = _guarded_group_write(group_id, apply, cache_reason="group_member_role_updated")
        if refusal:
            return refusal

        log_group_member_role_change(
            group_id=group_id,
            group_doc=group_doc,
            changed_by_user_id=user_id,
            changed_by_email=user_email,
            changed_by_role=outcome["current_role"],
            member_id=member_id,
            member_email=outcome["member_email"],
            member_name=outcome["member_name"],
            old_role=outcome["target_role"],
            new_role=outcome["new_role"],
        )
        notify_group_member_role_change(
            group_id=group_id,
            group_doc=group_doc,
            member_id=member_id,
            changed_by_email=user_email,
            old_role=outcome["target_role"],
            new_role=outcome["new_role"],
        )

        return jsonify({"message": f"User {member_id} updated to {outcome['new_role']}"}), 200

    @bp.route("/api/groups/<group_id>/members", methods=["GET"])
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

    @bp.route("/api/groups/<group_id>/transferOwnership", methods=["PATCH"])
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

        def apply(group_doc):
            if group_doc["owner"]["id"] != user_id:
                raise _ClassicResponse({"error": "Only the current owner can transfer ownership"}, 403)

            matching_member = None
            for m in group_doc["users"]:
                if m["userId"] == new_owner_id:
                    matching_member = m
                    break
            if not matching_member:
                raise _ClassicResponse({"error": "The specified new owner is not a member of the group"}, 400)

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
            return group_doc

        _committed, refusal = _guarded_group_write(group_id, apply, cache_reason="group_ownership_transferred")
        if refusal:
            return refusal

        return jsonify({"message": "Ownership transferred successfully"}), 200

    @bp.route("/api/groups/<group_id>/fileCount", methods=["GET"])
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

    @bp.route("/api/groups/<group_id>/activity", methods=["GET"])
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

    @bp.route("/api/groups/<group_id>/stats", methods=["GET"])
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

        try:
            stats_window = resolve_stats_time_window(request.args)
        except ValueError as ex:
            return jsonify({"error": str(ex)}), 400

        # Get metrics from group record
        metrics = group.get("metrics", {})
        document_metrics = metrics.get("document_metrics", {})
        
        total_documents = document_metrics.get("total_documents", 0)
        storage_used = document_metrics.get("storage_account_size", 0)
        ai_search_size = document_metrics.get("ai_search_size", 0)
        storage_account_size = document_metrics.get("storage_account_size", 0)

        # Get member count
        total_members = len(group.get("users", []))

        start_date = stats_window['start_date_iso']
        end_date = stats_window['end_date_iso']
        
        debug_print(f"[GROUP_STATS] Group ID: {group_id}")
        debug_print(f"[GROUP_STATS] Start date: {start_date}")
        debug_print(f"[GROUP_STATS] End date: {end_date}")
        
        token_query = """
            SELECT a.usage
            FROM a 
            WHERE a.workspace_context.group_id = @groupId 
            AND (
                (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate)
                OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate)
            )
            AND a.activity_type = 'token_usage'
        """
        token_params = [
            {"name": "@groupId", "value": group_id},
            {"name": "@startDate", "value": start_date},
            {"name": "@endDate", "value": end_date}
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
        date_series = build_stats_date_series(stats_window['start_date'], stats_window['end_date'])
        date_index_by_key = {}
        
        for index, day in enumerate(date_series):
            date_index_by_key[day['date']] = index
            doc_activity_labels.append(day['label'])
            token_usage_labels.append(day['label'])
            doc_upload_data.append(0)
            doc_delete_data.append(0)
            token_usage_data.append(0)

        # Get document upload activity by day
        doc_upload_query = """
            SELECT a.timestamp, a.created_at
            FROM a
            WHERE a.workspace_context.group_id = @groupId
            AND (
                (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate)
                OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate)
            )
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
                    date_key = timestamp_to_stats_date_key(timestamp)
                    idx = date_index_by_key.get(date_key)
                    if idx is not None:
                        doc_upload_data[idx] += 1
        except Exception as e:
            debug_print(f"[GROUP_STATS] Error querying document uploads: {e}")

        # Get document delete activity by day
        doc_delete_query = """
            SELECT a.timestamp, a.created_at
            FROM a
            WHERE a.workspace_context.group_id = @groupId
            AND (
                (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate)
                OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate)
            )
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
                    date_key = timestamp_to_stats_date_key(timestamp)
                    idx = date_index_by_key.get(date_key)
                    if idx is not None:
                        doc_delete_data[idx] += 1
        except Exception as e:
            debug_print(f"[GROUP_STATS] Error querying document deletes: {e}")

        # Get token usage by day
        token_activity_query = """
            SELECT a.timestamp, a.created_at, a.usage
            FROM a
            WHERE a.workspace_context.group_id = @groupId
            AND (
                (IS_DEFINED(a.timestamp) AND a.timestamp >= @startDate AND a.timestamp <= @endDate)
                OR (IS_DEFINED(a.created_at) AND a.created_at >= @startDate AND a.created_at <= @endDate)
            )
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
                    date_key = timestamp_to_stats_date_key(timestamp)
                    idx = date_index_by_key.get(date_key)
                    if idx is not None:
                        usage = item.get("usage", {})
                        tokens = usage.get("total_tokens", 0)
                        token_usage_data[idx] += tokens
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
            },
            "dateRange": [day['date'] for day in date_series],
            "window": stats_window_response_payload(stats_window)
        }

        return jsonify(stats), 200
