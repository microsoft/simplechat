# functions_authentication.py

from config import *
from functions_settings import *

# Default redirect path for OAuth consent flow (must match your Azure AD app registration)
REDIRECT_PATH = getattr(globals(), 'REDIRECT_PATH', '/getAToken')
#REDIRECT_PATH = getattr(globals(), 'REDIRECT_PATH', '/.auth/login/aad/callback')

def build_front_door_urls(front_door_url):
    """
    Build home and login redirect URLs from a Front Door base URL.
    
    Args:
        front_door_url (str): The base Front Door URL (e.g., https://myapp.azurefd.net)
    
    Returns:
        tuple: (home_url, login_redirect_url)
    """
    if not front_door_url:
        return None, None
    
    # Remove trailing slash if present
    base_url = front_door_url.rstrip('/')
    
    # Build the URLs
    home_url = base_url
    login_redirect_url = f"{base_url}/getAToken"
    
    return home_url, login_redirect_url

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


# Helper: Generate a consent URL for user to grant permissions
def get_consent_url(msal_app=None, scopes=None, redirect_uri=None, state=None, prompt="consent"):
    msal_app = _build_msal_app() if msal_app is None else msal_app
    required_scopes = scopes or SCOPE
    # Use a default redirect URI if not provided
    redirect_uri = redirect_uri or REDIRECT_PATH
    auth_url = msal_app.get_authorization_request_url(
        required_scopes,
        redirect_uri=redirect_uri,
        state=state,
        prompt=prompt
    )
    return auth_url

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

def get_valid_access_token_for_plugins(scopes=None):
    """
    Gets a valid access token for the current user.
    Tries MSAL cache first, then uses refresh token if needed.
    Returns the access token string or None if refresh failed or user not logged in.
    """
    if "user" not in session:
        print("get_valid_access_token: No user in session.")
        return {
            "error": "not_logged_in",
            "message": "User is not logged in.",
            "error_code": None,
            "error_description": "No user in session."
        }

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

    if not account:
        print("get_valid_access_token: No matching account found in MSAL cache.")
        return {
            "error": "no_account",
            "message": "No matching account found in MSAL cache.",
            "error_code": None,
            "error_description": "No account context."
        }

    result = msal_app.acquire_token_silent_with_error(required_scopes, account=account) # Ensure we handle errors properly
    _save_cache(msal_app.token_cache)

    if result and "access_token" in result:
        print(f"get_valid_access_token: Token acquired silently for scopes: {required_scopes}")
        return {"access_token": result['access_token']}

    # If we reach here, it means silent acquisition failed
    print("get_valid_access_token: acquire_token_silent failed. Needs re-authentication or received invalid grants.")
    if result is None: # Assume invalid grants or no token
        print("result is None: get_valid_access_token: Consent required.")
        host_url = request.host_url.rstrip('/')
        # Only enforce https if not localhost or 127.0.0.1
        if not (host_url.startswith('http://localhost') or host_url.startswith('http://127.0.0.1')):
            if not host_url.startswith('https://'):
                host_url = 'https://' + host_url.split('://', 1)[-1]
        redirect_url = host_url + REDIRECT_PATH
        logging.debug(f"Redirect URL for {user_info.get('oid')}: {redirect_url}")
        consent_url = get_consent_url(msal_app=msal_app ,scopes=required_scopes, redirect_uri=redirect_url)
        logging.debug(f"Consent URL: {consent_url}")
        return {
            "error": "consent_required",
            "message": "User consent is required to access this resource. Present to the user so the consent url opens in a new tab.",
            "consent_url": consent_url,
            "scopes": required_scopes,
            "error_code": None,
            "error_description": "No token result; interactive authentication required."
        }

    error_code = result.get('error') if result else None
    error_desc = result.get('error_description') if result else None
    print(f"MSAL Error: {error_code}, Description: {error_desc}")

    if error_code == "invalid_grant" and error_desc and ("AADSTS65001" in error_desc or "consent_required" in error_desc):
        host_url = request.host_url.rstrip('/')
        if not (host_url.startswith('http://localhost') or host_url.startswith('http://127.0.0.1')):
            if not host_url.startswith('https://'):
                host_url = 'https://' + host_url.split('://', 1)[-1]
        redirect_url = host_url + REDIRECT_PATH
        logging.debug(f"Redirect URL for {user_info.get('oid')}: {redirect_url}")
        consent_url = get_consent_url(msal_app=msal_app ,scopes=required_scopes, redirect_uri=redirect_url)
        logging.debug(f"Consent URL: {consent_url}")
        return {
            "error": "consent_required",
            "message": "User consent is required to access this resource. Present to the user so the consent url opens in a new tab.",
            "consent_url": consent_url,
            "scopes": required_scopes,
            "error_code": error_code,
            "error_description": error_desc
        }
    else:
        return {
            "error": "token_acquisition_failed",
            "message": "Failed to acquire access token.",
            "error_code": error_code,
            "error_description": error_desc
        }
    
