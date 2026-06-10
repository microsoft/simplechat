// admin_custom_pages.js
import { showToast } from "../chat/chat-toast.js";

let customPages = Array.isArray(window.customPages) ? window.customPages : [];

const enableCustomPagesToggle = document.getElementById("enable_custom_pages");
const customPagesSettings = document.getElementById("custom_pages_settings");
const customPagesTbody = document.getElementById("custom-pages-tbody");
const customPageModalElement = document.getElementById("customPageDesignerModal");
const customPageForm = document.getElementById("custom-page-designer-form");
const addCustomPageButton = document.getElementById("add-custom-page-btn");
const createRequestAccessPageButton = document.getElementById("create-request-access-page-btn");
const customPageModalTitle = document.getElementById("customPageDesignerModalLabel");
const customPageSaveButton = document.querySelector("[form='custom-page-designer-form'][type='submit']");
const restartAcknowledgementField = document.getElementById("custom_pages_restart_acknowledged");
const restartModalElement = document.getElementById("customPagesRestartModal");
const restartAcknowledgeButton = document.getElementById("custom-pages-restart-acknowledge-btn");
const restartCancelButton = document.getElementById("custom-pages-restart-cancel-btn");
const guideButton = document.getElementById("custom-pages-guide-btn");
const guideModalElement = document.getElementById("customPagesGuideModal");
const guideStatus = document.getElementById("custom-pages-guide-status");
const guideContent = document.getElementById("custom-pages-guide-content");
const requestAccessCreatedModalElement = document.getElementById("requestAccessPageCreatedModal");
const customPageSlugField = document.getElementById("custom_page_slug");
const customPageSlugFeedback = document.getElementById("custom-page-slug-feedback");

let customPageModal = null;
let restartModal = null;
let guideModal = null;
let requestAccessCreatedModal = null;
let guideMarkdownLoaded = false;
const fileListFields = ["css_files", "js_files", "asset_files", "json_files"];
const fileListControls = {
    css_files: {
        inputId: "custom_page_css_file_entry",
        addButtonId: "custom_page_css_file_add",
        hiddenId: "custom_page_css_files",
        listId: "custom_page_css_files_list"
    },
    js_files: {
        inputId: "custom_page_js_file_entry",
        addButtonId: "custom_page_js_file_add",
        hiddenId: "custom_page_js_files",
        listId: "custom_page_js_files_list"
    },
    asset_files: {
        inputId: "custom_page_asset_file_entry",
        addButtonId: "custom_page_asset_file_add",
        hiddenId: "custom_page_asset_files",
        listId: "custom_page_asset_files_list"
    },
    json_files: {
        inputId: "custom_page_json_file_entry",
        addButtonId: "custom_page_json_file_add",
        hiddenId: "custom_page_json_files",
        listId: "custom_page_json_files_list"
    }
};
const customPageFileLists = {
    css_files: [],
    js_files: [],
    asset_files: [],
    json_files: []
};

document.addEventListener("DOMContentLoaded", () => {
    if (!customPagesTbody) {
        return;
    }

    if (customPageModalElement && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        customPageModal = bootstrap.Modal.getOrCreateInstance(customPageModalElement);
    }
    if (restartModalElement && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        restartModal = bootstrap.Modal.getOrCreateInstance(restartModalElement);
    }
    if (guideModalElement && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        guideModal = bootstrap.Modal.getOrCreateInstance(guideModalElement);
    }
    if (requestAccessCreatedModalElement && typeof bootstrap !== "undefined" && bootstrap.Modal) {
        requestAccessCreatedModal = bootstrap.Modal.getOrCreateInstance(requestAccessCreatedModalElement);
    }

    setupCustomPagesToggle();
    setupCustomPagesGuide();
    setupCustomPageFileListEditors();
    setupCustomPageSlugValidation();
    renderCustomPagesTable();
    refreshCustomPages();

    if (addCustomPageButton) {
        addCustomPageButton.addEventListener("click", () => openCustomPageDesigner());
    }

    if (createRequestAccessPageButton) {
        createRequestAccessPageButton.addEventListener("click", createRequestAccessPage);
    }

    if (customPageForm) {
        customPageForm.addEventListener("submit", saveCustomPageFromDesigner);
    }
});

