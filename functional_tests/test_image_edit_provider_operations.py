# test_image_edit_provider_operations.py
"""
Functional tests for selected-provider image editing and explicit regeneration.
Version: 0.261.107
Implemented in: 0.261.107

Run the real binding, capability, generation and edit helpers with isolated
credentials, HTTP clients and persistence. No provider or database is contacted.
"""

import ast
import base64
import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from PIL import Image


sys.path.insert(0, str(Path(__file__).resolve().parent))

# The shared fixture installs application import seams before loading runtime modules.
from test_ai_connection_image_runtime import (  # noqa: E402
    IMAGE_BASE64,
    APP_ROOT,
    ImageRuntimeTestCase,
    connections,
    generation,
    image_edit,
    load_route_functions,
    shared_image_settings,
)


def settings_for(name, provider="new_foundry"):
    settings = shared_image_settings(direct=True, provider=provider)
    connection = settings["model_endpoints"][0]
    connection["models"][0]["modelName"] = name
    connection["connection"]["endpoint"] = (
        "https://images.openai.azure.com" if provider == "aoai"
        else "https://images.services.ai.azure.com"
    )
    return settings


def png(mode="RGBA", color=(0, 0, 0, 0)):
    buffer = io.BytesIO()
    Image.new(mode, (8, 8), color).save(buffer, format="PNG")
    return buffer.getvalue()


SOURCE = {
    "bytes": base64.b64decode(IMAGE_BASE64),
    "mime_type": "image/png",
    "file_name": "source.png",
    "width": 1,
    "height": 1,
}


