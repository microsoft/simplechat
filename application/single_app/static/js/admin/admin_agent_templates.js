// admin_agent_templates.js
// Admin UI logic for reviewing, approving, and deleting agent template submissions

import { showToast } from "../chat/chat-toast.js";

const panel = document.getElementById("agent-templates-admin-panel");
const tableBody = document.getElementById("agent-template-table-body");
const statusFilters = document.getElementById("agent-template-status-filters");
const disabledAlert = document.getElementById("agent-templates-disabled-alert");
const searchInput = document.getElementById("agent-template-search");
const paginationEl = document.getElementById("agent-template-pagination");
const paginationSummary = document.getElementById("agent-template-pagination-summary");
const paginationNav = document.getElementById("agent-template-pagination-nav");
const modalEl = document.getElementById("agentTemplateReviewModal");
const approveBtn = document.getElementById("agent-template-approve-btn");
const rejectBtn = document.getElementById("agent-template-reject-btn");
const deleteBtn = document.getElementById("agent-template-delete-btn");
const notesInput = document.getElementById("agent-template-review-notes");
const rejectReasonInput = document.getElementById("agent-template-reject-reason");
const errorAlert = document.getElementById("agent-template-review-error");
const statusBadge = document.getElementById("agent-template-review-status");
const helperEl = document.getElementById("agent-template-review-helper");
const descriptionEl = document.getElementById("agent-template-review-description");
const instructionsEl = document.getElementById("agent-template-review-instructions");
const actionsWrapper = document.getElementById("agent-template-review-actions-wrapper");
const actionsList = document.getElementById("agent-template-review-actions");
const settingsWrapper = document.getElementById("agent-template-review-settings-wrapper");
const settingsEl = document.getElementById("agent-template-review-settings");
const tagsContainer = document.getElementById("agent-template-review-tags");
const subtitleEl = document.getElementById("agent-template-review-subtitle");
const metaEl = document.getElementById("agent-template-review-meta");
const titleEl = document.getElementById("agentTemplateReviewModalLabel");

let currentFilter = "pending";
let templates = [];
let selectedTemplate = null;
let reviewModal = null;
let currentPage = 1;
let searchQuery = "";
const PAGE_SIZE = 10;

function init() {
  if (!panel) {
    return;
  }

  if (modalEl && window.bootstrap) {
    reviewModal = bootstrap.Modal.getOrCreateInstance(modalEl);
  }

  if (!window.appSettings?.enable_agent_template_gallery) {
    if (disabledAlert) disabledAlert.classList.remove("d-none");
    renderEmptyState("Template gallery is disabled.");
    return;
  }

  attachFilterHandlers();
  attachTableHandlers();
  attachSearchHandler();
  attachModalHandlers();
  loadTemplatesForFilter(currentFilter);
}

function attachFilterHandlers() {
  if (!statusFilters) {
    return;
  }
  statusFilters.addEventListener("click", (event) => {
    const button = event.target.closest("button[data-status]");
    if (!button) {
      return;
    }
    const { status } = button.dataset;
    if (!status || status === currentFilter) {
      return;
    }
    currentFilter = status;
    statusFilters.querySelectorAll("button").forEach((btn) => btn.classList.remove("active"));
    button.classList.add("active");
    currentPage = 1;
    loadTemplatesForFilter(currentFilter);
  });
}

function attachTableHandlers() {
  if (!tableBody) {
    return;
  }
  tableBody.addEventListener("click", (event) => {
    const reviewBtn = event.target.closest(".agent-template-review-btn");
    if (reviewBtn) {
      const templateId = reviewBtn.dataset.templateId;
      openReviewModal(templateId);
      return;
    }
    const deleteBtn = event.target.closest(".agent-template-inline-delete");
    if (deleteBtn) {
      const templateId = deleteBtn.dataset.templateId;
      confirmAndDelete(templateId);
    }
  });
}

