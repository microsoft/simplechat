// static/js/public/manage_public_workspace.js

// Global variables injected via the Jinja template
const workspaceId = window.workspaceId;
const userId = window.userId;

let currentUserRole = null;

$(document).ready(function () {
  // Initial load: workspace info, then members & pending requests
  loadWorkspaceInfo(function () {
    loadMembers();
  });

  // Initialize color picker
  initializeColorPicker();

  // Load stats when stats tab is shown
  $('#stats-tab').on('shown.bs.tab', function () {
    loadWorkspaceStats();
  });

  // Activity timeline pagination
  $('input[name="activityLimit"]').on('change', function() {
    const limit = parseInt($(this).val());
    loadActivityTimeline(limit);
  });

  // Edit workspace form (Owner only)
  $("#editWorkspaceForm").on("submit", function (e) {
    e.preventDefault();
    updateWorkspaceInfo();
  });

  // Delete workspace (Owner only)
  $("#deleteWorkspaceBtn").on("click", function () {
    // First check if any documents/prompts exist
    $.get(`/api/public_workspaces/${workspaceId}/fileCount`)
      .done(function (res) {
        const count = res.fileCount || 0;
        if (count > 0) {
          $("#deleteWorkspaceWarningBody").html(`
            <p>This workspace has <strong>${count}</strong> document(s) or prompt(s).</p>
            <p>Please remove them before deleting the workspace.</p>
          `);
          $("#deleteWorkspaceWarningModal").modal("show");
        } else {
          if (!confirm("Permanently delete this public workspace?")) return;
          $.ajax({
            url: `/api/public_workspaces/${workspaceId}`,
            method: "DELETE",
            success: function () {
              alert("Workspace deleted.");
              window.location.href = "/my_public_workspaces";
            },
            error: function (jq) {
              const err = jq.responseJSON?.error || jq.statusText;
              alert("Failed to delete workspace: " + err);
            }
          });
        }
      })
      .fail(function () {
        alert("Unable to verify workspace contents.");
      });
  });

  // Transfer ownership (Owner only)
  $("#transferOwnershipBtn").on("click", function () {
    $.get(`/api/public_workspaces/${workspaceId}/members`)
      .done(function (members) {
        let options = "";
        members.forEach(m => {
          if (m.role !== "Owner") {
            options += `<option value="${m.userId}">${m.displayName} (${m.email})</option>`;
          }
        });
        $("#newOwnerSelect").html(options);
        $("#transferOwnershipModal").modal("show");
      })
      .fail(function () {
        alert("Failed to load members for transfer.");
      });
  });
  $("#transferOwnershipForm").on("submit", function (e) {
    e.preventDefault();
    const newOwnerId = $("#newOwnerSelect").val();
    if (!newOwnerId) {
      alert("Select a member to transfer ownership to.");
      return;
    }
    $.ajax({
      url: `/api/public_workspaces/${workspaceId}/transferOwnership`,
      method: "PATCH",
      contentType: "application/json",
      data: JSON.stringify({ newOwnerId }),
      success: function () {
        alert("Ownership transferred.");
        location.reload();
      },
      error: function (jq) {
        const err = jq.responseJSON?.error || jq.statusText;
        alert("Failed to transfer ownership: " + err);
      }
    });
  });

  // Add Member (Admin/Owner)
  $("#addMemberBtn").on("click", function () {
    $("#userSearchTerm").val("");
    $("#userSearchResultsTable tbody").empty();
    $("#newUserId").val("");
    $("#newUserDisplayName").val("");
    $("#newUserEmail").val("");
    $("#searchStatus").text("");
    $("#addMemberModal").modal("show");
  });
  $("#addMemberForm").on("submit", function (e) {
    e.preventDefault();
    addMemberDirectly();
  });

  // Change Role (Admin/Owner)
  $("#changeRoleForm").on("submit", function (e) {
    e.preventDefault();
    const memberId = $("#roleChangeUserId").val();
    const newRole  = $("#roleSelect").val();
    setRole(memberId, newRole);
  });

  // Member search/filter
  $("#memberSearchBtn").on("click", function () {
    const term = $("#memberSearchInput").val().trim();
    const role = $("#memberRoleFilter").val();
    loadMembers(term, role);
  });

  // Search users for adding
  $("#searchUsersBtn").on("click", function () {
    searchUsers();
  });
  $("#userSearchTerm").on("keydown", function (e) {
    if (e.key === "Enter") {
      e.preventDefault();
      searchUsers();
    }
  });

  // Approve / Reject requests (Admin/Owner)
  $("#pendingRequestsTable").on("click", ".approve-request-btn", function () {
    approveRequest($(this).data("id"));
  });
  $("#pendingRequestsTable").on("click", ".reject-request-btn", function () {
    rejectRequest($(this).data("id"));
  });

  // CSV Bulk Upload Events
  $("#addBulkMemberBtn").on("click", function () {
    $("#csvBulkUploadModal").modal("show");
  });

  $("#csvExampleBtn").on("click", downloadCsvExample);
  $("#csvConfigBtn").on("click", showCsvConfig);
  $("#csvFileInput").on("change", handleCsvFileSelect);
  $("#csvNextBtn").on("click", startCsvUpload);
  $("#csvDoneBtn").on("click", function () {
    resetCsvModal();
    loadMembers();
  });

  // Reset CSV modal when closed
  $("#csvBulkUploadModal").on("hidden.bs.modal", function () {
    resetCsvModal();
  });

  // Bulk Actions Events
  $("#selectAllMembers").on("change", function () {
    const isChecked = $(this).prop("checked");
    $(".member-checkbox").prop("checked", isChecked);
    updateBulkActionsBar();
  });

  $(document).on("change", ".member-checkbox", function () {
    updateBulkActionsBar();
    updateSelectAllCheckbox();
  });

  $("#clearSelectionBtn").on("click", function () {
    $(".member-checkbox").prop("checked", false);
    $("#selectAllMembers").prop("checked", false);
    updateBulkActionsBar();
  });

  $("#bulkAssignRoleBtn").on("click", function () {
    const selectedMembers = getSelectedMembers();
    if (selectedMembers.length === 0) {
      alert("Please select at least one member");
      return;
    }
    $("#bulkRoleCount").text(selectedMembers.length);
    $("#bulkAssignRoleModal").modal("show");
  });

  $("#bulkAssignRoleForm").on("submit", function (e) {
    e.preventDefault();
    bulkAssignRole();
  });

  $("#bulkRemoveMembersBtn").on("click", function () {
    const selectedMembers = getSelectedMembers();
    if (selectedMembers.length === 0) {
      alert("Please select at least one member");
      return;
    }
    
    // Populate the list of members to be removed
    let membersList = "<ul class='list-unstyled'>";
    selectedMembers.forEach(member => {
      membersList += `<li>• ${member.name} (${member.email})</li>`;
    });
    membersList += "</ul>";
    
    $("#bulkRemoveCount").text(selectedMembers.length);
    $("#bulkRemoveMembersList").html(membersList);
    $("#bulkRemoveMembersModal").modal("show");
  });

  $("#bulkRemoveMembersForm").on("submit", function (e) {
    e.preventDefault();
    bulkRemoveMembers();
  });
});


