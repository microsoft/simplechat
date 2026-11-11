# test_admin_support_export_api.py
"""
Real support route/service tests across identity and consent boundaries.
Version: 0.261.426
Implemented in: 0.261.426
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "application" / "single_app"))

from test_support.support_exports import build_api, build_service


ROOT = "/api/admin/support-exports"


@pytest.mark.parametrize("roles", [["User"], ["ControlCenterAdmin"], ["ControlCenterDashboardReader"], "Admin"])
def test_non_admin_roles_cannot_query_export_sources(roles):
    service = build_service()[0]
    _, client = build_api(service, actor="someone", roles=roles)
    response = client.get(ROOT + "/users")
    assert response.status_code == 403


def test_review_is_required_and_binds_the_exact_request():
    service = build_service()[0]
    _, client = build_api(service)
    request = {"user_id": "owner", "sources": ["activity"]}
    no_review = client.post(ROOT, json={"request": request, "retry_key": "one"})
    assert no_review.status_code == 400
    review = client.post(ROOT + "/review", json=request)
    assert review.status_code == 200 and review.json["intervals"]
    created = client.post(ROOT, json={
        "request": request, "retry_key": "one", "review_id": review.json["review_id"],
    })
    assert created.status_code == 200
    assert created.headers["Cache-Control"] == "no-store"
    assert "privacy_salt" not in created.json and "source_configuration" not in created.json
    _, other = build_api(service, actor="other-admin")
    forbidden = other.get(ROOT + "/" + created.json["id"])
    assert forbidden.status_code == 404


def test_owner_only_consent_preview_and_decision():
    service = build_service()[0]
    _, admin = build_api(service)
    request = {
        "user_id": "owner", "sources": ["activity"], "include_transcripts": True,
        "conversation_ids": ["conversation-1"],
    }
    review = admin.post(ROOT + "/review", json=request)
    created = admin.post(ROOT, json={
        "request": request, "retry_key": "consent", "review_id": review.json["review_id"],
    })
    consent_id = "consent-" + created.json["id"]
    admin_attempt = admin.get("/api/support-export-consents/" + consent_id)
    assert admin_attempt.status_code == 404
    _, owner = build_api(service, actor="owner", roles=["User"])
    preview = owner.get("/api/support-export-consents/" + consent_id + "/preview")
    assert preview.status_code == 200 and preview.json["fingerprint"]
    assert "owner@example.test" not in str(preview.json["preview"])
    approved = owner.post("/api/support-export-consents/" + consent_id + "/decision", json={
        "action": "approve", "fingerprint": preview.json["fingerprint"],
    })
    assert approved.status_code == 200 and approved.json["status"] == "approved"
    service.tick()
    download = admin.get(ROOT + "/" + created.json["id"] + "/download")
    assert download.status_code == 200 and download.mimetype == "application/zip"
    assert download.headers["Cache-Control"] == "no-store"
    revoked = owner.post("/api/support-export-consents/" + consent_id + "/decision", json={"action": "revoke"})
    assert revoked.status_code == 200
    blocked = admin.get(ROOT + "/" + created.json["id"] + "/download")
    assert blocked.status_code == 409
