#!/usr/bin/env python3
# test_image_reference_resolver.py
"""
Functional tests for image reference resolver.
Version: 0.261.192
Implemented in: 0.261.192

This test ensures chat image references are parsed, authorized, screened, normalized, and
converted into provenance without importing application configuration or using Azure services.
"""

import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


TESTS_ROOT = Path(__file__).resolve().parent
APP_ROOT = TESTS_ROOT.parent / "application" / "single_app"
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(APP_ROOT))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_image_references as refs  # noqa: E402
from content_screening import access as screening_access  # noqa: E402,F401  (loaded before sys.modules patches)
from content_screening.contracts import DocumentHeldError  # noqa: E402


def png_bytes(width=16, height=12, color=(20, 40, 80)):
    buffer = io.BytesIO()
    Image.new("RGB", (width, height), color).save(buffer, format="PNG")
    return buffer.getvalue()


def heic_bytes():
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00mif1heic" + (b"\x00" * 32)


def capability(limit=10, editing=True, enabled=True):
    return {
        "enabled": enabled,
        "editing": editing,
        "max_reference_images": limit,
        "input_formats": ["image/png", "image/jpeg"],
        "reason": "Reference editing is unavailable.",
    }


def settings(**overrides):
    base = {
        "enable_user_workspace": True,
        "enable_group_workspaces": True,
        "enable_public_workspaces": True,
    }
    base.update(overrides)
    return base


class FakeReaders:
    def __init__(self):
        self.messages = {}
        self.documents = {}
        self.document_calls = []
        self.image_calls = []

    def message_reader(self, conversation_id, message_id):
        message = self.messages[message_id]
        return message, message.get("content", "")

    def document_reader(self, document_id, user_id, **kwargs):
        self.document_calls.append((document_id, user_id, dict(kwargs)))
        value = self.documents[document_id]
        if isinstance(value, BaseException):
            raise value
        return value

    def image_loader(self, message_doc, complete_content):
        self.image_calls.append((message_doc["id"], complete_content))
        payload = message_doc.get("image_bytes") or png_bytes()
        return "image/png", payload


class ImageReferenceParsingTests(unittest.TestCase):
    def test_version_header_is_current(self):
        assert_app_version_at_least("0.261.192")

    def test_parse_valid_mixed_list_dedupes_and_normalizes(self):
        parsed = refs.parse_image_references([
            {"type": "message", "message_id": " conv_image_123_abc "},
            {"type": "message", "message_id": "conv_image_123_abc"},
            {"type": "document", "document_id": "550e8400-e29b-41d4-a716-446655440000", "scope": "personal", "scope_id": "ignored"},
            {"type": "document", "document_id": "doc:2", "scope": "group", "scope_id": "group-1"},
            {"type": "document", "document_id": "doc.3", "scope": "public", "scope_id": "public_1"},
        ])
        self.assertEqual(parsed, [
            {"type": "message", "message_id": "conv_image_123_abc"},
            {
                "type": "document",
                "document_id": "550e8400-e29b-41d4-a716-446655440000",
                "scope": "personal",
                "scope_id": None,
            },
            {"type": "document", "document_id": "doc:2", "scope": "group", "scope_id": "group-1"},
            {"type": "document", "document_id": "doc.3", "scope": "public", "scope_id": "public_1"},
        ])

    def test_parse_rejects_invalid_shapes_and_limits(self):
        cases = [
            ("non-list", {"type": "message"}, "invalid_image_references", 400),
            ("bad-type", [{"type": "url", "url": "https://example.test/a.png"}], "invalid_image_references", 400),
            ("bad-id", [{"type": "message", "message_id": "bad id!"}], "invalid_image_references", 400),
            ("missing-scope", [{"type": "document", "document_id": "doc-1", "scope": "group"}], "invalid_image_references", 400),
            (
                "too-many",
                [{"type": "message", "message_id": f"conv_image_{index}"} for index in range(3)],
                "too_many_reference_images",
                400,
            ),
        ]
        for name, raw, code, status in cases:
            with self.subTest(name=name):
                with self.assertRaises(refs.ImageReferenceError) as raised:
                    refs.parse_image_references(raw, max_count=2)
                self.assertEqual((raised.exception.code, raised.exception.status_code), (code, status))

    def test_effective_max_reference_images(self):
        self.assertEqual(refs.effective_max_reference_images(capability(limit=12)), 10)
        self.assertEqual(refs.effective_max_reference_images(capability(limit=2)), 2)
        self.assertEqual(refs.effective_max_reference_images(capability(limit=5, editing=False)), 0)
        self.assertEqual(refs.effective_max_reference_images({"editing": True}), 0)


