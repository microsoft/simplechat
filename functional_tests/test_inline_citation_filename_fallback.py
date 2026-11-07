# test_inline_citation_filename_fallback.py
"""
Execute both production citation parsers against placeholder-label regressions.
Version: 0.261.389
Implemented in: 0.261.355; raw V2 citation markers in 0.261.388

Checks exact-ID filename fallback, preserved titles and locations, source isolation,
conflicting records, inert filenames, legacy messages, and optional copied sources.
No Azure services or model calls are used.
"""

import json
import re
import shutil
import subprocess
import sys
import tempfile
from html import unescape
from pathlib import Path

import pytest

from test_chat_citation_whitespace_preservation import run_citation_harness
from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
V2 = ROOT / "application" / "v2_ui"
FIRST = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee_1"
SECOND = "11111111-2222-3333-4444-555555555555_2"
M365 = "m365-0123456789abcdef"


def marker(label="Untitled Document", ids=FIRST, location="1", location_label="Page"):
    references = " ".join(f"[#{value}]" for value in ids.split(";"))
    return f"(Source: {label}, {location_label}: {location}) {references}"


def record(citation_id=FIRST, file_name="public-guide.md", **extra):
    return {"citation_id": citation_id, "file_name": file_name, **extra}


CASES = {
    "reported": (marker(), [record()], ["public-guide.md"]),
    "case_and_whitespace": (marker(" unTITled \t Document "), [record()], ["public-guide.md"]),
    "generic_untitled": (marker("Untitled"), [record()], ["public-guide.md"]),
    "meaningful": (marker("Public guide"), [record()], ["Public guide"]),
    "literal_filename": (marker("Untitled Document.docx"), [record()], ["Untitled Document.docx"]),
    "literal_title": (marker("An Untitled Document Collection"), [record()], ["An Untitled Document Collection"]),
    "legacy": (marker(), [], ["Untitled Document"]),
    "null_records": (marker(), None, ["Untitled Document"]),
    "invalid_records": (marker(), {"file_name": "unmatched.md"}, ["Untitled Document"]),
    "other_id": (marker(), [record(SECOND)], ["Untitled Document"]),
    "blank_filename": (marker(), [record(file_name=" \t ")], ["Untitled Document"]),
    "invalid_filename": (marker(), [record(file_name=123)], ["Untitled Document"]),
    "malformed_record": (marker(), [None, {}, record(citation_id=1)], ["Untitled Document"]),
    "duplicate": (marker(), [record(), record()], ["public-guide.md"]),
    "conflict": (
        marker(), [record(), record(file_name="different.md"), record()], ["Untitled Document"],
    ),
    "normalized_record": (marker(), [record(f" #{FIRST} ", " public-guide.md ")], ["public-guide.md"]),
    "two_files": (
        marker(ids=f"{FIRST};{SECOND}", location="1, 2"),
        [record(), record(SECOND, "different-guide.md")], ["public-guide.md", "different-guide.md"],
    ),
    "one_missing": (
        marker(ids=f"{FIRST};{SECOND}", location="1, 2"),
        [record()], ["public-guide.md", "Untitled Document"],
    ),
    "two_pages": (
        marker(ids=f"{FIRST};{FIRST[:-1]}2", location="1, 2"),
        [record(), record(FIRST[:-1] + "2")], ["public-guide.md"],
    ),
    "same_name_two_documents": (
        marker(ids=f"{FIRST};{SECOND[:-1]}1", location="1, 1"),
        [record(), record(SECOND[:-1] + "1")], ["public-guide.md"],
    ),
    "page_range": (
        marker(ids=f"{FIRST};{FIRST[:-1]}3", location="1-3", location_label="Pages"),
        [record(), record(FIRST[:-1] + "3")], ["public-guide.md"],
    ),
    "sheet": (marker(location="Annual figures", location_label="Sheet"), [record()], ["public-guide.md"]),
    "location": (marker(location="Workbook Schema", location_label="Location"), [record()], ["public-guide.md"]),
    "markup": (marker(), [record(file_name='<img src=x onerror="window.injected=true">.md')], ['<img src=x onerror="window.injected=true">.md']),
    "url_filename": (marker(), [record(file_name="https://example.test/file.md")], ["https://example.test/file.md"]),
    "web": (marker("https://example.test/source"), [record()], ["https://example.test/source"]),
    "agent": (marker("agent: Research"), [record()], ["agent: Research"]),
    "m365": (marker(ids=M365), [record(M365)], ["Untitled Document"]),
    "repeated": (
        f"First {marker()}. Again {marker()}\n\nNext paragraph.",
        [record()], ["public-guide.md", "public-guide.md"],
    ),
}
for scope_key, scope_value in [("user_id", "owner"), ("group_id", "group"), ("public_workspace_id", "public")]:
    CASES[scope_key] = (marker(), [record(**{scope_key: scope_value})], ["public-guide.md"])

