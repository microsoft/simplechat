# route_external_health.py

from config import *
from functions_authentication import *
from functions_settings import *
from functions_prompts import *

def register_route_external_health(app):
    @app.route('/external/healthcheck', methods=['GET'])
    @enabled_required("enable_external_healthcheck")
    def health_check():
        now = datetime.now()
        time_string = now.strftime("%Y-%m-%d %H:%M:%S")
        return time_string, 200