// --- API & Rendering Functions ---

// Load workspace metadata, determine user role, show/hide UI
function loadWorkspaceInfo(callback) {
  $.get(`/api/public_workspaces/${workspaceId}`)
    .done(function (ws) {
      // Update status alert
      updateWorkspaceStatusAlert(ws);
      const owner = ws.owner || {};
      const admins = ws.admins || [];
      const docMgrs = ws.documentManagers || [];

      // Update profile hero
      updateProfileHero(ws, owner);

      // Determine role
      if (userId === owner.userId) {
        currentUserRole = "Owner";
      } else if (admins.includes(userId)) {
        currentUserRole = "Admin";
      } else if (docMgrs.some(dm => dm.userId === userId)) {
        currentUserRole = "DocumentManager";
      }

      // Owner UI
      if (currentUserRole === "Owner") {
        $("#ownerActionsContainer").show();
        $("#editWorkspaceContainer").show();
        $("#editWorkspaceName").val(ws.name);
        $("#editWorkspaceDescription").val(ws.description);
        
        // Set selected color
        const color = ws.heroColor || '#0078d4';
        $("#selectedColor").val(color);
        updateHeroColor(color);
        $(`.color-option[data-color="${color}"]`).addClass('selected');
      }

      // Show member actions for non-owners
      if (currentUserRole !== "Owner" && currentUserRole) {
        $("#memberActionsContainer").show();
      }

      // Admin & Owner UI
      if (currentUserRole === "Owner" || currentUserRole === "Admin") {
        $("#addMemberBtn").show();
        $("#addBulkMemberBtn").show();
        $("#pendingRequestsSection").show();
        $("#activityTimelineSection").show();
        loadPendingRequests();
      }

      if (callback) callback();
    })
    .fail(function () {
      alert("Failed to load workspace info.");
    });
}

