// view-utils.js
// Shared utilities for list/grid view toggle, name humanization, and view modal
// Used by personal and group agents/actions workspace modules

/**
 * Convert a technical name to a human-readable display name.
 * Handles underscores, camelCase, PascalCase, and consecutive uppercase.
 * Examples:
 *   "sql_query" → "Sql Query"
 *   "myAgentName" → "My Agent Name"
 *   "OpenAPIPlugin" → "Open API Plugin"
 *   "log_analytics" → "Log Analytics"
 */
export function humanizeName(name) {
    if (!name) return "";
    // Replace underscores and hyphens with spaces
    let result = name.replace(/[_-]/g, " ");
    // Insert space before uppercase letters that follow lowercase letters (camelCase)
    result = result.replace(/([a-z])([A-Z])/g, "$1 $2");
    // Insert space between consecutive uppercase followed by lowercase (e.g., "APIPlugin" → "API Plugin")
    result = result.replace(/([A-Z]+)([A-Z][a-z])/g, "$1 $2");
    // Capitalize first letter of each word
    result = result.replace(/\b\w/g, (c) => c.toUpperCase());
    // Collapse multiple spaces
    result = result.replace(/\s+/g, " ").trim();
    return result;
}

/**
 * Truncate a description string to maxLen characters, appending "…" if truncated.
 */
export function truncateDescription(text, maxLen = 100) {
    if (!text) return "";
    if (text.length <= maxLen) return text;
    return text.substring(0, maxLen).trimEnd() + "…";
}

/**
 * Escape HTML entities to prevent XSS.
 */
export function escapeHtml(str) {
    if (!str) return "";
    return str.replace(/[&<>"']/g, (c) =>
        ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c])
    );
}

/**
 * Get an appropriate Bootstrap icon class for an action/plugin type.
 */
export function getTypeIcon(type) {
    if (!type) return "bi-lightning-charge";
    const t = type.toLowerCase();
    if (t.includes("sql")) return "bi-database";
    if (t.includes("cosmos")) return "bi-database-fill-gear";
    if (t.includes("simplechat")) return "bi-chat-square-dots";
    if (t.includes("openapi")) return "bi-globe";
    if (t.includes("log_analytics")) return "bi-graph-up";
    if (t.includes("msgraph")) return "bi-microsoft";
    if (t.includes("databricks")) return "bi-bricks";
    if (t.includes("http") || t.includes("smart_http")) return "bi-cloud-arrow-up";
    if (t.includes("azure_function")) return "bi-lightning";
    if (t.includes("blob")) return "bi-file-earmark";
    if (t.includes("queue")) return "bi-inbox";
    if (t.includes("embedding")) return "bi-vector-pen";
    if (t.includes("fact_memory")) return "bi-brain";
    if (t.includes("math")) return "bi-calculator";
    if (t.includes("text")) return "bi-fonts";
    if (t.includes("time")) return "bi-clock";
    return "bi-lightning-charge";
}

/**
 * Create the HTML string for a list/grid view toggle button group.
 * @param {string} prefix - Unique prefix for element IDs (e.g., "agents", "plugins", "group-agents")
 * @returns {string} HTML string
 */
export function createViewToggleHtml(prefix) {
    return `
        <div class="btn-group btn-group-sm" role="group" aria-label="View mode">
            <input type="radio" class="btn-check" name="${prefix}-view-mode" id="${prefix}-view-list" autocomplete="off" checked>
            <label class="btn btn-outline-secondary" for="${prefix}-view-list">
                <i class="bi bi-list-ul"></i>
            </label>
            <input type="radio" class="btn-check" name="${prefix}-view-mode" id="${prefix}-view-grid" autocomplete="off">
            <label class="btn btn-outline-secondary" for="${prefix}-view-grid">
                <i class="bi bi-grid-3x3-gap"></i>
            </label>
        </div>`;
}

/**
 * Set up view toggle event listeners and restore saved preference.
 * @param {string} prefix - Unique prefix matching createViewToggleHtml
 * @param {string} storageKey - localStorage key for persistence
 * @param {function} onSwitch - Callback receiving 'list' or 'grid'
 */
