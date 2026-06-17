# route_backend_users.py

from urllib.parse import quote

from config import *
from collaboration_models import (
    COLLABORATION_KIND,
    MEMBERSHIP_STATUS_ACCEPTED,
    MEMBERSHIP_STATUS_PENDING,
    get_collaboration_user_state_doc_id,
    normalize_collaboration_user,
)
from functions_appinsights import log_event
from functions_authentication import *
from functions_group import (
    check_group_status_allows_operation,
    get_user_groups,
    get_user_role_in_group,
    update_active_group_for_user,
)
from functions_public_workspaces import update_active_public_workspace_for_user
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security


PROFILE_LOOKUP_MEMBERSHIP_STATUSES = {
    MEMBERSHIP_STATUS_ACCEPTED,
    MEMBERSHIP_STATUS_PENDING,
}


def _escape_graph_odata_literal(value):
    return str(value or "").replace("'", "''")


def _build_user_info_response(user_id, display_name="", email="", user_principal_name=""):
    resolved_email = email or user_principal_name or ""
    return {
        "id": user_id,
        "user_id": user_id,
        "displayName": display_name or resolved_email or "",
        "display_name": display_name or resolved_email or "",
        "email": resolved_email,
        "mail": email or "",
        "userPrincipalName": user_principal_name or resolved_email,
    }


def _get_graph_user_info_by_id(user_id):
    normalized_user_id = str(user_id or "").strip()
    if not normalized_user_id:
        return None

    token = get_valid_access_token()
    if not token:
        return None

    user_endpoint = get_graph_endpoint(f"/users/{quote(normalized_user_id, safe='')}")
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json"
    }
    params = {
        "$select": "id,displayName,mail,userPrincipalName"
    }

    response = requests.get(user_endpoint, headers=headers, params=params)
    response.raise_for_status()
    user = response.json() or {}
    graph_user_id = user.get("id") or normalized_user_id
    return _build_user_info_response(
        graph_user_id,
        display_name=user.get("displayName", ""),
        email=user.get("mail", ""),
        user_principal_name=user.get("userPrincipalName", ""),
    )


def _normalize_user_lookup_id(value):
    return str(value or '').strip()


def _is_current_actor_admin():
    current_user = session.get('user') or {}
    roles = current_user.get('roles') or []
    return 'Admin' in roles


def _log_profile_relationship_check_error(check_name, actor_user_id, target_user_id, error):
    log_event(
        f'[UserProfile] {check_name} relationship check failed closed',
        extra={
            'actor_user_id': actor_user_id,
            'target_user_id': target_user_id,
            'error_type': type(error).__name__,
        },
        level=logging.WARNING,
        debug_only=True,
    )


def _has_shared_group_profile_relationship(actor_user_id, target_user_id):
    try:
        for group_doc in get_user_groups(actor_user_id):
            allowed, _ = check_group_status_allows_operation(group_doc, 'view')
            if not allowed:
                continue
            if get_user_role_in_group(group_doc, target_user_id):
                return True
    except Exception as ex:
        _log_profile_relationship_check_error('Group', actor_user_id, target_user_id, ex)

    return False


def _has_shared_document_profile_relationship(actor_user_id, target_user_id):
    actor_user_prefix = f'{actor_user_id},'
    target_user_prefix = f'{target_user_id},'
    query = """
        SELECT TOP 1 VALUE c.id
        FROM c
        WHERE IS_DEFINED(c.shared_user_ids)
        AND (
            (
                c.user_id = @actor_user_id
                AND (
                    ARRAY_CONTAINS(c.shared_user_ids, @target_user_id)
                    OR EXISTS(SELECT VALUE shared_user FROM shared_user IN c.shared_user_ids WHERE STARTSWITH(shared_user, @target_user_prefix))
                )
            )
            OR (
                c.user_id = @target_user_id
                AND (
                    ARRAY_CONTAINS(c.shared_user_ids, @actor_user_id)
                    OR EXISTS(SELECT VALUE shared_user FROM shared_user IN c.shared_user_ids WHERE STARTSWITH(shared_user, @actor_user_prefix))
                )
            )
        )
    """
    parameters = [
        {'name': '@actor_user_id', 'value': actor_user_id},
        {'name': '@target_user_id', 'value': target_user_id},
        {'name': '@actor_user_prefix', 'value': actor_user_prefix},
        {'name': '@target_user_prefix', 'value': target_user_prefix},
    ]

    try:
        matching_document_ids = list(cosmos_user_documents_container.query_items(
            query=query,
            parameters=parameters,
            enable_cross_partition_query=True,
        ))
        return bool(matching_document_ids)
    except Exception as ex:
        _log_profile_relationship_check_error('Document', actor_user_id, target_user_id, ex)

    return False


