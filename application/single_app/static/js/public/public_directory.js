// static/js/public/public_directory.js

$(document).ready(function () {
  // DOM references
  const tableBody = $("#public-directory-table tbody");
  const paginationContainer = $("#directory-pagination-container");
  const pageSizeSelect = $("#directory-page-size-select");
  const searchInput = $("#directory-search-input");
  const searchBtn = $("#directory-search-btn");
  const clearBtn = $("#directory-clear-btn");
  const allVisibleBtn = $("#allVisibleBtn");
  const allHiddenBtn = $("#allHiddenBtn");
  const viewModal = new bootstrap.Modal(document.getElementById('viewWorkspaceModal'));

  // State
  let currentPage = 1;
  let pageSize = parseInt(pageSizeSelect.val(), 10);
  let currentSearchQuery = "";
  let allWorkspaces = [];
  let userSettings = {};

// --- Curated List Helpers ---
let currentLoadedList = null;
let curatedListDirty = false;

function getSavedLists() {
  if (!userSettings || !userSettings.publicDirectorySavedLists) return {};
  return userSettings.publicDirectorySavedLists;
}
function saveCurrentVisibleList(listName) {
  if (!userSettings) userSettings = {};
  if (!userSettings.publicDirectorySavedLists) userSettings.publicDirectorySavedLists = {};
  // Get all visible workspace IDs
  const visibleIds = allWorkspaces.filter(ws => getWorkspaceVisibility(ws.id)).map(ws => ws.id);
  userSettings.publicDirectorySavedLists[listName] = visibleIds;
  saveUserSettings();
  currentLoadedList = listName;
  curatedListDirty = false;
  updateCuratedListStatus();
}
function deleteVisibleList(listName) {
  if (!userSettings || !userSettings.publicDirectorySavedLists) return;
  delete userSettings.publicDirectorySavedLists[listName];
  saveUserSettings();
  if (currentLoadedList === listName) {
    currentLoadedList = null;
    curatedListDirty = false;
    updateCuratedListStatus();
  }
}
function applyVisibleList(listName) {
  const lists = getSavedLists();
  if (!lists[listName]) return;
  // Set all to hidden, then set only those in the list to visible
  allWorkspaces.forEach(ws => setWorkspaceVisibility(ws.id, false));
  lists[listName].forEach(id => setWorkspaceVisibility(id, true));
  currentLoadedList = listName;
  curatedListDirty = false;
  updateCuratedListStatus();
}
function refreshVisibleListDropdown() {
  const $select = $("#loadVisibleListSelect");
  const lists = getSavedLists();
  $select.empty();
  $select.append(`<option value=""></option>`);
  Object.keys(lists).forEach(name => {
    $select.append(`<option value="${escapeHtml(name)}">${escapeHtml(name)}</option>`);
  });
}
function updateCuratedListStatus() {
  const $status = $("#curatedListStatus");
  const $saveArea = $("#curatedListSaveArea");
  const $statusArea = $("#curatedListStatusArea");
  if (curatedListDirty || !currentLoadedList) {
    // Show save area, hide status badge
    $saveArea.removeClass("d-none");
    $statusArea.addClass("d-none");
    $status.text("No list loaded").removeClass("bg-warning text-dark").addClass("bg-secondary");
  } else {
    // Show status badge, hide save area
    $saveArea.addClass("d-none");
    $statusArea.removeClass("d-none");
    $status.text(currentLoadedList).removeClass("bg-warning text-dark").addClass("bg-secondary");
  }
  if (curatedListDirty && currentLoadedList) {
    $status.text("Unsaved").removeClass("bg-secondary").addClass("bg-warning text-dark");
  }
}
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

  // Load user settings for view/hide preferences with comprehensive error handling
  function loadUserSettings() {
    return $.get('/api/user/settings')
      .done(function(data) {
        try {
          userSettings = data && data.settings ? data.settings : {};
          // Initialize publicDirectorySettings if not exists
          if (!userSettings.publicDirectorySettings) {
            userSettings.publicDirectorySettings = {};
          }
        } catch (error) {
          console.error('Error processing user settings:', error);
          userSettings = { publicDirectorySettings: {} };
        }
      })
      .fail(function(jqXHR) {
        console.warn('Failed to load user settings:', jqXHR.responseJSON?.error || jqXHR.statusText);
        userSettings = { publicDirectorySettings: {} };
      })
      .always(function() {
        // Ensure userSettings is always initialized
        if (!userSettings) {
          console.warn('User settings could not be loaded, using defaults');
          userSettings = { publicDirectorySettings: {} };
        }
      });
  }

  // Save user settings
  function saveUserSettings() {
    // Only attempt to save if userSettings is properly initialized
    if (!userSettings) {
      console.warn('Cannot save user settings: userSettings not initialized');
      return;
    }
    
    $.ajax({
      url: '/api/user/settings',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ settings: userSettings }),
      error: function(jqXHR) {
        console.error('Failed to save user settings:', jqXHR.responseJSON?.error || jqXHR.statusText);
        // If settings API is not available, continue without saving (graceful degradation)
      }
    });
  }

  // Get workspace visibility setting
  function getWorkspaceVisibility(workspaceId) {
    // Ensure userSettings and publicDirectorySettings exist
    if (!userSettings || !userSettings.publicDirectorySettings) {
      return false; // default to hidden if settings not loaded yet
    }
    return userSettings.publicDirectorySettings[workspaceId] === true; // default to hidden
  }

  // Set workspace visibility setting
  function setWorkspaceVisibility(workspaceId, isVisible) {
    // Ensure userSettings and publicDirectorySettings exist
    if (!userSettings) {
      userSettings = { publicDirectorySettings: {} };
    }
    if (!userSettings.publicDirectorySettings) {
      userSettings.publicDirectorySettings = {};
    }
    userSettings.publicDirectorySettings[workspaceId] = isVisible;
    saveUserSettings();
  }

  // Fetch all public workspaces
  function fetchWorkspaces() {
    // Show loading placeholder
    tableBody.html(`
      <tr class="table-loading-row">
        <td colspan="4" class="text-center p-4 text-muted">
          <div class="spinner-border spinner-border-sm me-2" role="status"></div>
          Loading public workspaces...
        </td>
      </tr>
    `);
    paginationContainer.empty();

    currentSearchQuery = searchInput.val().trim();
    let url = "/api/public_workspaces/discover";
    if (currentSearchQuery) {
      url += "?search=" + encodeURIComponent(currentSearchQuery);
    }

    $.get(url)
      .done(function (data) {
        allWorkspaces = data || [];
        renderWorkspaces();
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

  // Render workspaces with pagination
  function renderWorkspaces() {
    tableBody.empty();
    
    if (!allWorkspaces.length) {
      if (currentSearchQuery) {
        tableBody.html(`
          <tr><td colspan="4" class="text-center p-4 text-muted">
            No workspaces found matching "${escapeHtml(currentSearchQuery)}".
          </td></tr>
        `);
      } else {
        tableBody.html(`
          <tr><td colspan="4" class="text-center p-4 text-muted">
            No public workspaces available.
          </td></tr>
        `);
      }
      renderPaginationControls(1, pageSize, 0);
      return;
    }

    // Paginate
    const totalCount = allWorkspaces.length;
    const offset = (currentPage - 1) * pageSize;
    const paginatedWorkspaces = allWorkspaces.slice(offset, offset + pageSize);

    // Render each workspace
    paginatedWorkspaces.forEach(renderWorkspaceRow);
    renderPaginationControls(currentPage, pageSize, totalCount);
  }

  // Render a single workspace row
  function renderWorkspaceRow(ws) {
    const isVisible = getWorkspaceVisibility(ws.id);
    
    const row = $("<tr></tr>").attr("id", `workspace-row-${ws.id}`);

    // Expand/collapse button
    const expandCell = $("<td></td>");
    const expandBtn = $(`
      <button class="btn btn-sm btn-link p-0 expand-btn" data-id="${ws.id}">
        <i class="bi bi-chevron-right" id="arrow-icon-${ws.id}"></i>
      </button>
    `);
    expandCell.append(expandBtn);
    row.append(expandCell);

    // Name
    const nameCell = $("<td></td>")
      .attr("title", ws.name)
      .text(ws.name);
    row.append(nameCell);

    // Description
    const descCell = $("<td></td>")
      .attr("title", ws.description || "")
      .text(ws.description || "No description");
    row.append(descCell);

    // Actions
    const actionsCell = $("<td></td>");
    const actionButtons = $('<div class="action-buttons"></div>');

    // View/Hide visibility button
    const visibilityBtn = $(`
      <button class="visibility-btn ${isVisible ? 'visible' : 'hidden'}"
              data-id="${ws.id}"
              title="${isVisible ? 'Visible - Click to hide' : 'Hidden - Click to show'}"
              aria-label="${isVisible ? 'Hide workspace' : 'Show workspace'}">
        <i class="bi ${isVisible ? 'bi-eye' : 'bi-eye-slash'}"></i>
      </button>
    `);
    actionButtons.append(visibilityBtn);

    // Chat button
    const chatBtn = $(`
      <button class="btn btn-sm btn-primary chat-btn" data-id="${ws.id}">
        <i class="bi bi-chat-dots"></i> Chat
      </button>
    `);
    actionButtons.append(chatBtn);

    actionsCell.append(actionButtons);
    row.append(actionsCell);

    tableBody.append(row);

    // Add hidden details row
    const detailsRow = $(`
      <tr class="details-row" id="details-row-${ws.id}" style="display: none;">
        <td colspan="4">
          <div class="details-content">
            <div class="details-grid">
              <div class="detail-item">
                <div class="detail-label">Owner</div>
                <div class="detail-value" id="owner-${ws.id}">Loading...</div>
              </div>
              <div class="detail-item">
                <div class="detail-label">Number of Files</div>
                <div class="detail-value" id="files-${ws.id}">Loading...</div>
              </div>
              <div class="detail-item">
                <div class="detail-label">Number of Prompts</div>
                <div class="detail-value" id="prompts-${ws.id}">Loading...</div>
              </div>
            </div>
            <div class="mt-2">
              <button class="btn btn-primary btn-sm view-workspace-btn" data-id="${ws.id}">
                Goto Public Workspace
              </button>
            </div>
          </div>
        </td>
      </tr>
    `);
    tableBody.append(detailsRow);
  }

  // Toggle workspace details
  function toggleWorkspaceDetails(workspaceId) {
    const detailsRow = $(`#details-row-${workspaceId}`);
    const arrowIcon = $(`#arrow-icon-${workspaceId}`);
    
    if (detailsRow.is(':visible')) {
      detailsRow.hide();
      arrowIcon.removeClass('bi-chevron-down').addClass('bi-chevron-right');
    } else {
      detailsRow.show();
      arrowIcon.removeClass('bi-chevron-right').addClass('bi-chevron-down');
      loadWorkspaceDetails(workspaceId);
    }
  }

  // Load detailed workspace information
  function loadWorkspaceDetails(workspaceId) {
    // Load workspace details
    $.get(`/api/public_workspaces/${workspaceId}`)
      .done(function(workspace) {
        const ownerName = workspace.owner?.displayName || workspace.owner?.email || 'Unknown';
        $(`#owner-${workspaceId}`).text(ownerName);
      })
      .fail(function() {
        $(`#owner-${workspaceId}`).text('Unable to load');
      });

    // Load file count
    $.get(`/api/public_workspaces/${workspaceId}/fileCount`)
      .done(function(data) {
        $(`#files-${workspaceId}`).text(data.fileCount || 0);
      })
      .fail(function() {
        $(`#files-${workspaceId}`).text('Unable to load');
      });

    // Load prompt count
    $.get(`/api/public_workspaces/${workspaceId}/promptCount`)
      .done(function(data) {
        $(`#prompts-${workspaceId}`).text(data.promptCount || 0);
      })
      .fail(function() {
        $(`#prompts-${workspaceId}`).text('Unable to load');
      });
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
          renderWorkspaces();
        });
      } else if (active) {
        li.attr("aria-current", "page");
      }
      li.append(a);
      return li;
    }

    // Previous
    ul.append(pageItem(page - 1, "«", page <= 1, false));

    // Page numbers
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

  // Event handlers
  
  // Expand/collapse details
  tableBody.on("click", ".expand-btn", function() {
    const workspaceId = $(this).data("id");
    toggleWorkspaceDetails(workspaceId);
  });

  // Visibility button click
  tableBody.on("click", ".visibility-btn", function() {
    const workspaceId = $(this).data("id");
    const currentlyVisible = $(this).hasClass('visible');
    const newVisibility = !currentlyVisible;
    
    // Update button appearance, icon, and tooltip
    const icon = $(this).find('i');
    if (newVisibility) {
      $(this).removeClass('hidden').addClass('visible');
      $(this).attr('title', 'Visible - Click to hide');
      $(this).attr('aria-label', 'Hide workspace');
      icon.removeClass('bi-eye-slash').addClass('bi-eye');
    } else {
      $(this).removeClass('visible').addClass('hidden');
      $(this).attr('title', 'Hidden - Click to show');
      $(this).attr('aria-label', 'Show workspace');
      icon.removeClass('bi-eye').addClass('bi-eye-slash');
    }
    
    setWorkspaceVisibility(workspaceId, newVisibility);
    // Mark curated list as dirty if a list was loaded
    if (currentLoadedList) {
      curatedListDirty = true;
      updateCuratedListStatus();
    }
  });

  // Chat button
  tableBody.on("click", ".chat-btn", function() {
    const workspaceId = $(this).data("id");
    // Set only this workspace as visible, all others hidden
    if (!userSettings || !userSettings.publicDirectorySettings) {
      userSettings = { publicDirectorySettings: {} };
    }
    // Hide all, show only selected
    Object.keys(userSettings.publicDirectorySettings).forEach(function(key) {
      userSettings.publicDirectorySettings[key] = false;
    });
    userSettings.publicDirectorySettings[workspaceId] = true;
    // Save settings, then redirect
    $.ajax({
      url: '/api/user/settings',
      method: 'POST',
      contentType: 'application/json',
      data: JSON.stringify({ settings: userSettings }),
      success: function() {
        // Mark curated list as dirty if a list was loaded
        if (currentLoadedList) {
          curatedListDirty = true;
          updateCuratedListStatus();
        }
        // Redirect to chat with params to open search and select public scope
        window.location.href = `/chats?workspace=${workspaceId}&openSearch=1&scope=public`;
      },
      error: function() {
        // Mark curated list as dirty if a list was loaded
        if (currentLoadedList) {
          curatedListDirty = true;
          updateCuratedListStatus();
        }
        // Even if saving fails, proceed to chat page
        window.location.href = `/chats?workspace=${workspaceId}&openSearch=1&scope=public`;
      }
    });
  });

  // View workspace button
  tableBody.on("click", ".view-workspace-btn", function() {
    const workspaceId = $(this).data("id");
    window.location.href = `/public_workspaces?workspace=${workspaceId}`;
  });

  // Search functionality
  searchBtn.on("click", function() {
    currentPage = 1;
    fetchWorkspaces();
  });
  // Mark curated list as dirty if a list was loaded
  if (currentLoadedList) {
    curatedListDirty = true;
    updateCuratedListStatus();
  }

  searchInput.on("keypress", function(e) {
    if (e.which === 13) {
      e.preventDefault();
      currentPage = 1;
      fetchWorkspaces();
    }
  });

  clearBtn.on("click", function() {
    searchInput.val("");
    currentPage = 1;
    fetchWorkspaces();
  });
  // Mark curated list as dirty if a list was loaded
  if (currentLoadedList) {
    curatedListDirty = true;
    updateCuratedListStatus();
  }

  // Page size change
  pageSizeSelect.on("change", function() {
    pageSize = parseInt($(this).val(), 10);
    currentPage = 1;
    renderWorkspaces();
  });

  // Bulk action: All Visible
  allVisibleBtn.on("click", function() {
    allWorkspaces.forEach(function(ws) {
      setWorkspaceVisibility(ws.id, true);
      const btn = $(`.visibility-btn[data-id="${ws.id}"]`);
      const icon = btn.find('i');
      btn.removeClass('hidden').addClass('visible');
      btn.attr('title', 'Visible - Click to hide');
      btn.attr('aria-label', 'Hide workspace');
      icon.removeClass('bi-eye-slash').addClass('bi-eye');
    });
  });

  // Bulk action: All Hidden
  allHiddenBtn.on("click", function() {
    allWorkspaces.forEach(function(ws) {
      setWorkspaceVisibility(ws.id, false);
      const btn = $(`.visibility-btn[data-id="${ws.id}"]`);
      const icon = btn.find('i');
      btn.removeClass('visible').addClass('hidden');
      btn.attr('title', 'Hidden - Click to show');
      btn.attr('aria-label', 'Show workspace');
      icon.removeClass('bi-eye').addClass('bi-eye-slash');
    });
  });

  // Chat with Visible button
  $("#chatWithVisibleBtn").on("click", function() {
    // Go to chat page, enable search, select public scope (use currently visible workspaces)
    window.location.href = "/chats?openSearch=1&scope=public";
  });

  // Chat with All button
  $("#chatWithAllBtn").on("click", function() {
    // Set all workspaces to visible, then go to chat page
    allWorkspaces.forEach(function(ws) {
      setWorkspaceVisibility(ws.id, true);
      const btn = $(`.visibility-btn[data-id="${ws.id}"]`);
      const icon = btn.find('i');
      btn.removeClass('hidden').addClass('visible');
      btn.attr('title', 'Visible - Click to hide');
      btn.attr('aria-label', 'Hide workspace');
      icon.removeClass('bi-eye-slash').addClass('bi-eye');
    });
    // Give a short delay to ensure settings are saved before redirect
    setTimeout(function() {
      window.location.href = "/chats?openSearch=1&scope=public";
    }, 200);
  });

  // Save current visible set as a curated list
  $("#saveVisibleListBtn").on("click", function() {
    const listName = $("#saveListName").val().trim();
    if (!listName) {
      alert("Please enter a name for your list.");
      return;
    }
    saveCurrentVisibleList(listName);
    refreshVisibleListDropdown();
    $("#saveListName").val("");
    alert("List saved!");
    updateCuratedListStatus();
  });

  // Load curated list
  $("#loadVisibleListBtn").on("click", function() {
    const listName = $("#loadVisibleListSelect").val();
    if (!listName) {
      alert("Please select a list to load.");
      return;
    }
    applyVisibleList(listName);
    // Update UI to reflect new visibility
    allWorkspaces.forEach(function(ws) {
      const btn = $(`.visibility-btn[data-id="${ws.id}"]`);
      const icon = btn.find('i');
      if (getWorkspaceVisibility(ws.id)) {
        btn.removeClass('hidden').addClass('visible');
        btn.attr('title', 'Visible - Click to hide');
        btn.attr('aria-label', 'Hide workspace');
        icon.removeClass('bi-eye-slash').addClass('bi-eye');
      } else {
        btn.removeClass('visible').addClass('hidden');
        btn.attr('title', 'Hidden - Click to show');
        btn.attr('aria-label', 'Show workspace');
        icon.removeClass('bi-eye').addClass('bi-eye-slash');
      }
      updateCuratedListStatus();
    });
    // Show loaded list name
    updateCuratedListStatus();
  });

  // Delete curated list
  $("#deleteVisibleListBtn").on("click", function() {
    const listName = $("#loadVisibleListSelect").val();
    if (!listName) {
      alert("Please select a list to delete.");
      return;
    }
    if (confirm(`Delete list "${listName}"? This cannot be undone.`)) {
      deleteVisibleList(listName);
      refreshVisibleListDropdown();
      alert("List deleted.");
      updateCuratedListStatus();
    }
  });

  // Initialize - load user settings first, then fetch workspaces
  loadUserSettings().always(function() {
    // Settings are now loaded (or failed with defaults), safe to fetch workspaces
    fetchWorkspaces();
    refreshVisibleListDropdown();
  });
});