#!/usr/bin/env python3
# test_chat_image_upload_preview_route.py
"""
Functional test for chat image upload preview routes.
Version: 0.261.144
Implemented in: 0.261.144

This test ensures chat image preview variants and workspace image preview routing
serve browser-safe image bytes without leaking unauthorized workspace documents.
"""

import ast
import base64
import io
import os
import socket
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

from flask import Flask, Response, jsonify, redirect, request, stream_with_context
from PIL import Image
import werkzeug

ROOT_DIR = Path(__file__).resolve().parents[1]
APP_DIR = ROOT_DIR / "application" / "single_app"
sys.path.insert(0, str(APP_DIR))
sys.path.insert(0, str(ROOT_DIR / "functional_tests"))

from functions_image_formats import ImageFormatError, PREVIEW_VARIANTS, is_image_file_name, to_browser_image  # noqa: E402
from test_support.versioning import assert_app_version_at_least  # noqa: E402
from werkzeug.utils import secure_filename  # noqa: E402

if not hasattr(werkzeug, "__version__"):
    werkzeug.__version__ = "local-test"


class FakeScreeningError(Exception):
    """Screening hold used by the isolated route harness."""

    def __init__(self, public_message="Document is under review.", code="document_under_review", status_code=409):
        super().__init__(public_message)
        self.public_message = public_message
        self.code = code
        self.status_code = status_code


class FakeCosmosNotFound(Exception):
    """Cosmos not-found stand-in used by the isolated route harness."""


def load_definitions(filename, names, namespace):
    """Load selected function definitions from a route file without importing Azure config."""
    tree = ast.parse((APP_DIR / filename).read_text(encoding="utf-8"), filename=filename)
    selected = []
    wanted = set(names)

    def visit(node):
        if isinstance(node, ast.FunctionDef):
            if node.name in wanted:
                node.decorator_list = []
                selected.append(node)
            for child in node.body:
                visit(child)

    for child in tree.body:
        visit(child)

    found = {node.name for node in selected}
    missing = wanted - found
    assert not missing, f"Missing definitions in {filename}: {sorted(missing)}"
    selected.sort(key=lambda item: item.lineno)
    exec(compile(ast.Module(body=selected, type_ignores=[]), filename, "exec"), namespace)


def make_image_bytes(fmt="JPEG", size=(1200, 800), color=(20, 120, 200)):
    """Create small in-memory test images."""
    mode = "RGB"
    image = Image.new(mode, size, color)
    buffer = io.BytesIO()
    image.save(buffer, format=fmt)
    return buffer.getvalue()


def heic_bytes():
    """Return a minimal ISO-BMFF header recognized as HEIC by the format helper."""
    return b"\x00\x00\x00\x18ftypheic\x00\x00\x00\x00heicmif1"


def data_url(image_bytes, mime_type="image/png"):
    return f"data:{mime_type};base64,{base64.b64encode(image_bytes).decode('ascii')}"


