#!/usr/bin/env python3
# test_classic_group_stats_export_fix.py
"""
Functional test for the classic group stats export fix.
Version: 0.261.163
Implemented in: 0.261.163

This test ensures that the classic Manage group page's statistics export
(`exportGroupStats` in `static/js/group/manage_group.js`) produces its CSV,
including the storage section that is ticked by default. The export called a
`formatBytes` the module never defined or imported, so every export with
Storage ticked failed with "Failed to export group stats." and nothing
downloaded.

The test runs the real `exportGroupStats`, and the real CSV and window helpers
it calls, in Node, extracted from the module by name. Only the browser seams are
stubbed: jQuery's checkbox reads, `fetch`, the toast, the modal and the file
download. A helper the export calls that the module doesn't define is therefore
missing here too, and the export fails exactly as it did in the browser.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGE_GROUP_JS = REPO_ROOT / "application" / "single_app" / "static" / "js" / "group" / "manage_group.js"

# The module's own top-level functions the export path runs. `formatBytes` is
# the one the module was missing; the others were always there.
EXTRACTED_FUNCTIONS = (
    "formatDateInputForDisplay",
    "getStatsWindowLabel",
    "getStatsQueryString",
    "getExportStatsWindowSelection",
    "escapeCsvValue",
    "appendCsvRow",
    "appendCsvSectionBreak",
    "formatBytes",
    "exportGroupStats",
)

STATS_RESPONSE = {
    "totalDocuments": 12,
    "storageUsed": 1049600,
    "totalTokens": 4200,
    "totalMembers": 3,
    "window": {"label": "Last 30 Days"},
    "documentActivity": {"labels": ["2026-09-20", "2026-09-21"], "uploads": [2, 1], "deletes": [0, 1]},
    "tokenUsage": {"labels": ["2026-09-20", "2026-09-21"], "data": [1200, 3000]},
    "storage": {"ai_search_size": 1536, "storage_account_size": 1048576},
}

# The classic byte format, the same as the V2 group export's "Formatted" column.
FORMAT_CASES = (
    (0, "0 B"),
    (1, "1 B"),
    (1023, "1023 B"),
    (1024, "1 KB"),
    (1536, "1.5 KB"),
    (1048576, "1 MB"),
    (5905580032, "5.5 GB"),
    (1099511627776, "1 TB"),
    (2251799813685248, "2048 TB"),
)

DRIVER = r"""
const checks = __CHECKS__;
const stats = __STATS__;
const toasts = [];
const requested = [];
let downloaded = null;
let modalHidden = false;

const groupId = "group-1";
let currentStatsWindow = { days: 30, startDate: "", endDate: "" };

function $(selector) {
    return {
        prop: (name) => (name === "checked" ? Boolean(checks[selector]) : undefined),
        val: () => (selector === 'input[name="groupExportTimeWindow"]:checked' ? "30" : ""),
    };
}
const exportButton = { disabled: false, innerHTML: "Export" };
const document = {
    getElementById: (id) => (id === "executeGroupStatsExportBtn" ? exportButton : id === "groupStatsExportModal" ? {} : null),
};
const bootstrap = { Modal: { getInstance: () => ({ hide: () => { modalHidden = true; } }) } };
function showToast(message, tone) { toasts.push([message, tone]); }
async function fetch(url) {
    requested.push(url);
    return { ok: true, json: async () => stats };
}
function downloadCsvFile(content, filename) { downloaded = { content, filename }; }
const console = { error: () => {}, log: globalThis.console.log };

__FUNCTIONS__