export function setupViewToggle(prefix, storageKey, onSwitch) {
    const listRadio = document.getElementById(`${prefix}-view-list`);
    const gridRadio = document.getElementById(`${prefix}-view-grid`);
    if (!listRadio || !gridRadio) return;

    listRadio.addEventListener("change", () => {
        if (listRadio.checked) {
            localStorage.setItem(storageKey, "list");
            onSwitch("list");
        }
    });

    gridRadio.addEventListener("change", () => {
        if (gridRadio.checked) {
            localStorage.setItem(storageKey, "grid");
            onSwitch("grid");
        }
    });

    // Restore saved preference
    const saved = localStorage.getItem(storageKey);
    if (saved === "grid") {
        gridRadio.checked = true;
        listRadio.checked = false;
        onSwitch("grid");
    } else {
        onSwitch("list");
    }
}

/**
 * Toggle visibility of list and grid containers.
 * @param {string} mode - 'list' or 'grid'
 * @param {HTMLElement} listContainer - The list/table container element
 * @param {HTMLElement} gridContainer - The grid container element
 */
export function switchViewContainers(mode, listContainer, gridContainer) {
    if (listContainer) {
        listContainer.classList.toggle("d-none", mode !== "list");
    }
    if (gridContainer) {
        gridContainer.classList.toggle("d-none", mode !== "grid");
    }
}

// ============================================================================
// VIEW MODAL — Lightweight read-only detail view
// ============================================================================

/**
 * Open a read-only view modal for an agent or action.
 * @param {object} item - The agent or action data object
 * @param {'agent'|'action'} type - What kind of item this is
 * @param {object} [callbacks] - Optional action callbacks { onChat, onEdit, onDelete }
 */
export function openViewModal(item, type, callbacks = {}) {
    const modalEl = document.getElementById("item-view-modal");
    if (!modalEl) return;

    const titleEl = modalEl.querySelector(".modal-title");
    const bodyEl = modalEl.querySelector(".modal-body");
    const footerEl = modalEl.querySelector(".modal-footer");
    if (!titleEl || !bodyEl || !footerEl) return;

    if (type === "agent") {
        titleEl.textContent = "Agent Details";
        bodyEl.innerHTML = buildAgentViewHtml(item);
    } else {
        titleEl.textContent = "Action Details";
        bodyEl.innerHTML = buildActionViewHtml(item);
    }

    // Build footer buttons dynamically
    footerEl.innerHTML = '';
    const { onChat, onEdit, onDelete } = callbacks;

    if (onChat && typeof onChat === 'function') {
        const chatBtn = document.createElement('button');
        chatBtn.type = 'button';
        chatBtn.className = 'btn btn-primary';
        chatBtn.innerHTML = '<i class="bi bi-chat-dots me-1"></i>Chat';
        chatBtn.addEventListener('click', () => {
            bootstrap.Modal.getInstance(modalEl)?.hide();
            onChat(item);
        });
        footerEl.appendChild(chatBtn);
    }

    if (onEdit && typeof onEdit === 'function') {
        const editBtn = document.createElement('button');
        editBtn.type = 'button';
        editBtn.className = 'btn btn-outline-secondary';
        editBtn.innerHTML = '<i class="bi bi-pencil me-1"></i>Edit';
        editBtn.addEventListener('click', () => {
            bootstrap.Modal.getInstance(modalEl)?.hide();
            onEdit(item);
        });
        footerEl.appendChild(editBtn);
    }

    if (onDelete && typeof onDelete === 'function') {
        const delBtn = document.createElement('button');
        delBtn.type = 'button';
        delBtn.className = 'btn btn-outline-danger';
        delBtn.innerHTML = '<i class="bi bi-trash me-1"></i>Delete';
        delBtn.addEventListener('click', () => {
            bootstrap.Modal.getInstance(modalEl)?.hide();
            onDelete(item);
        });
        footerEl.appendChild(delBtn);
    }

    const closeBtn = document.createElement('button');
    closeBtn.type = 'button';
    closeBtn.className = 'btn btn-secondary';
    closeBtn.textContent = 'Close';
    closeBtn.setAttribute('data-bs-dismiss', 'modal');
    footerEl.appendChild(closeBtn);

    const modal = new bootstrap.Modal(modalEl);
    modal.show();
}