class ImageEditProviderOperationTests(ImageRuntimeTestCase):
    def test_bootstrap_exposes_complete_safe_image_capabilities(self):
        namespace = {"resolve_image_edit_capability": image_edit.resolve_image_edit_capability}
        load_route_functions("route_backend_v2.py", ("_build_capabilities",), namespace)
        projection = namespace["_build_capabilities"](settings_for("MAI-Image-2.6"))["image_edit"]
        self.assertEqual(projection["mode"], "edit")
        self.assertTrue(projection["enabled"])
        self.assertTrue(projection["editing"])
        self.assertFalse(projection["masking"])
        self.assertEqual(projection["sizes"], ["1024x1024", "1024x768", "768x1024"])
        self.assertEqual(projection["qualities"], [])
        for private_field in ("endpoint", "auth", "api_key", "model_path", "transport"):
            self.assertNotIn(private_field, projection)
        self.assertNotIn("images.services.ai.azure.com", repr(projection))
        self.secret_helper.assert_not_called()

    def test_personal_and_shared_handlers_forward_operation_and_raw_mask(self):
        for filename, handler in (
            ("route_backend_chats.py", "add_message_image_revision_api"),
            ("route_backend_collaboration.py", "add_collaboration_image_revision_api"),
        ):
            tree = ast.parse(APP_ROOT.joinpath(filename).read_text(encoding="utf-8-sig"))
            function = next(node for node in ast.walk(tree) if isinstance(node, ast.FunctionDef) and node.name == handler)
            invocation = next(
                node for node in ast.walk(function)
                if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "revise_image_message"
            )
            keywords = {keyword.arg: keyword.value for keyword in invocation.keywords}
            data = {"operation": "regenerate", "mask": []}
            for name, expected in (("operation", "regenerate"), ("mask_data_url", [])):
                value = eval(compile(ast.Expression(keywords[name]), filename, "eval"), {"data": data})
                self.assertEqual(value, expected)

    def test_azure_gpt_chat_and_disabled_defaults_cannot_offer_regeneration(self):
        for settings in (
            shared_image_settings(),
            {**shared_image_settings(direct=True), "enable_image_generation": False},
            {**shared_image_settings(direct=True), connections.IMAGE_SELECTION_KEY: {}},
        ):
            with self.subTest(selection=settings.get(connections.IMAGE_SELECTION_KEY)):
                capability = image_edit.resolve_image_edit_capability(settings)
                self.assertFalse(capability["enabled"])
                self.assertEqual(capability["mode"], "unavailable")
                self.assertTrue(capability["reason"])
        self.secret_helper.assert_not_called()

    def test_mai_reference_edits_reach_the_mai_client_and_preserve_method(self):
        client, constructor = self.mock_client()
        client.post.return_value = {"data": [{"b64_json": IMAGE_BASE64}]}
        result = image_edit.request_image_edit(
            settings_for("MAI-Image-2.6"), SOURCE, "Make the scene brighter", operation="edit",
        )
        self.assertEqual(result["method"], "edit")
        self.assertEqual(result["mime_type"], "image/png")
        self.assertEqual(constructor.call_args.kwargs["base_url"], "https://images.services.ai.azure.com/mai/v1/")
        self.assertEqual(constructor.call_args.kwargs["image_auth_header"], "api-key")
        self.assertEqual(constructor.call_args.kwargs["default_query"], {})
        self.assertEqual(client.post.call_args.args, ("images/edits",))
        self.assertEqual(client.post.call_args.kwargs["files"]["image"][1], SOURCE["bytes"])
        client.images.generate.assert_not_called()
        client.responses.create.assert_not_called()
        client.close.assert_called_once()

    def test_kontext_uses_preview_images_with_key_authentication(self):
        client, constructor = self.mock_client()
        client.images.edit.return_value = {"data": [{"b64_json": IMAGE_BASE64}]}
        result = image_edit.request_image_edit(
            settings_for("FLUX.1-Kontext-pro"), SOURCE, "Change the sky", operation="edit",
        )
        self.assertEqual(result["method"], "edit")
        self.assertEqual(constructor.call_args.kwargs["base_url"], "https://images.services.ai.azure.com/openai/v1/")
        self.assertEqual(constructor.call_args.kwargs["default_query"], {"api-version": "preview"})
        self.assertEqual(constructor.call_args.kwargs["image_auth_header"], "api-key")
        self.assertEqual(client.images.edit.call_args.kwargs["size"], "1024x1024")
        client.post.assert_not_called()

    def test_native_flux_reference_edit_has_no_generation_dimensions(self):
        client, constructor = self.mock_client()
        client.post.return_value = {"data": [{"b64_json": IMAGE_BASE64}]}
        result = image_edit.request_image_edit(
            settings_for("FLUX.2-pro"), SOURCE, "Change the color", operation="edit",
        )
        self.assertEqual(result["method"], "edit")
        body = client.post.call_args.kwargs["body"]
        self.assertEqual(body["input_image"], IMAGE_BASE64)
        self.assertNotIn("width", body)
        self.assertNotIn("height", body)
        self.assertEqual(constructor.call_args.kwargs["image_auth_header"], "authorization")

    def test_masks_and_unsupported_operations_fail_without_credentials_or_inference(self):
        for name, operation, mask in (
            ("MAI-Image-2.6", "edit", {"bytes": png()}),
            ("FLUX.2-pro", "edit", {"bytes": png()}),
            ("FLUX-1.1-pro", "edit", None),
            ("gpt-image-2", "regenerate", {"bytes": png()}),
        ):
            with self.subTest(model=name):
                with self.assertRaises(image_edit.ImageEditError) as raised:
                    image_edit.request_image_edit(
                        settings_for(name), SOURCE, "Change this", mask=mask, operation=operation,
                    )
                self.assertEqual(raised.exception.code, "unsupported_image_operation")
                self.assertEqual(raised.exception.status_code, 400)
        self.secret_helper.assert_not_called()

    def test_explicit_regeneration_does_not_load_or_send_a_source_image(self):
        client, _constructor = self.mock_client()
        helpers = types.ModuleType("functions_message_image_revisions")
        helpers.ORIGIN_AI, helpers.ORIGIN_CONTROL, helpers.ORIGIN_PROMPT = "ai", "control", "prompt"
        helpers.validate_origin = lambda value: value
        helpers.current_image_prompt = lambda _message: "Original image prompt"
        helpers.normalize_prompt = lambda value: value.strip()
        helpers.assert_revision_expectations = Mock()
        helpers.apply_image_revision = Mock(return_value={"revisions": []})
        with (
            patch.dict(sys.modules, {"functions_message_image_revisions": helpers}),
            patch.object(image_edit, "load_current_image_bytes") as load_source,
            patch.object(image_edit, "store_revision_image", return_value={"id": "revision-one"}),
        ):
            result = image_edit.revise_image_message(
                settings_for("gpt-image-2", "aoai"), {"id": "image-message"},
                "owner", "conversation", instruction="Create a forest instead",
                operation="regenerate",
            )
        load_source.assert_not_called()
        client.images.edit.assert_not_called()
        client.images.generate.assert_called_once()
        self.assertEqual(result["method"], "regenerate")
        self.assertEqual(helpers.apply_image_revision.call_args.kwargs["method"], "regenerate")

    def test_generation_only_flux_regenerates_but_never_claims_an_edit(self):
        client, _constructor = self.mock_client()
        client.post.return_value = {"data": [{"b64_json": IMAGE_BASE64}]}
        result = image_edit.request_image_edit(
            settings_for("FLUX-1.1-pro"), None, "A different mountain", operation="regenerate",
        )
        self.assertEqual(result["method"], "regenerate")
        body = client.post.call_args.kwargs["body"]
        self.assertNotIn("input_image", body)
        self.assertEqual(body["n"], 1)

    def test_source_conversion_uses_actual_mime_and_provider_formats(self):
        source = image_edit.prepare_source_image("image/jpeg", png(), ["image/png", "image/jpeg"])
        self.assertEqual(source["mime_type"], "image/png")
        self.assertEqual(source["file_name"], "image.png")
        buffer = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(buffer, format="WEBP")
        converted = image_edit.prepare_source_image("image/webp", buffer.getvalue(), ["image/png", "image/jpeg"])
        self.assertEqual(converted["mime_type"], "image/png")
        self.assertTrue(converted["bytes"].startswith(b"\x89PNG"))

    def test_mask_requires_real_png_transparency_and_respects_application_limit(self):
        with self.assertRaises(image_edit.ImageEditError):
            image_edit.normalize_mask(base64.b64encode(png("RGB", "red")).decode(), 8, 8)
        encoded = base64.b64encode(png()).decode()
        normalized = image_edit.normalize_mask(encoded, 8, 8, regions=1)
        self.assertEqual(normalized["coverage"], 1.0)
        self.assertEqual(normalized["regions"], 1)
        with self.assertRaises(image_edit.ImageEditError):
            image_edit.normalize_mask(encoded, 8, 8, max_bytes=10)

    def test_provider_base64_must_contain_an_image_not_prose(self):
        client, _constructor = self.mock_client()
        client.images.generate.return_value = {"data": [{"b64_json": base64.b64encode(b"not an image").decode()}]}
        with self.assertRaises(generation.ImageGenerationError) as raised:
            generation.request_generated_image_source(settings_for("gpt-image-2", "aoai"), "Draw a tree")
        self.assertEqual(raised.exception.code, "image_output_invalid")
        client.images.generate.assert_called_once()
        client.responses.create.assert_not_called()
        client.close.assert_called_once()


if __name__ == "__main__":
    unittest.main()
