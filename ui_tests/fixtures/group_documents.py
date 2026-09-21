# group_documents.py
"""
Closed M2A group document HTTP fixtures for the real production V2 SPA.
Version: 0.261.128
Implemented in: 0.261.128

The fixture serves full-set query results and separately scoped details/versions.
It never permits personal document APIs or document mutations. Navigation and
presentation preferences retain the real group shell's existing contracts.
"""

import copy
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from ui_tests.fixtures.group_workspace import GroupWorkspaceFixture, connect_options  # noqa: F401


SORT_FIELDS = (
    "_ts", "file_name", "title", "upload_date", "file_size",
    "number_of_pages", "version", "document_classification",
)
NUMERIC_SORT_FIELDS = ("_ts", "file_size", "number_of_pages", "version")
PLACES = ("all", "recent", "shared", "processing", "errors", "untagged")


def document(group_id, identifier, title, *, timestamp, **overrides):
    record = {
        "id": identifier, "document_id": identifier,
        "group_id": group_id, "owner_group_id": group_id,
        "shared_approval_status": "owner",
        "file_name": f"{identifier}.pdf", "title": title,
        "abstract": f"Approved metadata for {title}.", "authors": ["Research team"],
        "tags": ["Team"], "document_classification": "Internal",
        "status": "Processing complete", "percentage_complete": 100,
        "file_size": 4096, "number_of_pages": 12, "num_chunks": 15,
        "version": 3, "revision_family_id": f"family-{group_id}-{identifier}",
        "is_current_version": True,
        "_ts": timestamp, "upload_date": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "document_intelligence_extraction_mode": "read",
    }
    record.update(copy.deepcopy(overrides))
    return record


def restricted(record):
    """Represent the backend's safe projection without retaining extracted fields."""
    return {
        key: copy.deepcopy(value) for key, value in record.items()
        if key in {
            "id", "document_id", "group_id", "owner_group_id", "owner_group_name",
            "shared_group_active_id", "shared_approval_status", "file_name",
            "status", "percentage_complete", "version", "revision_family_id",
            "is_current_version", "_ts", "upload_date", "content_screening",
        }
    }


