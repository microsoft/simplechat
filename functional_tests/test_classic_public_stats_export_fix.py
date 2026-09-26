#!/usr/bin/env python3
# test_classic_public_stats_export_fix.py
"""
Functional test for the classic public workspace statistics export and its byte formatter.
Version: 0.261.181
Implemented in: 0.261.181

This test ensures that the classic manage public workspace page's statistics export
(`exportWorkspaceStats` in `static/js/public/manage_public_workspace.js`) produces its
CSV, column for column, and that its `formatBytes` writes the storage section's
"Formatted" column as the classic group page and the V2 statistics export do: "0 B" for
no size, then B to TB to two decimals, capped at TB. Before the fix, a size past a
terabyte printed "undefined" as its unit (2 PB was "2 undefined"), and a missing size
printed "NaN undefined".

The test runs the real `exportWorkspaceStats`, and the real CSV, window, toast and byte
helpers it calls, in Node, extracted from the module by name. Only the browser seams are
stubbed: jQuery's checkbox reads, `fetch`, the page toast, the modal and the file
download. A helper the export calls that the module doesn't define is therefore missing
here too, and the export fails exactly as it would in the browser.
"""

import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
MANAGE_PUBLIC_WORKSPACE_JS = (
    REPO_ROOT / "application" / "single_app" / "static" / "js" / "public" / "manage_public_workspace.js"
)

# The module's own top-level functions the export path runs.
EXTRACTED_FUNCTIONS = (
    "showStatsToast",
    "formatDateInputForDisplay",
    "getStatsWindowLabel",
    "getStatsQueryString",
    "getExportStatsWindowSelection",
    "escapeCsvValue",
    "appendCsvRow",
    "appendCsvSectionBreak",
    "formatBytes",
    "exportWorkspaceStats",
)

# The native statistics envelope: the classic figures without the invented storageLimit,
# which the classic export never wrote. The blob storage figure is past a terabyte.
STATS_RESPONSE = {
    "totalDocuments": 12,
    "storageUsed": 2251799813685248,
    "totalTokens": 4200,
    "totalMembers": 3,
    "window": {"label": "Last 30 Days"},
    "documentActivity": {"labels": ["9/20", "9/21"], "uploads": [2, 1], "deletes": [0, 1]},
    "tokenUsage": {"labels": ["9/20", "9/21"], "data": [1200, 3000]},
    "storage": {"ai_search_size": 1536, "storage_account_size": 2251799813685248},
}

# The classic byte format, the same as the classic group export's and the V2 export's
# "Formatted" column.
FORMAT_CASES = (
    (0, "0 B"),
    (None, "0 B"),
    (1, "1 B"),
    (1023, "1023 B"),
    (1024, "1 KB"),
    (1536, "1.5 KB"),
    (1048576, "1 MB"),
    (5905580032, "5.5 GB"),
    (1099511627776, "1 TB"),
    (1125899906842624, "1024 TB"),
    (2251799813685248, "2048 TB"),
)

DRIVER = r"""
const checks = __CHECKS__;
const stats = __STATS__;
const toasts = [];
const requested = [];
let downloaded = null;
let modalHidden = false;

const workspaceId = "pub-1";
let currentStatsWindow = { days: 30, startDate: "", endDate: "" };
const publicWorkspaceSingular = "Public Workspace";
const publicWorkspaceLowerSingular = "public workspace";

function $(selector) {
    return {
        prop: (name) => (name === "checked" ? Boolean(checks[selector]) : undefined),
        val: () => (selector === 'input[name="publicExportTimeWindow"]:checked' ? "30" : ""),
    };
}
const exportButton = { disabled: false, innerHTML: "Export" };
const document = {
    getElementById: (id) => (id === "executePublicStatsExportBtn" ? exportButton : id === "publicStatsExportModal" ? {} : null),
};
const bootstrap = { Modal: { getInstance: () => ({ hide: () => { modalHidden = true; } }) } };
function showPublicWorkspaceToast(message, tone) { toasts.push([message, tone]); }
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
await exportWorkspaceStats();
globalThis.console.log(JSON.stringify({
    toasts, requested, downloaded, modalHidden, buttonRestored: exportButton.innerHTML === "Export" && !exportButton.disabled,
}));
"""

ALL_SECTIONS = {
    "#publicExportSummary": True, "#publicExportDocuments": True,
    "#publicExportTokens": True, "#publicExportStorage": True,
}


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
            raise AssertionError(f"{name} in manage_public_workspace.js has no closing brace at column 0")
    return None


