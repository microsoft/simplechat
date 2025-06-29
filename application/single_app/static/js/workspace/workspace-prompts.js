// static/js/workspace/workspace-prompts.js

import { escapeHtml } from "./workspace-utils.js";

// ------------- State Variables (Prompts Tab) -------------
let promptsCurrentPage = 1;
let promptsPageSize = 10;
let promptsSearchTerm = '';

// ------------- DOM Elements (Prompts Tab) -------------
const promptsTableBody = document.querySelector("#prompts-table tbody");
const promptModalEl = document.getElementById("promptModal") ? new bootstrap.Modal(document.getElementById("promptModal")) : null;
const promptForm = document.getElementById("prompt-form");
const promptIdEl = document.getElementById("prompt-id");
const promptNameEl = document.getElementById("prompt-name");
const promptContentEl = document.getElementById("prompt-content");
const createPromptBtn = document.getElementById("create-prompt-btn");
const promptSaveBtn = document.getElementById('prompt-save-btn');
// New elements
const promptsSearchInput = document.getElementById('prompts-search-input');
const promptsApplyFiltersBtn = document.getElementById('prompts-apply-filters-btn');
const promptsClearFiltersBtn = document.getElementById('prompts-clear-filters-btn');
const promptsPageSizeSelect = document.getElementById('prompts-page-size-select');
const promptsPaginationContainer = document.getElementById('prompts-pagination-container');

// Check if essential elements exist
if (!promptsTableBody || !promptModalEl || !promptForm || !promptIdEl || !promptNameEl || !promptContentEl || !createPromptBtn || !promptSaveBtn || !promptsSearchInput || !promptsApplyFiltersBtn || !promptsClearFiltersBtn || !promptsPageSizeSelect || !promptsPaginationContainer) {
    console.warn("Workspace Prompts Tab: One or more essential DOM elements not found. Script might not function correctly.");
}

let simplemde = null; // Declare outside to be accessible

// Initialize SimpleMDE
if (promptContentEl && typeof SimpleMDE !== 'undefined') {
    try {
        simplemde = new SimpleMDE({ element: promptContentEl, spellChecker: false });
    } catch (e) { console.error("Failed to initialize SimpleMDE:", e); }
} else if (!promptContentEl) { console.warn("Prompt content textarea not found, SimpleMDE not initialized."); }
else if (typeof SimpleMDE === 'undefined') { console.warn("SimpleMDE library not loaded."); }


// ------------- Prompt Functions -------------

function fetchUserPrompts() {
    if (!promptsTableBody || !promptsPaginationContainer) return;

    // Show loading state
    promptsTableBody.innerHTML = `
         <tr class="table-loading-row">
             <td colspan="2">
                 <div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>
                 Loading prompts...
             </td>
         </tr>`;
    promptsPaginationContainer.innerHTML = ''; // Clear pagination

    // Build query parameters
    const params = new URLSearchParams({
        page: promptsCurrentPage,
        page_size: promptsPageSize,
    });
    if (promptsSearchTerm) {
        params.append('search', promptsSearchTerm);
    }

    fetch(`/api/prompts?${params.toString()}`)
        .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
        .then(data => {
            promptsTableBody.innerHTML = ""; // Clear loading/existing rows
            if (!data.prompts || data.prompts.length === 0) {
                 promptsTableBody.innerHTML = `
                    <tr>
                        <td colspan="2" class="text-center p-4 text-muted">
                            ${promptsSearchTerm ? 'No prompts found matching your search.' : 'No prompts created yet.'}
                            ${promptsSearchTerm ? '<br><button class="btn btn-link btn-sm p-0" id="prompts-reset-filter-msg-btn">Clear search</button> to see all prompts.' : ''}
                         </td>
                     </tr>`;
                 // Add event listener for the reset button within the message
                 const resetButton = document.getElementById('prompts-reset-filter-msg-btn');
                 if (resetButton) {
                     resetButton.addEventListener('click', () => {
                         promptsClearFiltersBtn.click(); // Simulate clicking the main clear button
                     });
                 }
            } else {
                data.prompts.forEach(p => renderPromptRow(p));
            }
            // Render pagination controls using data from response
            renderPromptsPaginationControls(data.page, data.page_size, data.total_count);
        })
        .catch(err => {
            console.error("Error fetching prompts:", err);
            promptsTableBody.innerHTML = `<tr><td colspan="2" class="text-center text-danger p-3">Error loading prompts: ${escapeHtml(err.error || err.message || 'Unknown error')}</td></tr>`;
            renderPromptsPaginationControls(1, promptsPageSize, 0); // Show empty pagination on error
        });
}