def _has_collaboration_profile_relationship(actor_user_id, target_user_id):
    query = """
        SELECT TOP 50 c.conversation_id
        FROM c
        WHERE c.user_id = @actor_user_id
        AND c.conversation_kind = @conversation_kind
        AND (
            c.membership_status = @accepted_status
            OR c.membership_status = @pending_status
        )
    """
    parameters = [
        {'name': '@actor_user_id', 'value': actor_user_id},
        {'name': '@conversation_kind', 'value': COLLABORATION_KIND},
        {'name': '@accepted_status', 'value': MEMBERSHIP_STATUS_ACCEPTED},
        {'name': '@pending_status', 'value': MEMBERSHIP_STATUS_PENDING},
    ]

    try:
        actor_states = list(cosmos_collaboration_user_state_container.query_items(
            query=query,
            parameters=parameters,
            partition_key=actor_user_id,
        ))
        for actor_state in actor_states:
            conversation_id = _normalize_user_lookup_id(actor_state.get('conversation_id'))
            if not conversation_id:
                continue

            try:
                target_state = cosmos_collaboration_user_state_container.read_item(
                    item=get_collaboration_user_state_doc_id(target_user_id, conversation_id),
                    partition_key=target_user_id,
                )
            except exceptions.CosmosResourceNotFoundError:
                continue

            target_status = _normalize_user_lookup_id(target_state.get('membership_status'))
            if target_status in PROFILE_LOOKUP_MEMBERSHIP_STATUSES:
                return True
    except Exception as ex:
        _log_profile_relationship_check_error('Collaboration', actor_user_id, target_user_id, ex)

    return False


def _authorize_user_profile_access(target_user_id):
    actor_user_id = _normalize_user_lookup_id(get_current_user_id())
    normalized_target_user_id = _normalize_user_lookup_id(target_user_id)

    if not actor_user_id:
        raise PermissionError('Authenticated user is required')
    if not normalized_target_user_id:
        raise LookupError('Target user is required')

    if actor_user_id == normalized_target_user_id:
        return actor_user_id, normalized_target_user_id
    if _is_current_actor_admin():
        return actor_user_id, normalized_target_user_id
    if _has_shared_group_profile_relationship(actor_user_id, normalized_target_user_id):
        return actor_user_id, normalized_target_user_id
    if _has_shared_document_profile_relationship(actor_user_id, normalized_target_user_id):
        return actor_user_id, normalized_target_user_id
    if _has_collaboration_profile_relationship(actor_user_id, normalized_target_user_id):
        return actor_user_id, normalized_target_user_id

    log_event(
        '[UserProfile] Denied cross-user profile lookup',
        extra={
            'actor_user_id': actor_user_id,
            'target_user_id': normalized_target_user_id,
        },
        level=logging.WARNING,
    )
    raise PermissionError('User profile access denied')


def _read_authorized_user_profile_document(target_user_id):
    actor_user_id, normalized_target_user_id = _authorize_user_profile_access(target_user_id)
    user_doc = cosmos_user_settings_container.read_item(
        item=normalized_target_user_id,
        partition_key=normalized_target_user_id,
    )
    return actor_user_id, normalized_target_user_id, user_doc


def _user_profile_not_found_response():
    return jsonify({'error': 'User not found or access denied'}), 404


