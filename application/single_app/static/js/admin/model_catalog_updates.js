// model_catalog_updates.js
// Signed package controls; all network requests remain same-origin.

function node(tag, text, className = "") {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    element.className = className;
    return element;
}

export function mountCatalogUpdates(root, { request, onApplied, canApply = () => true }) {
    let status = null;
    let preview = null;
    let rollback = false;
    let busy = false;
    let disposed = false;
    let message = "";
    let failed = false;
    const controller = new AbortController();
    root.setAttribute("aria-label", "Catalog updates");

    async function run(operation, body = {}) {
        if (busy) return;
        busy = true;
        message = "";
        render();
        try {
            const result = await request("/api/admin/model-catalog/updates", {
                ...(operation ? { method: "POST", body: { operation, ...body } } : {}),
                signal: controller.signal,
            });
            if (disposed) return;
            if (["upload", "preview", "rollback-preview"].includes(operation)) {
                preview = result;
                rollback = operation === "rollback-preview";
            } else {
                status = result;
                preview = null;
                if (operation === "apply" || operation === "rollback") {
                    message = "Catalog revision applied. New model operations use this revision.";
                    onApplied();
                }
            }
            failed = false;
        } catch (error) {
            if (disposed) return;
            failed = true;
            message = error.message || "Unable to update the catalog. Reload and retry.";
        } finally {
            busy = false;
            if (!disposed) render();
        }
    }

    function button(text, action, disabled = false) {
        const element = node("button", text, "sc-catalog-button");
        element.type = "button";
        element.disabled = busy || disabled;
        element.addEventListener("click", action);
        return element;
    }

    function render() {
        root.replaceChildren(node("h3", "Catalog updates", "h6"));
        root.setAttribute("aria-busy", String(busy));
        if (message) {
            const notice = node("p", message, failed ? "alert alert-danger" : "alert alert-success");
            notice.setAttribute("role", failed ? "alert" : "status");
            root.append(notice);
        }
        if (!status?.installed) {
            root.append(button(busy ? "Loading update status..." : "Reload update status", () => void run()));
            return;
        }
        root.append(node("p", `Installed: ${status.installed.revision} | Published: ${status.installed.publishedAt}`));
        root.append(node("p", `Official repository: ${status.repository}`, "text-break"));
        root.append(node("p", `Discovery URL: ${status.discoveryUrl}`, "text-break"));
        root.append(node("p", "Online checks contact GitHub from the server. No chats, documents, connection settings, or credentials are sent. Packages are never installed automatically."));
        const switchRow = node("div", undefined, "form-check form-switch mb-3");
        const toggle = node("input", undefined, "form-check-input");
        toggle.type = "checkbox";
        toggle.id = "model-catalog-online-updates";
        toggle.setAttribute("role", "switch");
        toggle.checked = status.onlineEnabled;
        toggle.disabled = busy;
        toggle.addEventListener("change", () => void run("online", { enabled: toggle.checked, etag: status.etag }));
        const label = node("label", "Allow online catalog update checks", "form-check-label");
        label.htmlFor = toggle.id;
        switchRow.append(toggle, label);
        root.append(switchRow);
        if (!status.publisherConfigured) {
            root.append(node("p", "Publisher verification key is not configured. Install the trusted public key before publishing or importing packages.", "alert alert-warning"));
        }
        const controls = node("div", undefined, "sc-catalog-toolbar");
        controls.append(button("Check for updates", () => void run("check"), !status.onlineEnabled || !status.publisherConfigured));
        const uploadLabel = node("label", "Upload signed package", "sc-catalog-field");
        const file = node("input");
        file.type = "file";
        file.accept = ".json,application/json";
        file.disabled = busy || !status.publisherConfigured;
        file.addEventListener("change", async () => {
            const selected = file.files?.[0];
            if (!selected) return;
            if (selected.size > 1536000) {
                failed = true;
                message = "The catalog package exceeds its size limit.";
                render();
                return;
            }
            try {
                const text = await selected.text();
                if (!disposed) await run("upload", { package: text });
            } catch {
                failed = true;
                message = "Unable to read the selected package.";
                render();
            }
        });
        uploadLabel.append(file);
        controls.append(uploadLabel, button("Preview rollback", () => void run("rollback-preview"), !status.canRollback));
        controls.append(button("Reload update status", () => void run()));
        root.append(controls);
        if (status.check) {
            root.append(node("p", `Last check: ${status.check.status} | ${status.check.attemptedAt}`, "text-break"));
            if (status.check.downloadUrl) root.append(node("p", `Download URL: ${status.check.downloadUrl}`, "text-break"));
            if (status.check.status === "available") {
                root.append(button("Preview available update", () => void run("preview", { digest: status.check.digest })));
            }
        }
        if (preview) {
            root.append(node("h4", `Review ${rollback ? "rollback" : "update"}: ${preview.manifest.revision}`, "h6"));
            root.append(node("p", rollback && !preview.digest ? "Bundled application catalog." : "Publisher signature verified."));
            root.append(node("p", `SHA-256 package digest: ${preview.digest || "bundled"}`, "text-break"));
            root.append(node("pre", JSON.stringify({ manifest: preview.manifest, changes: preview.changes }, null, 2), "text-wrap text-break"));
            root.append(node("p", "Applying changes affects new model operations across this deployment. Existing connection overrides and custom profiles are preserved."));
            root.append(button(rollback ? "Apply rollback" : "Apply catalog update", () => {
                if (canApply()) void run(rollback ? "rollback" : "apply", { digest: preview.digest, etag: preview.etag });
            }));
            root.append(button("Cancel update preview", () => { preview = null; render(); }));
        }
    }
    void run();
    return () => { disposed = true; controller.abort(); root.replaceChildren(); };
}
