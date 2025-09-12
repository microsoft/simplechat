# route_frontend_authentication.py

from unittest import result
from config import *
from functions_authentication import _build_msal_app, _load_cache, _save_cache
from functions_debug import debug_print

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

def register_route_frontend_authentication(app):
    @app.route('/login')
    def login():
        # Clear potentially stale cache/user info before starting new login
        session.pop("user", None)
        session.pop("token_cache", None)

        # Use helper to build app (cache not strictly needed here, but consistent)
        msal_app = _build_msal_app()
        
        # Get settings from database, with environment variable fallback
        from functions_settings import get_settings
        settings = get_settings()
        
        # Only use Front Door redirect URL if Front Door is enabled
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                redirect_uri = login_redirect_url
            else:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                redirect_uri = LOGIN_REDIRECT_URL or url_for('authorized', _external=True, _scheme='https')
        else:
            redirect_uri = url_for('authorized', _external=True, _scheme='https')
        
        debug_print(f"LOGIN_REDIRECT_URL (env): {LOGIN_REDIRECT_URL}")
        debug_print(f"front_door_url (db): {settings.get('front_door_url')}")
        debug_print(f"Front Door enabled: {settings.get('enable_front_door', False)}")
        debug_print(f"Using redirect_uri for Azure AD: {redirect_uri}")

        auth_url = msal_app.get_authorization_request_url(
            scopes=SCOPE, # Use SCOPE from config (includes offline_access)
            redirect_uri=redirect_uri
        )
        print("Redirecting to Azure AD for authentication.")
        #auth_url= auth_url.replace('https://', 'http://')  # Ensure HTTPS for security
        return redirect(auth_url)

    @app.route('/getAToken') # This is your redirect URI path
    def authorized():
        # Check for errors passed back from Azure AD
        if request.args.get('error'):
            error = request.args.get('error')
            error_description = request.args.get('error_description', 'No description provided.')
            print(f"Azure AD Login Error: {error} - {error_description}")
            return f"Login Error: {error} - {error_description}", 400 # Or render an error page

        code = request.args.get('code')
        if not code:
            print("Authorization code not found in callback.")
            return "Authorization code not found", 400

        # Build MSAL app WITH session cache (will be loaded by _build_msal_app via _load_cache)
        msal_app = _build_msal_app(cache=_load_cache()) # Load existing cache

        # Get settings from database, with environment variable fallback
        from functions_settings import get_settings
        settings = get_settings()
        
        # Only use Front Door redirect URL if Front Door is enabled
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                redirect_uri = login_redirect_url
            else:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                redirect_uri = LOGIN_REDIRECT_URL or url_for('authorized', _external=True, _scheme='https')
        else:
            redirect_uri = url_for('authorized', _external=True, _scheme='https')
        
        print(f"Token exchange using redirect_uri: {redirect_uri}")

        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=SCOPE, # Request the same scopes again
            redirect_uri=redirect_uri
        )

        if "error" in result:
            error_description = result.get("error_description", result.get("error"))
            print(f"Token acquisition failure: {error_description}")
            return f"Login failure: {error_description}", 500

        # --- Store results ---
        # Store user identity info (claims from ID token)
        debug_print(f" [claims] User {result.get('id_token_claims', {}).get('name', 'Unknown')} logged in.")
        debug_print(f" [claims] User claims: {result.get('id_token_claims', {})}")
        debug_print(f" [claims] User token: {result.get('access_token', 'Unknown')}")

        session["user"] = result.get("id_token_claims")

        # --- CRITICAL: Save the entire cache (contains tokens) to session ---
        _save_cache(msal_app.token_cache)

        print(f"User {session['user'].get('name')} logged in successfully.")
        # Redirect to the originally intended page or home
        # You might want to store the original destination in the session during /login
        # Get settings from database, with environment variable fallback
        from functions_settings import get_settings
        settings = get_settings()
        
        debug_print(f"HOME_REDIRECT_URL (env): {HOME_REDIRECT_URL}")
        debug_print(f"front_door_url (db): {settings.get('front_door_url')}")
        debug_print(f"Front Door enabled: {settings.get('enable_front_door', False)}")

        # Only use Front Door redirect URL if Front Door is enabled
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                print(f"Redirecting to configured Front Door URL: {home_url}")
                return redirect(home_url)
            elif HOME_REDIRECT_URL:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                print(f"Redirecting to environment HOME_REDIRECT_URL: {HOME_REDIRECT_URL}")
                return redirect(HOME_REDIRECT_URL)
        
        debug_print(f"Front Door not enabled or URLs not set, falling back to url_for('index')")
        return redirect(url_for('index')) # Or another appropriate page

    # This route is for API calls that need a token, not the web app login flow. This does not kick off a session.
    @app.route('/getATokenApi') # This is your redirect URI path
    def authorized_api():
        # Check for errors passed back from Azure AD
        if request.args.get('error'):
            error = request.args.get('error')
            error_description = request.args.get('error_description', 'No description provided.')
            print(f"Azure AD Login Error: {error} - {error_description}")
            return f"Login Error: {error} - {error_description}", 400 # Or render an error page

        code = request.args.get('code')
        if not code:
            print("Authorization code not found in callback.")
            return "Authorization code not found", 400

        # Build MSAL app WITH session cache (will be loaded by _build_msal_app via _load_cache)
        msal_app = _build_msal_app(cache=_load_cache()) # Load existing cache

        # Get settings for redirect URI (same logic as other routes)
        from functions_settings import get_settings
        settings = get_settings()
        
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                redirect_uri = login_redirect_url
            else:
                redirect_uri = LOGIN_REDIRECT_URL or url_for('authorized', _external=True, _scheme='https')
        else:
            redirect_uri = url_for('authorized', _external=True, _scheme='https')

        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=SCOPE, # Request the same scopes again
            redirect_uri=redirect_uri
        )

        if "error" in result:
            error_description = result.get("error_description", result.get("error"))
            print(f"Token acquisition failure: {error_description}")
            return f"Login failure: {error_description}", 500

        return jsonify(result, 200)

    @app.route('/logout')
    def logout():
        user_name = session.get("user", {}).get("name", "User")
        # Get the user's email before clearing the session
        user_email = session.get("user", {}).get("preferred_username") or session.get("user", {}).get("email")
        # Clear Flask session data
        session.clear()
        # Redirect user to Azure AD logout endpoint
        # MSAL provides a helper for this too, but constructing manually is fine
        # Get settings from database, with environment variable fallback
        from functions_settings import get_settings
        settings = get_settings()
        
        # Only use Front Door redirect URL if Front Door is enabled
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                logout_uri = home_url
            elif HOME_REDIRECT_URL:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                logout_uri = HOME_REDIRECT_URL
            else:
                logout_uri = url_for('index', _external=True, _scheme='https')
        else:
            logout_uri = url_for('index', _external=True, _scheme='https')
        
        print(f"Front Door enabled: {settings.get('enable_front_door', False)}")
        print(f"Front Door URL: {settings.get('front_door_url')}")
        print(f"Logout redirect URI: {logout_uri}")
        
        logout_url = (
            f"{AUTHORITY}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={quote(logout_uri)}"
        )
        # Add logout_hint parameter if we have the user's email
        if user_email:
            logout_url += f"&logout_hint={quote(user_email)}"
        
        print(f"{user_name} logged out. Redirecting to Azure AD logout.")
        return redirect(logout_url)