function renderPromptRow(p) {
    if (!promptsTableBody) return;
     const tr = document.createElement("tr");
     tr.innerHTML = `
         <td title="${escapeHtml(p.name)}">${escapeHtml(p.name)}</td>
         <td>
            <button class="btn btn-sm btn-primary" onclick="window.onEditPrompt('${p.id}')" title="Edit Prompt">
                <i class="bi bi-pencil-fill"></i> Edit
            </button>
            <button class="btn btn-sm btn-danger ms-1" onclick="window.onDeletePrompt('${p.id}', event)" title="Delete Prompt">
                <i class="bi bi-trash-fill"></i> Delete
            </button>
         </td>
     `;
     promptsTableBody.appendChild(tr);
}


function renderPromptsPaginationControls(page, pageSize, totalCount) {
    if (!promptsPaginationContainer) return;
    promptsPaginationContainer.innerHTML = ""; // clear old
    const totalPages = Math.ceil(totalCount / pageSize);

    if (totalPages <= 1) return; // Don't show pagination if only one page

    // Previous Button
    const prevLi = document.createElement('li');
    prevLi.classList.add('page-item');
    if (page <= 1) prevLi.classList.add('disabled');
    const prevA = document.createElement('a');
    prevA.classList.add('page-link');
    prevA.href = '#';
    prevA.innerHTML = '«';
    prevA.addEventListener('click', (e) => {
        e.preventDefault();
        if (promptsCurrentPage > 1) {
            promptsCurrentPage -= 1;
            fetchUserPrompts(); // Fetch previous page of prompts
        }
    });
    prevLi.appendChild(prevA);

    // Next Button
    const nextLi = document.createElement('li');
    nextLi.classList.add('page-item');
    if (page >= totalPages) nextLi.classList.add('disabled');
    const nextA = document.createElement('a');
    nextA.classList.add('page-link');
    nextA.href = '#';
    nextA.innerHTML = '»';
    nextA.addEventListener('click', (e) => {
        e.preventDefault();
        if (promptsCurrentPage < totalPages) {
            promptsCurrentPage += 1;
            fetchUserPrompts(); // Fetch next page of prompts
        }
    });
    nextLi.appendChild(nextA);

    // Determine page numbers to display
    const maxPagesToShow = 5;
    let startPage = 1;
    let endPage = totalPages;
    if (totalPages > maxPagesToShow) {
        let maxPagesBeforeCurrent = Math.floor(maxPagesToShow / 2);
        let maxPagesAfterCurrent = Math.ceil(maxPagesToShow / 2) - 1;
        if (page <= maxPagesBeforeCurrent) { startPage = 1; endPage = maxPagesToShow; }
        else if (page + maxPagesAfterCurrent >= totalPages) { startPage = totalPages - maxPagesToShow + 1; endPage = totalPages; }
        else { startPage = page - maxPagesBeforeCurrent; endPage = page + maxPagesAfterCurrent; }
    }

    const ul = document.createElement('ul');
    ul.classList.add('pagination', 'pagination-sm', 'mb-0');
    ul.appendChild(prevLi);

    // Add first page and ellipsis if needed
    if (startPage > 1) {
        const firstLi = document.createElement('li'); firstLi.classList.add('page-item');
        const firstA = document.createElement('a'); firstA.classList.add('page-link'); firstA.href = '#'; firstA.textContent = '1';
        firstA.addEventListener('click', (e) => { e.preventDefault(); promptsCurrentPage = 1; fetchUserPrompts(); });
        firstLi.appendChild(firstA); ul.appendChild(firstLi);
        if (startPage > 2) {
             const ellipsisLi = document.createElement('li'); ellipsisLi.classList.add('page-item', 'disabled');
             ellipsisLi.innerHTML = `<span class="page-link">...</span>`; ul.appendChild(ellipsisLi);
        }
    }

    // Add page number links
    for (let p = startPage; p <= endPage; p++) {
        const li = document.createElement('li'); li.classList.add('page-item');
        if (p === page) { li.classList.add('active'); li.setAttribute('aria-current', 'page'); }
        const a = document.createElement('a'); a.classList.add('page-link'); a.href = '#'; a.textContent = p;
        a.addEventListener('click', (e) => {
            e.preventDefault();
            if (promptsCurrentPage !== p) {
                promptsCurrentPage = p;
                fetchUserPrompts(); // Fetch specific page of prompts
            }
        });
        li.appendChild(a); ul.appendChild(li);
    }

    // Add last page and ellipsis if needed
    if (endPage < totalPages) {
         if (endPage < totalPages - 1) {
             const ellipsisLi = document.createElement('li'); ellipsisLi.classList.add('page-item', 'disabled');
             ellipsisLi.innerHTML = `<span class="page-link">...</span>`; ul.appendChild(ellipsisLi);
         }
        const lastLi = document.createElement('li'); lastLi.classList.add('page-item');
        const lastA = document.createElement('a'); lastA.classList.add('page-link'); lastA.href = '#'; lastA.textContent = totalPages;
        lastA.addEventListener('click', (e) => { e.preventDefault(); promptsCurrentPage = totalPages; fetchUserPrompts(); });
        lastLi.appendChild(lastA); ul.appendChild(lastLi);
    }

    ul.appendChild(nextLi);
    promptsPaginationContainer.appendChild(ul); // Append to the prompts pagination container
}


