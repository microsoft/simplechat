#!/usr/bin/env python3
"""
Functional test for the V2 settings Stats tab reaching parity with the classic profile page.

Version: 0.261.041
Implemented in: 0.261.041

The V2 Stats tab replaced a placeholder that showed four SVG bar sparklines. Everything it
now draws already existed on the classic profile page's stats tab, served by the same two
endpoints, so the risk in this change is not that a number is wrong -- it is that a field
name, query parameter or nested key is spelled differently on one side. That failure mode is
silent: the request succeeds, the response simply contains nothing the client recognises, and
the tab renders zeroes. Every name below was read off the route rather than inferred.

The second thing pinned here is the trade the change rests on. The account menu's Profile
link is gone, so the classic stats page is no longer one click away; a surface that quietly
stopped being covered would leave users with no route to it at all. Each classic surface is
therefore checked to have a counterpart.
"""

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_DIR = REPO_ROOT / "application" / "single_app"
V2_SRC = REPO_ROOT / "application" / "v2_ui" / "src"

sys.path.insert(0, str(REPO_ROOT / "functional_tests"))

from test_support.versioning import assert_app_version_at_least  # noqa: E402


def _read(path):
    return path.read_text(encoding="utf-8")


def test_trend_fields_match_the_route():
    """Every series the tab reads is a key the activity-trends route emits."""
    print("Testing activity-trends field names...")

    profile = _read(APP_DIR / "route_frontend_profile.py")
    stats_lib = _read(V2_SRC / "lib" / "userStats.ts")
    tab = _read(V2_SRC / "components" / "settings" / "StatsTab.tsx")

    # The response is assembled as a jsonify() literal, so these are the wire names.
    for field in (
        '"logins"',
        '"conversations"',
        '"documents"',
        '"tokens"',
        '"storage"',
        '"dateRange"',
        '"window"',
    ):
        assert field in profile, f"The activity-trends response no longer returns {field}"

    # Conversations and documents are nested by action, and each nests under a different
    # word. Reading `creates` from documents would return undefined, not an error.
    assert '"creates"' in profile and '"deletes"' in profile, (
        "Conversations are nested as creates/deletes"
    )
    assert '"uploads"' in profile, "Documents are nested as uploads/deletes"
    assert "data?.conversations?.creates" in tab, "The tab must read conversations.creates"
    assert "data?.conversations?.deletes" in tab, "The tab must read conversations.deletes"
    assert "data?.documents?.uploads" in tab, "The tab must read documents.uploads"
    assert "data?.documents?.deletes" in tab, "The tab must read documents.deletes"

    # Storage is a two-key object, and the keys are snake_case unlike the rest of the payload.
    for key in ("ai_search_size", "storage_account_size"):
        assert f'"{key}"' in profile, f"The storage payload no longer returns {key}"
        assert key in stats_lib, f"The stats client no longer reads {key}"

    # Days carry `count`, except the token series which carries `tokens`.
    assert '"tokens": tokens_by_date' in profile, (
        "The token series is keyed by `tokens`, not `count`"
    )
    assert "'tokens'" in stats_lib, "The client must read the token series by its own key"

    print("Activity-trends field name test passed!")
    return True


def test_window_parameters_match_the_resolver():
    """A preset sends days; a custom range sends dates, and never both."""
    print("Testing stats window parameters...")

    windows = _read(APP_DIR / "functions_stats_windows.py")
    stats_lib = _read(V2_SRC / "lib" / "userStats.ts")

    # resolve_stats_time_window branches on the *presence* of either date and ignores `days`
    # entirely in that branch, so sending both would be silently contradictory.
    for param in ("start_date", "end_date", "days"):
        assert f"'{param}'" in windows, f"The resolver no longer reads {param}"
        assert f"'{param}'" in stats_lib, f"The client no longer sends {param}"

    query = re.search(
        r"export function statsWindowQuery[\s\S]*?\n\}", stats_lib
    )
    assert query, "Could not find statsWindowQuery in userStats.ts"
    body = query.group(0)
    assert "isCustomWindow" in body, "The query must branch on whether the window is custom"
    custom_branch, preset_branch = body.split("} else {", 1)
    assert "start_date" in custom_branch and "end_date" in custom_branch
    assert "days" not in custom_branch.split("if (isCustomWindow")[1], (
        "A custom range must not also send `days`: the resolver ignores it, so its presence "
        "only invites the two to disagree"
    )
    assert "days" in preset_branch and "start_date" not in preset_branch

    # The presets must be values the resolver accepts. An unrecognised count is not
    # rejected, it becomes 30, so the tab would highlight a window it is not showing.
    allowed = re.search(r"ALLOWED_STATS_WINDOW_DAYS = \(([^)]*)\)", windows)
    assert allowed, "Could not find ALLOWED_STATS_WINDOW_DAYS"
    permitted = {value.strip() for value in allowed.group(1).split(",") if value.strip()}
    offered = set(re.findall(r"\{ days: (\d+),", stats_lib))
    assert offered and offered <= permitted, (
        f"The tab offers windows the route rejects: {offered - permitted}"
    )

    # The server refuses a reversed range with a 400; the client says so first.
    assert "start_date must be before or equal to end_date" in windows
    assert "validateCustomRange" in stats_lib, (
        "A custom range must be checked before it is sent, so the user is told what is "
        "wrong with the dates rather than shown a failed request"
    )

    print("Stats window parameter test passed!")
    return True


