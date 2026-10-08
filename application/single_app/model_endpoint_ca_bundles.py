# model_endpoint_ca_bundles.py
"""Certificate-only shared CA storage and fenced endpoint-reference reservations."""

from collections import OrderedDict
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
import json
import re
import threading
import time
from typing import Callable, Mapping
import uuid

from azure.core import MatchConditions
from azure.core.exceptions import AzureError, ResourceExistsError, ResourceNotFoundError
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError
from azure.storage.blob import ContentSettings
from cryptography import x509
from cryptography.exceptions import UnsupportedAlgorithm
from cryptography.hazmat.primitives import hashes, serialization


CA_CONTAINER_NAME = "model-endpoint-ca-bundles"
CA_DOCUMENT_TYPE = "model_endpoint_ca_bundle"
MAX_CA_BYTES = 1024 * 1024
MAX_CERTIFICATES = 64
MAX_METADATA_BYTES = 1500000
MAX_AUDIT_EVENTS = 50
REFERENCE_DEADLINE_SECONDS = 120
MAX_WRITE_ATTEMPTS = 5
CERTIFICATE_PATTERN = re.compile(br"-----BEGIN CERTIFICATE-----[\s\S]+?-----END CERTIFICATE-----")
SOURCE_ID_PATTERN = re.compile(r"[A-Za-z0-9_-]{1,256}\Z")
_PEM_CACHE = OrderedDict()
_PEM_CACHE_LOCK = threading.Lock()

@dataclass(frozen=True)
class ManagedCABundle:
    bundle_id: str
    revision: int
    sha256: str
    pem: str = field(repr=False)


class CABundleError(ValueError):
    """An explicit, user-safe certificate or shared-storage error."""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.public_message = message
        self.status = status

    @property
    def payload(self) -> dict:
        return {"error": self.public_message, "error_code": self.code}


def normalize_ca_bundle_id(value: object) -> str:
    if not isinstance(value, str) or not value.startswith("ca-"):
        raise CABundleError("ca_bundle_invalid", "Choose a valid CA bundle.")
    try:
        parsed = uuid.UUID(value[3:])
    except ValueError:
        raise CABundleError("ca_bundle_invalid", "Choose a valid CA bundle.") from None
    normalized = f"ca-{parsed.hex}"
    if value != normalized:
        raise CABundleError("ca_bundle_invalid", "Choose a valid CA bundle.")
    return normalized


def normalize_ca_bundle_reference(connection: Mapping) -> tuple[str, str]:
    mode = connection.get("ca_bundle_mode", "inherit")
    if mode not in ("inherit", "public", "bundle"):
        raise CABundleError("ca_bundle_invalid", "Choose inherited trust, public certificate authorities, or a CA bundle.")
    bundle_id = connection.get("ca_bundle_id", "")
    if mode == "bundle":
        return mode, normalize_ca_bundle_id(bundle_id)
    if bundle_id:
        raise CABundleError("ca_bundle_invalid", "A CA bundle ID requires bundle trust mode.")
    return mode, ""


def endpoint_ca_bundle_ids(endpoints: list) -> set[str]:
    bundle_ids = set()
    for endpoint in endpoints:
        if not isinstance(endpoint, dict):
            raise CABundleError("ca_bundle_invalid", "Model endpoints must be configuration objects.")
        connection = endpoint.get("connection") or {}
        if not isinstance(connection, dict):
            raise CABundleError("ca_bundle_invalid", "The endpoint connection is invalid.")
        _, bundle_id = normalize_ca_bundle_reference(connection)
        if bundle_id:
            if endpoint.get("provider") != "custom":
                raise CABundleError("ca_bundle_invalid", "Managed CA bundles are supported only for Custom endpoints.")
            bundle_ids.add(bundle_id)
    return bundle_ids


