# test_v2_admin_scale_settings.py
"""
Browser coverage for the V2 Admin Settings Scale group.
Version: 0.261.274
Implemented in: 0.261.274

Exercise the built application with the real field schema and in-memory admin
APIs. Check that the Redis connection reads the way the server-rendered page does
-- the key field becomes the Key Vault secret name, and Key Vault is named as a
prerequisite that can be reached in one step -- that Redis Metrics and the Redis
Explorer load only when looked at and page with a cursor, that the Document Access
Index shows its diagnostics only while the debug flag is set, that every operation
which changes a production resource asks first and sends the request body V1 sends,
that a manual scale is confirmed against the target the server will choose, and
that a container policy edited in the workbench is saved with the page. Light and
dark, phone and desktop, at large text, without overflow or console errors.
"""

import copy
import re
import sys
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from v2_admin_settings import AdminSettingsFixture, connect_options  # noqa: E402,F401


pytestmark = pytest.mark.ui

SCALE_SECTIONS = {
    "security": ("keyvault-section",),
    "scale": (
        "redis-cache-section",
        "redis-monitoring-section",
        "conversation-cache-section",
        "document-access-index-section",
        "cosmos-maintenance-section",
        "cosmos-throughput-section",
        "cosmos-throughput-metrics-table-section",
    ),
}
ARTIFACTS = "v2_admin_scale"
SETTINGS_API = "/api/admin/settings"

REDIS_STATUS = {
    "checked_at": "2026-01-05T12:00:00+00:00",
    "configuration": {
        "enabled": True,
        "configured": True,
        "auth_type": "key",
        "service_type": "azure_managed_redis",
        "service_type_source": "setting",
        "port": 10000,
    },
    "runtime": {
        "app_cache_using_redis": True,
        "session_using_redis": False,
        "monitoring_source": "app_cache",
        "client_available": True,
    },
    "health": {"status": "healthy", "ping_success": True, "ping_latency_ms": 1.8, "last_error": None},
    "memory": {
        "used_memory": 12582912,
        "used_memory_human": "12M",
        "maxmemory": 1073741824,
        "maxmemory_human": "1G",
        "maxmemory_policy": "volatile-lru",
        "usage_percent": 1.17,
        "mem_fragmentation_ratio": 1.2,
    },
    "clients": {"connected_clients": 4},
    "stats": {
        "instantaneous_ops_per_sec": 12,
        "keyspace_hit_rate_percent": 91.2,
        "expired_keys": 10,
        "evicted_keys": 0,
        "rejected_connections": 0,
        "total_error_replies": 0,
    },
    "keyspace": {"total_keys": 3},
    "server": {"redis_version": "7.2.4"},
    "dai_cache": {"version_marker_count": 2, "version_marker_no_expiry_count": 0, "payload_key_count": 5},
}

EXPLORER_PAGES = {
    "0": {
        "success": True,
        "keys": [
            {
                "key": "simplechat:settings",
                "type": "string",
                "ttl_seconds": -1,
                "memory_usage_bytes": 2048,
                "resolution": {
                    "kind": "settings",
                    "label": "Shared settings",
                    "resolved": True,
                    "entity_type": "app_settings",
                    "entity_name": "SimpleChat settings",
                },
            },
            {"key": "session:abc123", "type": "string", "ttl_seconds": 3600, "preview_restricted": True},
        ],
        "next_cursor": "17",
        "has_more": True,
    },
    "17": {
        "success": True,
        "keys": [{"key": "simplechat:gone", "type": "string", "ttl_seconds": 30}],
        "next_cursor": "0",
        "has_more": False,
    },
}

