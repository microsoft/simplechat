# route_frontend_authentication.py

import logging
import os
import jwt
import requests

from config import *
from config import DISABLE_APP_SERVICE_EASY_AUTH_LOGOUT
from functions_activity_logging import log_user_login, record_user_login_session_activity
from functions_terms_of_use import (
    apply_pending_pre_auth_terms_of_use,
    get_terms_of_use_config,
    has_terms_of_use_acceptance,
)
from functions_appinsights import log_event
from functions_authentication import _build_msal_app, _load_cache, _save_cache, clear_requested_oauth_scopes, create_ci_bearer_session, get_graph_authority, get_graph_endpoint, get_requested_oauth_scopes
from functions_debug import debug_print
from functions_settings import get_settings, sanitize_settings_for_user
from swagger_wrapper import swagger_route, get_auth_security

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


def _use_app_service_easy_auth_logout():
    """
    Determine whether logout should route through the App Service Easy Auth endpoint.

    Args:
        None.

    Returns:
        bool: True when the current request is being served behind App Service Easy Auth.
    Raises:
        None.
    """
    if DISABLE_APP_SERVICE_EASY_AUTH_LOGOUT:
        debug_print("Easy Auth logout disabled by DISABLE_APP_SERVICE_EASY_AUTH_LOGOUT; using local logout.")
        return False

    if not os.getenv('WEBSITE_HOSTNAME'):
        return False

    # Easy Auth injects these headers only on requests it actually intercepts, so they are
    # the reliable per-request signal that /.auth/logout is being served for this host.
    easy_auth_headers = (
        request.headers.get('X-MS-CLIENT-PRINCIPAL'),
        request.headers.get('X-MS-CLIENT-PRINCIPAL-ID'),
        request.headers.get('X-MS-CLIENT-PRINCIPAL-NAME'),
    )
    if not any(easy_auth_headers):
        debug_print("No App Service Easy Auth principal headers on this request; using local logout.")
        return False

    return True


def _build_app_service_easy_auth_logout_url():
    """Build the Easy Auth logout URL that resets the upstream session before re-entering Flask login."""
    post_logout_redirect_uri = quote(url_for('frontend_authentication.login'), safe='')
    return f"/.auth/logout?post_logout_redirect_uri={post_logout_redirect_uri}"

def _decode_teams_assertion_claims(teams_token):
    """Decode claims from a Teams assertion after MSAL has accepted it for OBO."""
    try:
        claims = jwt.decode(
            teams_token,
            options={
                "verify_signature": False,
                "verify_aud": False,
                "verify_exp": False,
            },
        )
        return claims if isinstance(claims, dict) else {}
    except Exception as e:
        log_event(
            f"[TEAMS_SSO] Unable to decode Teams assertion claims: {e}",
            level=logging.WARNING,
            debug_only=True,
        )
        return {}


def _fetch_graph_me(access_token):
    """Load the signed-in user's Microsoft Graph profile with the OBO access token."""
    if not access_token:
        return {}

    try:
        response = requests.get(
            get_graph_endpoint('/me'),
            headers={'Authorization': f'Bearer {access_token}'},
            timeout=10,
        )
        if response.status_code != 200:
            log_event(
                "[TEAMS_SSO] Microsoft Graph /me lookup failed during Teams token exchange.",
                extra={'status_code': response.status_code},
                level=logging.WARNING,
            )
            return {}
        payload = response.json()
        return payload if isinstance(payload, dict) else {}
    except Exception as e:
        log_event(
            f"[TEAMS_SSO] Microsoft Graph /me lookup raised during Teams token exchange: {e}",
            level=logging.WARNING,
            debug_only=True,
        )
        return {}


def _build_teams_session_user(result, teams_token):
    """Build the session user contract expected by the rest of SimpleChat."""
    token_claims = result.get('id_token_claims') if isinstance(result.get('id_token_claims'), dict) else {}
    assertion_claims = _decode_teams_assertion_claims(teams_token)
    graph_profile = _fetch_graph_me(result.get('access_token'))

    preferred_username = (
        token_claims.get('preferred_username')
        or assertion_claims.get('preferred_username')
        or assertion_claims.get('upn')
        or assertion_claims.get('email')
        or graph_profile.get('userPrincipalName')
        or graph_profile.get('mail')
    )
    email = (
        token_claims.get('email')
        or assertion_claims.get('email')
        or graph_profile.get('mail')
        or preferred_username
    )

    session_user = {
        'name': token_claims.get('name') or assertion_claims.get('name') or graph_profile.get('displayName') or preferred_username or 'Unknown User',
        'preferred_username': preferred_username,
        'email': email,
        'oid': token_claims.get('oid') or assertion_claims.get('oid') or graph_profile.get('id'),
        'tid': token_claims.get('tid') or assertion_claims.get('tid') or TENANT_ID,
        'sub': token_claims.get('sub') or assertion_claims.get('sub') or graph_profile.get('id'),
    }
    return {key: value for key, value in session_user.items() if value}


