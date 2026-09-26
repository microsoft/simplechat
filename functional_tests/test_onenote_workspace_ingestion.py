# test_onenote_workspace_ingestion.py
"""
Functional tests for page-aware OneNote workspace ingestion.
Version: 0.261.142
Implemented in: 0.261.142 (ported from 0.261.045)

Runs the repository processor and existing splitting helpers with scoped Azure
I/O substitutes. Native parsing and the process boundary have separate coverage.
"""

import importlib.util
import logging
import sys
import unittest
from pathlib import Path
from unittest.mock import patch


TEST_ROOT = Path(__file__).resolve().parent
APP_ROOT = TEST_ROOT.parent / "application" / "single_app"


def load_test_helper(name):
    spec = importlib.util.spec_from_file_location(name, TEST_ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    with patch.object(sys, "path", [str(TEST_ROOT), str(APP_ROOT), *sys.path]):
        with patch.dict(sys.modules):
            spec.loader.exec_module(module)
    return module


runtime_tests = load_test_helper("test_onenote_extractor_runtime")
chunk_tests = load_test_helper("test_markdown_chunk_size_enforcement")
onenote = runtime_tests.onenote


def page(text, section=("Notes",), title="Page", level=1, page_id="page-1"):
    return onenote.OneNotePage(tuple(section), page_id, title, level, text)


def extraction(pages):
    return onenote.OneNoteExtraction(
        len({item.section_path for item in pages}),
        tuple(pages),
        {"images": 0, "ink": 0, "attachments": 0, "empty_pages": sum(not item.text.strip() for item in pages)},
    )


class OneNoteIngestionTests(unittest.TestCase):
    def setUp(self):
        self.saved_batches = []
        self.updates = []
        self.uploads = []
        self.logs = []
        self.settings = {"max_file_size_mb": 50, "enable_extract_meta_data": False}
        self.result = extraction([page("Typed notes and table values.")])
        self.words = 400
        self.characters = 2000
        self.namespace = chunk_tests.build_content_namespace()
        self.namespace.update({
            "logging": logging,
            "ONENOTE_MAX_CHUNKS": onenote.ONENOTE_MAX_CHUNKS,
            "OneNoteExtractionError": onenote.OneNoteExtractionError,
            "extract_onenote": lambda source, maximum, **kwargs: self.result,
            "get_settings": lambda: self.settings,
            "get_chunk_size_config": lambda settings: {"txt": {"value": self.words, "unit": "words"}},
            "get_embedding_safe_chunk_characters": lambda settings: self.characters,
            "save_chunks_batch": self.save_batch,
            "upload_to_blob": lambda **kwargs: self.uploads.append(kwargs),
            "_run_final_metadata_extraction": lambda *args, **kwargs: "disabled",
            "log_event": lambda *args, **kwargs: self.logs.append((args, kwargs)),
        })
        chunk_tests.load_functions(APP_ROOT / "functions_documents.py", ["process_onenote"], self.namespace)

    def save_batch(self, chunks, user_id, document_id, **scope):
        self.saved_batches.append((chunks, user_id, document_id, scope))
        return {"total_tokens": 7, "model_deployment_name": "fixture-embedding"}

    def run_processor(self, enhanced=False, **scope):
        return self.namespace["process_onenote"](
            document_id="fixture-document",
            user_id="fixture-user",
            temp_file_path="local-fixture.onepkg",
            original_filename="fixture.onepkg",
            enable_enhanced_citations=enhanced,
            update_callback=lambda **kwargs: self.updates.append(kwargs),
            auto_extract_metadata=False,
            **scope,
        )

    def saved_chunks(self):
        return [chunk for batch, _, _, _ in self.saved_batches for chunk in batch]

    def test_one_parent_document_and_unique_chunk_numbers(self):
        self.result = extraction([
            page("First section body.", ("Planning",), "Overview"),
            page("Second section body.", ("Reference", "Notes"), "Overview", page_id="page-2"),
        ])
        saved_count, tokens, model = self.run_processor()
        chunks = self.saved_chunks()
        self.assertEqual([item["page_number"] for item in chunks], [1, 2])
        self.assertEqual(saved_count, 2)
        self.assertEqual(tokens, 7)
        self.assertEqual(model, "fixture-embedding")
        self.assertIn("Section: Planning", chunks[0]["page_text_content"])
        self.assertIn("Section: Reference / Notes", chunks[1]["page_text_content"])
        self.assertTrue(all(batch[2] == "fixture-document" for batch in self.saved_batches))

    def test_word_and_character_limits_include_context_headers(self):
        tokens = [f"token{index}" for index in range(200)]
        self.result = extraction([page("\n".join(tokens))])
        self.words = 25
        self.characters = 130
        self.run_processor()
        chunks = self.saved_chunks()
        combined = "\n".join(chunk["page_text_content"] for chunk in chunks)
        self.assertGreater(len(chunks), 1)
        for chunk in chunks:
            self.assertLessEqual(len(chunk["page_text_content"]), self.characters)
            self.assertLessEqual(len(chunk["page_text_content"].split()), self.words)
            self.assertIn("Section: Notes\nPage: Page\nSource page: 1\n", chunk["page_text_content"])
        for token in tokens:
            self.assertIn(token, combined)

    def test_long_unbroken_text_is_not_truncated(self):
        body = "x" * 5000
        self.result = extraction([page(body)])
        self.characters = 140
        self.run_processor()
        chunks = self.saved_chunks()
        body_parts = [chunk["page_text_content"].split("\n\n", 1)[1] for chunk in chunks]
        self.assertEqual("".join(body_parts), body)
        self.assertTrue(all(len(chunk["page_text_content"]) <= 140 for chunk in chunks))

    def test_subpages_keep_parent_titles_and_siblings_reset_them(self):
        self.result = extraction([
            page("", title="Parent"),
            page("Child content.", title="Child", level=2, page_id="page-2"),
            page("Sibling content.", title="Sibling", page_id="page-3"),
        ])
        self.run_processor()
        chunks = self.saved_chunks()
        self.assertIn("Page: Parent / Child", chunks[0]["page_text_content"])
        self.assertIn("Source page: 2", chunks[0]["page_text_content"])
        self.assertIn("Page: Sibling\n", chunks[1]["page_text_content"])
        self.assertNotIn("Parent / Sibling", chunks[1]["page_text_content"])
        self.assertEqual(self.updates[1]["onenote_source_page_count"], 3)
        self.assertEqual(self.updates[1]["number_of_pages"], 2)

    def test_personal_group_and_public_scopes_are_preserved(self):
        for scope in ({}, {"group_id": "group-1"}, {"public_workspace_id": "public-1"}):
            with self.subTest(scope=scope):
                self.saved_batches.clear()
                self.uploads.clear()
                self.run_processor(enhanced=True, **scope)
                self.assertEqual(self.saved_batches[0][1:3], ("fixture-user", "fixture-document"))
                self.assertEqual(self.saved_batches[0][3], scope)
                self.assertEqual({key: self.uploads[0][key] for key in scope}, scope)
                self.assertEqual(self.uploads[0]["blob_filename"], "fixture.onepkg")

    def test_extraction_failure_never_writes_chunks_or_source_blob(self):
        def fail(source, maximum, **kwargs):
            raise onenote.OneNoteExtractionError("incomplete_notebook")

        self.namespace["extract_onenote"] = fail
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            self.run_processor(enhanced=True)
        self.assertEqual(caught.exception.code, "incomplete_notebook")
        self.assertEqual(self.saved_batches, [])
        self.assertEqual(self.uploads, [])

    def test_oversized_header_fails_before_writes(self):
        self.characters = 10
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            self.run_processor(enhanced=True)
        self.assertEqual(caught.exception.code, "limit_exceeded")
        self.assertEqual(self.saved_batches, [])
        self.assertEqual(self.uploads, [])

    def test_chunk_count_limit_fails_before_any_partial_indexing(self):
        self.result = extraction([page("text", page_id=f"page-{index}") for index in range(3)])
        self.namespace["ONENOTE_MAX_CHUNKS"] = 2
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            self.run_processor(enhanced=True)
        self.assertEqual(caught.exception.code, "limit_exceeded")
        self.assertEqual(self.saved_batches, [])
        self.assertEqual(self.uploads, [])

    def test_no_typed_content_is_not_success(self):
        self.result = extraction([page(" \n", title="Image only")])
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            self.run_processor()
        self.assertEqual(caught.exception.code, "no_text")
        self.assertEqual(self.saved_batches, [])

    def test_batched_indexing_preserves_counts_and_token_usage(self):
        self.result = extraction([page(f"Body {index}", page_id=f"page-{index}") for index in range(65)])
        result = self.run_processor()
        self.assertEqual([len(batch[0]) for batch in self.saved_batches], [32, 32, 1])
        self.assertEqual(result, (65, 21, "fixture-embedding"))
        self.assertEqual(self.updates[-1]["num_chunks"], 65)
        self.assertEqual(self.uploads, [])

    def test_provider_error_never_enters_public_status(self):
        def fail(*args, **kwargs):
            raise RuntimeError("private-provider-endpoint-and-credentials")

        self.namespace["save_chunks_batch"] = fail
        with self.assertRaises(onenote.OneNoteExtractionError) as caught:
            self.run_processor()
        self.assertEqual(caught.exception.code, "indexing_failed")
        self.assertNotIn("private-provider", str(caught.exception))
        self.assertNotIn("private-provider", str(self.logs))


if __name__ == "__main__":
    unittest.main()
