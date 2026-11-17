# test_custom_pages_cosmos_sdk_responses.py
#!/usr/bin/env python3
"""
Functional test for the custom page storage owners against SDK-shaped Cosmos responses.
Version: 0.261.448
Implemented in: 0.261.448

The pinned azure-cosmos SDK answers a point read or an upsert with a ``CosmosDict`` and a query
with plain dictionaries. functions_custom_pages reads those responses through Mapping access and
returns freshly built plain metadata, so nothing downstream receives the SDK wrapper or the
service's underscore fields.

This test ensures that the real get, save, list and delete owners keep that contract when the
container answers the way Cosmos does, and that they report a missing page instead of failing.
It is the owner-runtime evidence the Cosmos response boundary inventory asks for after the module
changed to support the V2 embed mode.
"""

import copy
import importlib
import json
import os
import sys
from contextlib import contextmanager
from pathlib import Path

from azure.cosmos import exceptions
from azure.cosmos._cosmos_responses import CosmosDict

TESTS = Path(__file__).resolve().parent
APP = TESTS.parent / "application" / "single_app"
sys.path.insert(0, str(TESTS))

from test_support.app_stubs import stubbed_config  # noqa: E402


def _document(slug, **overrides):
    body = {
        "id": slug, "slug": slug, "title": slug.title(), "description": "", "enabled": True,
        "entry_type": "static", "access_level": "app_user", "nav_label": slug.title(),
        "nav_icon": "bi-file-earmark-text", "nav_order": 10, "roles": [], "show_in_nav": True,
        "open_in_new_tab": False, "render_jinja": False, "html_file": f"{slug}.html",
        "css_files": [], "js_files": [], "asset_files": [], "json_files": [], "source": "cosmos",
    }
    body.update(overrides)
    return body


class SdkShapedCustomPagesContainer:
    """Stores documents as Cosmos answers: SDK dictionaries for points, plain rows for queries."""

    def __init__(self, documents=None):
        self.documents = {}
        self.point_responses = []
        self.upsert_bodies = []
        self.deleted = []
        for slug, body in (documents or {}).items():
            self.documents[slug] = self._stored(body)

    @staticmethod
    def _stored(body):
        return {**copy.deepcopy(body), "_rid": "rid", "_self": "self", "_etag": '"etag"', "_attachments": "a/", "_ts": 1}

    def _point(self, body):
        response = CosmosDict(copy.deepcopy(body), response_headers={})
        self.point_responses.append(response)
        return response

    def query_items(self, query, enable_cross_partition_query=None, **kwargs):
        if getattr(self, "missing", False):
            raise exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found.")
        return iter([copy.deepcopy(body) for body in self.documents.values()])

    def read_item(self, item, partition_key):
        if partition_key != item or item not in self.documents:
            raise exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found.")
        return self._point(self.documents[item])

    def upsert_item(self, body):
        self.upsert_bodies.append(body)
        self.documents[body["id"]] = self._stored(body)
        return self._point(self.documents[body["id"]])

    def delete_item(self, item, partition_key):
        if partition_key != item or item not in self.documents:
            raise exceptions.CosmosResourceNotFoundError(status_code=404, message="Not found.")
        del self.documents[item]
        self.deleted.append(item)


@contextmanager
def custom_pages_with(container):
    """Import functions_custom_pages against the container, count its invalidations, forget it after."""
    before = set(sys.modules)
    with stubbed_config(cosmos_custom_pages_container=container, cosmos_settings_container=object()):
        try:
            pages = importlib.import_module("functions_custom_pages")
            invalidations = []
            pages.invalidate_custom_pages_cache = lambda reason="": invalidations.append(reason)
            yield pages, invalidations
        finally:
            for name in set(sys.modules) - before:
                module_file = getattr(sys.modules.get(name), "__file__", None) or ""
                if module_file.startswith(str(APP)):
                    sys.modules.pop(name, None)


