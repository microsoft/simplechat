# test_xsd_ingestion_generation_integration.py
"""
Functional tests for XSD ingestion and schema-bound XML publication.
Version: 0.250.160
Implemented in: 0.250.160

These tests exercise the application integration boundaries without loading
Azure-backed application configuration. They verify current-revision lookup,
one-summary indexing, dependent revalidation, upload capability propagation,
schema-source evidence isolation, and validation-before-publication behavior
for chat and workflow XML artifacts.
"""

import ast
import hashlib
import importlib.util
import logging
import os
import sys
import tempfile
import types
from datetime import datetime, timezone
from pathlib import Path

from test_support.versioning import assert_app_version_at_least


ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = ROOT / "application" / "single_app"
DOCUMENTS_FILE = APP_ROOT / "functions_documents.py"
CHAT_ROUTE_FILE = APP_ROOT / "route_backend_chats.py"
WORKFLOW_RUNNER_FILE = APP_ROOT / "functions_workflow_runner.py"
GENERATED_EXPORTS_FILE = APP_ROOT / "functions_generated_file_exports.py"
CHAT_FRONTEND_ROUTE_FILE = APP_ROOT / "route_frontend_chats.py"
CHAT_TEMPLATE_FILE = APP_ROOT / "templates" / "chats.html"
if str(APP_ROOT) not in sys.path:
    sys.path.insert(0, str(APP_ROOT))

import functions_xsd_schema as xsd  # noqa: E402


def _read_text(path):
    return path.read_text(encoding="utf-8")


def _load_nodes(path, names, namespace):
    tree = ast.parse(_read_text(path), filename=str(path))
    selected = [
        node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.ClassDef))
        and node.name in names
    ]
    if len(selected) != len(names):
        found = {node.name for node in selected}
        raise AssertionError(f"Missing definitions in {path.name}: {set(names) - found}")
    exec(
        compile(ast.Module(body=selected, type_ignores=[]), str(path), "exec"),
        namespace,
    )
    return namespace


def _load_generated_exports():
    spec = importlib.util.spec_from_file_location(
        "functions_generated_file_exports",
        GENERATED_EXPORTS_FILE,
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_xsd_query_excludes_archived_revisions():
    """Dependency resolution queries the actual current-version field."""
    captured = {}

    class FakeContainer:
        def query_items(self, *, query, parameters, enable_cross_partition_query):
            captured.update({
                "query": query,
                "parameters": parameters,
                "cross_partition": enable_cross_partition_query,
            })
            documents = [
                {"id": "current", "is_current_version": True},
                {"id": "archived", "is_current_version": False},
            ]
            if "c.is_current_version" in query:
                return [documents[0]]
            return documents

    namespace = {
        "_get_documents_container": lambda **kwargs: FakeContainer(),
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"_query_current_xsd_documents"},
        namespace,
    )
    results = namespace["_query_current_xsd_documents"]("owner")

    assert [item["id"] for item in results] == ["current"]
    assert "c.is_current_version" in captured["query"]
    assert "c.is_current)" not in captured["query"]


def test_shared_personal_xsd_dependencies_use_owner_workspace_and_individual_access():
    """A shared root cannot grant access to an unshared owner dependency."""
    root_bytes = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           xmlns:t="urn:shared"
           targetNamespace="urn:shared"
           elementFormDefault="qualified">
  <xs:include schemaLocation="common.xsd"/>
  <xs:element name="root" type="t:RootType"/>
</xs:schema>
"""
    dependency_bytes = b"""<?xml version="1.0"?>
<xs:schema xmlns:xs="http://www.w3.org/2001/XMLSchema"
           targetNamespace="urn:shared"
           elementFormDefault="qualified">
  <xs:complexType name="RootType">
    <xs:sequence>
      <xs:element name="value" type="xs:string"/>
    </xs:sequence>
  </xs:complexType>
