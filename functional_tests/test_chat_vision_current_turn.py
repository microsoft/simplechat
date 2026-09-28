#!/usr/bin/env python3
# test_chat_vision_current_turn.py
"""
Functional tests for current-turn chat vision.
Version: 0.261.144
Implemented in: 0.261.144

This test ensures current-turn chat images are collected, resolved, and attached only
for verified direct vision model paths without persisting or mutating chat history.
"""

import copy
import re
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


TESTS_ROOT = Path(__file__).resolve().parent
APP_ROOT = TESTS_ROOT.parent / "application" / "single_app"
sys.path.insert(0, str(TESTS_ROOT))
sys.path.insert(0, str(APP_ROOT))

from test_support.versioning import assert_app_version_at_least  # noqa: E402

import functions_chat_vision as chat_vision  # noqa: E402


def file_message(message_id, filename, *, upload=True, workspace_document_id=None, active=True):
    return {
        "id": message_id,
        "conversation_id": "conv",
        "role": "file",
        "filename": filename,
        "workspace_document_id": workspace_document_id or f"doc-{message_id}",
        "metadata": {
            "is_user_upload": upload,
            "thread_info": {"active_thread": active},
        },
    }


def image_message(message_id, filename, *, upload=True, active=True):
    return {
        "id": message_id,
        "conversation_id": "conv",
        "role": "image",
        "filename": filename,
        "metadata": {
            "is_user_upload": upload,
            "thread_info": {"active_thread": active},
        },
    }


