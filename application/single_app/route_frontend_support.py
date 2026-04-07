# route_frontend_support.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security
from support_menu_config import get_visible_support_latest_features


def _support_menu_access_allowed():
    user = session.get('user', {})
    roles = user.get('roles', []) if isinstance(user.get('roles', []), list) else []
    return 'Admin' in roles or 'User' in roles


def register_route_frontend_support(app):

    @app.route('/support/latest-features')
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_support_menu')
    def support_latest_features():
        """Render the latest features page exposed from the Support menu."""
        if not _support_menu_access_allowed():
            return 'Forbidden', 403

        settings = get_settings()
        if not settings.get('enable_support_latest_features', True):
            return 'Not Found', 404

        visible_features = get_visible_support_latest_features(settings)
        return render_template(
            'latest_features.html',
            support_latest_features=visible_features,
        )

    @app.route('/support/send-feedback')
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_support_menu')
    def support_send_feedback():
        """Render the support feedback page."""
        if not _support_menu_access_allowed():
            return 'Forbidden', 403

        settings = get_settings()
        recipient_email = str(settings.get('support_feedback_recipient_email') or '').strip()
        if not settings.get('enable_support_send_feedback', True) or not recipient_email:
            return 'Not Found', 404

        return render_template('support_send_feedback.html')