def register_route_frontend_authentication(bp):
    @bp.route('/login')
    @swagger_route(security=get_auth_security())
    def login():
        # Clear potentially stale cache/user info before starting new login
        session.pop("user", None)
        session.pop("token_cache", None)
        session.pop("last_activity_epoch", None)
        clear_requested_oauth_scopes()

        is_teams_login = request.args.get('teams', 'false').lower() == 'true'
        if is_teams_login and ENABLE_TEAMS_SSO:
            settings = get_settings() or {}
            public_settings = sanitize_settings_for_user(settings)
            return render_template(
                'login.html',
                app_settings=public_settings,
                client_id=CLIENT_ID,
                custom_teams_origins=CUSTOM_TEAMS_ORIGINS,
                enable_teams_sso=True,
                teams_app_resource=TEAMS_APP_RESOURCE,
                teams_success_redirect_path=TEAMS_SUCCESS_REDIRECT_PATH,
            )

        # Use helper to build app (cache not strictly needed here, but consistent)
        msal_app = _build_msal_app()
        
        # Get settings from database, with environment variable fallback
        settings = get_settings() or {}

        terms_config = get_terms_of_use_config(settings)
        if terms_config["enabled"] and not has_terms_of_use_acceptance(settings):
            return redirect(url_for('frontend_terms_of_use.terms_of_use'))

        # Only use Front Door redirect URL if Front Door is enabled
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                redirect_uri = login_redirect_url
            else:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                redirect_uri = LOGIN_REDIRECT_URL or url_for('frontend_authentication.authorized', _external=True, _scheme='https')
        else:
            redirect_uri = url_for('frontend_authentication.authorized', _external=True, _scheme='https')
        
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

    @bp.route('/ci-auth/session', methods=['POST'])
    @swagger_route(security=get_auth_security())
    def ci_auth_session():
        return create_ci_bearer_session()

    @bp.route('/getAToken') # This is your redirect URI path
    @swagger_route(security=get_auth_security())
    def authorized():
        # Check for errors passed back from Azure AD
        if request.args.get('error'):
            error = request.args.get('error')
            error_description = request.args.get('error_description', 'No description provided.')
            print(f"Azure AD Login Error: {error} - {error_description}")
            return f"Login Error: {error} - {error_description}", 400 # Or render an error page

        code = request.args.get('code')
        if not code:
            log_event(
                "[AUTH_CALLBACK] OAuth callback reached without an authorization code; redirecting to sign-in.",
                extra={'path': request.path},
                level=logging.INFO,
                debug_only=True,
            )
            return redirect(url_for('public_app.index'))

        # Build MSAL app WITH session cache (will be loaded by _build_msal_app via _load_cache)
        msal_app = _build_msal_app(cache=_load_cache()) # Load existing cache

        # Get settings from database, with environment variable fallback
        settings = get_settings() or {}
        
        # Only use Front Door redirect URL if Front Door is enabled
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                redirect_uri = login_redirect_url
            else:
                # Fall back to environment variable if Front Door is enabled but no URL is set
                redirect_uri = LOGIN_REDIRECT_URL or url_for('frontend_authentication.authorized', _external=True, _scheme='https')
        else:
            redirect_uri = url_for('frontend_authentication.authorized', _external=True, _scheme='https')
        
        print(f"Token exchange using redirect_uri: {redirect_uri}")

        requested_scopes = get_requested_oauth_scopes(clear_after_read=True)
        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=requested_scopes,
            redirect_uri=redirect_uri
        )

        if "error" in result:
            error_description = result.get("error_description", result.get("error"))
            print(f"Token acquisition failure: {error_description}")
            return f"Login failure: {error_description}", 500

        # --- Store results ---
        # Store user identity info (claims from ID token)
        debug_print(f" [CLAIMS] User {result.get('id_token_claims', {}).get('name', 'Unknown')} logged in.")
        debug_print(f" [CLAIMS] User claims: {result.get('id_token_claims', {})}")

        session["user"] = result.get("id_token_claims")
        session["last_activity_epoch"] = int(time.time())

        # --- CRITICAL: Save the entire cache (contains tokens) to session ---
        _save_cache(msal_app.token_cache)

        print(f"User {session['user'].get('name')} logged in successfully.")
        
        # Log the login activity
        try:
            user_id = session['user'].get('oid') or session['user'].get('sub')
            if user_id:
                log_user_login(user_id, 'azure_ad')
                record_user_login_session_activity(session)
        except Exception as e:
            debug_print(f"Could not log login activity: {e}")

        try:
            user_id = session['user'].get('oid') or session['user'].get('sub')
            if user_id:
                apply_pending_pre_auth_terms_of_use(
                    user_id=user_id,
                    settings=settings,
                    source="azure_ad_pre_auth",
                )
        except Exception as e:
            log_event(
                "[TERMS_OF_USE] Failed to apply pending Azure AD pre-auth acceptance.",
                extra={'error': str(e)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )
        
        # Redirect to the originally intended page or home
        # You might want to store the original destination in the session during /login
        # Get settings from database, with environment variable fallback
        settings = get_settings() or {}
        
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
        
        debug_print(f"Front Door not enabled or URLs not set, falling back to url_for('public_app.index')")
        return redirect(url_for('public_app.index')) # Or another appropriate page

    # This route is for API calls that need a token, not the web app login flow. This does not kick off a session.
    @bp.route('/getATokenApi') # This is your redirect URI path
    @swagger_route(security=get_auth_security())
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
        settings = get_settings() or {}
        
        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, login_redirect_url = build_front_door_urls(front_door_url)
                redirect_uri = login_redirect_url
            else:
                redirect_uri = LOGIN_REDIRECT_URL or url_for('frontend_authentication.authorized', _external=True, _scheme='https')
        else:
            redirect_uri = url_for('frontend_authentication.authorized', _external=True, _scheme='https')

        requested_scopes = get_requested_oauth_scopes(clear_after_read=True)
        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=requested_scopes,
            redirect_uri=redirect_uri
        )

        if "error" in result:
            error_description = result.get("error_description", result.get("error"))
            print(f"Token acquisition failure: {error_description}")
            return f"Login failure: {error_description}", 500

        return jsonify(result, 200)

    @bp.route('/auth/teams/token-exchange', methods=['POST'])
    @swagger_route(security=get_auth_security())
    def teams_token_exchange():
        """Exchange a Teams SSO assertion for a SimpleChat Flask session."""
        if not ENABLE_TEAMS_SSO:
            return jsonify({"error": "teams_sso_disabled"}), 404

        data = request.get_json(silent=True)
        if not isinstance(data, dict):
            return jsonify({
                "error": "invalid_request",
                "error_description": "Request body must be a valid JSON object.",
            }), 400

        teams_token = data.get('token')
        if not isinstance(teams_token, str) or not teams_token.strip():
            return jsonify({
                "error": "missing_token",
                "error_description": "Teams authentication token is required.",
            }), 400

        try:
            msal_app = _build_msal_app(cache=_load_cache(), authority_override=get_graph_authority())
            result = msal_app.acquire_token_on_behalf_of(
                user_assertion=teams_token,
                scopes=SCOPE,
            )
        except Exception as e:
            log_event(
                f"[TEAMS_SSO] Teams token exchange raised during OBO flow: {e}",
                level=logging.ERROR,
                exceptionTraceback=True,
            )
            return jsonify({
                "error": "token_exchange_failed",
                "error_description": "Teams sign-in could not be completed.",
            }), 500

        if "error" in result:
            log_event(
                "[TEAMS_SSO] Teams token exchange failed during OBO flow.",
                extra={
                    'msal_error': result.get('error'),
                    'correlation_id': result.get('correlation_id'),
                },
                level=logging.WARNING,
            )
            return jsonify({
                "error": result.get('error') or "token_exchange_failed",
                "error_description": "Teams sign-in could not be completed. Please use Microsoft sign-in.",
            }), 400

        session_user = _build_teams_session_user(result, teams_token)
        if not session_user.get('oid') or not session_user.get('tid'):
            log_event(
                "[TEAMS_SSO] Teams token exchange succeeded but user identity was incomplete.",
                extra={
                    'has_oid': bool(session_user.get('oid')),
                    'has_tid': bool(session_user.get('tid')),
                    'has_username': bool(session_user.get('preferred_username')),
                },
                level=logging.ERROR,
            )
            return jsonify({
                "error": "identity_incomplete",
                "error_description": "Teams sign-in could not resolve the signed-in user.",
            }), 400

        session['user'] = session_user
        session['last_activity_epoch'] = int(time.time())
        _save_cache(msal_app.token_cache)

        user_name = session_user.get('name', 'Unknown User')
        log_event(
            "[TEAMS_SSO] Teams SSO user authenticated successfully.",
            extra={'user_id': session_user.get('oid')},
            level=logging.INFO,
        )

        try:
            log_user_login(session_user.get('oid'), 'teams_sso')
            record_user_login_session_activity(session)
        except Exception as e:
            debug_print(f"[TEAMS_SSO] Could not log Teams login activity: {e}")

        try:
            apply_pending_pre_auth_terms_of_use(
                user_id=session_user.get('oid'),
                settings=get_settings() or {},
                source="teams_sso_pre_auth",
            )
        except Exception as e:
            log_event(
                "[TERMS_OF_USE] Failed to apply pending Teams pre-auth acceptance.",
                extra={'error': str(e)},
                level=logging.ERROR,
                exceptionTraceback=True,
            )

        return jsonify({
            "success": True,
            "user": {
                "name": user_name,
                "email": session_user.get('preferred_username') or session_user.get('email'),
                "id": session_user.get('oid'),
            },
        }), 200

    @bp.route('/logout/local')
    @swagger_route(security=get_auth_security())
    def local_logout():
        """
        Clear the local Flask session and redirect to the configured home destination.

        Args:
            None.

        Returns:
            Response: A redirect response to the local or Front Door home URL.
        Raises:
            None.
        """
        session.clear()

        if _use_app_service_easy_auth_logout():
            logout_url = _build_app_service_easy_auth_logout_url()
            debug_print(f"Redirecting local logout through App Service Easy Auth: {logout_url}")
            return redirect(logout_url)

        settings = get_settings() or {}

        if settings.get('enable_front_door', False):
            front_door_url = settings.get('front_door_url')
            if front_door_url:
                home_url, _ = build_front_door_urls(front_door_url)
                logout_uri = home_url
            elif HOME_REDIRECT_URL:
                logout_uri = HOME_REDIRECT_URL
            else:
                logout_uri = url_for('public_app.index')
        else:
            logout_uri = url_for('public_app.index')

        return redirect(logout_uri)

    @bp.route('/logout')
    @swagger_route(security=get_auth_security())
    def logout():
        user_name = session.get("user", {}).get("name", "User")
        # Get the user's email before clearing the session
        user_email = session.get("user", {}).get("preferred_username") or session.get("user", {}).get("email")
        # Clear Flask session data
        session.clear()

        if _use_app_service_easy_auth_logout():
            logout_url = _build_app_service_easy_auth_logout_url()
            debug_print(f"{user_name} logged out. Redirecting to App Service Easy Auth logout.")
            return redirect(logout_url)

        # Redirect user to Azure AD logout endpoint
        # MSAL provides a helper for this too, but constructing manually is fine
        # Get settings from database, with environment variable fallback
        settings = get_settings() or {}
        
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
                logout_uri = url_for('public_app.index', _external=True)
        else:
            logout_uri = url_for('public_app.index', _external=True)
        
        debug_print(f"Front Door enabled: {settings.get('enable_front_door', False)}")
        debug_print(f"Front Door URL: {settings.get('front_door_url')}")
        debug_print(f"Logout redirect URI: {logout_uri}")
        
        logout_url = (
            f"{AUTHORITY}/oauth2/v2.0/logout"
            f"?post_logout_redirect_uri={quote(logout_uri)}"
        )
        # Add logout_hint parameter if we have the user's email
        if user_email:
            logout_url += f"&logout_hint={quote(user_email)}"
        
        debug_print(f"{user_name} logged out. Redirecting to Azure AD logout.")
        return redirect(logout_url)