function setupCustomPagesToggle() {
    if (!enableCustomPagesToggle || !customPagesSettings) {
        return;
    }

    const initiallyEnabled = window.customPagesInitiallyEnabled === true;

    function syncCustomPagesVisibility() {
        customPagesSettings.classList.toggle("d-none", !enableCustomPagesToggle.checked);
    }

    enableCustomPagesToggle.addEventListener("change", () => {
        if (restartAcknowledgementField && !enableCustomPagesToggle.checked) {
            restartAcknowledgementField.value = "";
        }

        syncCustomPagesVisibility();

        if (enableCustomPagesToggle.checked && !initiallyEnabled && restartModal) {
            restartModal.show();
        }
    });

    if (restartAcknowledgeButton) {
        restartAcknowledgeButton.addEventListener("click", () => {
            if (restartAcknowledgementField) {
                restartAcknowledgementField.value = "on";
            }
            if (restartModal) {
                restartModal.hide();
            }
        });
    }

    if (restartCancelButton) {
        restartCancelButton.addEventListener("click", () => {
            enableCustomPagesToggle.checked = false;
            if (restartAcknowledgementField) {
                restartAcknowledgementField.value = "";
            }
            syncCustomPagesVisibility();
            if (restartModal) {
                restartModal.hide();
            }
        });
    }

    syncCustomPagesVisibility();
}

async function refreshCustomPages() {
    try {
        const response = await fetch("/api/admin/custom-pages");
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Failed to load custom pages.");
        }
        customPages = Array.isArray(payload.pages) ? payload.pages : [];
        renderCustomPagesTable();
        syncRequestAccessPageButtonState();
    } catch (error) {
        showToast(`Custom pages could not be loaded: ${error.message}`, "warning");
    }
}

function renderCustomPagesTable() {
    if (!customPagesTbody) {
        return;
    }

    customPagesTbody.textContent = "";

    if (!customPages.length) {
        const row = document.createElement("tr");
        const cell = document.createElement("td");
        cell.colSpan = 8;
        cell.className = "text-muted text-center";
        cell.textContent = "No custom pages are registered.";
        row.appendChild(cell);
        customPagesTbody.appendChild(row);
        return;
    }

    customPages.forEach(page => {
        const row = document.createElement("tr");
        appendTextCell(row, page.slug || "");
        appendTextCell(row, page.title || "");
        appendTextCell(row, page.entry_type || "static");
        appendTextCell(row, page.access_level === "authenticated" ? "Any signed-in user" : "App users only");
        appendTextCell(row, Array.isArray(page.roles) && page.roles.length ? page.roles.join(", ") : "Any eligible user");
        appendTextCell(row, page.enabled ? "Enabled" : "Disabled");
        appendTextCell(row, page.show_in_nav ? "Shown" : "Hidden");

        const actionCell = document.createElement("td");
        const isPythonPage = page.source === "python";

        const editButton = document.createElement("button");
        editButton.type = "button";
        editButton.className = "btn btn-sm btn-outline-primary me-1";
        editButton.textContent = isPythonPage ? "View" : "Edit";
        editButton.addEventListener("click", () => openCustomPageDesigner(page, isPythonPage));
        actionCell.appendChild(editButton);

        if (!isPythonPage) {
            const deleteButton = document.createElement("button");
            deleteButton.type = "button";
            deleteButton.className = "btn btn-sm btn-outline-danger";
            deleteButton.textContent = "Delete";
            deleteButton.addEventListener("click", () => deleteCustomPage(page.slug));
            actionCell.appendChild(deleteButton);
        }

        row.appendChild(actionCell);
        customPagesTbody.appendChild(row);
    });
    syncRequestAccessPageButtonState();
}

function requestAccessPageExists() {
    return customPages.some(page => (page.slug || "").toLowerCase() === "request-access");
}

function syncRequestAccessPageButtonState() {
    if (!createRequestAccessPageButton) {
        return;
    }

    const exists = requestAccessPageExists();
    createRequestAccessPageButton.disabled = exists;
    createRequestAccessPageButton.title = exists
        ? "The request-access custom page already exists."
        : "Create the optional Request Access page metadata.";
}