def get_video_indexer_account_token(settings, video_id=None):
    """
    For ARM-based VideoIndexer accounts:
    1) Acquire an ARM token with DefaultAzureCredential
    2) POST to the ARM generateAccessToken endpoint
    3) Return the account-level accessToken
    """
    # 1) ARM token
    if AZURE_ENVIRONMENT == "usgovernment":
        arm_scope = "https://management.usgovcloudapi.net/.default"
    elif AZURE_ENVIRONMENT == "custom":
        arm_scope = f"{CUSTOM_RESOURCE_MANAGER_URL_VALUE}/.default"
    else:
        arm_scope = "https://management.azure.com/.default"
    
    credential = DefaultAzureCredential()
    arm_token = credential.get_token(arm_scope).token
    print("[VIDEO] ARM token acquired", flush=True)

    # 2) Call the generateAccessToken API
    rg       = settings["video_indexer_resource_group"]
    sub      = settings["video_indexer_subscription_id"]
    acct     = settings["video_indexer_account_name"]
    api_ver  = settings.get("video_indexer_arm_api_version", "2021-11-10-preview")
    
    if AZURE_ENVIRONMENT == "usgovernment":
        url = (
        f"https://management.usgovcloudapi.net/subscriptions/{sub}"
        f"/resourceGroups/{rg}"
        f"/providers/Microsoft.VideoIndexer/accounts/{acct}"
        f"/generateAccessToken?api-version={api_ver}"
        )
    elif AZURE_ENVIRONMENT == "custom":
        url = (
        f"{CUSTOM_RESOURCE_MANAGER_URL_VALUE}/subscriptions/{sub}"
        f"/resourceGroups/{rg}"
        f"/providers/Microsoft.VideoIndexer/accounts/{acct}"
        f"/generateAccessToken?api-version={api_ver}"
        )
    else:
        url = (
        f"https://management.azure.com/subscriptions/{sub}"
        f"/resourceGroups/{rg}"
        f"/providers/Microsoft.VideoIndexer/accounts/{acct}"
        f"/generateAccessToken?api-version={api_ver}"
        )

    body = {
        "permissionType": "Contributor",
        "scope": "Account"
    }
    if video_id:
        body["videoId"] = video_id

    resp = requests.post(
        url,
        json=body,
        headers={"Authorization": f"Bearer {arm_token}"}
    )
    resp.raise_for_status()
    ai = resp.json().get("accessToken")
    print(f"[VIDEO] Account token acquired (len={len(ai)})", flush=True)
    return ai


JWKS_CACHE = {}

def get_microsoft_entra_jwks():
    """Fetches the JWKS from Microsoft Entra's OIDC metadata endpoint."""
    # Microsoft Entra OpenID Connect discovery endpoint
    global JWKS_CACHE
    global OIDC_METADATA_URL

    if not JWKS_CACHE:
        try:
            # Fetch OIDC configuration
            oidc_config = requests.get(OIDC_METADATA_URL).json()
            jwks_uri = oidc_config["jwks_uri"]

            # Fetch JWKS
            jwks_response = requests.get(jwks_uri).json()
            JWKS_CACHE = {key['kid']: key for key in jwks_response['keys']}
        except requests.exceptions.RequestException as e:
            print(f"Error fetching JWKS: {e}")
            return None
    return JWKS_CACHE