DAI_STATUS = {
    "state": {
        "status": "in_progress",
        "current_source_scope": "group:alpha",
        "completed_source_scopes": ["personal"],
        "total_documents_processed": 1200,
        "total_documents_failed": 0,
        "total_rows_upserted": 2400,
        "total_rows_deleted": 3,
        "last_completed_at": "2026-01-05T11:00:00+00:00",
        "last_error": None,
    },
    "settings": {
        "container_enabled": True,
        "write_through_enabled": True,
        "reads_enabled": True,
        "cache_enabled": True,
        "cache_ttl_seconds": 900,
        "shadow_validation_enabled": False,
    },
    "maintenance": {
        "auto_maintenance_enabled": True,
        "next_action": "backfill",
        "has_more_work": True,
        "active_interval_seconds": 60,
    },
    "read_metrics": {
        "windows": {
            "15m": {
                "sample_count": 40,
                "served_from_index_count": 38,
                "source_fallback_count": 2,
                "fallback_rate_percent": 5,
                "request_charge": 12.5,
                "elapsed_ms_avg": 18.2,
                "elapsed_ms_p95": 40.1,
            },
        },
    },
    "cache_metrics": {
        "windows": {
            "15m": {"hit_rate_percent": 75, "hit_count": 30, "miss_count": 10, "invalidation_count": 4},
        },
    },
    "repair_required_count": 0,
}

MAINTENANCE_STATUS = {
    "success": True,
    "document_access_index_backfill": DAI_STATUS,
    "conversation_cache": {
        "settings": {"enabled": True, "ttl_seconds": 120},
        "metrics": {
            "windows": {
                "15m": {
                    "hit_rate_percent": 82.5,
                    "hit_count": 33,
                    "miss_count": 7,
                    "write_count": 7,
                    "invalidation_count": 2,
                    "operation_counts": {"list": 30, "feed": 10},
                },
            },
        },
    },
    "cosmos_indexing_policies": {
        "mode": "dry_run",
        "container_count": 24,
        "containers_missing_expected_indexes": 2,
        "updated_container_count": 0,
        "failed_container_count": 0,
        "evaluated_at": "2026-01-05T09:00:00+00:00",
    },
    "stale_cache_cleanup": {"status": "not_run"},
}

THROUGHPUT_STATUS = {
    "configured": True,
    "resource": {
        "subscription_id": "00000000-0000-0000-0000-000000000000",
        "resource_group": "simplechat-rg",
        "account_name": "simplechat-cosmos",
        "database_name": "SimpleChat",
    },
    "throughput": {"scope": "database", "mode": "manual", "current_ru": 4000, "is_scalable": True},
    "capacity_scope": "database",
    "metrics": {"window_minutes": 5, "normalized_ru_percent": 42.5, "total_request_units": 120000},
    "containers": [
        {
            "container_name": "conversations",
            "mode": "autoscale",
            "current_ru": 4000,
            "is_scalable": True,
            "normalized_ru_percent": 63.2,
            "request_units": 400000,
            # The status carries each container's resolved policy, as get_container_policy builds it.
            "policy": {"container_name": "conversations", "enabled": True, "min_ru": 2000, "max_ru": 8000},
        },
        # Azure Monitor sent no percentage, so utilization is estimated from request units.
        # No policy either: a container discovered after the policies were saved.
        {"container_name": "documents", "mode": "manual", "current_ru": 1000, "is_scalable": True, "request_units": 90000},
        {"container_name": "settings", "mode": None, "current_ru": None, "is_scalable": False},
        {
            "container_name": "archive",
            "mode": "autoscale",
            "current_ru": 20000,
            "is_scalable": True,
            "portal_managed_scaling_required": True,
        },
    ],
    "last_checked_at": "2026-01-05T12:00:00+00:00",
}


