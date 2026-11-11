# support_export_store.py
"""Injected Cosmos/Blob persistence with conditional writes and private artifacts."""

import copy
import re
import uuid
from collections.abc import Mapping
from datetime import timedelta

from azure.core import MatchConditions
from azure.core.exceptions import ResourceExistsError, ResourceNotFoundError
from azure.storage.blob import ContentSettings

from cosmos_document_utils import normalize_cosmos_document
from support_export_contracts import SupportExportError, fail, iso, timestamp, utc_now


BLOB_PATH = re.compile(r"[0-9a-f]{32}/[0-9a-f]{32}/(?:snapshot\.json|bundle\.zip|preview\.json)\Z")
LEASE_SECONDS = 900


class SupportExportStore:
    def __init__(self, records, blobs):
        self.records = records
        self.blobs = blobs

    def read(self, record_id, partition):
        try:
            response = self.records.read_item(item=record_id, partition_key=partition)
        except ResourceNotFoundError:
            return None
        return normalize_cosmos_document(response)

    def create(self, document):
        response = self.records.create_item(body=document)
        return normalize_cosmos_document(response)

    def save(self, document):
        etag = document.get("_etag")
        if not isinstance(etag, str) or not etag:
            fail("storage_contract", "Support-export storage returned an invalid revision.", 503)
        body = {key: copy.deepcopy(item) for key, item in document.items() if not key.startswith("_")}
        try:
            response = self.records.replace_item(
                item=document["id"], body=body, etag=etag,
                match_condition=MatchConditions.IfNotModified,
            )
        except Exception as exc:
            if getattr(exc, "status_code", None) in (409, 412):
                fail("export_conflict", "This export changed. Refresh its status before trying again.", 409)
            raise
        return normalize_cosmos_document(response)

    def query(self, query, parameters, *, partition=None, limit=100):
        options = {"max_item_count": min(limit, 100)}
        if partition is None:
            options["enable_cross_partition_query"] = True
        else:
            options["partition_key"] = partition
        rows = self.records.query_items(query=query, parameters=parameters, **options)
        result = []
        for row in rows:
            if not isinstance(row, Mapping):
                fail("storage_contract", "Support-export storage returned an invalid query row.", 503)
            result.append(dict(row))
            if len(result) >= limit:
                break
        return result

    def configuration(self):
        document = self.read("configuration", "configuration")
        return document.get("configuration", {}) if document else {}

    def set_configuration(self, value):
        document = self.read("configuration", "configuration")
        if document:
            document["configuration"] = value
            self.save(document)
        else:
            self.create({
                "id": "configuration", "partition_key": "configuration",
                "record_kind": "configuration", "configuration": value,
            })

    def require_private_storage(self, *, create=False):
        if self.blobs is None:
            fail("storage_required", "Configure application Blob storage before generating support exports.", 503)
        try:
            properties = self.blobs.get_container_properties()
        except ResourceNotFoundError:
            if not create:
                fail("storage_container_missing", "Initialize the private support-export container before generating.", 503)
            try:
                self.blobs.create_container()
            except ResourceExistsError:
                pass
            properties = self.blobs.get_container_properties()
        public_access = properties.get("public_access")
        if public_access:
            fail("public_export_storage", "The support-export Blob container must have public access disabled.", 503)

    def put(self, path, data, expires_at, *, content_type="application/json"):
        if not BLOB_PATH.fullmatch(path):
            fail("invalid_artifact", "Invalid support-export artifact.", 503)
        self.require_private_storage()
        if self.read("blob-cleanup", "configuration") is None:
            try:
                self.create({
                    "id": "blob-cleanup", "partition_key": "configuration", "record_kind": "cleanup",
                    "continuation": None,
                })
            except Exception as exc:
                if getattr(exc, "status_code", None) != 409:
                    raise
                if self.read("blob-cleanup", "configuration") is None:
                    raise
        self.blobs.get_blob_client(path).upload_blob(
            data, overwrite=False,
            metadata={"expires_at": str(int(timestamp(expires_at).timestamp()))},
            content_settings=ContentSettings(content_type=content_type),
        )

    def get(self, path):
        if not isinstance(path, str) or not BLOB_PATH.fullmatch(path):
            fail("invalid_artifact", "Invalid support-export artifact.", 503)
        self.require_private_storage()
        return self.blobs.get_blob_client(path).download_blob().readall()

    def delete_artifacts(self, job_id):
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            fail("invalid_artifact", "Invalid support-export artifact.", 503)
        if self.blobs is None:
            fail("storage_required", "Support-export cleanup requires application Blob storage.", 503)
        for blob in self.blobs.list_blobs(name_starts_with=job_id + "/"):
            if not BLOB_PATH.fullmatch(blob.name):
                fail("invalid_artifact", "An unexpected support-export artifact needs administrator review.", 503)
            try:
                self.blobs.delete_blob(blob.name)
            except ResourceNotFoundError:
                pass

    def sweep_expired_blobs(self):
        """Bounded orphan recovery also works after a job document's TTL elapsed."""
        self.require_private_storage()
        cursor = self.read("blob-cleanup", "configuration")
        pages = self.blobs.list_blobs(include=["metadata"], results_per_page=100).by_page(
            continuation_token=cursor.get("continuation") if cursor else None,
        )
        page = next(pages, None)
        if page is not None:
            for blob in page:
                if not BLOB_PATH.fullmatch(blob.name):
                    fail("invalid_artifact", "An unexpected support-export artifact needs administrator review.", 503)
                try:
                    expires_at = int((blob.metadata or {})["expires_at"])
                except (KeyError, ValueError, TypeError):
                    fail("invalid_artifact", "A support-export artifact has invalid expiry metadata.", 503)
                if expires_at <= int(utc_now().timestamp()):
                    try:
                        self.blobs.delete_blob(blob.name)
                    except ResourceNotFoundError:
                        pass
        document = {
            "id": "blob-cleanup", "partition_key": "configuration", "record_kind": "cleanup",
            "continuation": pages.continuation_token,
            "next_scan_at": iso(utc_now() + timedelta(minutes=1)),
        }
        if cursor:
            document["_etag"] = cursor["_etag"]
            self.save(document)
        else:
            self.create(document)

    def acquire_slot(self, now=None):
        now = now or utc_now()
        for index in range(2):
            slot_id = f"worker-{index}"
            slot = self.read(slot_id, "worker-slots")
            token = uuid.uuid4().hex
            if slot is None:
                try:
                    return self.create({
                        "id": slot_id, "partition_key": "worker-slots", "record_kind": "lease",
                        "lease_token": token, "lease_until": iso(now + timedelta(seconds=LEASE_SECONDS)),
                    })
                except Exception as exc:
                    if getattr(exc, "status_code", None) == 409:
                        continue
                    raise
            if timestamp(slot["lease_until"]) > now:
                continue
            slot.update(lease_token=token, lease_until=iso(now + timedelta(seconds=LEASE_SECONDS)))
            try:
                return self.save(slot)
            except SupportExportError as exc:
                if exc.status == 409:
                    continue
                raise
        return None

    def renew_slot(self, slot):
        current = self.read(slot["id"], "worker-slots")
        if current is None or current["lease_token"] != slot["lease_token"] or timestamp(current["lease_until"]) <= utc_now():
            fail("lease_lost", "The export worker lease expired. Retry the export.", 409)
        current["lease_until"] = iso(utc_now() + timedelta(seconds=LEASE_SECONDS))
        return self.save(current)

    def release_slot(self, slot):
        current = self.read(slot["id"], "worker-slots")
        if current and current["lease_token"] == slot["lease_token"]:
            current["lease_until"] = iso(utc_now())
            self.save(current)