function setupCustomPageSlugValidation() {
    if (!customPageSlugField) {
        return;
    }

    customPageSlugField.addEventListener("blur", validateCustomPageSlugUniqueness);
    customPageSlugField.addEventListener("input", () => {
        customPageSlugField.classList.remove("is-invalid");
        if (customPageSlugFeedback) {
            customPageSlugFeedback.textContent = "A custom page with this slug already exists.";
        }
    });
}

function getNormalizedSlugValue() {
    return (customPageSlugField?.value || "").trim().toLowerCase();
}

function customPageSlugExists(slug) {
    if (!slug) {
        return false;
    }

    const originalSlug = customPageForm?.dataset.originalSlug || "";
    return customPages.some(page => {
        const pageSlug = (page.slug || "").toLowerCase();
        return pageSlug === slug && pageSlug !== originalSlug;
    });
}

function validateCustomPageSlugUniqueness() {
    if (!customPageSlugField) {
        return true;
    }

    const slug = getNormalizedSlugValue();
    const isDuplicate = customPageSlugExists(slug);
    customPageSlugField.classList.toggle("is-invalid", isDuplicate);
    if (isDuplicate && customPageSlugFeedback) {
        customPageSlugFeedback.textContent = `A custom page with slug "${slug}" already exists.`;
    }
    return !isDuplicate;
}

function appendTextCell(row, value) {
    const cell = document.createElement("td");
    cell.textContent = value;
    row.appendChild(cell);
}

function setupCustomPageFileListEditors() {
    fileListFields.forEach(fieldName => {
        const controls = fileListControls[fieldName];
        const addButton = document.getElementById(controls.addButtonId);
        const input = document.getElementById(controls.inputId);

        if (addButton) {
            addButton.addEventListener("click", () => addCustomPageFile(fieldName));
        }

        if (input) {
            input.addEventListener("keydown", event => {
                if (event.key === "Enter") {
                    event.preventDefault();
                    addCustomPageFile(fieldName);
                }
            });
        }

        setFileListValues(fieldName, []);
    });
}

function addCustomPageFile(fieldName) {
    const controls = fileListControls[fieldName];
    const input = controls ? document.getElementById(controls.inputId) : null;
    if (!input) {
        return;
    }

    const fileName = input.value.trim();
    if (!fileName) {
        return;
    }

    const currentFiles = customPageFileLists[fieldName] || [];
    if (!currentFiles.includes(fileName)) {
        currentFiles.push(fileName);
        setFileListValues(fieldName, currentFiles);
    }

    input.value = "";
    input.focus();
}

function removeCustomPageFile(fieldName, fileName) {
    const currentFiles = customPageFileLists[fieldName] || [];
    setFileListValues(fieldName, currentFiles.filter(currentFileName => currentFileName !== fileName));
}

function setFileListValues(fieldName, values) {
    customPageFileLists[fieldName] = normalizeFileList(values);
    syncFileListHiddenField(fieldName);
    renderCustomPageFileList(fieldName);
}

function normalizeFileList(values) {
    if (!Array.isArray(values)) {
        return [];
    }

    const seen = new Set();
    const normalizedValues = [];
    values.forEach(value => {
        const fileName = String(value || "").trim();
        if (fileName && !seen.has(fileName)) {
            seen.add(fileName);
            normalizedValues.push(fileName);
        }
    });
    return normalizedValues;
}

function syncFileListHiddenField(fieldName) {
    const controls = fileListControls[fieldName];
    const hiddenField = controls ? document.getElementById(controls.hiddenId) : null;
    if (hiddenField) {
        hiddenField.value = (customPageFileLists[fieldName] || []).join(", ");
    }
}

