# test_model_endpoint_ca_bundles.py
"""
Certificate registry and reference-fencing regressions.
Version: 0.261.052
Implemented in: 0.261.052

Uses real PEM parsing and registry logic with external Blob/Cosmos I/O doubles.
No application bootstrap, deployment environment, credentials, or network access.
"""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys

from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.cosmos.exceptions import CosmosAccessConditionFailedError, CosmosResourceNotFoundError
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID
import pytest

APP = Path(__file__).resolve().parents[1] / "application" / "single_app"
sys.path.insert(0, str(APP))

from model_endpoint_ca_bundles import (
    CABundleError, CABundleRegistry, MAX_CA_BYTES, REFERENCE_DEADLINE_SECONDS,
    normalize_ca_bundle_reference, validate_ca_certificates,
)


class Container:
    def __init__(self):
        self.items = {}
        self.revision = 0
        self.before_replace = None
        self.read_options = []

    def read_item(self, item, partition_key, **kwargs):
        self.read_options.append(kwargs)
        if item not in self.items:
            raise CosmosResourceNotFoundError(status_code=404)
        result = deepcopy(self.items[item])
        if kwargs.get("response_hook"):
            kwargs["response_hook"]({"x-ms-session-token": f"session-{result['_etag']}"}, result)
        return result

    def create_item(self, body):
        if body["id"] in self.items:
            raise ResourceExistsError()
        return self._save(body)

    def _save(self, body):
        self.revision += 1
        document = {**deepcopy(body), "_etag": str(self.revision)}
        self.items[body["id"]] = document
        return deepcopy(document)

    def replace_item(self, item, body, etag=None, **kwargs):
        callback, self.before_replace = self.before_replace, None
        if callback:
            callback()
        if etag != self.items[item]["_etag"]:
            raise CosmosAccessConditionFailedError(status_code=412)
        return self._save(body)

    def delete_item(self, item, **kwargs):
        self.items.pop(item)

    def query_items(self, **kwargs):
        return [deepcopy(item) for item in self.items.values() if item.get("state") == "active"]


class Blob:
    def __init__(self, owner, name):
        self.owner, self.name = owner, name

    def upload_blob(self, data, **kwargs):
        if self.name in self.owner.items:
            raise ResourceExistsError()
        self.owner.items[self.name] = bytes(data)

    def get_blob_properties(self):
        if self.name not in self.owner.items:
            raise ResourceNotFoundError()
        return {"size": len(self.owner.items[self.name])}

    def download_blob(self, length):
        data = self.owner.items[self.name][:length]
        return type("Download", (), {"readall": lambda self: data})()

    def delete_blob(self, **kwargs):
        if self.owner.fail_delete:
            raise ResourceNotFoundError("Synthetic missing object.")
        if self.name not in self.owner.items:
            raise ResourceNotFoundError()
        self.owner.items.pop(self.name)


class BlobContainer:
    def __init__(self):
        self.items = {}
        self.public_access = None
        self.fail_delete = False

    def create_container(self):
        return None

    def get_container_properties(self):
        return {"public_access": self.public_access}

    def get_blob_client(self, name):
        return Blob(self, name)

    def get_container_client(self, name):
        if name != "model-endpoint-ca-bundles":
            raise AssertionError("CA certificates must not use document containers.")
        return self


@pytest.fixture(scope="module")
def certificates():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    now = datetime.now(timezone.utc)

    def certificate(name, *, ca=True):
        subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, name)])
        return (
            x509.CertificateBuilder().subject_name(subject).issuer_name(subject)
            .public_key(key.public_key()).serial_number(x509.random_serial_number())
            .not_valid_before(now - timedelta(days=1)).not_valid_after(now + timedelta(days=365))
            .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
            .sign(key, hashes.SHA256()).public_bytes(serialization.Encoding.PEM)
        )

    return {
        "first": certificate("First root"), "second": certificate("Replacement root"),
        "leaf": certificate("Not a CA", ca=False),
        "private_key": key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        ),
    }


@pytest.fixture
def registry():
    metadata, blobs = Container(), BlobContainer()
    sources = {kind: Container() for kind in ("settings", "user_settings", "groups")}
    sources["settings"].create_item({"id": "app_settings", "model_endpoints": []})
    events, clock = [], [1000]

    def fence(etag):
        document = sources["settings"].read_item("app_settings", "app_settings")
        sources["settings"].replace_item("app_settings", document, etag=etag)

    store = CABundleRegistry(
        metadata, lambda: blobs, sources,
        global_source_fence=fence, log=lambda action, **fields: events.append((action, fields)),
        clock=lambda: clock[0],
    )
    return store, metadata, blobs, sources, events, clock


def endpoint(bundle_id):
    return {
        "id": "endpoint-one", "name": "<img src=x onerror=alert(1)>", "provider": "custom",
        "connection": {"ca_bundle_mode": "bundle", "ca_bundle_id": bundle_id},
    }