class ScaleApi:
    """The Scale group's admin APIs, answered in memory, with every call recorded."""

    def __init__(self, fixture):
        self.calls = []
        self.redis_status = copy.deepcopy(REDIS_STATUS)
        self.maintenance = copy.deepcopy(MAINTENANCE_STATUS)
        self.throughput = copy.deepcopy(THROUGHPUT_STATUS)
        # A held status read stands in for Azure Resource Manager and Azure Monitor taking
        # several seconds, which is when a second click could otherwise send a second change.
        self.hold_status = False
        self.held_status = []
        fixture.extra_routes.update({
            ("GET", f"{SETTINGS_API}/redis-monitoring/status"): self._redis_status,
            ("GET", f"{SETTINGS_API}/redis-explorer/keys"): self._explorer_keys,
            ("POST", f"{SETTINGS_API}/redis-explorer/value"): self._explorer_value,
            ("GET", f"{SETTINGS_API}/app-maintenance/status"): self._maintenance_status,
            ("POST", f"{SETTINGS_API}/app-maintenance/run"): self._maintenance_run,
            ("GET", f"{SETTINGS_API}/cosmos-throughput/status"): self._throughput_status,
            ("POST", f"{SETTINGS_API}/cosmos-throughput/validate-access"): self._validate_access,
            ("POST", f"{SETTINGS_API}/cosmos-throughput/scale"): self._scale,
            ("POST", f"{SETTINGS_API}/cosmos-throughput/convert-autoscale"): self._convert,
            ("POST", "/api/v2/admin/settings/test-connection"): self._test_connection,
        })

    def _record(self, route):
        request = route.request
        parsed = urlsplit(request.url)
        body = request.post_data_json if request.method == "POST" else None
        self.calls.append({
            "method": request.method,
            "path": parsed.path,
            "query": {
                key: values[0]
                for key, values in parse_qs(parsed.query, keep_blank_values=True).items()
            },
            "body": body,
        })
        return body

    def calls_to(self, suffix):
        return [call for call in self.calls if call["path"].endswith(suffix)]

    def _redis_status(self, route):
        self._record(route)
        route.fulfill(json=self.redis_status)

    def _explorer_keys(self, route):
        self._record(route)
        cursor = self.calls[-1]["query"].get("cursor", "0")
        route.fulfill(json=EXPLORER_PAGES[cursor])

    def _explorer_value(self, route):
        key = self._record(route)["key"]
        if key == "simplechat:gone":
            # A key that expired after the page listed it, as get_redis_explorer_value reports it.
            route.fulfill(status=404, json={
                "success": False,
                "status": "not_found",
                "key": key,
                "type": "none",
                "preview": "Redis key was not found.",
            })
            return
        route.fulfill(json={
            "success": True,
            "key": key,
            "type": "string",
            "ttl_seconds": -1,
            "memory_usage_bytes": 2048,
            "preview": '{\n  "enable_redis_cache": true\n}',
            "redacted": True,
            "truncated": False,
            "preview_restricted": False,
            "resolution": EXPLORER_PAGES["0"]["keys"][0]["resolution"],
        })

    def _maintenance_status(self, route):
        self._record(route)
        route.fulfill(json=self.maintenance)

    def _maintenance_run(self, route):
        body = self._record(route)
        steps = []
        if body.get("run_document_access_index_backfill"):
            current = copy.deepcopy(DAI_STATUS)
            current["state"]["status"] = "completed"
            steps.append({"name": "document_access_index_backfill", "results": {"current_status": current}})
        if body.get("apply_cosmos_indexing_policies"):
            steps.append({
                "name": "cosmos_indexing_policy_maintenance",
                "results": {**MAINTENANCE_STATUS["cosmos_indexing_policies"], "updated_container_count": 2},
            })
        if body.get("run_stale_cache_cleanup"):
            applied = bool(body.get("apply_stale_cache_cleanup"))
            steps.append({
                "name": "stale_cache_document_cleanup",
                "results": {
                    "status": "completed" if applied else "dry_run_completed",
                    "mode": "apply" if applied else "dry_run",
                    "candidate_count": 3,
                    "deleted_count": 3 if applied else 0,
                    "failed_count": 0,
                    "has_more_candidates": False,
                    "categories": [{"category": "conversation_cache", "candidate_count": 3, "deleted_count": 3 if applied else 0}],
                },
            })
        route.fulfill(json={"success": True, "steps": steps})

    def _throughput_status(self, route):
        self._record(route)
        if self.hold_status:
            self.held_status.append(route)
            return
        route.fulfill(json=self.throughput)

    def release_status(self):
        """Answer held status reads, as a slow Azure read finishing would."""
        self.hold_status = False
        while self.held_status:
            self.held_status.pop(0).fulfill(json=self.throughput)

    def _validate_access(self, route):
        self._record(route)
        # Validation reads Azure with the values on screen; here they name a draft target
        # running at 8,000 RU/s, which must not stand in for the saved database's status.
        draft_status = copy.deepcopy(THROUGHPUT_STATUS)
        draft_status["throughput"]["current_ru"] = 8000
        route.fulfill(json={
            "success": True,
            "message": "Cosmos throughput access is ready.",
            "checks": [
                {"name": "configuration", "label": "Resource configuration", "passed": True, "message": "Configured."},
                {"name": "throughput", "label": "Throughput read", "passed": True, "message": "Read 8,000 RU/s."},
            ],
            "status": draft_status,
        })

    def _scale(self, route):
        body = self._record(route)
        route.fulfill(json={
            "success": True,
            "scope": "container" if body.get("container_name") else "database",
            "container_name": body.get("container_name") or "",
            "from_ru": 4000,
            "to_ru": 5000,
        })

    def _convert(self, route):
        body = self._record(route)
        route.fulfill(json={"success": True, "container_name": body.get("container_name") or "", "from_ru": 1000, "to_ru": 1000})

    def _test_connection(self, route):
        self._record(route)
        route.fulfill(json={"message": "Redis connection successful."})


