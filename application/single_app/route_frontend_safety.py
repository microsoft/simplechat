# route_frontend_safety.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_safety(app):

    @app.route('/admin/safety_violations', methods=['GET'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @admin_required
    @safety_violation_admin_required
    @enabled_required("enable_content_safety")
    def admin_safety_violations():
        """
        Renders the admin safety violations page (admin_safety_violations.html).
        """
        return render_template('admin_safety_violations.html')

    @app.route('/safety_violations', methods=['GET'])
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    @enabled_required("enable_content_safety")
    def my_safety_violations():
        """
        Displays the logged-in user's safety violations.
        """        
        return render_template('my_safety_violations.html')