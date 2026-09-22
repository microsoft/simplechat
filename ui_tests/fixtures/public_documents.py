# public_documents.py
"""
Closed M3A public document HTTP fixtures for the real production V2 SPA.
Version: 0.261.132
Implemented in: 0.261.132

Every document read is scoped by the workspace id in its request path and every
returned record carries public_workspace_id. The fixture never permits personal
or group document APIs, and never permits a document mutation: the public surface
is strictly read-only.
"""

import copy
from collections import Counter
from datetime import datetime, timedelta, timezone

import pytest

from ui_tests.fixtures.public_workspace import PublicWorkspaceFixture, connect_options  # noqa: F401


SORT_FIELDS = (
    "_ts", "file_name", "title", "upload_date", "file_size",
    "number_of_pages", "version", "document_classification",
)
NUMERIC_SORT_FIELDS = ("_ts", "file_size", "number_of_pages", "version")
# The public surface has no 'shared' place: facets omit shared_with_me, so the explorer
# never offers it and never asks for it.
PLACES = ("all", "recent", "processing", "errors", "untagged")


def document(workspace_id, identifier, title, *, timestamp, **overrides):
    record = {
        "id": identifier, "document_id": identifier,
        "public_workspace_id": workspace_id,
        "shared_approval_status": "owner",
        "file_name": f"{identifier}.pdf", "title": title,
        "abstract": f"Published metadata for {title}.", "authors": ["Library team"],
        "tags": ["Team"], "document_classification": "Internal",
        "status": "Processing complete", "percentage_complete": 100,
        "file_size": 4096, "number_of_pages": 12, "num_chunks": 15,
        "version": 3, "revision_family_id": f"family-{workspace_id}-{identifier}",
        "is_current_version": True,
        "_ts": timestamp, "upload_date": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "document_intelligence_extraction_mode": "read",
    }
    record.update(copy.deepcopy(overrides))
    return record