</xs:schema>
"""
    root_document = {
        "id": "root",
        "user_id": "owner",
        "file_name": "root.xsd",
        "xsd_logical_path": "schemas/root.xsd",
        "source_kind": "xml_schema",
        "is_current_version": True,
    }
    dependency_document = {
        "id": "dependency",
        "user_id": "owner",
        "file_name": "common.xsd",
        "xsd_logical_path": "schemas/common.xsd",
        "source_kind": "xml_schema",
        "is_current_version": True,
        "shared_user_ids": ["viewer,pending"],
    }
    queried_owners = []
    blob_reads = []
    authorization = {"allowed": False}

    def get_document_metadata(**kwargs):
        assert kwargs["user_id"] == "viewer"
        if kwargs["document_id"] != "dependency":
            return None
        dependency_document["shared_user_ids"] = [
            f"viewer,{'approved' if authorization['allowed'] else 'pending'}"
        ]
        return dependency_document

    namespace = {
        "hashlib": hashlib,
        "get_document_metadata": get_document_metadata,
        "normalize_xsd_logical_path": xsd.normalize_xsd_logical_path,
        "_query_current_xsd_documents": (
            lambda owner_user_id, **kwargs: queried_owners.append(owner_user_id)
            or [root_document, dependency_document]
        ),
        "inspect_xsd_bytes": xsd.inspect_xsd_bytes,
        "resolve_xsd_dependency_path": xsd.resolve_xsd_dependency_path,
        "compile_xsd_graph": xsd.compile_xsd_graph,
        "XsdSchemaError": xsd.XsdSchemaError,
        "ERR_DEPENDENCY_MISSING": xsd.ERR_DEPENDENCY_MISSING,
        "_read_verified_xsd_blob": (
            lambda document, *args, **kwargs: blob_reads.append(document["id"])
            or {"bytes": dependency_bytes}
        ),
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {
            "_xsd_document_has_approved_scope_access",
            "_get_authorized_xsd_dependency_document",
            "_build_xsd_graph_source_record",
            "_compile_xsd_workspace_graph",
        },
        namespace,
    )

    try:
        namespace["_compile_xsd_workspace_graph"](
            root_document,
            root_bytes,
            "viewer",
        )
    except xsd.XsdSchemaError as exc:
        assert exc.code == xsd.ERR_DEPENDENCY_MISSING
        assert "unavailable or ambiguous" in str(exc)
    else:
        raise AssertionError("An unshared dependency must fail closed")
    assert queried_owners == ["owner"]
    assert blob_reads == []

    authorization["allowed"] = True
    graph = namespace["_compile_xsd_workspace_graph"](
        root_document,
        root_bytes,
        "viewer",
    )
    assert queried_owners == ["owner", "owner"]
    assert blob_reads == ["dependency"]
    assert xsd.validate_xml_bytes(
        b'<root xmlns="urn:shared"><value>ok</value></root>',
        graph,
    )["valid"] is True


def test_archived_xsd_cannot_be_loaded_as_a_generation_contract():
    """An authorized historical revision remains downloadable but not generative."""
    namespace = {
        "_require_xsd_request_scope_access": lambda *args, **kwargs: None,
        "get_document_metadata": lambda **kwargs: {
            "id": "archived-root",
            "source_kind": "xml_schema",
            "xsd_schema_status": "ready",
            "is_current_version": False,
            "user_id": "owner",
        },
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"load_xsd_generation_contract"},
        namespace,
    )
    try:
        namespace["load_xsd_generation_contract"](
            [{
                "document_id": "archived-root",
                "source_kind": "xml_schema",
                "authorization_status": "authorized",
                "scope": "personal",
            }],
            "owner",
        )
    except ValueError as exc:
        assert "archived" in str(exc).lower()
    else:
        raise AssertionError("An archived XSD revision must not govern new XML")


def test_final_xsd_contract_refresh_reauthorizes_and_detects_graph_drift():
    """Publication refreshes the whole graph and rejects changed dependencies."""
    root_document = {
        "id": "root",
        "user_id": "owner",
        "source_kind": "xml_schema",
        "xsd_schema_status": "ready",
        "is_current_version": True,
    }
    original_sources = [{
        "document_id": "root",
        "logical_path": "root.xsd",
        "sha256": "root-digest",
        "version": "1",
        "user_id": "owner",
        "group_id": "",
        "public_workspace_id": "",
        "is_current_version": True,
    }]
    refreshed_sources = list(original_sources)
    compiled_graph = object()
    namespace = {
        "_require_xsd_request_scope_access": lambda *args, **kwargs: None,
        "get_document_metadata": lambda **kwargs: root_document,
        "_xsd_document_has_approved_scope_access": (
            lambda document, user_id, **kwargs: user_id == "owner"
        ),
        "_read_verified_xsd_blob": (
            lambda *args, **kwargs: {"bytes": b"<schema/>"}
        ),
        "_compile_xsd_workspace_graph": (
            lambda *args, **kwargs: (compiled_graph, refreshed_sources)
        ),
        "_xsd_graph_source_identity": (
            lambda records: tuple(
                sorted(
                    (
                        record["document_id"],
                        record["logical_path"],
                        record["sha256"],
                    )
                    for record in records or []
                )
            )
        ),
        "build_xsd_generation_guidance": lambda graph: "fresh guidance",
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"refresh_xsd_generation_contract"},
        namespace,
    )
    contract = {
        "document_id": "root",
        "graph_sources": original_sources,
        "compiled_graph": object(),
    }
    refreshed = namespace["refresh_xsd_generation_contract"](
        contract,
        "owner",
    )
    assert refreshed["compiled_graph"] is compiled_graph
    assert refreshed["guidance"] == "fresh guidance"

    refreshed_sources = [{
        **original_sources[0],
        "sha256": "changed-digest",
    }]
    namespace["_compile_xsd_workspace_graph"] = (
        lambda *args, **kwargs: (compiled_graph, refreshed_sources)
    )
    try:
        namespace["refresh_xsd_generation_contract"](contract, "owner")
    except ValueError as exc:
        assert "changed" in str(exc).lower()
    else:
        raise AssertionError("A changed schema graph must block publication")


def test_xsd_finalization_rechecks_workspace_membership():
    """Group/public contract refresh cannot rely only on matching document IDs."""
    group_module = types.ModuleType("functions_group")
    group_module.get_user_groups = lambda user_id: [{"id": "allowed-group"}]
    public_module = types.ModuleType("functions_public_workspaces")
    public_module.find_public_workspace_by_id = (
        lambda workspace_id: (
            {"id": workspace_id}
            if workspace_id == "allowed-public"
            else None
        )
    )
    public_module.is_user_in_public_workspace = (
        lambda workspace, user_id: bool(workspace) and user_id == "owner"
    )
    previous_group_module = sys.modules.get("functions_group")
    previous_public_module = sys.modules.get("functions_public_workspaces")
    sys.modules["functions_group"] = group_module
    sys.modules["functions_public_workspaces"] = public_module
    try:
        namespace = {}
        _load_nodes(
            DOCUMENTS_FILE,
            {"_require_xsd_request_scope_access"},
            namespace,
        )
        require_access = namespace["_require_xsd_request_scope_access"]
        require_access("owner", group_id="allowed-group")
        require_access("owner", public_workspace_id="allowed-public")

        for kwargs in (
            {"group_id": "revoked-group"},
            {"public_workspace_id": "deleted-public"},
        ):
            try:
                require_access("owner", **kwargs)
            except PermissionError:
                pass
            else:
                raise AssertionError("Revoked workspace access must fail closed")
    finally:
        if previous_group_module is None:
            sys.modules.pop("functions_group", None)
        else:
            sys.modules["functions_group"] = previous_group_module
        if previous_public_module is None:
            sys.modules.pop("functions_public_workspaces", None)
        else:
            sys.modules["functions_public_workspaces"] = previous_public_module


def test_xsd_processing_propagates_scope_and_refreshes_dependents():
    """The background processor rechecks storage capability in the owning scope."""
    calls = []
    source_bytes = b"<schema/>"
    document = {
        "id": "schema-1",
        "file_name": "orders.xsd",
        "xsd_logical_path": "schemas/orders.xsd",
        "source_file_available": True,
        "blob_path": "owner/xsd/schema-1/orders.xsd",
    }

    def require_capability(file_name, **kwargs):
        calls.append(("capability", file_name, kwargs))

    def evaluate_schema(document_item, payload, user_id, **kwargs):
        calls.append(("evaluate", document_item["id"], payload, user_id, kwargs))
        return {
            "logical_path": "schemas/orders.xsd",
            "status": "ready",
            "dependencies": [],
        }

    namespace = {
        "require_xsd_ingestion_capability": require_capability,
        "get_document_metadata": lambda **kwargs: document,
        "normalize_xsd_logical_path": lambda file_name, logical_path=None: logical_path or file_name,
        "inspect_xsd_bytes": lambda payload, logical_path: {
            "sha256": "digest",
            "logical_path": logical_path,
        },
        "_read_verified_xsd_blob": lambda *args, **kwargs: {
            "bytes": source_bytes,
            "sha256": "digest",
            "blob_etag": "etag",
        },
        "_evaluate_xsd_document_schema": evaluate_schema,
        "_store_xsd_document_schema_state": lambda *args, **kwargs: "ready",
        "_revalidate_xsd_workspace_dependents": (
            lambda *args, **kwargs: calls.append(("revalidate", args, kwargs))
        ),
        "log_event": lambda *args, **kwargs: None,
    }
    _load_nodes(DOCUMENTS_FILE, {"process_xsd"}, namespace)

    with tempfile.NamedTemporaryFile(suffix=".xsd", delete=False) as source_file:
        source_file.write(source_bytes)
        source_file.flush()
        source_file_path = source_file.name
    try:
        namespace["process_xsd"](
            document_id="schema-1",
            user_id="owner",
            temp_file_path=source_file_path,
            original_filename="orders.xsd",
            update_callback=lambda **kwargs: calls.append(("update", kwargs)),
            group_id="group-1",
        )
    finally:
        Path(source_file_path).unlink(missing_ok=True)

    capability_call = next(call for call in calls if call[0] == "capability")
    assert capability_call[2]["user_id"] == "owner"
    assert capability_call[2]["group_id"] == "group-1"
    revalidation_call = next(call for call in calls if call[0] == "revalidate")
    assert revalidation_call[1][0] == "schemas/orders.xsd"
    assert revalidation_call[2]["exclude_document_id"] == "schema-1"


def test_xsd_source_staging_verifies_exact_bytes_and_cleans_failed_uploads():
    """Only newly created, unverified immutable source blobs are cleaned up."""
    source_bytes = b"<xs:schema xmlns:xs='http://www.w3.org/2001/XMLSchema'/>"

    class FakeCapabilityError(Exception):
        def __init__(self, message, *, code, http_status):
            super().__init__(message)
            self.code = code
            self.http_status = http_status

    class FakeResourceExistsError(Exception):
        pass

    class FakeDownload:
        def __init__(self, payload):
            self.payload = payload

        def readall(self):
            return self.payload

    class FakeProperties:
        etag = "etag-1"

    class FakeBlobClient:
        def __init__(self, payload, *, already_exists=False):
            self.payload = payload
            self.already_exists = already_exists
            self.deleted = False
            self.uploads = []

        def upload_blob(self, payload, **kwargs):
            self.uploads.append((payload, kwargs))
            if self.already_exists:
                raise FakeResourceExistsError()

        def download_blob(self):
            return FakeDownload(self.payload)

        def get_blob_properties(self):
            return FakeProperties()

        def delete_blob(self):
            self.deleted = True

    class FakeContainer:
        def __init__(self, blob_client):
            self.blob_client = blob_client

        def get_blob_client(self, blob_path):
            assert blob_path == "owner/xsd/schema-1/orders.xsd"
            return self.blob_client

    active_blob = [FakeBlobClient(source_bytes)]
    namespace = {
        "os": os,
        "hashlib": hashlib,
        "logging": logging,
        "XSD_PROFILE_ID": "profile",
        "XsdIngestionCapabilityError": FakeCapabilityError,
        "ResourceExistsError": FakeResourceExistsError,
        "inspect_xsd_bytes": lambda payload, logical_path: {
            "sha256": hashlib.sha256(payload).hexdigest(),
            "logical_path": logical_path,
        },
        "_build_immutable_xsd_blob_path": (
            lambda *args, **kwargs: "owner/xsd/schema-1/orders.xsd"
        ),
        "_get_blob_service_client": lambda: object(),
        "_ensure_blob_container_ready": (
            lambda client, container_name: FakeContainer(active_blob[0])
        ),
        "log_event": lambda *args, **kwargs: None,
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"_persist_xsd_source_before_create"},
        namespace,
    )
    helper = namespace["_persist_xsd_source_before_create"]

    with tempfile.NamedTemporaryFile(suffix=".xsd", delete=False) as source_file:
        source_file.write(source_bytes)
        source_file.flush()
        source_file_path = source_file.name
    try:
        staged = helper(
            source_file_path,
            "orders.xsd",
            "schema-1",
            {"logical_path": "orders.xsd", "container_name": "documents"},
            user_id="owner",
        )
        assert staged["created"] is True
        assert staged["blob_etag"] == "etag-1"
        assert active_blob[0].uploads[0][0] == source_bytes
        assert active_blob[0].uploads[0][1]["overwrite"] is False
        assert active_blob[0].deleted is False

        active_blob[0] = FakeBlobClient(source_bytes)
        try:
            helper(
                source_file_path,
                "orders.xsd",
                "schema-1",
                {
                    "logical_path": "orders.xsd",
                    "container_name": "documents",
                    "max_file_size_bytes": 1,
                },
                user_id="owner",
            )
        except FakeCapabilityError as exc:
            assert exc.code == "xsd_file_too_large"
        else:
            raise AssertionError("An oversized XSD must be rejected before Blob upload")
        assert active_blob[0].uploads == []

        active_blob[0] = FakeBlobClient(b"corrupted")
        try:
            helper(
                source_file_path,
                "orders.xsd",
                "schema-1",
                {"logical_path": "orders.xsd", "container_name": "documents"},
                user_id="owner",
            )
        except FakeCapabilityError as exc:
            assert exc.code == "xsd_exact_source_verification_failed"
        else:
            raise AssertionError("A corrupted newly staged XSD must be rejected")
        assert active_blob[0].deleted is True

        active_blob[0] = FakeBlobClient(b"corrupted", already_exists=True)
        try:
            helper(
                source_file_path,
                "orders.xsd",
                "schema-1",
                {"logical_path": "orders.xsd", "container_name": "documents"},
                user_id="owner",
            )
        except FakeCapabilityError:
            pass
        else:
            raise AssertionError("A conflicting immutable XSD must be rejected")
        assert active_blob[0].deleted is False
    finally:
        Path(source_file_path).unlink(missing_ok=True)


def test_xsd_state_indexes_exactly_one_summary_chunk():
    """Every XSD state refresh replaces only deterministic page one."""
    update_calls = []
    saved_chunks = []
    namespace = {
        "XSD_PROFILE_ID": "profile",
        "XSD_VALIDATOR_ID": "validator",
        "XSD_DIALECT_ID": "dialect",
        "summarize_xsd_inspection": lambda inspection: "bounded schema summary",
        "update_document": lambda **kwargs: update_calls.append(kwargs),
        "save_chunks": lambda *args, **kwargs: saved_chunks.append((args, kwargs)),
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"_store_xsd_document_schema_state"},
        namespace,
    )
    status = namespace["_store_xsd_document_schema_state"](
        {"id": "schema-1", "file_name": "orders.xsd"},
        {
            "logical_path": "orders.xsd",
            "status": "ready",
            "sha256": "abc",
            "byte_size": 42,
            "global_elements": ["Order"],
            "global_types": ["OrderType"],
            "dependencies": [],
        },
        {"blob_etag": "etag"},
        "owner",
        mark_processing_complete=True,
    )

    assert status == "ready"
    assert len(saved_chunks) == 1
    assert saved_chunks[0][0][:2] == ("bounded schema summary", 1)
    assert update_calls[0]["num_file_chunks"] == 1
    assert update_calls[0]["xsd_effective_dialect"] == "dialect"
    assert update_calls[0]["xsd_dependency_count"] == 0
    assert update_calls[-1]["status"] == "Complete"


def test_dependency_change_revalidates_transitive_dependents():
    """A changed dependency refreshes direct and transitive current dependents."""
    documents = [
        {
            "id": "grandparent",
            "file_name": "top.xsd",
            "xsd_logical_path": "top.xsd",
            "xsd_dependencies": [
                {"schema_location": "schemas/root.xsd"},
            ],
        },
        {
            "id": "parent",
            "file_name": "root.xsd",
            "xsd_logical_path": "schemas/root.xsd",
            "xsd_dependencies": [
                {"schema_location": "common.xsd"},
            ],
        },
        {
            "id": "unrelated",
            "file_name": "other.xsd",
            "xsd_logical_path": "other.xsd",
            "xsd_dependencies": [],
        },
    ]
    refreshed = []

    def resolve_path(base_path, location):
        base_directory = base_path.rsplit("/", 1)[0] if "/" in base_path else ""
        return f"{base_directory}/{location}".strip("/")

    class FakeLogging:
        ERROR = "error"

    namespace = {
        "normalize_xsd_logical_path": lambda file_name, logical_path=None: logical_path or file_name,
        "_query_current_xsd_documents": lambda *args, **kwargs: documents,
        "resolve_xsd_dependency_path": resolve_path,
        "_safe_int": lambda value: int(value or 0),
        "XsdSchemaError": ValueError,
        "_read_verified_xsd_blob": lambda document, *args, **kwargs: {
            "bytes": document["id"].encode("utf-8"),
            "blob_etag": "etag",
        },
        "_evaluate_xsd_document_schema": lambda document, *args, **kwargs: {
            "logical_path": document["xsd_logical_path"],
            "status": "ready",
        },
        "_store_xsd_document_schema_state": (
            lambda document, *args, **kwargs: refreshed.append(document["id"])
        ),
        "_refresh_xsd_document_schema_state": (
            lambda document, *args, **kwargs: refreshed.append(document["id"])
        ),
        "log_event": lambda *args, **kwargs: None,
        "logging": FakeLogging,
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"_revalidate_xsd_workspace_dependents"},
        namespace,
    )
    namespace["_revalidate_xsd_workspace_dependents"](
        "schemas/common.xsd",
        "owner",
    )

    assert refreshed == ["parent", "grandparent"]


def test_dependency_revalidation_recovers_edges_omitted_from_bounded_metadata():
    """Dependency discovery reloads exact XSD bytes when metadata was truncated."""
    document = {
        "id": "dependent",
        "file_name": "root.xsd",
        "xsd_logical_path": "schemas/root.xsd",
        "xsd_dependencies": [
            {"schema_location": f"unrelated-{index}.xsd"}
            for index in range(100)
        ],
        "xsd_dependency_count": 101,
    }
    refreshed = []
    reads = []

    namespace = {
        "normalize_xsd_logical_path": (
            lambda file_name, logical_path=None: logical_path or file_name
        ),
        "_query_current_xsd_documents": lambda *args, **kwargs: [document],
        "resolve_xsd_dependency_path": (
            lambda base_path, location: (
                f"{base_path.rsplit('/', 1)[0]}/{location}"
                if "/" in base_path
                else location
            )
        ),
        "_safe_int": lambda value: int(value or 0),
        "XsdSchemaError": ValueError,
        "_read_verified_xsd_blob": (
            lambda item, *args, **kwargs: reads.append(item["id"])
            or {"bytes": b"schema", "blob_etag": "etag"}
        ),
        "inspect_xsd_bytes": lambda payload, logical_path: {
            "dependencies": [{"schema_location": "late.xsd"}],
        },
        "_evaluate_xsd_document_schema": lambda item, *args, **kwargs: {
            "logical_path": item["xsd_logical_path"],
            "status": "ready",
        },
        "_store_xsd_document_schema_state": (
            lambda item, *args, **kwargs: refreshed.append(item["id"])
        ),
        "_refresh_xsd_document_schema_state": (
            lambda item, *args, **kwargs: refreshed.append(item["id"])
        ),
        "log_event": lambda *args, **kwargs: None,
        "logging": logging,
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"_revalidate_xsd_workspace_dependents"},
        namespace,
    )
    namespace["_revalidate_xsd_workspace_dependents"](
        "schemas/late.xsd",
        "owner",
    )

    assert refreshed == ["dependent"]
    assert reads == ["dependent"]


def test_dependency_discovery_failure_does_not_block_other_dependents():
    """One unreadable truncated manifest cannot abort sibling revalidation."""
    documents = [
        {
            "id": "unreadable",
            "file_name": "bad.xsd",
            "xsd_logical_path": "schemas/bad.xsd",
            "xsd_dependencies": [],
            "xsd_dependency_count": 101,
        },
        {
            "id": "healthy",
            "file_name": "healthy.xsd",
            "xsd_logical_path": "schemas/healthy.xsd",
            "xsd_dependencies": [{"schema_location": "changed.xsd"}],
            "xsd_dependency_count": 1,
        },
    ]
    refreshed = []
    logged = []
    blocked_updates = []

    def read_blob(document, *args, **kwargs):
        raise RuntimeError(f"cannot read {document['id']}")

    namespace = {
        "normalize_xsd_logical_path": (
            lambda file_name, logical_path=None: logical_path or file_name
        ),
        "_query_current_xsd_documents": lambda *args, **kwargs: documents,
        "resolve_xsd_dependency_path": (
            lambda base_path, location: (
                f"{base_path.rsplit('/', 1)[0]}/{location}"
                if "/" in base_path
                else location
            )
        ),
        "_safe_int": lambda value: int(value or 0),
        "XsdSchemaError": ValueError,
        "_read_verified_xsd_blob": read_blob,
        "inspect_xsd_bytes": lambda payload, logical_path: {"dependencies": []},
        "_refresh_xsd_document_schema_state": (
            lambda document, *args, **kwargs: refreshed.append(document["id"])
        ),
        "update_document": lambda **kwargs: blocked_updates.append(kwargs),
        "log_event": lambda *args, **kwargs: logged.append((args, kwargs)),
        "logging": logging,
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"_revalidate_xsd_workspace_dependents"},
        namespace,
    )
    namespace["_revalidate_xsd_workspace_dependents"](
        "schemas/changed.xsd",
        "owner",
    )

    assert refreshed == ["healthy"]
    assert len(blocked_updates) == 1
    assert blocked_updates[0]["document_id"] == "unreadable"
    assert blocked_updates[0]["xsd_schema_status"] == "validation_blocked"
    assert any(
        call_args
        and call_args[0] == "[XSD_INGESTION] Dependent schema edge discovery failed."
        for call_args, _call_kwargs in logged
    )


def test_xsd_state_refresh_uses_verified_source_and_current_workspace():
    """Single-document refresh reads, evaluates, and stores the promoted source."""
    calls = []
    document = {
        "id": "promoted",
        "group_id": "group-1",
        "xsd_logical_path": "schemas/root.xsd",
    }
    persisted_source = {
        "bytes": b"<schema/>",
        "sha256": "digest",
        "blob_etag": "etag",
    }
    inspection = {"status": "ready"}
    namespace = {
        "_read_verified_xsd_blob": (
            lambda item, user_id, **kwargs: calls.append(
                ("read", item["id"], user_id, kwargs)
            )
            or persisted_source
        ),
        "_evaluate_xsd_document_schema": (
            lambda item, payload, user_id, **kwargs: calls.append(
                ("evaluate", item["id"], payload, user_id, kwargs)
            )
            or inspection
        ),
        "_store_xsd_document_schema_state": (
            lambda item, result, source, user_id, **kwargs: calls.append(
                ("store", item["id"], result, source, user_id, kwargs)
            )
            or "ready"
        ),
    }
    _load_nodes(
        DOCUMENTS_FILE,
        {"_refresh_xsd_document_schema_state"},
        namespace,
    )

    status = namespace["_refresh_xsd_document_schema_state"](
        document,
        "owner",
        group_id="group-1",
    )

    assert status == "ready"
    assert [call[0] for call in calls] == ["read", "evaluate", "store"]
    assert calls[1][2] == persisted_source["bytes"]
    assert calls[2][2:4] == (inspection, persisted_source)
    assert all(call[-1].get("group_id") == "group-1" for call in calls)


def test_promoted_xsd_revision_refresh_precedes_dependent_revalidation():
    """Revision promotion refreshes its readiness before traversing dependents."""
    tree = ast.parse(_read_text(DOCUMENTS_FILE), filename=str(DOCUMENTS_FILE))
    function_node = next(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef)
        and node.name == "delete_document_revision"
    )
    function_source = ast.get_source_segment(_read_text(DOCUMENTS_FILE), function_node)

    refresh_index = function_source.index("_refresh_xsd_document_schema_state(")
    revalidate_index = function_source.index(
        "_revalidate_xsd_workspace_dependents(",
        refresh_index,
    )
    assert refresh_index < revalidate_index
    assert '"validation_blocked"' in function_source
    assert "promoted XSD revision could not be revalidated" in function_source


def test_chat_xsd_output_validates_before_publication():
    """Chat XML is never uploaded until exact final bytes pass XSD validation."""
    generated_exports = _load_generated_exports()
    events = []

    namespace = {
        "XsdSchemaError": xsd.XsdSchemaError,
        "get_tabular_generated_output_format": lambda question: "xml",
        "_has_generated_file_output": lambda outputs, output_format: False,
        "_assistant_content_disclaims_complete_file": lambda content: False,
        "normalize_json_artifact_payload": generated_exports.normalize_json_artifact_payload,
        "normalize_complete_xml_artifact_payload": (
            generated_exports.normalize_complete_xml_artifact_payload
        ),
        "normalize_xml_artifact_payload": generated_exports.normalize_xml_artifact_payload,
        "serialize_generated_json": generated_exports.serialize_generated_json,
        "serialize_generated_xml": generated_exports.serialize_generated_xml,
        "refresh_xsd_generation_contract": (
            lambda contract, user_id: events.append(("refresh", user_id))
            or contract
        ),
        "validate_xsd_generated_output": (
            lambda payload, contract: events.append(("validate", payload))
            or {"sha256": "validated-digest"}
        ),
        "_build_assistant_file_preview_lines": lambda content: ["<Order/>"],
        "_build_assistant_file_export_name": lambda output_format: "generated.xml",
        "upload_generated_analysis_artifact_for_current_user": (
            lambda **kwargs: events.append(("upload", kwargs["file_content"]))
            or {"message": {"id": "artifact-1", "file_name": kwargs["file_name"]}}
        ),
        "log_event": lambda *args, **kwargs: None,
    }
    _load_nodes(
        CHAT_ROUTE_FILE,
        {
            "XsdGeneratedOutputValidationError",
            "_find_existing_validated_xsd_output",
            "maybe_create_assistant_file_generated_output",
        },
        namespace,
    )
    contract = {
        "document_id": "schema-1",
        "compiled_graph": object(),
        "profile_id": "profile-1",
        "validator_id": "validator-1",
    }
    output = namespace["maybe_create_assistant_file_generated_output"](
        "Create XML",
        "<Order/>",
        "conversation-1",
        xsd_generation_contract=contract,
        user_id="owner",
    )

    assert [event[0] for event in events] == ["refresh", "validate", "upload"]
    assert output["artifact_message_id"] == "artifact-1"
    assert output["xsd_validation_sha256"] == "validated-digest"

    events.clear()

    def reject_output(payload, contract):
        events.append(("validate", payload))
        raise ValueError("invalid")

    namespace["validate_xsd_generated_output"] = reject_output
    try:
        namespace["maybe_create_assistant_file_generated_output"](
            "Create XML",
            "<Order/>",
            "conversation-1",
            xsd_generation_contract=contract,
            user_id="owner",
        )
    except namespace["XsdGeneratedOutputValidationError"]:
        pass
    else:
        raise AssertionError("Schema-invalid chat XML must fail publication")
    assert [event[0] for event in events] == ["refresh", "validate"]

    events.clear()
    try:
        namespace["maybe_create_assistant_file_generated_output"](
            "Create XML",
            "<broken><Order /></broken",
            "conversation-1",
            xsd_generation_contract=contract,
            user_id="owner",
        )
    except namespace["XsdGeneratedOutputValidationError"]:
        pass
    else:
        raise AssertionError("Malformed wrapper output must not publish a nested fragment")
    assert events == []

    trusted_existing_output = {
        "artifact_message_id": "artifact-existing",
        "output_format": "xml",
        "xsd_document_id": "schema-1",
        "xsd_profile": "profile-1",
        "xsd_validator_id": "validator-1",
        "xsd_validation_sha256": "existing-digest",
    }
    reused = namespace["maybe_create_assistant_file_generated_output"](
        "Create XML",
        "<Order/>",
        "conversation-1",
        existing_outputs=[trusted_existing_output],
        xsd_generation_contract=contract,
        user_id="owner",
    )
    assert reused is trusted_existing_output
    assert events == []


def test_workflow_xsd_output_validates_before_publication():
    """Workflow Analyze uses the same validation-before-upload invariant."""
    generated_exports = _load_generated_exports()
    events = []
    namespace = {
        "normalize_complete_xml_artifact_payload": (
            generated_exports.normalize_complete_xml_artifact_payload
        ),
        "normalize_xml_artifact_payload": generated_exports.normalize_xml_artifact_payload,
        "serialize_generated_xml": generated_exports.serialize_generated_xml,
        "refresh_xsd_generation_contract": (
            lambda contract, user_id: events.append(("refresh", user_id))
            or contract
        ),
        "validate_xsd_generated_output": (
            lambda payload, contract: events.append(("validate", payload))
            or {"sha256": "workflow-digest"}
        ),
        "upload_generated_analysis_artifact_for_user": (
            lambda **kwargs: events.append(("upload", kwargs["file_content"]))
            or {"message": {"id": "artifact-2", "file_name": kwargs["file_name"]}}
        ),
        "datetime": datetime,
        "timezone": timezone,
    }
    _load_nodes(
        WORKFLOW_RUNNER_FILE,
        {"_maybe_create_workflow_xsd_generated_output"},
        namespace,
    )
    output = namespace["_maybe_create_workflow_xsd_generated_output"](
        {"user_id": "owner"},
        "conversation-1",
        "<Order/>",
        {"document_id": "schema-1", "compiled_graph": object()},
    )

    assert [event[0] for event in events] == ["refresh", "validate", "upload"]
    assert output["xsd_validation_sha256"] == "workflow-digest"

    events.clear()
    assert namespace["_maybe_create_workflow_xsd_generated_output"](
        {"user_id": "owner"},
        "conversation-1",
        "Required source data is unavailable, so no XML was generated.",
        {"document_id": "schema-1", "compiled_graph": object()},
    ) is None
    assert events == []

    try:
        namespace["_maybe_create_workflow_xsd_generated_output"](
            {"user_id": "owner"},
            "conversation-1",
            "<Order>",
            {"document_id": "schema-1", "compiled_graph": object()},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Incomplete workflow XML must fail publication")
    assert events == []

    def reject_workflow_output(payload, contract):
        events.append(("validate", payload))
        raise ValueError("invalid")

    namespace["validate_xsd_generated_output"] = reject_workflow_output
    try:
        namespace["_maybe_create_workflow_xsd_generated_output"](
            {"user_id": "owner"},
            "conversation-1",
            "<Order/>",
            {"document_id": "schema-1", "compiled_graph": object()},
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Schema-invalid workflow XML must fail publication")
    assert [event[0] for event in events] == ["refresh", "validate"]


def test_workflow_xsd_explanation_does_not_create_an_empty_artifact():
    """Analyze preserves a model explanation when no complete XML was returned."""
    original_payload = {
        "artifacts": [],
        "assistant_reply": "Required source data is unavailable.",
    }
    namespace = {
        "has_generated_file_output": lambda outputs, output_format: False,
        "_maybe_create_workflow_xsd_generated_output": (
            lambda *args, **kwargs: None
        ),
        "get_generated_file_export_content": (
            lambda result: result.get("analysis_reply", "")
        ),
    }
    _load_nodes(
        WORKFLOW_RUNNER_FILE,
        {"_finalize_workflow_xsd_analysis_output"},
        namespace,
    )
    output = namespace["_finalize_workflow_xsd_analysis_output"](
        {"user_id": "owner"},
        "conversation-1",
        {"analysis_reply": "Required source data is unavailable."},
        original_payload,
        {"document_id": "schema-1", "compiled_graph": object()},
    )

    assert output == original_payload
    assert output["artifacts"] == []


def test_chat_loads_explicit_xsd_when_mixed_source_search_is_disabled():
    """Explicit XSD generation preflight is independent of mixed-source rollout."""
    calls = []
    contract = {"document_id": "schema-1", "guidance": "schema guidance"}

    def resolve_manifest(document_ids, **kwargs):
        calls.append(("resolve", document_ids, kwargs))
        return [{"document_id": "schema-1", "source_kind": "xml_schema"}]

    namespace = {
        "is_mixed_source_chat_search_enabled": (
            lambda settings: settings.get("mixed_source", False)
        ),
        "resolve_authorized_source_manifest": resolve_manifest,
        "partition_source_manifest": lambda manifest: {
            "schema_sources": [
                {
                    "document_id": "schema-1",
                    "source_kind": "xml_schema",
                    "authorization_status": "authorized",
                }
            ],
        },
        "load_xsd_generation_contract": (
            lambda sources, user_id: calls.append(("load", sources, user_id))
            or contract
        ),
    }
    _load_nodes(
        CHAT_ROUTE_FILE,
        {"_load_explicit_xsd_contract_without_mixed_source_search"},
        namespace,
    )
    helper = namespace["_load_explicit_xsd_contract_without_mixed_source_search"]

    result = helper(
        {"mixed_source": False},
        "xml",
        ["schema-1"],
        user_id="owner",
        conversation_id="conversation-1",
        active_group_ids=["group-1"],
        doc_scope="group",
    )

    assert result is contract
    assert [call[0] for call in calls] == ["resolve", "load"]
    assert calls[0][2]["selection_mode"] == "selected"
    assert calls[0][2]["active_group_ids"] == ["group-1"]

    calls.clear()
    assert helper(
        {"mixed_source": True},
        "xml",
        ["schema-1"],
        user_id="owner",
        conversation_id="conversation-1",
    ) is None
    assert helper(
        {"mixed_source": False},
        "json",
        ["schema-1"],
        user_id="owner",
        conversation_id="conversation-1",
    ) is None
    assert calls == []


def test_schema_contract_is_excluded_from_legacy_chunk_search():
    """Legacy search keeps selected data documents but not the root XSD contract."""
    namespace = {}
    _load_nodes(
        CHAT_ROUTE_FILE,
        {"_exclude_xsd_contract_document_ids_from_search"},
        namespace,
    )
    helper = namespace["_exclude_xsd_contract_document_ids_from_search"]

    assert helper(
        ["schema-1", "data-1", "data-2"],
        {"document_id": "schema-1"},
    ) == ["data-1", "data-2"]
    assert helper(["schema-1"], {"document_id": "schema-1"}) == []
    assert helper(["schema-1", "data-1"], None) == ["schema-1", "data-1"]


def test_chat_modes_each_build_one_schema_summary_evidence_envelope():
    """Streaming and non-streaming chat each wire schema evidence exactly once."""
    tree = ast.parse(_read_text(CHAT_ROUTE_FILE), filename=str(CHAT_ROUTE_FILE))

    def find_function(name):
        return next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )

    def count_schema_evidence_calls(function_node):
        return sum(
            1
            for node in ast.walk(function_node)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "build_schema_summary_evidence_envelopes"
        )

    assert count_schema_evidence_calls(find_function("chat_api")) == 1
    assert count_schema_evidence_calls(find_function("chat_stream_api")) == 1


def test_legacy_tabular_xml_publishers_are_suppressed_in_xsd_mode():
    """All legacy chat tabular publishers are guarded by the XSD contract."""
    tree = ast.parse(_read_text(CHAT_ROUTE_FILE), filename=str(CHAT_ROUTE_FILE))
    parent_by_node = {
        child: parent
        for parent in ast.walk(tree)
        for child in ast.iter_child_nodes(parent)
    }

    def find_function(name):
        return next(
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
            and node.name == name
        )

    publisher_names = {
        "maybe_queue_direct_tabular_generated_output",
        "maybe_create_tabular_generated_output",
    }
    calls = []
    for function_name in ("chat_api", "chat_stream_api"):
        function_node = find_function(function_name)
        for node in ast.walk(function_node):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in publisher_names
            ):
                calls.append(node)

    assert len(calls) == 8
    for call in calls:
        current = parent_by_node.get(call)
        guarded = False
        while current is not None and not isinstance(
            current,
            (ast.FunctionDef, ast.AsyncFunctionDef),
        ):
            if isinstance(current, ast.If):
                condition = ast.unparse(current.test)
                if (
                    "xsd_generation_contract" in condition
                    and "not xsd_generation_contract" in condition
                ):
                    guarded = True
                    break
            current = parent_by_node.get(current)
        assert guarded, (
            f"Legacy tabular publisher at line {call.lineno} is not suppressed "
            "by xsd_generation_contract"
        )


def test_suppressed_streams_never_persist_or_return_partial_file_content():
    """Canceled/interrupted XSD streams expose only neutral status messages."""
    tree = ast.parse(_read_text(CHAT_ROUTE_FILE), filename=str(CHAT_ROUTE_FILE))
    function_node = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef)
        and node.name == "chat_stream_api"
    )
    function_source = ast.get_source_segment(
        _read_text(CHAT_ROUTE_FILE),
        function_node,
    )

    assert "if mixed_source_manifest or suppress_streamed_file_payload:" in function_source
    assert "safe_partial_content = (" in function_source
    assert "if suppress_streamed_file_payload" in function_source
    assert "'content': safe_partial_content" in function_source
    assert "partial_content=safe_partial_content" in function_source


def test_xsd_chat_upload_ui_is_capability_gated():
    """The browser advertises XSD only when exact-source storage is available."""
    route_source = _read_text(CHAT_FRONTEND_ROUTE_FILE)
    template_source = _read_text(CHAT_TEMPLATE_FILE)

    assert 'public_settings["xsd_upload_available"] = bool(' in route_source
    assert 'enable_enhanced_citations' in route_source
    assert 'CLIENTS.get("storage_account_office_docs_client")' in route_source
    assert "{% if settings.xsd_upload_available %},.xsd{% endif %}" in template_source
    assert "XSD uploads require Enhanced Citations" in route_source
    assert "XSD uploads require an enabled personal or group workspace" in route_source


def test_schema_contract_is_not_counted_as_source_evidence():
    """An authoritative XSD is excluded from ordinary narrative/tabular evidence."""
    namespace = {}
    _load_nodes(
        CHAT_ROUTE_FILE,
        {"_exclude_xsd_contract_sources_from_evidence"},
        namespace,
    )
    manifest = [
        {"document_id": "schema-1", "source_kind": "xml_schema"},
        {"document_id": "data-1", "source_kind": "narrative"},
        {"document_id": "data-2", "source_kind": "tabular"},
    ]
    helper = namespace["_exclude_xsd_contract_sources_from_evidence"]
    assert helper(manifest, None) == manifest
    assert [item["document_id"] for item in helper(manifest, {"schema": True})] == [
        "data-1",
        "data-2",
    ]


if __name__ == "__main__":
    assert_app_version_at_least("0.250.160")
    tests = [
        test_current_xsd_query_excludes_archived_revisions,
        test_shared_personal_xsd_dependencies_use_owner_workspace_and_individual_access,
        test_archived_xsd_cannot_be_loaded_as_a_generation_contract,
        test_final_xsd_contract_refresh_reauthorizes_and_detects_graph_drift,
        test_xsd_finalization_rechecks_workspace_membership,
        test_xsd_processing_propagates_scope_and_refreshes_dependents,
        test_xsd_source_staging_verifies_exact_bytes_and_cleans_failed_uploads,
        test_xsd_state_indexes_exactly_one_summary_chunk,
        test_dependency_change_revalidates_transitive_dependents,
        test_dependency_revalidation_recovers_edges_omitted_from_bounded_metadata,
        test_dependency_discovery_failure_does_not_block_other_dependents,
        test_xsd_state_refresh_uses_verified_source_and_current_workspace,
        test_promoted_xsd_revision_refresh_precedes_dependent_revalidation,
        test_chat_xsd_output_validates_before_publication,
        test_workflow_xsd_output_validates_before_publication,
        test_workflow_xsd_explanation_does_not_create_an_empty_artifact,
        test_chat_loads_explicit_xsd_when_mixed_source_search_is_disabled,
        test_schema_contract_is_excluded_from_legacy_chunk_search,
        test_chat_modes_each_build_one_schema_summary_evidence_envelope,
        test_legacy_tabular_xml_publishers_are_suppressed_in_xsd_mode,
        test_suppressed_streams_never_persist_or_return_partial_file_content,
        test_xsd_chat_upload_ui_is_capability_gated,
        test_schema_contract_is_not_counted_as_source_evidence,
    ]
    results = []
    for test in tests:
        print(f"\nRunning {test.__name__}...")
        try:
            test()
            results.append(True)
            print("Test passed!")
        except Exception as exc:  # noqa: BLE001
            results.append(False)
            print(f"Test failed: {exc}")
            import traceback

            traceback.print_exc()

    passed = sum(1 for result in results if result)
    print(f"\nResults: {passed}/{len(results)} tests passed")
    sys.exit(0 if all(results) else 1)
