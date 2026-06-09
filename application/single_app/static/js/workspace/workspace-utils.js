// workspace-utils.js

const DOCUMENT_NOT_SYNCED_TOOLTIP = 'This document was uploaded manually and is not managed by File Sync.';

export function escapeHtml(unsafe) {
    if (unsafe === null || typeof unsafe === 'undefined') return '';
    return unsafe.toString()
        .replace(/&/g, "&amp;")
        .replace(/</g, "&lt;")
        .replace(/>/g, "&gt;")
        .replace(/"/g, "&quot;")
        .replace(/'/g, "&#39;");
    }

export function isSyncedDocument(doc) {
    return !!(doc && doc.file_sync && typeof doc.file_sync === 'object');
}

export function getDocumentSyncSourceLabel(doc) {
    if (!isSyncedDocument(doc)) {
        return '';
    }

    const syncMetadata = doc.file_sync;
    return syncMetadata.source_name
        || syncMetadata.relative_path
        || syncMetadata.remote_path
        || 'File Sync';
}

function getDocumentSyncTypeConfig(doc) {
    const sourceType = String(doc?.file_sync?.source_type || 'smb').trim().toLowerCase();
    const sourceTypeMap = {
        smb: { label: 'SMB', className: 'bg-primary text-white', title: 'Managed by File Sync from an SMB source.' },
        azure_files: { label: 'Azure Files', className: 'bg-info text-dark', title: 'Managed by File Sync from Azure Files.' },
        m365sp: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
        m365_sp: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
        m365_sharepoint: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
        sharepoint_online: { label: 'M365SP', className: 'bg-info text-dark', title: 'Managed by File Sync from Microsoft 365 SharePoint.' },
        one_drive: { label: 'OneDrive', className: 'bg-dark text-white', title: 'Managed by File Sync from OneDrive.' },
        onedrive: { label: 'OneDrive', className: 'bg-dark text-white', title: 'Managed by File Sync from OneDrive.' },
        google: { label: 'Google', className: 'bg-warning text-dark', title: 'Managed by File Sync from Google Workspace.' },
        google_workspace: { label: 'Google', className: 'bg-warning text-dark', title: 'Managed by File Sync from Google Workspace.' },
        spo: { label: 'SPO', className: 'bg-success text-white', title: 'Managed by File Sync from on-prem SharePoint.' },
        sharepoint_on_prem: { label: 'SPO', className: 'bg-success text-white', title: 'Managed by File Sync from on-prem SharePoint.' },
    };
    return sourceTypeMap[sourceType] || { label: sourceType.toUpperCase() || 'SYNC', className: 'bg-secondary text-white', title: 'Managed by File Sync.' };
}

function getDocumentSyncTypeBadgeHtml(doc, compact = false) {
    const syncType = getDocumentSyncTypeConfig(doc);
    const spacingClass = compact ? 'me-2 align-middle' : '';
    return `<span class="badge ${syncType.className} ${spacingClass}" title="${escapeHtml(syncType.title)}"><i class="bi bi-arrow-repeat me-1"></i>${escapeHtml(syncType.label)}</span>`;
}

function appendDocumentSyncTypeBadge(container, doc) {
    const syncType = getDocumentSyncTypeConfig(doc);
    const badge = document.createElement('span');
    badge.className = `badge ${syncType.className}`;
    badge.title = syncType.title;

    const icon = document.createElement('i');
    icon.className = 'bi bi-arrow-repeat me-1';
    badge.appendChild(icon);
    badge.appendChild(document.createTextNode(syncType.label));
    container.appendChild(badge);
}

export function getDocumentSyncBadgeHtml(doc, compact = false) {
    if (!isSyncedDocument(doc)) {
        return '';
    }

    return getDocumentSyncTypeBadgeHtml(doc, compact);
}

export function getDocumentSyncDetailsHtml(doc) {
    const synced = isSyncedDocument(doc);
    let details = synced
        ? `<p class="mb-1"><strong>Synced:</strong> ${getDocumentSyncTypeBadgeHtml(doc)}</p>`
        : `<p class="mb-1"><strong>Synced:</strong> <span class="badge bg-secondary" title="${escapeHtml(DOCUMENT_NOT_SYNCED_TOOLTIP)}">No</span></p>`;

    if (synced) {
        const syncMetadata = doc.file_sync;
        const sourceLabel = getDocumentSyncSourceLabel(doc);
        if (sourceLabel) {
            details += `<p class="mb-1"><strong>Sync Source:</strong> ${escapeHtml(sourceLabel)}</p>`;
        }
        if (syncMetadata.remote_path) {
            details += `<p class="mb-1"><strong>Remote Path:</strong> ${escapeHtml(syncMetadata.remote_path)}</p>`;
        }
    }

    return details;
}

export function setDocumentSyncStatusElement(element, doc) {
    if (!element) {
        return;
    }

    const synced = isSyncedDocument(doc);
    element.className = synced ? 'alert alert-info py-2 mb-3' : 'alert alert-secondary py-2 mb-3';
    element.replaceChildren();

    const statusLine = document.createElement('div');
    statusLine.className = 'd-flex align-items-center gap-2 flex-wrap';

    const label = document.createElement('strong');
    label.textContent = 'Synced:';
    statusLine.appendChild(label);

    if (synced) {
        appendDocumentSyncTypeBadge(statusLine, doc);
    } else {
        const badge = document.createElement('span');
        badge.className = 'badge bg-secondary';
        badge.title = DOCUMENT_NOT_SYNCED_TOOLTIP;
        badge.textContent = 'No';
        statusLine.appendChild(badge);
    }

    element.appendChild(statusLine);

    if (!synced) {
        return;
    }

    const syncMetadata = doc.file_sync;
    const sourceLabel = getDocumentSyncSourceLabel(doc);
    const detailLine = document.createElement('div');
    detailLine.className = 'small text-muted mt-1';
    const detailParts = [];
    if (sourceLabel) {
        detailParts.push(`Source: ${sourceLabel}`);
    }
    if (syncMetadata.remote_path) {
        detailParts.push(`Remote path: ${syncMetadata.remote_path}`);
    }
    detailLine.textContent = detailParts.join(' | ');
    element.appendChild(detailLine);
}