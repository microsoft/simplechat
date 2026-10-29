# test_group_document_filename_xss.py
"""
Regression guards for group document filename rendering.
Version: 0.261.029
Implemented in: 0.261.029

These guards cover Share launcher wiring and card tooltip boundaries.
Behavioral coverage lives in ui_tests/test_group_document_filename_xss_rendering.py.
"""

from pathlib import Path
import re
import unittest

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
TEMPLATE = ROOT / "application" / "single_app" / "templates" / "group_workspaces.html"


class GroupDocumentFilenameRenderingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.source = TEMPLATE.read_text(encoding="utf-8")

    def test_share_launchers_do_not_compile_document_data_as_javascript(self):
        handlers = re.findall(r'\bonclick="([^"]*)"', self.source)
        share_handlers = [handler for handler in handlers if "shareGroupDocument(" in handler]
        self.assertEqual(share_handlers, [], "Share must use a DOM event listener.")
        self.assertEqual(
            self.source.count('class="dropdown-item group-document-share-btn"'),
            3,
            "Cards, ordinary rows, and folder rows must use inert Share controls.",
        )

    def test_share_binding_covers_cards_rows_and_folder_insertion(self):
        for binding in (
            "window.bindGroupDocumentShareButton(column, doc)",
            "window.bindGroupDocumentShareButton(docRow, doc)",
            "window.bindGroupDocumentShareButton(row, docs[index])",
        ):
            with self.subTest(binding=binding):
                self.assertIn(binding, self.source)

    def test_card_titles_are_not_interpolated_into_html_attributes(self):
        unsafe_attributes = re.findall(
            r'title="\$\{[^}\n]*\b(?:displayTitle|subtitle)\b[^}\n]*\}"',
            self.source,
        )
        self.assertEqual(unsafe_attributes, [], "Card tooltips must use DOM properties.")

    def test_implementation_version_is_present(self):
        assert_app_version_at_least("0.261.029")


if __name__ == "__main__":
    unittest.main()
