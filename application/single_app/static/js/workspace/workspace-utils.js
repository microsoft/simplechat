// workspace-utils.js

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

export function getDocumentSyncBadgeHtml(doc, compact = false) {
    if (!isSyncedDocument(doc)) {
        return '';
    }

    const spacingClass = compact ? 'me-2 align-middle' : '';

    return `<span class="badge bg-info text-dark ${spacingClass}" title="Synced file"><i class="bi bi-arrow-repeat me-1"></i></span>`;
}

export function getDocumentSyncDetailsHtml(doc) {
    const synced = isSyncedDocument(doc);
    const badgeClass = synced ? 'bg-info text-dark' : 'bg-secondary';
    const badgeText = synced ? 'Yes' : 'No';

    let details = `<p class="mb-1"><strong>Synced:</strong> <span class="badge ${badgeClass}">${badgeText}</span></p>`;

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

    const badge = document.createElement('span');
    badge.className = synced ? 'badge bg-info text-dark' : 'badge bg-secondary';
    badge.textContent = synced ? 'Yes' : 'No';

    statusLine.append(label, badge);
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