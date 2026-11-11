# test_admin_support_export_jobs.py
"""
Behavioral support-job, SDK boundary, archive, and consent regressions.
Version: 0.261.428
Implemented in: 0.261.428

Run the real service/store/collectors with real CosmosDict point responses,
ETags, isolated Blob transport, and no application/Azure bootstrap.
"""

import copy
import hashlib
import io
import json
import sys
from datetime import timedelta
from pathlib import Path

import pytest
from azure.cosmos._cosmos_responses import CosmosDict

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from support_export_contracts import SupportExportError, iso, utc_now
from support_export_service import SupportExportService
from support_export_sources import SupportExportSources
from support_export_store import SupportExportStore
from test_support.support_exports import build_service


@pytest.fixture
def fixture():
    return build_service()


def create(fixture, *, transcripts=False, retry="retry-one", **changes):
    service = fixture[0]
    request = {
        "user_id": "owner", "sources": ["activity"], "include_transcripts": transcripts,
        "conversation_ids": ["conversation-1"] if transcripts else [], **changes,
    }
    return service.create("admin", ["Admin"], request, retry)


def finish(service, job_id):
    job = service.store.read(job_id, "admin")
    slot = service.store.acquire_slot()
    assert slot is not None
    try:
        service.run(job, slot)
    finally:
        service.store.release_slot(slot)
    return service.store.read(job_id, "admin")


def test_real_sdk_normalization_etags_and_lost_updates(fixture):
    service, _, records, *_ = fixture
    created = create(fixture)
    sdk = records.read_item(created["id"], "admin")
    assert type(sdk) is CosmosDict
    first = service.store.read(created["id"], "admin")
    second = service.store.read(created["id"], "admin")
    assert type(first) is dict and first["_etag"]
    first["phase"] = "One writer"
    saved = service.store.save(first)
    assert type(saved) is dict and saved["_etag"] != second["_etag"]
    with pytest.raises(SupportExportError, match="changed"):
        service.store.save(second)


def test_real_collectors_zip_coverage_and_no_secret_bytes(fixture):
    import zipfile

    service = fixture[0]
    created = create(fixture)
    final = finish(service, created["id"])
    assert final["status"] == "ready", final.get("error")
    data = service.download("admin", ["Admin"], created["id"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        assert archive.testzip() is None
        assert "manifest.json" in archive.namelist()
        joined = b"\n".join(archive.read(name) for name in archive.namelist())
        assert b"fake-password" not in joined
        assert b"owner@example.test" not in joined
        assert b"unrelated event" not in joined
        assert b"hidden prompt" not in joined
        manifest = json.loads(archive.read("manifest.json"))
        assert manifest["sources"]["activity"]["records"] == 1
        assert manifest["sources"]["telemetry"]["status"] == "excluded_by_admin"
        for name, checksum in manifest["checksums_sha256"].items():
            actual = hashlib.sha256(archive.read(name)).hexdigest()
            assert actual == checksum


def test_exact_owner_consent_snapshot_and_revocation(fixture):
    import zipfile

    service = fixture[0]
    created = create(fixture, transcripts=True)
    assert created["status"] == "waiting_for_consent"
    assert fixture[-1] == [("owner", created["id"])]
    consent_id = "consent-" + created["id"]
    with pytest.raises(SupportExportError):
        service.decide("admin", consent_id, "approve", "forged")
    preview = service.consent_preview("owner", consent_id)
    decision = service.decide("owner", consent_id, "approve", preview["fingerprint"])
    assert decision["status"] == "approved"
    final = finish(service, created["id"])
    assert final["status"] == "ready", final.get("error")
    data = service.download("admin", ["Admin"], created["id"])
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        transcript = archive.read("conversations/conversation-1.json")
        assert b"Contact" in transcript and b"owner@example.test" not in transcript
        assert b"hidden prompt" not in transcript
        conversation = json.loads(transcript)
        manifest = json.loads(archive.read("manifest.json"))
        activity = json.loads(archive.read("logs/activity.jsonl").splitlines()[0])
        assert conversation["conversation_id"] == manifest["conversations"][0]
        assert activity["properties"]["conversation_id"] == conversation["conversation_id"]
    revoked = service.decide("owner", consent_id, "revoke")
    assert revoked["status"] == "revoked"
    with pytest.raises(SupportExportError):
        service.download("admin", ["Admin"], created["id"])


def test_changed_snapshot_cannot_reuse_owner_preview(fixture):
    service, containers, *_ = fixture
    created = create(fixture, transcripts=True)
    consent_id = "consent-" + created["id"]
    preview = service.consent_preview("owner", consent_id)
    message = containers["messages"].read_item("message-1", "conversation-1")
    message["content"] = "Changed while the user was reviewing."
    containers["messages"].upsert_item(message)
    with pytest.raises(SupportExportError, match="snapshot changed"):
        service.decide("owner", consent_id, "approve", preview["fingerprint"])


def test_admin_isolation_retry_and_single_active_request(fixture):
    service = fixture[0]
    first = create(fixture)
    repeated = create(fixture)
    assert repeated["id"] == first["id"]
    with pytest.raises(SupportExportError, match="cannot change"):
        create(fixture, sources=["file_processing"])
    with pytest.raises(SupportExportError, match="active export"):
        create(fixture, retry="retry-two")
    with pytest.raises(SupportExportError):
        service.status("other-admin", ["Admin"], first["id"])
    for roles in (["User"], ["ControlCenterAdmin"], ["ControlCenterDashboardReader"]):
        with pytest.raises(SupportExportError):
            service.status("admin", roles, first["id"])


def test_shared_transcripts_and_preconsent_messages_are_blocked(fixture):
    service, containers, *_ = fixture
    personal = containers["conversations"].read_item("conversation-1", "conversation-1")
    personal["conversation_kind"] = "collaboration_source"
    personal["collaboration_conversation_id"] = "conversation-1"
    containers["conversations"].upsert_item(personal)
    listing = service.sources.conversations("owner")
    assert "Private conversation title" not in json.dumps(listing)
    assert "Contact owner" not in json.dumps(listing)
    assert listing["items"][0]["transcript_eligible"] is False
    with pytest.raises(SupportExportError):
        create(fixture, transcripts=True)


def test_cancellation_fences_worker_publication(fixture):
    service = fixture[0]
    created = create(fixture)
    collect = service.sources.collect_cosmos

    def cancel_during_collection(source, plan, intervals, progress):
        service.cancel("admin", ["Admin"], created["id"])
        return collect(source, plan, intervals, progress)

    service.sources.collect_cosmos = cancel_during_collection
    final = finish(service, created["id"])
    assert final["status"] == "cancelled"
    assert not fixture[3].data


def test_expiry_is_enforced_before_physical_cleanup(fixture):
    service = fixture[0]
    created = create(fixture)
    final = finish(service, created["id"])
    final["expires_at"] = iso(utc_now() - timedelta(seconds=1))
    service.store.save(final)
    assert fixture[3].data
    with pytest.raises(SupportExportError) as error:
        service.download("admin", ["Admin"], created["id"])
    assert error.value.status == 410
    service.tick()
    assert not fixture[3].data
    expired = service.store.read(created["id"], "admin")
    assert expired["cleanup_complete"] is True


def test_public_storage_and_worker_concurrency_are_rejected(fixture):
    service = fixture[0]
    fixture[3].public_access = "blob"
    with pytest.raises(SupportExportError, match="public access"):
        create(fixture)
    slots = [service.store.acquire_slot() for _ in range(3)]
    assert slots[0] is not None and slots[1] is not None and slots[2] is None
