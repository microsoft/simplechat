# route_external_admin_settings.py:

from config import *
from functions_authentication import *
from functions_settings import *

def register_route_external_admin_settings(app):
    @app.route('/external/applicationsettings/set', methods=['POST'])
    @accesstoken_required
    def external_update_application_settings():
        new_settings = request.get_json(silent=True)
        if new_settings is None:
            # If data is None, it means:
            # 1. No JSON data was sent.
            # 2. The Content-Type header was not 'application/json' (and force=False).
            # 3. The JSON sent was malformed (and silent=True).
            return jsonify({"error": "Request must be JSON and have a 'Content-Type: application/json' header."}), 400

        try:
            update_settings(new_settings)
            print("Settings have been updated")
        except Exception as e:
            # Catch other potential errors during data processing
            return jsonify({"error": f"An error occurred during processing: {str(e)}"}), 500

        return jsonify("Application settings have been updated."), 200
    
    @app.route('/external/applicationsettings/get', methods=['GET'])
    @accesstoken_required
    def external_get_application_settings():
        settings = get_settings()
        return settings, 200
