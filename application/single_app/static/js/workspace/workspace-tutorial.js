// workspace-tutorial.js

const EDGE_PADDING = 12;
const HIGHLIGHT_PADDING = 10;
const CARD_GAP = 14;

let tutorialSteps = [];
let currentStepIndex = -1;
let layerEl = null;
let highlightEl = null;
let cardEl = null;
let activeTarget = null;
let temporaryStateRestorers = [];
let originalActiveTabId = null;
let pendingStepToken = 0;
let scheduledPositionFrame = 0;
let layoutResizeObserver = null;
let layoutMutationObserver = null;
let currentStep = null;
let highlightedTargetEl = null;

const EXAMPLE_TAGS = [
    { name: "finance", color: "#0d6efd", count: 12 },
    { name: "q1-review", color: "#198754", count: 7 },
    { name: "urgent", color: "#dc3545", count: 3 },
    { name: "needs-follow-up", color: "#fd7e14", count: 5 }
];

const EXAMPLE_SHARED_USERS = [
    { name: "Adele Vance", email: "adele.vance@contoso.com" },
    { name: "Diego Siciliani", email: "diego.siciliani@contoso.com" }
];

function wait(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function isFeatureEnabled(flagName) {
    return window[flagName] === true || window[flagName] === "true";
}

function registerTemporaryStateRestorer(restorer) {
    if (typeof restorer === "function") {
        temporaryStateRestorers.push(restorer);
    }
}

function restoreTemporaryState() {
    while (temporaryStateRestorers.length) {
        const restore = temporaryStateRestorers.pop();
        try {
            restore();
        } catch (error) {
            console.warn("workspace-tutorial: failed to restore temporary state", error);
        }
    }
}

function getWorkspaceTabButton(tabButtonId) {
    return document.getElementById(tabButtonId);
}

function activateTab(tabButtonId) {
    const tabButton = getWorkspaceTabButton(tabButtonId);
    if (!tabButton) {
        return;
    }

    const activeButton = document.querySelector("#workspaceTab .nav-link.active");
    if (!originalActiveTabId && activeButton?.id) {
        originalActiveTabId = activeButton.id;
    }

    bootstrap.Tab.getOrCreateInstance(tabButton).show();
}

function restoreActiveTab() {
    if (!originalActiveTabId) {
        return;
    }

    const originalTabButton = getWorkspaceTabButton(originalActiveTabId);
    if (!originalTabButton) {
        return;
    }

    bootstrap.Tab.getOrCreateInstance(originalTabButton).show();
    originalActiveTabId = null;
}

function ensureCollapseVisible(toggleId, collapseId) {
    const toggleButton = document.getElementById(toggleId);
    const collapseEl = document.getElementById(collapseId);
    if (!collapseEl) {
        return;
    }

    if (!collapseEl.classList.contains("show")) {
        if (toggleButton) {
            toggleButton.click();
            registerTemporaryStateRestorer(() => {
                if (collapseEl.classList.contains("show")) {
                    toggleButton.click();
                }
            });
        } else {
            collapseEl.classList.add("show");
            registerTemporaryStateRestorer(() => {
                collapseEl.classList.remove("show");
            });
        }
    }
}

async function ensurePluginsReady() {
    activateTab("plugins-tab-btn");

    if (typeof window.fetchPlugins === "function") {
        await Promise.resolve(window.fetchPlugins());
    }
}

function isElementVisible(el) {
    if (!el) {
        return false;
    }

    const rect = el.getBoundingClientRect();
    return rect.width > 0 && rect.height > 0;
}

function findVisibleTarget(step) {
    const selectors = step.selectorList || (step.selector ? [step.selector] : []);
    for (const selector of selectors) {
        const el = document.querySelector(selector);
        if (isElementVisible(el)) {
            return el;
        }
    }

    return null;
}

function isStepAvailable(step) {
    if (typeof step.isAvailable === "function" && !step.isAvailable()) {
        return false;
    }

    if (step.availabilitySelector && !document.querySelector(step.availabilitySelector)) {
        return false;
    }

    if (step.selectorList) {
        return step.selectorList.some((selector) => document.querySelector(selector))
            || typeof step.prepare === "function";
    }

    return !step.selector
        || Boolean(document.querySelector(step.selector))
        || typeof step.prepare === "function"
        || Boolean(step.availabilitySelector);
}

async function resolveStepTarget(step, token, attemptsRemaining = 12) {
    if (!step) {
        return null;
    }

    if (typeof step.prepare === "function") {
        await Promise.resolve(step.prepare());
    }

    for (let attempt = 0; attempt < attemptsRemaining; attempt += 1) {
        if (token !== pendingStepToken) {
            return null;
        }

        const target = findVisibleTarget(step);
        if (target) {
            return target;
        }

        await wait(100);
    }

    return null;
}

function ensureDocumentsListView() {
    activateTab("documents-tab-btn");

    const listRadio = document.getElementById("docs-view-list");
    if (listRadio && !listRadio.checked) {
        listRadio.click();
    }
}

function getVisibleDocumentRows() {
    return Array.from(document.querySelectorAll("#documents-table tbody tr[id^='doc-row-']"))
        .filter((row) => isElementVisible(row));
}

function getFirstVisibleDocumentRow() {
    return getVisibleDocumentRows()[0] || null;
}

function getDocumentIdFromRow(row) {
    return row?.id?.startsWith("doc-row-") ? row.id.replace("doc-row-", "") : null;
}

function getFirstDocumentId() {
    return getDocumentIdFromRow(getFirstVisibleDocumentRow());
}

function hasVisibleDocuments() {
    return Boolean(getFirstVisibleDocumentRow());
}

function getDetailsRow(docId) {
    return docId ? document.getElementById(`details-row-${docId}`) : null;
}

function getDocumentDetailsPanel(docId) {
    return docId ? document.querySelector(`#details-row-${docId} .bg-light`) : null;
}

function getFirstDocumentActionsButton() {
    return getFirstVisibleDocumentRow()?.querySelector(".action-dropdown .dropdown-toggle") || null;
}

function ensureFirstDocumentDetailsVisible() {
    ensureDocumentsListView();

    const docId = getFirstDocumentId();
    const detailsRow = getDetailsRow(docId);
    if (!docId || !detailsRow) {
        return null;
    }

    if (detailsRow.style.display === "none") {
        window.toggleDetails?.(docId);
        registerTemporaryStateRestorer(() => {
            if (detailsRow.style.display !== "none") {
                window.toggleDetails?.(docId);
            }
        });
    }

    return getDocumentDetailsPanel(docId);
}

function ensureSelectionModeEnabled() {
    ensureDocumentsListView();

    const documentsTable = document.getElementById("documents-table");
    if (!documentsTable) {
        return false;
    }

    if (!documentsTable.classList.contains("selection-mode")) {
        window.toggleSelectionMode?.();
        registerTemporaryStateRestorer(() => {
            if (documentsTable.classList.contains("selection-mode")) {
                window.toggleSelectionMode?.();
            }
        });
    }

    return true;
}

function ensureFirstDocumentSelected() {
    if (!ensureSelectionModeEnabled()) {
        return null;
    }

    const row = getFirstVisibleDocumentRow();
    const docId = getDocumentIdFromRow(row);
    const checkbox = row?.querySelector(".document-checkbox");
    if (!row || !docId || !checkbox) {
        return null;
    }

    if (!checkbox.checked) {
        checkbox.checked = true;
        window.updateSelectedDocuments?.(docId, true);
        registerTemporaryStateRestorer(() => {
            if (checkbox.checked) {
                checkbox.checked = false;
                window.updateSelectedDocuments?.(docId, false);
            }
        });
    }

    return checkbox;
}

function createTutorialSurfaceRoot(className, styles = {}) {
    const surface = document.createElement("div");
    surface.className = className;
    Object.assign(surface.style, styles);
    if (layerEl && cardEl && layerEl.contains(cardEl)) {
        layerEl.insertBefore(surface, cardEl);
    } else if (layerEl) {
        layerEl.appendChild(surface);
    } else {
        document.body.appendChild(surface);
    }
    registerTemporaryStateRestorer(() => {
        surface.remove();
    });
    return surface;
}

function stripCloneIds(root) {
    root.querySelectorAll("[id]").forEach((el) => {
        el.setAttribute("data-tutorial-source-id", el.id);
        el.removeAttribute("id");
    });
    root.querySelectorAll("label[for]").forEach((el) => {
        el.removeAttribute("for");
    });
}

function addTutorialCloneBanner(container, text) {
    const banner = document.createElement("div");
    banner.className = "alert alert-info small mb-3";
    banner.textContent = text;
    container.prepend(banner);
}

function markTutorialCloneIgnoredByAutofill(root) {
    root.setAttribute("data-bwignore", "true");
    root.setAttribute("data-1p-ignore", "true");
    root.setAttribute("data-lpignore", "true");
    root.setAttribute("autocomplete", "off");

    root.querySelectorAll("form, input, textarea, select, button").forEach((el) => {
        el.setAttribute("data-bwignore", "true");
        el.setAttribute("data-1p-ignore", "true");
        el.setAttribute("data-lpignore", "true");
        el.setAttribute("autocomplete", "off");
    });
}

function createStaticFieldFromControl(control) {
    const field = document.createElement("div");
    field.className = control.className || "";
    field.classList.add("workspace-tutorial-static-field");
    field.setAttribute("data-tutorial-source-id", control.getAttribute("data-tutorial-source-id") || "");

    if (control.tagName === "TEXTAREA") {
        field.classList.add("is-textarea");
        field.textContent = control.value || control.textContent || "";
        return field;
    }

    if (control.tagName === "SELECT") {
        field.classList.add("is-select");
        const selectedOption = control.options[control.selectedIndex];
        field.textContent = selectedOption ? selectedOption.textContent : "";
        return field;
    }

    if (control.tagName === "INPUT" && control.type === "color") {
        field.classList.add("is-color");
        const swatch = document.createElement("div");
        swatch.className = "workspace-tutorial-static-color-swatch";
        swatch.style.backgroundColor = control.value || "#0d6efd";
        field.appendChild(swatch);
        return field;
    }

    field.textContent = control.value || control.getAttribute("value") || control.placeholder || "";
    return field;
}

function convertTutorialCloneControlsToStatic(root) {
    root.querySelectorAll("input, textarea, select").forEach((control) => {
        const staticField = createStaticFieldFromControl(control);
        control.replaceWith(staticField);
    });
}

function createTutorialModalClone(sourceModalId, cloneClassName, customizeClone) {
    const sourceContent = document.querySelector(`#${sourceModalId} .modal-content`);
    if (!sourceContent) {
        return null;
    }

    const surface = createTutorialSurfaceRoot(
        `workspace-tutorial-surface ${cloneClassName}`,
        {
            position: "fixed",
            inset: "0",
            zIndex: "1103",
            pointerEvents: "none"
        }
    );

    const backdrop = document.createElement("div");
    backdrop.className = "workspace-tutorial-modal-backdrop";
    Object.assign(backdrop.style, {
        position: "absolute",
        inset: "0",
        background: "rgba(0, 0, 0, 0.12)"
    });

    const dialog = document.createElement("div");
    dialog.className = "workspace-tutorial-modal-dialog";
    Object.assign(dialog.style, {
        position: "absolute",
        top: "50%",
        left: "50%",
        transform: "translate(-50%, -50%)",
        width: "min(560px, calc(100vw - 2rem))",
        maxHeight: "calc(100vh - 2rem)",
        overflow: "auto",
        pointerEvents: "auto"
    });

    const clone = sourceContent.cloneNode(true);
    stripCloneIds(clone);
    markTutorialCloneIgnoredByAutofill(clone);
    clone.querySelectorAll("input, textarea, select, button").forEach((el) => {
        if (el.tagName === "BUTTON") {
            el.disabled = true;
        } else {
            el.disabled = true;
            el.readOnly = true;
        }
    });

    if (typeof customizeClone === "function") {
        customizeClone(clone);
    }

    convertTutorialCloneControlsToStatic(clone);

    dialog.appendChild(clone);
    surface.appendChild(backdrop);
    surface.appendChild(dialog);
    return clone;
}

function createTutorialAnchoredMenu(anchorEl, className, innerHtml) {
    if (!anchorEl) {
        return null;
    }

    const rect = anchorEl.getBoundingClientRect();
    const surface = createTutorialSurfaceRoot(
        `workspace-tutorial-menu-clone ${className}`,
        {
            position: "fixed",
            top: `${Math.min(rect.bottom + 6, window.innerHeight - 260)}px`,
            left: `${Math.max(EDGE_PADDING, Math.min(rect.right - 240, window.innerWidth - 260))}px`,
            zIndex: "1103",
            minWidth: "240px",
            pointerEvents: "none"
        }
    );

    const menu = document.createElement("div");
    menu.className = "dropdown-menu show shadow-lg";
    menu.style.position = "static";
    menu.innerHTML = innerHtml;
    surface.appendChild(menu);
    return menu;
}

function ensureTutorialMetadataModal() {
    const clone = createTutorialModalClone("docMetadataModal", "workspace-tutorial-metadata-modal", (modalContent) => {
        addTutorialCloneBanner(modalContent.querySelector(".modal-body"), "Example only: this tutorial preview shows the metadata editor layout without changing your real document.");

        const titleInput = modalContent.querySelector("input[data-tutorial-source-id='doc-title']");
        const abstractInput = modalContent.querySelector("textarea[data-tutorial-source-id='doc-abstract']");
        const keywordsInput = modalContent.querySelector("input[data-tutorial-source-id='doc-keywords']");
        const pubDateInput = modalContent.querySelector("input[data-tutorial-source-id='doc-publication-date']");
        const authorsInput = modalContent.querySelector("input[data-tutorial-source-id='doc-authors']");
        const classificationSelect = modalContent.querySelector("select[data-tutorial-source-id='doc-classification']");
        const tagsContainer = modalContent.querySelector("[data-tutorial-source-id='doc-selected-tags-container']");

        if (titleInput) titleInput.value = "Milestone Tracking Data";
        if (abstractInput) abstractInput.value = "Example metadata showing the document summary, business context, and why the file matters before saving your edits.";
        if (keywordsInput) keywordsInput.value = "milestones, status tracking, ownership, project management";
        if (pubDateInput) pubDateInput.value = "03/2026";
        if (authorsInput) authorsInput.value = "Alex Wilber, Joni Sherman";
        if (classificationSelect) {
            classificationSelect.value = classificationSelect.querySelector("option[value='none']") ? "none" : classificationSelect.value;
        }
        if (tagsContainer) {
            tagsContainer.innerHTML = EXAMPLE_TAGS.slice(0, 3).map((tag) => `
                <span class="badge rounded-pill" style="background-color: ${tag.color}; color: #fff;">${tag.name}</span>
            `).join("");
        }
    });

    return clone?.querySelector(".modal-content") || null;
}

function ensureTutorialShareModal() {
    const clone = createTutorialModalClone("shareDocumentModal", "workspace-tutorial-share-modal", (modalContent) => {
        addTutorialCloneBanner(modalContent.querySelector(".modal-body"), "Example only: sharing is shown with sample users so the tutorial can explain the workflow without exposing your real sharing list.");

        const documentName = modalContent.querySelector("[data-tutorial-source-id='shareDocumentName']");
        const noSharedUsers = modalContent.querySelector("[data-tutorial-source-id='noSharedUsers']");
        const sharedUsersList = modalContent.querySelector("[data-tutorial-source-id='sharedUsersList']");
        const searchInput = modalContent.querySelector("input[data-tutorial-source-id='userSearchTerm']");
        const searchStatus = modalContent.querySelector("[data-tutorial-source-id='searchStatus']");
        const resultsBody = modalContent.querySelector("table[data-tutorial-source-id='userSearchResultsTable'] tbody");

        if (documentName) documentName.textContent = "milestones-20260320.xlsx";
        if (noSharedUsers) noSharedUsers.remove();
        if (sharedUsersList) {
            sharedUsersList.innerHTML = EXAMPLE_SHARED_USERS.map((user) => `
                <div class="d-flex justify-content-between align-items-center border-bottom py-2 small">
                    <div>
                        <div class="fw-semibold">${user.name}</div>
                        <div class="text-muted">${user.email}</div>
                    </div>
                    <span class="badge bg-secondary">Viewer</span>
                </div>
            `).join("");
        }
        if (searchInput) searchInput.value = "Megan";
        if (searchStatus) searchStatus.textContent = "Example results shown";
        if (resultsBody) {
            resultsBody.innerHTML = `
                <tr>
                    <td>Megan Bowen</td>
                    <td>megan.bowen@contoso.com</td>
                    <td><button type="button" class="btn btn-sm btn-outline-primary" disabled>Share</button></td>
                </tr>`;
        }
    });

    return clone?.querySelector(".modal-content") || null;
}

function ensureTutorialBulkTagModal() {
    const clone = createTutorialModalClone("bulkTagModal", "workspace-tutorial-bulk-tag-modal", (modalContent) => {
        addTutorialCloneBanner(modalContent.querySelector(".modal-body"), "Example only: this shows how bulk tag assignment works using sample tags, not your saved workspace data.");

        const count = modalContent.querySelector("[data-tutorial-source-id='bulk-tag-doc-count']");
        const actionSelect = modalContent.querySelector("select[data-tutorial-source-id='bulk-tag-action']");
        const tagsList = modalContent.querySelector("[data-tutorial-source-id='bulk-tags-list']");

        if (count) count.textContent = "2";
        if (actionSelect) actionSelect.value = "add_tags";
        if (tagsList) {
            tagsList.innerHTML = EXAMPLE_TAGS.map((tag, index) => `
                <button type="button" class="btn btn-sm ${index < 2 ? "btn-primary" : "btn-outline-secondary"}" disabled>
                    <i class="bi bi-tag-fill me-1"></i>${tag.name}
                </button>
            `).join("");
        }
    });

    return clone?.querySelector(".modal-content") || null;
}

function createTutorialTagSelectionModal(cloneClassName, titleText, bannerText) {
    const clone = createTutorialModalClone("tagSelectionModal", cloneClassName, (modalContent) => {
        const modalTitle = modalContent.querySelector(".modal-title");
        const list = modalContent.querySelector("[data-tutorial-source-id='tag-selection-list']");

        if (modalTitle) {
            modalTitle.textContent = titleText;
        }

        addTutorialCloneBanner(modalContent.querySelector(".modal-body"), bannerText);

        if (list) {
            list.innerHTML = EXAMPLE_TAGS.map((tag, index) => `
                <button type="button" class="list-group-item list-group-item-action d-flex justify-content-between align-items-center ${index < 2 ? "active" : ""}" disabled>
                    <span class="d-flex align-items-center gap-2">
                        <span class="rounded-circle" style="display:inline-block;width:12px;height:12px;background:${tag.color};"></span>
                        <span>${tag.name}</span>
                    </span>
                    <span class="badge ${index < 2 ? "bg-light text-dark" : "bg-secondary"}">${tag.count}</span>
                </button>
            `).join("");
        }
    });

    return clone?.querySelector(".modal-content") || null;
}

function ensureTutorialTagExampleModal() {
    return createTutorialTagSelectionModal(
        "workspace-tutorial-tag-example-modal",
        "Example Tag Selection",
        "Example only: these sample tags show how tags appear when you assign them to documents."
    );
}

function ensureTutorialMetadataTagSelectionModal() {
    return createTutorialTagSelectionModal(
        "workspace-tutorial-metadata-tag-selection-modal",
        "Select Tags For This Document",
        "Example only: this shows the single-document tag picker that appears from Manage Tags inside Edit Metadata."
    );
}

function ensureTutorialBulkTagSelectionModal() {
    return createTutorialTagSelectionModal(
        "workspace-tutorial-bulk-tag-selection-modal",
        "Select Tags For Selected Documents",
        "Example only: this shows the tag picker launched from the bulk Tag Assignment workflow for selected documents."
    );
}

function ensureTutorialWorkspaceTagManagementModal() {
    const clone = createTutorialModalClone("tagManagementModal", "workspace-tutorial-tag-management-modal", (modalContent) => {
        addTutorialCloneBanner(modalContent.querySelector(".modal-body"), "Example only: this shows the workspace tag library so the tutorial can explain tag creation, colors, counts, and editing without changing your real tags.");

        const nameInput = modalContent.querySelector("input[data-tutorial-source-id='new-tag-name']");
        const colorInput = modalContent.querySelector("input[data-tutorial-source-id='new-tag-color']");
        const tbody = modalContent.querySelector("[data-tutorial-source-id='existing-tags-tbody']");

        if (nameInput) {
            nameInput.value = "quarterly-review";
        }
        if (colorInput) {
            colorInput.value = "#7b61ff";
        }
        if (tbody) {
            tbody.innerHTML = EXAMPLE_TAGS.map((tag) => `
                <tr>
                    <td><span class="rounded-circle d-inline-block" style="width: 18px; height: 18px; background: ${tag.color};"></span></td>
                    <td><span class="badge rounded-pill" style="background-color: ${tag.color}; color: #fff;">${tag.name}</span></td>
                    <td>${tag.count}</td>
                    <td>
                        <button type="button" class="btn btn-sm btn-outline-secondary me-1" disabled>Edit</button>
                        <button type="button" class="btn btn-sm btn-outline-danger" disabled>Delete</button>
                    </td>
                </tr>
            `).join("");
        }
    });

    return clone?.querySelector(".modal-content") || null;
}

function ensureTutorialActionsMenu() {
    const menu = createTutorialAnchoredMenu(getFirstDocumentActionsButton(), "workspace-tutorial-doc-actions-menu", `
        <h6 class="dropdown-header">Document actions</h6>
        <button type="button" class="dropdown-item" data-tutorial-item="select" disabled>
            <i class="bi bi-check-square me-2"></i>Select
        </button>
        <button type="button" class="dropdown-item" data-tutorial-item="edit" disabled>
            <i class="bi bi-pencil-fill me-2"></i>Edit Metadata
        </button>
        <button type="button" class="dropdown-item" data-tutorial-item="chat" disabled>
            <i class="bi bi-chat-dots-fill me-2"></i>Chat
        </button>
        ${isFeatureEnabled("enable_file_sharing") ? `
            <div class="dropdown-divider"></div>
            <button type="button" class="dropdown-item" data-tutorial-item="share" disabled>
                <i class="bi bi-share-fill me-2"></i>Share
                <span class="badge bg-secondary ms-1">2</span>
            </button>
        ` : ""}
    `);

    return menu;
}

function buildSteps() {
    return [
        {
            id: "documents-upload",
            selector: "#upload-area",
            title: "Upload documents",
            body: "Drag files here or click to browse when you want to add new source material to your personal workspace.",
            prepare: () => activateTab("documents-tab-btn")
        },
        {
            id: "documents-filters-toggle",
            selector: "#docs-filters-toggle-btn",
            title: "Open document filters",
            body: "Use Show Search/Filters to reveal the document search, classification, author, keyword, abstract, and tag filters.",
            prepare: () => activateTab("documents-tab-btn")
        },
        {
            id: "documents-search",
            selector: "#docs-search-input",
            title: "Search your documents",
            body: "Search by file name or title here, then combine it with the metadata filters below when you need to narrow a large workspace quickly.",
            prepare: () => {
                activateTab("documents-tab-btn");
                ensureCollapseVisible("docs-filters-toggle-btn", "docs-filters-collapse");
            }
        },
        {
            id: "documents-view-toggle",
            selectorList: ["label[for='docs-view-grid']", "label[for='docs-view-list']"],
            title: "Switch document views",
            body: "Toggle between List and Grid to work either with document rows or tag-folder style organization.",
            prepare: () => activateTab("documents-tab-btn")
        },
        {
            id: "documents-open-details",
            selector: "#documents-table tbody tr[id^='doc-row-'] .expand-collapse-container button",
            title: "Open a document row",
            body: "Use the chevron on a document row to expand an in-place summary with metadata, tags, and document-specific actions.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureDocumentsListView
        },
        {
            id: "documents-details-panel",
            selector: "#documents-table tbody tr[id^='details-row-'] .bg-light",
            title: "Review document details",
            body: "The expanded section shows the file's metadata summary, detected tags, citations mode, and quick actions before you open a full editor.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureFirstDocumentDetailsVisible
        },
        {
            id: "documents-edit-metadata-button",
            selector: "#documents-table tbody tr[id^='details-row-'] .btn-info",
            title: "Edit metadata from the row",
            body: "Edit Metadata opens the document editor so you can refine title, abstract, keywords, publication date, authors, classification, and tags.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureFirstDocumentDetailsVisible
        },
        {
            id: "documents-edit-metadata-modal",
            selector: ".workspace-tutorial-metadata-modal .modal-content",
            title: "Metadata editor example",
            body: "This example modal shows the metadata form layout. It is a tutorial preview, so the values are sample content and nothing here changes your real document.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureTutorialMetadataModal,
            skipScrollIntoView: true
        },
        {
            id: "documents-edit-metadata-tag-selection",
            selector: ".workspace-tutorial-metadata-tag-selection-modal .modal-content",
            title: "Single-file tag picker example",
            body: "Right after opening Edit Metadata, this example shows the single-file tag picker that appears from Manage Tags. It demonstrates how tags are listed, colored, and counted for one document.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureTutorialMetadataTagSelectionModal,
            skipScrollIntoView: true
        },
        {
            id: "documents-chat-button",
            selector: "#documents-table tbody tr[id^='doc-row-'] button[onclick*='redirectToChat']",
            title: "Start chat from a document",
            body: "The row Chat button jumps straight into the chat page with that document preselected so you can ask questions about just this file.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureDocumentsListView
        },
        {
            id: "documents-actions-button",
            selector: "#documents-table tbody tr[id^='doc-row-'] .action-dropdown .dropdown-toggle",
            title: "Open document actions",
            body: "The three-dot menu collects row actions such as select mode, metadata editing, chat, sharing, and destructive actions.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureDocumentsListView
        },
        {
            id: "documents-actions-menu",
            selector: ".workspace-tutorial-doc-actions-menu .dropdown-menu",
            title: "Document actions overview",
            body: "This tutorial version shows the row actions in one place so you can see what each option means without changing the real row state underneath.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureTutorialActionsMenu,
            skipScrollIntoView: true
        },
        {
            id: "documents-actions-share",
            selector: ".workspace-tutorial-doc-actions-menu [data-tutorial-item='share']",
            title: "Share a document",
            body: "If sharing is enabled, Share lets you grant access to other users and review who already has this document.",
            isAvailable: () => hasVisibleDocuments() && isFeatureEnabled("enable_file_sharing"),
            prepare: ensureTutorialActionsMenu,
            targetHighlightClass: "workspace-tutorial-target-highlight",
            suppressOverlayHighlight: true,
            skipScrollIntoView: true
        },
        {
            id: "documents-share-modal",
            selector: ".workspace-tutorial-share-modal .modal-content",
            title: "Share dialog example",
            body: "This example share dialog shows the current access list, user lookup, and how new people can be added. The names here are sample data for the tutorial only.",
            isAvailable: () => hasVisibleDocuments() && isFeatureEnabled("enable_file_sharing"),
            prepare: ensureTutorialShareModal,
            skipScrollIntoView: true
        },
        {
            id: "documents-actions-chat",
            selector: ".workspace-tutorial-doc-actions-menu [data-tutorial-item='chat']",
            title: "Chat from the actions menu",
            body: "The Chat menu item does the same handoff as the row Chat button, which is useful when you are already working inside the actions menu.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureTutorialActionsMenu,
            targetHighlightClass: "workspace-tutorial-target-highlight",
            suppressOverlayHighlight: true,
            skipScrollIntoView: true
        },
        {
            id: "documents-actions-select",
            selector: ".workspace-tutorial-doc-actions-menu [data-tutorial-item='select']",
            title: "Enter selection mode",
            body: "Select switches the list into bulk-selection mode so you can act on several documents at once instead of one row at a time.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureTutorialActionsMenu,
            targetHighlightClass: "workspace-tutorial-target-highlight",
            suppressOverlayHighlight: true,
            skipScrollIntoView: true
        },
        {
            id: "documents-selection-checkbox",
            selector: "#documents-table.selection-mode tbody tr[id^='doc-row-'] .document-checkbox",
            title: "Choose documents for bulk actions",
            body: "Selection mode replaces the expand chevrons with checkboxes. Tick the documents you want to tag, chat with, delete, or clear from the current selection.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureFirstDocumentSelected
        },
        {
            id: "documents-selection-bar",
            selector: "#bulkActionsBar",
            title: "Bulk actions bar",
            body: "Once a document is selected, the bulk bar appears with Tag Assignment, Chat with Selected, Delete Selected, and Clear Selection so you can work across multiple files quickly.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureFirstDocumentSelected
        },
        {
            id: "documents-bulk-tag-modal",
            selector: ".workspace-tutorial-bulk-tag-modal .modal-content",
            title: "Bulk tag assignment example",
            body: "After you enter selection mode and choose Tag Assignment, this is the bulk tagging window. Use it to add, remove, or replace tags across several selected documents at once.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureTutorialBulkTagModal,
            skipScrollIntoView: true
        },
        {
            id: "documents-bulk-tag-selection",
            selector: ".workspace-tutorial-bulk-tag-selection-modal .modal-content",
            title: "Bulk tag picker example",
            body: "This follow-up example shows the tag picker launched from the bulk tag window so you can see how available tags look before applying them to the selected documents.",
            isAvailable: hasVisibleDocuments,
            prepare: ensureTutorialBulkTagSelectionModal,
            skipScrollIntoView: true
        },
        {
            id: "documents-manage-tags",
            selector: "#workspace-manage-tags-btn",
            title: "Manage workspace tags",
            body: "Use Manage Tags to maintain the workspace-wide tag library itself: create new tags, rename them, change colors, and keep document tagging consistent.",
            prepare: () => activateTab("documents-tab-btn")
        },
        {
            id: "documents-manage-tags-modal",
            selector: ".workspace-tutorial-tag-management-modal .modal-content",
            title: "Workspace tag library example",
            body: "This example shows the Manage Workspace Tags popup, where you add new tags, set colors, review how many documents use each tag, and maintain the shared tag library.",
            prepare: ensureTutorialWorkspaceTagManagementModal,
            skipScrollIntoView: true
        },
        {
            id: "prompts-create",
            selector: "#create-prompt-btn",
            availabilitySelector: "#prompts-tab-btn",
            title: "Create saved prompts",
            body: "Your Prompts stores reusable instructions and templates so you can start common tasks faster.",
            prepare: () => activateTab("prompts-tab-btn")
        },
        {
            id: "prompts-filters-toggle",
            selector: "#prompts-filters-toggle-btn",
            availabilitySelector: "#prompts-tab-btn",
            title: "Open prompt search",
            body: "Use Show Search/Filters in the prompts tab when you need to find a saved prompt by name instead of browsing the full list.",
            prepare: () => activateTab("prompts-tab-btn")
        },
        {
            id: "prompts-search",
            selector: "#prompts-search-input",
            availabilitySelector: "#prompts-tab-btn",
            title: "Search saved prompts",
            body: "Search prompts by name here and keep your prompt library manageable as it grows.",
            prepare: () => {
                activateTab("prompts-tab-btn");
                ensureCollapseVisible("prompts-filters-toggle-btn", "prompts-filters-collapse");
            }
        },
        {
            id: "agents-templates",
            selector: ".agent-examples-trigger",
            availabilitySelector: "#agents-tab-btn",
            title: "Start from agent templates",
            body: "Agent Templates gives you prebuilt starting points so you can assemble a new personal agent faster.",
            prepare: () => activateTab("agents-tab-btn")
        },
        {
            id: "agents-create",
            selector: "#create-agent-btn",
            availabilitySelector: "#agents-tab-btn",
            title: "Create personal agents",
            body: "Use New Agent to build a reusable agent with its own instructions, model choices, and action connections.",
            prepare: () => activateTab("agents-tab-btn")
        },
        {
            id: "agents-search",
            selector: "#agents-search",
            availabilitySelector: "#agents-tab-btn",
            title: "Search your agents",
            body: "Search agents by name or description to jump directly to the one you want to chat with or edit.",
            prepare: () => activateTab("agents-tab-btn")
        },
        {
            id: "plugins-create",
            selector: "#create-plugin-btn",
            availabilitySelector: "#plugins-tab-btn",
            title: "Create personal actions",
            body: "Use New Action to add a reusable tool or API integration that your personal agents can call.",
            prepare: ensurePluginsReady
        },
        {
            id: "plugins-search",
            selector: "#plugins-search",
            availabilitySelector: "#plugins-tab-btn",
            title: "Search your actions",
            body: "Search your action library by name or description to find the right integration quickly.",
            prepare: ensurePluginsReady
        }
    ];
}

function createLayer() {
    layerEl = document.createElement("div");
    layerEl.className = "workspace-tutorial-layer";

    highlightEl = document.createElement("div");
    highlightEl.className = "workspace-tutorial-highlight";
    highlightEl.setAttribute("aria-hidden", "true");

    cardEl = document.createElement("div");
    cardEl.className = "workspace-tutorial-card card shadow";
    cardEl.setAttribute("role", "dialog");
    cardEl.setAttribute("aria-live", "polite");

    layerEl.appendChild(highlightEl);
    layerEl.appendChild(cardEl);
    document.body.appendChild(layerEl);
}

function clearTargetHighlight() {
    if (highlightedTargetEl) {
        highlightedTargetEl.classList.remove("workspace-tutorial-target-highlight");
        highlightedTargetEl = null;
    }
}

function applyTargetHighlight(step, target) {
    clearTargetHighlight();

    if (step?.targetHighlightClass && target) {
        target.classList.add(step.targetHighlightClass);
        highlightedTargetEl = target;
    }
}

function cancelScheduledPosition() {
    if (scheduledPositionFrame) {
        window.cancelAnimationFrame(scheduledPositionFrame);
        scheduledPositionFrame = 0;
    }
}

function schedulePositionElements() {
    if (!layerEl) {
        return;
    }

    cancelScheduledPosition();
    scheduledPositionFrame = window.requestAnimationFrame(() => {
        scheduledPositionFrame = 0;
        window.requestAnimationFrame(() => {
            if (layerEl) {
                positionElements();
            }
        });
    });
}

function handleLayoutShift() {
    schedulePositionElements();
}

function startLayoutObservers() {
    stopLayoutObservers();

    const observedRoot = document.querySelector(".container") || document.body;
    if (!observedRoot) {
        return;
    }

    if (window.ResizeObserver) {
        layoutResizeObserver = new ResizeObserver(() => {
            schedulePositionElements();
        });
        layoutResizeObserver.observe(observedRoot);
    }

    if (window.MutationObserver) {
        layoutMutationObserver = new MutationObserver((mutations) => {
            const shouldReposition = mutations.some((mutation) => mutation.type === "childList"
                || mutation.attributeName === "class"
                || mutation.attributeName === "style"
                || mutation.attributeName === "aria-expanded");

            if (shouldReposition) {
                schedulePositionElements();
            }
        });

        layoutMutationObserver.observe(observedRoot, {
            subtree: true,
            childList: true,
            attributes: true,
            attributeFilter: ["class", "style", "aria-expanded"]
        });
    }
}

function stopLayoutObservers() {
    layoutResizeObserver?.disconnect();
    layoutResizeObserver = null;

    layoutMutationObserver?.disconnect();
    layoutMutationObserver = null;

    cancelScheduledPosition();
}

function positionElements() {
    if (!activeTarget || !highlightEl || !cardEl) {
        return;
    }

    highlightEl.style.opacity = currentStep?.suppressOverlayHighlight ? "0" : "1";

    const rect = activeTarget.getBoundingClientRect();
    const top = Math.max(rect.top - HIGHLIGHT_PADDING, EDGE_PADDING);
    const left = Math.max(rect.left - HIGHLIGHT_PADDING, EDGE_PADDING);
    const width = Math.min(rect.width + HIGHLIGHT_PADDING * 2, window.innerWidth - EDGE_PADDING * 2);
    const height = Math.min(rect.height + HIGHLIGHT_PADDING * 2, window.innerHeight - EDGE_PADDING * 2);

    highlightEl.style.top = `${top}px`;
    highlightEl.style.left = `${left}px`;
    highlightEl.style.width = `${width}px`;
    highlightEl.style.height = `${height}px`;

    cardEl.style.top = `${EDGE_PADDING}px`;
    cardEl.style.left = `${EDGE_PADDING}px`;

    const cardRect = cardEl.getBoundingClientRect();
    let cardTop = rect.bottom + CARD_GAP;
    let cardLeft = rect.left + rect.width / 2 - cardRect.width / 2;

    if (cardTop + cardRect.height > window.innerHeight - EDGE_PADDING) {
        cardTop = rect.top - cardRect.height - CARD_GAP;
    }

    if (cardTop < EDGE_PADDING) {
        cardTop = Math.min(window.innerHeight - cardRect.height - EDGE_PADDING, Math.max(EDGE_PADDING, rect.top + CARD_GAP));
    }

    cardLeft = Math.max(EDGE_PADDING, Math.min(cardLeft, window.innerWidth - cardRect.width - EDGE_PADDING));

    cardEl.style.top = `${cardTop}px`;
    cardEl.style.left = `${cardLeft}px`;
}

function renderCard(step) {
    const isLast = currentStepIndex === tutorialSteps.length - 1;
    cardEl.innerHTML = `
        <div class="card-body p-3">
            <div class="d-flex justify-content-between align-items-center mb-2">
                <span class="badge bg-secondary workspace-tutorial-step-badge">${currentStepIndex + 1}/${tutorialSteps.length}</span>
                <button type="button" class="btn-close" aria-label="Close tutorial"></button>
            </div>
            <h6 class="fw-semibold mb-1">${step.title}</h6>
            <p class="mb-3 small text-muted">${step.body}</p>
            <div class="d-flex justify-content-between align-items-center gap-2 workspace-tutorial-actions">
                <div class="d-flex gap-2">
                    <button type="button" class="btn btn-outline-secondary btn-sm" data-action="back" ${currentStepIndex === 0 ? "disabled" : ""}>Back</button>
                    <button type="button" class="btn btn-primary btn-sm" data-action="next">${isLast ? "Finish" : "Next"}</button>
                </div>
                <button type="button" class="btn btn-link btn-sm" data-action="skip">Skip</button>
            </div>
        </div>`;

    cardEl.querySelector(".btn-close")?.addEventListener("click", () => endTutorial());
    cardEl.querySelectorAll("[data-action]").forEach((btn) => {
        btn.addEventListener("click", async (event) => {
            event.preventDefault();
            const action = event.currentTarget.getAttribute("data-action");
            if (action === "skip") {
                endTutorial();
                return;
            }
            if (action === "back") {
                await goToStep(currentStepIndex - 1, -1);
                return;
            }
            if (action === "next") {
                await goToStep(currentStepIndex + 1, 1);
            }
        });
    });
}

function handleKeydown(event) {
    if (!layerEl) {
        return;
    }

    if (event.key === "Escape") {
        endTutorial();
    }
}

function bindGlobalListeners() {
    document.addEventListener("keydown", handleKeydown);
    window.addEventListener("resize", handleLayoutShift, true);
    window.addEventListener("scroll", handleLayoutShift, true);
    document.addEventListener("shown.bs.collapse", handleLayoutShift, true);
    document.addEventListener("hidden.bs.collapse", handleLayoutShift, true);
    document.addEventListener("shown.bs.tab", handleLayoutShift, true);
    startLayoutObservers();
}

function unbindGlobalListeners() {
    document.removeEventListener("keydown", handleKeydown);
    window.removeEventListener("resize", handleLayoutShift, true);
    window.removeEventListener("scroll", handleLayoutShift, true);
    document.removeEventListener("shown.bs.collapse", handleLayoutShift, true);
    document.removeEventListener("hidden.bs.collapse", handleLayoutShift, true);
    document.removeEventListener("shown.bs.tab", handleLayoutShift, true);
    stopLayoutObservers();
}

function endTutorial() {
    pendingStepToken += 1;
    clearTargetHighlight();
    restoreTemporaryState();
    restoreActiveTab();
    unbindGlobalListeners();

    if (layerEl) {
        layerEl.remove();
    }

    layerEl = null;
    highlightEl = null;
    cardEl = null;
    activeTarget = null;
    currentStep = null;
    currentStepIndex = -1;
}

async function goToStep(startIndex, direction = 1) {
    pendingStepToken += 1;
    const token = pendingStepToken;
    restoreTemporaryState();

    let index = startIndex;
    while (index >= 0 && index < tutorialSteps.length) {
        const step = tutorialSteps[index];
        const target = await resolveStepTarget(step, token);

        if (token !== pendingStepToken) {
            return;
        }

        if (target) {
            currentStepIndex = index;
            currentStep = step;
            activeTarget = target;
            applyTargetHighlight(step, target);
            if (!step.skipScrollIntoView && !target.closest(".workspace-tutorial-surface") && target.scrollIntoView) {
                target.scrollIntoView({ block: "center", inline: "center", behavior: "instant" });
            }
            renderCard(step);
            positionElements();
            schedulePositionElements();
            return;
        }

        index += direction;
    }

    endTutorial();
}

async function startTutorial() {
    endTutorial();
    tutorialSteps = buildSteps().filter(isStepAvailable);
    if (!tutorialSteps.length) {
        console.warn("workspace-tutorial: no steps available");
        return;
    }

    createLayer();
    bindGlobalListeners();
    await goToStep(0, 1);
}

function initPersonalWorkspaceTutorial() {
    const launchButton = document.getElementById("workspace-tutorial-btn");
    if (!launchButton) {
        return;
    }

    launchButton.addEventListener("click", (event) => {
        event.preventDefault();
        startTutorial();
    });
}

if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initPersonalWorkspaceTutorial);
} else {
    initPersonalWorkspaceTutorial();
}