RAW_MARKER = f"\u3010{FIRST}\u3011"
RAW_CASES = {
    "raw_page": {"message": f"Found it {RAW_MARKER}.", "records": [record(page_number=1)]},
    "raw_sheet": {"message": RAW_MARKER, "records": [record(location_label="Sheet", sheet_name="Annual figures")]},
    "raw_unknown": {"message": RAW_MARKER, "records": []},
    "raw_other_message": {"message": RAW_MARKER, "records": [record(SECOND)]},
    "raw_conflict": {"message": RAW_MARKER, "records": [record(), record(file_name="other.md"), record()]},
    "raw_code": {"message": f"`{RAW_MARKER}`\n\n```text\n{RAW_MARKER}\n```\n", "records": [record()]},
    "raw_open_fence": {"message": f"```text\n{RAW_MARKER}", "records": [record()]},
    "raw_false_fence_close": {"message": f"```text\n{RAW_MARKER}\n```not-a-closing-fence\n{RAW_MARKER}\n```",
                              "records": [record()]},
    "raw_no_page": {"message": RAW_MARKER, "records": [record()]},
    "raw_mixed": {"message": f"{RAW_MARKER} then {marker('Other guide', SECOND)}",
                  "records": [record(page_number=1), record(SECOND, "other.md", page_number=2)]},
    "raw_unsafe_name": {"message": RAW_MARKER, "records": [record(file_name="<img src=x onerror=run()>.md")]},
}

NODE_RUNNER = r"""
const esbuild = require('esbuild');
esbuild.buildSync({
    stdin: { contents: `
        import { parseCitations } from './src/lib/citations.ts';
        import { messageToPlainText } from './src/lib/messageText.ts';
        import fs from 'node:fs';
        const cases = JSON.parse(fs.readFileSync(0, 'utf8'));
        const results = {};
        for (const [key, item] of Object.entries(cases)) {
            const message = {content: item.message, hybrid_citations: item.records};
            results[key] = {
                ...parseCitations(item.message, item.records),
                plain: messageToPlainText(message),
                withSources: messageToPlainText(message, {includeSources: true}),
                original: message.content,
            };
        }
        process.stdout.write(JSON.stringify(results));
    `, resolveDir: process.cwd() },
    bundle: true, platform: 'node', format: 'cjs', outfile: process.argv[1], logLevel: 'warning',
});
"""


@pytest.fixture(scope="module")
def parsed_results():
    classic_cases = {
        key: {"message": message, "options": {"documentCitations": records}}
        for key, (message, records, _) in CASES.items()
    }
    classic = run_citation_harness(classic_cases)
    if classic is None:
        pytest.fail("Node.js is required to execute the production parsers.")
    node = shutil.which("node")
    inputs = {
        key: {"message": message, "records": records}
        for key, (message, records, _) in CASES.items()
    }
    inputs.update(RAW_CASES)
    with tempfile.TemporaryDirectory(prefix="simplechat-citation-fallback-") as temporary:
        bundle = Path(temporary) / "citations.cjs"
        built = subprocess.run(
            [node, "-e", NODE_RUNNER, str(bundle)], cwd=V2,
            capture_output=True, text=True, timeout=60,
        )
        assert built.returncode == 0, built.stdout + built.stderr
        checked = subprocess.run(
            [node, str(bundle)], input=json.dumps(inputs), cwd=V2,
            capture_output=True, text=True, timeout=60,
        )
        assert checked.returncode == 0, checked.stdout + checked.stderr
    return classic, json.loads(checked.stdout)