function attachModalHandlers() {
  if (!approveBtn || !rejectBtn || !deleteBtn) {
    return;
  }

  approveBtn.addEventListener("click", () => handleApproval());
  rejectBtn.addEventListener("click", () => handleRejection());
  deleteBtn.addEventListener("click", () => {
    if (selectedTemplate?.id) {
      confirmAndDelete(selectedTemplate.id, true);
    }
  });
}

function attachSearchHandler() {
  if (!searchInput) {
    return;
  }
  searchInput.addEventListener("input", (event) => {
    searchQuery = event.target.value?.trim().toLowerCase() || "";
    currentPage = 1;
    renderTemplates();
  });
}

async function loadTemplatesForFilter(status) {
  renderLoadingRow();
  try {
    const query = status && status !== "all" ? `?status=${encodeURIComponent(status)}` : "?status=all";
    const response = await fetch(`/api/admin/agent-templates${query}`);
    if (!response.ok) {
      throw new Error("Failed to load templates.");
    }
    const data = await response.json();
    templates = data.templates || [];
    currentPage = 1;
    renderTemplates();
  } catch (error) {
    console.error("Error loading agent templates", error);
    renderEmptyState(error.message || "Unable to load templates.");
  }
}

function renderLoadingRow() {
  if (!tableBody) return;
  tableBody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">
    <div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>
    Loading templates...
  </td></tr>`;
  setSummaryMessage("Loading templates...");
  renderPaginationControls(0);
}

function renderEmptyState(message) {
  if (!tableBody) return;
  tableBody.innerHTML = `<tr><td colspan="5" class="text-center text-muted py-4">${message}</td></tr>`;
  setSummaryMessage(message);
  renderPaginationControls(0);
}

function renderTemplates() {
  if (!tableBody) {
    return;
  }
  const filtered = getFilteredTemplates();
  if (!filtered.length) {
    const emptyMessage = searchQuery ? "No templates match your search." : "No templates found for this filter.";
    renderEmptyState(emptyMessage);
    return;
  }

  const totalItems = filtered.length;
  const totalPages = Math.ceil(totalItems / PAGE_SIZE) || 1;
  if (currentPage > totalPages) {
    currentPage = totalPages;
  }
  const startIndex = (currentPage - 1) * PAGE_SIZE;
  const pageItems = filtered.slice(startIndex, startIndex + PAGE_SIZE);
  const endIndex = startIndex + pageItems.length;

  tableBody.innerHTML = "";
  pageItems.forEach((template) => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td>
        <div class="fw-semibold">${escapeHtml(template.title || template.display_name || "Template")}</div>
        <div class="text-muted small text-truncate" style="max-width: 320px;">${escapeHtml(template.helper_text || template.description || "")}</div>
      </td>
      <td>${renderStatusBadge(template.status)}</td>
      <td>
        <div class="fw-semibold">${escapeHtml(template.created_by_name || 'Unknown')}</div>
        <div class="text-muted small">${escapeHtml(template.created_by_email || '')}</div>
      </td>
      <td class="text-muted small">${formatDate(template.updated_at || template.created_at)}</td>
      <td class="text-end">
        <div class="btn-group btn-group-sm" role="group">
          <button type="button" class="btn btn-outline-primary agent-template-review-btn" data-template-id="${template.id}">
            View
          </button>
          <button type="button" class="btn btn-outline-danger agent-template-inline-delete" data-template-id="${template.id}">
            Delete
          </button>
        </div>
      </td>
    `;
    tableBody.appendChild(row);
  });

  setSummaryMessage(`Showing ${startIndex + 1}-${endIndex} of ${totalItems} (page ${currentPage} of ${totalPages})`);
  renderPaginationControls(totalPages);
}

function getFilteredTemplates() {
  if (!searchQuery) {
    return templates;
  }
  return templates.filter((template) => {
    return [
      template.title,
      template.display_name,
      template.created_by_name,
      template.created_by_email
    ].some((value) => value && value.toString().toLowerCase().includes(searchQuery));
  });
}

