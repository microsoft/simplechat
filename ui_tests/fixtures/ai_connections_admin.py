# ai_connections_admin.py
"""
Closed API fixtures for shared AI Connections admin browser tests.
Version: 0.261.108
Implemented in: 0.261.105; embeddings added in 0.261.106

Reuse the built-SPA and local/Azure browser fixtures. All requests are intercepted;
no Azure inference, authentication, or settings services are called.
"""

import copy
from urllib.parse import urlsplit

from playwright.sync_api import expect

from v2_admin_settings import AdminSettingsFixture, ORIGIN, SPA_INDEX, STATIC_ROOT
from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV

CONNECTIONS = import_app_module("functions_ai_connections")
ENDPOINT_TYPES = import_app_module("functions_model_endpoint_types")

COHERE_EMBEDDING_MODELS = {
    "embed-v-4-0", "embed-v4.0", "cohere-embed-v3-english", "cohere-embed-v3-multilingual",
    "embed-english-v3.0", "embed-multilingual-v3.0",
}
PUBLIC_EMBEDDING_POLICY_FIELDS = {
    "dimensions", "default_dimensions", "supports_dimensions", "request_dimensions",
    "min_dimensions", "max_dimensions", "allowed_dimensions", "max_input_tokens",
    "max_batch_size", "max_batch_tokens", "tokenizer", "api", "requires_input_type",
}


def support(supported=True, api="chat", source="catalog"):
    return {"supported": supported, "available": supported, "source": source, "api": api, "reason": ""}


def connection(identifier, name, models, provider="aoai"):
    return {
        "id": identifier, "name": name, "provider": provider, "enabled": True,
        **({"api_type": "openai"} if provider == "custom" else {}),
        "connection": {
            "endpoint": "https://api.openai.com/v1" if provider == "custom" else f"https://{identifier}.openai.azure.com",
            "openai_api_version": "2024-05-01-preview",
            "operation_settings": {"image_generation": {"api_version": "2025-04-01-preview"}},
        },
        "auth": {"type": "api_key"}, "has_api_key": True, "models": models,
    }


def reference(endpoint_id="", model_id="", provider=""):
    return {"endpoint_id": endpoint_id, "model_id": model_id, "provider": provider}


def image_import_error_notice():
    """Match initialize_ai_connections' retained-settings failure response."""
    return {
        "status": "error",
        "message": (
            "Image connection import could not finish. Review connection and Key Vault permissions. "
            "Existing image settings remain active. Restart after correcting the configuration to retry."
        ),
    }

def embedding_import_error_notice():
    return {
        "status": "error",
        "message": "Embedding connection import could not finish. Existing embedding settings remain active. Review the saved configuration before retrying.",
    }


def embedding_model(identifier="embedding-model", model_name="text-embedding-3-small", dimensions=1536):
    cohere = model_name.lower() in COHERE_EMBEDDING_MODELS
    v3 = cohere and "v3" in model_name.lower()
    default_dimensions = 1024 if v3 else 3072 if model_name == "text-embedding-3-large" else 1536
    model = {
        "id": identifier, "deploymentName": "docs-embedding", "modelName": model_name,
        "displayName": "Document embeddings", "enabled": True,
        "capability_status": {
            "chat": support(False), "image_generation": support(False, api="images"),
            "embeddings": support(not cohere, api="openai"), "vision": {"supported": False, "source": "catalog"},
        },
        "embedding_policy": {
            "dimensions": dimensions, "default_dimensions": default_dimensions, "supports_dimensions": not v3 and model_name != "text-embedding-ada-002",
            "max_input_tokens": 512 if cohere else 8192, "max_batch_size": 8, "max_batch_tokens": 16384,
            "tokenizer": "conservative" if cohere else "cl100k_base",
            "api": "unsupported" if cohere else "openai", "requires_input_type": cohere,
        },
    }
    if dimensions != default_dimensions:
        model["embedding_config"] = {"dimensions": dimensions}
    if cohere:
        model["capability_status"]["embeddings"]["reason"] = "A verified OpenAI-compatible gateway is required for this embedding model."
    return model