class GroupDocumentsFixture(GroupWorkspaceFixture):
    def __init__(self, page):
        super().__init__(page)
        self.active_group = "group-a"
        self.now = int(datetime.now(timezone.utc).timestamp())
        self.documents = {}
        self.versions = {}
        self.detail_overrides = {}
        self.lock_chat = False
        self.allow_chat_writes = False
        self.preferences["v2DocumentsPrefs"] = {
            "viewMode": "details", "pageSize": 25, "detailsPaneOpen": True,
            "columns": ["name", "tags", "status", "modified", "size"],
            "sortBy": "_ts", "sortOrder": "desc",
        }
        self.preferences["v2DocumentSavedViews"] = [{
            "id": "private-view", "name": "Personal private view",
            "query": {"place": "recent", "search": "personal", "tags": ["Private"], "classification": None},
        }]
        for group_id, name in (("group-a", "Research brief"), ("group-b", "Read-only brief")):
            owned = document(group_id, "same-document", name, timestamp=self.now, tags=["Finance", "Team"])
            shared = document("origin", "shared-report", "Published report", timestamp=self.now - 1,
                shared_group_active_id=group_id, shared_approval_status="approved",
                owner_group_name="Publishing group", tags=["Finance"], document_classification="Confidential")
            pending = restricted(document("origin", "pending-report", "Restricted pending title", timestamp=self.now - 2,
                shared_group_active_id=group_id, shared_approval_status="not_approved", owner_group_name="Publishing group"))
            held = restricted(document(group_id, "held-report", "Restricted held title", timestamp=self.now - 3,
                content_screening={"state": "pending_review", "available": False, "finding_count": 2}))
            held_share = restricted(document("origin", "held-share", "Restricted shared title", timestamp=self.now - 4,
                shared_group_active_id=group_id, shared_approval_status="approved", owner_group_name="Publishing group",
                content_screening={"state": "scanning", "available": False, "finding_count": 0}))
            processing = document(group_id, "processing-report", "Indexing source", timestamp=self.now - 5,
                percentage_complete=30, status="Processing")
            failed = document(group_id, "failed-report", "Import needs attention", timestamp=self.now - 6,
                status="Processing failed", percentage_complete=10)
            rows = [owned, shared, pending, held, held_share, processing, failed]
            if group_id == "group-a":
                for index in range(1, 59):
                    rows.append(document(group_id, f"team-{index:02d}", f"Team research {index:02d}",
                        timestamp=self.now - (index + 10 if index % 3 else 200 * 86400),
                        tags=["Team", "Finance"] if index % 2 else [],
                        file_size=index * 1000, number_of_pages=index, version=index % 4 + 1,
                        document_classification="Internal" if index % 2 else "Confidential"))
            self.documents[group_id] = rows
            self.versions[(group_id, "same-document")] = [
                copy.deepcopy(owned),
                document(group_id, "previous-version", "Earlier research brief", timestamp=self.now - 86400,
                    version=2, is_current_version=False, revision_family_id=owned["revision_family_id"]),
            ]
            self.versions[(group_id, "shared-report")] = [
                copy.deepcopy(shared),
                restricted(document("origin", "pending-version", "Restricted earlier share", timestamp=self.now - 86400,
                    version=1, is_current_version=False, revision_family_id=shared["revision_family_id"],
                    shared_group_active_id=group_id, shared_approval_status="not_approved", owner_group_name="Publishing group")),
            ]

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = "0.261.128"
        payload["features"].update({
            "enable_document_classification": True,
            "enable_file_sharing": True,
            "enable_extract_meta_data": True,
            "enable_enhanced_extraction": True,
            "enable_content_screening": True,
        })
        payload["settings"]["document_classification_categories"] = [
            {"label": "Internal", "color": "#0078d4"},
            {"label": "Confidential", "color": "#8b5cf6"},
        ]
        return payload

    def visible(self, group_id):
        return [row for row in self.documents[group_id] if row.get("is_current_version") is not False]

    @staticmethod
    def tags(row):
        raw = row.get("tags", [])
        return [tag.strip() for tag in (raw.split(",") if isinstance(raw, str) else raw) if tag.strip()]

    @staticmethod
    def state(row):
        status = str(row.get("status", "")).lower()
        if "error" in status or "failed" in status:
            return "errors"
        if row.get("shared_approval_status") == "not_approved":
            return "pending"
        return "processing" if row.get("percentage_complete", 100) < 100 else "ready"

    def in_place(self, row, group_id, place):
        if place == "recent":
            return row.get("_ts", 0) >= self.now - int(timedelta(days=30).total_seconds())
        if place == "shared":
            return row.get("group_id") != group_id
        if place in ("processing", "errors"):
            return self.state(row) == place
        if place == "untagged":
            return not self.tags(row)
        return True

    def facets(self, group_id):
        rows = self.visible(group_id)
        return {
            "total": len(rows),
            **{key: sum(self.in_place(row, group_id, place) for row in rows)
               for key, place in (
                   ("untagged", "untagged"), ("processing", "processing"), ("errors", "errors"),
                   ("recent", "recent"), ("shared_with_me", "shared"),
               )},
            "by_tag": dict(Counter(tag for row in rows for tag in set(self.tags(row)))),
            "by_classification": dict(Counter(
                row["document_classification"] for row in rows if row.get("document_classification")
            )),
        }

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        if path.startswith("/api/group_documents"):
            assert method == "GET", f"M2A must not mutate documents: {entry}"
            assert len(entry.query.get("group_id", [])) == 1, f"Explicit single-group scope is required: {entry}"
            assert "group_ids" not in entry.query, f"The chat aggregate is not a workspace read: {entry}"
            group_id = entry.query["group_id"][0]
            assert group_id in self.groups, entry
            if group_id in self.denied_groups or not self.groups[group_id]["document_permissions"]["can_view"]:
                self._json(route, {"error": "Group documents are unavailable."}, 403)
                return
            if path == "/api/group_documents":
                assert set(entry.query) <= {
                    "group_id", "page", "page_size", "search", "tags", "classification", "place", "sort_by", "sort_order",
                }
                place = entry.query.get("place", ["all"])[0]
                sort_by = entry.query.get("sort_by", ["_ts"])[0]
                direction = entry.query.get("sort_order", ["desc"])[0]
                assert place in PLACES and sort_by in SORT_FIELDS and direction in ("asc", "desc")
                search = entry.query.get("search", [""])[0].casefold()
                tags = {tag.casefold() for tag in entry.query.get("tags", [""])[0].split(",") if tag}
                classification = entry.query.get("classification", [None])[0]
                rows = [
                    row for row in self.visible(group_id)
                    if self.in_place(row, group_id, place)
                    and search in f'{row.get("file_name", "")} {row.get("title", "")}'.casefold()
                    and tags.issubset({tag.casefold() for tag in self.tags(row)})
                    and (not classification or row.get("document_classification") == classification)
                ]
                rows.sort(
                    key=lambda row: float(row.get(sort_by) or 0) if sort_by in NUMERIC_SORT_FIELDS
                        else str(row.get(sort_by) or "").casefold(),
                    reverse=direction == "desc",
                )
                page = int(entry.query.get("page", ["1"])[0])
                size = int(entry.query.get("page_size", ["50"])[0])
                self._json(route, {
                    "documents": rows[(page - 1) * size:page * size], "total_count": len(rows),
                    "page": page, "page_size": size, "file_downloads_enabled": True,
                })
            elif path == "/api/group_documents/facets":
                assert entry.query == {"group_id": [group_id]}
                self._json(route, self.facets(group_id))
            elif path == "/api/group_documents/tags":
                assert entry.query == {"group_id": [group_id]}
                self._json(route, {"tags": [
                    {"name": name, "count": count, "color": "#0078d4" if name == "Finance" else "#059669"}
                    for name, count in sorted(self.facets(group_id)["by_tag"].items())
                ]})
            else:
                parts = path.split("/")
                identifier = parts[3]
                record = self.detail_overrides.get((group_id, identifier))
                if record is None:
                    record = next((row for row in self.visible(group_id) if row["id"] == identifier), None)
                if record is None:
                    self._json(route, {"error": "Document is not available in this group."}, 404)
                elif len(parts) == 5 and parts[4] == "versions":
                    self._json(route, {
                        "document_id": identifier, "group_id": group_id,
                        "revision_family_id": record["revision_family_id"],
                        "versions": self.versions.get((group_id, identifier), [record]),
                    })
                else:
                    assert len(parts) == 4
                    self._json(route, record)
        elif path == "/api/chat/stream" and self.lock_chat:
            self._json(route, {"error": "Context scope is locked for this conversation."}, 409)
        elif path == "/api/v2/orchestration/runs" and method == "GET":
            assert entry.query.get("conversation_id", [None])[0] in self.messages
            assert entry.query.get("limit") == ["25"]
            self._json(route, {"runs": []})
        else:
            super()._dispatch(route, entry)

    def assert_clean(self):
        super().assert_clean()
        assert not [request for request in self.requests if request.path.startswith("/api/documents")], (
            "Group document browsing or handoff made a personal document request."
        )
        for request in self.writes:
            if request.path == "/api/groups/setActive" and request.method == "PATCH":
                continue
            if request.path == "/api/user/settings" and request.method == "POST":
                assert set(request.body["settings"]) <= {
                    "v2DocumentsPrefs", "v2WorkspaceRailCollapsed", "v2RailCollapsed", "darkModeEnabled",
                }, f"Only presentation preferences may be shared with group browsing: {request}"
                continue
            assert self.allow_chat_writes and request.path in (
                "/api/create_conversation", "/api/chat/stream",
            ), f"Unexpected mutation during read-only group browsing: {request}"


@pytest.fixture
def group_documents_ui(page):
    fixture = GroupDocumentsFixture(page)
    yield fixture
    fixture.assert_clean()