function renderStatusBadge(status) {
  const normalized = (status || "pending").toLowerCase();
  const variants = {
    approved: "success",
    rejected: "danger",
    archived: "secondary",
    pending: "warning",
  };
  const badgeClass = variants[normalized] || "secondary";
  return `<span class="badge bg-${badgeClass} text-uppercase">${normalized}</span>`;
}

function setSummaryMessage(message = "") {
  if (paginationSummary) {
    paginationSummary.textContent = message;
  }
}

function renderPaginationControls(totalPages) {
  if (!paginationEl) {
    return;
  }

  if (paginationNav) {
    if (totalPages <= 1) {
      paginationNav.classList.add("d-none");
    } else {
      paginationNav.classList.remove("d-none");
    }
  }

  if (totalPages <= 1) {
    paginationEl.innerHTML = "";
    return;
  }

  const maxButtons = 5;
  let startPage = Math.max(1, currentPage - Math.floor(maxButtons / 2));
  let endPage = startPage + maxButtons - 1;
  if (endPage > totalPages) {
    endPage = totalPages;
    startPage = Math.max(1, endPage - maxButtons + 1);
  }

  const fragment = document.createDocumentFragment();
  fragment.appendChild(createPageItem("Previous", currentPage - 1, currentPage === 1));

  for (let page = startPage; page <= endPage; page += 1) {
    fragment.appendChild(createPageItem(page, page, false, page === currentPage));
  }

  fragment.appendChild(createPageItem("Next", currentPage + 1, currentPage === totalPages));

  paginationEl.innerHTML = "";
  paginationEl.appendChild(fragment);
}

function createPageItem(label, targetPage, disabled, active = false) {
  const li = document.createElement("li");
  li.className = "page-item";
  if (disabled) li.classList.add("disabled");
  if (active) li.classList.add("active");

  const button = document.createElement("button");
  button.type = "button";
  button.className = "page-link";
  button.textContent = label.toString();
  button.disabled = disabled;
  button.addEventListener("click", () => {
    if (disabled || targetPage === currentPage) {
      return;
    }
    currentPage = Math.min(Math.max(targetPage, 1), Math.ceil(getFilteredTemplates().length / PAGE_SIZE) || 1);
    renderTemplates();
  });

  li.appendChild(button);
  return li;
}

