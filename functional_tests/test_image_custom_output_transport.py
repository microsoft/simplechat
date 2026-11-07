# test_image_custom_output_transport.py
"""
Functional tests for the derived image URL boundary on Custom connections.
Version: 0.261.107
Implemented in: 0.261.107

Exercise the real image downloader with mock HTTP behind the same guarded-client
factory seam. Inference credentials and client certificates must not reach outputs.
"""

import io
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

import httpx
from PIL import Image


TEST_ROOT = Path(__file__).resolve().parent
APP_ROOT = TEST_ROOT.parent / "application" / "single_app"
sys.path.insert(0, str(TEST_ROOT))
sys.path.insert(0, str(APP_ROOT))

# Runtime imports use the repository's existing service-isolation seam.
from test_support.app_stubs import import_app_module  # noqa: E402
import functions_image_edit as image_edit  # noqa: E402


generation = import_app_module("functions_image_generation")


def custom_settings():
    return {
        "enable_image_generation": True,
        "image_generation_model_selection": {
            "endpoint_id": "custom-images", "model_id": "image", "provider": "custom",
        },
        "model_endpoints": [{
            "id": "custom-images", "provider": "custom", "api_type": "openai",
            "connection": {
                "endpoint": "https://api.openai.com/v1",
                "client_cert_path": "must-not-use-this-for-output.pem",
                "client_key_path": "must-not-use-this-for-output-key.pem",
            },
            "auth": {"type": "api_key", "api_key": "model-only-fixture-key"},
            "models": [{"id": "image", "modelName": "gpt-image-2", "enabled": True}],
        }],
    }


class CustomImageOutputTransportTests(unittest.TestCase):
    def setUp(self):
        output = io.BytesIO()
        Image.new("RGB", (8, 8), "blue").save(output, format="PNG")
        self.png = output.getvalue()
        self.requests = []
        self.status = 200
        self.headers = {}
        module = types.ModuleType("model_endpoint_clients")

        def respond(request):
            self.requests.append(request)
            return httpx.Response(self.status, content=self.png, headers=self.headers)

        def build_client(**_kwargs):
            return httpx.Client(
                transport=httpx.MockTransport(respond), follow_redirects=False, trust_env=False,
            )

        self.factory = Mock(side_effect=build_client)
        module.build_custom_openai_sync_http_client = self.factory
        patcher = patch.dict(sys.modules, {"model_endpoint_clients": module})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_output_download_is_guarded_and_never_carries_model_authentication(self):
        settings = custom_settings()
        with patch.object(generation.requests, "get") as legacy_get:
            mime_type, content = generation.resolve_generated_image_bytes(
                "https://output.example.test/image.png?sig=fixture-signature", settings=settings,
            )
        self.assertEqual(mime_type, "image/png")
        self.assertEqual(content, self.png)
        legacy_get.assert_not_called()
        self.assertEqual(len(self.requests), 1)
        for header in ("authorization", "api-key", "cookie", "x-simplechat-identity-key"):
            self.assertNotIn(header, self.requests[0].headers)
        self.assertNotIn("model-only-fixture-key", str(self.requests[0].headers))
        self.assertEqual(self.factory.call_args.kwargs, {
            "allow_private": False, "allow_insecure": False, "ca_bundle_path": "", "client_cert": None,
        })

    def test_flags_use_the_shared_parser_not_truthiness_of_false_strings(self):
        settings = custom_settings()
        settings.update(
            allow_private_custom_model_endpoints="false",
            allow_insecure_custom_model_endpoints="false",
        )
        generation.resolve_generated_image_bytes("https://output.example.test/image.png", settings=settings)
        self.assertFalse(self.factory.call_args.kwargs["allow_private"])
        self.assertFalse(self.factory.call_args.kwargs["allow_insecure"])

    def test_redirect_does_not_fetch_the_second_origin(self):
        self.status = 302
        self.headers["Location"] = "http://169.254.169.254/metadata/identity"
        with self.assertRaises(generation.ImageGenerationError) as raised:
            generation.resolve_generated_image_bytes(
                "https://output.example.test/image.png", settings=custom_settings(),
            )
        self.assertEqual(raised.exception.code, "image_download_failed")
        self.assertEqual(len(self.requests), 1)
        self.assertNotIn("169.254", str(raised.exception))

    def test_download_is_bounded_before_decoding_pixels(self):
        with patch.object(image_edit, "MAX_SOURCE_IMAGE_BYTES", 32):
            with self.assertRaises(generation.ImageGenerationError) as raised:
                generation.resolve_generated_image_bytes(
                    "https://output.example.test/image.png", settings=custom_settings(),
                )
        self.assertEqual(raised.exception.code, "image_output_invalid")

    def test_provider_url_cannot_supply_http_basic_credentials(self):
        with self.assertRaises(generation.ImageGenerationError):
            generation.resolve_generated_image_bytes(
                "https://user:password@output.example.test/image.png", settings=custom_settings(),
            )
        self.factory.assert_not_called()
        self.assertEqual(self.requests, [])


if __name__ == "__main__":
    unittest.main()