class AIConnectionsFixture(AdminSettingsFixture):
    """Production V2 components over deterministic, in-memory capability contracts."""

    def __init__(self, page):
        super().__init__(page)
        fields = import_app_module("admin_settings_fields")
        group = copy.deepcopy(next(group for group in ADMIN_NAV if group["id"] == "ai-models"))
        group["tabs"] = [tab for tab in group["tabs"] if tab["id"] in {"model-endpoints", "image-generation", "embeddings"}]
        section_ids = [section["id"] for tab in group["tabs"] for section in tab["sections"]]
        self.schema = {key: copy.deepcopy(fields.get_admin_settings_fields()[key]) for key in section_ids}
        self.settings = {
            field["key"]: copy.deepcopy(field["default"])
            for section in self.schema.values() for field in section
            if field.get("key") and "default" in field
        }
        self.settings.update({"enable_multi_model_endpoints": True, "enable_image_generation": True})
        self.custom_api_types = import_app_module("functions_model_endpoint_providers").get_model_endpoint_provider_ui_options()
        self.default_notices = {}
        self.payload.update({"admin_nav": [group], "field_schema": self.schema, "settings": self.settings})
        dual = {
            "id": "same:model", "deploymentName": "same-deployment", "modelName": "gpt-5.6-sol",
            "displayName": "Dual model", "enabled": True,
            "capability_status": {
                "chat": support(), "image_generation": support(api="responses"),
                "vision": {"supported": True, "source": "catalog"},
            },
        }
        imported = {**copy.deepcopy(dual), "displayName": "Imported image model", "enabled_capabilities": ["image_generation"]}
        image = {
            "id": "image-only", "deploymentName": "custom-image-name", "modelName": "gpt-image-1",
            "displayName": "Image only", "enabled": True,
            "capability_status": {"chat": support(False), "image_generation": support(api="images")},
        }
        self.endpoints = [
            connection("team", "Team OpenAI", [dual], provider="custom"),
            connection("studio", "Imported Studio", [imported], provider="custom"),
            connection("images", "Image Resource", [image]),
            connection("vectors", "Vector Resource", [embedding_model()]),
        ]
        self.selections = {
            "chat": reference("team", "same:model", "custom"),
            "image_generation": reference("studio", "same:model", "custom"),
            "embeddings": reference("vectors", "embedding-model", "aoai"),
        }
        self.refresh_capabilities()
        self.migration = {"status": "complete", "message": "Existing image configuration is now managed through AI Connections.", "imported_connections": 1}
        self.embedding_migration = {"status": "complete", "message": "Existing embedding configuration is now managed through AI Connections.", "imported_connections": 1}
        self.embedding_compatibility = {"status": "compatible", "message": "Existing vectors use the current embedding profile.", "dimensions": 1536, "profile_id": "fixture-profile"}
        self.selection_writes = []
        self.connection_writes = []
        self.image_tests = []
        self.embedding_tests = []
        self.connection_tests = []
        self.chat_tests = []
        self.reject_selection = False
        self.reject_connection = False
        self.reject_image_test = False
        self.reject_embedding_test = False
        self.selection_error = None
        self.selection_error_status = 400
        self.connection_error = None
        self.connection_error_status = 400
        self.expected_http_errors = 0
        self.capability_reads = []

    def resolve_models(self, endpoint):
        for model in endpoint["models"]:
            model["capability_status"] = CONNECTIONS.describe_model_capabilities(
                model, endpoint["provider"], endpoint=endpoint,
            )
            if model["capability_status"]["embeddings"]["supported"]:
                model["embedding_policy"] = CONNECTIONS.resolve_embedding_policy(model)

    @staticmethod
    def editor_endpoint(endpoint):
        """Connection records carry declarations/status, not the picker's resolved policy."""
        result = copy.deepcopy(endpoint)
        for model in result.get("models", []):
            model.pop("embedding_policy", None)
        return result
    def refresh_capabilities(self):
        for endpoint in self.endpoints:
            self.resolve_models(endpoint)

    def add_custom_embedding_connection(self, api_type="openai", auth_type="api_key"):
        embedding = embedding_model("custom-embedding")
        embedding["deploymentName"] = "embedding-wire-alias"
        embedding["embedding_config"] = {
            "max_batch_size": 2, "model_revision": "fixture-revision",
            "document_prefix": "passage: ", "query_prefix": "query: ",
        }
        embedding["vendorOptions"] = {"future": ["retained"]}
        image = copy.deepcopy(self.endpoints[0]["models"][0])
        image.update({
            "supportsImageEditing": True, "supportsImageMasking": True,
            "image_generation_api": "responses",
        })
        endpoint = connection("custom-vectors", "Custom Mixed Gateway", [image, embedding], provider="custom")
        endpoint["api_type"] = api_type
        endpoint["connection"].update(endpoint="https://gateway.example.test/prefix/api/v1", url_mode="exact")
        endpoint["connection"].pop("openai_api_version", None)
        if api_type == "azure_openai":
            endpoint["connection"]["api_version"] = "2025-04-01-preview"
        endpoint["auth"] = {"type": auth_type}
        endpoint["has_api_key"] = auth_type == "api_key"
        endpoint["has_bearer_token"] = auth_type == "bearer"
        endpoint["has_client_secret"] = auth_type == "oauth2_client_credentials"
        if auth_type == "oauth2_client_credentials":
            endpoint["auth"].update(token_url="https://identity.example.test/token", client_id="fixture-client")
        self.endpoints.append(endpoint)
        self.refresh_capabilities()
        return endpoint

    def add_embedding_alias(self):
        embedding = embedding_model("alias-embedding")
        embedding["deploymentName"] = "saved-wire-alias"
        endpoint = connection("alias-vectors", "Saved Embedding Alias", [embedding], provider="openai_compatible")
        endpoint["connection"] = {
            "endpoint": "https://gateway.example.test/preserved/base",
            "operation_settings": {"embeddings": {"api": "openai", "auth_header": "authorization"}},
        }
        self.endpoints.append(endpoint)
        self.refresh_capabilities()
        return endpoint

    def add_provider_image_connection(self, model_name):
        endpoint = connection("provider-image", "Provider Images", [{
            "id": "provider-image-model", "deploymentName": "image-wire-alias",
            "modelName": model_name, "displayName": model_name, "enabled": True,
            "supportsChat": True,
        }], provider="new_foundry")
        endpoint["connection"].update({
            "endpoint": "https://resource.services.ai.azure.com/api/projects/project",
            "openai_api_version": "v1", "project_api_version": "v1",
        })
        self.endpoints.append(endpoint)
        self.refresh_capabilities()
        return endpoint

    @staticmethod
    def retain_credentials(endpoint, previous=None):
        auth = endpoint.setdefault("auth", {})
        for field in ("api_key", "bearer_token", "client_secret"):
            marker = f"has_{field}"
            endpoint[marker] = bool(auth.pop(field, "")) or endpoint.get(marker, False) or (previous or {}).get(marker, False)

    def capability_response(self, capability):
        choices = []
        for endpoint in self.endpoints:
            if not endpoint.get("enabled", True):
                continue
            for model in endpoint["models"]:
                status = model.get("capability_status", {}).get(capability, support(False))
                allowed = model.get("enabled_capabilities")
                if not model.get("enabled", True) or not status["supported"] or status.get("available") is False or (allowed is not None and capability not in allowed):
                    continue
                if capability == "embeddings":
                    policy = model.get("embedding_policy", {})
                    if (
                        policy.get("api") != "openai"
                        or any(type(policy.get(key)) is not int or policy[key] <= 0 for key in ("dimensions", "max_input_tokens"))
                    ):
                        continue
                choices.append({
                    **reference(endpoint["id"], model["id"], endpoint["provider"]),
                    "connection_name": endpoint["name"], "label": model["displayName"],
                    "deployment_name": ENDPOINT_TYPES.resolve_model_endpoint_request_model(endpoint, model),
                    "capability": status,
                    **({"embedding_policy": {
                        key: value for key, value in model.get("embedding_policy", {}).items()
                        if key in PUBLIC_EMBEDDING_POLICY_FIELDS
                    }} if capability == "embeddings" else {}),
                })
        selected = self.selections[capability]
        valid = any(item["endpoint_id"] == selected["endpoint_id"] and item["model_id"] == selected["model_id"] for item in choices)
        return {
            "capability": capability,
            "selection": reference() if capability == "embeddings" and not valid else selected,
            "choices": choices,
            "reason": "The saved default is no longer available. Choose a replacement." if selected["endpoint_id"] and not valid else None,
            "enabled": True if capability == "embeddings" else self.settings["enable_multi_model_endpoints" if capability == "chat" else "enable_image_generation"],
            "migration": self.embedding_migration if capability == "embeddings" else self.migration,
            **({"compatibility": self.embedding_compatibility} if capability == "embeddings" else {}),
        }

    def _route(self, route):
        request = route.request
        path = urlsplit(request.url).path
        if not request.url.startswith(ORIGIN + "/"):
            return super()._route(route)
        if path.startswith("/api/v2/admin/capability-models/"):
            capability = path.rsplit("/", 1)[-1]
            if capability not in self.selections:
                self.unexpected_requests.append(path)
                route.fulfill(status=404, json={"error": "Unknown capability"})
            elif request.method == "PUT":
                selected = request.post_data_json["selection"]
                self.selection_writes.append((capability, copy.deepcopy(selected)))
                if self.reject_selection:
                    self.reject_selection = False
                    self.expected_http_errors += 1
                    route.fulfill(status=self.selection_error_status, json={
                        "error": self.selection_error or f"The {'embedding' if capability == 'embeddings' else 'image'} default could not be saved.",
                        "code": "embedding_profile_incompatible" if capability == "embeddings" else "invalid_selection",
                    })
                else:
                    self.selections[capability] = selected
                    if capability == "image_generation":
                        self.settings["image_generation_model_selection"] = copy.deepcopy(selected)
                        self.settings["ai_connections_image_migration_version"] = 1
                    elif capability == "embeddings":
                        self.settings["embedding_model_selection"] = copy.deepcopy(selected)
                        self.settings["ai_connections_embedding_migration_version"] = 1
                    route.fulfill(json=self.capability_response(capability))
            else:
                self.capability_reads.append(capability)
                route.fulfill(json=self.capability_response(capability))
        elif path == "/api/v2/admin/model-endpoints" and request.method == "GET":
            route.fulfill(json={
                "endpoints": [self.editor_endpoint(endpoint) for endpoint in self.endpoints], "multi_endpoint_enabled": self.settings["enable_multi_model_endpoints"],
                "migration": self.migration, "embedding_migration": self.embedding_migration,
                "default_notices": self.default_notices, "custom_api_types": self.custom_api_types,
                "custom_network_policy": {
                    "allow_private_custom_model_endpoints": self.settings.get("allow_private_custom_model_endpoints", False),
                    "allow_insecure_custom_model_endpoints": self.settings.get("allow_insecure_custom_model_endpoints", False),
                    "custom_model_endpoint_ca_bundle_path": self.settings.get("custom_model_endpoint_ca_bundle_path", ""),
                },
            })
        elif path == "/api/v2/admin/model-endpoints" and request.method == "POST":
            saved = request.post_data_json
            self.connection_writes.append(copy.deepcopy(saved))
            saved["id"] = "manual-connection"
            self.resolve_models(saved)
            self.retain_credentials(saved)
            self.endpoints.append(saved)
            route.fulfill(json={"endpoint": self.editor_endpoint(saved)})
        elif path.startswith("/api/v2/admin/model-endpoints/") and request.method == "PATCH":
            endpoint = next(item for item in self.endpoints if item["id"] == path.rsplit("/", 1)[-1])
            changes = request.post_data_json
            self.connection_writes.append(copy.deepcopy(changes))
            if self.reject_connection:
                self.reject_connection = False
                self.expected_http_errors += 1
                route.fulfill(status=self.connection_error_status, json={"error": self.connection_error or "The connection could not be saved."})
            else:
                previous = copy.deepcopy(endpoint)
                endpoint.update(changes)
                self.retain_credentials(endpoint, previous)
                self.resolve_models(endpoint)
                route.fulfill(json={"endpoint": self.editor_endpoint(endpoint)})
        elif path.startswith("/api/v2/admin/model-endpoints/") and request.method == "DELETE":
            if self.reject_connection:
                self.reject_connection = False
                self.expected_http_errors += 1
                route.fulfill(status=self.connection_error_status, json={"error": self.connection_error or "The connection could not be deleted."})
            else:
                self.endpoints = [endpoint for endpoint in self.endpoints if endpoint["id"] != path.rsplit("/", 1)[-1]]
                route.fulfill(json={"success": True})
        elif path == "/api/v2/admin/settings/test-connection" and request.method == "POST":
            if request.post_data_json.get("test_type") == "embedding":
                self.embedding_tests.append(request.post_data_json)
                route.fulfill(json={
                    "success": not self.reject_embedding_test, "dimensions": 1536,
                    "error": "Embedding inference returned incompatible dimensions." if self.reject_embedding_test else "",
                })
            else:
                self.image_tests.append(request.post_data_json)
                route.fulfill(json={"success": not self.reject_image_test, "error": "The saved model did not return an image." if self.reject_image_test else ""})
        elif path == "/api/models/test-connection":
            self.connection_tests.append(request.post_data_json)
            route.fulfill(json={"success": True, "count": 2})
        elif path == "/api/models/test-model":
            self.chat_tests.append(request.post_data_json)
            route.fulfill(json={"success": True})
        elif path == "/api/models/vision-capability":
            route.fulfill(json={"models": {}})
        else:
            super()._route(route)

    def open(self, width=1440):
        assert SPA_INDEX.is_file(), "Build the V2 SPA before running browser tests."
        source_root = STATIC_ROOT.parent.parent / "v2_ui" / "src"
        assert not any(path.stat().st_mtime > SPA_INDEX.stat().st_mtime for path in source_root.rglob("*") if path.is_file()), "Rebuild the V2 SPA before running browser tests."
        self.preferences = {"darkModeEnabled": False, "v2RailCollapsed": width < 1024}
        self.page.set_viewport_size({"width": width, "height": 1100})
        self.page.goto(f"{ORIGIN}/v2/admin", wait_until="networkidle")
        expect(self.page.get_by_role("region", name="AI Connections", exact=True)).to_be_visible()
        expect(self.page.get_by_label("Default image model", exact=True)).to_be_enabled()
        expect(self.page.get_by_label("Default embedding model", exact=True)).to_be_enabled()

    def assert_clean(self):
        resource_errors = [
            error for error in self.errors
            if error.startswith("Failed to load resource:") and any(str(status) in error for status in (400, 409, 503))
        ]
        assert len(resource_errors) <= self.expected_http_errors
        assert not [error for error in self.errors if error not in resource_errors], self.errors
        assert not self.unexpected_requests, self.unexpected_requests
