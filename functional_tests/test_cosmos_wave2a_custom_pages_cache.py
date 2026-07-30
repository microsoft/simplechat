# test_cosmos_wave2a_custom_pages_cache.py
#!/usr/bin/env python3
"""
Functional test for Cosmos Wave 2A custom pages cache.
Version: 0.250.032
Implemented in: 0.250.006

This test ensures custom page catalog and navigation reads use shared cache
entries and that writes invalidate those entries with a shared version bump.
"""

import copy
import importlib
import os
import sys
import types


ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SINGLE_APP_DIR = os.path.join(ROOT_DIR, "application", "single_app")
if SINGLE_APP_DIR not in sys.path:
    sys.path.insert(0, SINGLE_APP_DIR)


class FakeCosmosError(Exception):
    def __init__(self, status_code, message):
        super().__init__(message)
        self.status_code = status_code


class FakeCosmosContainer:
    def __init__(self, items=None):
        self.items = {}
        self._etag_counter = 0
        for item_id, item_body in copy.deepcopy(items or {}).items():
            self.items[item_id] = self._copy_with_new_etag(item_body)

    def _copy_with_new_etag(self, body):
        self._etag_counter += 1
        item = copy.deepcopy(body)
        item["_etag"] = f"etag-{self._etag_counter}"
        return item

    def query_items(self, query, parameters=None, **kwargs):
        return [copy.deepcopy(item) for item in self.items.values()]

    def read_item(self, item, partition_key):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        return copy.deepcopy(self.items[item])

    def create_item(self, body):
        item_id = body["id"]
        if item_id in self.items:
            raise FakeCosmosError(409, f"Duplicate item {item_id}")
        self.items[item_id] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[item_id])

    def upsert_item(self, body):
        self.items[body["id"]] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[body["id"]])

    def replace_item(self, item, body, etag=None, match_condition=None, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        if etag and self.items[item].get("_etag") != etag:
            raise FakeCosmosError(412, f"ETag mismatch for item {item}")
        self.items[item] = self._copy_with_new_etag(body)
        return copy.deepcopy(self.items[item])

    def delete_item(self, item, partition_key, **kwargs):
        if item not in self.items:
            raise FakeCosmosError(404, f"Missing item {item}")
        del self.items[item]


def _page(slug, nav_order=10):
    return {
        "id": slug,
        "slug": slug,
        "title": slug.title(),
        "description": "",
        "enabled": True,
        "entry_type": "static",
        "access_level": "authenticated",
        "nav_label": slug.title(),
        "nav_icon": "bi-file-earmark-text",
        "nav_order": nav_order,
        "roles": [],
        "show_in_nav": True,
        "open_in_new_tab": False,
        "render_jinja": False,
        "html_file": f"{slug}.html",
        "css_files": [],
        "js_files": [],
        "asset_files": [],
        "json_files": [],
        "source": "cosmos",
    }


def _load_custom_pages_module(custom_pages_container, settings_container):
    fake_config = types.ModuleType("config")
    fake_config.cosmos_custom_pages_container = custom_pages_container
    fake_config.cosmos_settings_container = settings_container
    sys.modules["config"] = fake_config

    fake_appinsights = types.ModuleType("functions_appinsights")
    fake_appinsights.log_event = lambda *args, **kwargs: None
    sys.modules["functions_appinsights"] = fake_appinsights

    for module_name in [
        "functions_shared_cache",
        "app_settings_cache",
        "functions_custom_pages",
    ]:
        sys.modules.pop(module_name, None)
    return importlib.import_module("functions_custom_pages")


def test_custom_pages_catalog_cache_invalidates_on_version_bump():
    """A version bump should refresh the cached custom pages catalog."""
    custom_pages_container = FakeCosmosContainer({"alpha": _page("alpha")})
    settings_container = FakeCosmosContainer()
    custom_pages = _load_custom_pages_module(custom_pages_container, settings_container)

    first = custom_pages.list_cosmos_custom_pages()
    custom_pages_container.items["beta"] = _page("beta", nav_order=20)
    cached = custom_pages.list_cosmos_custom_pages()
    custom_pages.invalidate_custom_pages_cache(reason="test")
    refreshed = custom_pages.list_cosmos_custom_pages()

    assert [page["slug"] for page in first] == ["alpha"]
    assert [page["slug"] for page in cached] == ["alpha"]
    assert {page["slug"] for page in refreshed} == {"alpha", "beta"}


def test_custom_pages_save_invalidates_catalog_cache():
    """Saving a page should invalidate the catalog cache without a manual bump."""
    custom_pages_container = FakeCosmosContainer({"alpha": _page("alpha")})
    settings_container = FakeCosmosContainer()
    custom_pages = _load_custom_pages_module(custom_pages_container, settings_container)

    custom_pages.list_cosmos_custom_pages()
    custom_pages.save_custom_page(_page("beta", nav_order=20), user_id="admin")
    refreshed = custom_pages.list_cosmos_custom_pages()

    assert {page["slug"] for page in refreshed} == {"alpha", "beta"}


def test_custom_pages_nav_cache_uses_cached_navigation_until_invalidated():
    """Navigation cache should be role-aware and version invalidated."""
    custom_pages_container = FakeCosmosContainer({"alpha": _page("alpha")})
    settings_container = FakeCosmosContainer()
    custom_pages = _load_custom_pages_module(custom_pages_container, settings_container)
    settings = {
        "enable_custom_pages": True,
        "custom_pages_nav_cache_ttl_seconds": 60,
    }

    first_nav = custom_pages.get_custom_pages_nav(settings)
    custom_pages_container.items["beta"] = _page("beta", nav_order=20)
    cached_nav = custom_pages.get_custom_pages_nav(settings)
    custom_pages.invalidate_custom_pages_cache(reason="test_nav")
    refreshed_nav = custom_pages.get_custom_pages_nav(settings)

    assert [item["slug"] for item in first_nav] == ["alpha"]
    assert [item["slug"] for item in cached_nav] == ["alpha"]
    assert {item["slug"] for item in refreshed_nav} == {"alpha", "beta"}


if __name__ == "__main__":
    tests = [
        test_custom_pages_catalog_cache_invalidates_on_version_bump,
        test_custom_pages_save_invalidates_catalog_cache,
        test_custom_pages_nav_cache_uses_cached_navigation_until_invalidated,
    ]
    results = []
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
            results.append(True)
        except Exception as exc:
            print(f"Test failed: {exc}")
            results.append(False)

    sys.exit(0 if all(results) else 1)
