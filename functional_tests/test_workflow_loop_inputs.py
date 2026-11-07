# test_workflow_loop_inputs.py
"""
Closed production-backed tests for workflow document/query loop inputs.
Version: 0.261.122
Implemented in: 0.261.117

Runs the real loop adapter, paged Cosmos/Search readers, metadata filtering, and
content-screening access against closed service doubles. No app startup, Azure
credentials, network requests, source normalization, or persistent writes occur.
"""

from contextlib import contextmanager
from copy import deepcopy
import ast
import importlib.util
import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace
import unittest
from unittest.mock import patch


APP_ROOT = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP_ROOT))

# Production imports follow the isolated application path setup.
from content_screening.contracts import (
    ContentUnit,
    content_fingerprint,
    hash_payload,
    metadata_fingerprint,
    subject_from_document,
)
from functions_analysis_access import analysis_source_snapshot
from functions_mixed_source_orchestration import resolve_authorized_source_manifest
from functions_workflow_loop_inputs import (
    WorkflowLoopInputError,
    iter_workflow_loop_documents,
    reauthorize_workflow_loop_document,
)
from functions_workflow_limits import WorkflowLoopLimitError


def module(name, **values):
    result = ModuleType(name)
    result.__dict__.update(values)
    return result


def unexpected(*_args, **_kwargs):
    raise AssertionError("Unexpected external call or persistent write.")


class MissingRecord(Exception):
    status_code = 404


class Paged:
    def __init__(self, rows, page_size=37, *, failure_page=None, incomplete=False, on_page=None):
        self.rows = rows
        self.page_size = page_size
        self.failure_page = failure_page
        self.incomplete = incomplete
        self.on_page = on_page
        self.pages_read = 0

    def by_page(self):
        owner = self

        class Pages:
            continuation_token = None

            def __iter__(self):
                return self

            def __next__(self):
                index = owner.pages_read
                if owner.failure_page == index:
                    raise RuntimeError("PRIVATE-ENDPOINT?credential=PRIVATE-SECRET")
                start = index * owner.page_size
                if start >= len(owner.rows):
                    self.continuation_token = "lost-continuation" if owner.incomplete else None
                    raise StopIteration
                if owner.on_page is not None:
                    owner.on_page(index)
                owner.pages_read += 1
                self.continuation_token = "next"
                return iter(deepcopy(owner.rows[start:start + owner.page_size]))

        return Pages()


class Container:
    def __init__(self):
        self.items = {}
        self.reads = []
        self.error = None

    def read_item(self, *, item, partition_key):
        self.reads.append((item, partition_key))
        if self.error is not None:
            raise self.error
        if item not in self.items:
            raise MissingRecord()
        return deepcopy(self.items[item])

    def query_items(self, *, parameters, **_kwargs):
        values = {entry["name"]: entry["value"] for entry in parameters}
        if values.get("@type") != "document_access_index_repair":
            raise AssertionError("Unexpected query.")
        return [
            row["id"] for row in self.items.values()
            if row.get("type") == values["@type"] and row.get("status") == values["@status"]
        ]

    create_item = upsert_item = replace_item = delete_item = unexpected


class IndexContainer(Container):
    def __init__(self):
        super().__init__()
        self.rows = []
        self.requests = []
        self.responses = []
        self.failure_page = None
        self.incomplete = False

    def query_items(self, *, query, parameters, partition_key, max_item_count):
        if self.error is not None:
            raise self.error
        self.requests.append({"query": query, "partition_key": partition_key, "page_size": max_item_count})
        values = {entry["name"]: entry["value"] for entry in parameters}
        rows = [
            row for row in self.rows
            if row["source_scope"] == values["@source_scope"]
            and row["scope_key"] == partition_key
            and row["access_granted"] is True
            and row["is_current_version"] is True
            and row["projection_version"] == values["@projection_version"]
        ]
        rows.sort(key=lambda value: value["document_id"])
        response = Paged(
            rows, max_item_count, failure_page=self.failure_page, incomplete=self.incomplete,
        )
        self.responses.append(response)
        return response


class SearchClient:
    def __init__(self):
        self.hits = []
        self.requests = []
        self.responses = []
        self.error = None
        self.failure_page = None
        self.incomplete = False

    def search(self, **arguments):
        if self.error is not None:
            raise self.error
        self.requests.append(arguments)
        excluded = set()
        exclusion = re.search(
            r"not search\.in\(document_id, '((?:''|[^'])*)', '([^']*)'\)",
            arguments["filter"],
        )
        if exclusion:
            excluded.update(exclusion[1].replace("''", "'").split(exclusion[2]))
        hits = [hit for hit in self.hits if hit["document_id"] not in excluded]
        if "top" in arguments:
            hits = hits[:arguments["top"]]
        result = Paged(
            hits, failure_page=self.failure_page, incomplete=self.incomplete,
        )
        self.responses.append(result)
        return result