def run_driver(body, checks=None):
    """Run `body` after the module's export functions and the browser stubs, and return its JSON."""
    node = shutil.which("node")
    if not node:
        raise AssertionError("Node.js is required to run the classic export in this test")
    source = MANAGE_PUBLIC_WORKSPACE_JS.read_text(encoding="utf-8")
    functions = [top_level_function(source, name) for name in EXTRACTED_FUNCTIONS]
    missing = [name for name, function in zip(EXTRACTED_FUNCTIONS, functions) if function is None]
    assert not missing, f"manage_public_workspace.js no longer defines {missing}"
    script = (
        DRIVER.replace("__CHECKS__", json.dumps(ALL_SECTIONS if checks is None else checks))
        .replace("__STATS__", json.dumps(STATS_RESPONSE))
        .replace("__FUNCTIONS__", "\n\n".join(functions))
        .replace("__BODY__", body)
    )
    completed = subprocess.run(
        [node, "--input-type=module"], input=script, capture_output=True, text=True, encoding="utf-8",
        timeout=60,
    )
    if completed.returncode != 0:
        raise AssertionError(f"The export driver failed:\n{completed.stderr[-2000:]}")
    return json.loads(completed.stdout.strip().splitlines()[-1])


def test_default_export_writes_the_classic_columns():
    """With every section ticked, as the dialog opens, the export downloads the classic CSV."""
    print("Testing the classic public stats export with every section ticked...")
    result = run_driver(EXPORT_BODY)

    assert result["toasts"] == [["Public Workspace stats exported successfully.", "success"]], result["toasts"]
    assert result["requested"] == ["/api/public_workspaces/pub-1/stats?days=30"]
    assert result["modalHidden"] and result["buttonRestored"]
    downloaded = result["downloaded"]
    assert downloaded is not None, "The export downloaded nothing"
    assert re.fullmatch(r"public_workspace_stats_export_\d{4}-\d{2}-\d{2}\.csv", downloaded["filename"])
    rows = downloaded["content"].split("\n")
    assert rows[0] == "Public Workspace Stats Export"
    assert rows[1].startswith("Export Date,")
    assert rows[2:4] == ["Data Period,Last 30 Days", ""]
    summary = rows[rows.index("SUMMARY METRICS"):]
    assert summary[1:7] == [
        "Metric,Value", "Total Documents,12", "Storage Used (bytes),2251799813685248", "Total Tokens,4200",
        "Total Members,3", "",
    ], summary[:7]
    documents = rows[rows.index("DOCUMENT ACTIVITY (Last 30 Days)"):]
    assert documents[1:5] == ["Date,Uploads,Deletes", "9/20,2,0", "9/21,1,1", ""], documents[:5]
    tokens = rows[rows.index("TOKEN USAGE (Last 30 Days)"):]
    assert tokens[1:5] == ["Date,Total Tokens", "9/20,1200", "9/21,3000", ""], tokens[:5]
    storage = rows[rows.index("STORAGE USAGE"):]
    assert storage[1:4] == [
        "Metric,Bytes,Formatted", "AI Search,1536,1.5 KB", "Blob Storage,2251799813685248,2048 TB",
    ], storage[:4]
    assert "undefined" not in downloaded["content"] and "NaN" not in downloaded["content"]
    assert "Limit" not in downloaded["content"]
    print("Test passed!")
    return True


def test_export_without_storage_still_downloads():
    """Leaving Storage unticked downloads the other sections and no storage rows."""
    print("Testing the classic public stats export without the storage section...")
    result = run_driver(EXPORT_BODY, checks={**ALL_SECTIONS, "#publicExportStorage": False})

    assert result["toasts"] == [["Public Workspace stats exported successfully.", "success"]], result["toasts"]
    rows = result["downloaded"]["content"].split("\n")
    assert "SUMMARY METRICS" in rows and "STORAGE USAGE" not in rows
    print("Test passed!")
    return True


def test_an_export_with_nothing_ticked_asks_for_a_section():
    print("Testing the classic public stats export with nothing ticked...")
    result = run_driver(EXPORT_BODY, checks={})

    assert result["toasts"] == [["Please select at least one data type to export.", "warning"]]
    assert result["requested"] == [] and result["downloaded"] is None
    print("Test passed!")
    return True


def test_format_bytes_caps_at_terabytes_and_reads_no_size_as_zero():
    """The storage column's format: `0 B`, then B, KB, MB, GB and TB to two decimals, capped at TB."""
    print("Testing the classic public byte formatter...")
    cases = json.dumps([value for value, _ in FORMAT_CASES])
    body = (
        f"globalThis.console.log(JSON.stringify([...{cases}.map((value) => formatBytes(value)), "
        "formatBytes(undefined), formatBytes(Number.NaN)]));"
    )
    result = run_driver(body)

    assert result == [expected for _, expected in FORMAT_CASES] + ["0 B", "0 B"], result
    print("Test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_default_export_writes_the_classic_columns,
        test_export_without_storage_still_downloads,
        test_an_export_with_nothing_ticked_asks_for_a_section,
        test_format_bytes_caps_at_terabytes_and_reads_no_size_as_zero,
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