def validate_bearer_token(token):
    """Validates a Microsoft Entra bearer token."""
    global CLIENT_ID, TENANT_ID, AUTHORITY
    try:
        jwks = get_microsoft_entra_jwks()
        if not jwks:
            return False, "Failed to retrieve signing keys."

        # Decode header to get 'kid' (key ID)
        header = jwt.get_unverified_header(token)
        kid = header.get("kid")

        if not kid or kid not in jwks:
            return False, "Invalid or missing key ID."

        key_data = jwks[kid]

        # Construct public key from JWK
        public_key = jwt.algorithms.RSAAlgorithm.from_jwk(key_data)

        # Validate the token
        decoded_token = jwt.decode(
            token,
            public_key,
            algorithms=["RS256"],  # Microsoft Entra typically uses RS256
            audience=f"api://{CLIENT_ID}",
            issuer=f"https://sts.windows.net/{TENANT_ID}/", # Example for common tenant or specific tenant ID
            #issuer=AUTHORITY, # Example for common tenant or specific tenant ID
            options={
                "verify_exp": True,
                "verify_nbf": True,
                "verify_iss": True,
                "verify_aud": True, # TODO: THIS NEEDS TO BE FIXED TO VERIFY AUDIENCE.
            }
        )
        return True, decoded_token
    except jwt.exceptions.ExpiredSignatureError:
        return False, "Token has expired."
    except jwt.exceptions.InvalidAudienceError:
        return False, "Invalid audience."
    except jwt.exceptions.InvalidIssuerError:
        return False, "Invalid issuer."
    except jwt.exceptions.InvalidTokenError as e:
        return False, f"Invalid token: {e}"
    except Exception as e:
        return False, f"An unexpected error occurred during token validation: {e}"

def accesstoken_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):

        print("accesstoken_required")

        auth_header = request.headers.get('Authorization')
        if not auth_header:
            return jsonify({"message": "Authorization header missing"}), 401

        if not auth_header.startswith("Bearer "):
            return jsonify({"message": "Invalid Authorization header format"}), 401

        token = auth_header.split(" ")[1]
        is_valid, data = validate_bearer_token(token)

        if not is_valid:
            return jsonify({"message": data}), 401

        # Check for "ExternalApi" role in the token claims
        roles = data.get("roles") if isinstance(data, dict) else None
        if not roles or "ExternalApi" not in roles:
            return jsonify({"message": "Forbidden: ExternalApi role required"}), 403

        print("User is valid")

        # You can now access claims from `data`, e.g., data['sub'], data['name'], data['roles']
        #kwargs['user_claims'] = data # Pass claims to the decorated function # NOT NEEDED FOR NOW
        return f(*args, **kwargs)
    return decorated_function

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
                # Get settings from database, with environment variable fallback
                from functions_settings import get_settings
                settings = get_settings()
                
                # Only use Front Door redirect URLs if Front Door is enabled
                if settings.get('enable_front_door', False):
                    front_door_url = settings.get('front_door_url')
                    if front_door_url:
                        home_url, login_redirect_url = build_front_door_urls(front_door_url)
                        return redirect(login_redirect_url)
                    elif LOGIN_REDIRECT_URL:
                        # Fall back to environment variable if Front Door is enabled but no URL is set
                        return redirect(LOGIN_REDIRECT_URL)
                
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

def get_user_profile_image():
    """
    Fetches the user's profile image from Microsoft Graph and returns it as base64.
    Returns None if no image is found or if there's an error.
    """
    token = get_valid_access_token()
    if not token:
        print("get_user_profile_image: Could not acquire access token")
        return None

    # Determine the correct Graph endpoint based on Azure environment
    if AZURE_ENVIRONMENT == "usgovernment":
        profile_image_endpoint = "https://graph.microsoft.us/v1.0/me/photo/$value"
    elif AZURE_ENVIRONMENT == "custom":
        profile_image_endpoint = f"{CUSTOM_GRAPH_URL_VALUE}/me/photo/$value"
    else:
        profile_image_endpoint = "https://graph.microsoft.com/v1.0/me/photo/$value"
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "image/*"
    }

    try:
        response = requests.get(profile_image_endpoint, headers=headers)
        
        if response.status_code == 200:
            # Convert image to base64
            import base64
            image_data = response.content
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            
            # Get content type for proper data URL formatting
            content_type = response.headers.get('content-type', 'image/jpeg')
            return f"data:{content_type};base64,{image_base64}"
            
        elif response.status_code == 404:
            # User has no profile image
            print("get_user_profile_image: User has no profile image")
            return None
        else:
            print(f"get_user_profile_image: Failed to fetch profile image. Status: {response.status_code}")
            return None
            
    except requests.exceptions.RequestException as e:
        print(f"get_user_profile_image: Request failed: {e}")
        return None
    except Exception as e:
        print(f"get_user_profile_image: Unexpected error: {e}")
        return None
