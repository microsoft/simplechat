// model_catalog_ui.js
// Shared, locally bundled catalog controls for classic and React V2.

const profileFields = ["displayName", "publisher", "summary", "strengths", "limitations", "aliases", "tasks", "capabilities", "sources", "archived"];
const capabilityNames = ["processesText", "generatesText", "processesImages", "generatesImages", "processesAudio", "generatesAudio", "processesVideo", "generatesVideo", "processesBinaryFiles", "optimizedForCoding", "toolCalling", "structuredOutput", "supportsStreaming", "reasoning"];

export async function catalogRequest(path, { method = "GET", body, signal } = {}) {
    const response = await fetch(path, {
        method, signal, credentials: "same-origin",
        headers: { Accept: "application/json", ...(body ? { "Content-Type": "application/json" } : {}) },
        ...(body ? { body: JSON.stringify(body) } : {})
    });
    if (!response.headers.get("content-type")?.includes("application/json")) {
        throw new Error("The catalog could not be loaded. Check your session and retry.");
    }
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "The catalog request failed.");
    return result;
}

function node(tag, text, className) {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
}

function button(label, callback) {
    const element = node("button", label, "sc-catalog-button");
    element.type = "button";
    element.addEventListener("click", callback);
    return element;
}

function select(label, choices, value, onChange) {
    const wrapper = node("label", label, "sc-catalog-field");
    const input = node("select");
    input.setAttribute("aria-label", label);
    choices.forEach(([key, text]) => input.appendChild(new Option(text, key)));
    input.value = value;
    input.addEventListener("change", () => onChange(input.value));
    wrapper.appendChild(input);
    return wrapper;
}

function input(label, value, onChange, multiline = false) {
    const wrapper = node("label", label, "sc-catalog-field");
    const control = node(multiline ? "textarea" : "input");
    if (!multiline) control.type = "text";
    control.value = value || "";
    control.maxLength = multiline ? 6000 : 160;
    if (multiline) control.rows = 3;
    control.addEventListener("input", () => onChange(control.value));
    wrapper.appendChild(control);
    return wrapper;
}

function notice(message) {
    const element = node("p", message, "alert alert-danger sc-catalog-error");
    element.setAttribute("role", "alert");
    return element;
}

function draftOf(profile) {
    const draft = Object.fromEntries(profileFields.filter((key) => key in profile)
        .map((key) => [key, structuredClone(profile[key])]));
    draft.capabilities = Object.fromEntries(Object.entries(draft.capabilities || {})
        .filter(([key]) => capabilityNames.includes(key)));
    return draft;
}