def test_create_resolve_replace_and_shared_worker_refresh(registry, certificates):
    store, metadata, blobs, sources, events, _ = registry
    created = store.create("Internal roots", certificates["first"], "admin")
    material, revision, digest = store.resolve(created["id"])
    assert material.encode("ascii") == certificates["first"]
    assert revision == 1
    assert len(digest) == 64
    assert len(created["certificates"]) == 1
    assert "BEGIN CERTIFICATE" not in json.dumps(created)
    assert "pending" not in created and "references" not in created
    replaced = store.replace(created["id"], "New roots", certificates["second"], 1, "admin")
    second_worker = CABundleRegistry(
        metadata, lambda: blobs, sources, global_source_fence=store.global_source_fence, log=store.log,
    )
    updated, revision, updated_digest = second_worker.resolve(created["id"])
    assert replaced["id"] == created["id"]
    assert revision == 2 and updated_digest != digest
    assert updated.encode("ascii") == certificates["second"]
    assert len(blobs.items) == 2
    assert [event["action"] for event in replaced["audit_history"]] == ["created", "replaced"]
    assert [action for action, _ in events] == ["created", "replaced"]


@pytest.mark.parametrize("kind", ("private_key", "leaf", "empty", "junk", "oversize", "mixed", "duplicate"))
def test_only_bounded_ca_certificates_are_accepted(certificates, kind):
    values = {
        **certificates, "empty": b"", "junk": b"not a certificate",
        "oversize": b"x" * (MAX_CA_BYTES + 1),
        "mixed": certificates["first"] + certificates["private_key"],
        "duplicate": certificates["first"] * 2,
    }
    with pytest.raises(CABundleError):
        validate_ca_certificates(values[kind])


def test_public_container_and_tampered_certificate_fail_closed(registry, certificates):
    store, _, blobs, _, _, _ = registry
    blobs.public_access = "blob"
    with pytest.raises(CABundleError, match="private"):
        store.create("Unsafe", certificates["first"], "admin")
    blobs.public_access = None
    created = store.create("Checked", certificates["first"], "admin")
    blob_name = next(iter(blobs.items))
    blobs.items[blob_name] = certificates["second"]
    with pytest.raises(CABundleError, match="integrity"):
        store.resolve(created["id"])


def test_references_block_delete_and_session_tokens_cross_workers(registry, certificates):
    store, _, blobs, sources, _, _ = registry
    created = store.create("Used root", certificates["first"], "admin")
    source = sources["settings"]
    document = source.read_item("app_settings", "app_settings")
    new_endpoints = [endpoint(created["id"])]
    with store.reserve_references("settings", "app_settings", [], new_endpoints, document["_etag"]):
        document["model_endpoints"] = new_endpoints
        source.replace_item("app_settings", document, etag=document["_etag"])
    refs = store.references(created["id"])
    assert refs == [{
        "scope": "global", "endpoint_id": "endpoint-one",
        "endpoint_name": "<img src=x onerror=alert(1)>",
    }]
    assert source.read_options[-1]["session_token"].startswith("session-")
    with pytest.raises(CABundleError, match="saved endpoints"):
        store.delete(created["id"], 1, "admin")
    document = source.read_item("app_settings", "app_settings")
    with store.reserve_references("settings", "app_settings", new_endpoints, [], document["_etag"]):
        document["model_endpoints"] = []
        source.replace_item("app_settings", document, etag=document["_etag"])
    store.delete(created["id"], 1, "admin")
    assert not blobs.items


def test_reservation_wins_concurrent_delete(registry, certificates):
    store, metadata, _, sources, _, _ = registry
    created = store.create("Race root", certificates["first"], "admin")
    source = sources["settings"].read_item("app_settings", "app_settings")
    held = []

    def concurrent_save():
        reservation = store.reserve_references("settings", "app_settings", [], [endpoint(created["id"])], source["_etag"])
        reservation.__enter__()
        held.append(reservation)

    metadata.before_replace = concurrent_save
    with pytest.raises(CABundleError, match="reference or changed"):
        store.delete(created["id"], 1, "admin")
    for reservation in held:
        reservation.__exit__(None, None, None)
    material, _, _ = store.resolve(created["id"])
    assert material.encode("ascii") == certificates["first"]


def test_expired_reservation_fences_late_parent_write(registry, certificates):
    store, metadata, _, sources, _, clock = registry
    created = store.create("Abandoned root", certificates["first"], "admin")
    original = sources["settings"].read_item("app_settings", "app_settings")
    bundle = metadata.read_item(created["id"], created["id"])
    bundle["pending"]["abandoned"] = {
        "source": {"kind": "settings", "id": "app_settings"},
        "expected_etag": original["_etag"], "deadline": clock[0] + REFERENCE_DEADLINE_SECONDS,
    }
    metadata.replace_item(created["id"], bundle, etag=bundle["_etag"])
    clock[0] += REFERENCE_DEADLINE_SECONDS + 1
    store.delete(created["id"], 1, "admin")
    original["model_endpoints"] = [endpoint(created["id"])]
    with pytest.raises(CosmosAccessConditionFailedError):
        sources["settings"].replace_item("app_settings", original, etag=original["_etag"])


@pytest.mark.parametrize("connection", (
    {"ca_bundle_mode": "unsafe"},
    {"ca_bundle_mode": "public", "ca_bundle_id": "ca-invalid"},
    {"ca_bundle_mode": "bundle", "ca_bundle_id": "../escape"},
))
def test_invalid_trust_selection_is_not_silently_inherited(connection):
    with pytest.raises(CABundleError):
        normalize_ca_bundle_reference(connection)
