// content-screening.js
(function () {
    "use strict";

    const heldStates = new Set([
        "held", "pending_scan", "scanning", "scan_error", "error", "incomplete",
        "pending_review", "remediating", "publishing", "rejected", "deleting", "deleted"
    ]);
    const statusLabels = {
        pending_scan: ["Pending scan — held", "text-bg-info"],
        scanning: ["Scanning — held", "text-bg-info"],
        pending_review: ["Needs review — held", "text-bg-warning"],
        held: ["Content held", "text-bg-warning"],
        scan_error: ["Scan error — held", "text-bg-danger"],
        error: ["Scan error — held", "text-bg-danger"],
        incomplete: ["Incomplete scan — held", "text-bg-danger"],
        remediating: ["Remediating — held", "text-bg-info"],
        publishing: ["Publishing — held", "text-bg-info"],
        approved_with_flags: ["Approved with flags", "text-bg-warning"],
        cleared: ["Screening cleared", "text-bg-success"],
        rejected: ["Rejected — held", "text-bg-danger"],
        deleting: ["Deleting — held", "text-bg-secondary"],
        deleted: ["Deleted", "text-bg-secondary"],
        queued: ["Scan queued", "text-bg-secondary"],
        not_enrolled: ["Not screened", "text-bg-secondary"]
    };
    const workspaces = new Map();
    const documentSummaries = new Map();
    const reviewPermissions = new Map();
    let confirmationPending = false;

    class ScreeningError extends Error {
        constructor(status = 0, code = "") {
            super("Content screening request failed.");
            this.status = status;
            this.code = code;
        }
    }

    function element(tag, className = "", text = null) {
        const node = document.createElement(tag);
        if (className) node.className = className;
        if (text !== null && text !== undefined) node.textContent = String(text);
        return node;
    }

    function button(label, className = "btn btn-outline-secondary", handler = null) {
        const node = element("button", className, label);
        node.type = "button";
        if (handler) node.addEventListener("click", handler);
        return node;
    }

    function showMessage(container, message, variant = "danger") {
        if (!container) return;
        const allowedVariants = new Set(["danger", "warning", "info", "success", "secondary"]);
        container.className = `alert alert-${allowedVariants.has(variant) ? variant : "danger"} mt-3`;
        container.textContent = message;
        container.setAttribute("role", "alert");
    }

    function clearMessage(container) {
        if (!container) return;
        container.replaceChildren();
        container.classList.add("d-none");
    }

    function errorMessage(error) {
        if (error?.status === 409 || error?.status === 412 || error?.status === 428) {
            return "This revision or policy has changed. Refresh required; no decision was applied by this request.";
        }
        if (error?.status === 401) return "Your session has expired. Sign in again, then refresh.";
        if (error?.status === 403) return "You do not have permission for this action. No content or decision was changed.";
        if (error?.status === 404) return "This item is unavailable or you no longer have access. Refresh the workspace.";
        if (error?.status === 400 || error?.status === 422) return "The request could not be validated. Check the policy, source selection, and required fields.";
        if (error?.status === 429) return "Screening is busy. Wait before retrying; the document remains held.";
        if (error?.status === 503) return "Screening or its storage dependency is unavailable. Existing holds remain in effect.";
        return "The request could not be completed. Refresh to check its current status before retrying.";
    }

    function apiUrl(path) {
        const url = new URL(path, window.location.origin);
        if (url.origin !== window.location.origin || !url.pathname.startsWith("/api/content-screening/")) {
            throw new ScreeningError(400);
        }
        return url;
    }

    function requestHeaders(extra = {}) {
        const headers = { Accept: "application/json", ...extra };
        const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
        if (csrfToken) headers["X-CSRFToken"] = csrfToken;
        return headers;
    }

    async function request(path, options = {}) {
        let response;
        try {
            response = await fetch(apiUrl(path), {
                credentials: "same-origin",
                cache: "no-store",
                redirect: "manual",
                ...options,
                headers: requestHeaders(options.body ? { "Content-Type": "application/json", ...options.headers } : options.headers)
            });
        } catch (error) {
            throw error instanceof ScreeningError ? error : new ScreeningError();
        }
        if (response.redirected || response.type === "opaqueredirect") throw new ScreeningError(401);
        if (!response.ok) {
            const failure = await response.json().catch(() => ({}));
            const code = typeof failure?.code === "string" ? failure.code : "";
            throw new ScreeningError(response.status, code);
        }
        if (response.status === 204) return {};
        if (!response.headers.get("Content-Type")?.includes("application/json")) throw new ScreeningError();
        let data;
        try {
            data = await response.json();
        } catch {
            throw new ScreeningError();
        }
        if (!data || typeof data !== "object") throw new ScreeningError();
        return { ...data, responseEtag: response.headers.get("ETag") || null };
    }

    function newRequestId() {
        if (typeof crypto.randomUUID === "function") return crypto.randomUUID();
        return Array.from(crypto.getRandomValues(new Uint32Array(4)), value => value.toString(16).padStart(8, "0")).join("");
    }

    function hasAction(actions, action) {
        return Array.isArray(actions) ? actions.includes(action) : actions?.[action] === true;
    }

    function summaryOf(doc) {
        return doc?.content_screening && typeof doc.content_screening === "object" ? doc.content_screening : null;
    }

    function isHeld(doc) {
        const summary = summaryOf(doc);
        return Boolean(summary && (summary.available === false || heldStates.has(summary.state)));
    }

    function statusBadge(doc) {
        const summary = summaryOf(doc);
        if (!summary) return null;
        const [label, className] = statusLabels[summary.state] || (isHeld(doc)
            ? ["Content unavailable", "text-bg-warning"] : ["Screening status", "text-bg-secondary"]);
        const badge = element("span", `badge screening-document-status ${className}`, label);
        badge.dataset.screeningState = String(summary.state || "");
        const count = Number(summary.finding_count);
        if (Number.isSafeInteger(count) && count > 0) {
            badge.append(document.createTextNode(` · ${count} finding${count === 1 ? "" : "s"}`));
        }
        return badge;
    }

    function scopeKey(scope) {
        return `${scope.scopeType}:${scope.scopeId || ""}`;
    }

    function scopeQuery(scope) {
        const query = new URLSearchParams({ scope_type: scope.scopeType });
        if (scope.scopeId) query.set("scope_id", scope.scopeId);
        return query;
    }

    function reviewUrl(scope, reviewId = "", tab = "") {
        const query = scopeQuery(scope);
        if (reviewId) query.set("scan_id", reviewId);
        if (tab) query.set("tab", tab);
        return `/content-review?${query.toString()}`;
    }

    function formatLocator(locator = {}) {
        const coordinate = value => value === null || value === undefined ? "?" : String(value);
        if (Number.isInteger(locator.page_number) && locator.page_number > 0) {
            return `Page ${locator.page_number}`;
        }
        if (locator.kind === "slide") return `Slide ${coordinate(locator.slide_number ?? locator.slide_index)}`;
        if (["table_sheet", "table_cell", "table_formula"].includes(locator.kind)) {
            let label = `Sheet ${coordinate(locator.sheet ?? locator.sheet_index)}`;
            if (locator.row !== undefined) label += ` · row ${coordinate(locator.row)}`;
            if (locator.column !== undefined) label += ` · column ${coordinate(locator.column)}`;
            if (locator.value_type) label += ` · ${coordinate(locator.value_type)}`;
            return label;
        }
        if (locator.kind === "metadata") return `Metadata · ${coordinate(locator.field ?? locator.name)}`;
        if (locator.kind === "figure" || locator.kind === "vision") return `Figure / image · ${coordinate(locator.figure_id ?? locator.index)}`;
        if (locator.kind === "segment" || locator.kind === "legacy_segment") {
            const label = locator.kind === "legacy_segment" ? "Legacy segment" : "Segment";
            return `${label} · ${coordinate(locator.segment_id ?? locator.segment_index ?? locator.index)}`;
        }
        if (locator.kind === "page") return "Source unit · physical page number unavailable";
        return `Section · ${coordinate(locator.section ?? locator.section_id ?? locator.paragraph ?? locator.index)}`;
    }

    function codePointLength(text) {
        return Array.from(String(text)).length;
    }

    function selectedCodePointRange(root) {
        const selection = window.getSelection();
        if (!selection || selection.rangeCount !== 1 || selection.isCollapsed) return null;
        const range = selection.getRangeAt(0);
        if (!root.contains(range.startContainer) || !root.contains(range.endContainer)) return null;
        const prefix = document.createRange();
        prefix.selectNodeContents(root);
        prefix.setEnd(range.startContainer, range.startOffset);
        const start = codePointLength(prefix.toString());
        const end = start + codePointLength(range.toString());
        return end > start ? { start, end } : null;
    }

    function renderSourceText(root, text, offsets = null) {
        root.replaceChildren();
        const characters = Array.from(String(text));
        if (!offsets || !Number.isInteger(offsets.start) || !Number.isInteger(offsets.end)
            || offsets.start < 0 || offsets.end <= offsets.start || offsets.end > characters.length) {
            root.textContent = text;
            return;
        }
        root.append(
            document.createTextNode(characters.slice(0, offsets.start).join("")),
            element("mark", "", characters.slice(offsets.start, offsets.end).join("")),
            document.createTextNode(characters.slice(offsets.end).join(""))
        );
    }

    async function confirmAction(title, description, label, destructive = false) {
        const modal = document.getElementById("screening-confirm-modal");
        if (!modal || !window.bootstrap?.Modal || confirmationPending) return false;
        confirmationPending = true;
        document.getElementById("screening-confirm-title").textContent = title;
        document.getElementById("screening-confirm-description").textContent = description;
        const confirmButton = document.getElementById("screening-confirm-action");
        confirmButton.textContent = label;
        confirmButton.className = destructive ? "btn btn-danger" : "btn btn-primary";
        const instance = bootstrap.Modal.getOrCreateInstance(modal);
        return new Promise(resolve => {
            let accepted = false;
            const accept = () => {
                accepted = true;
                instance.hide();
            };
            confirmButton.addEventListener("click", accept, { once: true });
            modal.addEventListener("hidden.bs.modal", () => {
                confirmButton.removeEventListener("click", accept);
                confirmationPending = false;
                resolve(accepted);
            }, { once: true });
            instance.show();
        });
    }

    async function downloadAttachment(path, fileName) {
        let response;
        try {
            response = await fetch(apiUrl(path), { credentials: "same-origin", cache: "no-store", redirect: "manual", headers: requestHeaders() });
        } catch {
            throw new ScreeningError();
        }
        if (response.redirected || response.type === "opaqueredirect") throw new ScreeningError(401);
        if (!response.ok) throw new ScreeningError(response.status);
        if (!/^attachment(?:;|$)/i.test(response.headers.get("Content-Disposition") || "")) throw new ScreeningError();
        if (response.headers.get("X-Content-Type-Options")?.toLowerCase() !== "nosniff"
            || !/\bno-store\b/i.test(response.headers.get("Cache-Control") || "")) throw new ScreeningError();
        const bytes = await response.arrayBuffer();
        // Even active-format originals are opaque downloads, never app-origin HTML previews.
        const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
        const link = element("a");
        link.href = url;
        link.download = String(fileName || "screening-document").replace(/[\\/:*?"<>|\u0000-\u001f]/g, "_");
        document.body.appendChild(link);
        link.click();
        link.remove();
        window.setTimeout(() => URL.revokeObjectURL(url), 60000);
    }

    function rememberDocument(doc) {
        if (doc?.id) documentSummaries.set(String(doc.id), doc);
    }

    function checkUsable(documentIds) {
        const held = Array.from(documentIds || []).some(id => isHeld(documentSummaries.get(String(id))));
        if (!held) return true;
        const message = "A selected document is held. Use Content review; held sources cannot be used in chat, analysis, or ordinary downloads.";
        document.querySelectorAll("[data-screening-workspace-message]").forEach(node => showMessage(node, message, "warning"));
        return false;
    }

    function createHeldDocument(doc, scope, mode = "row") {
        rememberDocument(doc);
        const cardMode = mode === "card";
        const outer = element(cardMode ? "div" : "tr", cardMode
            ? "col-12 col-md-6 col-xl-4" : "document-row screening-held-document");
        const content = cardMode ? element("div", "card item-card document-item-card screening-held-document h-100") : outer;
        content.dataset.documentId = String(doc.id);
        const prefix = scope.scopeType === "personal" ? "" : `${scope.scopeType}-`;
        if (!cardMode) outer.id = `${prefix}doc-row-${doc.id}`;
        const body = cardMode ? element("div", "card-body d-flex flex-column gap-2") : content;
        const selectCell = element(cardMode ? "div" : "td", cardMode ? "document-item-card__check" : "align-middle");
        const checkbox = element("input", "form-check-input document-checkbox d-none");
        checkbox.type = "checkbox";
        checkbox.dataset.documentId = String(doc.id);
        checkbox.setAttribute("aria-label", `Select ${doc.file_name || "document"} for management`);
        selectCell.appendChild(checkbox);
        const title = element(cardMode ? "h6" : "td", cardMode ? "card-title text-break" : "document-file-cell align-middle", doc.file_name || "Document");
        const status = element(cardMode ? "div" : "td", cardMode ? "document-item-card__status" : "document-title-cell align-middle");
        status.appendChild(statusBadge(doc));
        const actions = element(cardMode ? "div" : "td", cardMode ? "item-card-buttons d-flex flex-wrap gap-2" : "document-actions-cell align-middle");
        body.append(selectCell, title, status, actions);
        if (cardMode) {
            body.appendChild(element("p", "document-item-card__summary small mb-0", "Knowledge is held. Protected content is available only in authorized Content review."));
            content.appendChild(body);
            outer.appendChild(content);
        }
        decorateDocument(outer, doc, scope);
        return outer;
    }

    function decorateDocument(node, doc, scope) {
        rememberDocument(doc);
        const summary = summaryOf(doc);
        if (summary && !node.querySelector("[data-screening-state]")) {
            const target = node.querySelector(".document-item-card__status, .document-title-cell") || node.cells?.[2];
            if (target) {
                if (target.classList.contains("document-item-card__status")) target.replaceChildren(statusBadge(doc));
                else {
                    const wrapper = element("div", "mt-1");
                    wrapper.appendChild(statusBadge(doc));
                    target.appendChild(wrapper);
                }
            }
        }
        const target = node.querySelector(".item-card-buttons, .document-actions-cell") || node.cells?.[3];
        if (!target || target.querySelector("[data-screening-document-actions]")) return;
        const controls = element("span", "d-inline-flex flex-wrap gap-1 mt-1");
        controls.dataset.screeningDocumentActions = "";
        controls.dataset.screeningDocumentId = String(doc.id);
        controls.dataset.screeningScope = scopeKey(scope);
        target.appendChild(controls);
        updateDocumentScanControl(controls, workspaces.get(scopeKey(scope)));
        if (summary?.scan_id || summary?.review_id) {
            const key = JSON.stringify([scopeKey(scope), String(doc.id), summary.scan_id, summary.updated_at, summary.state]);
            let cached = reviewPermissions.get(key);
            if (!cached || Date.now() - cached.created > 30000) {
                cached = {
                    created: Date.now(),
                    request: Promise.resolve().then(() => window.ContentScreening.api.getStatus(scope, doc.id))
                };
                reviewPermissions.set(key, cached);
            }
            cached.request.then(status => {
                if (!controls.isConnected || status.can_review !== true || !status.scan_id) return;
                const link = element("a", "btn btn-sm btn-outline-secondary", "Content review");
                link.href = reviewUrl(scope, status.scan_id);
                controls.appendChild(link);
            }).catch(() => {
                reviewPermissions.delete(key);
            });
        }
    }

    function filterDocuments(docs, scope) {
        const workspace = workspaces.get(scopeKey(scope));
        const value = workspace?.root.querySelector("[data-screening-filter]")?.value || "all";
        return docs.filter(doc => {
            rememberDocument(doc);
            const state = summaryOf(doc)?.state;
            if (value === "held") return isHeld(doc);
            if (value === "scanning") return ["pending_scan", "scanning", "queued"].includes(state);
            if (value === "error") return ["error", "scan_error", "incomplete"].includes(state);
            return value === "all" || value === state;
        });
    }

    function decorateFolderTable(table, docs, scope) {
        if (!table?.tBodies[0]) return;
        const body = table.tBodies[0];
        const existing = new Map(Array.from(body.rows).map(row => [
            row.querySelector("[data-document-id]")?.dataset.documentId, row
        ]));
        const rows = document.createDocumentFragment();
        docs.forEach(doc => {
            const row = isHeld(doc) ? createHeldDocument(doc, scope) : existing.get(String(doc.id));
            if (!row) return;
            decorateDocument(row, doc, scope);
            rows.appendChild(row);
        });
        body.replaceChildren(rows);
    }

    function updateDocumentScanControl(controls, workspace) {
        const existing = controls.querySelector("[data-screening-scan-document]");
        if (!workspace?.canScan) {
            existing?.remove();
            return;
        }
        if (existing) return;
        const scan = button("Scan", "btn btn-sm btn-outline-primary", () => startScan(workspace.scope, [controls.dataset.screeningDocumentId], workspace));
        scan.dataset.screeningScanDocument = "";
        controls.appendChild(scan);
    }

    function syncWorkspaceSelection(workspace) {
        const ids = workspace.getSelectedIds();
        const selectedButton = workspace.root.querySelector("[data-screening-scan-selected]");
        selectedButton.disabled = !workspace.canScan || ids.length === 0;
        const heldSelected = ids.some(id => isHeld(documentSummaries.get(String(id))));
        const prefix = workspace.scope.scopeType === "personal" ? "" : `${workspace.scope.scopeType}-`;
        const chatButton = document.getElementById(`${prefix}chat-selected-btn`);
        const downloadButton = document.getElementById(`${prefix}download-selected-btn`);
        const metadataButton = document.getElementById(`${prefix}extract-selected-metadata-btn`);
        [chatButton, downloadButton, metadataButton].forEach(control => {
            if (!control) return;
            if (heldSelected) {
                control.dataset.screeningDisabled = "true";
                control.disabled = true;
                control.title = "Held sources require Content review.";
            } else if (control.dataset.screeningDisabled) {
                control.disabled = false;
                delete control.dataset.screeningDisabled;
                control.removeAttribute("title");
            }
        });
    }

    function registerWorkspace(options) {
        const root = document.querySelector(`[data-content-screening-workspace][data-scope-type="${options.scopeType}"]`);
        if (!root) return;
        const scope = { scopeType: options.scopeType, scopeId: options.scopeId || "" };
        (options.documents || []).forEach(rememberDocument);
        let workspace = workspaces.get(scopeKey(scope));
        if (!workspace) {
            workspace = { root, scope, canScan: false, getSelectedIds: () => [] };
            workspaces.set(scopeKey(scope), workspace);
        }
        Object.assign(workspace, {
            getSelectedIds: options.getSelectedIds || workspace.getSelectedIds,
            refresh: options.refresh,
            render: options.render || options.refresh,
            documents: options.documents || []
        });
        root.screeningWorkspace = workspace;
        window.clearTimeout(workspace.statusTimer);
        if (workspace.documents.some(doc => ["pending_scan", "scanning", "remediating", "publishing"].includes(summaryOf(doc)?.state))) {
            workspace.statusTimer = window.setTimeout(() => {
                if (!document.hidden && root.screeningWorkspace === workspace) workspace.refresh?.();
            }, 4000);
        }
        root.querySelector("[data-screening-review-link]").href = reviewUrl(scope);
        root.querySelector("[data-screening-policy-link]").href = reviewUrl(scope, "", "policy");
        if (!root.dataset.screeningBound) {
            root.dataset.screeningBound = "true";
            root.querySelector("[data-screening-filter]").addEventListener("change", () => root.screeningWorkspace.render?.());
            root.querySelector("[data-screening-scan-selected]").addEventListener("click", () => {
                const current = root.screeningWorkspace;
                startScan(current.scope, current.getSelectedIds(), current);
            });
            root.querySelector("[data-screening-scan-workspace]").addEventListener("click", () => {
                const current = root.screeningWorkspace;
                startScan(current.scope, null, current);
            });
        }
        syncWorkspaceSelection(workspace);
        if (workspace.loading || workspace.loaded) return;
        workspace.loading = true;
        window.ContentScreening.api.getConfiguration().then(configuration => {
            if (!configuration.enabled) {
                return {
                    new_scans_enabled: false, allowed_actions: [],
                    prerequisites: { ready: false }
                };
            }
            return window.ContentScreening.api.getPolicy(scope);
        }).then(data => {
            workspace.canScan = hasAction(data.allowed_actions, "scan") && data.new_scans_enabled === true && data.prerequisites?.ready === true;
            workspace.loaded = true;
            if (root.screeningWorkspace !== workspace) return;
            root.querySelectorAll("[data-screening-scan-selected], [data-screening-scan-workspace]").forEach(control => {
                control.classList.toggle("d-none", !hasAction(data.allowed_actions, "scan"));
                control.disabled = !workspace.canScan;
            });
            root.querySelector("[data-screening-workspace-notice]").textContent = data.new_scans_enabled
                ? "Scans hold each document when processing starts. Required administrator checks cannot be weakened."
                : "New scanning is disabled. Existing holds and approved-with-flags warnings remain in effect.";
            document.querySelectorAll("[data-screening-document-actions]").forEach(controls => {
                if (controls.dataset.screeningScope === scopeKey(scope)) updateDocumentScanControl(controls, workspace);
            });
            syncWorkspaceSelection(workspace);
        }).catch(error => {
            if (root.screeningWorkspace !== workspace) return;
            if (error.status === 403) root.querySelector("[data-screening-workspace-notice]").textContent = "Only authorized workspace managers can scan or configure additions. Existing holds still apply.";
            else showMessage(root.querySelector("[data-screening-workspace-message]"), errorMessage(error), "warning");
        }).finally(() => { workspace.loading = false; });
    }

    function jobStateLabel(job) {
        if (job.cancel_requested === true && !["cancelled", "completed", "completed_with_findings", "failed", "incomplete"].includes(job.status)) {
            return "Cancellation requested — existing holds retained";
        }
        const labels = {
            queued: "Queued", running: "Scanning", scanning: "Scanning", completed: "Completed",
            completed_with_findings: "Completed with findings", incomplete: "Incomplete — holds retained",
            cancelled: "Cancelled — existing holds retained", cancelling: "Cancellation requested",
            failed: "Failed — holds retained", paused: "Paused"
        };
        return labels[job.status] || "Scan job";
    }

    function renderJob(job, scope, container, onRefresh = null) {
        const card = element("section", "list-group-item border rounded p-3 mb-2");
        card.dataset.screeningJobId = String(job.id);
        card.appendChild(element("h3", "h6", jobStateLabel(job)));
        const counts = job.counts || {};
        const number = value => Number.isSafeInteger(value) && value >= 0 ? value : 0;
        const total = number(counts.total);
        const labels = {
            total: "total", queued: "queued", running: "running", completed: "completed",
            scanned: "scanned", cleared: "cleared", findings: "with findings", incomplete: "incomplete",
            failed: "failed", cancelled: "cancelled", enumerated: "enumerated", retry: "awaiting retry", skipped: "skipped"
        };
        const counters = Object.entries(labels).filter(([key]) => Number.isSafeInteger(counts[key]) && counts[key] >= 0)
            .map(([key, label]) => `${counts[key]} ${label}`);
        card.appendChild(element("p", "small mb-2", counters.join(" · ") || "Progress counters are not available yet."));
        if (total) {
            const progress = element("progress", "screening-job-progress");
            progress.max = total;
            if (Number.isSafeInteger(counts.scanned) || Number.isSafeInteger(counts.completed)) {
                progress.value = Math.min(total, number(counts.scanned ?? counts.completed));
            }
            progress.setAttribute("aria-label", "Scan job progress");
            card.appendChild(progress);
        }
        if (job.enumeration_complete === false) card.appendChild(element("p", "small text-body-secondary", "Enumerating stored documents and reachable revisions; the final total is not known yet."));
        const controls = element("div", "d-flex flex-wrap gap-2 mt-2");
        const message = element("div", "alert d-none");
        async function update(action) {
            const actionLabels = { cancel: "Cancel", resume: "Resume", retry: "Retry" };
            const confirmed = await confirmAction(
                `${actionLabels[action]} scan job?`,
                action === "cancel" ? "Already-held documents stay held. Queued documents not yet started keep their previous availability." : "Resume this durable job from its saved progress. Existing holds remain until a complete scan and any required review.",
                `${actionLabels[action]} job`
            );
            if (!confirmed) return;
            controls.querySelectorAll("button").forEach(control => { control.disabled = true; });
            try {
                await window.ContentScreening.api.updateJob(scope, job, action);
                const current = await window.ContentScreening.api.getJob(scope, job.id);
                const next = renderJob(current, scope, null, onRefresh);
                card.replaceWith(next);
                onRefresh?.();
            } catch (error) {
                showMessage(message, errorMessage(error));
            }
        }
        if (hasAction(job.allowed_actions, "cancel")) {
            const cancel = button("Cancel scan", "btn btn-sm btn-outline-danger", () => update("cancel"));
            cancel.disabled = job.cancel_requested === true;
            controls.appendChild(cancel);
        }
        if (hasAction(job.allowed_actions, "resume")) controls.appendChild(button("Resume scan", "btn btn-sm btn-outline-primary", () => update("resume")));
        if (hasAction(job.allowed_actions, "retry")) controls.appendChild(button("Retry scan", "btn btn-sm btn-outline-primary", () => update("retry")));
        controls.appendChild(button("Refresh progress", "btn btn-sm btn-outline-secondary", async () => {
            try {
                const current = await window.ContentScreening.api.getJob(scope, job.id);
                card.replaceWith(renderJob(current, scope, null, onRefresh));
                onRefresh?.();
            } catch (error) { showMessage(message, errorMessage(error)); }
        }));
        card.append(controls, message);
        if (container) container.appendChild(card);
        return card;
    }

    async function startScan(scope, documentIds = null, workspace = null, output = null) {
        const message = workspace?.root.querySelector("[data-screening-workspace-message]") || output;
        if (Array.isArray(documentIds) && !documentIds.length) {
            showMessage(message, "Select at least one document for scanning.", "warning");
            return;
        }
        const label = scope.scopeType === "global" ? "all workspaces and reachable revisions"
            : documentIds ? `${documentIds.length} selected document${documentIds.length === 1 ? "" : "s"}` : "this workspace and reachable revisions";
        if (!await confirmAction("Start content scan?", `Scan ${label}? Documents stay available while queued and become held when their scan starts. Model checks may add usage. No cost estimate is available.`, "Start scan")) return;
        try {
            const job = await window.ContentScreening.api.startScan(scope, documentIds);
            clearMessage(message);
            const target = workspace?.root.querySelector("[data-screening-workspace-jobs]") || output;
            if (target) {
                target.replaceChildren();
                renderJob(job, scope, target, workspace?.refresh);
                pollJob(job, scope, target, workspace?.refresh);
            }
            workspace?.refresh?.();
        } catch (error) {
            showMessage(message, errorMessage(error));
        }
    }

    function pollJob(job, scope, container, refresh = null) {
        if (!["queued", "running", "scanning", "cancelling"].includes(job.status)) return;
        window.setTimeout(async () => {
            if (!container.isConnected || document.hidden) return;
            try {
                const next = await window.ContentScreening.api.getJob(scope, job.id);
                const existing = Array.from(container.querySelectorAll("[data-screening-job-id]"))
                    .find(node => node.dataset.screeningJobId === String(job.id));
                if (!existing) return;
                existing.replaceWith(renderJob(next, scope, null, refresh));
                refresh?.();
                pollJob(next, scope, container, refresh);
            } catch {
                const notice = element("div", "alert alert-warning", "Automatic progress refresh paused. Refresh progress to check the durable job; existing holds remain.");
                container.appendChild(notice);
            }
        }, 4000);
    }

    async function mountScanJobs(controls, list, moreButton, scope) {
        const marker = newRequestId();
        controls.dataset.screeningLoad = marker;
        controls.replaceChildren();
        list.replaceChildren();
        moreButton.classList.add("d-none");
        let cursor = "";
        async function load(nextCursor = "") {
            try {
                const response = await window.ContentScreening.api.listJobs(scope, nextCursor);
                if (controls.dataset.screeningLoad !== marker) return;
                if (!nextCursor) list.replaceChildren();
                response.items.forEach(job => {
                    renderJob(job, scope, list);
                    pollJob(job, scope, list);
                });
                if (!response.items.length && !nextCursor) list.appendChild(element("p", "text-body-secondary", "No scan jobs in this workspace."));
                cursor = response.continuation_token || "";
                moreButton.classList.toggle("d-none", !cursor);
            } catch (error) {
                if (controls.dataset.screeningLoad === marker) showMessage(list, errorMessage(error));
            }
        }
        moreButton.onclick = () => load(cursor);
        try {
            const data = await window.ContentScreening.api.getPolicy(scope);
            if (controls.dataset.screeningLoad !== marker) return;
            if (hasAction(data.allowed_actions, "scan")) {
                const scan = button("Scan workspace", "btn btn-outline-primary", () => startScan(scope, null, null, list));
                scan.disabled = data.new_scans_enabled !== true || data.prerequisites?.ready !== true;
                controls.appendChild(scan);
            }
            controls.appendChild(button("Refresh scan jobs", "btn btn-outline-secondary ms-2", () => load()));
            await load();
        } catch (error) {
            if (controls.dataset.screeningLoad === marker) showMessage(list, errorMessage(error));
        }
    }

    window.ContentScreening = {
        ScreeningError, element, button, showMessage, clearMessage, errorMessage, request, newRequestId,
        hasAction, summaryOf, isHeld, statusBadge, scopeKey, scopeQuery, reviewUrl, formatLocator,
        codePointLength, selectedCodePointRange, renderSourceText, confirmAction, downloadAttachment,
        rememberDocument, checkUsable, createHeldDocument, decorateDocument, filterDocuments, workspaces,
        registerWorkspace, mountScanJobs, renderJob, startScan, decorateFolderTable
    };

    document.addEventListener("DOMContentLoaded", () => {
        const syncSelections = () => queueMicrotask(() => workspaces.forEach(workspace => {
            if (workspace.root.screeningWorkspace === workspace) syncWorkspaceSelection(workspace);
        }));
        document.addEventListener("change", event => {
            if (event.target.matches(".document-checkbox, .document-select-all-checkbox")) {
                syncSelections();
            }
        });
        document.addEventListener("click", event => {
            if (event.target.closest('.document-item-card, [id$="clear-selection-btn"], [id$="toggle-selection-btn"]')) syncSelections();
        }, true);
        document.addEventListener("screening:policy-loaded", event => {
            if (event.detail.scope.scopeType !== "global") return;
            const globalButton = document.getElementById("screening-scan-global");
            if (!globalButton) return;
            const data = event.detail.data;
            globalButton.classList.toggle("d-none", !hasAction(data.allowed_actions, "scan_global"));
            globalButton.disabled = data.new_scans_enabled !== true || data.prerequisites?.ready !== true;
            globalButton.onclick = () => startScan({ scopeType: "global", scopeId: "" }, null, null, document.getElementById("screening-admin-jobs"));
        });
        document.querySelectorAll("[data-screening-open-settings]").forEach(link => {
            link.addEventListener("click", event => {
                const trigger = document.querySelector('[data-bs-target="#content-safety"], a[href="#content-safety"][role="tab"]');
                if (trigger && window.bootstrap?.Tab) {
                    event.preventDefault();
                    bootstrap.Tab.getOrCreateInstance(trigger).show();
                    document.getElementById("content-screening-section")?.scrollIntoView({ block: "start" });
                }
            });
        });
    });
}());
