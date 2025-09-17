# route_health.py
# Combined health check endpoints for both internal and external monitoring

from config import *
from functions_authentication import *
from functions_settings import *
from functions_prompts import *

def register_route_external_health(app):
    @app.route('/external/healthcheck', methods=['GET'])
    @enabled_required("enable_external_healthcheck")
    def external_health_check():
        """External health check endpoint for specialized external monitoring."""
        now = datetime.now()
        time_string = now.strftime("%Y-%m-%d %H:%M:%S")
        return time_string, 200