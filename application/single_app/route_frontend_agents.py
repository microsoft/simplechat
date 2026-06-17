# route_frontend_agents.py

from config import *
from functions_authentication import *
from functions_settings import get_settings, sanitize_settings_for_user
from swagger_wrapper import swagger_route, get_auth_security


def register_route_frontend_agents(app):
    @app.route('/agents', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required('enable_semantic_kernel')
    def agents():
        settings = get_settings()
        public_settings = sanitize_settings_for_user(settings)
        return render_template(
            'agents.html',
            settings=public_settings,
        )