export function mountModelCatalog(root, { request = catalogRequest, onSaved = () => {} } = {}) {
    const controller = new AbortController();
    let data = { profiles: [], tasks: {}, etag: "" };
    let query = "";
    let origin = "";
    let task = "";
    let favorites = false;
    let publisher = "";
    let capability = "";
    let availability = "";
    let lifecycle = "active";
    let selected = null;
    let editing = false;
    let draft = null;
    let dirty = false;
    let busy = false;
    let loading = false;
    let disposed = false;
    root.classList.add("sc-model-catalog");
    const status = node("div");
    status.setAttribute("aria-live", "polite");
    const toolbar = node("div", undefined, "sc-catalog-toolbar");
    const list = node("div", undefined, "sc-catalog-list");
    const detail = node("div", undefined, "sc-catalog-detail");
    const columns = node("div", undefined, "sc-catalog-columns");
    columns.append(list, detail);
    root.replaceChildren(toolbar, status, columns);

    function confirmDiscard(action) {
        if (busy || loading) return;
        if (!dirty) return action();
        status.replaceChildren(notice("This profile has unsaved changes."));
        status.append(button("Discard changes", () => { dirty = false; status.replaceChildren(); action(); }));
    }

    async function load() {
        if (loading || busy) return;
        loading = true;
        setDisabled(true);
        status.replaceChildren(node("p", "Loading model catalog..."));
        try {
            const result = await request("/api/admin/model-catalog", { signal: controller.signal });
            if (disposed) return;
            data = result;
            status.replaceChildren();
            renderToolbar();
            renderList();
        } catch (error) {
            if (!disposed) status.replaceChildren(notice(error.message));
        } finally {
            loading = false;
            if (!disposed) setDisabled(false);
        }
    }

    function setDisabled(disabled) {
        root.querySelectorAll("button, input, select, textarea").forEach((element) => { element.disabled = disabled; });
        root.setAttribute("aria-busy", String(disabled));
    }

    async function save(payload, id) {
        if (busy || loading) return;
        busy = true;
        setDisabled(true);
        status.replaceChildren(node("p", "Saving..."));
        try {
            const result = await request(`/api/admin/model-catalog${id ? `/${encodeURIComponent(id)}` : ""}`, {
                method: id ? "PATCH" : "POST", body: { ...payload, etag: data.etag },
                signal: controller.signal
            });
            if (disposed) return;
            data = result;
            dirty = false;
            editing = false;
            selected = data.profiles.find((profile) => profile.id === id) || null;
            status.replaceChildren(node("p", "Catalog saved.", "alert alert-success"));
            renderToolbar();
            renderList();
            renderDetail();
            onSaved();
            window.dispatchEvent(new CustomEvent("model-catalog-changed"));
        } catch (error) {
            if (!disposed) status.replaceChildren(notice(error.message));
        } finally {
            busy = false;
            if (!disposed) setDisabled(false);
        }
    }

    function renderToolbar() {
        toolbar.replaceChildren(
            input("Search profiles", query, (value) => { query = value; renderList(); }),
            select("Origin", [["", "All profiles"], ["built_in", "Built-in"], ["custom", "Custom"]], origin, (value) => { origin = value; renderList(); }),
            select("Task strength", [["", "All tasks"], ...Object.entries(data.tasks)], task, (value) => { task = value; renderList(); }),
            select("Publisher", [["", "All publishers"], ...[...new Set(data.profiles.map((profile) => profile.publisher).filter(Boolean))].sort().map((value) => [value, value])], publisher, (value) => { publisher = value; renderList(); }),
            select("Capability", [["", "All capabilities"], ...capabilityNames.map((value) => [value, value.replace(/([A-Z])/g, " $1")])], capability, (value) => { capability = value; renderList(); }),
            select("Connections", [["", "All profiles"], ["linked", "Linked globally"], ["unlinked", "Not linked globally"]], availability, (value) => { availability = value; renderList(); }),
            select("Status", [["active", "Active"], ["archived", "Archived"], ["", "All statuses"]], lifecycle, (value) => { lifecycle = value; renderList(); }),
            button(favorites ? "Show all profiles" : "Show favorites", () => { favorites = !favorites; renderToolbar(); renderList(); }),
            button("Add custom profile", () => confirmDiscard(() => {
                selected = null;
                draft = { displayName: "", publisher: "", summary: "", strengths: [], limitations: [], sources: [], aliases: [], capabilities: {}, tasks: {}, archived: false };
                editing = true;
                renderDetail();
            })),
            button("Reload catalog", () => confirmDiscard(() => { editing = false; selected = null; renderDetail(); void load(); }))
        );
    }

    function renderList() {
        const normalized = query.trim().toLocaleLowerCase();
        const rows = data.profiles.filter((profile) =>
            (!origin || profile.origin === origin) &&
            (!favorites || profile.preferences.favorite) &&
            (!publisher || profile.publisher === publisher) &&
            (!capability || profile.capabilities[capability] === true) &&
            (!availability || Boolean(profile.linked_models?.length) === (availability === "linked")) &&
            (!lifecycle || profile.archived === (lifecycle === "archived")) &&
            (!task || ["suitable", "strong"].includes(profile.tasks[task])) &&
            `${profile.displayName} ${profile.id} ${profile.publisher} ${profile.summary} ${profile.aliases.join(" ")}`.toLocaleLowerCase().includes(normalized)
        ).sort((a, b) => Number(b.preferences.favorite) - Number(a.preferences.favorite) || a.displayName.localeCompare(b.displayName));
        list.replaceChildren(node("p", `${rows.length} profiles. Profiles are not deployments.`));
        for (const profile of rows) {
            const row = node("article", undefined, "sc-catalog-row");
            const name = button(`${profile.preferences.favorite ? "Favorite - " : ""}${profile.displayName}`, () => confirmDiscard(() => {
                selected = profile;
                editing = false;
                renderList();
                renderDetail();
                detail.querySelector("h3")?.focus();
            }));
            name.setAttribute("aria-pressed", String(selected?.id === profile.id));
            row.append(name, node("p", `${profile.publisher || "Unspecified publisher"} | ${profile.origin === "custom" ? "Custom" : "Built-in"} | ${profile.preferences.priority}${profile.archived ? " | Archived" : ""}`));
            row.append(node("p", profile.summary));
            row.append(node("small", `${profile.linked_models?.length || 0} globally connected models`));
            row.append(node("small", Object.entries(profile.tasks).filter(([, value]) => value === "strong").map(([key]) => data.tasks[key]).join(" / ")));
            list.appendChild(row);
        }
        if (!rows.length) list.append(node("p", "No matching profiles. Try a different search or add a custom profile."));
    }

    function renderDetail() {
        detail.replaceChildren();
        if (editing) return renderEditor();
        if (!selected) {
            detail.append(node("p", "Select a profile to inspect its strengths, evidence, and routing preferences."));
            return;
        }
        const profile = selected;
        const heading = node("h3", profile.displayName);
        heading.tabIndex = -1;
        detail.append(heading, node("p", profile.summary));
        detail.append(node("p", `${profile.evidence.replaceAll("_", " ")}${profile.verifiedAt ? ` | Reviewed ${profile.verifiedAt}` : ""}`));
        if (profile.chatCompletions === false) detail.append(notice("This model requires a different API and is not eligible for Auto orchestration."));
        for (const [label, values] of [["Strengths", profile.strengths], ["Limitations", profile.limitations]]) {
            detail.append(node("h4", label));
            const ul = node("ul");
            values.forEach((value) => ul.append(node("li", value)));
            detail.append(ul);
            if (!values.length) detail.append(node("p", "Not documented."));
        }
        detail.append(node("h4", "Task suitability"));
        Object.entries(profile.tasks).forEach(([key, value]) => detail.append(node("p", `${data.tasks[key] || key}: ${value}`)));
        detail.append(node("h4", "Technical capabilities"));
        const technical = node("dl", undefined, "sc-catalog-specs");
        capabilityNames.forEach((key) => {
            technical.append(node("dt", key.replace(/([A-Z])/g, " $1")), node("dd",
                profile.capabilities[key] === true ? "Supported" : profile.capabilities[key] === false ? "Not supported" : "Unknown"));
        });
        for (const key of ["contextWindow", "inputTokenLimit", "outputTokenLimit", "lifecycle"]) {
            if (profile.technical && key in profile.technical) technical.append(node("dt", key), node("dd", String(profile.technical[key] ?? "Unknown")));
        }
        detail.append(technical, node("p", "Capacity and operation support remain provider-qualified. Connection overrides and access still apply."));
        for (const [key, label] of [
            ["tokenLimitEvidence", "Token capacity evidence"], ["tokenLimitProfiles", "Hosted capacity profiles"],
            ["reasoningPolicy", "Reasoning policy"], ["embeddingPolicy", "Embedding policy"],
            ["imageProfiles", "Image operation profiles"]
        ]) {
            if (!profile.technical?.[key]) continue;
            const section = node("details");
            section.append(node("summary", label), node("pre", JSON.stringify(profile.technical[key], null, 2)));
            detail.append(section);
        }
        detail.append(node("h4", "Connected global models"));
        for (const linked of profile.linked_models || []) {
            detail.append(node("p", `${linked.connection} / ${linked.model} - ${linked.enabled ? "Enabled" : "Disabled"}`));
            detail.append(node("small", `Effective support: ${Object.entries(linked.capabilities).filter(([, value]) => value).map(([key]) => key).join(", ") || "Not declared"}`));
        }
        detail.append(node("p", "Personal and group connections are managed in their own workspaces. A profile never publishes a deployment."));
        detail.append(node("h4", "Routing preferences"), node("p", "Task suitability comes first, then priority, then favorite. Preferences do not change access or chat defaults."));
        detail.append(button(profile.preferences.favorite ? "Remove favorite" : "Favorite", () =>
            void save({ preferences: { ...profile.preferences, favorite: !profile.preferences.favorite } }, profile.id)));
        detail.append(select("Priority", [["preferred", "Preferred"], ["standard", "Standard"], ["lower", "Lower"]],
            profile.preferences.priority, (priority) => void save({ preferences: { ...profile.preferences, priority } }, profile.id)));
        detail.append(node("h4", "Evidence"));
        profile.sources.forEach((source) => {
            const url = new URL(source, window.location.origin);
            if (url.protocol !== "https:") return;
            const link = node("a", source);
            link.href = url.href;
            link.target = "_blank";
            link.rel = "noopener noreferrer";
            const paragraph = node("p");
            paragraph.appendChild(link);
            detail.append(paragraph);
        });
        detail.append(button("Duplicate as custom", () => {
            draft = draftOf(profile);
            draft.displayName = `${profile.displayName} custom`;
            draft.aliases = [];
            draft.archived = false;
            selected = null;
            editing = true;
            dirty = true;
            renderDetail();
        }));
        if (profile.origin === "custom") {
            detail.append(button("Edit profile", () => { draft = draftOf(profile); editing = true; renderDetail(); }));
            detail.append(button(profile.archived ? "Unarchive profile" : "Archive profile", () =>
                void save({ profile: { ...draftOf(profile), archived: !profile.archived } }, profile.id)));
        }
    }

    function renderEditor() {
        detail.append(node("h3", selected ? "Edit custom profile" : "New custom profile"));
        detail.append(node("p", "This saves a reusable profile, not a connection. Changes affect linked models. Unknown capabilities do not qualify a model for constrained Auto steps."));
        const update = (key, value) => { draft[key] = value; dirty = true; };
        for (const [key, label] of [["displayName", "Name"], ["publisher", "Publisher"], ["summary", "What this model is good at"]]) {
            detail.append(input(label, draft[key], (value) => update(key, value), key === "summary"));
        }
        for (const [key, label] of [["strengths", "Strengths (one per line)"], ["limitations", "Limitations (one per line)"], ["aliases", "Aliases (one per line)"], ["sources", "Evidence HTTPS links (one per line)"]]) {
            detail.append(input(label, (draft[key] || []).join("\n"), (value) => update(key, value.split("\n").map((line) => line.trim()).filter(Boolean)), true));
        }
        detail.append(node("h4", "Task suitability (administrator-declared)"));
        for (const [key, label] of Object.entries(data.tasks)) {
            detail.append(select(label, [["unknown", "Unknown"], ["suitable", "Suitable"], ["strong", "Strong"], ["unsuitable", "Unsuitable"]],
                draft.tasks[key] || "unknown", (value) => { draft.tasks[key] = value; dirty = true; }));
        }
        detail.append(node("h4", "Technical capabilities (administrator-declared)"));
        for (const key of capabilityNames) {
            detail.append(select(key.replace(/([A-Z])/g, " $1"),
                [["unknown", "Unknown"], ["true", "Supported"], ["false", "Not supported"]],
                key in draft.capabilities ? String(draft.capabilities[key]) : "unknown",
                (value) => {
                    if (value === "unknown") delete draft.capabilities[key];
                    else draft.capabilities[key] = value === "true";
                    dirty = true;
                }));
        }
        detail.append(button("Save profile", () => void save({ profile: draft }, selected?.id)));
        detail.append(button("Cancel editing", () => confirmDiscard(() => { editing = false; renderDetail(); })));
    }

    const preventUnload = (event) => { if (dirty) { event.preventDefault(); event.returnValue = ""; } };
    window.addEventListener("beforeunload", preventUnload);
    renderToolbar();
    renderDetail();
    void load();
    return () => {
        disposed = true;
        controller.abort();
        window.removeEventListener("beforeunload", preventUnload);
        root.replaceChildren();
    };
}

export function mountProfilePicker(root, model, onChange, request = catalogRequest) {
    const controller = new AbortController();
    root.classList.add("sc-model-catalog");
    root.replaceChildren(node("p", "Loading catalog profiles..."));
    request("/api/models/catalog", { signal: controller.signal }).then((data) => {
        if (controller.signal.aborted) return;
        const current = model.catalogProfileId || "";
        const choices = [["", "Automatic exact match (built-in only)"], ...data.profiles.map((profile) => [profile.id, profile.displayName])];
        if (current && !choices.some(([key]) => key === current)) choices.push([current, `${current} (unavailable or archived)`]);
        const summary = node("p");
        const explain = (value) => {
            const profile = data.profiles.find((item) => item.id === value);
            summary.textContent = profile ? `${profile.summary} Connection overrides still apply.` : "Profile association does not change the deployment name or credentials.";
        };
        root.replaceChildren(select("Catalog profile", choices, current, (value) => { onChange(value); explain(value); }), summary);
        explain(current);
    }).catch((error) => {
        if (!controller.signal.aborted) root.replaceChildren(notice(error.message));
    });
    return () => controller.abort();
}