// Update workspace name/description
function updateWorkspaceInfo() {
  const data = {
    name: $("#editWorkspaceName").val().trim(),
    description: $("#editWorkspaceDescription").val().trim(),
    heroColor: $("#selectedColor").val()
  };
  $.ajax({
    url: `/api/public_workspaces/${workspaceId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify(data),
    success: function () {
      alert("Workspace updated.");
      loadWorkspaceInfo();
    },
    error: function (jq) {
      const err = jq.responseJSON?.error || jq.statusText;
      alert("Failed to update: " + err);
    }
  });
}

// Load members list
function loadMembers(searchTerm = "", roleFilter = "") {
  let url = `/api/public_workspaces/${workspaceId}/members`;
  const params = [];
  if (searchTerm) params.push(`search=${encodeURIComponent(searchTerm)}`);
  if (roleFilter)  params.push(`role=${encodeURIComponent(roleFilter)}`);
  if (params.length) url += "?" + params.join("&");

  $.get(url)
    .done(function (members) {
      const rows = members.map(m => {
        const isOwner = m.role === "Owner";
        const checkboxHtml = isOwner || (currentUserRole !== "Owner" && currentUserRole !== "Admin") 
          ? '<input type="checkbox" class="form-check-input" disabled>' 
          : `<input type="checkbox" class="form-check-input member-checkbox" 
                     data-user-id="${m.userId}" 
                     data-user-name="${m.displayName || '(no name)'}"
                     data-user-email="${m.email || ''}"
                     data-user-role="${m.role}">`;
        
        return `
          <tr>
            <td>${checkboxHtml}</td>
            <td>
              ${m.displayName || "(no name)"}<br>
              <small>${m.email || ""}</small>
            </td>
            <td>${m.role}</td>
            <td>${renderMemberActions(m)}</td>
          </tr>
        `;
      }).join("");
      $("#membersTable tbody").html(rows);
      
      // Reset selection UI
      $("#selectAllMembers").prop("checked", false);
      updateBulkActionsBar();
    })
    .fail(function () {
      $("#membersTable tbody").html(
        `<tr><td colspan="4" class="text-danger">Failed to load members.</td></tr>`
      );
    });
}

// Actions HTML for each member
function renderMemberActions(member) {
  if (currentUserRole === "Owner" || currentUserRole === "Admin") {
    if (member.role === "Owner") {
      return `<span class="text-muted">Workspace Owner</span>`;
    }
    return `
      <button class="btn btn-sm btn-danger me-1"
              onclick="removeMember('${member.userId}')">
        Remove
      </button>
      <button class="btn btn-sm btn-outline-secondary"
              data-bs-toggle="modal"
              data-bs-target="#changeRoleModal"
              onclick="openChangeRoleModal('${member.userId}', '${member.role}')">
        Change Role
      </button>
    `;
  }
  return "";
}

// Open change-role modal
function openChangeRoleModal(userId, currentRole) {
  $("#roleChangeUserId").val(userId);
  $("#roleSelect").val(currentRole);
}

// Set a new role for a member
function setRole(memberId, newRole) {
  $.ajax({
    url: `/api/public_workspaces/${workspaceId}/members/${memberId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify({ role: newRole }),
    success: function () {
      $("#changeRoleModal").modal("hide");
      loadMembers();
    },
    error: function () {
      alert("Failed to update role.");
    }
  });
}

// Remove a member
function removeMember(memberId) {
  if (!confirm("Remove this member?")) return;
  $.ajax({
    url: `/api/public_workspaces/${workspaceId}/members/${memberId}`,
    method: "DELETE",
    success: loadMembers,
    error: function () {
      alert("Failed to remove member.");
    }
  });
}

// Load pending document-manager requests
function loadPendingRequests() {
  $.get(`/api/public_workspaces/${workspaceId}/requests`)
    .done(function (requests) {
      const rows = requests.map(req => `
        <tr>
          <td>${req.displayName}</td>
          <td>${req.email}</td>
          <td>
            <button class="btn btn-sm btn-success approve-request-btn"
                    data-id="${req.userId}">Approve</button>
            <button class="btn btn-sm btn-danger reject-request-btn"
                    data-id="${req.userId}">Reject</button>
          </td>
        </tr>
      `).join("");
      $("#pendingRequestsTable tbody").html(rows);
    })
    .fail(function (jq) {
      if (jq.status === 403) {
        $("#pendingRequestsSection").hide();
      } else {
        alert("Failed to load pending requests.");
      }
    });
}

// Approve a document-manager request
function approveRequest(requestId) {
  $.ajax({
    url: `/api/public_workspaces/${workspaceId}/requests/${requestId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify({ action: "approve" }),
    success: function () {
      loadMembers();
      loadPendingRequests();
    },
    error: function () {
      alert("Failed to approve request.");
    }
  });
}

// Reject a document-manager request
function rejectRequest(requestId) {
  $.ajax({
    url: `/api/public_workspaces/${workspaceId}/requests/${requestId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify({ action: "reject" }),
    success: loadPendingRequests,
    error: function () {
      alert("Failed to reject request.");
    }
  });
}

// Search users for manual add
function searchUsers() {
  const term = $("#userSearchTerm").val().trim();
  if (!term) {
    alert("Enter a name or email to search.");
    return;
  }
  $("#searchStatus").text("Searching...");
  $("#searchUsersBtn").prop("disabled", true);

  $.get("/api/userSearch", { query: term })
    .done(renderUserSearchResults)
    .fail(function (jq) {
      const err = jq.responseJSON?.error || jq.statusText;
      alert("User search failed: " + err);
    })
    .always(function () {
      $("#searchStatus").text("");
      $("#searchUsersBtn").prop("disabled", false);
    });
}

// Render user-search results in add-member modal
function renderUserSearchResults(users) {
  let html = "";
  if (!users || !users.length) {
    html = `<tr><td colspan="3" class="text-center text-muted">No results.</td></tr>`;
  } else {
    users.forEach(u => {
      html += `
        <tr>
          <td>${u.displayName || "(no name)"}</td>
          <td>${u.email || ""}</td>
          <td>
            <button class="btn btn-sm btn-primary"
                    onclick="selectUserForAdd('${u.id}', '${u.displayName}', '${u.email}')">
              Select
            </button>
          </td>
        </tr>
      `;
    });
  }
  $("#userSearchResultsTable tbody").html(html);
}

// Populate manual-add fields from search result
function selectUserForAdd(id, name, email) {
  $("#newUserId").val(id);
  $("#newUserDisplayName").val(name);
  $("#newUserEmail").val(email);
}

// Add a new document-manager directly
function addMemberDirectly() {
  const uid = $("#newUserId").val().trim();
  const name = $("#newUserDisplayName").val().trim();
  const email= $("#newUserEmail").val().trim();
  if (!uid) {
    alert("Select or enter a valid user.");
    return;
  }

  $.ajax({
    url: `/api/public_workspaces/${workspaceId}/members`,
    method: "POST",
    contentType: "application/json",
    data: JSON.stringify({ userId: uid, displayName: name, email }),
    success: function () {
      $("#addMemberModal").modal("hide");
      loadMembers();
    },
    error: function () {
      alert("Failed to add member.");
    }
  });
}

// --- New Functions for Profile Hero and Stats ---

// Update profile hero section
function updateProfileHero(workspace, owner) {
  const initial = workspace.name ? workspace.name.charAt(0).toUpperCase() : 'W';
  $('#workspaceInitial').text(initial);
  $('#workspaceHeroName').text(workspace.name || 'Unnamed Workspace');
  $('#workspaceOwnerName').text(owner.displayName || 'Unknown');
  $('#workspaceOwnerEmail').text(owner.email || 'N/A');
  $('#workspaceHeroDescription').text(workspace.description || 'No description provided');
  
  // Apply hero color
  const color = workspace.heroColor || '#0078d4';
  updateHeroColor(color);
}

// Update hero color
function updateHeroColor(color) {
  const darker = adjustColorBrightness(color, -30);
  document.documentElement.style.setProperty('--hero-color', color);
  document.documentElement.style.setProperty('--hero-color-dark', darker);
}

// Adjust color brightness
function adjustColorBrightness(color, percent) {
  const num = parseInt(color.replace('#', ''), 16);
  const amt = Math.round(2.55 * percent);
  const R = (num >> 16) + amt;
  const G = (num >> 8 & 0x00FF) + amt;
  const B = (num & 0x0000FF) + amt;
  return '#' + (0x1000000 + (R < 255 ? R < 1 ? 0 : R : 255) * 0x10000 +
    (G < 255 ? G < 1 ? 0 : G : 255) * 0x100 +
    (B < 255 ? B < 1 ? 0 : B : 255))
    .toString(16).slice(1);
}

// Initialize color picker
function initializeColorPicker() {
  $('.color-option').on('click', function() {
    $('.color-option').removeClass('selected');
    $(this).addClass('selected');
    const color = $(this).data('color');
    $('#selectedColor').val(color);
    updateHeroColor(color);
  });
}

// Load workspace stats
let documentChart, storageChart, tokenChart;

function loadWorkspaceStats() {
  // Load stats data
  $.get(`/api/public_workspaces/${workspaceId}/stats`)
    .done(function(stats) {
      updateStatCards(stats);
      updateCharts(stats);
      // Load activity timeline if user has permission
      if (currentUserRole === "Owner" || currentUserRole === "Admin") {
        loadActivityTimeline(50);
      }
    })
    .fail(function() {
      console.error('Failed to load workspace stats');
      $('#stat-documents').text('N/A');
      $('#stat-storage').text('N/A');
      $('#stat-tokens').text('N/A');
      $('#stat-members').text('N/A');
    });
}

// Update stat cards
function updateStatCards(stats) {
  $('#stat-documents').text(stats.totalDocuments || 0);
  $('#stat-storage').text(formatBytes(stats.storageUsed || 0));
  $('#stat-tokens').text(formatNumber(stats.totalTokens || 0));
  $('#stat-members').text(stats.totalMembers || 0);
}

// Update charts
function updateCharts(stats) {
  // Document Activity Chart - Two bars for uploads and deletes
  const docCtx = document.getElementById('documentChart');
  if (docCtx) {
    if (documentChart) documentChart.destroy();
    documentChart = new Chart(docCtx, {
      type: 'bar',
      data: {
        labels: stats.documentActivity?.labels || [],
        datasets: [
          {
            label: 'Uploads',
            data: stats.documentActivity?.uploads || [],
            backgroundColor: 'rgba(13, 202, 240, 0.8)',
            borderColor: 'rgb(13, 202, 240)',
            borderWidth: 1
          },
          {
            label: 'Deletes',
            data: stats.documentActivity?.deletes || [],
            backgroundColor: 'rgba(220, 53, 69, 0.8)',
            borderColor: 'rgb(220, 53, 69)',
            borderWidth: 1
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { 
            display: true,
            position: 'top'
          }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: { precision: 0 }
          }
        }
      }
    });
  }

  // Storage Usage Chart (Doughnut) - AI Search and Blob Storage
  const storageCtx = document.getElementById('storageChart');
  if (storageCtx) {
    if (storageChart) storageChart.destroy();
    const aiSearch = stats.storage?.ai_search_size || 0;
    const blobStorage = stats.storage?.storage_account_size || 0;
    
    storageChart = new Chart(storageCtx, {
      type: 'doughnut',
      data: {
        labels: ['AI Search', 'Blob Storage'],
        datasets: [{
          data: [aiSearch, blobStorage],
          backgroundColor: [
            'rgb(13, 110, 253)',
            'rgb(23, 162, 184)'
          ],
          borderWidth: 2
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom' },
          tooltip: {
            callbacks: {
              label: function(context) {
                return context.label + ': ' + formatBytes(context.parsed);
              }
            }
          }
        }
      }
    });
  }

  // Token Usage Chart
  const tokenCtx = document.getElementById('tokenChart');
  if (tokenCtx) {
    if (tokenChart) tokenChart.destroy();
    tokenChart = new Chart(tokenCtx, {
      type: 'bar',
      data: {
        labels: stats.tokenUsage?.labels || [],
        datasets: [{
          label: 'Tokens Used',
          data: stats.tokenUsage?.data || [],
          backgroundColor: 'rgba(255, 193, 7, 0.7)',
          borderColor: 'rgb(255, 193, 7)',
          borderWidth: 1
        }]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
          legend: { display: false }
        },
        scales: {
          y: {
            beginAtZero: true,
            ticks: {
              callback: function(value) {
                return formatNumber(value);
              }
            }
          }
        }
      }
    });
  }
}

// Load activity timeline
function loadActivityTimeline(limit = 50) {
  $.get(`/api/public_workspaces/${workspaceId}/activity?limit=${limit}`)
    .done(function(activities) {
      if (!activities || activities.length === 0) {
        $('#activityTimeline').html('<p class="text-muted">No recent activity</p>');
        return;
      }
      
      const html = activities.map(activity => renderActivityItem(activity)).join('');
      $('#activityTimeline').html(html);
    })
    .fail(function(xhr) {
      if (xhr.status === 403) {
        $('#activityTimeline').html('<p class="text-danger">Access denied - Only workspace owners and admins can view activity timeline</p>');
      } else {
        $('#activityTimeline').html('<p class="text-danger">Failed to load activity</p>');
      }
    });
}

// Render activity item
function renderActivityItem(activity) {
  const icons = {
    'document_creation': 'file-earmark-arrow-up',
    'document_deletion': 'file-earmark-x',
    'token_usage': 'cpu',
    'user_login': 'box-arrow-in-right'
  };
  
  const colors = {
    'document_creation': 'success',
    'document_deletion': 'danger',
    'token_usage': 'primary',
    'user_login': 'info'
  };
  
  const activityType = activity.activity_type || 'unknown';
  const icon = icons[activityType] || 'circle';
  const color = colors[activityType] || 'secondary';
  const time = formatRelativeTime(activity.timestamp || activity.created_at);
  
  // Generate description based on activity type
  let description = '';
  let title = activityType.replace(/_/g, ' ').replace(/\b\w/g, l => l.toUpperCase());
  
  if (activityType === 'document_creation' && activity.document) {
    description = `File: ${activity.document.file_name || 'Unknown'}`;
  } else if (activityType === 'document_deletion' && activity.document_metadata) {
    description = `File: ${activity.document_metadata.file_name || 'Unknown'}`;
  } else if (activityType === 'token_usage' && activity.usage) {
    description = `Tokens: ${formatNumber(activity.usage.total_tokens || 0)}`;
  } else if (activityType === 'user_login') {
    description = 'User logged in';
  }
  
  const activityJson = JSON.stringify(activity);
  
  return `
    <div class="activity-item border p-3 rounded mb-2" data-activity='${activityJson.replace(/'/g, "&apos;")}' onclick="showRawActivity(this)" style="cursor: pointer;">
      <div class="d-flex align-items-start gap-3">
        <div class="activity-icon">
          <i class="bi bi-${icon} text-${color}" style="font-size: 1.5rem;"></i>
        </div>
        <div class="flex-grow-1">
          <div class="d-flex justify-content-between align-items-start mb-1">
            <h6 class="mb-0">${title}</h6>
            <small class="text-muted">${time}</small>
          </div>
          <p class="mb-0 text-muted small">${description}</p>
        </div>
      </div>
    </div>
  `;
}

// Format bytes
function formatBytes(bytes) {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return Math.round(bytes / Math.pow(k, i) * 100) / 100 + ' ' + sizes[i];
}

// Format number with commas
function formatNumber(num) {
  return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

// Show raw activity in modal
function showRawActivity(element) {
  try {
    const activityJson = element.getAttribute('data-activity');
    const activity = JSON.parse(activityJson);
    const modalBody = document.getElementById('rawActivityModalBody');
    modalBody.innerHTML = `<pre><code>${JSON.stringify(activity, null, 2)}</code></pre>`;
    $('#rawActivityModal').modal('show');
  } catch (error) {
    console.error('Error showing raw activity:', error);
  }
}

// Copy raw activity to clipboard
function copyRawActivityToClipboard() {
  const modalBody = document.getElementById('rawActivityModalBody');
  const text = modalBody.textContent;
  navigator.clipboard.writeText(text).then(() => {
    alert('Activity data copied to clipboard!');
  }).catch(err => {
    console.error('Failed to copy:', err);
  });
}

// Make functions globally available
window.showRawActivity = showRawActivity;
window.copyRawActivityToClipboard = copyRawActivityToClipboard;

// Format relative time
function formatRelativeTime(timestamp) {
  const now = new Date();
  const date = new Date(timestamp);
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  return date.toLocaleDateString();
}

// ============================================================================
// CSV Bulk Member Upload Functions
// ============================================================================

let csvParsedData = [];

function downloadCsvExample() {
  const csvContent = `userId,displayName,email,role
00000000-0000-0000-0000-000000000001,John Smith,john.smith@contoso.com,user
00000000-0000-0000-0000-000000000002,Jane Doe,jane.doe@contoso.com,admin
00000000-0000-0000-0000-000000000003,Bob Johnson,bob.johnson@contoso.com,document_manager`;
  
  const blob = new Blob([csvContent], { type: 'text/csv' });
  const url = window.URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = 'bulk_members_example.csv';
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  window.URL.revokeObjectURL(url);
}

function showCsvConfig() {
  const modal = new bootstrap.Modal(document.getElementById('csvFormatInfoModal'));
  modal.show();
}

function validateGuid(guid) {
  return ValidationUtils.validateGuid(guid);
}

function validateEmail(email) {
  const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
  return emailRegex.test(email);
}

function handleCsvFileSelect(event) {
  const file = event.target.files[0];
  if (!file) {
    $("#csvNextBtn").prop("disabled", true);
    $("#csvValidationResults").hide();
    $("#csvErrorDetails").hide();
    return;
  }

  const reader = new FileReader();
  reader.onload = function (e) {
    const text = e.target.result;
    const lines = text.split(/\r?\n/).filter(line => line.trim());

    $("#csvErrorDetails").hide();
    $("#csvValidationResults").hide();

    // Validate header
    if (lines.length < 2) {
      showCsvError("CSV must contain at least a header row and one data row");
      return;
    }

    const header = lines[0].toLowerCase().trim();
    if (header !== "userid,displayname,email,role") {
      showCsvError("Invalid header. Expected: userId,displayName,email,role");
      return;
    }

    // Validate row count
    const dataRows = lines.slice(1);
    if (dataRows.length > 1000) {
      showCsvError(`Too many rows. Maximum 1,000 members allowed (found ${dataRows.length})`);
      return;
    }

    // Parse and validate rows
    csvParsedData = [];
    const errors = [];
    const validRoles = ['user', 'admin', 'document_manager'];
    
    for (let i = 0; i < dataRows.length; i++) {
      const rowNum = i + 2; // +2 because header is row 1
      const row = dataRows[i].split(',');
      
      if (row.length !== 4) {
        errors.push(`Row ${rowNum}: Expected 4 columns, found ${row.length}`);
        continue;
      }

      const userId = row[0].trim();
      const displayName = row[1].trim();
      const email = row[2].trim();
      const role = row[3].trim().toLowerCase();

      if (!userId || !displayName || !email || !role) {
        errors.push(`Row ${rowNum}: All fields are required`);
        continue;
      }

      if (!validateGuid(userId)) {
        errors.push(`Row ${rowNum}: Invalid GUID format for userId`);
        continue;
      }

      if (!validateEmail(email)) {
        errors.push(`Row ${rowNum}: Invalid email format`);
        continue;
      }

      if (!validRoles.includes(role)) {
        errors.push(`Row ${rowNum}: Invalid role '${role}'. Must be: user, admin, or document_manager`);
        continue;
      }

      csvParsedData.push({ userId, displayName, email, role });
    }

    if (errors.length > 0) {
      showCsvError(`Found ${errors.length} validation error(s):\n` + errors.slice(0, 10).join('\n') + 
                   (errors.length > 10 ? `\n... and ${errors.length - 10} more` : ''));
      return;
    }

    // Show validation success
    const sampleRows = csvParsedData.slice(0, 3);
    $("#csvValidationDetails").html(`
      <p><strong>✓ Valid CSV file detected</strong></p>
      <p>Total members to add: <strong>${csvParsedData.length}</strong></p>
      <p>Sample data (first 3):</p>
      <ul class="mb-0">
        ${sampleRows.map(row => `<li>${row.displayName} (${row.email})</li>`).join('')}
      </ul>
    `);
    $("#csvValidationResults").show();
    $("#csvNextBtn").prop("disabled", false);
  };

  reader.readAsText(file);
}

function showCsvError(message) {
  $("#csvErrorList").html(`<pre class="mb-0">${escapeHtml(message)}</pre>`);
  $("#csvErrorDetails").show();
  $("#csvNextBtn").prop("disabled", true);
  csvParsedData = [];
}

function startCsvUpload() {
  if (csvParsedData.length === 0) {
    alert("No valid data to upload");
    return;
  }

  // Switch to stage 2
  $("#csvStage1").hide();
  $("#csvStage2").show();
  $("#csvNextBtn").hide();
  $("#csvCancelBtn").hide();
  $("#csvModalClose").hide();

  // Upload members
  uploadCsvMembers();
}

async function uploadCsvMembers() {
  let successCount = 0;
  let failedCount = 0;
  let skippedCount = 0;
  const failures = [];

  for (let i = 0; i < csvParsedData.length; i++) {
    const member = csvParsedData[i];
    const progress = Math.round(((i + 1) / csvParsedData.length) * 100);
    
    updateCsvProgress(progress, `Processing ${i + 1} of ${csvParsedData.length}: ${member.displayName}`);

    try {
      const response = await fetch(`/api/public_workspaces/${workspaceId}/members`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          userId: member.userId,
          displayName: member.displayName,
          email: member.email,
          role: member.role
        })
      });

      const data = await response.json();
      
      if (response.ok && data.success) {
        successCount++;
      } else if (data.error && data.error.includes('already a member')) {
        skippedCount++;
      } else {
        failedCount++;
        failures.push(`${member.displayName}: ${data.error || 'Unknown error'}`);
      }
    } catch (error) {
      failedCount++;
      failures.push(`${member.displayName}: ${error.message}`);
    }
  }

  // Show summary
  showCsvSummary(successCount, failedCount, skippedCount, failures);
}