@pytest.fixture
def scale_ui(page):
    fixture = AdminSettingsFixture(page, sections=SCALE_SECTIONS, validate_updates=True)
    fixture.api = ScaleApi(fixture)
    fixture.settings.update({
        "enable_redis_cache": True,
        "redis_url": "simplechat.redis.cache.windows.net",
        "redis_key": "***REDACTED***",
        # The saved guardrails a manual scale is estimated from.
        "cosmos_throughput_min_ru": 2000,
        "cosmos_throughput_max_ru": 6000,
        "cosmos_throughput_cached_status": copy.deepcopy(THROUGHPUT_STATUS),
        "cosmos_throughput_container_policies": {},
    })
    page.emulate_media(reduced_motion="reduce")
    yield fixture
    fixture.assert_clean()


def _region(page, name):
    return page.get_by_role("region", name=name, exact=True)


def _group_toggle(region, label):
    return region.get_by_role("button", name=re.compile(f"^{re.escape(label)}"))


def _open_group(region, label):
    """Expand a settings group; a configured section starts with its groups closed."""
    toggle = _group_toggle(region, label)
    if toggle.get_attribute("aria-expanded") == "false":
        toggle.click()
    expect(toggle).to_have_attribute("aria-expanded", "true")


def _readout(scope, label):
    """The value beside a readout label."""
    return scope.locator(f"xpath=.//div[dt[normalize-space()='{label}']]/dd[1]").first


def _schema_label(fixture, section_id, key):
    return next(field["label"] for field in fixture.schema[section_id] if field.get("key") == key)


def _connection_test_label(fixture):
    return next(
        field["label"] for field in fixture.schema["redis-cache-section"] if field.get("component") == "connection-test"
    )


def test_the_redis_key_follows_the_authentication_type(scale_ui):
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    redis = _region(page, "Redis Cache")
    key_label = _schema_label(scale_ui, "redis-cache-section", "redis_key")
    auth_label = _schema_label(scale_ui, "redis-cache-section", "redis_auth_type")
    _open_group(redis, "Connection")

    expect(redis.get_by_label(key_label, exact=True)).to_be_visible()
    expect(redis.get_by_text("Key Vault secret storage")).to_have_count(0)

    redis.get_by_label(auth_label, exact=True).select_option("key_vault")
    expect(redis.get_by_label("Key Vault Secret Name", exact=True)).to_be_visible()
    expect(redis.get_by_label(key_label, exact=True)).to_have_count(0)
    # The prerequisite appears where it is felt, and Key Vault names what relies on it.
    expect(redis).to_contain_text("Key Vault secret storage")
    expect(_region(page, "Key Vault")).to_contain_text("Redis Cache")
    scale_ui.capture("redis-key-vault", ARTIFACTS)

    redis.get_by_label(auth_label, exact=True).select_option("managed_identity")
    expect(redis.get_by_label("Key Vault Secret Name", exact=True)).to_have_count(0)
    expect(redis.get_by_label(key_label, exact=True)).to_have_count(0)


