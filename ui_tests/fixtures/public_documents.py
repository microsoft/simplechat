# public_documents.py
"""
Closed M3A public document HTTP fixtures for the real production V2 SPA.
Version: 0.261.183
Implemented in: 0.261.132
The served rows, read texts and refusals are the real read routes', held to them by
functional_tests/test_public_document_fixture_parity.py: 0.261.179
A generated artifact awaiting publication is shown, held, only to a workspace manager; to anyone
else it does not exist: 0.261.183
chat_list is the public chat document list as its route answers it, pending artifacts left out for
every caller, held to the route by functional_tests/test_public_chat_document_list_pending_artifacts.py:
0.261.183

Every document read is scoped by the workspace id in its request path and every
returned record carries public_workspace_id. The fixture never permits personal
or group document APIs, and never permits a document mutation: the public surface
is strictly read-only.
"""

import ast
import copy
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from ui_tests.fixtures.public_workspace import (  # noqa: F401
    PUBLIC_MANAGER_ROLES, PublicWorkspaceFixture, connect_options, public_context,
)


APP_ROOT = Path(__file__).resolve().parents[2] / "application" / "single_app"


def _screening_field_set(name):
    """A `frozenset({...})` field allow-list from content_screening/access.py, read from the server
    rather than copied, so a held row keeps exactly the fields the server keeps."""
    tree = ast.parse((APP_ROOT / "content_screening" / "access.py").read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in node.targets
        ):
            return frozenset(ast.literal_eval(node.value.args[0]))
    raise LookupError(f"content_screening/access.py defines no {name}")


HELD_PUBLIC_FIELDS = _screening_field_set("HELD_PUBLIC_FIELDS")
GENERATED_ARTIFACT_REQUEST_FIELDS = _screening_field_set("GENERATED_ARTIFACT_REQUEST_FIELDS")


SORT_FIELDS = (
    "_ts", "file_name", "title", "upload_date", "file_size",
    "number_of_pages", "version", "document_classification",
)
NUMERIC_SORT_FIELDS = ("_ts", "file_size", "number_of_pages", "version")
# The server's PUBLIC_DOCUMENT_PLACE_FILTERS: a public workspace has no cross-workspace share, so
# there is no 'shared' place, and the explorer never asks for one.
PLACES = ("all", "recent", "processing", "errors", "untagged")

# The read texts the real public document routes send (functions_public_document_access.py and
# functions_public_document_reads.py), held to them by
# functional_tests/test_public_document_fixture_parity.py. Every authenticated caller reads a public
# workspace as at least a User, so the access refusal is unreachable under today's role rules; the
# fixture keeps it, with the server's sentence, as a client robustness scenario.
PUBLIC_DOCUMENTS_DENIED_ERROR = "You do not have access to the selected public workspace."
PUBLIC_DOCUMENTS_STATUS_ERROR = "Documents are unavailable for this public workspace's current status."
PUBLIC_DOCUMENT_NOT_FOUND_ERROR = "Document not found or access denied."
SCREENING_UNAVAILABLE_STATUS = "Content screening: document unavailable"
# The status a manager's projection gives a generated artifact awaiting publication
# (functions_public_document_reads.PUBLIC_ARTIFACT_AWAITING_APPROVAL_STATUS).
AWAITING_APPROVAL_STATUS = "Awaiting generated artifact approval"


def document(workspace_id, identifier, title, *, timestamp, **overrides):
    """A stored public document. Tags are stored lowercase (`validate_tags`), and a public document
    has no share relationship to store."""
    record = {
        "id": identifier, "document_id": identifier,
        "public_workspace_id": workspace_id,
        "file_name": f"{identifier}.pdf", "title": title,
        "abstract": f"Published metadata for {title}.", "authors": ["Library team"],
        "tags": ["team"], "document_classification": "Internal",
        "status": "Processing complete", "percentage_complete": 100,
        "file_size": 4096, "number_of_pages": 12, "num_chunks": 15,
        "version": 3, "revision_family_id": f"family-{workspace_id}-{identifier}",
        "is_current_version": True,
        "_ts": timestamp, "upload_date": datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
        "document_intelligence_extraction_mode": "read",
    }
    record.update(copy.deepcopy(overrides))
    return record


