# route_frontend_authentication.py

from unittest import result
from config import *
from functions_authentication import _build_msal_app, _load_cache, _save_cache

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
        login_redirect_url = settings.get('login_redirect_url') or LOGIN_REDIRECT_URL
        
        # Use database login_redirect_url if set, otherwise fall back to url_for
        redirect_uri = login_redirect_url if login_redirect_url else url_for('authorized', _external=True, _scheme='https')
        
        print(f"LOGIN_REDIRECT_URL (env): {LOGIN_REDIRECT_URL}")
        print(f"login_redirect_url (db): {settings.get('login_redirect_url')}")
        print(f"Using redirect_uri for Azure AD: {redirect_uri}")
        
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
        login_redirect_url = settings.get('login_redirect_url') or LOGIN_REDIRECT_URL
        
        # Use database login_redirect_url if set, otherwise fall back to url_for
        redirect_uri = login_redirect_url if login_redirect_url else url_for('authorized', _external=True, _scheme='https')
        
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
        print(f"[claims] User {result.get('id_token_claims', {}).get('name', 'Unknown')} logged in.")
        print(f"[claims] User claims: {result.get('id_token_claims', {})}")
        session["user"] = result.get("id_token_claims")
        
        # Print user info for debugging
        #print(f"[claims] User {result.get('id_token_claims', {}).get('name', 'Unknown')} logged in.")
        #print(f"[claims] User claims: {result.get('id_token_claims', {})}")

        # --- CRITICAL: Save the entire cache (contains tokens) to session ---
        _save_cache(msal_app.token_cache)

        print(f"User {session['user'].get('name')} logged in successfully.")
        # Redirect to the originally intended page or home
        # You might want to store the original destination in the session during /login
        # Get settings from database, with environment variable fallback
        from functions_settings import get_settings
        settings = get_settings()
        home_redirect_url = settings.get('home_redirect_url') or HOME_REDIRECT_URL
        
        print(f"HOME_REDIRECT_URL (env): {HOME_REDIRECT_URL}")
        print(f"home_redirect_url (db): {settings.get('home_redirect_url')}")
        if home_redirect_url:
            print(f"Redirecting to configured URL: {home_redirect_url}")
            return redirect(home_redirect_url)
        else:
            print("HOME_REDIRECT_URL not set, falling back to url_for('index')")
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

        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=SCOPE, # Request the same scopes again
            redirect_uri=url_for('authorized', _external=True, _scheme='https')
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
        home_redirect_url = settings.get('home_redirect_url') or HOME_REDIRECT_URL
        
        logout_uri = home_redirect_url if home_redirect_url else url_for('index', _external=True, _scheme='https') # Where to land after logout
        
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