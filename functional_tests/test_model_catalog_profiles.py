# test_model_catalog_profiles.py
"""
Functional tests for reusable profiles and per-step model routing.
Version: 0.261.126
Implemented in: 0.261.126

Exercises real dependency-light profile/routing modules, without network or storage.
"""

from copy import deepcopy
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from functions_model_catalog import (
    ModelCatalogError, apply_model_profile, change_catalog, find_profile,
    get_effective_model_profiles, normalize_custom_profile, model_profile_projection,
    supports_auto_chat,
)
from functions_orchestration_model_routing import (
    answer_selection, assign_step_models, step_model_context, validate_auto_bindings,
)


def custom_profile(**updates):
    return {
        "displayName": "Internal text model",
        "publisher": "Internal",
        "summary": "Verified internal text deployment.",
        "capabilities": {"processesText": True, "generatesText": True},
        "tasks": {"general": "suitable", "summarization": "strong"},
        **updates,
    }


def candidate(key, tasks, *, favorite=False, priority="standard", capabilities=None):
    return {
        "key": key, "label": key,
        "selection": {"model_deployment": key, "model_endpoint_id": f"ep-{key}", "model_id": key, "model_provider": "custom"},
        "profile": {
            "id": key, "revision": "one", "tasks": tasks, "archived": False,
            "preferences": {"favorite": favorite, "priority": priority},
        },
        "capabilities": capabilities or {"processesText": True, "generatesText": True},
    }