// ------------- Event Listeners -------------

// Create Prompt Button
if (createPromptBtn && promptModalEl) {
    createPromptBtn.addEventListener("click", () => {
        if (!promptIdEl || !promptNameEl || !promptContentEl) return;
        const modalLabel = document.getElementById("promptModalLabel");
        if (modalLabel) modalLabel.textContent = "Create New Prompt";
        promptIdEl.value = "";
        promptNameEl.value = "";
        if (simplemde) {
            simplemde.value("");
            // Clear the editor completely
            simplemde.codemirror.setValue("");
        }
        else { promptContentEl.value = ""; }
        promptModalEl.show();
        
        // Force refresh after modal is fully shown
        setTimeout(() => {
            if (simplemde) {
                simplemde.codemirror.refresh();
                simplemde.codemirror.focus();
            }
        }, 300);
    });
}

// Add event listener for modal shown event
if (promptModalEl) {
    document.getElementById("promptModal")?.addEventListener('shown.bs.modal', function () {
        if (simplemde) {
            simplemde.codemirror.refresh();
            simplemde.codemirror.focus();
        }
    });
}

// Save Prompt Form
if (promptForm && promptSaveBtn && promptModalEl) {
    promptForm.addEventListener("submit", (e) => {
        e.preventDefault();
        if (!promptIdEl || !promptNameEl || !promptContentEl) return;

        promptSaveBtn.disabled = true;
        promptSaveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1"></span> Saving...`;

        let contentValue = simplemde ? simplemde.value() : promptContentEl.value;
        const promptId = promptIdEl.value;
        const payload = {
            name: promptNameEl.value.trim(),
            content: contentValue.trim(),
        };

        const url = promptId ? `/api/prompts/${promptId}` : "/api/prompts";
        const method = promptId ? "PATCH" : "POST";

        fetch(url, {
            method: method,
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
            .then(data => {
                promptModalEl.hide();
                // Refresh the current page after saving
                fetchUserPrompts();
            })
            .catch(err => {
                console.error(`Error ${method === 'POST' ? 'creating' : 'updating'} prompt:`, err);
                alert(`Error ${method === 'POST' ? 'creating' : 'updating'} prompt: ` + (err.error || err.message || "Unknown error"));
            })
            .finally(() => {
                promptSaveBtn.disabled = false;
                promptSaveBtn.innerHTML = "Save Prompt";
            });
    });
}

// Prompts Page Size Select
if (promptsPageSizeSelect) {
    promptsPageSizeSelect.addEventListener('change', (e) => {
        promptsPageSize = parseInt(e.target.value, 10);
        promptsCurrentPage = 1; // Reset to first page
        fetchUserPrompts();
    });
}

// Prompts Filter Buttons
if (promptsApplyFiltersBtn) {
    promptsApplyFiltersBtn.addEventListener('click', () => {
        promptsSearchTerm = promptsSearchInput ? promptsSearchInput.value.trim() : '';
        promptsCurrentPage = 1; // Reset to first page
        fetchUserPrompts();
    });
}

if (promptsClearFiltersBtn) {
    // Remove any existing event listeners to prevent duplicates
    promptsClearFiltersBtn.removeEventListener('click', clearPromptsFilters);
    
    // Define the clear filters function
    function clearPromptsFilters() {
        console.log("Clearing prompt filters...");
        if (promptsSearchInput) promptsSearchInput.value = '';
        promptsSearchTerm = '';
        promptsCurrentPage = 1; // Reset to first page
        fetchUserPrompts();
    }
    
    // Add the event listener
    promptsClearFiltersBtn.addEventListener('click', clearPromptsFilters);
    
    // Make the function globally available for other components to use
    window.clearPromptsFilters = clearPromptsFilters;
}

// Optional: Trigger search on Enter key in prompts search input
if (promptsSearchInput) {
    promptsSearchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            promptsApplyFiltersBtn.click();
        }
    });
}