def test_redis_metrics_load_when_seen_and_the_explorer_pages(scale_ui):
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    api = scale_ui.api
    metrics = _region(page, "Redis Metrics")
    metrics.scroll_into_view_if_needed()

    expect(_readout(metrics, "Health")).to_contain_text("Healthy")
    expect(_readout(metrics, "Memory usage")).to_contain_text("12M / 1G")
    assert len(api.calls_to("/redis-monitoring/status")) == 1
    # Browsing keys is a separate decision; nothing is listed until it is opened.
    assert not api.calls_to("/redis-explorer/keys")

    metrics.get_by_role("button", name=re.compile("^Redis Explorer")).click()
    keys = metrics.get_by_role("list", name="Redis keys")
    expect(keys.get_by_role("button", name=re.compile("simplechat:settings"))).to_be_visible()
    assert api.calls_to("/redis-explorer/keys")[-1]["query"] == {"cursor": "0", "page_size": "25", "filter": ""}

    metrics.get_by_role("button", name="Next").click()
    expect(keys.get_by_role("button", name=re.compile("simplechat:gone"))).to_be_visible()
    assert api.calls_to("/redis-explorer/keys")[-1]["query"]["cursor"] == "17"

    # A key that expired since it was listed explains itself, as on the classic page.
    keys.get_by_role("button", name=re.compile("simplechat:gone")).click()
    expect(metrics.get_by_text("Redis key was not found.")).to_be_visible()

    metrics.get_by_role("button", name="Previous").click()
    expect(keys.get_by_role("button", name=re.compile("simplechat:settings"))).to_be_visible()
    assert api.calls_to("/redis-explorer/keys")[-1]["query"]["cursor"] == "0"

    keys.get_by_role("button", name=re.compile("simplechat:settings")).click()
    expect(metrics.get_by_label("Sanitized preview")).to_contain_text("enable_redis_cache")
    expect(_readout(metrics, "Sanitization")).to_have_text("Redacted")
    assert api.calls_to("/redis-explorer/value")[-1]["body"] == {"key": "simplechat:settings"}
    scale_ui.capture("redis-explorer", ARTIFACTS)

    # Chromium logs the deliberate 404 above as a console error. It is the scenario under
    # test, so exactly that entry is allowed; anything else still fails the test.
    expected = "Failed to load resource: the server responded with a status of 404 (Not Found)"
    assert scale_ui.errors.count(expected) == 1, scale_ui.errors
    scale_ui.errors.remove(expected)


def test_a_passing_connection_test_refreshes_redis_metrics(scale_ui):
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    api = scale_ui.api
    metrics = _region(page, "Redis Metrics")
    metrics.scroll_into_view_if_needed()
    expect(_readout(metrics, "Health")).to_contain_text("Healthy")

    redis = _region(page, "Redis Cache")
    _open_group(redis, "Connection")
    # A passing test means the metrics on screen may be out of date, so they are read again.
    with page.expect_request(lambda request: request.url.endswith("/redis-monitoring/status")):
        redis.get_by_role("button", name=_connection_test_label(scale_ui)).click()
    expect(redis.get_by_role("status")).to_contain_text("Redis connection successful.")
    test = api.calls_to("/test-connection")[-1]["body"]
    assert test["test_type"] == "redis"
    assert test["endpoint"] == "simplechat.redis.cache.windows.net"
    # The stored key travels as its placeholder; the server swaps it back.
    assert test["key"] == "***REDACTED***"
    assert len(api.calls_to("/redis-monitoring/status")) == 2


def test_redis_metrics_stay_quiet_while_redis_is_off(scale_ui):
    scale_ui.settings["enable_redis_cache"] = False
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    metrics = _region(scale_ui.page, "Redis Metrics")
    metrics.scroll_into_view_if_needed()
    expect(metrics.get_by_text("Nothing to monitor yet")).to_be_visible()
    expect(metrics).to_contain_text("Redis Cache")
    assert not scale_ui.api.calls_to("/redis-monitoring/status")


