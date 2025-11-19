// group_plugins.js
// Handles group action management within the group workspace UI

import { ensurePluginsTableInRoot, validatePluginManifest } from "../plugin_common.js";
import { showToast } from "../chat/chat-toast.js";

const root = document.getElementById("group-plugins-root");
const permissionWarning = document.getElementById("group-plugins-permission-warning");

let plugins = [];
let filteredPlugins = [];
let templateReady = false;
let listenersBound = false;
let currentContext = window.groupWorkspaceContext || {
  activeGroupId: null,
  activeGroupName: "",
  userRole: null
};

function escapeHtml(value) {
  if (!value) return "";
  return value.replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;"
  }[char] || char));
}

function canManagePlugins() {
  const role = currentContext?.userRole;
  return role === "Owner" || role === "Admin";
}

function ensureTemplate() {
  if (!root) return null;
  if (!templateReady) {
    ensurePluginsTableInRoot({
      rootSelector: "#group-plugins-root",
      templateId: "group-plugins-table-template"
    });
    templateReady = true;
    updatePermissionUI();
    bindRootEvents();
  }
  return document.getElementById("group-plugins-table-body");
}

function bindRootEvents() {
  if (!root || listenersBound) return;

  root.addEventListener("input", (event) => {
    if (event.target && event.target.id === "group-plugins-search") {
      filterPlugins(event.target.value.trim());
    }
  });

  root.addEventListener("click", async (event) => {
    const createBtn = event.target.closest("#create-group-plugin-btn");
    if (createBtn) {
      event.preventDefault();
      openPluginModal();
      return;
    }

    const editBtn = event.target.closest(".edit-group-plugin-btn");
    if (editBtn) {
      const pluginId = editBtn.dataset.pluginId;
      openPluginModal(pluginId);
      return;
    }

    const deleteBtn = event.target.closest(".delete-group-plugin-btn");
    if (deleteBtn) {
      const pluginId = deleteBtn.dataset.pluginId;
      deleteGroupPlugin(pluginId);
    }
  });

  listenersBound = true;
}

function renderLoading() {
  if (!root) return;
  root.innerHTML = `
    <div class="d-flex justify-content-center py-5">
      <div class="spinner-border" role="status">
        <span class="visually-hidden">Loading…</span>
      </div>
    </div>`;
  templateReady = false;
}

function renderNoGroupSelected() {
  if (!root) return;
  root.innerHTML = `
    <div class="alert alert-info mt-3">
      Select a group to load actions.
    </div>`;
  templateReady = false;
}

function renderError(message) {
  if (!root) return;
  root.innerHTML = `
    <div class="alert alert-danger mt-3">
      ${escapeHtml(message)}
    </div>`;
  templateReady = false;
}

function updatePermissionUI() {
  if (!root) return;
  const canManage = canManagePlugins();
  const createBtn = document.getElementById("create-group-plugin-btn");
  if (createBtn) {
    createBtn.classList.toggle("d-none", !canManage);
    createBtn.disabled = !canManage;
  }
  if (permissionWarning) {
    permissionWarning.classList.toggle("d-none", canManage);
  }
}

function renderPluginsTable(list) {
  const tbody = ensureTemplate();
  if (!tbody) return;

  tbody.innerHTML = "";
  if (!list.length) {
    tbody.innerHTML = `
      <tr>
        <td colspan="3" class="text-center text-muted p-4">No group actions found.</td>
      </tr>`;
    return;
  }

  const canManage = canManagePlugins();
  list.forEach((plugin) => {
    const tr = document.createElement("tr");
    const displayName = plugin.displayName || plugin.display_name || plugin.name || "";
    const description = plugin.description || "No description available.";
    const isGlobal = Boolean(plugin.is_global);

    let actionsHtml = "<span class=\"text-muted small\">—</span>";
    if (canManage && !isGlobal) {
      actionsHtml = `
        <div class="d-flex gap-1">
          <button type="button" class="btn btn-sm btn-outline-secondary edit-group-plugin-btn" data-plugin-id="${escapeHtml(plugin.id || plugin.name || "")}">
            <i class="bi bi-pencil"></i>
          </button>
          <button type="button" class="btn btn-sm btn-outline-danger delete-group-plugin-btn" data-plugin-id="${escapeHtml(plugin.id || plugin.name || "")}">
            <i class="bi bi-trash"></i>
          </button>
        </div>`;
    } else if (canManage && isGlobal) {
      actionsHtml = "<span class=\"text-muted small\">Managed globally</span>";
    }

    const titleHtml = isGlobal
      ? `${escapeHtml(displayName)} <span class="badge bg-info text-dark ms-1" style="font-size: 0.65rem;">global</span>`
      : escapeHtml(displayName);

    tr.innerHTML = `
      <td><strong title="${escapeHtml(displayName)}">${titleHtml}</strong></td>
      <td class="text-muted small">${escapeHtml(description)}</td>
      <td>${actionsHtml}</td>`;

    tbody.appendChild(tr);
  });
}

function filterPlugins(term) {
  if (!term) {
    filteredPlugins = plugins.slice();
  } else {
    const needle = term.toLowerCase();
    filteredPlugins = plugins.filter((plugin) => {
      const name = (plugin.displayName || plugin.display_name || plugin.name || "").toLowerCase();
      const description = (plugin.description || "").toLowerCase();
      return name.includes(needle) || description.includes(needle);
    });
  }
  renderPluginsTable(filteredPlugins);
}