def register_route_backend_users(app):
    """
    This route will expose GET /api/userSearch?query=<searchTerm> which calls
    Microsoft Graph to find users by displayName, mail, userPrincipalName, etc.
    """

    @app.route("/api/userSearch", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_user_search():
        query = request.args.get("query", "").strip()
        if not query:
            return jsonify([]), 200

        safe_query = _escape_graph_odata_literal(query)

        token = get_valid_access_token()
        if not token:
            return jsonify({"error": "Could not acquire access token"}), 401

        user_endpoint = get_graph_endpoint("/users")
            
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        filter_str = (
            f"startswith(displayName, '{safe_query}') "
            f"or startswith(mail, '{safe_query}') "
            f"or startswith(userPrincipalName, '{safe_query}')"
        )
        params = {
            "$filter": filter_str,
            "$top": 10,
            "$select": "id,displayName,mail,userPrincipalName"
        }

        try:
            response = requests.get(user_endpoint, headers=headers, params=params)
            response.raise_for_status() # Raise an exception for bad status codes (4xx or 5xx)

            user_results = response.json().get("value", [])
            results = []
            for user in user_results:
                email = user.get("mail") or user.get("userPrincipalName") or ""
                results.append({
                    "id": user.get("id"),
                    "displayName": user.get("displayName", "(no name)"),
                    "email": email
                })
            return jsonify(results), 200

        except requests.exceptions.RequestException as e:
            print(f"Graph API request failed: {e}")
            # Try to get more details from response if available
            error_details = "Unknown error"
            if e.response is not None:
                try:
                    error_details = e.response.json()
                except ValueError: # Handle cases where response is not JSON
                    error_details = e.response.text
            return jsonify({
                "error": "Graph API request failed",
                "details": error_details
            }), getattr(e.response, 'status_code', 500) # Use response status code if available

    @app.route("/api/user/info/<user_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_get_user_info(user_id):
        """
        Get user info (email, display_name) by user_id (oid).
        """
        try:
            _, normalized_user_id = _authorize_user_profile_access(user_id)
        except (LookupError, PermissionError):
            return _user_profile_not_found_response()

        try:
            user_doc = cosmos_user_settings_container.read_item(
                item=normalized_user_id,
                partition_key=normalized_user_id,
            )
            return jsonify(_build_user_info_response(
                normalized_user_id,
                display_name=user_doc.get("display_name", ""),
                email=user_doc.get("email", ""),
            )), 200
        except exceptions.CosmosResourceNotFoundError:
            pass
        except Exception as ex:
            log_event(
                '[UserProfile] Failed to load user info',
                extra={
                    'target_user_id': _normalize_user_lookup_id(user_id),
                    'error_type': type(ex).__name__,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )

        try:
            graph_user_info = _get_graph_user_info_by_id(normalized_user_id)
            if graph_user_info:
                return jsonify(graph_user_info), 200
        except requests.exceptions.RequestException as ex:
            log_event(
                "[Users] Graph user info lookup failed",
                level=logging.WARNING,
                extra={
                    "target_user_id": normalized_user_id,
                    "status_code": getattr(ex.response, "status_code", None),
                },
                debug_only=True,
            )

        return _user_profile_not_found_response()

    @app.route('/api/user/collaboration-suggestions', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def api_collaboration_suggestions():
        user_id = get_current_user_id()
        if not user_id:
            return jsonify({"error": "Unable to identify user"}), 401

        query = str(request.args.get('query') or '').strip().lower()
        recent_only = str(request.args.get('recent_only', 'false')).strip().lower() == 'true'

        try:
            requested_limit = int(request.args.get('limit', 8))
        except (TypeError, ValueError):
            requested_limit = 8
        limit = max(1, min(requested_limit, 20))

        user_settings_doc = get_user_settings(user_id) or {}
        recent_collaborators = ((user_settings_doc.get('settings') or {}).get('recentCollaborators') or [])

        suggestions = []
        seen_user_ids = set()

        def add_suggestion(raw_value, source_label):
            fallback_user_id = None
            if isinstance(raw_value, dict):
                fallback_user_id = raw_value.get('id')

            normalized_user = normalize_collaboration_user(raw_value, fallback_user_id=fallback_user_id)
            if not normalized_user:
                return

            normalized_user_id = normalized_user.get('user_id')
            if not normalized_user_id or normalized_user_id == user_id or normalized_user_id in seen_user_ids:
                return

            haystack = f"{normalized_user.get('display_name', '')} {normalized_user.get('email', '')}".strip().lower()
            if query and query not in haystack:
                return

            seen_user_ids.add(normalized_user_id)
            suggestions.append({
                'user_id': normalized_user_id,
                'display_name': normalized_user.get('display_name'),
                'email': normalized_user.get('email'),
                'source': source_label,
            })

        for recent_collaborator in recent_collaborators:
            add_suggestion(recent_collaborator, 'recent')
            if len(suggestions) >= limit:
                return jsonify({'results': suggestions[:limit]}), 200

        if not recent_only and query:
            user_query = (
                f'SELECT TOP {max(limit * 3, 12)} c.id, c.display_name, c.email FROM c '
                'WHERE c.id != @current_user_id AND '
                '((IS_DEFINED(c.display_name) AND CONTAINS(LOWER(c.display_name), @query)) '
                'OR (IS_DEFINED(c.email) AND CONTAINS(LOWER(c.email), @query)))'
            )
            local_results = list(cosmos_user_settings_container.query_items(
                query=user_query,
                parameters=[
                    {'name': '@current_user_id', 'value': user_id},
                    {'name': '@query', 'value': query},
                ],
                enable_cross_partition_query=True,
            ))
            for local_result in local_results:
                add_suggestion({
                    'id': local_result.get('id'),
                    'display_name': local_result.get('display_name'),
                    'email': local_result.get('email'),
                }, 'local')
                if len(suggestions) >= limit:
                    break

        return jsonify({'results': suggestions[:limit]}), 200
    
    @app.route('/api/user/settings', methods=['GET', 'POST'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required # Assuming this decorator confirms a valid user exists
    def user_settings():
        try:
            user_id = get_current_user_id()
            if not user_id: # Redundant if get_current_user_id raises error, but safe
                 return jsonify({"error": "Unable to identify user"}), 401
        except ValueError as e:
             # Handle case where get_current_user_id fails (e.g., session issue)
             print(f"Error getting user ID: {e}")
             return jsonify({"error": str(e)}), 401
        except Exception as e:
             # Catch other potential errors during user ID retrieval
             print(f"Unexpected error getting user ID: {e}")
             return jsonify({"error": "Internal server error identifying user"}), 500


        # --- Handle POST Request (Update Settings) ---
        if request.method == 'POST':
            try:
                # Expect JSON data, as sent by the fetch API in chat-layout.js
                data = request.get_json()

                if not data:
                    return jsonify({"error": "Missing JSON body"}), 400

                # The JS sends { settings: { key: value, ... } }
                # Extract the inner 'settings' dictionary
                settings_to_update = data.get('settings')

                if settings_to_update is None:
                     # Maybe the client sent the data flat? Handle for flexibility or error out.
                     # If you want to be strict:
                     return jsonify({"error": "Request body must contain a 'settings' object"}), 400
                     # If you want to be flexible (accept flat structure like {"activeGroupOid": "..."}):
                     # settings_to_update = data

                if not isinstance(settings_to_update, dict):
                    return jsonify({"error": "'settings' must be an object"}), 400

                # Basic validation could go here (e.g., check allowed keys, value types)
                # Example: Allowed keys
                allowed_keys = {
                    'activeGroupOid', 'layoutPreference', 'splitSizesPreference', 'dockedSidebarHidden', 
                    'darkModeEnabled', 'preferredModelDeployment', 'agents', 'plugins', "selected_agent", 
                    'navLayout', 'profileImage', 'enable_agents', 'streamingEnabled', 'reasoningEffortSettings',
                    'preferredModelId', 'dismissedMultiEndpointNotice',
                    # Public directory and workspace settings
                    'publicDirectorySavedLists', 'publicDirectorySettings', 'activePublicWorkspaceOid',
                    # Chat UI settings
                    'navbar_layout', 'chatLayout', 'showChatTitle', 'chatSplitSizes',
                    'deepResearchDefaultEnabled',
                    'sidebarToggleStyle', 'sidebarMenuState',
                    # Microphone permission settings
                    'microphonePermissionPreference', 'microphonePermissionState',
                    # Text-to-speech settings
                    'ttsEnabled', 'ttsVoice', 'ttsSpeed', 'ttsAutoplay',
                    # Tutorial visibility settings
                    'showTutorialButtons',
                    'recentCollaborators',
                    # Personal workspace settings managed by other backend/frontend flows
                    'personal_model_endpoints', 'tag_definitions',
                    # Retention settings kept for current and legacy profile payloads
                    'retention_policy', 'retention_policy_enabled', 'retention_policy_days',
                    # Metrics and other settings
                    'metrics', 'lastUpdated'
                } # Add others as needed
                invalid_keys = set(settings_to_update.keys()) - allowed_keys
                if invalid_keys:
                    print(f"Warning: Received invalid settings keys: {invalid_keys}")
                    settings_to_update = {
                        key: value
                        for key, value in settings_to_update.items()
                        if key in allowed_keys
                    }
                    if not settings_to_update:
                        return jsonify({"error": "No valid settings keys provided"}), 400


                settings_to_update = dict(settings_to_update)

                if "sidebarToggleStyle" in settings_to_update:
                    sidebar_toggle_style = str(settings_to_update.get("sidebarToggleStyle") or "large").strip().lower()
                    if sidebar_toggle_style not in {"large", "compact"}:
                        return jsonify({"error": "Invalid sidebar toggle style"}), 400
                    settings_to_update["sidebarToggleStyle"] = sidebar_toggle_style

                if "sidebarMenuState" in settings_to_update:
                    sidebar_menu_state = settings_to_update.get("sidebarMenuState")
                    allowed_sidebar_menu_keys = {
                        "workspaces", "support", "externalLinks", "adminSettings",
                        "controlCenter", "conversations"
                    }
                    if not isinstance(sidebar_menu_state, dict):
                        return jsonify({"error": "Invalid sidebar menu state"}), 400

                    normalized_sidebar_menu_state = {}
                    for key, value in sidebar_menu_state.items():
                        if key not in allowed_sidebar_menu_keys:
                            continue
                        if isinstance(value, bool):
                            normalized_sidebar_menu_state[key] = value
                        elif isinstance(value, str) and value.strip().lower() in {"true", "false"}:
                            normalized_sidebar_menu_state[key] = value.strip().lower() == "true"

                    settings_to_update["sidebarMenuState"] = normalized_sidebar_menu_state

                active_group_updated = False
                active_public_workspace_updated = False

                if "activeGroupOid" in settings_to_update:
                    requested_active_group = str(settings_to_update.pop("activeGroupOid") or "").strip()
                    if requested_active_group:
                        try:
                            update_active_group_for_user(requested_active_group, user_id=user_id)
                            active_group_updated = True
                        except LookupError:
                            return jsonify({"error": "Group not found"}), 404
                        except PermissionError:
                            return jsonify({"error": "You are not a member of this group"}), 403
                    else:
                        settings_to_update["activeGroupOid"] = requested_active_group

                if "activePublicWorkspaceOid" in settings_to_update:
                    requested_active_public_workspace = str(
                        settings_to_update.pop("activePublicWorkspaceOid") or ""
                    ).strip()
                    if requested_active_public_workspace:
                        try:
                            update_active_public_workspace_for_user(
                                user_id,
                                requested_active_public_workspace,
                            )
                            active_public_workspace_updated = True
                        except LookupError:
                            return jsonify({"error": "Workspace not found"}), 404
                    else:
                        settings_to_update["activePublicWorkspaceOid"] = requested_active_public_workspace

                # Call the updated function - it handles merging and timestamp
                success = True
                if settings_to_update:
                    success = update_user_settings(user_id, settings_to_update)
                elif active_group_updated or active_public_workspace_updated:
                    success = True

                if success:
                    return jsonify({"message": "User settings updated successfully"}), 200
                else:
                    # update_user_settings should ideally log the specific error
                    return jsonify({"error": "Failed to update settings"}), 500

            except Exception as e:
                # Catch potential JSON parsing errors or other unexpected issues
                print(f"Error processing POST /api/user/settings: {e}")
                return jsonify({"error": "Internal server error processing request"}), 500


        # --- Handle GET Request (Retrieve Settings) ---
        # This part remains largely the same as your original
        try:
            user_settings_data = get_user_settings(user_id) # This fetches the whole document
            # The frontend JS expects the document structure, including the 'settings' key inside it.
            return jsonify(user_settings_data), 200 # Return the full document or {} if not found
        except Exception as e:
            print(f"Error retrieving settings for user {user_id}: {e}")
            return jsonify({"error": "Failed to retrieve user settings"}), 500

    @app.route('/api/user/profile-image/<user_id>', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def get_user_profile_image_api(user_id):
        """
        Get profile image for a specific user by user_id (oid).
        Returns only the profile image data to protect user privacy.
        """
        try:
            _, normalized_user_id, user_doc = _read_authorized_user_profile_document(user_id)
            
            # Extract profile image from settings
            profile_image = user_doc.get("settings", {}).get("profileImage", None)
            
            return jsonify({
                "user_id": normalized_user_id,
                "profile_image": profile_image
            }), 200
        except (LookupError, PermissionError, exceptions.CosmosResourceNotFoundError):
            return jsonify({
                'error': 'User not found or access denied',
                'profile_image': None,
            }), 404
        except Exception as ex:
            log_event(
                '[UserProfile] Failed to load profile image',
                extra={
                    'target_user_id': _normalize_user_lookup_id(user_id),
                    'error_type': type(ex).__name__,
                },
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({'error': 'Failed to retrieve profile image', 'profile_image': None}), 500
