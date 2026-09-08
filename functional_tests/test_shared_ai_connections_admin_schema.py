# test_shared_ai_connections_admin_schema.py
"""
Schema coverage for shared image defaults and retained legacy compatibility fields.
Version: 0.261.102
Implemented in: 0.261.102
"""

from test_support.app_stubs import import_app_module
from test_support.nav import ADMIN_NAV


fields_module = import_app_module("admin_settings_fields")


def test_normal_image_surface_has_one_shared_picker_and_no_duplicate_credentials():
    fields = fields_module.get_admin_settings_fields()["image-config"]
    active = [field for field in fields if not field.get("legacy")]
    assert [field["key"] for field in active] == [
        "enable_image_generation", "image_generation_model_selection",
    ]
    assert active[1]["component"] == "image-generation-model-selection"
    assert "depends_on" not in active[1]
    legacy = {field["key"] for field in fields if field.get("legacy")}
    assert {"image_gen_model", "azure_openai_image_gen_key", "azure_apim_image_gen_subscription_key", "enable_image_gen_apim"} <= legacy
    assert {"azure_openai_image_gen_key", "azure_apim_image_gen_subscription_key"} <= fields_module.get_secret_field_keys()


def test_shared_default_and_legacy_catalog_cannot_use_scalar_settings_patch():
    for key in ("image_generation_model_selection", "image_gen_model"):
        normalized, errors, _warnings = fields_module.normalize_admin_settings_updates({key: {}}, {})
        assert key in errors and key not in normalized


def test_ai_connections_labels_keep_existing_navigation_ids():
    group = next(item for item in ADMIN_NAV if item["id"] == "ai-models")
    tab = next(item for item in group["tabs"] if item["id"] == "model-endpoints")
    assert tab["label"] == "AI Connections"
    section = next(item for item in tab["sections"] if item["id"] == "multi-endpoint-configuration")
    assert section["label"] == "AI Connections"
