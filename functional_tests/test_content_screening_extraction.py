# test_content_screening_extraction.py
"""
Functional tests for private canonical extraction.
Version: 0.261.106
Implemented in: 0.261.106

Checks page identity, complete native CSV coverage, explicit extraction failure,
and lossless publication splitting without live Azure dependencies.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

# Import the independent extraction package without bootstrapping the application.
from content_screening.contracts import ContentUnit, ScreeningError, Subject
from content_screening.extraction import (
    ExtractionCapture,
    capture_extraction,
    capture_table_source,
    capture_text_before_chunking,
    current_extraction,
    publication_chunks,
)


class ScreeningExtractionTests(unittest.TestCase):
    def capture(self):
        return ExtractionCapture(Subject("personal", "owner", "document", "1"), "scan", "file.txt")

    def test_capture_is_scoped_and_reset(self):
        capture = self.capture()
        with capture_extraction(capture):
            self.assertIs(current_extraction("document"), capture)
            self.assertIsNone(current_extraction("another-document"))
            capture_text_before_chunking("Full original text")
            capture.add_chunk("Full original", 1)
            capture.add_chunk("original text", 2)
            capture.completed = True
        self.assertIsNone(current_extraction())
        self.assertEqual([unit.text for unit in capture.finish({})], ["Full original text"])

    def test_real_pages_are_not_replaced_by_synthetic_chunk_numbers(self):
        capture = self.capture()
        capture.add_pages([{"page_number": 1, "content": "First page"}])
        capture.add_pages([{"page_number": 1, "content": "Second source file part"}])
        capture.add_chunk("A synthetic chunk", 900)
        capture.completed = True
        units = capture.finish({})
        self.assertEqual([unit.locator["page_number"] for unit in units], [1, 2])

    def test_incomplete_or_empty_extraction_is_not_success(self):
        capture = self.capture()
        capture.add_chunk("partial content", 1)
        with self.assertRaises(ScreeningError):
            capture.finish({})
        capture.completed = True
        capture.failure_code = "source_failed"
        with self.assertRaises(ScreeningError):
            capture.finish({})

    def test_csv_inspects_last_cell_not_only_schema(self):
        capture = self.capture()
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "table.csv"
            source.write_text("name,value\nfirst,ordinary\nlast,private-canary\n", encoding="utf-8")
            capture_table_source(capture, source)
        capture.add_chunk("A schema summary without row values", 1)
        capture.completed = True
        units = capture.finish({})
        canary = [unit for unit in units if unit.text == "private-canary"]
        self.assertEqual(len(canary), 1)
        self.assertEqual(canary[0].locator["row"], 3)
        self.assertEqual(canary[0].locator["column"], 2)
        self.assertFalse(any("schema summary" in unit.text for unit in units))

    def test_publication_retains_tail_and_page_mapping(self):
        chunks = publication_chunks([ContentUnit("one", "abcdefghijk", {"page_number": 7})], 4)
        self.assertEqual("".join(chunk["chunk_text"] for chunk in chunks), "abcdefghijk")
        self.assertEqual([chunk["chunk_sequence"] for chunk in chunks], [1, 2, 3])
        self.assertTrue(all(chunk["page_number"] == 7 for chunk in chunks))

    def test_metadata_is_inspected_but_not_published_as_a_body_chunk(self):
        capture = self.capture()
        capture.add_chunk("body", 1)
        capture.completed = True
        units = capture.finish({"abstract": "sensitive summary"})
        self.assertTrue(any(unit.text == "sensitive summary" for unit in units))
        self.assertEqual([chunk["chunk_text"] for chunk in publication_chunks(units, 100)], ["body"])

    def test_content_budget_never_returns_a_partial_clean_capture(self):
        capture = self.capture()
        capture.max_characters = 3
        with self.assertRaises(ScreeningError):
            capture.add_text("longer")


if __name__ == "__main__":
    unittest.main()
