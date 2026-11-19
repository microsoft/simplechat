// model_ca_bundle_manager.js

import { showToast } from "../chat/chat-toast.js";
import { CABundleRequestError, requestCertificateApi } from "../model_ca_bundles.js";

function element(tag, className, text) {
    const node = document.createElement(tag);
    node.className = className;
    if (text !== undefined) {
        node.textContent = text;
    }
    return node;
}

export function initializeCABundleManager() {
    const panel = document.getElementById("model-ca-bundle-manager");
    if (!panel || panel.dataset.initialized === "true") {
        return;
    }
    panel.dataset.initialized = "true";
    const name = document.getElementById("model-ca-bundle-name");
    const file = document.getElementById("model-ca-bundle-file");
    const save = document.getElementById("model-ca-bundle-save");
    const cancel = document.getElementById("model-ca-bundle-cancel");
    const refresh = document.getElementById("model-ca-bundle-refresh");
    const status = document.getElementById("model-ca-bundle-status");
    const list = document.getElementById("model-ca-bundle-list");
    const deleteElement = document.getElementById("modelCaBundleDeleteModal");
    const deleteModal = bootstrap.Modal.getOrCreateInstance(deleteElement);
    const confirmDelete = document.getElementById("model-ca-bundle-delete-confirm");
    let editing = null;
    let deleting = null;
    let busy = false;

    function report(message, danger = false) {
        status.textContent = message;
        status.className = danger ? "alert alert-danger mt-2" : "small text-muted mt-2";
    }

    function setBusy(value) {
        busy = value;
        for (const control of [save, cancel, refresh, name, file, confirmDelete]) {
            control.disabled = value;
        }
        for (const button of list.querySelectorAll("button")) {
            button.disabled = value || button.dataset.unavailable === "true";
        }
    }

    function reset() {
        editing = null;
        name.value = "";
        file.value = "";
        save.textContent = "Upload CA bundle";
        cancel.classList.add("d-none");
    }

    function details(bundle) {
        const section = element("details", "mt-2");
        section.append(element("summary", "", "Certificates, references, and audit history"));
        const certificates = element("ul", "small text-break mb-2");
        for (const certificate of bundle.certificates || []) {
            certificates.append(element(
                "li", "", `${certificate.subject}; SHA-256 ${certificate.sha256}; valid ${certificate.valid_from}; expires ${certificate.expires_at}`
            ));
        }
        section.append(certificates);
        for (const reference of bundle.references || []) {
            section.append(element("div", "small text-break", `${reference.scope}: ${reference.endpoint_name} (${reference.endpoint_id})`));
        }
        for (const event of bundle.audit_history || []) {
            section.append(element("div", "small text-muted text-break", `${event.timestamp}: ${event.action}, revision ${event.revision}`));
        }
        return section;
    }

    function render(bundles) {
        list.replaceChildren();
        if (!bundles.length) {
            list.append(element("p", "text-muted mb-0", "No CA bundles uploaded. Existing application trust is unchanged."));
            return;
        }
        for (const bundle of bundles) {
            const card = element("div", "border rounded p-3 mb-2");
            card.dataset.caBundleId = bundle.id;
            const title = element("h6", "text-break mb-1", bundle.name);
            const expired = Date.parse(bundle.expires_at) < Date.now();
            card.append(title, element(
                "div", expired ? "small text-danger" : "small text-muted",
                `Revision ${bundle.revision}; expires ${bundle.expires_at}${expired ? " (expired)" : ""}`
            ));
            const referenceCount = (bundle.references || []).length;
            card.append(element("div", "small", `${referenceCount} endpoint reference(s); ${bundle.pending_save_count || 0} save reservation(s).`));
            if (bundle.state === "deleting") {
                card.append(element("div", "alert alert-warning mt-2", "Deletion is incomplete. Retry deletion to finish cleaning up certificate storage."));
            }
            const actions = element("div", "d-flex flex-wrap gap-2 mt-2");
            const edit = element("button", "btn btn-sm btn-outline-primary", "Edit / replace");
            edit.type = "button";
            edit.disabled = bundle.state === "deleting";
            edit.dataset.unavailable = String(edit.disabled);
            edit.addEventListener("click", () => {
                if (busy) {
                    return;
                }
                editing = bundle;
                name.value = bundle.name;
                file.value = "";
                save.textContent = "Save bundle changes";
                cancel.classList.remove("d-none");
                report("Choose a new PEM file to replace certificates, or leave it empty to rename. Existing endpoints keep the stable bundle ID.");
                name.focus();
            });
            const remove = element("button", "btn btn-sm btn-outline-danger", bundle.state === "deleting" ? "Retry deletion" : "Delete unused bundle");
            remove.type = "button";
            remove.disabled = referenceCount > 0;
            remove.dataset.unavailable = String(remove.disabled);
            remove.addEventListener("click", () => {
                if (busy) {
                    return;
                }
                deleting = bundle;
                document.getElementById("model-ca-bundle-delete-name").textContent = bundle.name;
                deleteModal.show();
            });
            actions.append(edit, remove);
            card.append(actions, details(bundle));
            list.append(card);
        }
    }

    async function load() {
        const data = await requestCertificateApi("/api/model-ca-bundles");
        if (!Array.isArray(data.bundles)) {
            throw new CABundleRequestError("The certificate manager returned an invalid bundle inventory.");
        }
        render(data.bundles);
        panel.dataset.loaded = "true";
    }

    async function perform(operation) {
        if (busy) {
            return;
        }
        setBusy(true);
        try {
            await operation();
        } catch (error) {
            report(error instanceof CABundleRequestError ? error.message : "The certificate operation failed. Refresh and verify the current state.", true);
        } finally {
            setBusy(false);
        }
    }

    save.addEventListener("click", () => perform(async () => {
        const certificate = file.files[0];
        if (!name.value.trim() || (!editing && !certificate)) {
            throw new CABundleRequestError("Enter a friendly name and choose a PEM CA certificate file.");
        }
        if (certificate && certificate.size > 1024 * 1024) {
            throw new CABundleRequestError("Certificate bundles must not exceed 1 MiB.");
        }
        const body = new FormData();
        body.append("name", name.value.trim());
        if (certificate) {
            body.append("file", certificate);
        }
        if (editing) {
            body.append("expected_revision", String(editing.revision));
        }
        await requestCertificateApi(
            editing ? `/api/model-ca-bundles/${encodeURIComponent(editing.id)}` : "/api/model-ca-bundles",
            { method: editing ? "PUT" : "POST", body }
        );
        reset();
        await load();
        report("CA bundle saved. New model requests resolve the current certificate revision.");
        showToast("CA bundle saved.", "success");
    }));
    confirmDelete.addEventListener("click", () => perform(async () => {
        if (!deleting) {
            throw new CABundleRequestError("Select the unused bundle to delete.");
        }
        await requestCertificateApi(`/api/model-ca-bundles/${encodeURIComponent(deleting.id)}`, {
            method: "DELETE", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ expected_revision: deleting.revision })
        });
        deleting = null;
        deleteModal.hide();
        await load();
        report("Unused CA bundle deleted.");
    }));
    refresh.addEventListener("click", () => perform(async () => {
        await load();
        report("Certificate inventory refreshed.");
    }));
    cancel.addEventListener("click", reset);
    name.addEventListener("keydown", (event) => {
        if (event.key === "Enter") {
            event.preventDefault();
            save.click();
        }
    });
    panel.addEventListener("toggle", () => {
        if (panel.open && panel.dataset.loaded !== "true") {
            perform(load);
        }
    });
}
