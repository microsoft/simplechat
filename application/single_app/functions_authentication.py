# functions_authentication.py

from config import *
from functions_settings import *

def _load_cache():
    """Loads the MSAL token cache from the Flask session."""
    cache = SerializableTokenCache()
    if session.get("token_cache"):
        try:
            cache.deserialize(session["token_cache"])
        except Exception as e:
            # Handle potential corruption or format issues gracefully
            print(f"Warning: Could not deserialize token cache: {e}. Starting fresh.")
            session.pop("token_cache", None) # Clear corrupted cache
    return cache

def _save_cache(cache):
    """Saves the MSAL token cache back into the Flask session if it has changed."""
    if cache.has_state_changed:
        try:
            session["token_cache"] = cache.serialize()
        except Exception as e:
            print(f"Error: Could not serialize token cache: {e}")
            # Decide how to handle this, maybe clear cache or log extensively
            # session.pop("token_cache", None) # Option: Clear on serialization failure

def _build_msal_app(cache=None):
    """Builds the MSAL ConfidentialClientApplication, optionally initializing with a cache."""
    return ConfidentialClientApplication(
        CLIENT_ID,
        authority=AUTHORITY,
        client_credential=CLIENT_SECRET,
        token_cache=cache  # Pass the cache instance here
    )


def get_valid_access_token(scopes=None):
    """
    Gets a valid access token for the current user.
    Tries MSAL cache first, then uses refresh token if needed.
    Returns the access token string or None if refresh failed or user not logged in.
    """
    if "user" not in session:
        print("get_valid_access_token: No user in session.")
        return None # User not logged in

    required_scopes = scopes or SCOPE # Use default SCOPE if none provided

    msal_app = _build_msal_app(cache=_load_cache())
    user_info = session.get("user", {})
    # MSAL uses home_account_id which combines oid and tid
    # Construct it carefully based on your id_token_claims structure
    # Assuming 'oid' is the user's object ID and 'tid' is the tenant ID in claims
    home_account_id = f"{user_info.get('oid')}.{user_info.get('tid')}"

    accounts = msal_app.get_accounts(username=user_info.get('preferred_username')) # Or use home_account_id if available reliably
    account = None
    if accounts:
        # Find the correct account if multiple exist (usually only one for web apps)
        # Prioritize matching home_account_id if available
        for acc in accounts:
            if acc.get('home_account_id') == home_account_id:
                 account = acc
                 break
        if not account:
             account = accounts[0] # Fallback to first account if no perfect match
             print(f"Warning: Using first account found ({account.get('username')}) as home_account_id match failed.")

    if account:
        # Try to get token silently (checks cache, then uses refresh token)
        result = msal_app.acquire_token_silent(required_scopes, account=account)
        _save_cache(msal_app.token_cache) # Save cache state AFTER attempt

        if result and "access_token" in result:
            # Optional: Check expiry if you want fine-grained control, but MSAL usually handles it
            # expires_in = result.get('expires_in', 0)
            # if expires_in > 60: # Check if token is valid for at least 60 seconds
            #     print("get_valid_access_token: Token acquired silently.")
            #     return result['access_token']
            # else:
            #     print("get_valid_access_token: Silent token expired or about to expire.")
            #     # MSAL should have refreshed, but if not, fall through
            print(f"get_valid_access_token: Token acquired silently for scopes: {required_scopes}")
            return result['access_token']
        else:
            # acquire_token_silent failed (e.g., refresh token expired, needs interaction)
            print("get_valid_access_token: acquire_token_silent failed. Needs re-authentication.")
            # Log the specific error if available in result
            if result and ('error' in result or 'error_description' in result):
                print(f"MSAL Error: {result.get('error')}, Description: {result.get('error_description')}")
            # Optionally clear session or specific keys if refresh consistently fails
            # session.pop("token_cache", None)
            # session.pop("user", None)
            return None # Indicate failure to get a valid token

    else:
        print("get_valid_access_token: No matching account found in MSAL cache.")
        # This might happen if the cache was cleared or the user logged in differently
        return None # Cannot acquire token without an account context
    