def held(record, state="scanning"):
    """A document content screening holds, as every reader's projection lists it
    (content_screening.access.public_document_payload): only the held fields, the screening summary,
    and why it is unavailable. A hold in a state no one can clean up (`scanning`) leaves a manager no
    document operation at all."""
    projected = {key: copy.deepcopy(value) for key, value in record.items() if key in HELD_PUBLIC_FIELDS or key == "_ts"}
    projected.update({
        "content_screening": {"state": state, "available": False, "finding_count": 0},
        "status": SCREENING_UNAVAILABLE_STATUS, "enhanced_citations": False,
    })
    return projected


def member_projection(record):
    """The action hints the read projection computes for an ordinary reader's row: no management
    operation, and the review of any document of a workspace that offers review."""
    record.setdefault("document_actions", [])
    record.setdefault("document_collaboration_actions", ["inspect"])
    return record


def awaiting_publication(row):
    """functions_public_document_policy.public_document_approval_pending: a generated artifact whose
    publication is undecided, by its promotion status or, before one is recorded, its stored status."""
    promotion = row.get("generated_artifact_promotion_status")
    return promotion == "pending_approval" or (
        promotion is None and str(row.get("status") or "").strip().lower() == "pending approval"
    )


def awaiting_approval(record):
    """A generated artifact awaiting publication, as a manager's projection lists it
    (functions_public_document_reads._project_public_document), and as a group member sees one: only
    the held fields and the request, never its content. No one else is shown it at all
    (PublicDocumentsFixture.viewer_may_see)."""
    projected = {
        key: copy.deepcopy(value) for key, value in record.items()
        if key in HELD_PUBLIC_FIELDS or key in GENERATED_ARTIFACT_REQUEST_FIELDS
        or key in ("_ts", "content_screening")
    }
    projected.update({
        "status": AWAITING_APPROVAL_STATUS, "generated_artifact_promotion_status": "pending_approval",
        "enhanced_citations": False,
    })
    return projected


def chat_list(rows):
    """GET /api/public_workspace_documents, the list the V2 and classic chat pickers read, as the route
    answers it: every row a chat can use. A generated artifact awaiting publication is left out for
    every caller, since it has no content until its approval queues processing (decision 27)."""
    return {
        "documents": [copy.deepcopy(row) for row in rows if not awaiting_publication(row)],
        "workspace_name": "All Public Workspaces",
    }


def served(record):
    """A row as the routes return it. `_ts` is the server's own sort and recent key, so the final
    projection never carries it; the explorer dates a row by its upload date instead."""
    return {key: copy.deepcopy(value) for key, value in record.items() if key != "_ts"}