def test_index_diagnostics_need_the_debug_flag(scale_ui):
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    index = _region(page, "DAI Metrics")
    index.scroll_into_view_if_needed()

    expect(_readout(index, "Read path")).to_contain_text("Always on")
    expect(index.get_by_role("button", name="Run one backfill batch")).to_have_count(0)
    # V1 renders the diagnostics only while enable_dai_debug is set; so does V2.
    expect(_group_toggle(index, "Automatic maintenance and diagnostics")).to_have_count(0)
    expect(index.get_by_text("Diagnostics are showing")).to_have_count(0)


def test_index_diagnostics_reset_asks_first(scale_ui):
    # Document Access Index diagnostics, switched on under Operations > Debug Logging.
    scale_ui.settings["enable_dai_debug"] = True
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    api = scale_ui.api
    index = _region(page, "DAI Metrics")
    index.scroll_into_view_if_needed()

    _open_group(index, "Automatic maintenance and diagnostics")
    shadow_label = _schema_label(scale_ui, "document-access-index-section", "enable_document_access_index_shadow_validation")
    expect(index.get_by_text(shadow_label, exact=True)).to_be_visible()

    index.get_by_role("button", name="Reset checkpoint").click()
    dialog = page.get_by_role("dialog", name="Reset document access backfill")
    expect(dialog).to_be_visible()
    assert not api.calls_to("/app-maintenance/run"), "Nothing runs before it is confirmed."
    scale_ui.capture("dai-reset-confirm", ARTIFACTS)

    dialog.get_by_role("button", name="Reset and run batch").click()
    expect(dialog).to_have_count(0)
    assert api.calls_to("/app-maintenance/run")[-1]["body"] == {
        "apply_cosmos_indexing_policies": False,
        "run_document_access_index_backfill": True,
        "reset_document_access_index_backfill": True,
    }
    expect(_readout(index, "Backfill state")).to_contain_text("Completed")


def test_maintenance_changes_ask_first_and_send_the_v1_requests(scale_ui):
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    api = scale_ui.api
    maintenance = _region(page, "Cosmos Maintenance")
    maintenance.scroll_into_view_if_needed()
    expect(_readout(maintenance, "Missing expected indexes")).to_have_text("2")

    # A dry run changes nothing, so it runs at once.
    maintenance.get_by_role("button", name="Dry run cleanup").click()
    expect(maintenance).to_contain_text("dry run found 3 candidate document(s)")
    assert api.calls_to("/app-maintenance/run")[-1]["body"] == {
        "apply_cosmos_indexing_policies": False,
        "run_document_access_index_backfill": False,
        "run_stale_cache_cleanup": True,
        "apply_stale_cache_cleanup": False,
    }

    maintenance.get_by_role("button", name="Delete stale cache docs").click()
    dialog = page.get_by_role("dialog", name="Delete stale cache documents")
    expect(dialog).to_be_visible()
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_have_count(0)
    assert len(api.calls_to("/app-maintenance/run")) == 1, "Cancel must not delete anything."

    maintenance.get_by_role("button", name="Apply missing indexes").click()
    dialog = page.get_by_role("dialog", name="Apply missing Cosmos indexes")
    dialog.get_by_role("button", name="Apply indexes").click()
    expect(dialog).to_have_count(0)
    assert api.calls_to("/app-maintenance/run")[-1]["body"] == {
        "apply_cosmos_indexing_policies": True,
        "run_document_access_index_backfill": False,
        "run_stale_cache_cleanup": False,
    }
    expect(maintenance).to_contain_text("Index updates were submitted for 2 container(s).")