def test_lifetime_totals_read_the_cached_metrics_block():
    """The four cards come from /api/user/settings, not from the window."""
    print("Testing cached metrics contract...")

    profile = _read(APP_DIR / "route_frontend_profile.py")
    # The block itself is produced and cached by the control-center metrics pass, which is
    # where its group and field names are actually decided; the settings route only hands
    # back what was stored.
    producer = _read(APP_DIR / "route_backend_control_center.py")
    stats_lib = _read(V2_SRC / "lib" / "userStats.ts")
    tab = _read(V2_SRC / "components" / "settings" / "StatsTab.tsx")

    assert '"settings": response_settings' in profile, (
        "The settings route no longer nests its payload under `settings`"
    )
    assert "response_settings['metrics'] = metrics" in profile, (
        "The metrics block is no longer returned inside settings"
    )
    assert "settings?.settings?.metrics" in tab, (
        "The tab must read the metrics block from inside `settings`"
    )
    assert "'calculated_at': datetime.now(timezone.utc).isoformat()" in producer, (
        "The cached block no longer records when it was calculated"
    )

    # Group names on the metrics block. Each is a separate dict, and a card reading the
    # wrong one would show a plausible number from the wrong category.
    for group in ("login_metrics", "chat_metrics", "document_metrics"):
        assert f"'{group}'" in producer, f"The cached metrics block no longer has {group}"
        assert group in stats_lib, f"The stats client no longer models {group}"

    # The fields behind the four cards, and the two sizes the export reports.
    for field in (
        "total_logins",
        "total_conversations",
        "total_messages",
        "total_message_size",
        "total_documents",
        "ai_search_size",
        "storage_account_size",
    ):
        assert f"'{field}'" in producer, f"The cached metrics block no longer has {field}"
        assert field in stats_lib, f"The stats client no longer reads {field}"

    # The note explaining that the totals are cached only makes sense with the stamp.
    assert "calculated_at" in stats_lib
    assert "calculated_at" in tab, (
        "The tab must say when the cached totals were worked out; without it the four "
        "cards read as live figures"
    )

    # last_login is the one field on the block that is not cached: the settings route
    # overwrites it from the activity log, which is why it can be shown beside a stale total.
    assert "login_metrics['last_login'] = login_activity_summary.get('last_login')" in profile
    assert "last_login" in tab, "The tab should surface the last sign-in"

    print("Cached metrics contract test passed!")
    return True


def test_every_classic_stats_surface_has_a_counterpart():
    """Nothing the classic stats tab shows was dropped on the way over."""
    print("Testing classic parity...")

    tab = _read(V2_SRC / "components" / "settings" / "StatsTab.tsx")
    export_dialog = _read(V2_SRC / "components" / "settings" / "StatsExportDialog.tsx")
    stats_lib = _read(V2_SRC / "lib" / "userStats.ts")
    combined = tab + export_dialog + stats_lib

    surfaces = {
        "preset windows": "STATS_WINDOWS",
        "custom date range": "validateCustomRange",
        "cached totals note": "calculated_at",
        "conversation totals": "total_conversations",
        "message totals": "total_messages",
        "document totals": "total_documents",
        "sign-in totals": "total_logins",
        "sign-in trend chart": "logins",
        "conversation trend chart": "conversationCreates",
        "document trend chart": "documentUploads",
        "token trend chart": "tokenMillions",
        "storage breakdown": "ai_search_size",
        "CSV export": "buildActivityCsv",
        "account information": "display_name",
    }
    missing = [name for name, marker in surfaces.items() if marker not in combined]
    assert not missing, (
        "These classic stats surfaces have no counterpart in the V2 tab, and the classic "
        f"page is no longer linked from the account menu: {missing}"
    )

    # The classic export's section titles and column headers, so a saved spreadsheet keeps
    # working across both interfaces.
    for heading in (
        "SUMMARY METRICS",
        "LOGIN ACTIVITY",
        "CONVERSATION ACTIVITY",
        "DOCUMENT ACTIVITY",
        "TOKEN USAGE",
    ):
        assert heading in stats_lib, f"The export no longer writes the {heading} section"
    for header in (
        "Conversations Created",
        "Conversations Deleted",
        "Documents Uploaded",
        "Documents Deleted",
        "Total Tokens",
    ):
        assert header in stats_lib, f"The export no longer writes the {header} column"

    print("Classic parity test passed!")
    return True