@pytest.mark.parametrize("case", CASES)
def test_both_clients_use_only_matching_filenames_for_placeholder_labels(parsed_results, case):
    classic, v2 = parsed_results
    message, _, names = CASES[case]
    actual_names = [group["fileName"] for group in v2[case]["groups"]]
    assert actual_names == names
    classic_text = unescape(re.sub(r"<[^>]+>", "", classic[case]["markdown"]))
    for name in names:
        assert f"Source: {name}," in classic_text
    assert v2[case]["original"] == message
    if case not in {"legacy", "null_records", "invalid_records", "other_id", "blank_filename", "invalid_filename", "malformed_record", "conflict", "m365"}:
        assert "Untitled Document" not in actual_names or case == "one_missing"


def test_multi_document_locations_and_ids_remain_paired(parsed_results):
    classic, v2 = parsed_results
    groups = v2["two_files"]["groups"]
    assert [(group["citations"][0]["citationId"], group["citations"][0]["locationValue"]) for group in groups] == [
        (FIRST, "1"), (SECOND, "2"),
    ]
    rendered = classic["two_files"]["markdown"]
    first, second = rendered.split(", (Source:")
    assert "public-guide.md" in first and FIRST in first and SECOND not in first
    assert "different-guide.md" in second and SECOND in second and FIRST not in second
    same_name_refs = [citation["citationId"] for citation in v2["same_name_two_documents"]["groups"][0]["citations"]]
    assert same_name_refs == [FIRST, SECOND[:-1] + "1"]
    same_name_sources = classic["same_name_two_documents"]["markdown"]
    assert FIRST in same_name_sources and SECOND[:-1] + "1" in same_name_sources
    for page in ("1", "2", "3"):
        assert f'data-citation-id="{FIRST[:-1]}{page}"' in classic["page_range"]["markdown"]


def test_fallbacks_stay_inert_and_preserve_surrounding_prose(parsed_results):
    classic, v2 = parsed_results
    assert "<img" not in classic["markup"]["markdown"]
    assert "&lt;img" in classic["markup"]["markdown"]
    assert "<a href=\"https://example.test/file.md\"" not in classic["url_filename"]["markdown"]
    assert v2["url_filename"]["groups"][0]["kind"] == "document"
    assert "\n\nNext paragraph." in classic["repeated"]["markdown"]
    assert "\n\nNext paragraph." in v2["repeated"]["text"]
    assert "Sources:\n1. public-guide.md" in v2["reported"]["withSources"]
    assert v2["reported"]["plain"] == ""
    assert v2["sheet"]["groups"][0]["citations"][0]["locationValue"] == "Annual figures"
    assert v2["location"]["groups"][0]["citations"][0]["locationValue"] == "Workbook Schema"


def test_implementation_version():
    assert_app_version_at_least("0.261.355")


def test_v2_raw_markers_use_only_exact_recorded_source_metadata(parsed_results):
    _, v2 = parsed_results
    page = v2["raw_page"]["groups"][0]
    assert page["fileName"] == "public-guide.md"
    assert page["citations"][0]["locationValue"] == "1"
    assert page["citations"][0]["citationId"] == FIRST
    assert v2["raw_sheet"]["groups"][0]["citations"][0]["locationValue"] == "Annual figures"
    assert v2["raw_no_page"]["groups"][0]["citations"][0]["pageNumber"] == ""
    assert v2["raw_no_page"]["groups"][0]["citations"][0]["locationValue"] == ""
    assert [group["fileName"] for group in v2["raw_mixed"]["groups"]] == ["public-guide.md", "Other guide"]
    assert v2["raw_unsafe_name"]["groups"][0]["fileName"] == "<img src=x onerror=run()>.md"
    for key in ("raw_unknown", "raw_other_message", "raw_conflict"):
        assert v2[key]["groups"] == []
        assert v2[key]["text"] == "[Source unavailable]"
    for key in ("raw_code", "raw_open_fence", "raw_false_fence_close"):
        assert v2[key]["groups"] == []
        assert v2[key]["text"] == RAW_CASES[key]["message"]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