function formatDate(value) {
  if (!value) {
    return "-";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return date.toLocaleString();
}

async function openReviewModal(templateId) {
  if (!templateId || !reviewModal) {
    return;
  }
  try {
    const response = await fetch(`/api/admin/agent-templates/${templateId}`);
    if (!response.ok) {
      throw new Error('Failed to load template.');
    }
    const data = await response.json();
    selectedTemplate = data.template;
    populateReviewModal(selectedTemplate);
    reviewModal.show();
  } catch (error) {
    console.error('Failed to open template modal', error);
    showToast(error.message || 'Unable to load template.', 'danger');
  }
}

function populateReviewModal(template) {
  if (!template) {
    return;
  }
  titleEl.textContent = template.title || template.display_name || 'Agent Template';
  helperEl.textContent = template.helper_text || template.description || '-';
  descriptionEl.textContent = template.description || '-';
  instructionsEl.textContent = template.instructions || '';
  notesInput.value = template.review_notes || '';
  rejectReasonInput.value = template.rejection_reason || '';
  updateStatusBadge(template.status);

  const submittedBy = template.created_by_name || 'Unknown submitter';
  const submittedAt = formatDate(template.created_at);
  subtitleEl.textContent = `Submitted by ${submittedBy}`;
  metaEl.textContent = `Updated ${formatDate(template.updated_at)}`;

  if (Array.isArray(template.actions_to_load) && template.actions_to_load.length) {
    actionsWrapper.classList.remove('d-none');
    actionsList.innerHTML = '';
    template.actions_to_load.forEach((action) => {
      const badge = document.createElement('span');
      badge.className = 'badge bg-info text-dark me-1 mb-1';
      badge.textContent = action;
      actionsList.appendChild(badge);
    });
  } else {
    actionsWrapper.classList.add('d-none');
    actionsList.innerHTML = '';
  }

  if (template.additional_settings) {
    settingsWrapper.classList.remove('d-none');
    settingsEl.textContent = template.additional_settings;
  } else {
    settingsWrapper.classList.add('d-none');
    settingsEl.textContent = '';
  }

  if (Array.isArray(template.tags) && template.tags.length) {
    tagsContainer.classList.remove('d-none');
    tagsContainer.innerHTML = '';
    template.tags.slice(0, 8).forEach((tag) => {
      const badge = document.createElement('span');
      badge.className = 'badge bg-secondary-subtle text-secondary-emphasis';
      badge.textContent = tag;
      tagsContainer.appendChild(badge);
    });
  } else {
    tagsContainer.classList.add('d-none');
    tagsContainer.innerHTML = '';
  }

  hideModalError();
}

function updateStatusBadge(status) {
  const normalized = (status || 'pending').toLowerCase();
  statusBadge.textContent = normalized;
  statusBadge.className = 'badge';
  statusBadge.classList.add(`bg-${{
    approved: 'success',
    rejected: 'danger',
    archived: 'secondary',
    pending: 'warning'
  }[normalized] || 'secondary'}`);
}

function hideModalError() {
  if (errorAlert) {
    errorAlert.classList.add('d-none');
    errorAlert.textContent = '';
  }
}

function showModalError(message) {
  if (!errorAlert) {
    showToast(message, 'danger');
    return;
  }
  errorAlert.classList.remove('d-none');
  errorAlert.textContent = message;
}

async function handleApproval() {
  if (!selectedTemplate?.id) {
    return;
  }
  await submitTemplateDecision(`/api/admin/agent-templates/${selectedTemplate.id}/approve`, {
    notes: notesInput.value?.trim() || undefined
  }, 'Template approved!');
}

async function handleRejection() {
  if (!selectedTemplate?.id) {
    return;
  }
  const reason = rejectReasonInput.value?.trim();
  if (!reason) {
    showModalError('A rejection reason is required.');
    rejectReasonInput.focus();
    return;
  }
  await submitTemplateDecision(`/api/admin/agent-templates/${selectedTemplate.id}/reject`, {
    reason,
    notes: notesInput.value?.trim() || undefined
  }, 'Template rejected.');
}

async function submitTemplateDecision(url, payload, successMessage) {
  try {
    setModalButtonsDisabled(true);
    const response = await fetch(url, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Failed to update template.');
    }
    showToast(successMessage, 'success');
    hideModalError();
    reviewModal?.hide();
    loadTemplatesForFilter(currentFilter);
  } catch (error) {
    console.error('Template decision failed', error);
    showModalError(error.message || 'Failed to update template.');
  } finally {
    setModalButtonsDisabled(false);
  }
}

function setModalButtonsDisabled(disabled) {
  [approveBtn, rejectBtn, deleteBtn].forEach((btn) => {
    if (btn) btn.disabled = disabled;
  });
}

async function confirmAndDelete(templateId, closeModal = false) {
  if (!templateId) {
    return;
  }
  if (!confirm('Delete this template? This action cannot be undone.')) {
    return;
  }
  try {
    const response = await fetch(`/api/admin/agent-templates/${templateId}`, {
      method: 'DELETE'
    });
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      throw new Error(data.error || 'Failed to delete template.');
    }
    showToast('Template deleted.', 'success');
    if (closeModal) {
      reviewModal?.hide();
    }
    loadTemplatesForFilter(currentFilter);
  } catch (error) {
    console.error('Failed to delete template', error);
    showToast(error.message || 'Failed to delete template.', 'danger');
  }
}

function escapeHtml(value) {
  const div = document.createElement('div');
  div.textContent = value || '';
  return div.innerHTML;
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', init);
} else {
  init();
}