function updateCsvProgress(percentage, statusText) {
  $("#csvProgressBar").css("width", percentage + "%");
  $("#csvProgressBar").attr("aria-valuenow", percentage);
  $("#csvProgressText").text(percentage + "%");
  $("#csvStatusText").text(statusText);
}

function showCsvSummary(successCount, failedCount, skippedCount, failures) {
  $("#csvStage2").hide();
  $("#csvStage3").show();
  $("#csvDoneBtn").show();

  let summaryHtml = `
    <p><strong>Upload Summary:</strong></p>
    <ul>
      <li>✅ Successfully added: <strong>${successCount}</strong></li>
      <li>⏭️ Skipped (already members): <strong>${skippedCount}</strong></li>
      <li>❌ Failed: <strong>${failedCount}</strong></li>
    </ul>
  `;

  if (failures.length > 0) {
    summaryHtml += `
      <hr>
      <p><strong>Failed Members:</strong></p>
      <ul class="text-danger">
        ${failures.slice(0, 10).map(f => `<li>${escapeHtml(f)}</li>`).join('')}
        ${failures.length > 10 ? `<li><em>... and ${failures.length - 10} more</em></li>` : ''}
      </ul>
    `;
  }

  $("#csvSummary").html(summaryHtml);
}

function resetCsvModal() {
  // Reset to stage 1
  $("#csvStage1").show();
  $("#csvStage2").hide();
  $("#csvStage3").hide();
  $("#csvNextBtn").show();
  $("#csvNextBtn").prop("disabled", true);
  $("#csvCancelBtn").show();
  $("#csvDoneBtn").hide();
  $("#csvModalClose").show();
  $("#csvValidationResults").hide();
  $("#csvErrorDetails").hide();
  $("#csvFileInput").val('');
  csvParsedData = [];
  
  // Reset progress
  updateCsvProgress(0, 'Ready');
}