// --- Global Functions for Inline `onclick` Handlers ---

// Edit Prompt (Remains largely the same, just needs to be global)
window.onEditPrompt = function (promptId) {
    if (!promptModalEl || !promptIdEl || !promptNameEl || !promptContentEl) return;
    fetch(`/api/prompts/${promptId}`)
        .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
        .then(data => {
            const modalLabel = document.getElementById("promptModalLabel");
                if (modalLabel) modalLabel.textContent = `Edit Prompt: ${escapeHtml(data.name)}`;
            promptIdEl.value = data.id;
            promptNameEl.value = data.name;
            
            // Clear the editor completely first
            if (simplemde) {
                simplemde.codemirror.setValue("");
                simplemde.value(data.content || "");
            }
            else { promptContentEl.value = data.content || ""; }
            
            promptModalEl.show();
            
            // Force refresh after modal is fully shown
            setTimeout(() => {
                if (simplemde) {
                    simplemde.codemirror.refresh();
                    simplemde.codemirror.focus();
                }
            }, 300);
        })
        .catch(err => {
            console.error("Error retrieving prompt for edit:", err);
            alert("Error retrieving prompt: " + (err.error || err.message || "Unknown error"));
        });
};

// Delete Prompt (Remains the same, but calls fetchUserPrompts at the end)
window.onDeletePrompt = function (promptId, event) {
    if (!confirm("Are you sure you want to delete this prompt?")) return;

    const deleteBtn = event ? event.target.closest('button') : null;
    if (deleteBtn) {
        deleteBtn.disabled = true;
        deleteBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;
    }

    fetch(`/api/prompts/${promptId}`, { method: "DELETE" })
        .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
        .then(data => {
            // Refresh the current page after deleting
            fetchUserPrompts();
        })
        .catch(err => {
            console.error("Error deleting prompt:", err);
            alert("Error deleting prompt: " + (err.error || err.message || "Unknown error"));
            if (deleteBtn) {
                    deleteBtn.disabled = false;
                    deleteBtn.innerHTML = '<i class="bi bi-trash-fill"></i> Delete';
            }
        });
};

// Make fetchUserPrompts globally available IF needed by workspace-init.js
window.fetchUserPrompts = fetchUserPrompts;