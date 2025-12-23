# route_frontend_notifications.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_notifications(app):

    @app.route("/notifications")
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    def notifications():
        """
        Renders the notifications page for the current user.
        """
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        user_id = get_current_user_id()
        user_settings = get_user_settings(user_id)
        
        return render_template(
            "notifications.html",
            app_settings=public_settings,
            settings=public_settings,
            user_settings=user_settings
        )
