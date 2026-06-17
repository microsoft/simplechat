# route_external_health.py
# Combined health check endpoints for both internal and external monitoring

from config import *
from functions_authentication import *
from functions_settings import *
from functions_prompts import *
from swagger_wrapper import swagger_route, get_auth_security

def register_route_external_health(app):
    @app.route('/external/healthcheck', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @swagger_route()
    @enabled_required("enable_external_healthcheck")
    def external_health_check():
        """External health check endpoint for monitoring."""
        now = datetime.now()
        time_string = now.strftime("%Y-%m-%d %H:%M:%S")
        return time_string, 200


def register_no_auth_health(app):
    @app.route('/external/healthcheckz', methods=['GET'])
    @swagger_route(security=get_auth_security())
    @enabled_required("enable_no_auth_external_healthcheck")
    def no_auth_external_healthcheck():
        return {
            "status": "ok",
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        }, 200