// ============================================================================
// Bulk Member Actions Functions
// ============================================================================

function getSelectedMembers() {
  const selected = [];
  $(".member-checkbox:checked").each(function () {
    selected.push({
      userId: $(this).data("user-id"),
      name: $(this).data("user-name"),
      email: $(this).data("user-email"),
      role: $(this).data("user-role")
    });
  });
  return selected;
}

function updateBulkActionsBar() {
  const selectedCount = $(".member-checkbox:checked").length;
  if (selectedCount > 0) {
    $("#selectedCount").text(selectedCount);
    $("#bulkActionsBar").show();
  } else {
    $("#bulkActionsBar").hide();
  }
}

function updateSelectAllCheckbox() {
  const totalCheckboxes = $(".member-checkbox").length;
  const checkedCheckboxes = $(".member-checkbox:checked").length;
  
  if (totalCheckboxes > 0 && checkedCheckboxes === totalCheckboxes) {
    $("#selectAllMembers").prop("checked", true);
    $("#selectAllMembers").prop("indeterminate", false);
  } else if (checkedCheckboxes > 0) {
    $("#selectAllMembers").prop("checked", false);
    $("#selectAllMembers").prop("indeterminate", true);
  } else {
    $("#selectAllMembers").prop("checked", false);
    $("#selectAllMembers").prop("indeterminate", false);
  }
}