function renderCustomPageFileList(fieldName) {
    const controls = fileListControls[fieldName];
    const listElement = controls ? document.getElementById(controls.listId) : null;
    if (!listElement) {
        return;
    }

    listElement.textContent = "";
    const files = customPageFileLists[fieldName] || [];

    if (!files.length) {
        const emptyItem = document.createElement("li");
        emptyItem.className = "list-group-item text-muted small";
        emptyItem.textContent = "No files added.";
        listElement.appendChild(emptyItem);
        return;
    }

    files.forEach(fileName => {
        const item = document.createElement("li");
        item.className = "list-group-item d-flex align-items-center justify-content-between gap-2";

        const label = document.createElement("span");
        label.className = "text-break";
        label.textContent = fileName;
        item.appendChild(label);

        const removeButton = document.createElement("button");
        removeButton.type = "button";
        removeButton.className = "btn btn-sm btn-outline-danger";
        removeButton.textContent = "Remove";
        removeButton.addEventListener("click", () => removeCustomPageFile(fieldName, fileName));
        item.appendChild(removeButton);

        listElement.appendChild(item);
    });
}

function openCustomPageDesigner(page = null, readOnly = false) {
    if (!customPageForm || !customPageModal) {
        return;
    }

    customPageForm.reset();
    customPageForm.dataset.mode = page ? "edit" : "create";
    customPageForm.dataset.originalSlug = page?.slug || "";
    if (customPageSlugField) {
        customPageSlugField.classList.remove("is-invalid");
    }

    if (customPageModalTitle) {
        customPageModalTitle.textContent = readOnly ? "View Custom Page" : (page ? "Edit Custom Page" : "New Custom Page");
    }

    setFieldValue("custom_page_slug", page?.slug || "");
    setFieldValue("custom_page_title", page?.title || "");
    setFieldValue("custom_page_description", page?.description || "");
    setFieldValue("custom_page_nav_label", page?.nav_label || page?.title || "");
    setFieldValue("custom_page_nav_icon", page?.nav_icon || "bi-file-earmark-text");
    setFieldValue("custom_page_nav_order", page?.nav_order ?? 100);
    setFieldValue("custom_page_roles", Array.isArray(page?.roles) ? page.roles.join(", ") : "");
    setFieldValue("custom_page_html_file", page?.html_file || "");
    setFieldValue("custom_page_access_level", page?.access_level || "app_user");
    setFileListValues("css_files", Array.isArray(page?.css_files) ? page.css_files : []);
    setFileListValues("js_files", Array.isArray(page?.js_files) ? page.js_files : []);
    setFileListValues("asset_files", Array.isArray(page?.asset_files) ? page.asset_files : []);
    setFileListValues("json_files", Array.isArray(page?.json_files) ? page.json_files : []);
    setCheckedValue("custom_page_enabled", page?.enabled !== false);
    setCheckedValue("custom_page_show_in_nav", page?.show_in_nav !== false);
    setCheckedValue("custom_page_open_in_new_tab", page?.open_in_new_tab === true);

    customPageForm.querySelectorAll("input, textarea, button").forEach(element => {
        element.disabled = readOnly;
    });
    if (customPageSaveButton) {
        customPageSaveButton.disabled = readOnly;
    }

    customPageModal.show();
}

function setFieldValue(id, value) {
    const field = document.getElementById(id);
    if (field) {
        field.value = value;
    }
}

function setCheckedValue(id, value) {
    const field = document.getElementById(id);
    if (field) {
        field.checked = Boolean(value);
    }
}

async function saveCustomPageFromDesigner(event) {
    event.preventDefault();
    if (!validateCustomPageSlugUniqueness()) {
        showToast("Choose a unique slug before saving this custom page.", "warning");
        return;
    }

    const originalSlug = customPageForm.dataset.originalSlug || "";
    const payload = readCustomPageDesignerPayload();
    const mode = customPageForm.dataset.mode || "create";
    const url = mode === "edit" && originalSlug
        ? `/api/admin/custom-pages/${encodeURIComponent(originalSlug)}`
        : "/api/admin/custom-pages";
    const method = mode === "edit" && originalSlug ? "PUT" : "POST";

    try {
        const response = await fetch(url, {
            method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload)
        });
        const result = response.status === 204 ? {} : await response.json();
        if (!response.ok) {
            throw new Error(result.error || "Failed to save custom page.");
        }
        showToast("Custom page saved.", "success");
        customPageModal.hide();
        await refreshCustomPages();
    } catch (error) {
        showToast(error.message, "danger");
    }
}

