// static/js/public/my_public_workspaces.js

$(document).ready(function () {
  // Grab global active workspace ID (set via inline <script> in the template)
  const activeWorkspaceId = window.activeWorkspaceId || null;

  // DOM references
  const tableBody            = $("#my-public-workspaces-table tbody");
  const paginationContainer  = $("#pagination-container");
  const pageSizeSelect       = $("#page-size-select");
  const searchInput          = $("#searchQueryInput");
  const searchBtn            = $("#searchBtn");
  const clearSearchBtn       = $("#clearSearchBtn");
  const createModal          = window.canCreatePublicWorkspaces ? new bootstrap.Modal(document.getElementById('createPublicWorkspaceModal')) : null;
  const findModal            = new bootstrap.Modal(document.getElementById('findPublicWorkspaceModal'));

  // State
  let currentPage        = 1;
  let pageSize           = parseInt(pageSizeSelect.val(), 10);
  let currentSearchQuery = "";

  // Utility: escape HTML to avoid XSS
  function escapeHtml(unsafe) {
    if (!unsafe) return '';
    return unsafe
      .toString()
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#039;");
  }

  // Fetch and render the list of public workspaces
  function fetchWorkspaces() {
    // Show loading placeholder
    tableBody.html(`
      <tr class="table-loading-row">
        <td colspan="4" class="text-center p-4 text-muted">
          <div class="spinner-border spinner-border-sm me-2" role="status"></div>
          Loading…
        </td>
      </tr>
    `);
    paginationContainer.empty();

    currentSearchQuery = searchInput.val().trim();

    const params = new URLSearchParams({
      page: currentPage,
      page_size: pageSize
    });
    if (currentSearchQuery) {
      params.append("search", currentSearchQuery);
    }

    $.get(`/api/public_workspaces?${params.toString()}`)
      .done(function (data) {
        tableBody.empty();
        const workspaces = data.workspaces || [];
        if (workspaces.length) {
          workspaces.forEach(renderWorkspaceRow);
        } else if (currentSearchQuery) {
          tableBody.html(`
            <tr><td colspan="4" class="text-center p-4 text-muted">
              No workspaces found matching "${escapeHtml(currentSearchQuery)}".
            </td></tr>
          `);
        } else {
          tableBody.html(`
            <tr><td colspan="4" class="text-center p-4 text-muted">
              You don't have any public workspaces yet.<br>
              Use "Create New Public Workspace" or "Find Public Workspace" above.
            </td></tr>
          `);
        }
        renderPaginationControls(data.page, data.page_size, data.total_count);
      })
      .fail(function (jqXHR) {
        const err = jqXHR.responseJSON?.error || jqXHR.statusText;
        tableBody.html(`
          <tr><td colspan="4" class="text-center text-danger p-4">
            Error loading workspaces: ${escapeHtml(err)}
          </td></tr>
        `);
        renderPaginationControls(1, pageSize, 0);
      });
  }

  // Render a single workspace row
  function renderWorkspaceRow(ws) {
    const row = $("<tr></tr>");

    // Name
    row.append(
      $("<td></td>")
        .attr("title", ws.name)
        .text(ws.name)
    );

    // Role
    row.append(
      $("<td></td>").text(ws.userRole || "Document Manager")
    );

    // Active badge or Set Active button
    const activeCell = $("<td class='text-center'></td>");
    if (ws.id === activeWorkspaceId) {
      activeCell.append('<span class="badge bg-primary">Active</span>');
    } else {
      const btn = $("<button class='btn btn-sm btn-outline-secondary set-active-btn'>Set Active</button>")
        .attr("data-id", ws.id);
      activeCell.append(btn);
    }
    row.append(activeCell);

    // Manage button
    const actionsCell = $("<td class='text-center'></td>");
    const manageLink = $("<a class='btn btn-sm btn-secondary'></a>")
      .attr("href", `/public_workspaces/${ws.id}`)
      .html('<i class="bi bi-gear-fill"></i> Manage');
    actionsCell.append(manageLink);
    row.append(actionsCell);

    tableBody.append(row);
  }

  // Render pagination controls
  function renderPaginationControls(page, size, total) {
    paginationContainer.empty();
    const totalPages = Math.ceil(total / size);
    if (totalPages <= 1) return;

    const ul = $('<ul class="pagination pagination-sm mb-0"></ul>');

    function pageItem(p, text, disabled, active) {
      const li = $('<li class="page-item"></li>')
        .toggleClass("disabled", !!disabled)
        .toggleClass("active", !!active);
      const a = $('<a class="page-link" href="#"></a>').text(text);
      if (!disabled && !active) {
        a.on("click", function (e) {
          e.preventDefault();
          currentPage = p;
          fetchWorkspaces();
        });
      } else if (active) {
        li.attr("aria-current", "page");
      }
      li.append(a);
      return li;
    }

    // Previous
    ul.append(pageItem(page - 1, "«", page <= 1, false));

    // Page window
    const maxDisplay = 5;
    let start = 1, end = totalPages;
    if (totalPages > maxDisplay) {
      const half = Math.floor(maxDisplay / 2);
      start = page > half ? page - half : 1;
      end = start + maxDisplay - 1;
      if (end > totalPages) {
        end = totalPages;
        start = end - maxDisplay + 1;
      }
    }
    if (start > 1) {
      ul.append(pageItem(1, "1", false, false));
      if (start > 2) {
        ul.append('<li class="page-item disabled"><span class="page-link">…</span></li>');
      }
    }
    for (let p = start; p <= end; p++) {
      ul.append(pageItem(p, p, false, p === page));
    }
    if (end < totalPages) {
      if (end < totalPages - 1) {
        ul.append('<li class="page-item disabled"><span class="page-link">…</span></li>');
      }
      ul.append(pageItem(totalPages, totalPages, false, false));
    }

    // Next
    ul.append(pageItem(page + 1, "»", page >= totalPages, false));

    paginationContainer.append(ul);
  }

  // Set active public workspace
  function setActivePublicWorkspace(id, btn) {
    const origHtml = btn.html();
    btn.prop("disabled", true).html('<span class="spinner-border spinner-border-sm" role="status"></span>');

    $.ajax({
      url: "/api/public_workspaces/setActive",
      method: "PATCH",
      contentType: "application/json",
      data: JSON.stringify({ workspaceId: id }),
      success: fetchWorkspaces,
      error: function (jq) {
        const err = jq.responseJSON?.error || jq.statusText;
        alert("Failed to set active workspace: " + escapeHtml(err));
        btn.prop("disabled", false).html(origHtml);
      }
    });
  }

  // Handle "Create Public Workspace" form submit
  function handleCreateForm(e) {
    e.preventDefault();
    const name        = $("#publicWorkspaceName").val().trim();
    const description = $("#publicWorkspaceDescription").val().trim();
    if (!name) {
      alert("Name is required.");
      return;
    }
    const submitBtn = $("#createPublicWorkspaceSubmitBtn");
    const origText  = submitBtn.text();
    submitBtn.prop("disabled", true).html('<span class="spinner-border spinner-border-sm"></span> Creating…');

    $.ajax({
      url: "/api/public_workspaces",
      method: "POST",
      contentType: "application/json",
      data: JSON.stringify({ name, description }),
      success: function () {
        if (createModal) {
          createModal.hide();
        }
        $("#createPublicWorkspaceForm")[0].reset();
        fetchWorkspaces();
      },
      error: function (jq) {
        const err = jq.responseJSON?.error || jq.statusText;
        alert("Error creating workspace: " + escapeHtml(err));
      },
      complete: function () {
        submitBtn.prop("disabled", false).text(origText);
      }
    });
  }

  // Search all public workspaces (for the "Find" modal)
  function searchAllWorkspaces(term) {
    const resultsBody = $("#globalWorkspaceResultsTable tbody");
    resultsBody.html('<tr><td colspan="3" class="text-center"><div class="spinner-border spinner-border-sm"></div> Searching…</td></tr>');
    let url = "/api/public_workspaces/discover";
    if (term) url += "?search=" + encodeURIComponent(term);

    $.get(url)
      .done(renderGlobalWorkspaceResults)
      .fail(function (jq) {
        const err = jq.responseJSON?.error || jq.statusText;
        resultsBody.html('<tr><td colspan="3" class="text-center text-danger">' + escapeHtml(err) + '</td></tr>');
      });
  }

  // Render results in the "Find Public Workspace" modal
  function renderGlobalWorkspaceResults(workspaces) {
    const tbody = $("#globalWorkspaceResultsTable tbody").empty();
    if (!workspaces || !workspaces.length) {
      tbody.html('<tr><td colspan="3" class="text-center text-muted">No workspaces found.</td></tr>');
      return;
    }
    workspaces.forEach(ws => {
      const row = $("<tr></tr>");
      row.append($("<td></td>").text(ws.name));
      row.append($("<td></td>").text(ws.description || ""));
      const btn = $("<button class='btn btn-sm btn-primary join-request-btn'>Request Access</button>")
        .attr("data-id", ws.id);
      row.append($("<td></td>").append(btn));
      tbody.append(row);
    });
  }

  // Handle join request
  function requestToJoin(id, btn) {
    const origText = btn.text();
    btn.prop("disabled", true).html('<span class="spinner-border spinner-border-sm"></span> Sending…');

    $.ajax({
      url: `/api/public_workspaces/${encodeURIComponent(id)}/requests`,
      method: "POST",
      success: function () {
        alert("Request sent successfully!");
        btn.removeClass("btn-primary").addClass("btn-outline-secondary").text("Requested");
      },
      error: function (jq) {
        const err = jq.responseJSON?.error || jq.statusText;
        alert("Failed to send request: " + escapeHtml(err));
        btn.prop("disabled", false).text(origText);
      }
    });
  }

  // --- Event wiring ---

  // Active button in table
  tableBody.on("click", ".set-active-btn", function () {
    const id = $(this).attr("data-id");
    setActivePublicWorkspace(id, $(this));
  });

  // Create form (only if user has permission)
  if (window.canCreatePublicWorkspaces) {
    $("#createPublicWorkspaceForm").on("submit", handleCreateForm);
  }

  // Search / clear
  searchBtn.on("click", function () {
    currentPage = 1;
    fetchWorkspaces();
  });
  searchInput.on("keypress", function (e) {
    if (e.which === 13) {
      e.preventDefault();
      currentPage = 1;
      fetchWorkspaces();
    }
  });
  clearSearchBtn.on("click", function () {
    searchInput.val("");
    currentPage = 1;
    fetchWorkspaces();
  });

  // Page size change
  pageSizeSelect.on("change", function () {
    pageSize = parseInt($(this).val(), 10);
    currentPage = 1;
    fetchWorkspaces();
  });

  // Find modal search
  $("#globalWorkspaceSearchBtn").on("click", function () {
    const term = $("#globalWorkspaceSearchInput").val().trim();
    searchAllWorkspaces(term);
  });
  $("#globalWorkspaceSearchInput").on("keypress", function (e) {
    if (e.which === 13) {
      e.preventDefault();
      searchAllWorkspaces($(this).val().trim());
    }
  });

  // Reset find modal on show
  $("#findPublicWorkspaceModal").on("show.bs.modal", function () {
    $("#globalWorkspaceSearchInput").val("");
    $("#globalWorkspaceResultsTable tbody").html('<tr><td colspan="3" class="text-center text-muted">Enter a name and click Search.</td></tr>');
  });

  // Join request buttons
  $("#globalWorkspaceResultsTable").on("click", ".join-request-btn", function () {
    requestToJoin($(this).attr("data-id"), $(this));
  });

  // Initial fetch
  fetchWorkspaces();
});
