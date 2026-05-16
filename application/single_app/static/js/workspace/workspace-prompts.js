// static/js/workspace/workspace-prompts.js

import { openViewModal, setupViewToggle, switchViewContainers, truncateDescription } from "./view-utils.js";

// ------------- State Variables (Prompts Tab) -------------
let promptsCurrentPage = 1;
let promptsPageSize = 10;
let promptsSearchTerm = '';

// ------------- DOM Elements (Prompts Tab) -------------
const promptsTableBody = document.querySelector("#prompts-table tbody");
const promptsListView = document.getElementById("prompts-list-view");
const promptsCardView = document.getElementById("prompts-card-view");
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
if (!promptsTableBody || !promptsListView || !promptsCardView || !promptModalEl || !promptForm || !promptIdEl || !promptNameEl || !promptContentEl || !createPromptBtn || !promptSaveBtn || !promptsSearchInput || !promptsApplyFiltersBtn || !promptsClearFiltersBtn || !promptsPageSizeSelect || !promptsPaginationContainer) {
    console.warn("Workspace Prompts Tab: One or more essential DOM elements not found. Script might not function correctly.");
}

let simplemde = null; // Declare outside to be accessible

// Initialize SimpleMDE
if (promptContentEl && typeof SimpleMDE !== 'undefined') {
    try {
        simplemde = new SimpleMDE({ 
            element: promptContentEl, 
            spellChecker: false,
            autoDownloadFontAwesome: false // Prevent CSP violation
        });
    } catch (e) { console.error("Failed to initialize SimpleMDE:", e); }
} else if (!promptContentEl) { console.warn("Prompt content textarea not found, SimpleMDE not initialized."); }
else if (typeof SimpleMDE === 'undefined') { console.warn("SimpleMDE library not loaded."); }


// ------------- Prompt Functions -------------

function createPromptLoadingElement(message) {
    const wrapper = document.createElement('div');
    wrapper.className = 'col-12 text-center text-muted py-5';

    const spinner = document.createElement('div');
    spinner.className = 'spinner-border spinner-border-sm me-2';
    spinner.setAttribute('role', 'status');

    const hiddenLabel = document.createElement('span');
    hiddenLabel.className = 'visually-hidden';
    hiddenLabel.textContent = 'Loading...';
    spinner.appendChild(hiddenLabel);

    wrapper.appendChild(spinner);
    wrapper.append(message);
    return wrapper;
}

function setPromptsLoadingState() {
    if (promptsTableBody) {
        const row = document.createElement('tr');
        row.className = 'table-loading-row';
        const cell = document.createElement('td');
        cell.colSpan = 2;

        const spinner = document.createElement('div');
        spinner.className = 'spinner-border spinner-border-sm me-2';
        spinner.setAttribute('role', 'status');
        const hiddenLabel = document.createElement('span');
        hiddenLabel.className = 'visually-hidden';
        hiddenLabel.textContent = 'Loading...';
        spinner.appendChild(hiddenLabel);

        cell.appendChild(spinner);
        cell.append('Loading prompts...');
        row.appendChild(cell);
        promptsTableBody.replaceChildren(row);
    }

    if (promptsCardView) {
        promptsCardView.replaceChildren(createPromptLoadingElement('Loading prompts...'));
    }
}

function renderPromptsEmptyState(message, showResetButton) {
    if (promptsTableBody) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 2;
        cell.className = 'text-center p-4 text-muted';
        cell.append(message);

        if (showResetButton) {
            cell.appendChild(document.createElement('br'));
            const resetButton = document.createElement('button');
            resetButton.type = 'button';
            resetButton.className = 'btn btn-link btn-sm p-0';
            resetButton.textContent = 'Clear search';
            resetButton.addEventListener('click', () => promptsClearFiltersBtn?.click());
            cell.appendChild(resetButton);
            cell.append(' to see all prompts.');
        }

        row.appendChild(cell);
        promptsTableBody.replaceChildren(row);
    }

    if (promptsCardView) {
        const wrapper = document.createElement('div');
        wrapper.className = 'col-12 text-center text-muted py-5';

        const icon = document.createElement('i');
        icon.className = 'bi bi-card-text display-6 mb-2 d-block';
        wrapper.appendChild(icon);

        const text = document.createElement('p');
        text.className = 'mb-2';
        text.textContent = message;
        wrapper.appendChild(text);

        if (showResetButton) {
            const resetButton = document.createElement('button');
            resetButton.type = 'button';
            resetButton.className = 'btn btn-link btn-sm p-0';
            resetButton.textContent = 'Clear search';
            resetButton.addEventListener('click', () => promptsClearFiltersBtn?.click());
            wrapper.appendChild(resetButton);
        }

        promptsCardView.replaceChildren(wrapper);
    }
}

