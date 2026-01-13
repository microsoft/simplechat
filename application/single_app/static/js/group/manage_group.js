// manage_group.js
import { showToast } from "../chat/chat-toast.js";

let currentUserRole = null;

$(document).ready(function () {
  loadGroupInfo(function () {
    loadMembers();
  });

  $("#leaveGroupBtn").on("click", function () {
    leaveGroup();
  });

  $("#editGroupForm").on("submit", function (e) {
    e.preventDefault();
    updateGroupInfo();
  });

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

  $("#changeRoleForm").on("submit", function (e) {
    e.preventDefault();
    const memberUserId = $("#roleChangeUserId").val();
    const newRole = $("#roleSelect").val();
    setRole(memberUserId, newRole);
  });

  $("#memberSearchBtn").on("click", function () {
    const searchTerm = $("#memberSearchInput").val().trim();
    const roleFilter = $("#memberRoleFilter").val().trim();
    loadMembers(searchTerm, roleFilter);
  });

  loadMembers("", "");

  $("#searchUsersBtn").on("click", function () {
    searchUsers();
  });

  $("#userSearchTerm").on("keydown", function (e) {
    if (e.key === "Enter" || e.keyCode === 13) {
      e.preventDefault(); // prevent form submission
      searchUsers(); // fire the search
    }
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

  // Activity timeline pagination
  $('input[name="activityLimit"]').on('change', function() {
    const limit = parseInt($(this).val());
    loadActivityTimeline(limit);
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

  $("#transferOwnershipBtn").on("click", function () {
    $.get(`/api/groups/${groupId}/members`, function (members) {
      let options = "";
      members.forEach((m) => {
        if (m.role === "Owner") return;

        options += `<option value="${m.userId}">${m.displayName} (${m.email})</option>`;
      });

      $("#newOwnerSelect").html(options);
      $("#transferOwnershipModal").modal("show");
    });
  });

  $("#transferOwnershipForm").on("submit", function (e) {
    e.preventDefault();
    const newOwnerId = $("#newOwnerSelect").val();
    if (!newOwnerId) {
      showToast("Please select a member.", "warning");
      return;
    }

    $.ajax({
      url: `/api/groups/${groupId}/transferOwnership`,
      method: "PATCH",
      contentType: "application/json",
      data: JSON.stringify({ newOwnerId }),
      success: function (resp) {
        $("#transferOwnershipModal").modal("hide");
        showToast("Ownership transferred successfully.", "success");
        setTimeout(function() {
          window.location.reload();
        }, 1000);
      },
      error: function (err) {
        console.error(err);
        $("#transferOwnershipModal").modal("hide");
        if (err.responseJSON && err.responseJSON.error) {
          showToast("Error: " + err.responseJSON.error, "danger");
        } else {
          showToast("Failed to transfer ownership.", "danger");
        }
      },
    });
  });

  $("#deleteGroupBtn").on("click", function () {
    $.get(`/api/groups/${groupId}/fileCount`, function (res) {
      const fileCount = res.fileCount || 0;
      if (fileCount > 0) {
        $("#deleteGroupWarningBody").html(`
      <p>This group has <strong>${fileCount}</strong> document(s).</p>
      <p>You must remove or delete these documents before the group can be deleted.</p>
    `);
        $("#deleteGroupWarningModal").modal("show");
        return;
      } else {
        if (
          !confirm("Are you sure you want to permanently delete this group?")
        ) {
          return;
        }
        $.ajax({
          url: `/api/groups/${groupId}`,
          method: "DELETE",
          success: function (resp) {
            alert("Group deleted successfully!");
            window.location.href = "/my_groups";
          },
          error: function (err) {
            console.error(err);
            if (err.responseJSON && err.responseJSON.error) {
              alert("Error: " + err.responseJSON.error);
            } else {
              alert("Failed to delete group.");
            }
          },
        });
      }
    }).fail(function (err) {
      console.error(err);
      alert("Unable to check file count. Cannot proceed with deletion.");
    });
  });
});

function loadGroupInfo(doneCallback) {
  $.get(`/api/groups/${groupId}`, function (group) {
    const ownerName = group.owner?.displayName || "N/A";
    const ownerEmail = group.owner?.email || "N/A";

    // Update hero section
    const initial = group.name ? group.name.charAt(0).toUpperCase() : 'G';
    $('#groupInitial').text(initial);
    $('#groupHeroName').text(group.name);
    $('#groupOwnerName').text(ownerName);
    $('#groupOwnerEmail').text(ownerEmail);
    $('#groupHeroDescription').text(group.description || 'No description provided');

    // Update group status alert if not active
    updateGroupStatusAlert(group.status || 'active');

    const admins = group.admins || [];
    const docManagers = group.documentManagers || [];
    const groupStatus = group.status || 'active';
    const isGroupEditable = (groupStatus === 'active' || groupStatus === 'upload_disabled');
    const isGroupLocked = (groupStatus === 'locked' || groupStatus === 'inactive');

    if (userId === group.owner?.id) {
      currentUserRole = "Owner";
    } else if (admins.includes(userId)) {
      currentUserRole = "Admin";
    } else if (docManagers.includes(userId)) {
      currentUserRole = "DocumentManager";
    } else {
      currentUserRole = "User";
    }

    if (currentUserRole === "Owner") {
      $("#editGroupContainer").show();
      $("#editGroupName").val(group.name);
      $("#editGroupDescription").val(group.description);
      $("#ownerActionsContainer").show();
      
      // Disable editing for locked/inactive groups
      if (isGroupLocked) {
        $("#editGroupName").prop('readonly', true);
        $("#editGroupDescription").prop('readonly', true);
        $("#editGroupForm button[type='submit']").hide();
      } else {
        $("#editGroupName").prop('readonly', false);
        $("#editGroupDescription").prop('readonly', false);
        $("#editGroupForm button[type='submit']").show();
      }
    } else {
      $("#leaveGroupContainer").show();
    }

    if (currentUserRole === "Admin" || currentUserRole === "Owner") {
      // Show/hide member management buttons based on group status
      if (isGroupLocked) {
        $("#addMemberBtn").hide();
        $("#addBulkMemberBtn").hide();
      } else {
        $("#addMemberBtn").show();
        $("#addBulkMemberBtn").show();
      }
      
      $("#pendingRequestsSection").show();
      $("#activityTimelineSection").show();
      $("#stats-tab-item").show();

      loadPendingRequests();
      loadGroupStats();
      loadActivityTimeline(50);
    }

    if (typeof doneCallback === "function") {
      doneCallback();
    }
  }).fail(function (err) {
    console.error(err);
    alert("Failed to load group info.");
  });
}

function leaveGroup() {
  if (!confirm("Are you sure you want to leave this group?")) return;

  $.ajax({
    url: `/api/groups/${groupId}/members/${userId}`,
    method: "DELETE",
    success: function (resp) {
      alert("You have left the group.");
      window.location.href = "/my_groups";
    },
    error: function (err) {
      console.error(err);
      if (err.responseJSON && err.responseJSON.error) {
        alert("Error: " + err.responseJSON.error);
      } else {
        alert("Unable to leave group.");
      }
    },
  });
}

function updateGroupInfo() {
  const data = {
    name: $("#editGroupName").val(),
    description: $("#editGroupDescription").val(),
  };
  $.ajax({
    url: `/api/groups/${groupId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify(data),
    success: function () {
      alert("Group updated successfully!");
      loadGroupInfo();
    },
    error: function (err) {
      console.error(err);
      alert("Failed to update group info.");
    },
  });
}

function loadMembers(searchTerm, roleFilter) {
  let url = `/api/groups/${groupId}/members`;

  const params = [];
  if (searchTerm) {
    params.push(`search=${encodeURIComponent(searchTerm)}`);
  }
  if (roleFilter) {
    params.push(`role=${encodeURIComponent(roleFilter)}`);
  }
  if (params.length > 0) {
    url += "?" + params.join("&");
  }

  $.get(url, function (members) {
    let rows = "";
    members.forEach((m) => {
      const isOwner = m.role === "Owner";
      const checkboxHtml = isOwner || (currentUserRole !== "Owner" && currentUserRole !== "Admin") 
        ? '<input type="checkbox" class="form-check-input" disabled>' 
        : `<input type="checkbox" class="form-check-input member-checkbox" 
                   data-user-id="${m.userId}" 
                   data-user-name="${m.displayName || '(no name)'}"
                   data-user-email="${m.email || ''}"
                   data-user-role="${m.role}">`;
      
      rows += `
      <tr>
        <td>${checkboxHtml}</td>
        <td>
          ${m.displayName || "(no name)"}<br/>
          <small>${m.email || ""}</small>
        </td>
        <td>${m.role}</td>
        <td>${renderMemberActions(m)}</td>
      </tr>
    `;
    });
    $("#membersTable tbody").html(rows);
    
    // Reset selection UI
    $("#selectAllMembers").prop("checked", false);
    updateBulkActionsBar();
  }).fail(function (err) {
    console.error(err);
    $("#membersTable tbody").html(
      "<tr><td colspan='4' class='text-danger'>Failed to load members</td></tr>"
    );
  });
}

function renderMemberActions(member) {
  if (currentUserRole === "Owner" || currentUserRole === "Admin") {
    if (member.role === "Owner") {
      return `<span class="text-muted">Group Owner</span>`;
    } else {
      return `
        <button
          class="btn btn-sm btn-danger me-1"
          onclick="removeMember('${member.userId}')">
          Remove
        </button>
        <button
          type="button"
          class="btn btn-sm btn-outline-secondary"
          data-bs-toggle="modal"
          data-bs-target="#changeRoleModal"
          onclick="openChangeRoleModal('${member.userId}', '${member.role}')"
        >
          Change Role
        </button>
      `;
    }
  } else {
    return ``;
  }
}

function openChangeRoleModal(userId, currentRole) {
  $("#roleChangeUserId").val(userId);
  $("#roleSelect").val(currentRole);
}

function setRole(userId, newRole) {
  $.ajax({
    url: `/api/groups/${groupId}/members/${userId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify({ role: newRole }),
    success: function () {
      $("#changeRoleModal").modal("hide");
      loadMembers();
    },
    error: function (err) {
      console.error(err);
      alert("Failed to update role.");
    },
  });
}

function removeMember(userId) {
  if (!confirm("Are you sure you want to remove this member?")) return;
  $.ajax({
    url: `/api/groups/${groupId}/members/${userId}`,
    method: "DELETE",
    success: function () {
      loadMembers();
    },
    error: function (err) {
      console.error(err);
      alert("Failed to remove member.");
    },
  });
}

function loadPendingRequests() {
  $.get(`/api/groups/${groupId}/requests`, function (pending) {
    let rows = "";
    pending.forEach((u) => {
      rows += `
        <tr>
          <td>${u.displayName}</td>
          <td>${u.email}</td>
          <td>
            <button class="btn btn-sm btn-success" onclick="approveRequest('${u.userId}')">Approve</button>
            <button class="btn btn-sm btn-danger" onclick="rejectRequest('${u.userId}')">Reject</button>
          </td>
        </tr>
      `;
    });
    $("#pendingRequestsTable tbody").html(rows);
  }).fail(function (err) {
    if (err.status === 403) {
      $("#pendingRequestsSection").hide();
    } else {
      console.error(err);
    }
  });
}

function approveRequest(requestId) {
  $.ajax({
    url: `/api/groups/${groupId}/requests/${requestId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify({ action: "approve" }),
    success: function () {
      loadMembers();
      loadPendingRequests();
    },
    error: function (err) {
      console.error(err);
      alert("Failed to approve request.");
    },
  });
}

function rejectRequest(requestId) {
  $.ajax({
    url: `/api/groups/${groupId}/requests/${requestId}`,
    method: "PATCH",
    contentType: "application/json",
    data: JSON.stringify({ action: "reject" }),
    success: function () {
      loadPendingRequests();
    },
    error: function (err) {
      console.error(err);
      alert("Failed to reject request.");
    },
  });
}

function searchUsers() {
  const term = $("#userSearchTerm").val().trim();
  if (!term) {
    alert("Please enter a search term.");
    return;
  }

  // UI state
  $("#searchStatus").text("Searching...");
  $("#searchUsersBtn").prop("disabled", true);

  $.ajax({
    url: "/api/userSearch",
    method: "GET",
    data: { query: term },
    dataType: "json",
  })
    .done(function (results) {
      renderUserSearchResults(results);
    })
    .fail(function (jqXHR, textStatus, errorThrown) {
      console.error("User search error:", textStatus, errorThrown);

      if (jqXHR.status === 401) {
        // Session expired or no token → force re-login
        window.location.href = "/login";
      } else {
        const msg = jqXHR.responseJSON?.error
          ? jqXHR.responseJSON.error
          : "User search failed.";
        alert(msg);
      }
    })
    .always(function () {
      // Restore UI state
      $("#searchStatus").text("");
      $("#searchUsersBtn").prop("disabled", false);
    });
}

function renderUserSearchResults(users) {
  let html = "";
  if (!users || users.length === 0) {
    html = `
      <tr>
        <td colspan="3" class="text-muted text-center">No results found</td>
      </tr>
    `;
  } else {
    users.forEach((u) => {
      html += `
        <tr>
          <td>${u.displayName || "(no name)"}</td>
          <td>${u.email || ""}</td>
          <td>
            <button class="btn btn-sm btn-primary"
              onclick="selectUserForAdd('${u.id}', '${u.displayName}', '${
        u.email
      }')"
            >
              Select
            </button>
          </td>
        </tr>
      `;
    });
  }
  $("#userSearchResultsTable tbody").html(html);
}

function selectUserForAdd(uid, displayName, email) {
  $("#newUserId").val(uid);
  $("#newUserDisplayName").val(displayName);
  $("#newUserEmail").val(email);
}

function addMemberDirectly() {
  const userId = $("#newUserId").val().trim();
  const displayName = $("#newUserDisplayName").val().trim();
  const email = $("#newUserEmail").val().trim();

  if (!userId) {
    alert("Please select or enter a valid user ID.");
    return;
  }

  $.ajax({
    url: `/api/groups/${groupId}/members`,
    method: "POST",
    contentType: "application/json",
    data: JSON.stringify({ userId, displayName, email }),
    success: function () {
      $("#addMemberModal").modal("hide");
      loadMembers();
    },
    error: function (err) {
      console.error(err);
      alert("Failed to add member directly.");
    },
  });
}

// Function to update group status alert box
function updateGroupStatusAlert(status) {
  const alertBox = $("#group-status-alert");
  const contentDiv = $("#group-status-content");
  
  if (!status || status === 'active') {
    alertBox.addClass('d-none');
    alertBox.removeClass('alert-warning alert-info alert-danger');
    return;
  }
  
  const statusMessages = {
    'locked': {
      type: 'warning',
      icon: 'bi-lock-fill',
      title: '🔒 Locked (Read-Only)',
      message: 'Group is in read-only mode',
      details: [
        '❌ New document uploads',
        '❌ Document deletions',
        '❌ Creating, editing, or deleting prompts',
        '❌ Creating, editing, or deleting agents',
        '❌ Creating, editing, or deleting actions',
        '✅ Viewing existing documents',
        '✅ Chat and search with existing documents',
        '✅ Using existing prompts, agents, and actions'
      ]
    },
    'upload_disabled': {
      type: 'info',
      icon: 'bi-cloud-slash-fill',
      title: '📁 Upload Disabled',
      message: 'Restrict new content but allow other operations',
      details: [
        '❌ New document uploads',
        '✅ Document deletions (cleanup)',
        '✅ Full chat and search functionality',
        '✅ Creating, editing, and deleting prompts',
        '✅ Creating, editing, and deleting agents',
        '✅ Creating, editing, and deleting actions'
      ]
    },
    'inactive': {
      type: 'danger',
      icon: 'bi-exclamation-triangle-fill',
      title: '⭕ Inactive',
      message: 'Group is disabled',
      details: [
        '❌ ALL operations (uploads, chat, document access)',
        '❌ Creating, editing, or deleting prompts, agents, and actions',
        '✅ Only admin viewing of group information',
        'Use case: Decommissioned projects, suspended groups, compliance holds'
      ]
    }
  };
  
  const config = statusMessages[status];
  if (config) {
    alertBox.removeClass('d-none alert-warning alert-info alert-danger');
    alertBox.addClass(`alert-${config.type}`);
    
    const detailsList = config.details.map(d => `<li class="mb-1">${d}</li>`).join('');
    
    contentDiv.html(`
      <div class="d-flex align-items-start">
        <i class="bi ${config.icon} me-2 flex-shrink-0" style="font-size: 1.2rem;"></i>
        <div>
          <strong>${config.title}</strong> - ${config.message}
          <ul class="mb-0 mt-2 small">
            ${detailsList}
          </ul>
        </div>
      </div>
    `);
  } else {
    alertBox.addClass('d-none');
  }
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

// Stats and Charts Functions
let documentChart, storageChart, tokenChart;

function loadGroupStats() {
  $.get(`/api/groups/${groupId}/stats`)
    .done(function(data) {
      // Update stat cards
      $('#stat-documents').text(data.totalDocuments || 0);
      
      // Format storage
      const storageMB = Math.round(data.storageUsed / (1024 * 1024));
      $('#stat-storage').text(storageMB + ' MB');
      
      // Format tokens
      const tokensK = Math.round(data.totalTokens / 1000);
      $('#stat-tokens').text(tokensK + 'K');
      
      $('#stat-members').text(data.totalMembers || 0);

      // Create charts
      createDocumentChart(data.documentActivity);
      createStorageChart(data.storage);
      createTokenChart(data.tokenUsage);
    })
    .fail(function(xhr) {
      console.error('Failed to load group stats:', xhr);
      $('#stat-documents').text('Error');
      $('#stat-storage').text('Error');
      $('#stat-tokens').text('Error');
      $('#stat-members').text('Error');
    });
}

function createDocumentChart(activityData) {
  const ctx = document.getElementById('documentChart');
  if (!ctx) return;

  if (documentChart) {
    documentChart.destroy();
  }

  documentChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: activityData.labels,
      datasets: [
        {
          label: 'Uploads',
          data: activityData.uploads,
          backgroundColor: 'rgba(13, 202, 240, 0.8)',
          borderColor: 'rgba(13, 202, 240, 1)',
          borderWidth: 1
        },
        {
          label: 'Deletes',
          data: activityData.deletes,
          backgroundColor: 'rgba(220, 53, 69, 0.8)',
          borderColor: 'rgba(220, 53, 69, 1)',
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
          ticks: {
            stepSize: 1
          }
        }
      }
    }
  });
}

function createStorageChart(storageData) {
  const ctx = document.getElementById('storageChart');
  if (!ctx) return;

  if (storageChart) {
    storageChart.destroy();
  }

  const aiSearchMB = Math.round(storageData.ai_search_size / (1024 * 1024));
  const blobStorageMB = Math.round(storageData.storage_account_size / (1024 * 1024));

  storageChart = new Chart(ctx, {
    type: 'doughnut',
    data: {
      labels: ['AI Search', 'Blob Storage'],
      datasets: [{
        data: [aiSearchMB, blobStorageMB],
        backgroundColor: [
          'rgba(13, 110, 253, 0.8)',
          'rgba(13, 202, 240, 0.8)'
        ],
        borderColor: [
          'rgba(13, 110, 253, 1)',
          'rgba(13, 202, 240, 1)'
        ],
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: true,
          position: 'bottom'
        },
        tooltip: {
          callbacks: {
            label: function(context) {
              return context.label + ': ' + context.parsed + ' MB';
            }
          }
        }
      }
    }
  });
}

function createTokenChart(tokenData) {
  const ctx = document.getElementById('tokenChart');
  if (!ctx) return;

  if (tokenChart) {
    tokenChart.destroy();
  }

  tokenChart = new Chart(ctx, {
    type: 'bar',
    data: {
      labels: tokenData.labels,
      datasets: [{
        label: 'Tokens',
        data: tokenData.data,
        backgroundColor: 'rgba(255, 193, 7, 0.8)',
        borderColor: 'rgba(255, 193, 7, 1)',
        borderWidth: 1
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          display: false
        }
      },
      scales: {
        y: {
          beginAtZero: true
        }
      }
    }
  });
}

// Activity Timeline Functions
function loadActivityTimeline(limit = 50) {
  $.get(`/api/groups/${groupId}/activity?limit=${limit}`)
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
        $('#activityTimeline').html('<p class="text-danger">Access denied - Only group owners and admins can view activity timeline</p>');
      } else {
        $('#activityTimeline').html('<p class="text-danger">Failed to load activity</p>');
      }
    });
}

function renderActivityItem(activity) {
  const icons = {
    'document_creation': 'file-earmark-arrow-up',
    'document_deletion': 'file-earmark-x',
    'token_usage': 'cpu',
    'user_login': 'box-arrow-in-right',
    'conversation_creation': 'chat-dots',
    'conversation_deletion': 'chat-dots-fill'
  };
  
  const colors = {
    'document_creation': 'success',
    'document_deletion': 'danger',
    'token_usage': 'primary',
    'user_login': 'info',
    'conversation_creation': 'primary',
    'conversation_deletion': 'danger'
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
  } else if (activityType === 'conversation_creation') {
    description = 'New conversation started';
  } else if (activityType === 'conversation_deletion') {
    description = 'Conversation deleted';
  }
  
  const activityJson = JSON.stringify(activity);
  
  return `
    <div class="activity-item" data-activity='${activityJson.replace(/'/g, "&apos;")}' onclick="showRawActivity(this)">
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

function formatRelativeTime(timestamp) {
  if (!timestamp) return 'Unknown';
  
  const date = new Date(timestamp);
  const now = new Date();
  const diffMs = now - date;
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMs / 3600000);
  const diffDays = Math.floor(diffMs / 86400000);
  
  if (diffMins < 1) return 'Just now';
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;
  if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
  if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
  return `${Math.floor(diffDays / 365)}y ago`;
}

function formatNumber(num) {
  return num.toString().replace(/\B(?=(\d{3})+(?!\d))/g, ',');
}

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

function copyRawActivityToClipboard() {
  const modalBody = document.getElementById('rawActivityModalBody');
  const text = modalBody.textContent;
  
  navigator.clipboard.writeText(text).then(() => {
    showToast('Activity data copied to clipboard', 'success');
  }).catch(err => {
    console.error('Failed to copy:', err);
    showToast('Failed to copy to clipboard', 'danger');
  });
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
      const response = await fetch(`/api/groups/${groupId}/members`, {
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

function escapeHtml(text) {
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============================================================================
// Bulk Actions Functions
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
      const response = await fetch(`/api/groups/${groupId}/members/${member.userId}`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ role: newRole })
      });

      const data = await response.json();
      
      if (response.ok) {
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
      const response = await fetch(`/api/groups/${groupId}/members/${member.userId}`, {
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