class LoopInputTests(unittest.TestCase):
    def setUp(self):
        self.workflow = {"id": "workflow-1", "user_id": "owner"}
        self.settings = {"enable_file_sharing": True}
        self.personal = Container()
        self.group_documents = Container()
        self.public_documents = Container()
        self.scans = Container()
        self.settings_store = Container()
        self.index = IndexContainer()
        self.search_clients = {scope: SearchClient() for scope in ("personal", "group", "public")}
        self.memberships = {("owner", "group-1"), ("owner", "group-2")}
        self.groups = {"group-1": {"id": "group-1"}, "group-2": {"id": "group-2"}}
        self.workspaces = {"public-1": {"id": "public-1"}}
        self.scope_checks = []
        self.profile_slots = []
        self.embedding_calls = []
        self.units = {}
        config = module(
            "config",
            CLIENTS={
                "search_client_user": self.search_clients["personal"],
                "search_client_group": self.search_clients["group"],
                "search_client_public": self.search_clients["public"],
            },
            VectorizedQuery=lambda **kwargs: SimpleNamespace(**kwargs),
            cosmos_document_access_index_container=self.index,
            cosmos_settings_container=self.settings_store,
            cosmos_user_documents_container=self.personal,
            cosmos_group_documents_container=self.group_documents,
            cosmos_public_documents_container=self.public_documents,
            cosmos_content_screening_container=self.scans,
            cosmos_groups_container=Container(),
            cosmos_public_workspaces_container=Container(),
            cosmos_user_settings_container=Container(),
            cosmos_user_documents_container_name="documents",
            cosmos_group_documents_container_name="group_documents",
            cosmos_public_documents_container_name="public_documents",
        )

        class SemanticQuotaError(Exception):
            pass

        modules = {
            "config": config,
            "app_settings_cache": module("app_settings_cache"),
            "functions_settings": module(
                "functions_settings", get_settings=lambda: deepcopy(self.settings),
                get_user_settings=unexpected, update_settings=unexpected,
            ),
            "functions_appinsights": module("functions_appinsights", log_event=lambda *_args, **_kwargs: None),
            "functions_group": module(
                "functions_group", assert_group_role=self.authorize_group,
                find_group_by_id=lambda identity: deepcopy(self.groups.get(identity)),
                check_group_status_allows_operation=self.workspace_available,
            ),
            "functions_public_workspaces": module(
                "functions_public_workspaces",
                find_public_workspace_by_id=lambda identity: deepcopy(self.workspaces.get(identity)),
                check_public_workspace_status_allows_operation=self.workspace_available,
                get_user_visible_public_workspace_docs=unexpected,
                get_user_visible_public_workspace_ids_from_settings=unexpected,
            ),
            "functions_content": module("functions_content", generate_embedding=self.generate_embedding),
            "functions_documents": module(
                "functions_documents",
                get_document_blob_storage_info=lambda *_args, **_kwargs: (None, None),
                normalize_document_revision_families=unexpected,
            ),
            "functions_debug": module("functions_debug", debug_print=lambda *_args, **_kwargs: None),
            "functions_embedding_compatibility": module(
                "functions_embedding_compatibility",
                REMOTE_OPTIONS={"retry_total": 0},
                read_embedding_settings=lambda: deepcopy(self.settings),
                active_embedding_profile=lambda _settings: SimpleNamespace(profile_id="current-profile"),
                embedding_search_filter=lambda *_args: "embedding_profile_id eq 'current-profile'",
                embedding_query_slot=self.profile_slot,
                search_with_embedding_profile=unexpected,
            ),
            "utils_cache": module(
                "utils_cache", generate_search_cache_key=unexpected,
                get_cached_search_results=unexpected, cache_search_results=unexpected,
                DEBUG_ENABLED=False,
            ),
            "functions_service_health": module(
                "functions_service_health", SemanticSearchQuotaExceededError=SemanticQuotaError,
                clear_semantic_search_quota_warning=unexpected,
                is_semantic_search_quota_error=lambda error: getattr(error, "quota", False),
                record_semantic_search_quota_exceeded=unexpected,
            ),
            "content_screening.storage": module(
                "content_screening.storage",
                ScreeningStorage=lambda: SimpleNamespace(read_json=self.read_units),
            ),
            "azure.core": module("azure.core", MatchConditions=SimpleNamespace(IfNotModified="etag")),
        }
        self.module_patch = patch.dict(sys.modules, modules)
        self.module_patch.start()
        self.addCleanup(self.module_patch.stop)
        self.catalog = self.load_production_module("functions_document_access_index")
        self.settings_store.items["document_access_index_backfill_state"] = {
            "id": "document_access_index_backfill_state",
            "schema_version": self.catalog.DOCUMENT_ACCESS_INDEX_SCHEMA_VERSION,
            "status": "succeeded", "completed_source_scopes": ["personal", "group", "public"],
        }
        self.search = self.load_production_module("functions_search")

    def load_production_module(self, name):
        spec = importlib.util.spec_from_file_location(name, APP_ROOT / f"{name}.py")
        loaded = importlib.util.module_from_spec(spec)
        sys.modules[name] = loaded
        spec.loader.exec_module(loaded)
        return loaded

    def authorize_group(self, user_id, group_id, allowed_roles):
        self.scope_checks.append((user_id, group_id, tuple(allowed_roles)))
        self.assertIn("Owner", allowed_roles)
        self.assertIn("Admin", allowed_roles)
        if (user_id, group_id) not in self.memberships:
            raise PermissionError("PRIVATE membership details")
        return "User"

    @staticmethod
    def workspace_available(workspace, operation):
        if operation != "chat":
            raise AssertionError("Expected content-use authorization.")
        return bool(workspace and workspace.get("status") != "inactive"), "Unavailable"

    @contextmanager
    def profile_slot(self, profile_id):
        self.profile_slots.append(profile_id)
        yield

    def generate_embedding(self, query, *, purpose, profile):
        self.embedding_calls.append((query, purpose, profile.profile_id))
        return [0.25, 0.5], {}

    def read_units(self, reference, subject):
        self.assertEqual(reference, {"name": subject.document_id})
        return deepcopy(self.units[subject.document_id])

    def add_document(self, identity, *, scope="personal", scope_id=None, **overrides):
        scope_id = scope_id or {"personal": "owner", "group": "group-1", "public": "public-1"}[scope]
        document = {
            "id": identity, "file_name": f"{identity}.txt", "version": 1, "_etag": f"etag-{identity}",
            "revision_family_id": f"family-{identity}", "is_current_version": True,
            "search_visibility_state": "active", "title": "Retention policy",
            "abstract": "Legal records", "authors": ["Alice"], "keywords": ["records"],
            "tags": ["keep"], "document_classification": "Restricted",
            "blob_path": "PRIVATE-STORAGE-PATH", "connection_secret": "PRIVATE-SECRET",
            {"personal": "user_id", "group": "group_id", "public": "public_workspace_id"}[scope]: scope_id,
            **overrides,
        }
        store = {"personal": self.personal, "group": self.group_documents, "public": self.public_documents}[scope]
        store.items[identity] = document
        self.index.rows.extend(self.catalog.build_document_access_index_rows(document))
        return document

    def add_hit(self, document, *, score=5.0, text="retention policy", version=None):
        scope = "public" if document.get("public_workspace_id") else "group" if document.get("group_id") else "personal"
        hit = {
            "id": f"hit-{len(self.search_clients[scope].hits)}",
            "document_id": document["id"], "chunk_text": text,
            "version": document["version"] if version is None else version,
            "@search.score": score,
            "file_name": document["file_name"],
            **{field: document[field] for field in ("user_id", "group_id", "public_workspace_id") if field in document},
        }
        self.search_clients[scope].hits.append(hit)
        return hit

    def mark_screened(self, document, text="retention policy"):
        units = [ContentUnit("unit", text, {"page_number": 1})]
        self.units[document["id"]] = [unit.to_dict() for unit in units]
        marker = {
            "state": "cleared", "scan_id": f"scan-{document['id']}", "source_revision": str(document["version"]),
            "content_fingerprint": content_fingerprint(units), "canonical_ref": {"name": document["id"]},
            "availability_generation": 1,
            "active_blob": {"container": "private", "path": "private-screened-blob", "etag": "approved"},
        }
        policy = {"test": "approved"}
        marker["policy_fingerprint"] = hash_payload(policy)
        document["content_screening"] = marker
        self.scans.items[marker["scan_id"]] = {
            "id": marker["scan_id"], "kind": "scan",
            "subject": subject_from_document(document).to_dict(),
            "state": "cleared", "coverage_complete": True, "result_status": "pass",
            "policy": policy, "policy_fingerprint": marker["policy_fingerprint"],
            "content_fingerprint": marker["content_fingerprint"], "units_ref": marker["canonical_ref"],
            "publication": {
                "active_blob": marker["active_blob"],
                "metadata_fingerprint": metadata_fingerprint(document),
                "content_fingerprint": marker["content_fingerprint"],
            },
        }

    @staticmethod
    def selected(*identities, scope="personal", scope_id=None):
        return {
            "kind": "documents",
            "documents": [
                {"document_id": identity, "scope_type": scope, **({"scope_id": scope_id} if scope_id else {})}
                for identity in identities
            ],
        }

    @staticmethod
    def query(*, content=None, count=None, scopes=None, filters=None):
        return {
            "kind": "workspace_query",
            "scopes": scopes or [{"scope_type": "personal"}],
            "filters": filters or {},
            "selection": {"mode": "best_n", "count": count} if count is not None else {"mode": "all_matches"},
            **({"content": content} if content is not None else {}),
        }

    def resolve(self, iterable, *, max_items=500, workflow=None, **kwargs):
        return list(iter_workflow_loop_documents(
            workflow or self.workflow, iterable, actor_user_id="owner",
            max_items=max_items, settings=self.settings, **kwargs,
        ))

    def analyze_snapshot(self, document, *, scope, scope_id):
        def context_resolver(**arguments):
            self.assertEqual(arguments["user_id"], "owner")
            self.assertEqual(arguments["document_id"], document["id"])
            self.assertEqual(arguments["doc_scope"], scope)
            self.assertEqual(arguments["active_group_ids"], [scope_id] if scope == "group" else [])
            return {
                "scope": scope, "document": deepcopy(document),
                "group_id": scope_id if scope == "group" else None,
                "public_workspace_id": scope_id if scope == "public" else None,
            }

        manifest = resolve_authorized_source_manifest(
            [document["id"]], user_id="owner", doc_scope=scope,
            active_group_ids=[scope_id] if scope == "group" else [],
            active_public_workspace_ids=[scope_id] if scope == "public" else [],
            context_resolver=context_resolver,
        )
        self.assertEqual(manifest[0]["authorization_status"], "authorized")
        return analysis_source_snapshot(manifest)[0]

    def test_explicit_order_safe_projection_and_exact_reauthorization(self):
        self.add_document("a")
        self.add_document("b")
        capture = {}
        entries = self.resolve(self.selected("b", "a"), capture_metadata=capture)
        self.assertEqual([entry["document"]["document_id"] for entry in entries], ["b", "a"])
        self.assertEqual(set(entries[0]), {"document", "source", "availability"})
        self.assertEqual(set(entries[0]["document"]), {"document_id", "file_name", "scope_type", "scope_id"})
        self.assertNotIn("PRIVATE", json.dumps(entries))
        self.assertEqual(entries[0]["source"]["source_revision"], "etag-b")
        self.assertTrue(capture["complete"])
        self.assertEqual((capture["count"], capture["count_exact"]), (2, True))
        self.assertEqual(
            reauthorize_workflow_loop_document(self.workflow, entries[0], actor_user_id="owner"),
            entries[0],
        )

    def test_duplicate_and_forged_personal_inputs_fail_before_source_reads(self):
        self.add_document("a")
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.selected("a", "a"))
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.selected("a", scope_id="another-owner"))
        self.assertFalse(self.personal.reads)
        with self.assertRaises(WorkflowLoopInputError):
            list(iter_workflow_loop_documents(
                self.workflow, self.selected("a"), actor_user_id="another-owner", max_items=500,
            ))

    def test_frozen_envelope_fields_are_accepted_without_mutation_or_echo(self):
        self.add_document("a")
        entry = self.resolve(self.selected("a"))[0]
        frozen = {
            **deepcopy(entry), "kind": "document", "index": 0,
            "item_id": "1" * 64, "item_sha256": "2" * 64,
        }
        before = deepcopy(frozen)
        current = reauthorize_workflow_loop_document(self.workflow, frozen, actor_user_id="owner")
        self.assertEqual(current, entry)
        self.assertEqual(frozen, before)
        frozen["availability"]["source_revision"] = "forged"
        with self.assertRaises(WorkflowLoopInputError):
            reauthorize_workflow_loop_document(self.workflow, frozen, actor_user_id="owner")
        frozen = {**before, "kind": "record"}
        with self.assertRaises(WorkflowLoopInputError):
            reauthorize_workflow_loop_document(self.workflow, frozen, actor_user_id="owner")

    def test_projection_candidates_are_not_permission_grants(self):
        other = self.add_document("other", scope_id="stranger")
        forged_row = next(
            row for row in self.catalog.build_document_access_index_rows({
                **other, "shared_user_ids": ["owner,approved"],
            }) if row["scope_key"] == "user:owner"
        )
        self.index.rows.append(forged_row)
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.query())
        self.add_hit(other)
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.query(content={"mode": "keyword", "query": "retention"}))

    def test_group_scope_policy_and_current_membership_are_authoritative(self):
        self.add_document("group-doc", scope="group")
        group_workflow = {**self.workflow, "group_id": "group-1"}
        entries = self.resolve(self.selected("group-doc", scope="group", scope_id="group-1"), workflow=group_workflow)
        self.assertEqual(entries[0]["source"]["scope_id"], "group-1")
        with self.assertRaises(WorkflowLoopInputError) as raised:
            self.resolve(self.query(scopes=[{"scope_type": "group", "scope_id": "group-2"}]), workflow=group_workflow)
        self.assertEqual(raised.exception.code, "workflow_loop_scope_forbidden")
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.query(), workflow=group_workflow)
        self.memberships.remove(("owner", "group-1"))
        with self.assertRaises(WorkflowLoopInputError):
            reauthorize_workflow_loop_document(group_workflow, entries[0], actor_user_id="owner")
        self.assertTrue(all(user == "owner" for user, _group, _roles in self.scope_checks))

    def test_shared_documents_deduplicate_by_actual_source_not_access_path(self):
        document = self.add_document(
            "shared", scope="group", scope_id="group-2", shared_group_ids=["group-1,approved"],
        )
        entries = self.resolve(self.query(scopes=[
            {"scope_type": "group", "scope_id": "group-2"},
            {"scope_type": "group", "scope_id": "group-1"},
        ]))
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["document"]["scope_id"], "group-1")
        self.assertEqual(entries[0]["availability"]["scope_id"], "group-2")
        document["shared_group_ids"] = ["group-1,not_approved"]
        with self.assertRaises(WorkflowLoopInputError):
            reauthorize_workflow_loop_document(self.workflow, entries[0], actor_user_id="owner")

    def test_duplicate_revision_projections_count_only_the_current_source(self):
        self.add_document("old", version=1, revision_family_id="family", is_current_version=False)
        current = self.add_document("current", version=2, revision_family_id="family")
        self.index.rows.extend(self.catalog.build_document_access_index_rows(current))
        entries = self.resolve(self.query(), max_items=1)
        self.assertEqual([entry["document"]["document_id"] for entry in entries], ["current"])
        self.assertEqual(entries[0]["source"]["source_version"], 2)

    def test_personal_sharing_keeps_dispatch_scope_and_analyze_source_semantics(self):
        document = self.add_document("shared", scope_id="source-owner", shared_user_ids=["owner,approved"])
        entry = self.resolve(self.selected("shared"))[0]
        self.assertEqual(entry["source"]["scope_id"], "source-owner")
        self.assertEqual(entry["document"]["scope_id"], "owner")
        self.assertEqual(entry["availability"]["scope_id"], "source-owner")
        self.assertEqual(entry["source"], self.analyze_snapshot(document, scope="personal", scope_id="owner"))
        self.assertEqual(
            reauthorize_workflow_loop_document(self.workflow, entry, actor_user_id="owner"), entry,
        )
        self.assertEqual(self.resolve(self.query())[0], entry)
        self.add_hit(document)
        self.assertEqual(
            self.resolve(self.query(content={"mode": "keyword", "query": "retention"})),
            [entry],
        )
        document["shared_user_ids"] = []
        with self.assertRaises(WorkflowLoopInputError):
            reauthorize_workflow_loop_document(self.workflow, entry, actor_user_id="owner")

    def test_group_sharing_works_with_membership_only_in_the_recipient_group(self):
        self.memberships.remove(("owner", "group-2"))
        document = self.add_document(
            "shared", scope="group", scope_id="group-2", shared_group_ids=["group-1,approved"],
        )
        workflow = {**self.workflow, "group_id": "group-1"}
        entry = self.resolve(
            self.selected("shared", scope="group", scope_id="group-1"), workflow=workflow,
        )[0]
        self.assertEqual(entry["document"]["scope_id"], "group-1")
        self.assertEqual(entry["source"]["scope_id"], "group-1")
        self.assertEqual(entry["availability"]["scope_id"], "group-2")
        self.assertEqual(entry["source"], self.analyze_snapshot(document, scope="group", scope_id="group-1"))
        self.assertEqual(
            reauthorize_workflow_loop_document(workflow, entry, actor_user_id="owner"), entry,
        )
        self.assertEqual(
            self.resolve(self.query(scopes=[{"scope_type": "group", "scope_id": "group-1"}]), workflow=workflow),
            [entry],
        )
        self.assertTrue(all(group_id == "group-1" for _user, group_id, _roles in self.scope_checks))
        self.add_hit(document)
        for mode in ("keyword", "hybrid"):
            with self.subTest(mode=mode):
                self.assertEqual(
                    self.resolve(self.query(
                        scopes=[{"scope_type": "group", "scope_id": "group-1"}],
                        content={"mode": mode, "query": "retention"},
                        count=1 if mode == "hybrid" else None,
                    ), workflow=workflow),
                    [entry],
                )
        self.assertNotIn(("owner", "group-2"), self.memberships)

    def test_source_version_fallback_matches_analyze_snapshot_semantics(self):
        document = self.add_document("legacy-version", version=None, source_version=7)
        entry = self.resolve(self.selected("legacy-version"))[0]
        self.assertEqual(entry["source"]["source_version"], 7)
        self.assertEqual(entry["source"], self.analyze_snapshot(document, scope="personal", scope_id="owner"))

    def test_public_scope_uses_explicit_current_workspace_not_active_preferences(self):
        self.add_document("public", scope="public")
        entry = self.resolve(self.selected("public", scope="public", scope_id="public-1"))[0]
        self.workspaces["public-1"]["status"] = "inactive"
        with self.assertRaises(WorkflowLoopInputError):
            reauthorize_workflow_loop_document(self.workflow, entry, actor_user_id="owner")

    def test_precise_500_and_501_query_admission(self):
        for number in range(500):
            self.add_document(f"doc-{number:04d}")
        self.assertEqual(len(self.resolve(self.query())), 500)
        self.add_document("doc-0500")
        capture = {}
        yielded = []
        with self.assertRaises(WorkflowLoopLimitError) as raised:
            for entry in iter_workflow_loop_documents(
                self.workflow, self.query(), actor_user_id="owner", max_items=500,
                settings=self.settings, capture_metadata=capture,
            ):
                yielded.append(entry)
        self.assertFalse(yielded)
        self.assertEqual((raised.exception.count, raised.exception.count_exact, raised.exception.limit), (501, False, 500))
        self.assertIn("at least 501", raised.exception.public_message)
        self.assertEqual((capture["count"], capture["count_exact"], capture["complete"]), (501, False, False))

    def test_configured_above_1000_uses_every_catalog_page(self):
        for number in range(1201):
            self.add_document(f"doc-{number:04d}")
        entries = self.resolve(self.query(), max_items=1500)
        self.assertEqual(len(entries), 1201)
        self.assertEqual(entries[-1]["document"]["document_id"], "doc-1200")
        self.assertGreater(self.index.responses[-1].pages_read, 10)
        self.assertTrue(all("TOP " not in request["query"] for request in self.index.requests))
        self.assertTrue(all(request["page_size"] == 100 for request in self.index.requests))
        with self.assertRaises(WorkflowLoopLimitError) as raised:
            self.resolve(self.selected(*(f"doc-{number:04d}" for number in range(1201))), max_items=1200)
        self.assertEqual((raised.exception.count, raised.exception.count_exact), (1201, True))

    def test_hard_max_plus_one_is_a_precise_limit_error_without_reads(self):
        with self.assertRaises(WorkflowLoopLimitError) as raised:
            self.resolve(self.selected(*(f"doc-{number}" for number in range(5001))), max_items=5000)
        self.assertEqual(
            (raised.exception.count, raised.exception.count_exact, raised.exception.limit),
            (5001, True, 5000),
        )
        self.assertFalse(self.personal.reads)

    def test_parent_preview_handler_preserves_precise_limit_errors(self):
        source = ast.parse((APP_ROOT / "route_backend_workflows.py").read_text(encoding="utf-8"))
        function = next(
            node for node in source.body
            if isinstance(node, ast.FunctionDef) and node.name == "_workflow_loop_preview_response"
        )
        self.add_document("a")
        self.add_document("b")
        self.settings["workflow_max_loop_items"] = 1
        namespace = {
            "get_current_user_id": lambda: "owner",
            "get_settings": lambda: deepcopy(self.settings),
            "_assert_personal_workflow_draft_access": lambda _settings: None,
            "request": SimpleNamespace(get_json=lambda **_kwargs: {"iterable": self.query(), "max_items": 2}),
            "jsonify": lambda payload: payload,
        }
        exec(
            compile(ast.Module(body=[function], type_ignores=[]), "parent_loop_preview", "exec"),
            namespace,
        )
        payload, status = namespace["_workflow_loop_preview_response"]()
        self.assertEqual(status, 422)
        self.assertEqual((payload["count"], payload["count_exact"], payload["limit"]), (2, False, 1))
        self.assertFalse(payload["within_limit"])
        self.assertIn("at least 2", payload["error"])

    def test_metadata_filters_use_current_document_list_semantics_on_later_pages(self):
        for number in range(1102):
            self.add_document(f"doc-{number:04d}", title="Unrelated")
        self.personal.items["doc-1101"]["title"] = "Retention policy"
        entries = self.resolve(self.query(filters={
            "search": "retention", "classification": "Restricted", "author": "ali",
            "keywords": "record", "abstract": "legal", "tags": ["keep"],
        }), max_items=10)
        self.assertEqual([entry["document"]["document_id"] for entry in entries], ["doc-1101"])

    def test_keyword_all_matches_does_not_inherit_chat_chunk_caps(self):
        for number in range(1105):
            self.add_hit(self.add_document(f"doc-{number:04d}"))
        capture = {}
        entries = self.resolve(
            self.query(content={"mode": "keyword", "query": "retention"}),
            max_items=1500, capture_metadata=capture,
        )
        self.assertEqual(len(entries), 1105)
        self.assertTrue(capture["exhaustive"])
        request = self.search_clients["personal"].requests[0]
        self.assertNotIn("top", request)
        self.assertNotIn("vector_queries", request)
        self.assertEqual(request["search_fields"], ["chunk_text"])
        self.assertIn("shared_user_ids/any", request["filter"])
        self.assertIn("embedding_profile_id eq 'current-profile'", request["filter"])
        self.assertGreater(len(self.profile_slots), 20)
        self.assertFalse(self.embedding_calls)

    def test_best_n_keyword_ranks_unique_documents_with_deterministic_ties(self):
        first, second, third = (self.add_document(identity) for identity in ("a", "b", "c"))
        for _number in range(600):
            self.add_hit(first, score=10)
        self.add_hit(third, score=9)
        self.add_hit(second, score=9)
        capture = {}
        entries = self.resolve(
            self.query(content={"mode": "keyword", "query": "retention"}, count=3),
            capture_metadata=capture,
        )
        self.assertEqual([entry["document"]["document_id"] for entry in entries], ["a", "b", "c"])
        self.assertFalse(capture["exhaustive"])
        self.assertEqual(capture["count"], 3)

    def test_keyword_limit_counts_documents_not_duplicate_chunks(self):
        first = self.add_document("a")
        for _number in range(600):
            self.add_hit(first)
        self.add_hit(self.add_document("b"))
        iterable = self.query(content={"mode": "keyword", "query": "retention"})
        self.assertEqual(len(self.resolve(iterable, max_items=2)), 2)
        with self.assertRaises(WorkflowLoopLimitError) as raised:
            self.resolve(iterable, max_items=1)
        self.assertEqual((raised.exception.count, raised.exception.count_exact), (2, False))

    def test_hybrid_backfills_duplicate_candidate_windows_at_document_level(self):
        first, second, third = (self.add_document(identity) for identity in ("a", "b", "c"))
        for _number in range(1000):
            self.add_hit(first, score=10)
        self.add_hit(third, score=9)
        self.add_hit(second, score=9)
        capture = {}
        entries = self.resolve(
            self.query(content={"mode": "hybrid", "query": "retention obligations"}, count=3),
            capture_metadata=capture,
        )
        self.assertEqual([entry["document"]["document_id"] for entry in entries], ["a", "b", "c"])
        requests = self.search_clients["personal"].requests
        self.assertEqual(len(requests), 2)
        self.assertIn("not search.in(document_id, 'a', '|')", requests[1]["filter"])
        self.assertEqual(requests[0]["vector_queries"][0].k_nearest_neighbors, 1000)
        self.assertEqual(requests[0]["semantic_error_mode"], "fail")
        self.assertEqual(capture["candidate_expansion_rounds"], 1)
        self.assertEqual(capture["semantic_rerank_window"], 50)
        self.assertTrue(capture["candidate_limitations"])
        self.assertFalse(capture["exhaustive"])

    def test_hybrid_configured_above_1000_expands_without_a_document_ceiling(self):
        for number in range(1201):
            self.add_hit(self.add_document(f"doc-{number:04d}"))
        entries = self.resolve(
            self.query(content={"mode": "hybrid", "query": "retention"}, count=1201),
            max_items=1500,
        )
        self.assertEqual(len(entries), 1201)
        self.assertEqual(entries[-1]["document"]["document_id"], "doc-1200")
        self.assertEqual(len(self.search_clients["personal"].requests), 2)

    def test_explicit_best_n_must_fit_effective_ceiling(self):
        with self.assertRaises(WorkflowLoopLimitError):
            self.resolve(self.query(content={"mode": "hybrid", "query": "retention"}, count=51), max_items=50)
        self.assertFalse(self.search_clients["personal"].requests)

    def test_empty_collection_is_explicit_and_distinct_from_failed_catalog(self):
        for iterable in (self.selected(), self.query()):
            capture = {}
            self.assertEqual(self.resolve(iterable, capture_metadata=capture), [])
            self.assertEqual((capture["count"], capture["count_exact"], capture["complete"]), (0, True, True))
        self.settings_store.items["document_access_index_backfill_state"]["status"] = "running"
        capture = {}
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.query(), capture_metadata=capture)
        self.assertFalse(capture["complete"])
        self.assertFalse(capture["count_exact"])

    def test_catalog_backlog_and_failed_continuations_are_not_empty_success(self):
        self.add_document("a")
        self.settings_store.items["repair"] = {
            "id": "repair", "type": "document_access_index_repair", "status": "repair_required",
        }
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.query())
        del self.settings_store.items["repair"]
        self.index.incomplete = True
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(self.query())
        self.index.incomplete = False
        self.index.failure_page = 1
        with self.assertRaises(WorkflowLoopInputError) as raised:
            self.resolve(self.query())
        self.assertNotIn("PRIVATE", raised.exception.public_message)

    def test_search_errors_quota_and_failed_continuations_have_safe_public_errors(self):
        self.add_hit(self.add_document("a"))
        client = self.search_clients["personal"]
        iterable = self.query(content={"mode": "keyword", "query": "retention"})
        for failure in ("backend", "quota", "continuation", "page"):
            with self.subTest(failure=failure):
                client.error = RuntimeError("PRIVATE-ENDPOINT?credential=PRIVATE-SECRET") if failure in {"backend", "quota"} else None
                if failure == "quota":
                    client.error.quota = True
                client.incomplete = failure == "continuation"
                client.failure_page = 1 if failure == "page" else None
                capture = {}
                with self.assertRaises(WorkflowLoopInputError) as raised:
                    self.resolve(iterable, capture_metadata=capture)
                self.assertNotIn("PRIVATE", str(raised.exception))
                self.assertFalse(capture["complete"])
                self.assertFalse(capture["count_exact"])

    def test_source_revision_screening_generation_and_receipt_forgery_fail_closed(self):
        document = self.add_document("a")
        self.mark_screened(document)
        entry = self.resolve(self.selected("a"))[0]
        for field, value in (("_etag", "changed"), ("version", 2)):
            original = document[field]
            document[field] = value
            with self.assertRaises(WorkflowLoopInputError):
                reauthorize_workflow_loop_document(self.workflow, entry, actor_user_id="owner")
            document[field] = original
        document["content_screening"]["availability_generation"] = 2
        with self.assertRaises(WorkflowLoopInputError) as raised:
            reauthorize_workflow_loop_document(self.workflow, entry, actor_user_id="owner")
        self.assertEqual(raised.exception.code, "workflow_loop_source_changed")
        document["content_screening"]["availability_generation"] = 1
        forged = deepcopy(entry)
        forged["source"]["storage_locator"] = {"path": "PRIVATE"}
        with self.assertRaises(WorkflowLoopInputError):
            reauthorize_workflow_loop_document(self.workflow, forged, actor_user_id="owner")

    def test_late_source_change_never_marks_a_staged_prefix_complete(self):
        self.add_document("a")
        second = self.add_document("b")
        capture = {}
        entries = iter_workflow_loop_documents(
            self.workflow, self.selected("a", "b"), actor_user_id="owner",
            max_items=500, capture_metadata=capture,
        )
        self.assertEqual(next(entries)["document"]["document_id"], "a")
        second["_etag"] = "changed-after-first-page-write"
        with self.assertRaises(WorkflowLoopInputError):
            list(entries)
        self.assertFalse(capture["complete"])
        self.assertFalse(capture["count_exact"])

    def test_only_current_screened_keyword_representations_are_usable(self):
        document = self.add_document("a")
        self.mark_screened(document)
        self.add_hit(document)
        iterable = self.query(content={"mode": "keyword", "query": "retention"})
        self.assertEqual(len(self.resolve(iterable)), 1)
        self.search_clients["personal"].hits[0]["chunk_text"] = "Removed unscreened text"
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(iterable)
        self.search_clients["personal"].hits[0]["chunk_text"] = "retention policy"
        document["content_screening"]["state"] = "held"
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(iterable)

    def test_stale_chunk_revisions_do_not_count_as_current_matches(self):
        document = self.add_document("a", version=2)
        self.add_hit(document, version=1)
        capture = {}
        entries = self.resolve(
            self.query(content={"mode": "keyword", "query": "retention"}), capture_metadata=capture,
        )
        self.assertEqual(entries, [])
        self.assertTrue(capture["complete"])
        self.assertTrue(capture["count_exact"])

    def test_invalid_rank_or_missing_indexed_content_is_not_empty_success(self):
        hit = self.add_hit(self.add_document("a"))
        iterable = self.query(content={"mode": "keyword", "query": "retention"}, count=1)
        hit["@search.score"] = float("nan")
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(iterable)
        hit["@search.score"] = 1
        del hit["chunk_text"]
        with self.assertRaises(WorkflowLoopInputError):
            self.resolve(iterable)

    def test_source_filter_values_are_odata_escaped(self):
        list(self.search.iter_document_query_search_pages(
            "retention", "actor'quoted", scope_type="group", scope_id="group'quoted",
        ))
        expression = self.search_clients["group"].requests[0]["filter"]
        self.assertIn("group_id eq 'group''quoted'", expression)
        self.assertIn("g eq 'group''quoted,approved'", expression)

    def test_cancellation_check_is_not_disguised_as_backend_failure(self):
        class Cancelled(Exception):
            pass

        self.add_document("a")
        cancellation = Cancelled("Run cancelled")

        def check():
            raise cancellation

        with self.assertRaises(Cancelled) as raised:
            self.resolve(self.query(), check=check)
        self.assertIs(raised.exception, cancellation)
        self.assertFalse(self.index.requests)


if __name__ == "__main__":
    unittest.main()