__BODY__
"""

EXPORT_BODY = r"""
await exportGroupStats();
globalThis.console.log(JSON.stringify({
    toasts, requested, downloaded, modalHidden, buttonRestored: exportButton.innerHTML === "Export" && !exportButton.disabled,
}));
"""


def top_level_function(source, name):
    """The source of the module's top-level `function name(...) {...}`, or None when it has none.

    Every top-level function in the module opens at column 0 and closes on a line that is
    exactly `}`, so the first such line after the declaration ends it.
    """
    lines = source.splitlines()
    declaration = re.compile(rf"^(async\s+)?function\s+{re.escape(name)}\s*\(")
    for start, line in enumerate(lines):
        if declaration.match(line):
            for end in range(start + 1, len(lines)):
                if lines[end] == "}":
                    return "\n".join(lines[start:end + 1])
            raise AssertionError(f"{name} in manage_group.js has no closing brace at column 0")
    return None


def run_driver(body, checks=None):
    """Run `body` after the module's export functions and the browser stubs, and return its JSON."""
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is required to run the classic export in this test")
    source = MANAGE_GROUP_JS.read_text(encoding="utf-8")
    functions = [top_level_function(source, name) for name in EXTRACTED_FUNCTIONS]
    if checks is None:
        checks = {
            "#groupExportSummary": True, "#groupExportDocuments": True,
            "#groupExportTokens": True, "#groupExportStorage": True,
        }
    script = (
        DRIVER.replace("__CHECKS__", json.dumps(checks))
        .replace("__STATS__", json.dumps(STATS_RESPONSE))
        .replace("__FUNCTIONS__", "\n\n".join(function for function in functions if function))
        .replace("__BODY__", body)
    )
    completed = subprocess.run(
        [node, "--input-type=module"], input=script, capture_output=True, text=True, encoding="utf-8",
        timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(f"The export driver failed:\n{completed.stderr[-2000:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_default_export_downloads_the_csv_with_storage():
    """With every section ticked, as the dialog opens, the export downloads a complete CSV."""
    print("Testing the classic group stats export with every section ticked...")
    result = run_driver(EXPORT_BODY)

    assert result["toasts"] == [["Group stats exported successfully.", "success"]], result["toasts"]
    assert result["requested"] == ["/api/groups/group-1/stats?days=30"]
    assert result["modalHidden"] and result["buttonRestored"]
    downloaded = result["downloaded"]
    assert downloaded is not None, "The export downloaded nothing"
    assert re.fullmatch(r"group_stats_export_\d{4}-\d{2}-\d{2}\.csv", downloaded["filename"])
    rows = downloaded["content"].split("\n")
    assert rows[0] == "Group Stats Export"
    assert "Data Period,Last 30 Days" in rows
    for section in ("SUMMARY METRICS", "DOCUMENT ACTIVITY (Last 30 Days)", "TOKEN USAGE (Last 30 Days)", "STORAGE USAGE"):
        assert section in rows, f"{section} is missing from the CSV"
    storage = rows[rows.index("STORAGE USAGE"):]
    assert storage[1:4] == ["Metric,Bytes,Formatted", "AI Search,1536,1.5 KB", "Blob Storage,1048576,1 MB"], storage[:4]
    print("Test passed!")
    return True


def test_export_without_storage_still_downloads():
    """Leaving Storage unticked downloads the other sections and no storage rows."""
    print("Testing the classic group stats export without the storage section...")
    result = run_driver(EXPORT_BODY, checks={
        "#groupExportSummary": True, "#groupExportDocuments": True,
        "#groupExportTokens": True, "#groupExportStorage": False,
    })

    assert result["toasts"] == [["Group stats exported successfully.", "success"]], result["toasts"]
    rows = result["downloaded"]["content"].split("\n")
    assert "SUMMARY METRICS" in rows and "STORAGE USAGE" not in rows
    print("Test passed!")
    return True


def test_format_bytes_uses_the_classic_format():
    """The storage column's format: `0 B`, then B, KB, MB, GB and TB to two decimals, capped at TB."""
    print("Testing the classic group byte formatter...")
    cases = json.dumps([value for value, _ in FORMAT_CASES])
    result = run_driver(f"globalThis.console.log(JSON.stringify({cases}.map((value) => formatBytes(value))));")

    assert result == [expected for _, expected in FORMAT_CASES], result
    print("Test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_default_export_downloads_the_csv_with_storage,
        test_export_without_storage_still_downloads,
        test_format_bytes_uses_the_classic_format,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(test())
        except Exception as error:
            print(f"Test failed: {error}")
            import traceback
            traceback.print_exc()
            results.append(False)
    success = all(results)
    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if success else 1)