class ImageReferenceResolverTests(unittest.TestCase):
    def resolve(self, fake, references, cap=None, app_settings=None):
        return refs.resolve_image_references(
            settings() if app_settings is None else app_settings,
            "user-1",
            "conv",
            references,
            capability() if cap is None else cap,
            message_reader=fake.message_reader,
            document_reader=fake.document_reader,
            image_loader=fake.image_loader,
        )

    def assert_reference_error(self, code, status, callback):
        with self.assertRaises(refs.ImageReferenceError) as raised:
            callback()
        self.assertEqual((raised.exception.code, raised.exception.status_code), (code, status))
        return raised.exception

    def test_unsupported_capability_and_over_model_limit(self):
        fake = FakeReaders()
        ref = [{"type": "message", "message_id": "conv_image_1"}]
        self.assert_reference_error(
            "unsupported_image_operation",
            400,
            lambda: self.resolve(fake, ref, cap=capability(editing=False)),
        )
        fake.messages["conv_image_1"] = {
            "id": "conv_image_1",
            "conversation_id": "conv",
            "role": "image",
            "image_bytes": png_bytes(),
        }
        fake.messages["conv_image_2"] = {
            "id": "conv_image_2",
            "conversation_id": "conv",
            "role": "image",
            "image_bytes": png_bytes(),
        }
        error = self.assert_reference_error(
            "too_many_reference_images",
            400,
            lambda: self.resolve(
                fake,
                [{"type": "message", "message_id": "conv_image_1"}, {"type": "message", "message_id": "conv_image_2"}],
                cap=capability(limit=1),
            ),
        )
        self.assertIn("at most 1", error.public_message)

    def test_message_reference_conversation_defense(self):
        fake = FakeReaders()
        self.assert_reference_error(
            "image_reference_not_found",
            404,
            lambda: self.resolve(fake, [{"type": "message", "message_id": "other_image_1"}]),
        )
        fake.messages["conv_image_1"] = {
            "id": "conv_image_1",
            "conversation_id": "other",
            "role": "image",
            "image_bytes": png_bytes(),
        }
        self.assert_reference_error(
            "image_reference_not_found",
            404,
            lambda: self.resolve(fake, [{"type": "message", "message_id": "conv_image_1"}]),
        )

    def test_role_image_reference_resolves_and_sanitizes_provenance(self):
        fake = FakeReaders()
        fake.messages["conv_image_1"] = {
            "id": "conv_image_1",
            "conversation_id": "conv",
            "role": "image",
            "file_name": "..\\nested\\portrait.png",
            "image_bytes": png_bytes(20, 10),
        }
        result = self.resolve(fake, [{"type": "message", "message_id": "conv_image_1"}])
        self.assertEqual(len(result["sources"]), 1)
        self.assertEqual(fake.image_calls, [("conv_image_1", "")])
        provenance = result["provenance"][0]
        self.assertEqual(provenance["file_name"], "portrait.png")
        self.assertEqual((provenance["width"], provenance["height"]), (20, 10))
        self.assertNotIn("bytes", provenance)
        self.assertNotIn("blob_path", provenance)

    def test_role_file_image_uses_workspace_document_with_model_purpose(self):
        fake = FakeReaders()
        fake.messages["conv_file_1"] = {
            "id": "conv_file_1",
            "conversation_id": "conv",
            "role": "file",
            "file_name": "upload.png",
            "workspace_document_id": "doc-1",
        }
        fake.documents["doc-1"] = ({"id": "doc-1", "file_name": "upload.png"}, png_bytes(9, 7))
        result = self.resolve(fake, [{"type": "message", "message_id": "conv_file_1"}])
        self.assertEqual(result["provenance"][0]["message_id"], "conv_file_1")
        self.assertEqual(fake.document_calls, [("doc-1", "user-1", {"purpose": "model"})])
        self.assertEqual((result["provenance"][0]["width"], result["provenance"][0]["height"]), (9, 7))

    def test_role_file_pdf_is_rejected(self):
        fake = FakeReaders()
        fake.messages["conv_file_1"] = {
            "id": "conv_file_1",
            "conversation_id": "conv",
            "role": "file",
            "file_name": "report.pdf",
            "workspace_document_id": "doc-1",
        }
        fake.documents["doc-1"] = ({"id": "doc-1", "file_name": "report.pdf"}, b"%PDF-1.7")
        self.assert_reference_error(
            "unsupported_reference_format",
            415,
            lambda: self.resolve(fake, [{"type": "message", "message_id": "conv_file_1"}]),
        )

    def test_heic_document_and_screening_errors_are_mapped(self):
        fake = FakeReaders()
        fake.documents["heic-doc"] = ({"id": "heic-doc", "file_name": "photo.heic"}, heic_bytes())
        heic_error = self.assert_reference_error(
            "unsupported_reference_format",
            415,
            lambda: self.resolve(
                fake,
                [{"type": "document", "document_id": "heic-doc", "scope": "personal", "scope_id": None}],
            ),
        )
        self.assertIn("JPG or PNG", heic_error.public_message)

        fake.documents["held-doc"] = DocumentHeldError()
        held_error = self.assert_reference_error(
            "document_under_review",
            409,
            lambda: self.resolve(
                fake,
                [{"type": "document", "document_id": "held-doc", "scope": "personal", "scope_id": None}],
            ),
        )
        self.assertEqual(held_error.public_message, DocumentHeldError.public_message)

    def test_permission_error_and_disabled_scope_are_not_found(self):
        fake = FakeReaders()
        fake.documents["secret-doc"] = PermissionError("no")
        self.assert_reference_error(
            "image_reference_not_found",
            404,
            lambda: self.resolve(
                fake,
                [{"type": "document", "document_id": "secret-doc", "scope": "personal", "scope_id": None}],
            ),
        )
        self.assert_reference_error(
            "image_reference_not_found",
            404,
            lambda: self.resolve(
                fake,
                [{"type": "document", "document_id": "doc-1", "scope": "group", "scope_id": "group-1"}],
                app_settings=settings(enable_group_workspaces=False),
            ),
        )

    def test_group_and_public_scope_are_passed_to_document_reader(self):
        fake = FakeReaders()
        fake.documents["group-doc"] = ({"id": "group-doc", "file_name": "group.png"}, png_bytes())
        fake.documents["public-doc"] = ({"id": "public-doc", "file_name": "public.jpg"}, png_bytes())
        result = self.resolve(fake, [
            {"type": "document", "document_id": "group-doc", "scope": "group", "scope_id": "group-1"},
            {"type": "document", "document_id": "public-doc", "scope": "public", "scope_id": "public-1"},
        ])
        self.assertEqual([item["document_id"] for item in result["provenance"]], ["group-doc", "public-doc"])
        self.assertEqual(fake.document_calls[0], ("group-doc", "user-1", {"purpose": "model", "group_id": "group-1"}))
        self.assertEqual(
            fake.document_calls[1],
            ("public-doc", "user-1", {"purpose": "model", "public_workspace_id": "public-1"}),
        )

    def test_personal_scope_reads_only_personal_documents(self):
        fake = FakeReaders()
        fake.documents["doc-1"] = ({"id": "doc-1", "user_id": "user-1", "file_name": "house.png"}, png_bytes())
        self.resolve(fake, [{"type": "document", "document_id": "doc-1", "scope": "personal", "scope_id": None}])
        self.assertEqual(fake.document_calls, [("doc-1", "user-1", {"purpose": "model", "personal_only": True})])

    def test_personal_scope_cannot_reach_group_or_public_documents(self):
        # A personal reference must not bypass disabled group or public workspaces.
        fake = FakeReaders()
        fake.documents["group-doc"] = (
            {"id": "group-doc", "group_id": "group-1", "file_name": "group.png"},
            png_bytes(),
        )
        fake.documents["public-doc"] = (
            {"id": "public-doc", "public_workspace_id": "public-1", "file_name": "public.png"},
            png_bytes(),
        )
        for document_id in ("group-doc", "public-doc"):
            with self.subTest(document_id=document_id):
                self.assert_reference_error(
                    "image_reference_not_found",
                    404,
                    lambda: self.resolve(
                        fake,
                        [{"type": "document", "document_id": document_id, "scope": "personal", "scope_id": None}],
                        app_settings=settings(enable_group_workspaces=False, enable_public_workspaces=False),
                    ),
                )

    def test_default_document_reader_scopes_personal_reads(self):
        calls = []

        def read_available_document_bytes(document_id, user_id, **kwargs):
            calls.append((document_id, user_id, kwargs))
            return {"id": document_id}, b""

        fake_access = type(sys)("content_screening.access")
        fake_access.read_available_document_bytes = read_available_document_bytes
        with patch.dict(sys.modules, {"content_screening.access": fake_access}):
            refs._default_document_reader("doc-1", "user-1", personal_only=True)
            refs._default_document_reader("doc-2", "user-1", group_id="group-1")
            refs._default_document_reader("doc-3", "user-1")

        self.assertIs(calls[0][2]["metadata_reader"], refs.personal_document_metadata_reader)
        self.assertIsNone(calls[1][2]["metadata_reader"])
        self.assertEqual(calls[1][2]["group_id"], "group-1")
        # Message-linked uploads may live in a group workspace, so they stay unscoped.
        self.assertIsNone(calls[2][2]["metadata_reader"])

    def test_personal_metadata_reader_never_searches_group_or_public_containers(self):
        class FakeContainer:
            def __init__(self, documents):
                self.documents = documents
                self.reads = []

            def read_item(self, item, partition_key):
                self.reads.append(item)
                if item not in self.documents:
                    error = Exception("missing")
                    error.status_code = 404
                    raise error
                return dict(self.documents[item])

        user_container = FakeContainer({"personal-doc": {"id": "personal-doc", "user_id": "user-1"}})
        group_container = FakeContainer({"group-doc": {"id": "group-doc", "group_id": "group-1"}})
        public_container = FakeContainer({"public-doc": {"id": "public-doc", "public_workspace_id": "public-1"}})
        fake_config = type(sys)("config")
        fake_config.cosmos_user_documents_container = user_container
        fake_config.cosmos_group_documents_container = group_container
        fake_config.cosmos_public_documents_container = public_container

        with patch.dict(sys.modules, {"config": fake_config}):
            document = refs.personal_document_metadata_reader(document_id="personal-doc", user_id="user-1")
            for document_id in ("group-doc", "public-doc"):
                with self.subTest(document_id=document_id):
                    with self.assertRaises(LookupError):
                        refs.personal_document_metadata_reader(document_id=document_id, user_id="user-1")

        self.assertEqual(document["id"], "personal-doc")
        self.assertEqual(user_container.reads, ["personal-doc", "group-doc", "public-doc"])
        self.assertEqual(group_container.reads, [])
        self.assertEqual(public_container.reads, [])

    def test_order_preserved_and_references_round_trip_from_metadata(self):
        fake = FakeReaders()
        fake.messages["conv_image_1"] = {
            "id": "conv_image_1",
            "conversation_id": "conv",
            "role": "image",
            "file_name": "first.png",
            "image_bytes": png_bytes(4, 4),
        }
        fake.documents["doc-2"] = ({"id": "doc-2", "file_name": "second.png"}, png_bytes(5, 5))
        requested = [
            {"type": "message", "message_id": "conv_image_1"},
            {"type": "document", "document_id": "doc-2", "scope": "personal", "scope_id": None},
        ]
        result = self.resolve(fake, requested)
        self.assertEqual(
            [(item["type"], item.get("message_id") or item.get("document_id")) for item in result["provenance"]],
            [("message", "conv_image_1"), ("document", "doc-2")],
        )
        self.assertEqual(refs.references_from_metadata({"image_references": result["provenance"]}), requested)
        self.assertEqual(refs.references_from_metadata({"image_references": [{"type": "bad"}]}), [])

    def test_payload_budget_retries_smaller_edges_then_fails(self):
        fake = FakeReaders()
        fake.messages["conv_image_1"] = {
            "id": "conv_image_1",
            "conversation_id": "conv",
            "role": "image",
            "image_bytes": png_bytes(),
        }
        calls = []

        def fake_normalize(image_bytes, allowed_formats=None, max_edge=0, file_stem="reference"):
            calls.append(max_edge)
            return {
                "bytes": b"x" * 9,
                "mime_type": "image/png",
                "file_name": f"{file_stem}.png",
                "width": max_edge,
                "height": max_edge,
            }

        with patch.object(refs, "MAX_REFERENCE_PAYLOAD_BYTES", 8), patch.object(refs, "normalize_model_image", fake_normalize):
            self.assert_reference_error(
                "image_too_large",
                413,
                lambda: self.resolve(fake, [{"type": "message", "message_id": "conv_image_1"}]),
            )
        self.assertEqual(calls, [refs.MODEL_IMAGE_MAX_EDGE, 1536, 1024])

    def test_payload_budget_retry_can_succeed(self):
        fake = FakeReaders()
        fake.messages["conv_image_1"] = {
            "id": "conv_image_1",
            "conversation_id": "conv",
            "role": "image",
            "image_bytes": png_bytes(),
        }

        def fake_normalize(image_bytes, allowed_formats=None, max_edge=0, file_stem="reference"):
            size = 12 if max_edge == refs.MODEL_IMAGE_MAX_EDGE else 7
            return {
                "bytes": b"x" * size,
                "mime_type": "image/png",
                "file_name": f"{file_stem}.png",
                "width": max_edge,
                "height": max_edge,
            }

        with patch.object(refs, "MAX_REFERENCE_PAYLOAD_BYTES", 8), patch.object(refs, "normalize_model_image", fake_normalize):
            result = self.resolve(fake, [{"type": "message", "message_id": "conv_image_1"}])
        self.assertEqual(len(result["sources"][0]["bytes"]), 7)
        self.assertEqual(result["provenance"][0]["width"], 1536)


class ImageReferencePromptAndImportTests(unittest.TestCase):
    def test_reference_prompt_outputs(self):
        self.assertEqual(refs.reference_prompt("  make it blue\nnow ", 0), "make it blue now")
        self.assertEqual(
            refs.reference_prompt("make it blue", 1),
            "Use the attached reference image as the visual basis. make it blue",
        )
        self.assertEqual(
            refs.reference_prompt("make it blue", 3),
            "Use the 3 attached reference images, numbered image 1 through image 3 in the order given, as visual references. make it blue",
        )

    def test_module_imports_without_application_configuration(self):
        probe = (
            "import sys; sys.path.insert(0, sys.argv[1]); import functions_image_references; "
            "leaked = sorted(name for name in ('config', 'flask', 'functions_settings') if name in sys.modules); "
            "print(leaked); sys.exit(1 if leaked else 0)"
        )
        completed = subprocess.run(
            [sys.executable, "-c", probe, str(APP_ROOT)],
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(completed.returncode, 0, completed.stdout + completed.stderr)


if __name__ == "__main__":
    unittest.main()