function buildAgentViewHtml(agent) {
    const displayName = escapeHtml(agent.display_name || agent.displayName || agent.name || "");
    const name = escapeHtml(agent.name || "");
    const description = escapeHtml(agent.description || "No description available.");
    const model = escapeHtml(agent.azure_openai_gpt_deployment || agent.model || "Default");
    const agentType = agent.agent_type === "new_foundry"
        ? "New Foundry"
        : agent.agent_type === "aifoundry"
            ? "Foundry (classic)"
            : "Local (Semantic Kernel)";
    const rawInstructions = agent.instructions || "No instructions defined.";
    // Render instructions as Markdown (marked + DOMPurify are loaded globally in base.html)
    const renderedInstructions = (typeof marked !== 'undefined' && typeof DOMPurify !== 'undefined')
        ? DOMPurify.sanitize(marked.parse(rawInstructions))
        : escapeHtml(rawInstructions);
    const isGlobal = agent.is_global;
    const scopeBadge = isGlobal
        ? '<span class="badge bg-info text-dark">Global</span>'
        : '<span class="badge bg-secondary">Personal</span>';

    return `
        <div class="card mb-3 border-0 shadow-sm">
            <div class="card-header text-white py-2" style="background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);">
                <i class="bi bi-info-circle me-2"></i><strong>Basic Information</strong>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Display Name</label>
                        <span class="fw-medium">${displayName}</span>
                    </div>
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Generated Name</label>
                        <span class="fw-medium font-monospace">${name}</span>
                    </div>
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Scope</label>
                        ${scopeBadge}
                    </div>
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Agent Type</label>
                        <span class="badge bg-info text-dark">${escapeHtml(agentType)}</span>
                    </div>
                    <div class="col-12">
                        <label class="text-muted small mb-1 d-block">Description</label>
                        <span class="fw-medium">${description}</span>
                    </div>
                </div>
            </div>
        </div>
        <div class="card mb-3 border-0 shadow-sm">
            <div class="card-header text-white py-2" style="background: linear-gradient(135deg, #ffc107 0%, #e0a800 100%);">
                <i class="bi bi-gear me-2"></i><strong>Model Configuration</strong>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Model / Deployment</label>
                        <span class="fw-medium font-monospace">${model}</span>
                    </div>
                </div>
            </div>
        </div>
        <div class="card mb-3 border-0 shadow-sm">
            <div class="card-header text-white py-2" style="background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%);">
                <i class="bi bi-file-text me-2"></i><strong>Instructions</strong>
            </div>
            <div class="card-body">
                <div class="p-3 bg-light border rounded rendered-markdown" style="max-height: 300px; overflow-y: auto; font-size: 0.9rem;">
${renderedInstructions}
                </div>
            </div>
        </div>`;
}

function buildActionViewHtml(action) {
    const displayName = escapeHtml(action.display_name || action.displayName || action.name || "");
    const name = escapeHtml(action.name || "");
    const description = escapeHtml(action.description || "No description available.");
    const type = escapeHtml(action.type || "unknown");
    const typeIcon = getTypeIcon(action.type);
    const authType = escapeHtml(formatAuthType(action.auth?.type || action.auth_type || ""));
    const endpoint = escapeHtml(action.endpoint || action.base_url || "");
    const isGlobal = action.is_global;
    const scopeBadge = isGlobal
        ? '<span class="badge bg-info text-dark">Global</span>'
        : '<span class="badge bg-secondary">Personal</span>';

    let configHtml = "";
    if (endpoint) {
        configHtml = `
        <div class="card mb-3 border-0 shadow-sm">
            <div class="card-header text-white py-2" style="background: linear-gradient(135deg, #28a745 0%, #1e7e34 100%);">
                <i class="bi bi-gear me-2"></i><strong>Configuration</strong>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-12">
                        <label class="text-muted small mb-1 d-block">Endpoint</label>
                        <span class="fw-medium font-monospace text-break">${endpoint}</span>
                    </div>
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Authentication</label>
                        <span class="fw-medium">${authType || "None"}</span>
                    </div>
                </div>
            </div>
        </div>`;
    }

    return `
        <div class="card mb-3 border-0 shadow-sm">
            <div class="card-header text-white py-2" style="background: linear-gradient(135deg, #007bff 0%, #0056b3 100%);">
                <i class="bi bi-info-circle me-2"></i><strong>Basic Information</strong>
            </div>
            <div class="card-body">
                <div class="row g-3">
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Display Name</label>
                        <span class="fw-medium">${displayName}</span>
                    </div>
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Generated Name</label>
                        <span class="fw-medium font-monospace">${name}</span>
                    </div>
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Type</label>
                        <span class="fw-medium"><i class="bi ${typeIcon} me-1"></i>${humanizeName(type)}</span>
                    </div>
                    <div class="col-md-6">
                        <label class="text-muted small mb-1 d-block">Scope</label>
                        ${scopeBadge}
                    </div>
                    <div class="col-12">
                        <label class="text-muted small mb-1 d-block">Description</label>
                        <span class="fw-medium">${description}</span>
                    </div>
                </div>
            </div>
        </div>
        ${configHtml}`;
}

