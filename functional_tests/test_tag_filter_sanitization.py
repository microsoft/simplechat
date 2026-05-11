# test_tag_filter_sanitization.py
#!/usr/bin/env python3
"""
Functional test for tag filter sanitization.
Version: 0.238.025
Implemented in: 0.238.025

This test ensures that sanitize_tags_for_filter() properly validates and
sanitizes tag inputs for filter/query operations, preventing SQL and OData
injection attacks while allowing valid tags through.
"""

import sys
import os
sys.path.append(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'application', 'single_app'))


def test_sanitize_tags_for_filter():
    """Test the sanitize_tags_for_filter function."""
    print("Testing sanitize_tags_for_filter()...")

    from functions_documents import sanitize_tags_for_filter

    try:
        # --- Valid inputs ---
        # Basic valid tags (comma-separated string)
        result = sanitize_tags_for_filter("valid-tag,another_tag")
        assert result == ["valid-tag", "another_tag"], f"Expected ['valid-tag', 'another_tag'], got {result}"
        print("  PASS: Basic valid tags (comma-separated string)")

        # Basic valid tags (list)
        result = sanitize_tags_for_filter(["valid-tag", "another_tag"])
        assert result == ["valid-tag", "another_tag"], f"Expected ['valid-tag', 'another_tag'], got {result}"
        print("  PASS: Basic valid tags (list)")

        # Uppercase normalization
        result = sanitize_tags_for_filter("MyTag,UPPER")
        assert result == ["mytag", "upper"], f"Expected ['mytag', 'upper'], got {result}"
        print("  PASS: Uppercase normalization")

        # Whitespace trimming
        result = sanitize_tags_for_filter("  spaced  , padded  ")
        assert result == ["spaced", "padded"], f"Expected ['spaced', 'padded'], got {result}"
        print("  PASS: Whitespace trimming")

        # --- Invalid inputs filtered out ---
        # Special characters dropped
        result = sanitize_tags_for_filter("good,b@d,fine")
        assert result == ["good", "fine"], f"Expected ['good', 'fine'], got {result}"
        print("  PASS: Special characters dropped")

        # SQL injection attempt
        result = sanitize_tags_for_filter("'; DROP TABLE--")
        assert result == [], f"Expected [], got {result}"
        print("  PASS: SQL injection attempt blocked")

        # OData injection attempt
        result = sanitize_tags_for_filter("x) or true or (t eq 'y")
        assert result == [], f"Expected [], got {result}"
        print("  PASS: OData injection attempt blocked")

        # Tags with spaces (list input)
        result = sanitize_tags_for_filter(["tag1", "tag with spaces"])
        assert result == ["tag1"], f"Expected ['tag1'], got {result}"
        print("  PASS: Tags with spaces dropped (list input)")

        # Tags with quotes
        result = sanitize_tags_for_filter(["good", "it's", 'say"hello'])
        assert result == ["good"], f"Expected ['good'], got {result}"
        print("  PASS: Tags with quotes dropped")

        # Tags with parentheses
        result = sanitize_tags_for_filter(["valid", "bad(tag)", "also)bad"])
        assert result == ["valid"], f"Expected ['valid'], got {result}"
        print("  PASS: Tags with parentheses dropped")

        # --- Edge cases ---
        # Empty string
        result = sanitize_tags_for_filter("")
        assert result == [], f"Expected [], got {result}"
        print("  PASS: Empty string returns []")

        # Empty list
        result = sanitize_tags_for_filter([])
        assert result == [], f"Expected [], got {result}"
        print("  PASS: Empty list returns []")

        # None
        result = sanitize_tags_for_filter(None)
        assert result == [], f"Expected [], got {result}"
        print("  PASS: None returns []")

        # Non-string type
        result = sanitize_tags_for_filter(12345)
        assert result == [], f"Expected [], got {result}"
        print("  PASS: Non-string/list type returns []")

        # Length limit (51 chars)
        long_tag = "a" * 51
        result = sanitize_tags_for_filter(long_tag)
        assert result == [], f"Expected [], got {result}"
        print("  PASS: 51-char tag dropped")

        # Length limit (exactly 50 chars - should pass)
        tag_50 = "a" * 50
        result = sanitize_tags_for_filter(tag_50)
        assert result == [tag_50], f"Expected ['{tag_50}'], got {result}"
        print("  PASS: 50-char tag accepted")

        # Deduplication
        result = sanitize_tags_for_filter("dup,dup,unique")
        assert result == ["dup", "unique"], f"Expected ['dup', 'unique'], got {result}"
        print("  PASS: Deduplication works")

        # Deduplication with case difference
        result = sanitize_tags_for_filter("Tag,TAG,tag")
        assert result == ["tag"], f"Expected ['tag'], got {result}"
        print("  PASS: Case-insensitive deduplication works")

        # Only commas / empty segments
        result = sanitize_tags_for_filter(",,,")
        assert result == [], f"Expected [], got {result}"
        print("  PASS: Only commas returns []")

        # Mixed valid and invalid in list
        result = sanitize_tags_for_filter([None, 123, "valid", "", "  ", "b@d"])
        assert result == ["valid"], f"Expected ['valid'], got {result}"
        print("  PASS: Non-string items in list dropped")

        print("\nAll sanitize_tags_for_filter tests passed!")
        return True

    except AssertionError as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\nTest failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_build_tags_filter():
    """Test the build_tags_filter function with sanitized inputs."""
    print("\nTesting build_tags_filter()...")

    from functions_search import build_tags_filter

    try:
        # Valid single tag
        result = build_tags_filter(["valid"])
        assert result == "document_tags/any(t: t eq 'valid')", f"Unexpected result: {result}"
        print("  PASS: Single valid tag")

        # Valid multiple tags
        result = build_tags_filter(["tag1", "tag-2"])
        expected = "document_tags/any(t: t eq 'tag1') and document_tags/any(t: t eq 'tag-2')"
        assert result == expected, f"Unexpected result: {result}"
        print("  PASS: Multiple valid tags")

        # Mixed valid and invalid - only valid should appear
        result = build_tags_filter(["good", "b@d", "fine"])
        expected = "document_tags/any(t: t eq 'good') and document_tags/any(t: t eq 'fine')"
        assert result == expected, f"Unexpected result: {result}"
        print("  PASS: Mixed valid/invalid tags - only valid in output")

        # All invalid tags
        result = build_tags_filter(["b@d", "inv alid", "no!way"])
        assert result == "", f"Expected empty string, got: {result}"
        print("  PASS: All invalid tags returns empty string")

        # Empty list
        result = build_tags_filter([])
        assert result == "", f"Expected empty string, got: {result}"
        print("  PASS: Empty list returns empty string")

        # None
        result = build_tags_filter(None)
        assert result == "", f"Expected empty string, got: {result}"
        print("  PASS: None returns empty string")

        # Injection attempt via tag value
        result = build_tags_filter(["x') or true or (t eq 'y"])
        assert result == "", f"Expected empty string, got: {result}"
        print("  PASS: OData injection attempt returns empty string")

        print("\nAll build_tags_filter tests passed!")
        return True

    except AssertionError as e:
        print(f"\nTest failed: {e}")
        import traceback
        traceback.print_exc()
        return False
    except Exception as e:
        print(f"\nTest failed with exception: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success1 = test_sanitize_tags_for_filter()
    success2 = test_build_tags_filter()

    if success1 and success2:
        print("\n=== ALL TESTS PASSED ===")
        sys.exit(0)
    else:
        print("\n=== SOME TESTS FAILED ===")
        sys.exit(1)