class PublicDocumentsFixture(PublicWorkspaceFixture):
    def __init__(self, page):
        super().__init__(page)
        self.active_workspace = "pub-a"
        # The M3A read surface models a public workspace whose file downloads are turned off, so an
        # ordinary reader sees no Download control here and the list reports file_downloads_enabled
        # false, exactly as the real read routes do for a downloads-off workspace
        # (test_public_document_fixture_parity's reader env runs with downloads off). Reader downloads,
        # a downloads-on capability whose bytes must be served, are exercised on the management fixture.
        self.workspaces = {
            "pub-a": public_context("pub-a", "Research library", disable_file_downloads=True),
            "pub-b": public_context("pub-b", "Read-only library", disable_file_downloads=True),
        }
        self.now = int(datetime.now(timezone.utc).timestamp())
        self.documents = {}
        self.versions = {}
        self.detail_overrides = {}
        # Each workspace's tag definitions: the tag list names every one with its current-set count.
        self.vocabulary = {}
        self.preferences["v2DocumentsPrefs"] = {
            "viewMode": "details", "pageSize": 25, "detailsPaneOpen": True,
            "columns": ["name", "tags", "status", "modified", "size"],
            "sortBy": "_ts", "sortOrder": "desc",
        }
        for workspace_id, name in (("pub-a", "Research brief"), ("pub-b", "Read-only brief")):
            # Stored tags are normalized to lowercase (`validate_tags`), so every row carries them in lowercase.
            headline = document(workspace_id, "same-document", name, timestamp=self.now, tags=["finance", "team"])
            processing = document(workspace_id, "processing-report", "Indexing source", timestamp=self.now - 5,
                percentage_complete=30, status="Processing")
            failed = document(workspace_id, "failed-report", "Import needs attention", timestamp=self.now - 6,
                status="Processing failed", percentage_complete=10)
            rows = [headline, processing, failed]
            if workspace_id == "pub-a":
                for index in range(1, 59):
                    rows.append(document(workspace_id, f"team-{index:02d}", f"Team research {index:02d}",
                        timestamp=self.now - (index + 10 if index % 3 else 200 * 86400),
                        tags=["team", "finance"] if index % 2 else [],
                        file_size=index * 1000, number_of_pages=index, version=index % 4 + 1,
                        document_classification="Internal" if index % 2 else "Confidential"))
            # The fixture views both workspaces as an ordinary reader (public_context's default role).
            self.documents[workspace_id] = [member_projection(row) for row in rows]
            self.vocabulary[workspace_id] = {"finance": "#0078d4", "team": "#059669"}
            self.versions[(workspace_id, "same-document")] = [
                copy.deepcopy(self.documents[workspace_id][0]),
                member_projection(document(workspace_id, "previous-version", "Earlier research brief",
                    timestamp=self.now - 86400, version=2, is_current_version=False,
                    revision_family_id=headline["revision_family_id"])),
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

    def viewer_may_see(self, workspace_id, row):
        """functions_public_document_policy.public_document_visible_to_role for the viewer's role: a
        generated artifact awaiting publication is visible only to the workspace's managers."""
        return self.workspaces[workspace_id].get("role") in PUBLIC_MANAGER_ROLES or not awaiting_publication(row)

    def visible(self, workspace_id):
        """The current rows the viewer may see. The list, its count, the facets and the tag counts are
        all computed from this one set, as load_public_document_browser_documents computes them."""
        return [
            row for row in self.documents[workspace_id]
            if row.get("is_current_version") is not False and self.viewer_may_see(workspace_id, row)
        ]

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
        return {
            "total": len(rows),
            **{key: sum(self.in_place(row, place) for row in rows)
               for key, place in (
                   ("untagged", "untagged"), ("processing", "processing"),
                   ("errors", "errors"), ("recent", "recent"),
               )},
            # build_document_facets counts the documents another workspace owns. A public workspace
            # owns every document it lists, so this is always 0 and the explorer offers no Shared place.
            "shared_with_me": sum(row.get("public_workspace_id") != workspace_id for row in rows),
            "by_tag": dict(Counter(tag for row in rows for tag in set(self.tags(row)))),
            "by_classification": dict(Counter(
                row["document_classification"] for row in rows if row.get("document_classification")
            )),
        }

    def _documents_base(self, workspace_id):
        return f"/api/public-workspaces/{workspace_id}/documents"

    def _read_refusal(self, workspace_id):
        """The refusal a read meets before any document is read, or None."""
        if workspace_id in self.denied_workspaces:
            return PUBLIC_DOCUMENTS_DENIED_ERROR
        if not self.workspaces[workspace_id]["document_permissions"]["can_view"]:
            return PUBLIC_DOCUMENTS_STATUS_ERROR
        return None

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
            refusal = self._read_refusal(workspace_id)
            if refusal:
                self._json(route, {"error": refusal}, 403)
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
                # The route derives the flag from the same policy the context advertises.
                downloads = "download" in self.workspaces[workspace_id].get("document_management", {}).get("operations", [])
                self._json(route, {
                    "documents": [served(row) for row in rows[(page - 1) * size:page * size]], "total_count": len(rows),
                    "page": page, "page_size": size, "file_downloads_enabled": downloads,
                })
            elif suffix == "/facets":
                assert entry.query == {}, entry
                self._json(route, self.facets(workspace_id))
            elif suffix == "/tags":
                assert entry.query == {}, entry
                counts = self.facets(workspace_id)["by_tag"]
                self._json(route, {"tags": [
                    {"name": name, "count": counts.get(name, 0), "color": color}
                    for name, color in sorted(self.vocabulary[workspace_id].items())
                ]})
            else:
                assert entry.query == {}, entry
                parts = suffix.strip("/").split("/")
                identifier = parts[0]
                record = self.detail_overrides.get((workspace_id, identifier))
                if record is None:
                    record = next((row for row in self.visible(workspace_id) if row["id"] == identifier), None)
                if record is None:
                    self._json(route, {"error": PUBLIC_DOCUMENT_NOT_FOUND_ERROR}, 404)
                elif len(parts) == 2 and parts[1] == "versions":
                    self._json(route, {
                        "document_id": identifier, "public_workspace_id": workspace_id,
                        "revision_family_id": record["revision_family_id"],
                        "versions": [
                            served(row) for row in self.versions.get((workspace_id, identifier), [record])
                            if self.viewer_may_see(workspace_id, row)
                        ],
                    })
                else:
                    assert len(parts) == 1
                    self._json(route, served(record))
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