function readCustomPageDesignerPayload() {
    return {
        slug: getFieldValue("custom_page_slug").trim().toLowerCase(),
        title: getFieldValue("custom_page_title").trim(),
        description: getFieldValue("custom_page_description").trim(),
        nav_label: getFieldValue("custom_page_nav_label").trim(),
        nav_icon: getFieldValue("custom_page_nav_icon").trim() || "bi-file-earmark-text",
        nav_order: Number.parseInt(getFieldValue("custom_page_nav_order"), 10) || 100,
        roles: splitCsv(getFieldValue("custom_page_roles")),
        access_level: getFieldValue("custom_page_access_level") || "app_user",
        html_file: getFieldValue("custom_page_html_file").trim(),
        css_files: customPageFileLists.css_files,
        js_files: customPageFileLists.js_files,
        asset_files: customPageFileLists.asset_files,
        json_files: customPageFileLists.json_files,
        enabled: Boolean(document.getElementById("custom_page_enabled")?.checked),
        show_in_nav: Boolean(document.getElementById("custom_page_show_in_nav")?.checked),
        open_in_new_tab: Boolean(document.getElementById("custom_page_open_in_new_tab")?.checked),
        entry_type: "static"
    };
}

function getFieldValue(id) {
    return document.getElementById(id)?.value || "";
}

function splitCsv(value) {
    return String(value || "")
        .split(",")
        .map(item => item.trim())
        .filter(Boolean);
}

async function deleteCustomPage(slug) {
    if (!slug) {
        return;
    }

    try {
        const response = await fetch(`/api/admin/custom-pages/${encodeURIComponent(slug)}`, {
            method: "DELETE"
        });
        if (!response.ok) {
            const payload = await response.json();
            throw new Error(payload.error || "Failed to delete custom page.");
        }
        showToast("Custom page deleted.", "success");
        await refreshCustomPages();
    } catch (error) {
        showToast(error.message, "danger");
    }
}

function setupCustomPagesGuide() {
    if (!guideButton || !guideModal) {
        return;
    }

    guideButton.addEventListener("click", async () => {
        guideModal.show();
        if (!guideMarkdownLoaded) {
            await loadCustomPagesGuide();
        }
    });
}

async function loadCustomPagesGuide() {
    if (guideStatus) {
        guideStatus.classList.remove("d-none");
        guideStatus.textContent = "Loading guide...";
    }
    if (guideContent) {
        guideContent.classList.add("d-none");
        guideContent.textContent = "";
    }

    try {
        const response = await fetch("/api/admin/custom-pages/developer-guide", { credentials: "same-origin" });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Developer guide could not be loaded.");
        }

        const markdown = payload.markdown || "";
        if (guideContent && typeof marked !== "undefined" && typeof DOMPurify !== "undefined") {
            guideContent.innerHTML = DOMPurify.sanitize(marked.parse(markdown));
            guideContent.classList.remove("d-none");
            guideMarkdownLoaded = true;
            if (guideStatus) {
                guideStatus.classList.add("d-none");
            }
            return;
        }

        if (guideContent) {
            guideContent.textContent = markdown;
            guideContent.classList.remove("d-none");
            guideMarkdownLoaded = true;
        }
        if (guideStatus) {
            guideStatus.classList.add("d-none");
        }
    } catch (error) {
        if (guideStatus) {
            guideStatus.textContent = error.message;
        }
    }
}

async function createRequestAccessPage() {
    if (!createRequestAccessPageButton) {
        return;
    }

    createRequestAccessPageButton.disabled = true;
    try {
        const response = await fetch("/api/admin/custom-pages/request-access-example", {
            method: "POST",
            headers: { "Content-Type": "application/json" }
        });
        const payload = await response.json();
        if (!response.ok) {
            throw new Error(payload.error || "Failed to create Request Access page.");
        }
        showToast("Request Access page created and access-denied button enabled.", "success");
        await refreshCustomPages();
        if (requestAccessCreatedModal) {
            requestAccessCreatedModal.show();
        }
    } catch (error) {
        showToast(error.message, "danger");
    } finally {
        syncRequestAccessPageButtonState();
    }
}