class ChatVisionCurrentTurnTests(unittest.TestCase):
    def test_version_header_matches_feature_version(self):
        assert_app_version_at_least("0.261.144")

    def test_current_turn_window_retry_and_inactive_threads(self):
        messages = [
            file_message("old-file", "old.png"),
            {"id": "assistant-1", "role": "assistant", "content": "done", "metadata": {"thread_info": {"active_thread": True}}},
            file_message("active-file", "active.jpg"),
            file_message("inactive-file", "inactive.png", active=False),
            {"id": "retry-user", "role": "user", "content": "what is this?", "metadata": {"thread_info": {"active_thread": True}}},
            image_message("after-current", "later.png"),
        ]

        refs = chat_vision.collect_current_turn_image_references(messages, "retry-user")

        self.assertEqual(refs, [{"type": "message", "message_id": "active-file"}])

    def test_uploads_non_uploads_heic_and_dedupe(self):
        repeated = file_message("same-image", "same.png")
        messages = [
            {"id": "assistant-1", "role": "assistant", "content": "ready"},
            repeated,
            repeated,
            file_message("not-upload", "private.png", upload=False),
            file_message("heif", "photo.heic"),
            image_message("legacy-upload", "legacy.webp"),
            image_message("generated", "generated.png", upload=False),
            {"id": "user-1", "role": "user", "content": "describe"},
        ]

        refs = chat_vision.collect_current_turn_image_references(messages, "user-1")

        self.assertEqual(refs, [
            {"type": "message", "message_id": "same-image"},
            {"type": "message", "message_id": "legacy-upload"},
        ])

    def test_selected_image_documents_without_non_image_reads(self):
        messages = [{"id": "user-1", "role": "user", "content": "describe"}]
        selected_documents = [
            {"id": "spreadsheet", "file_name": "budget.xlsx", "scope": "personal"},
            {"id": "missing-name", "scope": "personal"},
            {"id": "heif-doc", "file_name": "scan.heif", "scope": "personal"},
            {"id": "personal-image", "file_name": "map.png", "scope": "personal", "scope_id": "ignored"},
            {"id": "group-image", "file_name": "floorplan.jpeg", "scope": "group", "group_id": "group-1"},
        ]

        refs = chat_vision.collect_current_turn_image_references(
            messages,
            "user-1",
            selected_documents=selected_documents,
        )

        self.assertEqual(refs, [
            {"type": "document", "document_id": "personal-image", "scope": "personal", "scope_id": None},
            {"type": "document", "document_id": "group-image", "scope": "group", "scope_id": "group-1"},
        ])

    def test_explicit_selection_filters_search_results_and_infers_scope(self):
        search_documents = [
            {"document_id": "matched-only", "file_name": "unrelated.png"},
            {"document_id": "group-map", "file_name": "map.png", "group_id": "group-1"},
            {"document_id": "group-map", "file_name": "map.png", "group_id": "group-1"},
            {"document_id": "public-photo", "file_name": "photo.jpg", "public_workspace_id": "public-1"},
            {"document_id": "personal-house", "file_name": "house.jpeg"},
        ]

        selected = chat_vision.explicitly_selected_documents(
            search_documents,
            ["group-map", "public-photo", "personal-house"],
        )
        refs = chat_vision.collect_current_turn_image_references(
            [{"id": "user-1", "role": "user", "content": "describe"}],
            "user-1",
            selected_documents=selected,
        )

        self.assertEqual(chat_vision.explicitly_selected_documents(search_documents, []), [])
        self.assertEqual(refs, [
            {"type": "document", "document_id": "group-map", "scope": "group", "scope_id": "group-1"},
            {"type": "document", "document_id": "public-photo", "scope": "public", "scope_id": "public-1"},
            {"type": "document", "document_id": "personal-house", "scope": "personal", "scope_id": None},
        ])

    def test_selected_upload_document_is_not_sent_twice(self):
        messages = [
            {"id": "assistant-1", "role": "assistant", "content": "ready"},
            file_message("upload-1", "house.png", workspace_document_id="doc-house"),
            {"id": "user-1", "role": "user", "content": "describe"},
        ]

        refs = chat_vision.collect_current_turn_image_references(
            messages,
            "user-1",
            selected_documents=[{"document_id": "doc-house", "file_name": "house.png"}],
        )

        self.assertEqual(refs, [{"type": "message", "message_id": "upload-1"}])

    def test_attach_images_never_sends_empty_text_block(self):
        image_parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc", "detail": "auto"}}]

        empty_text = chat_vision.attach_images_to_last_user_message(
            [{"role": "user", "content": "   "}],
            image_parts,
        )
        list_content = chat_vision.attach_images_to_last_user_message(
            [{"role": "user", "content": [{"type": "text", "text": "hello"}]}],
            image_parts,
        )

        self.assertEqual(empty_text[0]["content"], image_parts)
        self.assertEqual(list_content[0]["content"], [{"type": "text", "text": "hello"}, image_parts[0]])

    def test_max_four_cap(self):
        messages = [{"id": "assistant-1", "role": "assistant", "content": "ready"}]
        messages.extend(file_message(f"image-{index}", f"image-{index}.png") for index in range(5))
        messages.append({"id": "user-1", "role": "user", "content": "describe"})

        refs = chat_vision.collect_current_turn_image_references(messages, "user-1")

        self.assertEqual(len(refs), 4)
        self.assertEqual(refs[-1]["message_id"], "image-3")

    def test_build_parts_skips_failing_resolver_and_shapes_data_url(self):
        refs = [
            {"type": "message", "message_id": "ok-1"},
            {"type": "message", "message_id": "bad"},
            {"type": "message", "message_id": "ok-2"},
        ]

        def resolver(_settings, _user_id, _conversation_id, references, _capability):
            reference_id = references[0]["message_id"]
            if reference_id == "bad":
                raise RuntimeError("not ready")
            return {
                "sources": [{
                    "bytes": f"bytes-{reference_id}".encode("utf-8"),
                    "mime_type": "image/png",
                    "file_name": f"{reference_id}.png",
                }]
            }

        parts = chat_vision.build_vision_image_parts(
            {},
            "user",
            "conv",
            refs,
            resolver=resolver,
        )

        self.assertEqual(len(parts), 2)
        self.assertEqual(parts[0]["type"], "image_url")
        self.assertEqual(parts[0]["image_url"]["detail"], "auto")
        self.assertTrue(parts[0]["image_url"]["url"].startswith("data:image/png;base64,"))

    def test_skipped_images_do_not_fence_the_model_call(self):
        from flask import Flask, g

        from content_screening import access as screening_access
        from content_screening.contracts import DocumentHeldError

        def provenance_key(reference_id):
            return ("user-1", "personal", "user-1", reference_id)

        def resolver(_settings, user_id, _conversation_id, references, _capability):
            reference_id = references[0]["message_id"]
            document = {"id": reference_id, "user_id": user_id, "file_name": f"{reference_id}.png"}
            # The real screening reader records every document it reads and every hold it hits.
            screening_access._remember_document_use(document, user_id)
            if reference_id == "held":
                failure = DocumentHeldError()
                screening_access._remember_screening_failure(failure)
                raise failure
            size = 80 if reference_id == "too-big" else 10
            return {"sources": [{"bytes": b"x" * size, "mime_type": "image/png", "file_name": document["file_name"]}]}

        refs = [
            {"type": "message", "message_id": "ok-1"},
            {"type": "message", "message_id": "held"},
            {"type": "message", "message_id": "too-big"},
        ]
        rechecked = []
        app = Flask("vision-screening-state")
        with app.test_request_context("/api/chat"), \
                patch.object(chat_vision, "MAX_VISION_IMAGE_PAYLOAD_BYTES", 50), \
                patch.object(
                    screening_access,
                    "assert_document_available",
                    lambda source, **kwargs: rechecked.append(source["screening_provenance"]["document_id"]),
                ):
            parts = chat_vision.build_vision_image_parts({}, "user-1", "conv", refs, resolver=resolver)

            self.assertEqual(len(parts), 1)
            self.assertIsNone(getattr(g, "content_screening_error", None))
            self.assertEqual(list(g.content_screening_sources), [provenance_key("ok-1")])
            # The guard around the model call must not raise for the skipped images.
            screening_access.assert_current_request_sources_available("user-1")
        self.assertEqual(rechecked, ["ok-1"])

    def test_skipped_image_keeps_an_earlier_screening_failure(self):
        from flask import Flask, g

        from content_screening import access as screening_access
        from content_screening.contracts import DocumentHeldError

        earlier_failure = DocumentHeldError()

        def resolver(_settings, _user_id, _conversation_id, _references, _capability):
            screening_access._remember_screening_failure(DocumentHeldError())
            raise DocumentHeldError()

        app = Flask("vision-earlier-failure")
        with app.test_request_context("/api/chat"):
            g.content_screening_error = earlier_failure
            parts = chat_vision.build_vision_image_parts(
                {}, "user-1", "conv", [{"type": "message", "message_id": "held"}], resolver=resolver,
            )
            self.assertEqual(parts, [])
            self.assertIs(g.content_screening_error, earlier_failure)

    def test_attach_images_to_last_user_message_without_mutation(self):
        messages = [
            {"role": "user", "content": "earlier"},
            {"role": "assistant", "content": "ok"},
            {"role": "user", "content": "what is this?"},
        ]
        original = copy.deepcopy(messages)
        image_parts = [{"type": "image_url", "image_url": {"url": "data:image/png;base64,abc", "detail": "auto"}}]

        updated = chat_vision.attach_images_to_last_user_message(messages, image_parts)

        self.assertEqual(messages, original)
        self.assertEqual(updated[0], messages[0])
        self.assertEqual(updated[1], messages[1])
        self.assertEqual(updated[2]["content"][0], {"type": "text", "text": "what is this?"})
        self.assertEqual(updated[2]["content"][1], image_parts[0])

    def test_decision_function_conditions(self):
        with patch("functions_chat_vision.is_vision_capable_model", return_value=True):
            self.assertTrue(chat_vision.should_include_current_turn_images(
                image_generation_enabled=False,
                agent_active=False,
                orchestration_active=False,
                model="gpt-4o",
                endpoint="https://example.openai.azure.com",
                provider_kind="azure_openai",
            ))
            self.assertFalse(chat_vision.should_include_current_turn_images(
                image_generation_enabled=True,
                agent_active=False,
                orchestration_active=False,
                model="gpt-4o",
                endpoint="",
                provider_kind="azure_openai",
            ))
            self.assertFalse(chat_vision.should_include_current_turn_images(
                image_generation_enabled=False,
                agent_active=True,
                orchestration_active=False,
                model="gpt-4o",
                endpoint="",
                provider_kind="azure_openai",
            ))
            self.assertFalse(chat_vision.should_include_current_turn_images(
                image_generation_enabled=False,
                agent_active=False,
                orchestration_active=True,
                model="gpt-4o",
                endpoint="",
                provider_kind="azure_openai",
            ))
            self.assertFalse(chat_vision.should_include_current_turn_images(
                image_generation_enabled=False,
                agent_active=False,
                orchestration_active=False,
                model="gpt-4o",
                endpoint="",
                provider_kind="unknown_provider",
            ))
        with patch("functions_chat_vision.is_vision_capable_model", return_value=False):
            self.assertFalse(chat_vision.should_include_current_turn_images(
                image_generation_enabled=False,
                agent_active=False,
                orchestration_active=False,
                model="text-only",
                endpoint="",
                provider_kind="azure_openai",
            ))

    def test_thought_pluralization(self):
        self.assertEqual(chat_vision.vision_thought_text(1), "Including 1 image from this message")
        self.assertEqual(chat_vision.vision_thought_text(2), "Including 2 images from this message")

    def test_route_backend_chats_wires_both_direct_paths(self):
        route_source = (APP_ROOT / "route_backend_chats.py").read_text(encoding="utf-8")
        self.assertIn("from functions_chat_vision import (", route_source)
        self.assertGreaterEqual(route_source.count("should_include_current_turn_images("), 2)
        self.assertGreaterEqual(route_source.count("collect_current_turn_image_references("), 2)
        self.assertGreaterEqual(route_source.count("build_vision_image_parts("), 2)
        self.assertGreaterEqual(route_source.count("attach_images_to_last_user_message("), 2)
        guarded_calls = re.findall(
            r"should_include_current_turn_images\(\s*image_generation_enabled=image_gen_enabled,\s*"
            r"agent_active=.*?model=.*?provider_kind=.*?\)",
            route_source,
            flags=re.DOTALL,
        )
        self.assertGreaterEqual(len(guarded_calls), 2)
        self.assertIn("vision_thought_text(len(current_turn_image_parts))", route_source)
        self.assertGreaterEqual(route_source.count("selected_documents=explicitly_selected_documents("), 2)
        self.assertNotIn("include_current_turn_images = False", route_source)


if __name__ == "__main__":
    unittest.main()
