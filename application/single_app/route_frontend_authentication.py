# route_frontend_authentication.py

from config import *

def register_route_frontend_authentication(app):
    @app.route('/login')
    def login():
        msal_app = ConfidentialClientApplication(
            CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
        )
        auth_url = msal_app.get_authorization_request_url(
            scopes=SCOPE,
            redirect_uri=url_for('authorized', _external=True, _scheme='https')
        )
        print("Redirecting to Azure AD for authentication.")
        return redirect(auth_url)

    @app.route('/getAToken')
    def authorized():
        msal_app = ConfidentialClientApplication(
            CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
        )
        code = request.args.get('code')
        if not code:
            print("Authorization code not found.")
            return "Authorization code not found", 400
        result = msal_app.acquire_token_by_authorization_code(
            code=code,
            scopes=SCOPE,
            redirect_uri=url_for('authorized', _external=True, _scheme='https')
        )
        if "error" in result:
            error_description = result.get("error_description", result.get("error"))
            print(f"Login failure: {error_description}")
            return f"Login failure: {error_description}", 500
        session["user"] = result.get("id_token_claims")
        session["access_token"] = result.get("access_token")
        print("User logged in successfully.")
        # Check if PROXY_REDIRECT_URL is set
        proxy_redirect_url = os.getenv("PROXY_REDIRECT_URL")
        if proxy_redirect_url:
            print(f"Redirecting to proxy URL: {proxy_redirect_url}")
            return redirect(proxy_redirect_url)
        else:
            print("Redirecting to index.")
            return redirect(url_for('index'))

    @app.route('/logout')
    def logout():
        session.clear()
        logout_url = f"{AUTHORITY}/oauth2/v2.0/logout?post_logout_redirect_uri={url_for('index', _external=True)}"
        print("User logged out. Redirecting to Azure AD logout endpoint.")
        return redirect(logout_url)