class PublicDocumentsFixture(PublicWorkspaceFixture):
    def __init__(self, page):
        super().__init__(page)
        self.active_workspace = "pub-a"
        self.now = int(datetime.now(timezone.utc).timestamp())
        self.documents = {}
        self.versions = {}
        self.detail_overrides = {}
        self.preferences["v2DocumentsPrefs"] = {
            "viewMode": "details", "pageSize": 25, "detailsPaneOpen": True,
            "columns": ["name", "tags", "status", "modified", "size"],
            "sortBy": "_ts", "sortOrder": "desc",
        }
        for workspace_id, name in (("pub-a", "Research brief"), ("pub-b", "Read-only brief")):
            headline = document(workspace_id, "same-document", name, timestamp=self.now, tags=["Finance", "Team"])
            processing = document(workspace_id, "processing-report", "Indexing source", timestamp=self.now - 5,
                percentage_complete=30, status="Processing")
            failed = document(workspace_id, "failed-report", "Import needs attention", timestamp=self.now - 6,
                status="Processing failed", percentage_complete=10)
            rows = [headline, processing, failed]
            if workspace_id == "pub-a":
                for index in range(1, 59):
                    rows.append(document(workspace_id, f"team-{index:02d}", f"Team research {index:02d}",
                        timestamp=self.now - (index + 10 if index % 3 else 200 * 86400),
                        tags=["Team", "Finance"] if index % 2 else [],
                        file_size=index * 1000, number_of_pages=index, version=index % 4 + 1,
                        document_classification="Internal" if index % 2 else "Confidential"))
            self.documents[workspace_id] = rows
            self.versions[(workspace_id, "same-document")] = [
                copy.deepcopy(headline),
                document(workspace_id, "previous-version", "Earlier research brief", timestamp=self.now - 86400,
                    version=2, is_current_version=False, revision_family_id=headline["revision_family_id"]),
            ]

    def _bootstrap(self):
        payload = super()._bootstrap()
        payload["version"] = "0.261.132"
        payload["features"].update({
            "enable_document_classification": True,
            "enable_extract_meta_data": True,
        })
        payload["settings"]["document_classification_categories"] = [
            {"label": "Internal", "color": "#0078d4"},
            {"label": "Confidential", "color": "#8b5cf6"},
        ]
        return payload

    def visible(self, workspace_id):
        return [row for row in self.documents[workspace_id] if row.get("is_current_version") is not False]

    @staticmethod
    def tags(row):
        raw = row.get("tags", [])
        return [tag.strip() for tag in (raw.split(",") if isinstance(raw, str) else raw) if tag.strip()]

    @staticmethod
    def state(row):
        status = str(row.get("status", "")).lower()
        if "error" in status or "failed" in status:
            return "errors"
        return "processing" if row.get("percentage_complete", 100) < 100 else "ready"

    def in_place(self, row, place):
        if place == "recent":
            return row.get("_ts", 0) >= self.now - int(timedelta(days=30).total_seconds())
        if place in ("processing", "errors"):
            return self.state(row) == place
        if place == "untagged":
            return not self.tags(row)
        return True

    def facets(self, workspace_id):
        rows = self.visible(workspace_id)
        # Deliberately omits shared_with_me: a public workspace has no shared place.
        return {
            "total": len(rows),
            **{key: sum(self.in_place(row, place) for row in rows)
               for key, place in (
                   ("untagged", "untagged"), ("processing", "processing"),
                   ("errors", "errors"), ("recent", "recent"),
               )},
            "by_tag": dict(Counter(tag for row in rows for tag in set(self.tags(row)))),
            "by_classification": dict(Counter(
                row["document_classification"] for row in rows if row.get("document_classification")
            )),
        }

    def _documents_base(self, workspace_id):
        return f"/api/public-workspaces/{workspace_id}/documents"

    def _dispatch(self, route, entry):
        path, method = entry.path, entry.method
        prefix = "/api/public-workspaces/"
        if path.startswith(prefix) and "/documents" in path:
            assert method == "GET", f"M3A must not mutate public documents: {entry}"
            remainder = path[len(prefix):]
            workspace_id, _, tail = remainder.partition("/documents")
            assert workspace_id in self.workspaces, entry
            assert "group_id" not in entry.query and "group_ids" not in entry.query, entry
            assert "public_workspace_id" not in entry.query, entry
            if workspace_id in self.denied_workspaces or not self.workspaces[workspace_id]["document_permissions"]["can_view"]:
                self._json(route, {"error": "Public workspace documents are unavailable."}, 403)
                return
            suffix = tail  # "" | "/facets" | "/tags" | "/<id>" | "/<id>/versions"
            if suffix == "":
                assert set(entry.query) <= {
                    "page", "page_size", "search", "tags", "classification", "place", "sort_by", "sort_order",
                }, entry
                place = entry.query.get("place", ["all"])[0]
                sort_by = entry.query.get("sort_by", ["_ts"])[0]
                direction = entry.query.get("sort_order", ["desc"])[0]
                assert place in PLACES and sort_by in SORT_FIELDS and direction in ("asc", "desc")
                search = entry.query.get("search", [""])[0].casefold()
                tags = {tag.casefold() for tag in entry.query.get("tags", [""])[0].split(",") if tag}
                classification = entry.query.get("classification", [None])[0]
                rows = [
                    row for row in self.visible(workspace_id)
                    if self.in_place(row, place)
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
                    "page": page, "page_size": size, "file_downloads_enabled": False,
                })
            elif suffix == "/facets":
                assert entry.query == {}, entry
                self._json(route, self.facets(workspace_id))
            elif suffix == "/tags":
                assert entry.query == {}, entry
                self._json(route, {"tags": [
                    {"name": name, "count": count, "color": "#0078d4" if name == "Finance" else "#059669"}
                    for name, count in sorted(self.facets(workspace_id)["by_tag"].items())
                ]})
            else:
                assert entry.query == {}, entry
                parts = suffix.strip("/").split("/")
                identifier = parts[0]
                record = self.detail_overrides.get((workspace_id, identifier))
                if record is None:
                    record = next((row for row in self.visible(workspace_id) if row["id"] == identifier), None)
                if record is None:
                    self._json(route, {"error": "Document is not available in this workspace."}, 404)
                elif len(parts) == 2 and parts[1] == "versions":
                    self._json(route, {
                        "document_id": identifier, "public_workspace_id": workspace_id,
                        "revision_family_id": record["revision_family_id"],
                        "versions": self.versions.get((workspace_id, identifier), [record]),
                    })
                else:
                    assert len(parts) == 1
                    self._json(route, record)
        elif path == "/api/v2/orchestration/runs" and method == "GET":
            assert entry.query.get("conversation_id", [None])[0] in self.messages
            assert entry.query.get("limit") == ["25"]
            self._json(route, {"runs": []})
        else:
            super()._dispatch(route, entry)

    def assert_clean(self):
        super().assert_clean()
        assert not [request for request in self.requests if request.path.startswith("/api/documents")], (
            "Public document browsing made a personal document request."
        )
        assert not [request for request in self.requests if request.path.startswith("/api/group_documents")], (
            "Public document browsing made a group document request."
        )
        for request in self.writes:
            if request.path == "/api/public_workspaces/setActive" and request.method == "PATCH":
                continue
            if request.path == "/api/user/settings" and request.method == "POST":
                assert set(request.body["settings"]) <= {
                    "v2DocumentsPrefs", "v2WorkspaceRailCollapsed", "v2RailCollapsed", "darkModeEnabled",
                }, f"Only presentation preferences may be shared with public browsing: {request}"
                continue
            assert False, f"Unexpected mutation during read-only public browsing: {request}"


@pytest.fixture
def public_documents_ui(page):
    fixture = PublicDocumentsFixture(page)
    yield fixture
    fixture.assert_clean()