function renderPromptsErrorState(message) {
    if (promptsTableBody) {
        const row = document.createElement('tr');
        const cell = document.createElement('td');
        cell.colSpan = 2;
        cell.className = 'text-center text-danger p-3';
        cell.textContent = message;
        row.appendChild(cell);
        promptsTableBody.replaceChildren(row);
    }

    if (promptsCardView) {
        const wrapper = document.createElement('div');
        wrapper.className = 'col-12 text-center text-danger py-5';
        const icon = document.createElement('i');
        icon.className = 'bi bi-exclamation-triangle display-6 mb-2 d-block';
        const text = document.createElement('p');
        text.className = 'mb-0';
        text.textContent = message;
        wrapper.append(icon, text);
        promptsCardView.replaceChildren(wrapper);
    }
}

function getPromptPreview(prompt) {
    const content = String(prompt?.content || '').trim();
    if (content) {
        return truncateDescription(content, 180);
    }

    return 'Open the prompt to review or edit the reusable content.';
}

function isPromptCardActionTarget(target) {
    return Boolean(target.closest('a, button, input, label, select, textarea, .dropdown-menu'));
}

function buildPromptChatUrl(promptId, scopeType = 'personal', scopeId = '') {
    const params = new URLSearchParams({
        prompt_id: String(promptId || ''),
        prompt_scope: scopeType,
        openPrompt: '1',
    });

    if (scopeId) {
        params.set('prompt_scope_id', String(scopeId));
    }

    return `/chats?${params.toString()}`;
}

function chatWithPrompt(promptId) {
    if (!promptId) {
        return;
    }

    window.location.href = buildPromptChatUrl(promptId);
}

function createPromptButton({ className, title, iconClass, label, onClick }) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = className;
    button.title = title;
    button.setAttribute('aria-label', title);

    const icon = document.createElement('i');
    icon.className = iconClass;
    button.appendChild(icon);

    if (label) {
        icon.classList.add('me-1');
        button.append(label);
    }

    button.addEventListener('click', (event) => {
        event.stopPropagation();
        onClick(event);
    });

    return button;
}

function renderPromptRow(prompt) {
    if (!promptsTableBody) return;

    const row = document.createElement('tr');
    row.dataset.promptId = prompt.id || '';

    const nameCell = document.createElement('td');
    nameCell.title = prompt.name || '';
    nameCell.textContent = prompt.name || 'Untitled Prompt';

    const actionsCell = document.createElement('td');
    const actionWrap = document.createElement('div');
    actionWrap.className = 'd-flex gap-1 justify-content-start justify-content-md-end';

    actionWrap.append(
        createPromptButton({
            className: 'btn btn-sm btn-primary',
            title: 'Chat with Prompt',
            iconClass: 'bi bi-chat-dots',
            onClick: () => chatWithPrompt(prompt.id),
        }),
        createPromptButton({
            className: 'btn btn-sm btn-outline-info',
            title: 'View Prompt',
            iconClass: 'bi bi-eye',
            onClick: () => window.onViewPrompt(prompt.id),
        }),
        createPromptButton({
            className: 'btn btn-sm btn-outline-secondary',
            title: 'Edit Prompt',
            iconClass: 'bi bi-pencil',
            onClick: () => window.onEditPrompt(prompt.id),
        }),
        createPromptButton({
            className: 'btn btn-sm btn-outline-danger',
            title: 'Delete Prompt',
            iconClass: 'bi bi-trash',
            onClick: (event) => window.onDeletePrompt(prompt.id, event),
        })
    );

    actionsCell.appendChild(actionWrap);
    row.append(nameCell, actionsCell);
    promptsTableBody.appendChild(row);
}