def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if "user" not in session:
            is_api_request = (
                request.accept_mimetypes.accept_json and
                not request.accept_mimetypes.accept_html
            ) or request.path.startswith('/api/')

            if is_api_request:
                print(f"API request to {request.path} blocked (401 Unauthorized). No valid session.")
                return jsonify({"error": "Unauthorized", "message": "Authentication required"}), 401
            else:
                print(f"Browser request to {request.path} redirected ta login. No valid session.")
                return redirect(url_for('login'))

        return f(*args, **kwargs)
    return decorated_function

def user_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user', {})
        if 'roles' not in user or ('User' not in user['roles'] and 'Admin' not in user['roles']):
             if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html or request.path.startswith('/api/'):
                  return jsonify({"error": "Forbidden", "message": "Insufficient permissions (User/Admin role required)"}), 403
             else:
                  return "Forbidden", 403
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user', {})
        if 'roles' not in user or 'Admin' not in user['roles']:
             if request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html or request.path.startswith('/api/'):
                  return jsonify({"error": "Forbidden", "message": "Insufficient permissions (Admin role required)"}), 403
             else:
                  return "Forbidden", 403
        return f(*args, **kwargs)
    return decorated_function

def feedback_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user', {})
        settings = get_settings()
        require_member_of_feedback_admin = settings.get("require_member_of_feedback_admin", False)

        if require_member_of_feedback_admin:
            if 'roles' not in user or 'FeedbackAdmin' not in user['roles']:
                 is_api_request = (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html) or request.path.startswith('/api/')
                 if is_api_request:
                      return jsonify({"error": "Forbidden", "message": "Insufficient permissions (FeedbackAdmin role required)"}), 403
                 else:
                      return "Forbidden: FeedbackAdmin role required", 403
        return f(*args, **kwargs)
    return decorated_function
    
def safety_violation_admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user', {})
        settings = get_settings()
        require_member_of_safety_violation_admin = settings.get("require_member_of_safety_violation_admin", False)

        if require_member_of_safety_violation_admin:
            if 'roles' not in user or 'SafetyViolationAdmin' not in user['roles']:
                is_api_request = (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html) or request.path.startswith('/api/')
                if is_api_request:
                    return jsonify({"error": "Forbidden", "message": "Insufficient permissions (SafetyViolationAdmin role required)"}), 403
                else:
                    return "Forbidden: SafetyViolationAdmin role required", 403
        return f(*args, **kwargs)
    return decorated_function

def create_group_role_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user', {})
        settings = get_settings()
        require_member_of_create_group = settings.get("require_member_of_create_group", False)

        if require_member_of_create_group:
            if 'roles' not in user or 'CreateGroups' not in user['roles']:
                is_api_request = (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html) or request.path.startswith('/api/')
                if is_api_request:
                    return jsonify({"error": "Forbidden", "message": "Insufficient permissions (CreateGroups role required)"}), 403
                else:
                    return "Forbidden: CreateGroups role required", 403
        return f(*args, **kwargs)
    return decorated_function
    
def create_public_workspace_role_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user = session.get('user', {})
        settings = get_settings()
        require_member_of_create_public_workspace = settings.get("require_member_of_create_public_workspace", False)

        if require_member_of_create_public_workspace:
            if 'roles' not in user or 'CreatePublicWorkspaces' not in user['roles']:
                is_api_request = (request.accept_mimetypes.accept_json and not request.accept_mimetypes.accept_html) or request.path.startswith('/api/')
                if is_api_request:
                    return jsonify({"error": "Forbidden", "message": "Insufficient permissions (CreatePublicWorkspaces role required)"}), 403
                else:
                    return "Forbidden: CreatePublicWorkspaces role required", 403
        return f(*args, **kwargs)
    return decorated_function

def get_current_user_id():
    user = session.get('user')
    if user:
        return user.get('oid')
    return None

def get_current_user_info():
    user = session.get("user")
    if not user:
        return None
    return {
        "userId": user.get("oid"), 
        "email": user.get("preferred_username") or user.get("email"),
        "displayName": user.get("name")
    }
