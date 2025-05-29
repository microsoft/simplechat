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
});


// --- API & Rendering Functions ---

// Load workspace metadata, determine user role, show/hide UI
function loadWorkspaceInfo(callback) {
  $.get(`/api/public_workspaces/${workspaceId}`)
    .done(function (ws) {
      const owner = ws.owner || {};
      const admins = ws.admins || [];
      const docMgrs = ws.documentManagers || [];

      // Header info
      $("#workspaceInfoContainer").html(`
        <h4>${ws.name}</h4>
        <p>${ws.description || ""}</p>
        <p><strong>Owner:</strong> ${owner.displayName} (${owner.email})</p>
      `);

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
      }

      // Admin & Owner UI
      if (currentUserRole === "Owner" || currentUserRole === "Admin") {
        $("#addMemberBtn").show();
        $("#pendingRequestsSection").show();
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
    description: $("#editWorkspaceDescription").val().trim()
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
        return `
          <tr>
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
    })
    .fail(function () {
      $("#membersTable tbody").html(
        `<tr><td colspan="3" class="text-danger">Failed to load members.</td></tr>`
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
