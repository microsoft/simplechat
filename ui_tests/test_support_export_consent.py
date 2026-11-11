# test_support_export_consent.py
"""
Classic and V2 owner-only support-data consent browser coverage.
Version: 0.261.428
Implemented in: 0.261.428
"""

import sys
from pathlib import Path

import pytest
from playwright.sync_api import expect

sys.path.insert(0, str(Path(__file__).resolve().parent / "fixtures"))

from playwright_connection import connect_options
from support_export_backend import API_PATTERN, ORIGIN, ClassicSupportPage, SupportBackend
from test_v2_approvals_and_terms_pages import ApprovalsFixture


pytestmark = pytest.mark.ui


def request_transcripts(backend):
    return backend.service.create(
        "test-admin", ["Admin"],
        {"user_id": "owner", "sources": ["activity"], "conversation_ids": ["conversation-1"], "include_transcripts": True},
        "owner-consent",
    )


@pytest.mark.parametrize("interface,width", [("classic", 1440), ("v2", 390)])
def test_owner_reviews_approves_and_revokes_exact_snapshots(page, interface, width):
    admin = SupportBackend()
    job = request_transcripts(admin)
    owner = SupportBackend(service=admin.service, actor="owner", roles=["User"])
    if interface == "classic":
        fixture = ClassicSupportPage(page, owner, consent=True)
        fixture.open(width=width, query="?support_export=" + job["id"])
        region = page.locator('[data-support-exports="consent"]')
    else:
        fixture = ApprovalsFixture(page)
        page.route(API_PATTERN, owner.handle)
        fixture.open("/v2/approvals?support_export=" + job["id"], width=width)
        region = page.get_by_role("region", name="Request details")
    approve = region.get_by_role("button", name="Approve whole-conversation snapshots")
    expect(approve).to_be_disabled()
    region.get_by_role("button", name="Review my snapshot preview").click()
    expect(approve).to_be_disabled()
    region.get_by_label("I approve releasing the whole requested snapshots", exact=False).check()
    approve.click()
    expect(region.get_by_role("button", name="Revoke further transcript downloads")).to_be_visible()
    consent = admin.service.consent_details("owner", "consent-" + job["id"])
    assert consent["status"] == "approved"
    region.get_by_role("button", name="Revoke further transcript downloads").click()
    consent = admin.service.consent_details("owner", "consent-" + job["id"])
    assert consent["status"] == "revoked"
    fixture.assert_clean()
