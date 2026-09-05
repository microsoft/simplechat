#!/usr/bin/env python3
"""
Functional test for the catalog-backed model capability resolver.
Version: 0.261.013
Implemented in: 0.261.013

Model capability answers used to be guessed from the model's name, so a model the
catalog did not know about -- an on-premises or customer-supplied model reached
through a Custom endpoint -- silently received wrong answers for vision, tool
calling, streaming, and reasoning.

These tests ensure that:
  * the shipped catalog validates against its JSON schema,
  * capability answers resolve through override -> endpoint -> catalog -> heuristic,
  * catalog matching never lets a model inherit a sibling's capabilities through a
    shared "family" value,
  * a longer, more specific identifier prefix wins over a shorter one,
  * models absent from the catalog still fall back to the legacy heuristics.
"""

import json
import os
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(
    os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "application",
        "single_app",
    )
)

from test_support.versioning import assert_app_version_at_least

import functions_model_capabilities as capabilities


CATALOG_PATH = capabilities.get_model_capability_catalog_path()
SCHEMA_PATH = os.path.join(
    os.path.dirname(CATALOG_PATH),
    "schemas",
    "model_capabilities.schema.json",
)


def test_catalog_matches_schema():
    """The shipped catalog must validate against its own schema."""
    print("Testing model capability catalog schema...")
    try:
        import jsonschema

        with open(SCHEMA_PATH, "r", encoding="utf-8") as schema_file:
            schema = json.load(schema_file)
        with open(CATALOG_PATH, "r", encoding="utf-8") as catalog_file:
            catalog = json.load(catalog_file)

        jsonschema.validate(instance=catalog, schema=schema)

        assert catalog["schemaVersion"] >= 2, "Catalog must be schemaVersion 2 or later."

        model_ids = [record["id"] for record in catalog["models"]]
        assert len(model_ids) == len(set(model_ids)), "Catalog model ids must be unique."

        providers = {record["provider"] for record in catalog["models"]}
        assert "google" in providers, "Catalog must cover Google models."

        print(f"Catalog validated: {len(model_ids)} models, providers={sorted(providers)}")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_family_does_not_leak_capabilities():
    """A shared 'family' must never let one model inherit a sibling's capabilities."""
    print("Testing family isolation...")
    try:
        with open(CATALOG_PATH, "r", encoding="utf-8") as catalog_file:
            catalog = json.load(catalog_file)

        families = {}
        for record in catalog["models"]:
            families.setdefault(record["family"], []).append(record)

        mixed_families = [
            family
            for family, records in families.items()
            if len({r["capabilities"]["processesImages"] for r in records}) > 1
        ]
        assert mixed_families, (
            "Expected at least one family whose members disagree on vision, "
            "otherwise this test proves nothing."
        )

        for family in mixed_families:
            for record in families[family]:
                resolved = capabilities.is_vision_capable_model(record["id"])
                expected = record["capabilities"]["processesImages"]
                assert resolved == expected, (
                    f"{record['id']} in family '{family}' resolved vision={resolved}, "
                    f"catalog says {expected}"
                )

        # A bare family name must not resolve to any member of that family.
        for family in mixed_families:
            if family not in {record["id"] for record in catalog["models"]}:
                assert capabilities.find_model_catalog_record(family) is None, (
                    f"Bare family name '{family}' must not match a specific model."
                )

        print(f"Family isolation held for: {sorted(mixed_families)}")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_longest_prefix_wins():
    """A deployment suffix must resolve to the most specific catalog record."""
    print("Testing longest-prefix identifier matching...")
    try:
        record = capabilities.find_model_catalog_record("gpt-5.1-chat-v2")
        assert record is not None, "Expected a catalog match for gpt-5.1-chat-v2."
        assert record["id"] == "gpt-5.1-chat", (
            f"gpt-5.1-chat-v2 must resolve to gpt-5.1-chat, got {record['id']}"
        )
        assert capabilities.is_vision_capable_model("gpt-5.1-chat-v2") is False

        record = capabilities.find_model_catalog_record("gpt-5.6-sol-eastus")
        assert record is not None and record["id"] == "gpt-5.6-sol"

        print("Longest-prefix matching passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_override_precedence():
    """Per-model and endpoint overrides must outrank the catalog and heuristics."""
    print("Testing capability override precedence...")
    try:
        # gpt-4o is vision-capable by heuristic and catalog; an explicit override wins.
        model = {"modelName": "gpt-4o", "capabilities": {"processesImages": False}}
        assert capabilities.is_vision_capable_model(model) is False, (
            "Per-model override must outrank the catalog."
        )

        # An endpoint-level override applies when the model declares nothing.
        endpoint = {"capabilities": {"processesImages": True}}
        unknown_model = {"modelName": "corp-llm-v2"}
        assert capabilities.is_vision_capable_model(unknown_model, endpoint) is True, (
            "Endpoint override must apply to an otherwise unknown model."
        )

        # The model override still wins over the endpoint override.
        conflicting_model = {"modelName": "corp-llm-v2", "capabilities": {"processesImages": False}}
        assert capabilities.is_vision_capable_model(conflicting_model, endpoint) is False

        print("Override precedence passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_unknown_model_falls_back_to_heuristics():
    """Models absent from the catalog keep the legacy name-based answers."""
    print("Testing heuristic fallback for unknown models...")
    try:
        assert capabilities.find_model_catalog_record("corp-llm-v2") is None
        assert capabilities.is_vision_capable_model("corp-llm-v2") is False
        assert capabilities.is_vision_capable_model("my-vision-model") is True
        assert capabilities.is_vision_capable_model("gpt-4o") is True

        # Streaming defaults to True for unknown models so nothing is wrongly wrapped.
        assert capabilities.supports_streaming("corp-llm-v2") is True
        # But an explicit declaration is honoured.
        assert capabilities.supports_streaming(
            {"modelName": "corp-llm-v2", "capabilities": {"supportsStreaming": False}}
        ) is False

        print("Heuristic fallback passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_google_models_resolve():
    """Gemini models must resolve from the catalog rather than the name heuristics."""
    print("Testing Google model resolution...")
    try:
        record = capabilities.find_model_catalog_record("gemini-3.8-flash")
        assert record is not None, "gemini-3.8-flash must be in the catalog."
        assert record["provider"] == "google"

        # The legacy heuristics answer False for every Gemini capability.
        assert capabilities.is_vision_capable_model("gemini-3.8-flash") is True
        assert capabilities.supports_tool_calling("gemini-2.5-pro") is True
        assert capabilities.supports_streaming("gemini-2.5-flash") is True

        print("Google model resolution passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


def test_version_bumped():
    """The capability resolver ships at or after its implementation version."""
    print("Testing config version...")
    try:
        assert_app_version_at_least("0.261.013")
        print("Config version check passed")
        return True
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback

        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_catalog_matches_schema,
        test_family_does_not_leak_capabilities,
        test_longest_prefix_wins,
        test_override_precedence,
        test_unknown_model_falls_back_to_heuristics,
        test_google_models_resolve,
        test_version_bumped,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
