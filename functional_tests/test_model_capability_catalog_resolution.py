# test_model_capability_catalog_resolution.py
"""
Functional tests for the catalog-backed model capability resolver and schema.
Version: 0.261.042
Implemented in: 0.261.035

Chat model library projections added in: 0.261.042

The qualitative resolver first shipped in 0.261.014. These tests preserve its
override, family-isolation, prefix, and fallback behavior while validating the
schemaVersion 3 token-evidence contract. unittest assertions fail under pytest,
standalone execution, and optimized Python; no failure is returned as False.
"""

import json
import sys
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker, validators

# Standalone execution needs the dependency-light application and test helpers.
TEST_ROOT = Path(__file__).resolve().parent
APP_ROOT = TEST_ROOT.parent / "application" / "single_app"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(APP_ROOT))

import functions_model_capabilities as capabilities
from test_support.versioning import assert_app_version_at_least


CATALOG_PATH = Path(capabilities.get_model_capability_catalog_path())
SCHEMA_PATH = CATALOG_PATH.parent / "schemas" / "model_capabilities.schema.json"


def _is_true_integer(_checker, value):
    """JSON's integral-float equivalence is not the catalog's integer contract."""
    return type(value) is int


CatalogSchemaValidator = validators.extend(
    Draft202012Validator,
    type_checker=Draft202012Validator.TYPE_CHECKER.redefine(
        "integer", _is_true_integer
    ),
)


def load_catalog_schema_validator():
    """Use the shipped schema without resolving any remote schema or source."""
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    CatalogSchemaValidator.check_schema(schema)
    return CatalogSchemaValidator(schema, format_checker=FormatChecker())


class TestModelCapabilityCatalog(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.catalog = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))

    def setUp(self):
        capabilities.reset_model_capability_catalog_cache()

    def tearDown(self):
        capabilities.reset_model_capability_catalog_cache()

    def test_catalog_matches_schema(self):
        """The shipped catalog must validate against the strict v3 schema."""
        validator = load_catalog_schema_validator()
        validator.validate(self.catalog)

        self.assertEqual(self.catalog["schemaVersion"], 3)
        model_ids = [record["id"] for record in self.catalog["models"]]
        self.assertEqual(len(model_ids), len(set(model_ids)))
        providers = {record["provider"] for record in self.catalog["models"]}
        self.assertIn("google", providers)

    def test_family_does_not_leak_capabilities(self):
        """A family must never give one model a sibling's capabilities."""
        families = {}
        for record in self.catalog["models"]:
            families.setdefault(record["family"], []).append(record)

        mixed_families = [
            family
            for family, records in families.items()
            if len({record["capabilities"]["processesImages"] for record in records}) > 1
        ]
        self.assertTrue(mixed_families, "The test needs mixed-vision families.")

        model_ids = {record["id"] for record in self.catalog["models"]}
        for family in mixed_families:
            for record in families[family]:
                with self.subTest(family=family, model=record["id"]):
                    resolved = capabilities.is_vision_capable_model(record["id"])
                    self.assertEqual(resolved, record["capabilities"]["processesImages"])

            if family not in model_ids:
                matched = capabilities.find_model_catalog_record(family)
                self.assertIsNone(matched, f"Bare family {family!r} matched a model.")

    def test_editor_library_is_isolated_and_registry_backed(self):
        document = capabilities.load_model_capability_catalog()
        self.assertIsInstance(document, dict)
        original = json.dumps(document, sort_keys=True)
        records = capabilities.get_model_capability_catalog_records()
        records[0]["capabilities"]["processesImages"] = "mutated"
        self.assertEqual(json.dumps(document, sort_keys=True), original)
        options = capabilities.get_model_endpoint_library_options()
        self.assertTrue(options)
        for option in options:
            descriptor = capabilities.get_model_endpoint_provider(option["api_type"])
            self.assertIsNotNone(descriptor)
            self.assertEqual(option["url_mode"], "auto")
            self.assertEqual(option["catalogSchemaVersion"], 3)
            self.assertTrue(option["sourceIds"])
            self.assertNotIn("capabilities", option)
            self.assertNotIn("api_path", option)
            record = next(record for record in document["models"] if record["id"] == option["id"])
            self.assertTrue(record["capabilities"]["processesText"])
            self.assertTrue(record["capabilities"]["generatesText"])
        options[0]["sourceIds"].clear()
        self.assertEqual(json.dumps(document, sort_keys=True), original)

    def test_longest_prefix_wins(self):
        """Legacy capability matching still accepts exact deployment suffixes."""
        record = capabilities.find_model_catalog_record("gpt-5.1-chat-v2")
        self.assertIsNotNone(record)
        self.assertEqual(record["id"], "gpt-5.1-chat")
        vision = capabilities.is_vision_capable_model("gpt-5.1-chat-v2")
        self.assertFalse(vision)

        record = capabilities.find_model_catalog_record("gpt-5.6-sol-eastus")
        self.assertIsNotNone(record)
        self.assertEqual(record["id"], "gpt-5.6-sol")

    def test_override_precedence(self):
        """Per-model and endpoint overrides outrank catalog and heuristics."""
        model = {"modelName": "gpt-4o", "capabilities": {"processesImages": False}}
        vision = capabilities.is_vision_capable_model(model)
        self.assertFalse(vision)

        endpoint = {"capabilities": {"processesImages": True}}
        unknown_model = {"modelName": "corp-llm-v2"}
        vision = capabilities.is_vision_capable_model(unknown_model, endpoint)
        self.assertTrue(vision)

        conflicting_model = {
            "modelName": "corp-llm-v2",
            "capabilities": {"processesImages": False},
        }
        vision = capabilities.is_vision_capable_model(conflicting_model, endpoint)
        self.assertFalse(vision)

    def test_unknown_model_falls_back_to_heuristics(self):
        """Unknown qualitative capabilities retain the legacy behavior."""
        matched = capabilities.find_model_catalog_record("corp-llm-v2")
        self.assertIsNone(matched)
        for model_name, expected in (
            ("corp-llm-v2", False),
            ("my-vision-model", True),
            ("gpt-4o", True),
        ):
            with self.subTest(model=model_name):
                vision = capabilities.is_vision_capable_model(model_name)
                self.assertEqual(vision, expected)

        streaming = capabilities.supports_streaming("corp-llm-v2")
        self.assertTrue(streaming)
        streaming = capabilities.supports_streaming(
            {"modelName": "corp-llm-v2", "capabilities": {"supportsStreaming": False}}
        )
        self.assertFalse(streaming)

    def test_google_models_resolve(self):
        """Gemini qualitative capabilities resolve from the catalog."""
        record = capabilities.find_model_catalog_record("gemini-3.8-flash")
        self.assertIsNotNone(record)
        self.assertEqual(record["provider"], "google")

        vision = capabilities.is_vision_capable_model("gemini-3.8-flash")
        tool_calling = capabilities.supports_tool_calling("gemini-2.5-pro")
        streaming = capabilities.supports_streaming("gemini-2.5-flash")
        self.assertTrue(vision)
        self.assertTrue(tool_calling)
        self.assertTrue(streaming)

    def test_version_bumped(self):
        """The original capability resolver remains in supported releases."""
        assert_app_version_at_least("0.261.014")


if __name__ == "__main__":
    unittest.main()
