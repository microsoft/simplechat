# test_v2_stats_export_contracts.py
"""
Functional test for V2 statistics export CSV contracts.
Version: 0.261.165
Implemented in: 0.261.165

This test pins the personal Statistics export's sections, columns and UTF-8 BOM
path, and the group Statistics CSV column format with its classic no-BOM adapter.
"""

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / "application" / "single_app"
V2_SRC = ROOT / "application" / "v2_ui" / "src"


def _read(path):
    return path.read_text(encoding="utf-8")


def test_personal_export_keeps_classic_sections_columns_and_bom_contract():
    classic = _read(APP_DIR / "templates" / "profile.html")
    stats_lib = _read(V2_SRC / "lib" / "userStats.ts")
    export_dialog = _read(V2_SRC / "components" / "settings" / "StatsExportDialog.tsx")

    for marker in (
        "User Activity Export",
        "SUMMARY METRICS",
        "LOGIN ACTIVITY",
        "CONVERSATION ACTIVITY",
        "DOCUMENT ACTIVITY",
        "TOKEN USAGE",
        "Total Logins",
        "Last Login",
        "Total Conversations",
        "Total Messages",
        "Total Message Size (bytes)",
        "Total Documents",
        "AI Search Size (bytes)",
        "Storage Size (bytes)",
        "Metrics Calculated At",
        "Date', 'Logins",
        "Date', 'Conversations Created', 'Conversations Deleted",
        "Date', 'Documents Uploaded', 'Documents Deleted",
        "Date', 'Total Tokens",
    ):
        assert marker in classic, f"The classic personal export no longer contains {marker}"
        assert marker in stats_lib, f"The V2 personal export no longer contains {marker}"

    assert "const body = withBom ? `\\ufeff${contents}` : contents;" in export_dialog
    assert "downloadCsv(csv, activityCsvFileName());" in export_dialog


def test_group_export_keeps_classic_csv_columns_without_bom():
    classic = _read(APP_DIR / "static" / "js" / "group" / "manage_group.js")
    group_stats = _read(V2_SRC / "lib" / "groupStats.ts")
    export_dialog = _read(V2_SRC / "components" / "settings" / "StatsExportDialog.tsx")

    markers = (
        ("Group Stats Export", "Group Stats Export"),
        ("SUMMARY METRICS", "SUMMARY METRICS"),
        ("DOCUMENT ACTIVITY", "DOCUMENT ACTIVITY"),
        ("TOKEN USAGE", "TOKEN USAGE"),
        ("STORAGE USAGE", "STORAGE USAGE"),
        ('Metric", "Value', "Metric', 'Value"),
        ("Total Documents", "Total Documents"),
        ("Storage Used (bytes)", "Storage Used (bytes)"),
        ("Total Tokens", "Total Tokens"),
        ("Total Members", "Total Members"),
        ('Date", "Uploads", "Deletes', "Date', 'Uploads', 'Deletes"),
        ('Date", "Total Tokens', "Date', 'Total Tokens"),
        ('Metric", "Bytes", "Formatted', "Metric', 'Bytes', 'Formatted"),
        ("AI Search", "AI Search"),
        ("Blob Storage", "Blob Storage"),
    )
    for classic_marker, v2_marker in markers:
        assert classic_marker in classic, f"The classic group export no longer contains {classic_marker}"
        assert v2_marker in group_stats, f"The V2 group export no longer contains {v2_marker}"

    assert "omitBom: true" in group_stats
    assert "downloadCsv(csv, fileName, !adapter.omitBom);" in export_dialog
