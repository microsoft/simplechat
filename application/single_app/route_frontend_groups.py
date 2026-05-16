# route_frontend_groups.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_groups(app):
    @app.route("/my_groups", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def my_groups():
        """
        Redirects the legacy My Groups page to the profile Groups tab.
        """
        return redirect(url_for('profile', tab='groups'))

    @app.route("/groups/<group_id>", methods=["GET"])
    @swagger_route(security=get_auth_security())
    @login_required
    @user_required
    @enabled_required("enable_group_workspaces")
    def manage_group(group_id):
        """
        Renders a page or view for managing a single group (not shown in detail here).
        Could be a second template like 'manage_group.html'.
        """
        
        return render_template("manage_group.html", group_id=group_id)
