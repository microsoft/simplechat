# test_azure_openai_identity_split.py
#!/usr/bin/env python3
"""
Functional test for Azure OpenAI fetch/use identity separation.
Version: 0.250.001
Implemented in: 0.250.001

This test ensures legacy GPT, embedding, and image model discovery uses the
management-plane service principal path while runtime embedding and image
generation managed identity use remains data-plane only.
"""

from pathlib import Path
import re
import sys


REPO_ROOT = Path(__file__).resolve().parents[1]


def read_workspace_file(relative_path):
    """Read a workspace file as UTF-8 text."""
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_backend_and_admin_guidance_identity_split():
    """Validate OpenAI discovery and runtime identity split in backend and admin UI."""
    print("Testing Azure OpenAI management-plane and data-plane identity split...")

    models_route = read_workspace_file("application/single_app/route_backend_models.py")
    settings_route = read_workspace_file("application/single_app/route_backend_settings.py")
    admin_template = read_workspace_file("application/single_app/templates/admin_settings.html")

    legacy_helper_match = re.search(
        r"def build_legacy_aoai_discovery_auth_settings\(\):(?P<body>.*?)\n    def build_inference_client",
        models_route,
        re.DOTALL,
    )
    assert legacy_helper_match, "Expected a legacy AOAI discovery auth helper."
    legacy_helper_body = legacy_helper_match.group("body")

    assert '"type": "service_principal"' in legacy_helper_body, (
        "Legacy GPT, embedding, and image fetch should use the service principal for ARM discovery."
    )
    assert '"tenant_id": TENANT_ID' in legacy_helper_body, (
        "Legacy discovery helper should use the configured Entra tenant."
    )
    assert '"client_id": CLIENT_ID' in legacy_helper_body, (
        "Legacy discovery helper should use the configured app registration client id."
    )
    assert "DefaultAzureCredential" not in legacy_helper_body, (
        "Legacy discovery helper should not switch to the runtime managed identity implicitly."
    )

    assert models_route.count("build_legacy_aoai_discovery_auth_settings()") >= 3, (
        "GPT, embedding, and image fetch routes should share the legacy discovery helper."
    )
    assert "get_aoai_account_name(endpoint)" in models_route, (
        "Fetch routes should normalize AOAI resource endpoints consistently."
    )

    assert "direct_data.get('auth_type') == 'managed_identity'" in settings_route, (
        "Runtime connection tests should still honor managed identity for data-plane calls."
    )
    assert "get_bearer_token_provider(DefaultAzureCredential(), cognitive_services_scope)" in settings_route, (
        "Runtime managed identity calls should use the Cognitive Services data-plane scope."
    )

    assert "Fetch Models</strong> lists deployments through the Azure management plane" in admin_template, (
        "Admin guide should explain that fetch is management-plane discovery."
    )
    assert "Test Connection</strong>, chat generation, file uploads, embedding generation, and image generation call the Azure OpenAI data plane" in admin_template, (
        "Admin guide should explain that generation and upload embeddings are data-plane calls."
    )
    assert "The SimpleChat app registration or service principal" in admin_template, (
        "Admin guide should identify the service principal used for legacy fetch."
    )
    assert "The App Service managed identity" in admin_template, (
        "Admin guide should identify the managed identity used for runtime calls."
    )
    assert "Cognitive Services User" in admin_template, (
        "Admin guide should name the management-plane role for model discovery."
    )
    assert "Cognitive Services OpenAI User" in admin_template, (
        "Admin guide should name the data-plane role for inference."
    )

    print("Azure OpenAI identity split validated.")
    return True


if __name__ == "__main__":
    try:
        success = test_backend_and_admin_guidance_identity_split()
    except Exception as ex:
        print(f"Test failed: {ex}")
        raise

    sys.exit(0 if success else 1)