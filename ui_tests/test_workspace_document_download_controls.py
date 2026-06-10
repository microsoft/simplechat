# test_workspace_document_download_controls.py
"""
UI regression test for workspace document download controls.
Version: 0.241.181
Implemented in: 0.241.181

This test ensures personal, group, and public workspace document download
controls are present, policy-gated, and wired to the expected download APIs.
"""

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]
APP_ROOT = REPO_ROOT / "application" / "single_app"


def _read(relative_path: str) -> str:
    return (REPO_ROOT / relative_path).read_text(encoding="utf-8")


def test_personal_workspace_download_controls_are_policy_gated() -> None:
    """Validate personal workspace single and bulk download UI wiring."""
    template = _read("application/single_app/templates/workspace.html")
    script = _read("application/single_app/static/js/workspace/workspace-documents.js")

    assert 'id="download-selected-btn"' in template
    assert "Download Selected" in template
    assert "personalWorkspaceFileDownloadsEnabled = Boolean(data.file_downloads_enabled);" in script
    assert "window.downloadDocumentFile" in script
    assert "window.downloadSelectedDocuments" in script
    assert "/api/documents/${encodeURIComponent(documentId)}/download" in script
    assert "/api/documents/download" in script
    assert "document_ids: Array.from(selectedDocuments)" in script
    assert "downloadBtn.classList.toggle('d-none', !personalWorkspaceFileDownloadsEnabled);" in script
    assert "downloadSelectedBtn.addEventListener('click', window.downloadSelectedDocuments);" in script


def test_group_workspace_download_controls_are_policy_gated() -> None:
    """Validate group workspace single and bulk download UI wiring."""
    template = _read("application/single_app/templates/group_workspaces.html")

    assert 'id="group-download-selected-btn"' in template
    assert "Download Selected" in template
    assert "let groupFileDownloadsEnabled = false;" in template
    assert "let groupFileDownloadEnabledGroupIds = [];" in template
    assert "function canDownloadGroupDocuments()" in template
    assert "groupFileDownloadsEnabled = Boolean(data.file_downloads_enabled);" in template
    assert "data.file_download_enabled_group_ids" in template
    assert "window.downloadGroupDocumentFile" in template
    assert "window.downloadGroupSelectedDocuments" in template
    assert "/api/group_documents/${encodeURIComponent(documentId)}/download" in template
    assert "/api/group_documents/download" in template
    assert "document_ids: Array.from(groupSelectedDocuments)" in template
    assert 'downloadBtn.classList.toggle("d-none", !canDownloadGroupDocuments());' in template
    assert 'groupDownloadSelectedBtn.addEventListener("click", downloadGroupSelectedDocuments);' in template


def test_public_workspace_download_controls_are_policy_gated() -> None:
    """Validate public workspace single and bulk download UI wiring."""
    template = _read("application/single_app/templates/public_workspaces.html")
    script = _read("application/single_app/static/js/public/public_workspace.js")

    assert 'id="public-download-selected-btn"' in template
    assert "Download Selected" in template
    assert "let publicFileDownloadsEnabled = false;" in script
    assert "publicFileDownloadsEnabled = Boolean(data.file_downloads_enabled);" in script
    assert "window.downloadPublicDocumentFile" in script
    assert "window.downloadPublicSelectedDocuments" in script
    assert "/api/public_documents/${encodeURIComponent(documentId)}/download" in script
    assert "/api/public_documents/download" in script
    assert "document_ids: Array.from(publicSelectedDocuments)" in script
    assert "downloadBtn.classList.toggle('d-none', !publicFileDownloadsEnabled);" in script
    assert "publicDownloadSelectedBtn.addEventListener('click', downloadPublicSelectedDocuments);" in script
    assert "createPublicDropdownItem('bi-download', 'Download file'" in script
