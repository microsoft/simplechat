# route_frontend_feedback.py

from config import *
from functions_authentication import *
from functions_settings import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_frontend_feedback(app):

    @app.route("/admin/feedback_review")
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @admin_required
    @feedback_admin_required
    @enabled_required("enable_user_feedback")
    def admin_feedback_review():
        """
        Renders the feedback review page (feedback_review.html).
        """
        
        return render_template("admin_feedback_review.html")
    
    @app.route("/my_feedback")
    @swagger_route(
        security=get_auth_security()
    )
    @login_required
    @user_required
    @enabled_required("enable_user_feedback")
    def my_feedback():
        """
        Renders the "My Feedback" page for the current user.
        """
        
        return render_template("my_feedback.html")