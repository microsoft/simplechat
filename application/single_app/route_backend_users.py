# route_backend_users.py

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_backend_users(app):
    """
    This route will expose GET /api/userSearch?query=<searchTerm> which calls
    Microsoft Graph to find users by displayName, mail, userPrincipalName, etc.
    """

    @app.route("/api/userSearch", methods=["GET"])
    @login_required
    @user_required
    def api_user_search():
        query = request.args.get("query", "").strip()
        if not query:
            return jsonify([]), 200

        token = get_valid_access_token()
        if not token:
            return jsonify({"error": "Could not acquire access token"}), 401

        if AZURE_ENVIRONMENT == "usgovernment":
            user_endpoint = "https://graph.microsoft.us/v1.0/users"
        elif AZURE_ENVIRONMENT == "custom":
            user_endpoint = CUSTOM_GRAPH_URL_VALUE
        else:
            user_endpoint = "https://graph.microsoft.com/v1.0/users"
            
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        }

        filter_str = (
            f"startswith(displayName, '{query}') "
            f"or startswith(mail, '{query}') "
            f"or startswith(userPrincipalName, '{query}')"
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
    @login_required
    @user_required
    def api_get_user_info(user_id):
        """
        Get user info (email, display_name) by user_id (oid).
        """
        # Directly query Cosmos for the user document by id (oid)
        from config import cosmos_user_settings_container
        try:
            user_doc = cosmos_user_settings_container.read_item(
                item=user_id,
                partition_key=user_id
            )
            print(f"[DEBUG] /api/user/info/{user_id} → doc: {user_doc}", flush=True)
            return jsonify({
                "user_id": user_id,
                "email": user_doc.get("email", ""),
                "display_name": user_doc.get("display_name", "")
            }), 200
        except Exception as e:
            print(f"[ERROR] /api/user/info/{user_id} failed: {e}", flush=True)
            return jsonify({
                "error": f"User not found for oid {user_id}"
            }), 404
    
    @app.route('/api/user/settings', methods=['GET', 'POST'])
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
                allowed_keys = {'activeGroupOid', 'layoutPreference', 'splitSizesPreference', 'dockedSidebarHidden', 'darkModeEnabled', 'preferredModelDeployment', 'agents', 'plugins', "selected_agent", 'navLayout', 'profileImage', 'enable_agents'} # Add others as needed
                invalid_keys = set(settings_to_update.keys()) - allowed_keys
                if invalid_keys:
                    print(f"Warning: Received invalid settings keys: {invalid_keys}")
                    # Decide whether to ignore them or return an error
                    # To ignore: settings_to_update = {k: v for k, v in settings_to_update.items() if k in allowed_keys}
                    # To error: return jsonify({"error": f"Invalid settings keys provided: {', '.join(invalid_keys)}"}), 400


                # Call the updated function - it handles merging and timestamp
                success = update_user_settings(user_id, settings_to_update)

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
    @login_required
    @user_required
    def get_user_profile_image_api(user_id):
        """
        Get profile image for a specific user by user_id (oid).
        Returns only the profile image data to protect user privacy.
        """
        from config import cosmos_user_settings_container
        try:
            user_doc = cosmos_user_settings_container.read_item(
                item=user_id,
                partition_key=user_id
            )
            
            # Extract profile image from settings
            profile_image = user_doc.get("settings", {}).get("profileImage", None)
            
            return jsonify({
                "user_id": user_id,
                "profile_image": profile_image
            }), 200
            
        except Exception as e:
            print(f"[ERROR] /api/user/profile-image/{user_id} failed: {e}", flush=True)
            return jsonify({
                "error": f"User profile image not found for oid {user_id}",
                "profile_image": None
            }), 404
