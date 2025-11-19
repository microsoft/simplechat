// group_agents.js
// Handles group agent management within the group workspace UI

import { showToast } from "../chat/chat-toast.js";
import * as agentsCommon from "../agents_common.js";
import { AgentModalStepper } from "../agent_modal_stepper.js";

const tableBody = document.getElementById("group-agents-table-body");
const errorContainer = document.getElementById("group-agents-error");
const searchInput = document.getElementById("group-agents-search");
const createButton = document.getElementById("create-group-agent-btn");
const permissionWarning = document.getElementById("group-agents-permission-warning");

let agents = [];
let filteredAgents = [];
let agentStepper = null;
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

function canManageAgents() {
  const role = currentContext?.userRole;
  return role === "Owner" || role === "Admin";
}

function truncateName(name, maxLength = 18) {
  if (!name || name.length <= maxLength) return name || "";
  return `${name.substring(0, maxLength)}…`;
}

function updatePermissionUI() {
  const canManage = canManageAgents();
  if (createButton) {
    createButton.classList.toggle("d-none", !canManage);
    createButton.disabled = !canManage;
  }
  if (permissionWarning) {
    permissionWarning.classList.toggle("d-none", canManage);
  }
}

function renderLoading() {
  if (!tableBody) return;
  tableBody.innerHTML = `
    <tr class="table-loading-row">
      <td colspan="3">
        <div class="spinner-border spinner-border-sm me-2" role="status">
          <span class="visually-hidden">Loading…</span>
        </div>
        Loading group agents…
      </td>
    </tr>`;
  if (errorContainer) {
    errorContainer.innerHTML = "";
  }
}

function renderNoGroupSelected() {
  if (!tableBody) return;
  tableBody.innerHTML = `
    <tr>
      <td colspan="3" class="text-center text-muted p-4">
        Select a group to load agents.
      </td>
    </tr>`;
}

function renderError(message) {
  if (errorContainer) {
    errorContainer.innerHTML = `<div class="alert alert-danger">${escapeHtml(message)}</div>`;
  }
  if (tableBody) {
    tableBody.innerHTML = "";
  }
}

function renderAgentsTable(list) {
  if (!tableBody) return;

  if (!list.length) {
    tableBody.innerHTML = `
      <tr>
        <td colspan="3" class="text-center text-muted p-4">
          No group agents found.
        </td>
      </tr>`;
    return;
  }

  const canManage = canManageAgents();
  tableBody.innerHTML = "";

  list.forEach((agent) => {
    const tr = document.createElement("tr");
    const displayName = truncateName(agent.display_name || agent.displayName || agent.name || "");
    const description = escapeHtml(agent.description || "No description available.");

    let actionsHtml = "<span class=\"text-muted small\">—</span>";
    if (canManage) {
      actionsHtml = `
        <button type="button" class="btn btn-sm btn-outline-secondary me-1 edit-group-agent-btn" data-agent-id="${escapeHtml(agent.id || agent.name || "")}">
          <i class="bi bi-pencil"></i>
        </button>
        <button type="button" class="btn btn-sm btn-outline-danger delete-group-agent-btn" data-agent-id="${escapeHtml(agent.id || agent.name || "")}">
          <i class="bi bi-trash"></i>
        </button>`;
    }

    tr.innerHTML = `
      <td><strong title="${escapeHtml(agent.display_name || agent.displayName || agent.name || "")}">${escapeHtml(displayName)}</strong></td>
      <td class="text-muted small">${description}</td>
      <td>${actionsHtml}</td>`;

    tableBody.appendChild(tr);
  });
}

function filterAgents(term) {
  if (!term) {
    filteredAgents = agents.slice();
  } else {
    const needle = term.toLowerCase();
    filteredAgents = agents.filter((agent) => {
      const name = (agent.display_name || agent.displayName || agent.name || "").toLowerCase();
      const description = (agent.description || "").toLowerCase();
      return name.includes(needle) || description.includes(needle);
    });
  }
  renderAgentsTable(filteredAgents);
}