class ProfileTests(unittest.TestCase):
    def test_create_edit_preferences_and_archive_preserve_identity(self):
        settings = change_catalog({}, profile=custom_profile())
        profile = get_effective_model_profiles(settings)[-1]
        profile_id, revision = profile["id"], profile["revision"]
        settings = change_catalog(settings, profile_id=profile_id, preferences={"favorite": True, "priority": "preferred"})
        preferred = get_effective_model_profiles(settings)[-1]
        self.assertEqual(preferred["revision"], revision)
        self.assertTrue(preferred["preferences"]["favorite"])
        settings = change_catalog(settings, profile_id=profile_id, profile=custom_profile(archived=True))
        archived = find_profile({"catalogProfileId": profile_id}, settings)
        self.assertTrue(archived["archived"])
        self.assertNotEqual(archived["revision"], revision)
        self.assertEqual(archived["id"], profile_id)

    def test_built_in_facts_are_immutable_but_preferences_are_editable(self):
        with self.assertRaises(ModelCatalogError):
            change_catalog({}, profile_id="gpt-5", profile=custom_profile())
        settings = change_catalog({}, profile_id="gpt-5", preferences={"favorite": True})
        profile = find_profile({"modelName": "gpt-5"}, settings)
        self.assertTrue(profile["preferences"]["favorite"])
        self.assertEqual(profile["origin"], "built_in")

    def test_alias_collision_and_invalid_fields_are_rejected(self):
        for updates in (
            {"aliases": ["gpt-5"]}, {"secret": "not-permitted"},
            {"tasks": {"magic": "strong"}}, {"tasks": {"general": 5}},
            {"capabilities": {"toolCalling": "true"}}, {"capabilities": {"toolCalling": 1}},
            {"sources": ["javascript:evil()"]}, {"sources": ["https://user:pass@example.test"]},
            {"archived": "false"}, {"displayName": ""}, {"summary": "x" * 1201},
            {"sources": ["https://[invalid"]}, {"sources": ["https://example.test:99999/path"]},
            {"sources": ["https://example.test/unsafe path"]}, {"aliases": ["internal", "INTERNAL"]},
        ):
            with self.subTest(updates=updates):
                with self.assertRaises(ModelCatalogError):
                    change_catalog({}, profile=custom_profile(**updates))

    def test_custom_aliases_require_an_explicit_association(self):
        settings = change_catalog({}, profile=custom_profile(aliases=["internal-model"]))
        unlinked = find_profile({"modelName": "internal-model"}, settings)
        self.assertIsNone(unlinked)
        profile_id = get_effective_model_profiles(settings)[-1]["id"]
        first = find_profile({"modelName": "first", "catalogProfileId": profile_id}, settings)
        second = find_profile({"modelName": "second", "catalogProfileId": profile_id}, settings)
        self.assertEqual(first["id"], second["id"])

    def test_profile_is_not_a_deployment_and_does_not_overwrite_overrides(self):
        settings = change_catalog({}, profile=custom_profile(capabilities={
            "processesText": True, "generatesText": True, "processesImages": True,
        }))
        profile_id = get_effective_model_profiles(settings)[-1]["id"]
        model = {"id": "deployment-one", "modelName": "private", "catalogProfileId": profile_id, "supportsVision": False}
        saved = deepcopy(model)
        effective = apply_model_profile(model, {"capabilities": {"toolCalling": False}}, settings)
        self.assertEqual(model, saved)
        self.assertFalse(effective["capabilities"]["processesImages"])
        self.assertFalse(effective["capabilities"]["toolCalling"])
        self.assertTrue(effective["capabilities"]["generatesText"])
        self.assertEqual(effective["modelName"], "private")
        self.assertNotIn("contextWindow", effective)
        self.assertNotIn("auth", effective)

    def test_unknown_and_incomplete_profiles_remain_unknown(self):
        profile = normalize_custom_profile({"displayName": "Only a description"})
        self.assertEqual(profile["capabilities"], {})
        self.assertEqual(profile["tasks"], {})
        with self.assertRaises(ModelCatalogError):
            find_profile({"catalogProfileId": "custom:missing"}, {})

    def test_built_in_selection_evidence_and_copy_isolation(self):
        profiles = get_effective_model_profiles({})
        self.assertGreater(len(profiles), 100)
        nano = next(profile for profile in profiles if profile["id"] == "gpt-5-nano")
        self.assertEqual(nano["tasks"]["summarization"], "strong")
        self.assertEqual(nano["verifiedAt"], "2026-09-21")
        self.assertTrue(nano["sources"])
        nano["capabilities"].clear()
        fresh = find_profile({"modelName": "gpt-5-nano"}, {})
        self.assertTrue(fresh["capabilities"]["generatesText"])

    def test_unknown_link_does_not_break_other_catalog_rows(self):
        projection = model_profile_projection({"catalogProfileId": "custom:missing"}, {}, {})
        self.assertFalse(projection["auto_routing_available"])
        self.assertIn("unavailable", projection["profile_error"])
        valid = model_profile_projection({"modelName": "gpt-5"}, {}, {})
        self.assertTrue(valid["auto_routing_available"])
        self.assertEqual(valid["profile"]["id"], "gpt-5")

    def test_responses_only_models_cannot_be_enabled_for_auto_by_a_custom_link(self):
        settings = change_catalog({}, profile=custom_profile())
        profile_id = get_effective_model_profiles(settings)[-1]["id"]
        for name in ("gpt-5-pro", "gpt-5.4-pro", "gpt-5.3-codex", "gpt-5.1-codex"):
            with self.subTest(name=name):
                available = supports_auto_chat({"modelName": name, "catalogProfileId": profile_id}, settings)
                self.assertFalse(available)

    def test_transform_and_aggregate_limit_do_not_mutate_input(self):
        original = {"unrelated": {"keep": True}}
        saved = change_catalog(original, profile=custom_profile())
        self.assertNotIn("model_catalog", original)
        self.assertTrue(saved["unrelated"]["keep"])
        with patch("functions_model_catalog.MAX_CATALOG_BYTES", 20):
            with self.assertRaises(ModelCatalogError):
                change_catalog(original, profile=custom_profile())
        self.assertNotIn("model_catalog", original)