def test_validate_access_checks_the_values_on_screen(scale_ui):
    scale_ui.settings["cosmos_throughput_autoscale_enabled"] = True
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    throughput = _region(page, "Cosmos DB Throughput")
    throughput.scroll_into_view_if_needed()
    # The saved snapshot is shown at once, so nothing is read on arrival.
    expect(_readout(throughput, "Current RU/s")).to_contain_text("4,000")
    expect(throughput.get_by_text("Saved snapshot")).to_be_visible()
    assert not scale_ui.api.calls_to("/cosmos-throughput/status")

    account_label = _schema_label(scale_ui, "cosmos-throughput-section", "cosmos_throughput_account_name")
    _open_group(throughput, "Cosmos resource")
    throughput.get_by_label(account_label, exact=True).fill("draft-account")
    throughput.get_by_role("button", name="Validate access").click()
    expect(throughput).to_contain_text("Passed: Resource configuration.")
    body = scale_ui.api.calls_to("/validate-access")[-1]["body"]
    assert body["cosmos_throughput_account_name"] == "draft-account"
    assert body["cosmos_throughput_min_ru"] == 2000
    assert scale_ui.patches == [], "Validation must not save anything."

    # What validation read describes the draft target. A manual change still starts from
    # the saved database's status, because that is what the server will change.
    expect(_readout(throughput, "Current RU/s")).to_contain_text("4,000")
    throughput.get_by_role("group", name="Database capacity actions").get_by_role("button", name="Scale up").click()
    dialog = scale_ui.page.get_by_role("dialog", name="Scale throughput up")
    expect(dialog).to_contain_text("from 4,000 RU/s to about 5,000 RU/s")
    dialog.get_by_role("button", name="Cancel").click()
    expect(dialog).to_have_count(0)
    assert not scale_ui.api.calls_to("/cosmos-throughput/scale")


def test_a_manual_scale_is_confirmed_against_its_target(scale_ui):
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    api = scale_ui.api
    throughput = _region(page, "Cosmos DB Throughput")
    throughput.scroll_into_view_if_needed()

    throughput.get_by_role("group", name="Database capacity actions").get_by_role("button", name="Scale up").click()
    dialog = page.get_by_role("dialog", name="Scale throughput up")
    expect(dialog).to_contain_text("from 4,000 RU/s to about 5,000 RU/s")
    expect(dialog).to_contain_text("6,000 RU/s maximum")
    assert not api.calls_to("/cosmos-throughput/scale"), "Nothing changes before it is confirmed."
    scale_ui.capture("scale-confirm", ARTIFACTS)

    # The change is sent once. Until the new status is read the dialog holds, so a second
    # click cannot send another step from the capacity this one replaced.
    api.hold_status = True
    confirm = dialog.get_by_role("button", name="Scale up")
    with page.expect_request(lambda request: request.url.endswith("/cosmos-throughput/status")):
        confirm.click()
    expect(dialog).to_be_visible()
    expect(confirm).to_be_disabled()
    api.release_status()
    expect(dialog).to_have_count(0)
    assert [call["body"] for call in api.calls_to("/cosmos-throughput/scale")] == [
        {"direction": "up", "container_name": ""},
    ]
    expect(throughput).to_contain_text("changed from 4,000 RU/s to 5,000 RU/s")
    # The outcome is followed by a live reading.
    assert len(api.calls_to("/cosmos-throughput/status")) == 1


