#!/usr/bin/env python3
# test_data_management_backup_cosmos_pagination.py
"""
Functional test for Cosmos backup source pagination and backup failure logging.
Version: 0.250.209
Implemented in: 0.250.209

This test ensures Cosmos backup source reads drain a single cross-partition
pager instead of replaying a continuation token against a rebuilt query, which
previously failed every container holding more than one page with
"BadRequest: Invalid Continuation Token". It also covers the bounded failure
reason rollup used for source blob backup logging and the sanitized diagnostic
text now retained in Application Insights log properties.
"""

import importlib.util
from pathlib import Path
import sys
import types

REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"
MODULE_PATH = APP_ROOT / "functions_data_management.py"
sys.path.insert(0, str(APP_ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_support.versioning import assert_app_version_at_least


class FakeCosmosBadRequest(Exception):
    """Mimic the non-retryable Cosmos error raised for replayed continuation tokens."""

    def __init__(self, message="(BadRequest) Invalid Continuation Token"):
        super().__init__(message)
        self.status_code = 400


class FakePageIterator:
    """Serve ordered pages and reject any attempt to resume from a token."""

    def __init__(self, pages, continuation_token=None):
        if continuation_token is not None:
            raise FakeCosmosBadRequest()
        self._pages = list(pages)
        self._index = 0
        self.continuation_token = "opaque-token"

    def __iter__(self):
        return self

    def __next__(self):
        if self._index >= len(self._pages):
            raise StopIteration
        page = self._pages[self._index]
        self._index += 1
        return list(page)


class FakeItemPaged:
    """Expose the by_page contract used by the production source reader."""

    def __init__(self, pages, call_log):
        self._pages = pages
        self._call_log = call_log

    def by_page(self, continuation_token=None):
        self._call_log.append(continuation_token)
        return FakePageIterator(self._pages, continuation_token=continuation_token)

    def __iter__(self):
        for page in self._pages:
            for item in page:
                yield item


class FakePagedContainer:
    """Return a paged query result and count how often the query is rebuilt."""

    def __init__(self, pages):
        self._pages = pages
        self.query_calls = 0
        self.by_page_tokens = []

    def query_items(self, **kwargs):
        self.query_calls += 1
        return FakeItemPaged(self._pages, self.by_page_tokens)


class FakeUnpagedContainer:
    """Model lightweight test doubles that do not implement Cosmos paging."""

    def __init__(self, items):
        self._items = items
        self.query_calls = 0

    def query_items(self, **kwargs):
        self.query_calls += 1
        return list(self._items)


ARTIFACT = {
    "name": "personal_conversations",
    "container_attr": "cosmos_conversations_container",
    "container_name_attr": "cosmos_conversations_container_name",
    "partition_key_path": "/id",
    "category": "conversations",
}


def load_data_management_module():
    """Load production backup helpers with stubbed infrastructure dependencies."""
    config_module = types.ModuleType("config")
    config_module.CLIENTS = {}
    config_module.VERSION = "0.250.209"
    config_module.cosmos_data_management_jobs_container = None
    config_module.cosmos_data_management_job_items_container = None
    config_module.cosmos_settings_container = None
    config_module.cosmos_conversations_container_name = "conversations"
    sys.modules["config"] = config_module

    appinsights_module = types.ModuleType("functions_appinsights")
    logged_events = []
    appinsights_module.log_event = (
        lambda message, extra=None, **_kwargs: logged_events.append((message, extra or {}))
    )
    sys.modules["functions_appinsights"] = appinsights_module

    throughput_module = types.ModuleType("functions_cosmos_throughput")

    class FakeCosmosThroughputError(Exception):
        pass

    throughput_module.CosmosThroughputError = FakeCosmosThroughputError
    throughput_module.get_container_throughput = lambda *_a, **_k: {}
    throughput_module.get_database_throughput = lambda *_a, **_k: {}
    throughput_module.set_database_throughput = lambda *_a, **_k: {}
    sys.modules["functions_cosmos_throughput"] = throughput_module

    module_name = "data_management_backup_pagination_test_module"
    spec = importlib.util.spec_from_file_location(module_name, MODULE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    assert spec and spec.loader
    spec.loader.exec_module(module)
    sys.modules.pop(module_name, None)
    module.logged_events = logged_events
    return module


def build_pages(page_count, page_size):
    """Build sequential Cosmos-shaped pages with unique ids per document."""
    pages = []
    for page_index in range(page_count):
        pages.append([
            {
                "id": f"doc-{page_index * page_size + offset:05d}",
                "_ts": 1700000000,
                "_etag": f"etag-{page_index}-{offset}",
                "payload": "value",
            }
            for offset in range(page_size)
        ])
    return pages


def test_multi_page_cosmos_source_drains_a_single_pager():
    """Containers larger than one page must stream fully without a token replay."""
    print("Testing Cosmos backup multi-page source reads...")
    try:
        module = load_data_management_module()
        page_size = module.DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE
        pages = build_pages(3, page_size)
        container = FakePagedContainer(pages)

        items = list(module._iter_backup_cosmos_source_items(
            container,
            ARTIFACT,
            {"cosmos_source_cutoff_epoch": 0},
        ))

        expected_count = 3 * page_size
        assert len(items) == expected_count, (
            f"Expected {expected_count} streamed items, got {len(items)}"
        )
        assert container.query_calls == 1, (
            f"Query must be built once, was built {container.query_calls} times"
        )
        assert container.by_page_tokens == [None], (
            f"by_page must never receive a continuation token, got {container.by_page_tokens}"
        )

        identities = {item["source_identity"] for item in items}
        assert len(identities) == expected_count, "Streamed items must be unique"

        print("Test passed!")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_cutoff_and_unpaged_fallback_still_stream():
    """The cutoff filter and non-paged test-double path must keep working."""
    print("Testing Cosmos backup cutoff filtering and unpaged fallback...")
    try:
        module = load_data_management_module()
        page_size = module.DATA_MANAGEMENT_BACKUP_MANIFEST_BATCH_SIZE

        pages = build_pages(2, page_size)
        pages[1][0]["_ts"] = 1900000000
        container = FakePagedContainer(pages)
        items = list(module._iter_backup_cosmos_source_items(
            container,
            ARTIFACT,
            {"cosmos_source_cutoff_epoch": 1800000000},
        ))
        assert len(items) == (2 * page_size) - 1, (
            f"Cutoff must drop exactly one item, got {len(items)}"
        )

        flat_items = [item for page in build_pages(2, page_size) for item in page]
        unpaged = FakeUnpagedContainer(flat_items)
        unpaged_items = list(module._iter_backup_cosmos_source_items(
            unpaged,
            ARTIFACT,
            {"cosmos_source_cutoff_epoch": 0},
        ))
        assert len(unpaged_items) == 2 * page_size, (
            f"Unpaged fallback must stream every item, got {len(unpaged_items)}"
        )

        print("Test passed!")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_failure_reason_rollup_is_bounded():
    """Per-item failures must collapse into a bounded, ordered log summary."""
    print("Testing backup failure reason rollup...")
    try:
        module = load_data_management_module()
        limit = module.DATA_MANAGEMENT_BACKUP_MAX_LOGGED_FAILURE_REASONS

        counts = {}
        for index in range(limit + 25):
            module._record_backup_failure_reason(counts, f"Failure kind {index}")
        for _ in range(5):
            module._record_backup_failure_reason(counts, "Failure kind 0")

        assert len(counts) <= limit + 1, (
            f"Distinct reasons must stay bounded, got {len(counts)}"
        )
        assert "Other backup failures." in counts, "Overflow reasons must be aggregated"
        assert counts["Failure kind 0"] == 6, (
            f"Repeat reasons must accumulate, got {counts['Failure kind 0']}"
        )

        summary = module._summarize_backup_failure_reasons(counts)
        rendered_counts = [int(entry.split("x ", 1)[0]) for entry in summary.split("; ")]
        assert rendered_counts == sorted(rendered_counts, reverse=True), (
            f"Summary must be ordered by frequency, got {summary!r}"
        )
        assert "25x Other backup failures." in summary, (
            f"Overflow bucket must be reported, got {summary!r}"
        )
        assert "6x Failure kind 0" in summary, (
            f"Repeat reason counts must be reported, got {summary!r}"
        )
        assert module._summarize_backup_failure_reasons({}) == "", (
            "Empty rollups must render as an empty string"
        )

        print("Test passed!")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_logger_extra_retains_sanitized_diagnostics():
    """App Insights properties must carry message text without leaking secrets."""
    print("Testing App Insights logger extras...")
    try:
        sys.modules.pop("functions_appinsights", None)
        sys.modules.setdefault("app_settings_cache", types.ModuleType("app_settings_cache"))
        import functions_appinsights

        extra = functions_appinsights._build_logger_extra(
            "[DATA_MANAGEMENT] Cosmos backup source page read failed.",
            {
                "job_id": "data_management_partial_20260817T0300Z",
                "container": "conversations",
                "status_code": 400,
                "error": "(BadRequest) Invalid Continuation Token",
                "api_key": "super-secret-value",
            },
        )

        assert "Cosmos backup source page read failed" in extra["sc_message"], (
            "Sanitized message text must reach App Insights"
        )
        assert extra["sc_error"] == "(BadRequest) Invalid Continuation Token", (
            f"Allowlisted diagnostics must retain text, got {extra.get('sc_error')!r}"
        )
        assert extra["sc_container"] == "conversations"
        assert extra["sc_status_code"] == 400
        assert extra["sc_api_key_present"] is True, "Sensitive keys must collapse to presence"
        assert "super-secret-value" not in str(extra), "Secret values must never be emitted"

        print("Test passed!")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


def test_version_is_at_least_fix_version():
    """The shipped app version must include this fix."""
    print("Testing config version floor...")
    try:
        assert_app_version_at_least("0.250.209")
        print("Test passed!")
        return True
    except Exception as exc:
        print(f"Test failed: {exc}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    tests = [
        test_multi_page_cosmos_source_drains_a_single_pager,
        test_cutoff_and_unpaged_fallback_still_stream,
        test_failure_reason_rollup_is_bounded,
        test_logger_extra_retains_sanitized_diagnostics,
        test_version_is_at_least_fix_version,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        results.append(test())

    print(f"\nResults: {sum(results)}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