function overrideAgentStepper(stepper) {
  stepper.loadAvailableActions = async function loadGroupActions() {
    const container = document.getElementById("agent-actions-container");
    const emptyMessage = document.getElementById("agent-no-actions-message");
    if (!container) return;

    try {
      container.innerHTML = `
        <div class="col-12 text-center">
          <div class="spinner-border" role="status">
            <span class="visually-hidden">Loading…</span>
          </div>
          <p class="mt-2">Loading available group actions…</p>
        </div>`;

      const response = await fetch("/api/group/plugins");
      const payload = await response.json().catch(() => ({ actions: [] }));
      if (!response.ok) {
        throw new Error(payload?.error || response.statusText || "Failed to load actions");
      }

      const actions = Array.isArray(payload.actions) ? payload.actions : [];
      const normalized = actions.map((action) => ({
        ...action,
        display_name: action.display_name || action.displayName || action.name || "",
        description: action.description || "",
        is_global: Boolean(action.is_global)
      }));

      normalized.sort((a, b) => {
        const nameA = (a.display_name || a.name || "").toLowerCase();
        const nameB = (b.display_name || b.name || "").toLowerCase();
        return nameA.localeCompare(nameB);
      });

      container.innerHTML = "";

      if (!normalized.length) {
        container.style.display = "none";
        if (emptyMessage) emptyMessage.classList.remove("d-none");
        return;
      }

      container.style.display = "";
      if (emptyMessage) emptyMessage.classList.add("d-none");

      normalized.forEach((action) => {
        const card = this.createActionCard(action);
        container.appendChild(card);
      });

      this.initializeActionSearch(normalized);

      if (this.actionsToSelect && Array.isArray(this.actionsToSelect)) {
        this.setSelectedActions(this.actionsToSelect);
        this.actionsToSelect = null;
      }
    } catch (error) {
      console.error("Error loading group actions:", error);
      container.innerHTML = `
        <div class="col-12">
          <div class="alert alert-warning">Unable to load group actions. ${escapeHtml(error.message || "")}</div>
        </div>`;
    }
  };

  stepper.savePersonalAgent = async function saveGroupAgent(agentData) {
    const payload = { ...agentData };
    const isEdit = this.isEditMode && this.originalAgent && (this.originalAgent.id || this.originalAgent.name);

    if (!isEdit || !payload.id) {
      payload.id = payload.id || crypto.randomUUID();
    }

    const agentId = encodeURIComponent(payload.id || "");
    const url = isEdit ? `/api/group/agents/${agentId}` : "/api/group/agents";
    const method = isEdit ? "PATCH" : "POST";

    const response = await fetch(url, {
      method,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });

    let body = null;
    try {
      body = await response.json();
    } catch (parseError) {
      body = null;
    }

    if (!response.ok) {
      const message = body?.error || `Failed to ${isEdit ? "update" : "create"} group agent`;
      throw new Error(message);
    }

    this.handleSaveSuccess();
    if (typeof window.fetchGroupAgents === "function") {
      await window.fetchGroupAgents();
    }
  };

  return stepper;
}

function getAgentStepper() {
  if (!agentStepper) {
    agentStepper = overrideAgentStepper(new AgentModalStepper(false));
    window.agentModalStepper = agentStepper;
  }
  return agentStepper;
}

async function openAgentModal(agent = null) {
  if (!canManageAgents()) {
    showToast("You do not have permission to manage group agents.", "warning");
    return;
  }

  try {
    const stepper = getAgentStepper();
    await stepper.showModal(agent);
    agentsCommon.setupApimToggle(
      document.getElementById("agent-enable-apim"),
      document.getElementById("agent-apim-fields"),
      document.getElementById("agent-gpt-fields"),
      () => agentsCommon.loadGlobalModelsForModal({
        endpoint: "/api/user/agent/settings",
        agent,
        globalModelSelect: document.getElementById("agent-global-model-select"),
        isGlobal: false,
        customConnectionCheck: agentsCommon.shouldEnableCustomConnection,
        deploymentFieldIds: { gpt: "agent-gpt-deployment", apim: "agent-apim-deployment" }
      })
    );
  } catch (error) {
    console.error("Error opening group agent modal:", error);
    showToast(error.message || "Unable to open agent modal.", "danger");
  }
}

async function deleteGroupAgent(agentId) {
  if (!canManageAgents()) {
    showToast("You do not have permission to delete group agents.", "warning");
    return;
  }

  if (!agentId) return;
  if (!confirm("Delete this group agent?")) return;

  try {
    const response = await fetch(`/api/group/agents/${encodeURIComponent(agentId)}`, {
      method: "DELETE"
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(payload?.error || "Failed to delete group agent");
    }
    showToast("Group agent deleted successfully.", "success");
    await fetchGroupAgents();
  } catch (error) {
    console.error("Error deleting group agent:", error);
    showToast(error.message || "Unable to delete group agent.", "danger");
  }
}

async function fetchGroupAgents() {
  if (!tableBody) return;

  if (!currentContext?.activeGroupId) {
    renderNoGroupSelected();
    return;
  }

  renderLoading();

  try {
    const response = await fetch("/api/group/agents");
    const payload = await response.json().catch(() => ({ agents: [] }));
    if (!response.ok) {
      throw new Error(payload?.error || response.statusText || "Failed to load group agents");
    }

    agents = Array.isArray(payload.agents) ? payload.agents : [];
    const searchTerm = searchInput?.value?.trim() || "";
    filterAgents(searchTerm);
  } catch (error) {
    console.error("Error loading group agents:", error);
    renderError(error.message || "Unable to load group agents.");
  }
}

function handleTableClick(event) {
  const editBtn = event.target.closest(".edit-group-agent-btn");
  if (editBtn) {
    const agentId = editBtn.dataset.agentId;
    const agent = agents.find((item) => item.id === agentId || item.name === agentId);
    openAgentModal(agent || null);
    return;
  }

  const deleteBtn = event.target.closest(".delete-group-agent-btn");
  if (deleteBtn) {
    const agentId = deleteBtn.dataset.agentId;
    deleteGroupAgent(agentId);
  }
}

function bindEventHandlers() {
  if (searchInput) {
    searchInput.addEventListener("input", (event) => {
      filterAgents(event.target.value.trim());
    });
  }

  if (createButton) {
    createButton.addEventListener("click", () => openAgentModal());
  }

  if (tableBody) {
    tableBody.addEventListener("click", handleTableClick);
  }

  window.addEventListener("groupWorkspace:context-changed", (event) => {
    currentContext = event.detail || currentContext;
    updatePermissionUI();
  });
}

function initialize() {
  updatePermissionUI();
  bindEventHandlers();

  if (document.getElementById("group-agents-tab-btn")?.classList.contains("active")) {
    fetchGroupAgents();
  }
}

if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", initialize);
} else {
  initialize();
}

window.fetchGroupAgents = fetchGroupAgents;