async function bulkAssignRole() {
  const selectedMembers = getSelectedMembers();
  const newRole = $("#bulkRoleSelect").val();
  
  if (selectedMembers.length === 0) {
    alert("No members selected");
    return;
  }

  // Close modal and show progress
  $("#bulkAssignRoleModal").modal("hide");
  
  let successCount = 0;
  let failedCount = 0;
  const failures = [];

  for (let i = 0; i < selectedMembers.length; i++) {
    const member = selectedMembers[i];
    
    try {
      const response = await fetch(`/api/public_workspaces/${workspaceId}/members/${member.userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole })
      });

      const data = await response.json();
      
      if (response.ok && data.success) {
        successCount++;
      } else {
        failedCount++;
        failures.push(`${member.name}: ${data.error || 'Unknown error'}`);
      }
    } catch (error) {
      failedCount++;
      failures.push(`${member.name}: ${error.message}`);
    }
  }

  // Show summary
  let message = `Role assignment complete:\n✅ Success: ${successCount}\n❌ Failed: ${failedCount}`;
  if (failures.length > 0) {
    message += "\n\nFailed members:\n" + failures.slice(0, 5).join("\n");
    if (failures.length > 5) {
      message += `\n... and ${failures.length - 5} more`;
    }
  }
  alert(message);

  // Reload members and clear selection
  loadMembers();
}

async function bulkRemoveMembers() {
  const selectedMembers = getSelectedMembers();
  
  if (selectedMembers.length === 0) {
    alert("No members selected");
    return;
  }

  // Close modal
  $("#bulkRemoveMembersModal").modal("hide");
  
  let successCount = 0;
  let failedCount = 0;
  const failures = [];

  for (let i = 0; i < selectedMembers.length; i++) {
    const member = selectedMembers[i];
    
    try {
      const response = await fetch(`/api/public_workspaces/${workspaceId}/members/${member.userId}`, {
        method: 'DELETE'
      });

      const data = await response.json();
      
      if (response.ok && data.success) {
        successCount++;
      } else {
        failedCount++;
        failures.push(`${member.name}: ${data.error || 'Unknown error'}`);
      }
    } catch (error) {
      failedCount++;
      failures.push(`${member.name}: ${error.message}`);
    }
  }

  // Show summary
  let message = `Member removal complete:\n✅ Success: ${successCount}\n❌ Failed: ${failedCount}`;
  if (failures.length > 0) {
    message += "\n\nFailed removals:\n" + failures.slice(0, 5).join("\n");
    if (failures.length > 5) {
      message += `\n... and ${failures.length - 5} more`;
    }
  }
  alert(message);

  // Reload members and clear selection
  loadMembers();
}
