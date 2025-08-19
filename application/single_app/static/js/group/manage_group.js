// manage_group.js

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
      alert("Please select a member.");
      return;
    }

    $.ajax({
      url: `/api/groups/${groupId}/transferOwnership`,
      method: "PATCH",
      contentType: "application/json",
      data: JSON.stringify({ newOwnerId }),
      success: function (resp) {
        alert("Ownership transferred successfully.");
        window.location.reload();
      },
      error: function (err) {
        console.error(err);
        if (err.responseJSON && err.responseJSON.error) {
          alert("Error: " + err.responseJSON.error);
        } else {
          alert("Failed to transfer ownership.");
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

    $("#groupInfoContainer").html(`
      <h4>${group.name}</h4>
      <p>${group.description || ""}</p>
      <p>
        <strong>Owner Name:</strong> ${ownerName}<br/>
        <strong>Owner Email:</strong> ${ownerEmail}
      </p>
    `);

    const admins = group.admins || [];
    const docManagers = group.documentManagers || [];

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
    } else {
      $("#leaveGroupContainer").show();
    }

    if (currentUserRole === "Admin" || currentUserRole === "Owner") {
      $("#addMemberBtn").show();
      $("#pendingRequestsSection").show();

      loadPendingRequests();
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
      rows += `
      <tr>
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
  }).fail(function (err) {
    console.error(err);
    $("#membersTable tbody").html(
      "<tr><td colspan='3' class='text-danger'>Failed to load members</td></tr>"
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