function formatAuthType(type) {
    if (!type) return "";
    const map = {
        "key": "API Key",
        "identity": "Managed Identity",
        "user": "User (Delegated)",
        "servicePrincipal": "Service Principal",
        "connection_string": "Connection String",
        "basic": "Basic Auth",
        "username_password": "Username / Password",
        "NoAuth": "No Authentication"
    };
    return map[type] || type;
}

// ============================================================================
// GRID CARD RENDERERS
// ============================================================================

/**
 * Create a grid card element for an agent.
 * @param {object} agent - Agent data object
 * @param {object} options - { onChat, onView, onEdit, onDelete, canManage, isGroup }
 * @returns {HTMLElement}
 */
export function createAgentCard(agent, options = {}) {
    const { onChat, onView, onEdit, onDelete, canManage = false, isGroup = false } = options;
    const col = document.createElement("div");
    col.className = "col-sm-6 col-md-4 col-lg-3";

    const displayName = humanizeName(agent.display_name || agent.displayName || agent.name || "");
    const description = agent.description || "No description available.";
    const isGlobal = agent.is_global;

    let badgeHtml = "";
    if (isGlobal) {
        badgeHtml = '<span class="badge bg-info text-dark ms-1" style="font-size: 0.65rem;">Global</span>';
    }

    let buttonsHtml = `
        <button class="btn btn-sm btn-primary item-card-chat-btn me-1" title="Chat with this agent">
            <i class="bi bi-chat-dots me-1"></i>Chat
        </button>
        <button class="btn btn-sm btn-outline-info item-card-view-btn me-1" title="View details">
            <i class="bi bi-eye"></i>
        </button>`;

    if (canManage && !isGlobal) {
        buttonsHtml += `
        <button class="btn btn-sm btn-outline-secondary item-card-edit-btn me-1" title="Edit">
            <i class="bi bi-pencil"></i>
        </button>
        <button class="btn btn-sm btn-outline-danger item-card-delete-btn" title="Delete">
            <i class="bi bi-trash"></i>
        </button>`;
    }

    col.innerHTML = `
        <div class="card item-card h-100">
            <div class="card-body d-flex flex-column">
                <div class="item-card-icon mb-2">
                    <i class="bi bi-robot" style="font-size: 1.75rem;"></i>
                </div>
                <h6 class="card-title mb-1">${escapeHtml(displayName)}${badgeHtml}</h6>
                <p class="card-text small text-muted flex-grow-1">${escapeHtml(truncateDescription(description, 120))}</p>
                <div class="item-card-buttons mt-2 d-flex flex-wrap gap-1">
                    ${buttonsHtml}
                </div>
            </div>
        </div>`;

    // Bind button events
    const chatBtn = col.querySelector(".item-card-chat-btn");
    const viewBtn = col.querySelector(".item-card-view-btn");
    const editBtn = col.querySelector(".item-card-edit-btn");
    const deleteBtn = col.querySelector(".item-card-delete-btn");

    if (chatBtn && onChat) chatBtn.addEventListener("click", (e) => { e.stopPropagation(); onChat(agent); });
    if (viewBtn && onView) viewBtn.addEventListener("click", (e) => { e.stopPropagation(); onView(agent); });
    if (editBtn && onEdit) editBtn.addEventListener("click", (e) => { e.stopPropagation(); onEdit(agent); });
    if (deleteBtn && onDelete) deleteBtn.addEventListener("click", (e) => { e.stopPropagation(); onDelete(agent); });

    // Clicking anywhere on the card opens the detail view
    const cardEl = col.querySelector(".item-card");
    if (cardEl && onView) {
        cardEl.style.cursor = "pointer";
        cardEl.addEventListener("click", () => onView(agent));
    }

    return col;
}