async function fetchGroupPlugins() {
  if (!root) return;

  if (!currentContext?.activeGroupId) {
    renderNoGroupSelected();
    return;
  }

  renderLoading();

  try {
    const response = await fetch("/api/group/plugins");
    const payload = await response.json().catch(() => ({ actions: [] }));
    if (!response.ok) {
      throw new Error(payload?.error || response.statusText || "Failed to load group actions");
    }

    plugins = (payload.actions || []).map((action) => ({
      ...action,
      displayName: action.displayName || action.display_name || action.name || "",
      description: action.description || "",
      is_global: Boolean(action.is_global)
    }));
    filteredPlugins = plugins.slice();

    renderPluginsTable(filteredPlugins);
    updatePermissionUI();
  } catch (error) {
    console.error("Error loading group actions:", error);
    renderError(error.message || "Unable to load group actions.");
  }
}

async function openPluginModal(pluginId = null) {
  if (!canManagePlugins()) {
    showToast("You do not have permission to manage group actions.", "warning");
    return;
  }

  if (!window.pluginModalStepper) {
    showToast("Action modal is not available. Please refresh and try again.", "danger");
    return;
  }

  let plugin = null;
  if (pluginId) {
    const cached = plugins.find((item) => item.id === pluginId || item.name === pluginId);
    if (cached?.is_global) {
      showToast("Global actions are read-only and managed by administrators.", "info");
      return;
    }
    try {
      const response = await fetch(`/api/group/plugins/${encodeURIComponent(pluginId)}`);
      const payload = await response.json().catch(() => ({}));
      if (!response.ok) {
        throw new Error(payload?.error || "Failed to load group action");
      }
      plugin = payload;
    } catch (error) {
      console.error("Error loading group action:", error);
      showToast(error.message || "Unable to load action details.", "danger");
      return;
    }
  }

  try {
    const modal = await window.pluginModalStepper.showModal(plugin);
    setupSaveHandler(plugin, modal);
  } catch (error) {
    console.error("Error opening action modal:", error);
    showToast(error.message || "Unable to open action modal.", "danger");
  }
}

function setupSaveHandler(existingPlugin, modalInstance) {
  const saveBtn = document.getElementById("save-plugin-btn");
  if (!saveBtn) return;

  saveBtn.onclick = null;
  saveBtn.onclick = async (event) => {
    event.preventDefault();

    const errorDiv = document.getElementById("plugin-modal-error");
    if (errorDiv) {
      errorDiv.classList.add("d-none");
      errorDiv.textContent = "";
    }

    try {
      const formData = window.pluginModalStepper.getFormData();
      if (existingPlugin?.id) {
        formData.id = existingPlugin.id;
      }

      const validation = await validatePluginManifest(formData);
      const validationFailed = validation === false || (validation && validation.valid === false);
      if (validationFailed) {
        const message = validation?.errors?.join("\n") || "Validation error: Invalid action data.";
        if (window.pluginModalStepper?.showError) {
          window.pluginModalStepper.showError(message);
        }
        return;
      }

      const originalText = saveBtn.innerHTML;
      saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving…`;
      saveBtn.disabled = true;
      try {
        await saveGroupPlugin(formData, existingPlugin);
      } finally {
        saveBtn.innerHTML = originalText;
        saveBtn.disabled = false;
      }

      if (modalInstance && typeof modalInstance.hide === "function") {
        modalInstance.hide();
      } else {
        bootstrap.Modal.getInstance(document.getElementById("plugin-modal"))?.hide();
      }

      showToast(existingPlugin ? "Group action updated successfully." : "Group action created successfully.", "success");
      await fetchGroupPlugins();
    } catch (error) {
      console.error("Error saving group action:", error);
      const message = error.message || "Unable to save group action.";
      if (window.pluginModalStepper?.showError) {
        window.pluginModalStepper.showError(message);
      } else {
        showToast(message, "danger");
      }
    }
  };
}

async function saveGroupPlugin(pluginManifest, existingPlugin) {
  const payload = {
    ...pluginManifest,
    displayName: pluginManifest.displayName || pluginManifest.display_name || pluginManifest.name || ""
  };

  delete payload.is_global;
  delete payload.scope;

  const hasId = Boolean(existingPlugin?.id || payload.id);
  if (!payload.id && existingPlugin?.id) {
    payload.id = existingPlugin.id;
  }

  const url = hasId ? `/api/group/plugins/${encodeURIComponent(payload.id)}` : "/api/group/plugins";
  const method = hasId ? "PATCH" : "POST";

  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });

  const body = await response.json().catch(() => ({}));
  if (!response.ok) {
    throw new Error(body?.error || `Failed to ${hasId ? "update" : "create"} group action`);
  }
  return body;
}

async function deleteGroupPlugin(pluginId) {
  if (!canManagePlugins()) {
    showToast("You do not have permission to delete group actions.", "warning");
    return;
  }
  if (!pluginId) return;

  const cached = plugins.find((item) => item.id === pluginId || item.name === pluginId);
  if (cached?.is_global) {
    showToast("Global actions cannot be deleted from a group workspace.", "info");
    return;
  }
  if (!confirm("Delete this group action?")) return;

  try {
    const response = await fetch(`/api/group/plugins/${encodeURIComponent(pluginId)}`, {
      method: "DELETE"
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.error || "Failed to delete group action");
    }
    showToast("Group action deleted successfully.", "success");
    await fetchGroupPlugins();
  } catch (error) {
    console.error("Error deleting group action:", error);
    showToast(error.message || "Unable to delete group action.", "danger");
  }
}

function initialize() {
  if (!root) return;
  ensureTemplate();
  updatePermissionUI();

  window.addEventListener("groupWorkspace:context-changed", (event) => {
    currentContext = event.detail || currentContext;
    updatePermissionUI();
  });

  if (document.getElementById("group-plugins-tab-btn")?.classList.contains("active")) {
    fetchGroupPlugins();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialize);
} else {
  initialize();
}

window.fetchGroupPlugins = fetchGroupPlugins;