function createPromptCard(prompt) {
    const col = document.createElement('div');
    col.className = 'col-12 col-md-6 col-xl-4';

    const card = document.createElement('div');
    card.className = 'card item-card prompt-item-card h-100';
    card.tabIndex = 0;
    card.setAttribute('aria-label', `View prompt ${prompt.name || 'Untitled Prompt'}`);

    const body = document.createElement('div');
    body.className = 'card-body d-flex flex-column';

    const iconWrap = document.createElement('div');
    iconWrap.className = 'item-card-icon mb-2';
    const icon = document.createElement('i');
    icon.className = 'bi bi-card-text';
    icon.style.fontSize = '1.75rem';
    iconWrap.appendChild(icon);

    const title = document.createElement('h6');
    title.className = 'card-title mb-2';
    title.textContent = prompt.name || 'Untitled Prompt';

    const preview = document.createElement('p');
    preview.className = 'card-text small text-muted prompt-card-preview flex-grow-1';
    preview.textContent = getPromptPreview(prompt);

    const actions = document.createElement('div');
    actions.className = 'item-card-buttons mt-2 d-flex flex-wrap gap-1';
    actions.append(
        createPromptButton({
            className: 'btn btn-sm btn-primary',
            title: 'Chat with Prompt',
            iconClass: 'bi bi-chat-dots',
            label: 'Chat',
            onClick: () => chatWithPrompt(prompt.id),
        }),
        createPromptButton({
            className: 'btn btn-sm btn-outline-info',
            title: 'View Prompt',
            iconClass: 'bi bi-eye',
            label: 'View',
            onClick: () => window.onViewPrompt(prompt.id),
        }),
        createPromptButton({
            className: 'btn btn-sm btn-outline-secondary',
            title: 'Edit Prompt',
            iconClass: 'bi bi-pencil',
            label: 'Edit',
            onClick: () => window.onEditPrompt(prompt.id),
        }),
        createPromptButton({
            className: 'btn btn-sm btn-outline-danger',
            title: 'Delete Prompt',
            iconClass: 'bi bi-trash',
            onClick: (event) => window.onDeletePrompt(prompt.id, event),
        })
    );

    card.addEventListener('click', (event) => {
        if (!isPromptCardActionTarget(event.target)) {
            window.onViewPrompt(prompt.id);
        }
    });
    card.addEventListener('keydown', (event) => {
        if (!isPromptCardActionTarget(event.target) && (event.key === 'Enter' || event.key === ' ')) {
            event.preventDefault();
            window.onViewPrompt(prompt.id);
        }
    });

    body.append(iconWrap, title, preview, actions);
    card.appendChild(body);
    col.appendChild(card);
    return col;
}

function renderPromptViews(prompts) {
    promptsTableBody.replaceChildren();
    prompts.forEach((prompt) => renderPromptRow(prompt));

    if (promptsCardView) {
        promptsCardView.replaceChildren(...prompts.map((prompt) => createPromptCard(prompt)));
    }
}

function fetchUserPrompts() {
    if (!promptsTableBody || !promptsPaginationContainer) return;

    setPromptsLoadingState();
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
            if (!data.prompts || data.prompts.length === 0) {
                renderPromptsEmptyState(
                    promptsSearchTerm ? 'No prompts found matching your search.' : 'No prompts created yet.',
                    Boolean(promptsSearchTerm)
                );
            } else {
                renderPromptViews(data.prompts);
            }
            // Render pagination controls using data from response
            renderPromptsPaginationControls(data.page, data.page_size, data.total_count);
        })
        .catch(err => {
            console.error("Error fetching prompts:", err);
            renderPromptsErrorState(`Error loading prompts: ${err.error || err.message || 'Unknown error'}`);
            renderPromptsPaginationControls(1, promptsPageSize, 0); // Show empty pagination on error
        });
}

function fetchPrompt(promptId) {
    return fetch(`/api/prompts/${encodeURIComponent(promptId)}`)
        .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)));
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

        const url = promptId ? `/api/prompts/${encodeURIComponent(promptId)}` : "/api/prompts";
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

setupViewToggle('prompts', 'promptsViewPreference', (mode) => {
    switchViewContainers(mode, promptsListView, promptsCardView);
});


// --- Global Functions for Inline `onclick` Handlers ---

// Edit Prompt (Remains largely the same, just needs to be global)
window.onEditPrompt = function (promptId) {
    if (!promptModalEl || !promptIdEl || !promptNameEl || !promptContentEl) return;
    fetchPrompt(promptId)
        .then(data => {
            const modalLabel = document.getElementById("promptModalLabel");
            if (modalLabel) modalLabel.textContent = `Edit Prompt: ${data.name || 'Untitled Prompt'}`;
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

window.onViewPrompt = function (promptId) {
    fetchPrompt(promptId)
        .then(data => {
            openViewModal(data, 'prompt', {
                onChat: (item) => chatWithPrompt(item.id),
                onEdit: (item) => window.onEditPrompt(item.id),
            });
        })
        .catch(err => {
            console.error("Error retrieving prompt for view:", err);
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

    fetch(`/api/prompts/${encodeURIComponent(promptId)}`, { method: "DELETE" })
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
                deleteBtn.innerHTML = '<i class="bi bi-trash"></i>';
            }
        });
};

window.chatWithPrompt = chatWithPrompt;

// Make fetchUserPrompts globally available IF needed by workspace-init.js
window.fetchUserPrompts = fetchUserPrompts;