def test_get_custom_page_reads_an_sdk_point_response_into_plain_metadata():
    container = SdkShapedCustomPagesContainer({"alpha": _document("alpha")})
    with custom_pages_with(container) as (pages, _):
        found = pages.get_custom_page("alpha", include_python=False, use_cache=False)
        missing = pages.get_custom_page("beta", include_python=False, use_cache=False)

    assert type(container.point_responses[0]) is CosmosDict, "The double must answer like the SDK"
    assert type(found) is dict, "The page handed on is plain metadata, not the SDK wrapper"
    assert found["slug"] == "alpha" and found["source"] == "cosmos"
    assert not [key for key in found if key.startswith("_")], "The service's own fields are dropped"
    assert json.loads(json.dumps(found)) == found
    assert missing is None, "A page that does not exist is reported as missing, not as an error"


def test_save_custom_page_returns_plain_metadata_from_an_sdk_upsert_response():
    container = SdkShapedCustomPagesContainer({"alpha": _document("alpha")})
    with custom_pages_with(container) as (pages, invalidations):
        saved = pages.save_custom_page(_document("alpha", title="Renamed"), user_id="admin")
        created = pages.save_custom_page(_document("gamma"), user_id="admin")
        try:
            pages.save_custom_page(_document("bad", html_file="../outside.html"), user_id="admin")
            rejected = False
        except ValueError:
            rejected = True

    assert type(saved) is dict and saved["title"] == "Renamed"
    assert not [key for key in saved if key.startswith("_")]
    assert created["slug"] == "gamma"
    assert all(type(body) is dict for body in container.upsert_bodies), "Only plain metadata is written"
    assert all(not any(key.startswith("_") for key in body) for body in container.upsert_bodies)
    assert all(body["modified_by"] == "admin" and body["entry_type"] == "static" for body in container.upsert_bodies)
    assert invalidations == ["save_custom_page", "save_custom_page"], "Each save invalidates the cached catalog"
    assert rejected is True and len(container.upsert_bodies) == 2, "Invalid metadata never reaches the container"


def test_listing_normalizes_plain_query_rows_and_reports_a_missing_container_as_empty():
    container = SdkShapedCustomPagesContainer({"alpha": _document("alpha"), "beta": _document("beta", nav_order=20)})
    with custom_pages_with(container) as (pages, _):
        listed = pages._list_cosmos_custom_pages_source()
        container.missing = True
        emptied = pages._list_cosmos_custom_pages_source()

    assert sorted(page["slug"] for page in listed) == ["alpha", "beta"]
    assert all(type(page) is dict and not any(key.startswith("_") for key in page) for page in listed)
    assert emptied == [], "A container that is gone lists no pages"


def test_delete_custom_page_ignores_the_point_response_and_reports_a_missing_page():
    container = SdkShapedCustomPagesContainer({"alpha": _document("alpha")})
    with custom_pages_with(container) as (pages, invalidations):
        removed = pages.delete_custom_page("alpha")
        again = pages.delete_custom_page("alpha")
        unsafe = pages.delete_custom_page("../alpha")

    assert removed is True and container.deleted == ["alpha"]
    assert again is False and unsafe is False, "A missing or unsafe slug is refused without an error"
    assert invalidations == ["delete_custom_page"], "Only a real delete invalidates the cached catalog"


if __name__ == "__main__":
    from test_support.versioning import assert_app_version_at_least

    assert_app_version_at_least("0.261.448")
    tests = [
        test_get_custom_page_reads_an_sdk_point_response_into_plain_metadata,
        test_save_custom_page_returns_plain_metadata_from_an_sdk_upsert_response,
        test_listing_normalizes_plain_query_rows_and_reports_a_missing_container_as_empty,
        test_delete_custom_page_ignores_the_point_response_and_reports_a_missing_page,
    ]
    failures = 0
    for test in tests:
        print(f"Running {test.__name__}...")
        try:
            test()
            print("Test passed.")
        except Exception as error:  # noqa: BLE001 - report and continue
            failures += 1
            print(f"Test failed: {error}")
            import traceback

            traceback.print_exc()
    sys.exit(1 if failures else 0)
