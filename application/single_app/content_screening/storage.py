# storage.py
"""Private, revision-bound, immutable artifacts in Enhanced Citations storage."""

import hashlib
import importlib
import json
import re
from pathlib import Path

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import ContentSettings

from content_screening.contracts import (
    ScreeningConfigurationError,
    ScreeningConflictError,
    ScreeningError,
    ScreeningValidationError,
    Subject,
    hash_payload,
    normalize_identifier,
)


DEFAULT_CONTAINER_NAME = "content-screening"
ARTIFACT_PREFIX = "screening/v1"
PART_BYTES = 8 * 1024 * 1024
MAX_ARTIFACT_BYTES = 128 * 1024 * 1024
MAX_MANIFEST_BYTES = 32768
HASH_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
ORDINARY_CONTAINERS = frozenset({
    "user-documents", "group-documents", "public-documents", "personal-chat", "group-chat",
})


def _subject(value):
    return value if isinstance(value, Subject) else Subject.from_dict(value)


def _hash(data):
    return hashlib.sha256(data).hexdigest()


def _property(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _not_found(exc):
    return getattr(exc, "status_code", None) == 404 or isinstance(exc, ResourceNotFoundError)


def _already_exists(exc):
    return getattr(exc, "status_code", None) in {409, 412} or isinstance(exc, ResourceExistsError)


def revision_prefix(subject):
    """Return a backend-only prefix; no user filename or scope ID is a path."""
    return f"{ARTIFACT_PREFIX}/{_subject(subject).key}/"


class ScreeningStorage:
    def __init__(self, client=None, container_name=None):
        self._client = client
        self._container_name = container_name
        self._verified_container = None

    def _resolve(self):
        if self._client is None:
            configuration = importlib.import_module("config")
            allowed_name = getattr(
                configuration, "storage_account_content_screening_container_name", DEFAULT_CONTAINER_NAME,
            )
            if self._container_name is not None and self._container_name != allowed_name:
                raise ScreeningConfigurationError("The screening artifact container is not configured.")
            self._client = configuration.CLIENTS.get("storage_account_office_docs_client")
            self._container_name = allowed_name
        if self._client is None:
            raise ScreeningConfigurationError()
        self._container_name = self._container_name or DEFAULT_CONTAINER_NAME
        if (
            not isinstance(self._container_name, str)
            or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])", self._container_name)
            or self._container_name in ORDINARY_CONTAINERS
        ):
            raise ScreeningConfigurationError("A private screening artifact container is required.")
        return self._client

    @property
    def container_name(self):
        self._resolve()
        return self._container_name

    def _container(self, *, create=False):
        client = self._resolve()
        container = self._verified_container or client.get_container_client(self._container_name)
        try:
            properties = container.get_container_properties()
        except Exception as exc:
            if not create or not _not_found(exc):
                raise
            try:
                container.create_container()
            except Exception as create_exc:
                if not _already_exists(create_exc):
                    raise
            properties = container.get_container_properties()
        if _property(properties, "public_access") not in (None, ""):
            raise ScreeningConfigurationError("Screening artifacts require a private container.")
        self._verified_container = container
        return container

    def validate_connection(self):
        """Explicitly probe/create the private container for feature activation."""
        self._container(create=True)
        return {"configured": True, "private": True}

    def _blob(self, path, *, create=False):
        return self._container(create=create).get_blob_client(path)

    def _put_immutable(self, path, payload, content_type):
        digest = _hash(payload)
        blob = self._blob(path, create=True)
        try:
            result = blob.upload_blob(
                payload, overwrite=False,
                metadata={"screening_sha256": digest, "screening_size": str(len(payload))},
                content_settings=ContentSettings(
                    content_type=content_type, content_disposition="attachment",
                    cache_control="no-store",
                ),
            )
            etag = _property(result, "etag")
        except Exception as exc:
            if not _already_exists(exc):
                raise
            properties = blob.get_blob_properties()
            metadata = _property(properties, "metadata", {}) or {}
            if metadata.get("screening_sha256") != digest or _property(properties, "size") != len(payload):
                raise ScreeningConflictError("A screening artifact cannot be overwritten.") from None
            etag = _property(properties, "etag")
            self._download({
                "blob_name": path, "sha256": digest, "size": len(payload), "etag": etag,
            }, limit=max(PART_BYTES, MAX_MANIFEST_BYTES))
        if not isinstance(etag, str) or not etag:
            raise ScreeningError(code="screening_blob_version_missing")
        return {"blob_name": path, "sha256": digest, "size": len(payload), "etag": etag}

    def write_bytes(self, subject, scan_id, name, data, content_type="application/octet-stream"):
        subject = _subject(subject)
        scan_key = hash_payload(normalize_identifier(scan_id, "scan"))
        artifact_key = hash_payload(normalize_identifier(name, "artifact"))
        if not isinstance(data, bytes) or len(data) > MAX_ARTIFACT_BYTES:
            raise ScreeningValidationError("The screening artifact exceeds its storage limit.")
        if not isinstance(content_type, str) or len(content_type) > 128 or not re.fullmatch(r"[A-Za-z0-9.+-]+/[A-Za-z0-9.+-]+", content_type):
            raise ScreeningValidationError("The screening artifact type is invalid.")
        base = f"{revision_prefix(subject)}{scan_key}/{artifact_key}"
        parts = [
            self._put_immutable(
                f"{base}/part-{index:04d}", data[offset:offset + PART_BYTES], content_type,
            )
            for index, offset in enumerate(range(0, max(len(data), 1), PART_BYTES))
        ]
        manifest = {
            "schema_version": 1, "subject_key": subject.key, "scan_key": scan_key,
            "artifact_key": artifact_key, "sha256": _hash(data), "size": len(data),
            "content_type": content_type, "parts": parts,
        }
        payload = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        stored = self._put_immutable(f"{base}/manifest", payload, "application/json")
        return {
            "schema_version": 1, "container": self.container_name, "subject_key": subject.key,
            "scan_key": scan_key, "artifact_key": artifact_key, "blob_name": stored["blob_name"],
            "etag": stored["etag"], "manifest_sha256": stored["sha256"],
            "sha256": manifest["sha256"], "size": len(data),
        }

    def _validate_reference(self, reference, subject):
        subject = _subject(subject)
        if not isinstance(reference, dict) or reference.get("schema_version") != 1:
            raise ScreeningValidationError("The screening artifact reference is invalid.")
        if reference.get("subject_key") != subject.key or reference.get("container") != self.container_name:
            raise ScreeningConflictError("The artifact does not belong to this source revision.")
        for key in ("scan_key", "artifact_key", "sha256", "manifest_sha256"):
            if not isinstance(reference.get(key), str) or not HASH_PATTERN.fullmatch(reference[key]):
                raise ScreeningValidationError("The screening artifact reference is invalid.")
        base = f"{revision_prefix(subject)}{reference['scan_key']}/{reference['artifact_key']}"
        if (
            reference.get("blob_name") != f"{base}/manifest"
            or not isinstance(reference.get("etag"), str) or not reference["etag"]
            or type(reference.get("size")) is not int or not 0 <= reference["size"] <= MAX_ARTIFACT_BYTES
        ):
            raise ScreeningValidationError("The screening artifact reference is invalid.")
        return base

    def _download(self, part, *, limit):
        size = part.get("size")
        if type(size) is not int or not 0 <= size <= limit or not part.get("etag"):
            raise ScreeningValidationError("The screening artifact manifest is invalid.")
        try:
            blob = self._blob(part["blob_name"])
            properties = blob.get_blob_properties()
            if _property(properties, "size") != size or _property(properties, "etag") != part["etag"]:
                raise ScreeningConflictError()
            range_arguments = {"offset": 0, "length": size + 1} if size else {}
            stream = blob.download_blob(
                etag=part["etag"], match_condition=MatchConditions.IfNotModified,
                max_concurrency=1, **range_arguments,
            )
            data = stream.readall()
        except Exception as exc:
            if getattr(exc, "status_code", None) in {404, 409, 412} or _not_found(exc):
                raise ScreeningConflictError("The screening artifact changed or is missing.") from None
            raise
        if len(data) != size or _hash(data) != part.get("sha256"):
            raise ScreeningConflictError("The screening artifact content does not match its manifest.")
        return data

    def _read_verified_bytes(self, reference, subject, *, rebind_versions=False):
        base = self._validate_reference(reference, subject)
        blob = self._blob(reference["blob_name"])
        try:
            properties = blob.get_blob_properties()
        except Exception as exc:
            if _not_found(exc):
                raise ScreeningConflictError("The screening artifact is missing.") from None
            raise
        manifest_size = _property(properties, "size")
        manifest_bytes = self._download({
            "blob_name": reference["blob_name"],
            "etag": _property(properties, "etag") if rebind_versions else reference["etag"],
            "size": manifest_size, "sha256": reference["manifest_sha256"],
        }, limit=MAX_MANIFEST_BYTES)
        try:
            manifest = json.loads(manifest_bytes)
        except (TypeError, ValueError, UnicodeError):
            raise ScreeningValidationError("The screening artifact manifest is invalid.") from None
        if not isinstance(manifest, dict) or any(
            manifest.get(key) != reference.get(key)
            for key in ("schema_version", "subject_key", "scan_key", "artifact_key", "size", "sha256")
        ):
            raise ScreeningConflictError()
        parts = manifest.get("parts")
        expected_count = max(1, (reference["size"] + PART_BYTES - 1) // PART_BYTES)
        if not isinstance(parts, list) or len(parts) != expected_count:
            raise ScreeningValidationError("The screening artifact manifest is invalid.")
        chunks = []
        for index, part in enumerate(parts):
            expected_size = min(PART_BYTES, max(0, reference["size"] - index * PART_BYTES))
            if (
                not isinstance(part, dict) or part.get("blob_name") != f"{base}/part-{index:04d}"
                or part.get("size") != expected_size
            ):
                raise ScreeningValidationError("The screening artifact manifest is invalid.")
            if rebind_versions:
                properties = self._blob(part["blob_name"]).get_blob_properties()
                part = {**part, "etag": _property(properties, "etag")}
            chunks.append(self._download(part, limit=PART_BYTES))
        result = b"".join(chunks)
        if len(result) != reference["size"] or _hash(result) != reference["sha256"]:
            raise ScreeningConflictError()
        return result

    def read_bytes(self, reference, subject):
        return self._read_verified_bytes(reference, subject)

    def rebind_transferred_reference(self, reference, subject):
        """Explicitly revalidate copied bytes without releasing a document hold.

        A privileged restore/review adapter must authorize the subject and persist
        the returned reference with CAS. Ordinary reads never relax their ETag.
        """
        data = self._read_verified_bytes(reference, subject, rebind_versions=True)
        return self.write_bytes(
            subject, f"transferred:{reference['scan_key']}",
            f"{reference['artifact_key']}:{reference['manifest_sha256']}", data,
        )

    def write_json(self, subject, scan_id, name, value):
        try:
            data = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (ValueError, TypeError, RecursionError):
            raise ScreeningValidationError("The screening artifact must contain valid JSON.") from None
        return self.write_bytes(subject, scan_id, name, data, "application/json")

    def read_json(self, reference, subject):
        try:
            return json.loads(self.read_bytes(reference, subject))
        except (ValueError, UnicodeError):
            raise ScreeningValidationError("The screening artifact does not contain valid JSON.") from None

    def write_source(self, subject, scan_id, source_path, file_name):
        normalize_identifier(file_name, "filename")
        path = Path(source_path)
        if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
            raise ScreeningValidationError("The source file is missing or exceeds the screening limit.")
        with path.open("rb") as source:
            data = source.read(MAX_ARTIFACT_BYTES + 1)
        return self.write_bytes(subject, scan_id, "source", data)

    def delete_revision(self, subject):
        prefix = revision_prefix(subject)
        try:
            container = self._container()
        except Exception as exc:
            if _not_found(exc):
                return
            raise
        for blob in container.list_blobs(name_starts_with=prefix, results_per_page=100):
            path = _property(blob, "name")
            if not isinstance(path, str) or not re.fullmatch(
                f"{re.escape(prefix)}[0-9a-f]{{64}}/[0-9a-f]{{64}}/(manifest|part-[0-9]{{4}})", path,
            ):
                raise ScreeningValidationError("A screening artifact path is invalid.")
            etag = _property(blob, "etag")
            if not etag:
                raise ScreeningConflictError()
            try:
                container.get_blob_client(path).delete_blob(
                    etag=etag, match_condition=MatchConditions.IfNotModified,
                    delete_snapshots="include",
                )
            except Exception as exc:
                if _not_found(exc):
                    continue
                if getattr(exc, "status_code", None) in {409, 412}:
                    raise ScreeningConflictError() from None
                raise
