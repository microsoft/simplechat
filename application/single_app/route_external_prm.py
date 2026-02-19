# route_external_prm.py
"""Protected Resource Metadata (PRM) endpoint for SimpleChat."""

from config import *
from swagger_wrapper import swagger_route, get_auth_security


def register_route_external_prm(app):
    @app.route('/.well-known/oauth-protected-resource', methods=['GET'])
    @swagger_route(security=get_auth_security())
    def get_prm_metadata():
        resource = request.host_url.rstrip('/')
        metadata = {
            "resource": resource,
            "resource_name": "SimpleChat",
            "resource_documentation": "https://microsoft.github.io/simplechat/",
            "authorization_servers": [
                f"https://login.microsoftonline.com/{TENANT_ID}/v2.0"
            ],
            "scopes_supported": [
                f"api://{CLIENT_ID}/.default"
            ],
            "bearer_methods_supported": [
                "header"
            ]
        }
        return jsonify(metadata), 200