def test_account_menu_offers_one_destination():
    """The rail's user menu no longer sends people to the classic profile page."""
    print("Testing account menu...")

    sidebar = _read(V2_SRC / "components" / "layout" / "Sidebar.tsx")
    assert 'href="/profile"' not in sidebar, (
        "The account menu must not link to the classic profile page: Settings is the single "
        "destination for personal settings, and its Stats tab now carries the stats"
    )
    assert 'to="/settings"' in sidebar, "The account menu must still reach Settings"
    assert 'href="/logout"' in sidebar, "The account menu must still offer sign out"

    # The classic deep links inside the workspace tabs are a different thing: they are the
    # "open this in the classic UI" fallback for tabs V2 has not rebuilt, not navigation to
    # a profile, and they stay until those tabs exist.
    workspaces = _read(V2_SRC / "lib" / "workspaces.ts")
    assert "/profile?tab=" in workspaces, (
        "The workspace tabs' classic fallbacks were removed; those capabilities have no "
        "other route while the V2 tabs are unbuilt"
    )

    print("Account menu test passed!")
    return True


def test_charts_use_the_shared_vendored_runtime():
    """One loader, vendored bytes, nothing fetched from outside the application."""
    print("Testing chart runtime...")

    runtime = _read(V2_SRC / "lib" / "chartRuntime.ts")
    vendor_assets = _read(V2_SRC / "lib" / "vendorAssets.ts")
    chart_component = _read(V2_SRC / "components" / "settings" / "StatsChart.tsx")
    inline_chart = _read(V2_SRC / "components" / "chat" / "InlineChart.tsx")

    assert "chartJs: 'vendor/chartjs-" in vendor_assets, (
        "Chart.js must resolve to the vendored directory"
    )
    vendor_dir = re.search(r"chartJs: 'vendor/(chartjs-[\d.]+)/", vendor_assets)
    assert vendor_dir, "Could not read the vendored Chart.js directory name"
    assert (
        REPO_ROOT / "application" / "v2_ui" / "public" / "vendor" / vendor_dir.group(1)
    ).is_dir(), f"The vendored directory {vendor_dir.group(1)} does not exist"

    assert "VENDOR_PATHS.chartJs" in runtime
    # Both callers share the singleton, so whichever draws first pays for the script.
    for name, source in (("StatsChart", chart_component), ("InlineChart", inline_chart)):
        assert "loadChartRuntime" in source, f"{name} must use the shared loader"
        assert "loadVendorScript(VENDOR_PATHS.chartJs)" not in source, (
            f"{name} defines a second Chart.js loader; the point of the shared one is that "
            "the script is fetched and evaluated once"
        )

    # A chart that cannot be drawn must say so. An empty box reads as "no activity", which
    # is a different and much worse claim than "this failed to load".
    assert "could not be drawn" in chart_component, (
        "A failed chart load must be reported rather than left blank"
    )

    print("Chart runtime test passed!")
    return True


def test_version_is_at_least_implementation_version():
    """The application version is at or beyond the version that added this."""
    print("Testing application version...")
    assert_app_version_at_least("0.261.041")
    print("Application version test passed!")
    return True


if __name__ == "__main__":
    tests = [
        test_trend_fields_match_the_route,
        test_window_parameters_match_the_resolver,
        test_lifetime_totals_read_the_cached_metrics_block,
        test_every_classic_stats_surface_has_a_counterpart,
        test_account_menu_offers_one_destination,
        test_charts_use_the_shared_vendored_runtime,
        test_version_is_at_least_implementation_version,
    ]

    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            results.append(bool(test()))
        except Exception as exc:  # noqa: BLE001 - surface any failure with a traceback
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()
            results.append(False)

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
