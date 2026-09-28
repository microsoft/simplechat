#!/usr/bin/env python3
# test_chat_image_reference_request.py
"""
Functional test for chat Image-mode reference request helpers.
Version: 0.261.144
Implemented in: 0.261.144

This test ensures direct Image-mode reference request parsing, validation, mask handling,
prompt composition, and compatibility thoughts work without Azure services.
"""

import base64
import io
import sys
import unittest
from pathlib import Path

from PIL import Image


TESTS_ROOT = Path(__file__).resolve().parent
APP_ROOT = TESTS_ROOT.parent / "application" / "single_app"
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(APP_ROOT))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_chat_image_references as chat_refs  # noqa: E402
from functions_image_references import ImageReferenceError  # noqa: E402


def png_bytes(width=16, height=12, color=(20, 80, 120)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def mask_data_url(width=16, height=12, *, empty=False):
    mask = Image.new("RGBA", (width, height), (0, 0, 0, 255))
    if not empty:
        for x in range(width // 2):
            for y in range(height):
                mask.putpixel((x, y), (0, 0, 0, 0))
    buffer = io.BytesIO()
    mask.save(buffer, format="PNG")
    encoded = base64.b64encode(buffer.getvalue()).decode("ascii")
    return f"data:image/png;base64,{encoded}"


def capability(limit=10, editing=True, enabled=True, masking=True, input_fidelity=False):
    return {
        "enabled": enabled,
        "editing": editing,
        "masking": masking,
        "max_reference_images": limit,
        "input_formats": ["image/png", "image/jpeg"],
        "input_fidelity": input_fidelity,
        "reason": "Reference editing is unavailable.",
    }


class FakeReaders:
    def __init__(self):
        self.messages = {
            "conv_image_1": {
                "id": "conv_image_1",
                "conversation_id": "conv",
                "role": "image",
                "file_name": "first.png",
                "image_bytes": png_bytes(),
            },
            "conv_image_2": {
                "id": "conv_image_2",
                "conversation_id": "conv",
                "role": "image",
                "file_name": "second.png",
                "image_bytes": png_bytes(8, 8),
            },
        }

    def message_reader(self, conversation_id, message_id):
        message = self.messages[message_id]
        return message, ""

    def document_reader(self, document_id, user_id, **kwargs):
        raise AssertionError("Document reader should not be used by this test")

    def image_loader(self, message_doc, complete_content):
        return "image/png", message_doc["image_bytes"]


class ChatImageReferenceRequestTests(unittest.TestCase):
    def setUp(self):
        self.fake = FakeReaders()

    def prepare(self, raw_references, image_mask=None, mask_regions=0, cap=None):
        return chat_refs.prepare_chat_image_references(
            {"enable_user_workspace": True},
            "user-1",
            "conv",
            raw_references,
            image_mask,
            mask_regions,
            capability=cap or capability(),
            message_reader=self.fake.message_reader,
            document_reader=self.fake.document_reader,
            image_loader=self.fake.image_loader,
        )

    def assert_reference_error(self, code, status, callback):
        with self.assertRaises(ImageReferenceError) as raised:
            callback()
        self.assertEqual((raised.exception.code, raised.exception.status_code), (code, status))
        return raised.exception

    def test_version_header_is_current(self):
        assert_app_version_at_least("0.261.144")

    def test_parse_errors_are_exposed(self):
        self.assert_reference_error(
            "invalid_image_references",
            400,
            lambda: self.prepare({"type": "message", "message_id": "conv_image_1"}),
        )

    def test_capability_disabled_or_zero_limit_is_unsupported(self):
        reference = [{"type": "message", "message_id": "conv_image_1"}]
        self.assert_reference_error(
            "unsupported_image_operation",
            400,
            lambda: self.prepare(reference, cap=capability(editing=False)),
        )
        self.assert_reference_error(
            "unsupported_image_operation",
            400,
            lambda: self.prepare(reference, cap=capability(limit=0)),
        )

    def test_too_many_references_is_rejected_before_resolve(self):
        references = [
            {"type": "message", "message_id": "conv_image_1"},
            {"type": "message", "message_id": "conv_image_2"},
        ]
        error = self.assert_reference_error(
            "too_many_reference_images",
            400,
            lambda: self.prepare(references, cap=capability(limit=1)),
        )
        self.assertIn("at most 1", error.public_message)

    def test_mask_with_multiple_references_is_rejected(self):
        references = [
            {"type": "message", "message_id": "conv_image_1"},
            {"type": "message", "message_id": "conv_image_2"},
        ]
        self.assert_reference_error(
            "unsupported_image_operation",
            400,
            lambda: self.prepare(references, image_mask=mask_data_url(), cap=capability(limit=2)),
        )

    def test_mask_without_masking_capability_is_rejected(self):
        reference = [{"type": "message", "message_id": "conv_image_1"}]
        self.assert_reference_error(
            "unsupported_image_operation",
            400,
            lambda: self.prepare(reference, image_mask=mask_data_url(), cap=capability(masking=False)),
        )

    def test_empty_mask_falls_back_to_whole_image_edit(self):
        result = self.prepare(
            [{"type": "message", "message_id": "conv_image_1"}],
            image_mask=mask_data_url(empty=True),
            mask_regions=2,
        )
        self.assertEqual(len(result["sources"]), 1)
        self.assertIsNone(result["mask"])
        self.assertIsNone(result["mask_metadata"])

    def test_mask_metadata_and_input_fidelity_are_returned(self):
        result = self.prepare(
            [{"type": "message", "message_id": "conv_image_1"}],
            image_mask=mask_data_url(),
            mask_regions=3,
            cap=capability(input_fidelity=True),
        )
        self.assertEqual(result["mask_metadata"]["regions"], 3)
        self.assertAlmostEqual(result["mask_metadata"]["coverage"], 0.5)
        self.assertEqual(result["input_fidelity"], "high")

    def test_prompt_composition_for_masked_and_unmasked_edits(self):
        masked = chat_refs.compose_chat_reference_prompt(
            "make this a cartoon",
            1,
            {"coverage": 0.5, "regions": 1, "covers_everything": False},
        )
        self.assertIn("Apply this change only within the transparent region", masked)
        self.assertIn("make this a cartoon", masked)
        one = chat_refs.compose_chat_reference_prompt("make this a cartoon", 1, None)
        many = chat_refs.compose_chat_reference_prompt("combine these", 3, None)
        self.assertTrue(one.startswith("Use the attached reference image"))
        self.assertIn("image 1 through image 3", many)

    def test_compatibility_thought_strings_and_pluralization(self):
        self.assertEqual(chat_refs.chat_reference_thoughts({"image_generation": True}), [])
        self.assertEqual(
            chat_refs.chat_reference_thoughts({
                "image_generation": True,
                "image_references": [{"type": "message", "message_id": "conv_image_1"}],
            }),
            ["Using 1 reference image"],
        )
        thoughts = chat_refs.chat_reference_thoughts({
            "image_generation": True,
            "image_references": [
                {"type": "message", "message_id": f"conv_image_{index}"}
                for index in range(12)
            ],
            "image_mask": "data:image/png;base64,abc",
            "image_mask_dropped": True,
        })
        self.assertEqual(thoughts[0], "Using 10 reference images")
        self.assertIn("Editing the selected region of the reference image", thoughts)
        self.assertIn("The original selection mask isn't saved, so this retry edits the whole image", thoughts)

    def test_request_field_parsing_rejects_bad_regions_and_non_string_mask(self):
        parsed = chat_refs.read_chat_image_reference_request({
            "image_references": [{"type": "message", "message_id": "conv_image_1"}],
            "image_mask": "data:image/png;base64,abc",
            "image_mask_regions": "1000",
            "image_mask_dropped": True,
        })
        self.assertEqual(parsed["mask_regions"], 999)
        self.assertTrue(parsed["image_mask_dropped"])
        self.assert_reference_error(
            "invalid_image_mask",
            400,
            lambda: chat_refs.read_chat_image_reference_request({"image_mask_regions": "many"}),
        )
        self.assert_reference_error(
            "invalid_image_mask",
            400,
            lambda: chat_refs.read_chat_image_reference_request({"image_mask": {"bad": True}}),
        )


if __name__ == "__main__":
    unittest.main()