class RoutingTests(unittest.TestCase):
    def test_auto_chooses_a_different_model_for_each_step(self):
        candidates = [
            candidate("summary", {"general": "suitable", "summarization": "strong"}),
            candidate("code", {"general": "suitable", "coding": "strong"}),
        ]
        plan = {"steps": [
            {"capability_id": "document_analyze", "model_task": "summarization"},
            {"capability_id": "respond", "model_task": "coding"},
            {"capability_id": "document_search"},
        ]}
        result = assign_step_models(plan, candidates)
        self.assertEqual(result["steps"][0]["model_binding"]["label"], "summary")
        self.assertEqual(result["steps"][1]["model_binding"]["label"], "code")
        self.assertNotIn("model_binding", result["steps"][2])
        selected = answer_selection(plan, {"model": {"model_deployment": "bootstrap"}})
        self.assertEqual(selected["model"]["model_deployment"], "code")

    def test_suitability_beats_favorite_and_priority(self):
        profiles = [
            candidate("favorite", {"coding": "suitable"}, favorite=True, priority="preferred"),
            candidate("specialist", {"coding": "strong"}, priority="lower"),
        ]
        plan = assign_step_models({"steps": [{"capability_id": "respond", "model_task": "coding"}]}, profiles)
        self.assertEqual(plan["steps"][0]["model_binding"]["label"], "specialist")

    def test_preferences_break_ties_stably(self):
        rows = [
            candidate("z", {"general": "suitable"}, favorite=True),
            candidate("a", {"general": "suitable"}),
        ]
        first = assign_step_models({"steps": [{"capability_id": "respond"}]}, rows)
        self.assertEqual(first["steps"][0]["model_binding"]["label"], "z")
        rows[1]["profile"]["preferences"]["priority"] = "preferred"
        second = assign_step_models({"steps": [{"capability_id": "respond"}]}, list(reversed(rows)))
        self.assertEqual(second["steps"][0]["model_binding"]["label"], "a")

    def test_incompatibility_archival_and_unknown_suitability_are_not_fallbacks(self):
        row = candidate("favorite", {"tool_use": "strong"}, favorite=True, priority="preferred")
        with self.assertRaises(ModelCatalogError):
            assign_step_models({"steps": [{"capability_id": "action_invoke"}]}, [row])
        row["capabilities"]["toolCalling"] = True
        row["profile"]["archived"] = True
        with self.assertRaises(ModelCatalogError):
            assign_step_models({"steps": [{"capability_id": "action_invoke"}]}, [row])
        with self.assertRaises(ModelCatalogError):
            assign_step_models({"steps": [{"capability_id": "respond", "model_task": "coding"}]},
                               [candidate("general", {"general": "strong"})])

    def test_manual_selection_is_unchanged(self):
        seeds = {"model": {"model_deployment": "pinned"}, "reasoning_effort": "high"}
        actual = answer_selection({"steps": []}, seeds)
        self.assertIs(actual, seeds)

    def test_group_binding_retains_document_scope_and_reauthorizes_every_step(self):
        row = candidate("group-model", {"general": "suitable"})
        row["scope_id"] = "model-group"
        plan = assign_step_models({"steps": [{"capability_id": "respond"}]}, [row])
        selected = answer_selection(plan, {"active_group_ids": ["document-group"]})
        self.assertEqual(selected["active_group_ids"], ["document-group", "model-group"])
        resolver = Mock(side_effect=PermissionError("revoked"))
        with self.assertRaises(PermissionError):
            validate_auto_bindings(plan, {}, {}, resolver)
        resolver.assert_called_once()

    def test_step_context_closes_and_restores_after_failure(self):
        settings = change_catalog({}, profile=custom_profile())
        profile = get_effective_model_profiles(settings)[-1]
        metadata = apply_model_profile({"catalogProfileId": profile["id"], "modelName": "internal"}, {}, settings)
        model = SimpleNamespace(
            model_metadata=metadata, deployment="deployed", model_id="one", endpoint_id="ep",
            provider="custom", as_planner_client=lambda: "planner", close=Mock(),
        )
        binding = {"selection": {"model_deployment": "deployed"}, "profile_id": profile["id"],
                   "profile_revision": profile["revision"], "required_capabilities": ["generatesText"]}
        step = {"capability_id": "respond", "model_binding": binding}
        context = SimpleNamespace(user_id="user", invoke_prompt="original", gpt_model="old", model_context={}, planner_client="old", planner_deployment="old")
        with self.assertRaisesRegex(RuntimeError, "test failure"):
            with step_model_context(step, context, settings=settings, seeds={},
                                    resolve_model=lambda *_: model, invoke_factory=lambda _: "step-prompt"):
                self.assertEqual(context.invoke_prompt, "step-prompt")
                self.assertEqual(context.model_context["model_id"], "one")
                raise RuntimeError("test failure")
        self.assertEqual(context.invoke_prompt, "original")
        self.assertEqual(context.gpt_model, "old")
        model.close.assert_called_once()
        binding["profile_revision"] = "stale"
        with self.assertRaises(ModelCatalogError):
            validate_auto_bindings({"model_routing": "auto", "steps": [step]}, {}, settings, lambda *_: model)


if __name__ == "__main__":
    unittest.main()