def validate_ca_certificates(data: bytes) -> tuple[bytes, list[dict]]:
    if not isinstance(data, bytes) or not data or len(data) > MAX_CA_BYTES:
        raise CABundleError("ca_bundle_invalid", "Upload a nonempty PEM certificate bundle no larger than 1 MiB.")
    blocks = CERTIFICATE_PATTERN.findall(data)
    if not blocks or len(blocks) > MAX_CERTIFICATES or CERTIFICATE_PATTERN.sub(b"", data).strip():
        raise CABundleError("ca_bundle_invalid", "Upload only PEM certificates, without private keys or other content (maximum 64 certificates).")
    certificates = []
    canonical = []
    fingerprints = set()
    try:
        for block in blocks:
            certificate = x509.load_pem_x509_certificate(block)
            constraints = certificate.extensions.get_extension_for_class(x509.BasicConstraints)
            if not constraints.value.ca:
                raise CABundleError("ca_bundle_invalid", "Every uploaded certificate must be a certificate authority.")
            fingerprint = certificate.fingerprint(hashes.SHA256()).hex()
            if fingerprint in fingerprints:
                raise CABundleError("ca_bundle_invalid", "Remove duplicate certificates from the bundle.")
            fingerprints.add(fingerprint)
            canonical.append(certificate.public_bytes(serialization.Encoding.PEM))
            certificates.append({
                "sha256": fingerprint,
                "subject": certificate.subject.rfc4514_string(),
                "issuer": certificate.issuer.rfc4514_string(),
                "valid_from": certificate.not_valid_before_utc.isoformat(),
                "expires_at": certificate.not_valid_after_utc.isoformat(),
            })
    except CABundleError:
        raise
    except (ValueError, UnsupportedAlgorithm, x509.ExtensionNotFound):
        raise CABundleError("ca_bundle_invalid", "The PEM bundle contains an invalid or non-CA certificate.") from None
    return b"".join(canonical), certificates


def _name(value: object) -> str:
    if not isinstance(value, str):
        raise CABundleError("ca_bundle_invalid", "Give the bundle a friendly name.")
    name = value.strip()
    if not name or len(name) > 120 or any(ord(character) < 32 for character in name):
        raise CABundleError("ca_bundle_invalid", "The bundle name must contain 1-120 characters without control characters.")
    return name


def _source_key(source: Mapping) -> str:
    kind, source_id = source.get("kind"), source.get("id")
    if kind not in ("settings", "user_settings", "groups") or not isinstance(source_id, str) or not SOURCE_ID_PATTERN.fullmatch(source_id):
        raise CABundleError("ca_bundle_integrity", "The certificate reference source is invalid.", 503)
    if kind == "settings" and source_id != "app_settings":
        raise CABundleError("ca_bundle_integrity", "The certificate reference source is invalid.", 503)
    return f"{kind}:{source_id}"