def test_a_container_policy_is_edited_in_place_and_saved_with_the_page(scale_ui):
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    page = scale_ui.page
    metrics = _region(page, "Cosmos Metrics")
    metrics.scroll_into_view_if_needed()

    containers = metrics.get_by_role("list", name="Cosmos containers")
    expect(containers.get_by_role("button")).to_have_count(4)
    expect(containers.get_by_role("button", name=re.compile("^conversations"))).to_contain_text("2,000-8,000 RU/s")
    # A shared or monitor-only container says so once, with no policy of its own.
    archive = containers.get_by_role("button", name=re.compile("^archive"))
    expect(archive.get_by_text("Monitor only")).to_have_count(1)
    expect(containers.get_by_role("button", name=re.compile("^settings"))).not_to_contain_text(
        re.compile(r"[\d,]+-[\d,]+ RU/s")
    )

    documents = containers.get_by_role("button", name=re.compile("^documents"))
    expect(documents).to_contain_text("est.")
    documents.click()
    expect(metrics.get_by_role("heading", name="documents", level=3)).to_be_visible()

    # With no policy of its own, the form starts from the global policy that governs it.
    form = metrics.get_by_test_id("cosmos-container-policy-form")
    expect(form.get_by_label("Scale up at", exact=True)).to_have_value("90")
    expect(form.get_by_label("Minimum", exact=True)).to_have_value("2000")
    expect(form.get_by_label("Maximum", exact=True)).to_have_value("6000")

    # Typed a key at a time, as a person types. Nothing rounds or clamps a half-typed
    # number, and clearing a field does not commit 0 on the way.
    minimum = form.get_by_label("Minimum", exact=True)
    minimum.fill("")
    minimum.press_sequentially("3000")
    expect(minimum).to_have_value("3000")
    interval = form.get_by_role("group", name="Scale up").get_by_label("Interval", exact=True)
    interval.fill("")
    interval.press_sequentially("30")
    expect(interval).to_have_value("30")
    interval.blur()
    expect(minimum).to_have_value("3000")
    expect(interval).to_have_value("30")
    expect(documents).to_contain_text("Unsaved")
    scale_ui.capture("container-policy", ARTIFACTS)

    page.get_by_role("button", name="Save changes", exact=True).click()
    expect(page.get_by_role("button", name="Save changes", exact=True)).to_have_count(0)
    saved = scale_ui.patches[-1]["cosmos_throughput_container_policies"]["documents"]
    # The whole policy is staged, as the classic page stages it, so nothing is left implicit.
    assert (saved["min_ru"], saved["max_ru"], saved["scale_up_threshold_percent"]) == (3000, 6000, 90)
    assert saved["scale_up_cooldown_minutes"] == 30
    assert saved["container_name"] == "documents"
    stored = scale_ui.settings["cosmos_throughput_container_policies"]["documents"]
    assert stored["max_ru"] == 6000 and stored["min_ru"] == 3000

    # Shared and portal-managed containers have nothing to edit.
    containers.get_by_role("button", name=re.compile("^settings")).click()
    expect(form).to_have_count(0)
    containers.get_by_role("button", name=re.compile("^archive")).click()
    expect(metrics.get_by_role("group", name="Capacity actions for archive").get_by_role("button", name="Scale up")).to_be_disabled()


def test_an_enforced_global_policy_locks_container_policies(scale_ui):
    scale_ui.settings["cosmos_throughput_enforce_container_defaults"] = True
    scale_ui.open(width=1920, height=1080, ready_region="Redis Cache")
    metrics = _region(scale_ui.page, "Cosmos Metrics")
    metrics.scroll_into_view_if_needed()
    expect(metrics).to_contain_text("Global policy is enforced")
    metrics.get_by_role("list", name="Cosmos containers").get_by_role("button", name=re.compile("^conversations")).click()
    expect(metrics.get_by_test_id("cosmos-container-policy-form")).to_have_count(0)
    expect(metrics.get_by_role("button", name="Apply global policy to all")).to_have_count(0)


@pytest.mark.parametrize("theme", ["light", "dark"])
@pytest.mark.parametrize("width,font_size", [(390, "m"), (1920, "xl")])
def test_the_scale_group_never_overflows(scale_ui, theme, width, font_size):
    # Document Access Index diagnostics, switched on under Operations > Debug Logging.
    scale_ui.settings["enable_dai_debug"] = True
    scale_ui.open(theme=theme, width=width, font_size=font_size, ready_region="Redis Cache")
    page = scale_ui.page
    for name in ("Redis Metrics", "DAI Metrics", "Cosmos Maintenance", "Cosmos DB Throughput", "Cosmos Metrics"):
        region = _region(page, name)
        region.scroll_into_view_if_needed()
        expect(region).to_be_visible()
    metrics = _region(page, "Redis Metrics")
    metrics.get_by_role("button", name=re.compile("^Redis Explorer")).click()
    expect(metrics.get_by_role("list", name="Redis keys")).to_be_visible()

    assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    for region in page.locator(".admin-settings-distinct").all():
        overflow = region.evaluate("element => element.scrollWidth - element.clientWidth")
        assert overflow <= 1, f"A Scale card overflows by {overflow}px at {width}px/{font_size}/{theme}"
    scale_ui.capture(f"responsive-{theme}-{width}-{font_size}", ARTIFACTS)
