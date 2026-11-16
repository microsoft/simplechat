# test_image_provider_sdk_http.py
"""
Functional tests for provider-specific image request contracts.
Version: 0.261.107
Implemented in: 0.261.107

Use the existing OpenAI SDK and mocked HTTP to exercise JSON, Responses and
multipart encoding. No provider service, credential store or app startup is used.
"""

import base64
import json
import sys
import unittest
from pathlib import Path

import httpx
from openai import OpenAI


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Install the standalone test path before importing application leaf modules.
from functions_image_adapters import edit_image, generate_image  # noqa: E402
from functions_image_api_route import build_image_api_base_url, extract_responses_image_source  # noqa: E402
from functions_image_capabilities import resolve_image_model_capability  # noqa: E402


IMAGE_BASE64 = "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg=="
IMAGE_BYTES = base64.b64decode(IMAGE_BASE64)
SOURCE = {"bytes": IMAGE_BYTES, "file_name": "source.png", "mime_type": "image/png"}


class ImageProviderHttpTests(unittest.TestCase):
    def setUp(self):
        self.requests = []

    def client(self, base_url, **options):
        def respond(request):
            self.requests.append(request)
            body = {"data": [{"b64_json": IMAGE_BASE64}], "created": 1}
            if request.url.path.endswith("/responses"):
                body = {
                    "id": "resp_test", "object": "response", "created_at": 1,
                    "status": "completed", "model": "gpt-5.6-sol",
                    "output": [{
                        "id": "ig_test", "type": "image_generation_call",
                        "status": "completed", "result": IMAGE_BASE64,
                    }],
                }
            return httpx.Response(200, json=body)

        client = OpenAI(
            api_key="fixture-key", base_url=base_url, max_retries=0,
            http_client=httpx.Client(transport=httpx.MockTransport(respond), trust_env=False),
            **options,
        )
        self.addCleanup(client.close)
        return client

    @staticmethod
    def capability(model_name, direct=False):
        return resolve_image_model_capability(
            {"modelName": model_name},
            {
                "provider": "custom" if direct else "new_foundry",
                "api_type": "openai",
                "connection": {"endpoint": "https://api.openai.com/v1" if direct else "https://image.services.ai.azure.com"},
            },
        )

    def test_mai_generation_uses_its_own_path_and_dimensions(self):
        client = self.client("https://image.services.ai.azure.com/mai/v1/")
        response = generate_image(client, "mai-deployment", self.capability("MAI-Image-2.6"), "A poster", size="768x1024")
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/mai/v1/images/generations")
        self.assertEqual(json.loads(request.content), {
            "model": "mai-deployment", "prompt": "A poster", "width": 768, "height": 1024,
        })
        self.assertEqual(response["data"][0]["b64_json"], IMAGE_BASE64)

    def test_mai_edits_upload_bytes_as_multipart_not_a_local_path(self):
        client = self.client("https://image.services.ai.azure.com/mai/v1/")
        edit_image(client, "mai-deployment", self.capability("MAI-Image-2.5"), "Change the lighting", SOURCE)
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/mai/v1/images/edits")
        self.assertTrue(request.headers["content-type"].startswith("multipart/form-data; boundary="))
        for part in (b'name="model"', b"mai-deployment", b'name="prompt"', b'name="image"; filename="source.png"', IMAGE_BYTES):
            self.assertIn(part, request.content)
        for forbidden in (b'name="mask"', b'name="n"', b'name="size"', b'name="width"', b'name="background"'):
            self.assertNotIn(forbidden, request.content)

    def test_mai_invalid_masks_sizes_and_rendering_options_do_not_send_requests(self):
        client = self.client("https://image.services.ai.azure.com/mai/v1/")
        capability = self.capability("MAI-Image-2.6")
        for kwargs in ({"size": "1536x1024"}, {"quality": "high"}, {"background": "transparent"}):
            with self.subTest(kwargs=kwargs), self.assertRaises(ValueError):
                generate_image(client, "mai", capability, "Prompt", **kwargs)
        with self.assertRaises(ValueError):
            edit_image(client, "mai", capability, "Edit", SOURCE, mask={"bytes": IMAGE_BYTES})
        with self.assertRaises(ValueError):
            edit_image(client, "mai", capability, "Edit", SOURCE, size="1024x1024")
        self.assertEqual(self.requests, [])

    def test_flux_uses_explicit_foundry_paths_and_inline_reference_bytes(self):
        for name, path in (
            ("FLUX.2-pro", "flux-2-pro"),
            ("FLUX.2-flex", "flux-2-flex"),
            ("FLUX-1.1-pro", "flux-pro-1.1"),
        ):
            with self.subTest(model=name):
                client = self.client("https://resource.services.ai.azure.com/providers/blackforestlabs/v1/")
                capability = self.capability(name)
                generate_image(client, "image-deployment", capability, "A tree")
                request = self.requests[-1]
                self.assertEqual(request.url.path, f"/providers/blackforestlabs/v1/{path}")
                expected = {
                    "model": "image-deployment", "prompt": "A tree", "width": 1024, "height": 1024,
                    "output_format": "png",
                }
                if path == "flux-2-pro":
                    expected["num_images"] = 1
                elif path == "flux-pro-1.1":
                    expected["n"] = 1
                self.assertEqual(json.loads(request.content), expected)
                if capability["editing"]:
                    edit_image(client, "image-deployment", capability, "Autumn leaves", SOURCE)
                    edit_body = json.loads(self.requests[-1].content)
                    self.assertEqual(edit_body["input_image"], IMAGE_BASE64)
                    for field in ("width", "height", "n", "num_images"):
                        self.assertNotIn(field, edit_body)
                else:
                    count = len(self.requests)
                    with self.assertRaises(ValueError):
                        edit_image(client, "image-deployment", capability, "Edit", SOURCE)
                    self.assertEqual(len(self.requests), count)

    def test_kontext_uses_its_documented_images_compatibility_contract(self):
        client = self.client(
            "https://resource.services.ai.azure.com/openai/v1/",
            default_query={"api-version": "preview"},
        )
        capability = self.capability("FLUX.1-Kontext-pro")
        generate_image(client, "kontext-deployment", capability, "A fox")
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/openai/v1/images/generations")
        self.assertEqual(request.url.params["api-version"], "preview")
        self.assertEqual(json.loads(request.content), {
            "model": "kontext-deployment", "prompt": "A fox", "n": 1, "size": "1024x1024",
        })
        edit_image(client, "kontext-deployment", capability, "A sunset background", SOURCE)
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/openai/v1/images/edits")
        for part in (b'name="image"; filename="source.png"', IMAGE_BYTES, b'name="size"', b"1024x1024"):
            self.assertIn(part, request.content)
        self.assertNotIn(b'name="mask"', request.content)

    def test_direct_responses_edits_include_source_and_mask(self):
        client = self.client("https://api.openai.com/v1/")
        result = edit_image(
            client, "gpt-5.6-sol", self.capability("gpt-5.6-sol", direct=True),
            "Make the background blue", SOURCE, mask={"bytes": IMAGE_BYTES},
        )
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/v1/responses")
        body = json.loads(request.content)
        self.assertEqual(body["model"], "gpt-5.6-sol")
        self.assertEqual(body["input"][0]["content"][1], {
            "type": "input_image", "image_url": f"data:image/png;base64,{IMAGE_BASE64}",
        })
        self.assertEqual(body["tools"], [{
            "type": "image_generation", "action": "edit",
            "input_image_mask": {"image_url": f"data:image/png;base64,{IMAGE_BASE64}"},
        }])
        self.assertEqual(body["tool_choice"], {"type": "image_generation"})
        self.assertNotIn("api-version", request.url.params)
        self.assertNotIn("x-ms-oai-image-generation-deployment", request.headers)
        self.assertEqual(extract_responses_image_source(result), f"data:image/png;base64,{IMAGE_BASE64}")

    def test_direct_images_edit_uses_images_not_the_responses_tool(self):
        client = self.client("https://api.openai.com/v1/")
        edit_image(
            client, "gpt-image-2", self.capability("gpt-image-2", direct=True),
            "Edit the selected area", SOURCE, mask={"bytes": IMAGE_BYTES}, quality="high",
        )
        request = self.requests[-1]
        self.assertEqual(request.url.path, "/v1/images/edits")
        self.assertIn(IMAGE_BYTES, request.content)
        for part in (b'name="mask"', b'name="quality"', b"high", b"gpt-image-2"):
            self.assertIn(part, request.content)

    def test_provider_paths_preserve_gateways_and_normalize_known_project_suffixes(self):
        for route, suffix, version in (
            ("mai", "/mai/v1/", "v1"),
            ("flux", "/providers/blackforestlabs/v1/", "preview"),
        ):
            with self.subTest(route=route):
                self.assertEqual(
                    build_image_api_base_url("https://gateway.example/models/team/openai/v1", route, api_version=version),
                    f"https://gateway.example/models/team{suffix}",
                )
                self.assertEqual(
                    build_image_api_base_url("https://resource.services.ai.azure.com/api/projects/studio", route, api_version=version),
                    f"https://resource.services.ai.azure.com{suffix}",
                )
                self.assertEqual(
                    build_image_api_base_url("https://gateway.example/api/projects/studio", route, api_version=version),
                    f"https://gateway.example/api/projects/studio{suffix}",
                )


if __name__ == "__main__":
    unittest.main()