class CABundleRegistry:
    """Storage handles and callbacks are supplied by the settings owner, never imported."""

    def __init__(
        self, metadata_container, blob_factory: Callable,
        source_containers: Mapping, *, global_source_fence: Callable,
        log: Callable, clock: Callable = time.time,
    ):
        self.metadata = metadata_container
        self.blob_factory = blob_factory
        self.sources = source_containers
        self.global_source_fence = global_source_fence
        self.log = log
        self.clock = clock
        self._blob_container = None

    def _blob(self, *, create: bool = False):
        if self._blob_container is None:
            try:
                self._blob_container = self.blob_factory().get_container_client(CA_CONTAINER_NAME)
                if create:
                    try:
                        self._blob_container.create_container()
                    except ResourceExistsError:
                        pass
                properties = self._blob_container.get_container_properties()
                if "public_access" not in properties or properties["public_access"] is not None:
                    raise CABundleError("ca_bundle_storage", "The CA bundle container must be private.", 503)
            except (AzureError, ValueError) as error:
                self._blob_container = None
                if isinstance(error, CABundleError):
                    raise
                raise CABundleError("ca_bundle_storage", "Configure accessible application Blob Storage for CA bundles.", 503) from error
        return self._blob_container

    def _read(self, bundle_id: str, *, allow_deleting: bool = False) -> dict:
        bundle_id = normalize_ca_bundle_id(bundle_id)
        try:
            document = self.metadata.read_item(item=bundle_id, partition_key=bundle_id)
        except CosmosResourceNotFoundError:
            raise CABundleError("ca_bundle_missing", "The selected CA bundle no longer exists.", 404) from None
        if document.get("document_type") != CA_DOCUMENT_TYPE or document.get("state") not in ("active", "deleting"):
            raise CABundleError("ca_bundle_missing", "The selected CA bundle no longer exists.", 404)
        if not allow_deleting and document["state"] != "active":
            raise CABundleError("ca_bundle_missing", "The selected CA bundle is being deleted.", 409)
        if not isinstance(document.get("references"), dict) or not isinstance(document.get("pending"), dict):
            raise CABundleError("ca_bundle_integrity", "The certificate reference metadata is invalid.", 503)
        return deepcopy(document)

    def _change(self, bundle_id: str, transform: Callable, *, allow_deleting: bool = False) -> dict:
        for _ in range(MAX_WRITE_ATTEMPTS):
            document = self._read(bundle_id, allow_deleting=allow_deleting)
            changed = transform(document)
            if len(json.dumps(changed).encode("utf-8")) > MAX_METADATA_BYTES:
                raise CABundleError("ca_bundle_capacity", "The CA bundle reference inventory has reached its safe storage limit.", 409)
            try:
                return self.metadata.replace_item(
                    item=bundle_id, body=changed,
                    etag=document["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            except CosmosAccessConditionFailedError:
                continue
        raise CABundleError("ca_bundle_conflict", "The CA bundle changed. Reload and try again.", 409)

    def _audit(self, document: dict, action: str, actor_id: str) -> None:
        event = {
            "action": action, "actor_id": actor_id,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "revision": document["revision"],
        }
        document["audit_history"] = [*(document.get("audit_history") or []), event][-MAX_AUDIT_EVENTS:]
        document["updated_at"] = event["timestamp"]

    @staticmethod
    def _projection(document: dict, *, details: bool) -> dict:
        projected = {
            key: deepcopy(document[key]) for key in (
                "id", "name", "revision", "updated_at", "certificates",
            )
        }
        projected["expires_at"] = min(certificate["expires_at"] for certificate in projected["certificates"])
        if details:
            projected["state"] = document["state"]
            projected["audit_history"] = deepcopy(document.get("audit_history") or [])
            projected["pending_save_count"] = len(document["pending"])
        else:
            projected["certificate_count"] = len(projected.pop("certificates"))
        return projected

    def list_bundles(self, *, details: bool = False) -> list[dict]:
        rows = self.metadata.query_items(
            query="SELECT * FROM c WHERE c.document_type = @type AND " + (
                "c.state IN ('active', 'deleting')" if details else "c.state = 'active'"
            ),
            parameters=[{"name": "@type", "value": CA_DOCUMENT_TYPE}],
            enable_cross_partition_query=True,
        )
        return sorted((self._projection(row, details=details) for row in rows), key=lambda row: (row["name"].casefold(), row["id"]))

    def _upload(self, bundle_id: str, pem: bytes) -> tuple[str, str]:
        digest = hashlib.sha256(pem).hexdigest()
        blob_name = f"{bundle_id}/{digest}.pem"
        blob = self._blob(create=True).get_blob_client(blob_name)
        try:
            blob.upload_blob(
                pem, overwrite=False, content_settings=ContentSettings(content_type="application/x-pem-file"),
            )
        except ResourceExistsError:
            existing = self._download(blob_name, digest)
            if existing != pem:
                raise CABundleError("ca_bundle_integrity", "The existing certificate content failed integrity validation.", 503)
        return blob_name, digest

    def create(self, name: str, data: bytes, actor_id: str) -> dict:
        name = _name(name)
        pem, certificates = validate_ca_certificates(data)
        bundle_id = f"ca-{uuid.uuid4().hex}"
        blob_name, digest = self._upload(bundle_id, pem)
        document = {
            "id": bundle_id, "document_type": CA_DOCUMENT_TYPE,
            "state": "active", "name": name, "revision": 1,
            "blob_name": blob_name, "sha256": digest, "certificates": certificates,
            "blob_history": [blob_name], "references": {}, "pending": {},
        }
        self._audit(document, "created", actor_id)
        saved = self.metadata.create_item(document)
        self.log("created", bundle_id=bundle_id, revision=1, actor_id=actor_id)
        return self._projection(saved, details=True)

    def replace(self, bundle_id: str, name: str, data: bytes | None, expected_revision: int, actor_id: str) -> dict:
        name = _name(name)
        if type(expected_revision) is not int or expected_revision < 1:
            raise CABundleError("ca_bundle_conflict", "Reload the CA bundle before replacing it.", 409)
        uploaded = None
        if data is not None:
            pem, certificates = validate_ca_certificates(data)
            blob_name, digest = self._upload(normalize_ca_bundle_id(bundle_id), pem)
            uploaded = blob_name, digest, certificates

        def transform(document):
            if document["revision"] != expected_revision:
                raise CABundleError("ca_bundle_conflict", "The CA bundle changed. Reload before replacing it.", 409)
            document["name"] = name
            document["revision"] += 1
            if uploaded is not None:
                document["blob_name"], document["sha256"], document["certificates"] = uploaded
                document["blob_history"] = list(dict.fromkeys([*document["blob_history"], uploaded[0]]))
            self._audit(document, "replaced" if uploaded is not None else "renamed", actor_id)
            return document

        saved = self._change(bundle_id, transform)
        self.log("replaced" if uploaded is not None else "renamed", bundle_id=bundle_id, revision=saved["revision"], actor_id=actor_id)
        return self._projection(saved, details=True)

    def _download(self, blob_name: str, digest: str) -> bytes:
        if not re.fullmatch(r"ca-[0-9a-f]{32}/[0-9a-f]{64}\.pem", blob_name):
            raise CABundleError("ca_bundle_integrity", "The certificate object reference is invalid.", 503)
        blob = self._blob().get_blob_client(blob_name)
        properties = blob.get_blob_properties()
        if not 0 < properties["size"] <= MAX_CA_BYTES:
            raise CABundleError("ca_bundle_integrity", "The stored certificate bundle has an invalid size.", 503)
        pem = blob.download_blob(length=MAX_CA_BYTES + 1).readall()
        if len(pem) > MAX_CA_BYTES or hashlib.sha256(pem).hexdigest() != digest:
            raise CABundleError("ca_bundle_integrity", "The stored certificate bundle failed integrity validation.", 503)
        return pem

    def resolve(self, bundle_id: str) -> tuple[str, int, str]:
        document = self._read(bundle_id)
        cache_key = (document["id"], document["revision"], document["sha256"])
        with _PEM_CACHE_LOCK:
            pem = _PEM_CACHE.get(cache_key)
            if pem is not None:
                _PEM_CACHE.move_to_end(cache_key)
        if pem is None:
            pem = self._download(document["blob_name"], document["sha256"])
            with _PEM_CACHE_LOCK:
                _PEM_CACHE[cache_key] = pem
                while len(_PEM_CACHE) > 64:
                    _PEM_CACHE.popitem(last=False)
        return pem.decode("ascii"), document["revision"], document["sha256"]

    def validate_selection(self, bundle_id: str) -> None:
        self._read(bundle_id)

    def revision_token(self, bundle_id: str) -> dict:
        document = self._read(bundle_id)
        return {"bundle_id": document["id"], "revision": document["revision"], "sha256": document["sha256"]}

    def _source(self, source: Mapping) -> tuple[dict | None, str | None]:
        _source_key(source)
        session_token = source.get("session_token")
        if session_token is not None and (
            not isinstance(session_token, str) or len(session_token) > 4096
            or any(ord(character) < 32 for character in session_token)
        ):
            raise CABundleError("ca_bundle_integrity", "The certificate reference session is invalid.", 503)
        headers = {}
        try:
            document = self.sources[source["kind"]].read_item(
                item=source["id"], partition_key=source["id"],
                session_token=session_token,
                response_hook=lambda response_headers, _body: headers.update(response_headers),
            )
        except CosmosResourceNotFoundError:
            return None, headers.get("x-ms-session-token")
        return document, headers.get("x-ms-session-token")

    @staticmethod
    def _endpoints(source: Mapping, document: dict | None) -> list:
        if document is None:
            return []
        if source["kind"] == "user_settings":
            settings = document.get("settings") or {}
            if not isinstance(settings, dict):
                raise CABundleError("ca_bundle_integrity", "The endpoint reference inventory is invalid.", 503)
            endpoints = settings.get("personal_model_endpoints", [])
        else:
            endpoints = document.get("model_endpoints", [])
        if not isinstance(endpoints, list):
            raise CABundleError("ca_bundle_integrity", "The endpoint reference inventory is invalid.", 503)
        return endpoints

    def _fence(self, source: Mapping, expected_etag: str | None) -> None:
        document, _ = self._source(source)
        if document is None:
            if expected_etag is not None:
                return
            try:
                self.sources[source["kind"]].create_item({"id": source["id"], "settings": {}})
            except ResourceExistsError:
                return
            return
        if document.get("_etag") != expected_etag:
            return
        try:
            if source["kind"] == "settings":
                self.global_source_fence(expected_etag)
            else:
                self.sources[source["kind"]].replace_item(
                    item=source["id"], body=document,
                    etag=expected_etag, match_condition=MatchConditions.IfNotModified,
                )
        except (CosmosAccessConditionFailedError, ResourceExistsError):
            return

    def _finish(self, bundle_ids: set[str], token: str, source: Mapping) -> None:
        document, session_token = self._source(source)
        if document is not None and not session_token:
            raise CABundleError("ca_bundle_storage", "Unable to confirm the endpoint reference session. Reload and verify the save.", 503)
        reference = {"kind": source["kind"], "id": source["id"], "session_token": session_token}
        source_key = _source_key(source)
        for bundle_id in bundle_ids:
            def transform(bundle):
                if token not in bundle["pending"]:
                    raise CABundleError("ca_bundle_conflict", "The endpoint save reservation changed. Reload and verify the saved configuration.", 409)
                bundle["pending"].pop(token)
                bundle["references"][source_key] = reference
                return bundle
            self._change(bundle_id, transform)

    @contextmanager
    def reserve_references(self, kind: str, source_id: str, old_endpoints: list, new_endpoints: list, expected_etag: str | None):
        bundle_ids = endpoint_ca_bundle_ids(old_endpoints) | endpoint_ca_bundle_ids(new_endpoints)
        source = {"kind": kind, "id": source_id}
        _source_key(source)
        token = uuid.uuid4().hex
        reserved = set()
        try:
            for bundle_id in sorted(bundle_ids):
                def transform(document):
                    document["pending"][token] = {
                        "source": source, "expected_etag": expected_etag,
                        "deadline": self.clock() + REFERENCE_DEADLINE_SECONDS,
                    }
                    return document
                self._change(bundle_id, transform)
                reserved.add(bundle_id)
            yield
        except (AzureError, CABundleError):
            # Fence the source before dropping reservations: an ambiguous timed-out
            # write must not later resurrect a reference to a deleted bundle.
            if reserved:
                self._fence(source, expected_etag)
                self._finish(reserved, token, source)
            raise
        else:
            if reserved:
                self._finish(reserved, token, source)

    def references(self, bundle_id: str) -> list[dict]:
        document = self._read(bundle_id, allow_deleting=True)
        references = []
        for source in document["references"].values():
            owner_document, _ = self._source(source)
            for endpoint in self._endpoints(source, owner_document):
                if bundle_id not in endpoint_ca_bundle_ids([endpoint]):
                    continue
                references.append({
                    "scope": {"settings": "global", "user_settings": "personal", "groups": "group"}[source["kind"]],
                    "endpoint_id": str(endpoint.get("id") or ""),
                    "endpoint_name": str(endpoint.get("name") or endpoint.get("id") or "Unnamed endpoint"),
                })
        return references

    def delete(self, bundle_id: str, expected_revision: int, actor_id: str) -> None:
        document = self._read(bundle_id, allow_deleting=True)
        for token, pending in list(document["pending"].items()):
            if pending["deadline"] > self.clock():
                raise CABundleError("ca_bundle_in_use", "An endpoint save is using this bundle. Verify the save and try again.", 409)
            self._fence(pending["source"], pending["expected_etag"])
            self._finish({bundle_id}, token, pending["source"])
        document = self._read(bundle_id, allow_deleting=True)
        if document["revision"] != expected_revision:
            raise CABundleError("ca_bundle_conflict", "The CA bundle changed. Reload before deleting it.", 409)
        if document["state"] == "active":
            if self.references(bundle_id):
                raise CABundleError("ca_bundle_in_use", "This bundle is used by saved endpoints. Change their trust selection before deleting it.", 409)
            document["state"] = "deleting"
            self._audit(document, "deletion_started", actor_id)
            try:
                self.metadata.replace_item(
                    item=bundle_id, body=document,
                    etag=document["_etag"], match_condition=MatchConditions.IfNotModified,
                )
            except CosmosAccessConditionFailedError:
                raise CABundleError("ca_bundle_conflict", "The bundle gained a reference or changed. Reload before deleting it.", 409) from None
        for blob_name in document["blob_history"]:
            try:
                self._blob().get_blob_client(blob_name).delete_blob(delete_snapshots="include")
            except ResourceNotFoundError:
                pass
        self.metadata.delete_item(item=bundle_id, partition_key=bundle_id)
        self.log("deleted", bundle_id=bundle_id, revision=expected_revision, actor_id=actor_id)