class ChatImagePreviewRouteTests(unittest.TestCase):
    """Preview route regressions for chat-owned and workspace-backed images."""

    def setUp(self):
        assert_app_version_at_least("0.261.144")
        self._socket = socket.socket
        socket.socket = self._blocked_socket

    def tearDown(self):
        socket.socket = self._socket

    @staticmethod
    def _blocked_socket(*_args, **_kwargs):
        raise AssertionError("Network access is blocked in this functional test.")

    def build_chat_client(self, *, message, content="", document=None, content_bytes=None, screening_error=None):
        state = {"delegated": [], "reads": []}

        def build_available_document_response(document_id, user_id=None, purpose="preview"):
            state["delegated"].append((document_id, user_id, purpose))
            return Response(b"delegated", mimetype="application/octet-stream", headers={"X-Delegated": "1"})

        def read_available_document_bytes(document_id, **kwargs):
            state["reads"].append((document_id, kwargs))
            if screening_error:
                raise screening_error
            return document or {"id": document_id, "file_name": "image.jpg"}, content_bytes or make_image_bytes()

        def get_complete_image_content(_container, conversation_id, image_id):
            self.assertEqual(conversation_id, "conversation")
            self.assertEqual(image_id, "conversation_image_1_abcd")
            return dict(message), content

        namespace = {
            "Response": Response,
            "jsonify": jsonify,
            "request": request,
            "redirect": redirect,
            "stream_with_context": stream_with_context,
            "logging": __import__("logging"),
            "secure_filename": secure_filename,
            "build_available_document_response": build_available_document_response,
            "read_available_document_bytes": read_available_document_bytes,
            "get_current_user_id": lambda: "user-1",
            "get_complete_image_content": get_complete_image_content,
            "_authorize_image_conversation_read": lambda user_id, conversation_id: ({"id": conversation_id}, "personal"),
            "resolve_served_revision": lambda _message, _rev: None,
            "is_blob_backed_image_message": lambda _message: False,
            "is_external_image_url": lambda value: str(value or "").startswith("https://images.example/"),
            "decode_image_content": lambda value: (
                str(value).split(";", 1)[0].replace("data:", ""),
                base64.b64decode(str(value).split(",", 1)[1]),
            ),
            "load_image_bytes_from_blob": lambda _container, _path: content_bytes or make_image_bytes(),
            "ImageFormatError": ImageFormatError,
            "PREVIEW_VARIANTS": PREVIEW_VARIANTS,
            "is_image_file_name": is_image_file_name,
            "to_browser_image": to_browser_image,
            "ScreeningError": FakeScreeningError,
            "PermissionError": PermissionError,
            "CosmosResourceNotFoundError": FakeCosmosNotFound,
            "LookupError": LookupError,
            "log_event": lambda *_args, **_kwargs: None,
            "debug_print": lambda *_args, **_kwargs: None,
            "cosmos_messages_container": object(),
        }
        load_definitions(
            "route_backend_conversations.py",
            {"api_get_image"},
            namespace,
        )
        app = Flask("chat-image-preview")
        app.add_url_rule("/api/image/<image_id>", view_func=namespace["api_get_image"])
        return SimpleNamespace(client=app.test_client(), state=state)

    def build_workspace_client(self, *, settings=None, read_result=None, read_error=None):
        state = {"reads": [], "personal_reader": object()}

        def read_available_document_bytes(document_id, **kwargs):
            state["reads"].append((document_id, kwargs))
            if read_error:
                raise read_error
            return read_result or ({"id": document_id, "file_name": "photo.jpg"}, make_image_bytes())

        namespace = {
            "Response": Response,
            "jsonify": jsonify,
            "request": request,
            "secure_filename": secure_filename,
            "logging": __import__("logging"),
            "get_current_user_id": lambda: "user-1",
            "get_settings": lambda: settings or {
                "enable_user_workspace": True,
                "enable_group_workspaces": True,
                "enable_public_workspaces": True,
            },
            "read_available_document_bytes": read_available_document_bytes,
            "personal_document_metadata_reader": state["personal_reader"],
            "ImageFormatError": ImageFormatError,
            "PREVIEW_VARIANTS": PREVIEW_VARIANTS,
            "is_image_file_name": is_image_file_name,
            "to_browser_image": to_browser_image,
            "ScreeningError": FakeScreeningError,
            "PermissionError": PermissionError,
            "LookupError": LookupError,
            "CosmosResourceNotFoundError": FakeCosmosNotFound,
            "log_event": lambda *_args, **_kwargs: None,
        }
        load_definitions(
            "route_enhanced_citations.py",
            {"preview_workspace_document_image"},
            namespace,
        )
        app = Flask("workspace-image-preview")
        app.add_url_rule(
            "/api/workspace_documents/image_preview",
            view_func=namespace["preview_workspace_document_image"],
        )
        return SimpleNamespace(client=app.test_client(), state=state)

    def test_no_variant_workspace_path_delegates_unchanged(self):
        runtime = self.build_chat_client(
            message={"id": "conversation_image_1_abcd", "workspace_document_id": "doc-1"},
        )
        response = runtime.client.get("/api/image/conversation_image_1_abcd")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, b"delegated")
        self.assertEqual(runtime.state["delegated"], [("doc-1", "user-1", "image_preview")])
        self.assertEqual(runtime.state["reads"], [])

    def test_workspace_jpeg_thumbnail_headers_and_bounds(self):
        jpeg = make_image_bytes("JPEG", size=(1600, 1200))
        runtime = self.build_chat_client(
            message={"id": "conversation_image_1_abcd", "workspace_document_id": "doc-1"},
            document={"id": "doc-1", "file_name": "camera.jpg"},
            content_bytes=jpeg,
        )
        response = runtime.client.get("/api/image/conversation_image_1_abcd?variant=thumbnail")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/jpeg")
        self.assertEqual(response.headers["Cache-Control"], "no-store, private")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertTrue(response.headers["Content-Disposition"].startswith('inline; filename="camera.jpg"'))
        with Image.open(io.BytesIO(response.data)) as preview:
            self.assertLessEqual(max(preview.size), 1024)

    def test_workspace_tiff_display_converts_to_png(self):
        tiff = make_image_bytes("TIFF", size=(80, 60))
        runtime = self.build_chat_client(
            message={"id": "conversation_image_1_abcd", "workspace_document_id": "doc-1"},
            document={"id": "doc-1", "file_name": "scan.tiff"},
            content_bytes=tiff,
        )
        response = runtime.client.get("/api/image/conversation_image_1_abcd?variant=display")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/png")
        self.assertIn('filename="scan.png"', response.headers["Content-Disposition"])

    def test_workspace_heic_display_passthrough(self):
        runtime = self.build_chat_client(
            message={"id": "conversation_image_1_abcd", "workspace_document_id": "doc-1"},
            document={"id": "doc-1", "file_name": "phone.heic"},
            content_bytes=heic_bytes(),
        )
        response = runtime.client.get("/api/image/conversation_image_1_abcd?variant=display")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.mimetype, "image/heic")
        self.assertEqual(response.data, heic_bytes())

    def test_workspace_non_image_document_is_refused(self):
        runtime = self.build_chat_client(
            message={"id": "conversation_image_1_abcd", "workspace_document_id": "doc-1"},
            document={"id": "doc-1", "file_name": "notes.txt"},
            content_bytes=b"not image",
        )
        response = runtime.client.get("/api/image/conversation_image_1_abcd?variant=thumbnail")
        self.assertEqual(response.status_code, 415)
        self.assertEqual(response.get_json()["error_code"], "not_an_image")

    def test_invalid_variant_is_rejected(self):
        runtime = self.build_chat_client(message={"id": "conversation_image_1_abcd"})
        response = runtime.client.get("/api/image/conversation_image_1_abcd?variant=giant")
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error_code"], "invalid_preview_variant")

    def test_held_workspace_document_uses_screening_status(self):
        runtime = self.build_chat_client(
            message={"id": "conversation_image_1_abcd", "workspace_document_id": "doc-1"},
            screening_error=FakeScreeningError(),
        )
        response = runtime.client.get("/api/image/conversation_image_1_abcd?variant=thumbnail")
        self.assertEqual(response.status_code, 409)
        self.assertEqual(response.get_json()["error_code"], "document_under_review")

    def test_role_image_data_url_thumbnail(self):
        png = make_image_bytes("PNG", size=(1400, 900))
        runtime = self.build_chat_client(
            message={"id": "conversation_image_1_abcd", "role": "image", "filename": "upload.png"},
            content=data_url(png, "image/png"),
        )
        response = runtime.client.get("/api/image/conversation_image_1_abcd?variant=thumbnail")
        self.assertEqual(response.status_code, 200)
        self.assertIn(response.mimetype, {"image/jpeg", "image/png"})
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertEqual(response.headers["Cache-Control"], "private, max-age=3600")
        with Image.open(io.BytesIO(response.data)) as preview:
            self.assertLessEqual(max(preview.size), 1024)

    def test_workspace_preview_feature_flag_disabled(self):
        runtime = self.build_workspace_client(settings={
            "enable_user_workspace": False,
            "enable_group_workspaces": True,
            "enable_public_workspaces": True,
        })
        response = runtime.client.get("/api/workspace_documents/image_preview?doc_id=doc-1")
        self.assertEqual(response.status_code, 403)
        self.assertEqual(runtime.state["reads"], [])

    def test_workspace_preview_group_scope_passes_group_id(self):
        runtime = self.build_workspace_client()
        response = runtime.client.get(
            "/api/workspace_documents/image_preview?doc_id=doc-1&scope=group&scope_id=group-1&variant=thumbnail"
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(runtime.state["reads"][0][1]["group_id"], "group-1")
        self.assertEqual(runtime.state["reads"][0][1]["purpose"], "image_preview")
        self.assertNotIn("metadata_reader", runtime.state["reads"][0][1])

    def test_workspace_preview_personal_scope_reads_only_personal_documents(self):
        runtime = self.build_workspace_client()
        response = runtime.client.get("/api/workspace_documents/image_preview?doc_id=doc-1&variant=thumbnail")
        self.assertEqual(response.status_code, 200)
        read_kwargs = runtime.state["reads"][0][1]
        self.assertIs(read_kwargs["metadata_reader"], runtime.state["personal_reader"])
        self.assertNotIn("group_id", read_kwargs)
        self.assertNotIn("public_workspace_id", read_kwargs)

    def test_workspace_preview_personal_scope_refuses_group_and_public_documents(self):
        # scope=personal must not serve a document from a group or public workspace whose flag is off.
        disabled = {
            "enable_user_workspace": True,
            "enable_group_workspaces": False,
            "enable_public_workspaces": False,
        }
        for owner in ({"group_id": "group-1"}, {"public_workspace_id": "public-1"}):
            with self.subTest(owner=owner):
                runtime = self.build_workspace_client(
                    settings=disabled,
                    read_result=({"id": "doc-1", "file_name": "photo.jpg", **owner}, make_image_bytes()),
                )
                response = runtime.client.get("/api/workspace_documents/image_preview?doc_id=doc-1&scope=personal")
                self.assertEqual(response.status_code, 404)
                self.assertNotIn("image", response.mimetype)

    def test_workspace_preview_missing_doc_id(self):
        runtime = self.build_workspace_client()
        response = runtime.client.get("/api/workspace_documents/image_preview")
        self.assertEqual(response.status_code, 400)

    def test_workspace_preview_unauthorized_is_generic_404(self):
        runtime = self.build_workspace_client(read_error=PermissionError("private"))
        response = runtime.client.get("/api/workspace_documents/image_preview?doc_id=doc-1")
        self.assertEqual(response.status_code, 404)
        self.assertNotIn("private", response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main(verbosity=2)