/**
 * Create a grid card element for an action/plugin.
 * @param {object} plugin - Action/plugin data object
 * @param {object} options - { onView, onEdit, onDelete, canManage, isAdmin }
 * @returns {HTMLElement}
 */
export function createActionCard(plugin, options = {}) {
    const { onView, onEdit, onDelete, canManage = true, isAdmin = false } = options;
    const col = document.createElement("div");
    col.className = "col-sm-6 col-md-4 col-lg-3";

    const displayName = humanizeName(plugin.display_name || plugin.displayName || plugin.name || "");
    const description = plugin.description || "No description available.";
    const type = plugin.type || "";
    const typeIcon = getTypeIcon(type);
    const isGlobal = plugin.is_global;

    let badgeHtml = "";
    if (isGlobal) {
        badgeHtml = '<span class="badge bg-info text-dark ms-1" style="font-size: 0.65rem;">Global</span>';
    }

    const typeBadge = type
        ? `<span class="badge bg-light text-dark border me-1" style="font-size: 0.65rem;"><i class="bi ${typeIcon} me-1"></i>${escapeHtml(humanizeName(type))}</span>`
        : "";

    let buttonsHtml = `
        <button class="btn btn-sm btn-outline-info item-card-view-btn me-1" title="View details">
            <i class="bi bi-eye"></i>
        </button>`;

    if ((isAdmin || (canManage && !isGlobal))) {
        buttonsHtml += `
        <button class="btn btn-sm btn-outline-secondary item-card-edit-btn me-1" title="Edit">
            <i class="bi bi-pencil"></i>
        </button>
        <button class="btn btn-sm btn-outline-danger item-card-delete-btn" title="Delete">
            <i class="bi bi-trash"></i>
        </button>`;
    }

    col.innerHTML = `
        <div class="card item-card h-100">
            <div class="card-body d-flex flex-column">
                <div class="item-card-icon mb-2">
                    <i class="bi ${typeIcon}" style="font-size: 1.75rem;"></i>
                </div>
                <h6 class="card-title mb-1">${escapeHtml(displayName)}${badgeHtml}</h6>
                <div class="mb-2">${typeBadge}</div>
                <p class="card-text small text-muted flex-grow-1">${escapeHtml(truncateDescription(description, 120))}</p>
                <div class="item-card-buttons mt-2 d-flex flex-wrap gap-1">
                    ${buttonsHtml}
                </div>
            </div>
        </div>`;

    // Bind button events
    const viewBtn = col.querySelector(".item-card-view-btn");
    const editBtn = col.querySelector(".item-card-edit-btn");
    const deleteBtn = col.querySelector(".item-card-delete-btn");

    if (viewBtn && onView) viewBtn.addEventListener("click", (e) => { e.stopPropagation(); onView(plugin); });
    if (editBtn && onEdit) editBtn.addEventListener("click", (e) => { e.stopPropagation(); onEdit(plugin); });
    if (deleteBtn && onDelete) deleteBtn.addEventListener("click", (e) => { e.stopPropagation(); onDelete(plugin); });

    // Clicking anywhere on the card opens the detail view
    const cardEl = col.querySelector(".item-card");
    if (cardEl && onView) {
        cardEl.style.cursor = "pointer";
        cardEl.addEventListener("click", () => onView(plugin));
    }

    return col;
}
