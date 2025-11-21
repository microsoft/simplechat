// admin_settings.js
import { showToast } from "../chat/chat-toast.js";

let gptSelected = window.gptSelected || [];
let gptAll      = window.gptAll || [];

let embeddingSelected = window.embeddingSelected || [];
let embeddingAll      = window.embeddingAll || [];

let imageSelected = window.imageSelected || [];
let imageAll      = window.imageAll || [];

let classificationCategories = window.classificationCategories || [];
let enableDocumentClassification = window.enableDocumentClassification || false;

let externalLinks = window.externalLinks || [];
let enableExternalLinks = window.enableExternalLinks || false;
let externalLinksMenuName = window.externalLinksMenuName || 'External Links';

// Track whether form has been modified since last save
let formModified = false;

const enableClassificationToggle = document.getElementById('enable_document_classification');
const classificationSettingsDiv = document.getElementById('document_classification_settings');
const classificationTbody = document.getElementById('classification-categories-tbody');
const addClassificationBtn = document.getElementById('add-classification-btn');
const classificationJsonInput = document.getElementById('document_classification_categories_json');

const enableExternalLinksToggle = document.getElementById('enable_external_links');
const externalLinksSettingsDiv = document.getElementById('external_links_settings');
const externalLinksTbody = document.getElementById('external-links-tbody');
const addExternalLinkBtn = document.getElementById('add-external-link-btn');
const externalLinksJsonInput = document.getElementById('external_links_json');

const adminForm = document.getElementById('admin-settings-form');
const saveButton = document.getElementById('floating-save-btn') || (adminForm ? adminForm.querySelector('button[type="submit"]') : null);
const enableGroupWorkspacesToggle = document.getElementById('enable_group_workspaces');
const createGroupPermissionSettingDiv = document.getElementById('create_group_permission_setting');

document.addEventListener('DOMContentLoaded', () => {
    // --- Existing Setup ---
    renderGPTModels();
    renderEmbeddingModels();
    renderImageModels();

    updateGptHiddenInput();
    updateEmbeddingHiddenInput();
    updateImageHiddenInput();

    setupToggles(); // This function will be extended below
    
    // Initialize tooltips
    initializeTooltips();

    setupTestButtons();

    activateTabFromHash(); // Keep tab activation logic

    document.querySelectorAll('.nav-link').forEach(tab => {
        tab.addEventListener('click', function () {
            history.pushState(null, null, this.getAttribute('data-bs-target'));
        });
    });

    window.addEventListener("popstate", activateTabFromHash);

    // --- NEW: Classification Setup ---
    setupClassification(); // Initialize classification section
    
    // --- NEW: External Links Setup ---
    setupExternalLinks(); // Initialize external links section
    
    // --- Setup form change tracking ---
    setupFormChangeTracking();

    // --- Setup Settings Walkthrough (after all other components are ready) ---
    setTimeout(() => {
        setupSettingsWalkthrough();
    }, 100);


    // --- Add form submission validation ---
    if (adminForm) {
        adminForm.addEventListener('submit', function(e) {
            try {
                console.log('🚀 Form submission started - gathering tab information...');
                
                // Capture the current active tab before form submission
                const activeTab = getCurrentActiveTab();
                
                if (activeTab) {
                    // Store the active tab in sessionStorage to restore after redirect
                    sessionStorage.setItem('adminSettingsActiveTab', activeTab);
                } else {
                    console.warn('⚠️ Form submission - No active tab detected, tab preservation may not work');
                }
                
                // Ensure classification categories is valid JSON before submission
                if (classificationJsonInput) {
                    const jsonString = updateClassificationJsonInput();
                    console.log("Classification categories before submission:", jsonString);
                    
                    // Verify JSON is valid by parsing it
                    try {
                        JSON.parse(jsonString);
                    } catch (jsonErr) {
                        console.error("Invalid JSON for classification categories:", jsonErr);
                        // Set to empty array if invalid
                        classificationJsonInput.value = "[]";
                    }
                }
            } catch (err) {
                console.error("Error in form submission validation:", err);
                // Allow form to submit even if there's an error to avoid blocking users
            }
        });
    }
});

/**
 * Gets the current active tab's target hash (e.g., "#general", "#agents")
 * @returns {string|null} The hash of the currently active tab, or null if none found
 */
function getCurrentActiveTab() {    
    // First check if we're using sidebar navigation
    const sidebarToggle = document.getElementById('admin-settings-toggle');
    
    if (sidebarToggle) {
        
        // For sidebar navigation, check for active sidebar nav links
        // First check for active section (more specific)
        const activeSidebarSection = document.querySelector('.admin-nav-section.active');
        if (activeSidebarSection) {
            const tabId = activeSidebarSection.getAttribute('data-tab');
            return tabId ? '#' + tabId : null;
        }
        
        // Then check for active tab (less specific)
        const activeSidebarTab = document.querySelector('.admin-nav-tab.active');
        console.log('🔍 getCurrentActiveTab - Looking for .admin-nav-tab.active:', activeSidebarTab);
        if (activeSidebarTab) {
            const tabId = activeSidebarTab.getAttribute('data-tab');
            return tabId ? '#' + tabId : null;
        }
        
        // Fallback: check which tab pane is currently visible for sidebar nav
        const activeTabPane = document.querySelector('.tab-pane.show.active');
        if (activeTabPane) {
            return '#' + activeTabPane.id;
        }
        
        // If no active tab found but we have a hash, use that
        if (window.location.hash) {
            return window.location.hash;
        }
                
        // Debug: List all available sidebar navigation elements
        const allSections = document.querySelectorAll('.admin-nav-section');
        const allTabs = document.querySelectorAll('.admin-nav-tab');
        const allPanes = document.querySelectorAll('.tab-pane');
        allSections.forEach(section => {
            console.log('  - Section:', section.getAttribute('data-tab'), 'active:', section.classList.contains('active'));
        });
        allTabs.forEach(tab => {
            console.log('  - Tab:', tab.getAttribute('data-tab'), 'active:', tab.classList.contains('active'));
        });
        allPanes.forEach(pane => {
            console.log('  - Pane:', pane.id, 'show:', pane.classList.contains('show'), 'active:', pane.classList.contains('active'));
        });
        
    } else {
        
        // For tab navigation, check Bootstrap tab buttons
        const activeTabButton = document.querySelector('button.nav-link.active[data-bs-target]');
        console.log('🔍 getCurrentActiveTab - Looking for button.nav-link.active[data-bs-target]:', activeTabButton);
        if (activeTabButton) {
            const target = activeTabButton.getAttribute('data-bs-target');
            return target;
        }
        
        // Fallback: check which tab pane is currently visible for tab nav
        const activeTabPane = document.querySelector('.tab-pane.fade.show.active');
        console.log('🔍 getCurrentActiveTab - Looking for .tab-pane.fade.show.active:', activeTabPane);
        if (activeTabPane) {
            return '#' + activeTabPane.id;
        }
        
        console.log('❌ getCurrentActiveTab - No active Bootstrap tab elements found');
    }
    
    console.log('❌ getCurrentActiveTab - No active tab found anywhere');
    return null;
}

function activateTabFromHash() {
    const timestamp = new Date().toLocaleTimeString();
    console.log('activateTabFromHash - Called');
    
    let hash = window.location.hash;
    
    // If no hash in URL, check sessionStorage for saved tab from form submission
    if (!hash) {
        const savedTab = sessionStorage.getItem('adminSettingsActiveTab');
        
        if (savedTab) {
            hash = savedTab;
            
            // Clear the saved tab to prevent it from affecting future navigation
            sessionStorage.removeItem('adminSettingsActiveTab');
            
            // Update URL with the restored hash
            history.replaceState(null, null, hash);
        } else {
            console.log(`❌ [${timestamp}] activateTabFromHash - No saved tab found in sessionStorage`);
        }
    } else {
        console.log(`✅ [${timestamp}] activateTabFromHash - Hash found in URL:`, hash);
    }
    
    if (hash) {
        const tabId = hash.startsWith('#') ? hash.substring(1) : hash;
        
        // Check if we're using sidebar navigation
        const sidebarToggle = document.getElementById('admin-settings-toggle');
        
        if (sidebarToggle) {
            // Try different ways to access the showAdminTab function
            let showTabFunction = null;
            if (typeof showAdminTab === 'function') {
                showTabFunction = showAdminTab;
            } else if (typeof window.showAdminTab === 'function') {
                showTabFunction = window.showAdminTab;
            }
            
            if (showTabFunction) {
                showTabFunction(tabId);
            } else {
                // Manual tab activation fallback
                // Hide all tab panes
                document.querySelectorAll('.tab-pane').forEach(pane => {
                    pane.classList.remove('show', 'active');
                });
                
                // Show the selected tab pane
                const targetTab = document.getElementById(tabId);
                if (targetTab) {
                    targetTab.classList.add('show', 'active');
                }
            }
            
            // Set active nav link for sidebar - handle both tab and section level
            
            // First clear all active states
            const allTabs = document.querySelectorAll('.admin-nav-tab');
            const allSections = document.querySelectorAll('.admin-nav-section');
            
            allTabs.forEach(link => {
                link.classList.remove('active');
            });
            allSections.forEach(link => {
                link.classList.remove('active');
            });
            
            // Set the main tab as active
            const navLink = document.querySelector(`.admin-nav-tab[data-tab="${tabId}"]`);
            const navSection = document.querySelector(`.admin-nav-section[data-tab="${tabId}"]`);
            
            if (navLink) {
                navLink.classList.add('active');
            }
            
            if (navSection) {
                navSection.classList.add('active');
            }
            
            // Also expand the submenu if it exists
            const submenu = document.getElementById(tabId + '-submenu');
            if (submenu) {
                submenu.style.display = 'block';
            }
            
        } else {
            // Use Bootstrap tab navigation
            const tabButton = document.querySelector(`button.nav-link[data-bs-target="${hash}"]`);
            if (tabButton) {
                const tab = new bootstrap.Tab(tabButton);
                tab.show();
            }
        }
    }
}

function renderGPTModels() {
    const listDiv = document.getElementById('gpt_models_list');
    if (!listDiv) return;

    if (!gptAll || gptAll.length === 0) {
        listDiv.innerHTML = '<p class="text-warning">No GPT models found. Click "Fetch GPT Models" to populate.</p>';
        return;
    }

    let html = '<ul class="list-group">';
    gptAll.forEach(m => {
        const isSelected = gptSelected.some(sel => sel.deploymentName === m.deploymentName);
        // use green for selected, blue for not
        const btnClass = isSelected ? 'btn-success' : 'btn-primary';
        const btnLabel = isSelected ? 'Selected' : 'Select';

        html += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <span>${m.deploymentName} (Model: ${m.modelName})</span>
                <button
                  class="btn btn-sm ${btnClass}"
                  onclick="selectGptModel('${m.deploymentName}', '${m.modelName}')"
                >
                  ${btnLabel}
                </button>
            </li>
        `;
    });
    html += '</ul>';
    listDiv.innerHTML = html;
}


function renderEmbeddingModels() {
    const listDiv = document.getElementById('embedding_models_list');
    if (!listDiv) return;

    if (!embeddingAll || embeddingAll.length === 0) {
        listDiv.innerHTML = '<p class="text-warning">No embedding models found. Click "Fetch Embedding Models" to populate.</p>';
        return;
    }

    let html = '<ul class="list-group">';
    embeddingAll.forEach(m => {
        const isSelected = embeddingSelected.some(sel =>
            sel.deploymentName === m.deploymentName &&
            sel.modelName === m.modelName
        );
        const buttonLabel = isSelected ? 'Selected' : 'Select';
        const buttonDisabled = isSelected ? 'disabled' : '';
        html += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <span>${m.deploymentName} (Model: ${m.modelName})</span>
                <button class="btn btn-sm btn-primary" ${buttonDisabled}
                    onclick="selectEmbeddingModel('${m.deploymentName}', '${m.modelName}')">
                    ${buttonLabel}
                </button>
            </li>
        `;
    });
    html += '</ul>';
    listDiv.innerHTML = html;
}

function renderImageModels() {
    const listDiv = document.getElementById('image_models_list');
    if (!listDiv) return;

    if (!imageAll || imageAll.length === 0) {
        listDiv.innerHTML = '<p class="text-warning">No image models found. Click "Fetch Image Models" to populate.</p>';
        return;
    }

    let html = '<ul class="list-group">';
    imageAll.forEach(m => {
        const isSelected = imageSelected.some(sel =>
            sel.deploymentName === m.deploymentName &&
            sel.modelName === m.modelName
        );
        const buttonLabel = isSelected ? 'Selected' : 'Select';
        const buttonDisabled = isSelected ? 'disabled' : '';
        html += `
            <li class="list-group-item d-flex justify-content-between align-items-center">
                <span>${m.deploymentName} (Model: ${m.modelName})</span>
                <button class="btn btn-sm btn-primary" ${buttonDisabled}
                    onclick="selectImageModel('${m.deploymentName}', '${m.modelName}')">
                    ${buttonLabel}
                </button>
            </li>
        `;
    });
    html += '</ul>';
    listDiv.innerHTML = html;
}

const fetchGptBtn = document.getElementById('fetch_gpt_models_btn');
if (fetchGptBtn) {
    fetchGptBtn.addEventListener('click', async () => {
        const listDiv = document.getElementById('gpt_models_list');
        listDiv.innerHTML = 'Fetching...';
        try {
            const resp = await fetch('/api/models/gpt');
            const data = await resp.json();
            if (resp.ok && data.models && data.models.length > 0) {
                gptAll = data.models;
                renderGPTModels();
                updateGptHiddenInput();
            } else {
                listDiv.innerHTML = `<p class="text-danger">Error: ${data.error || 'No GPT models found'}</p>`;
            }
        } catch (err) {
            listDiv.innerHTML = `<p class="text-danger">Error fetching GPT models: ${err.message}</p>`;
        }
    });
}

window.selectGptModel = (deploymentName, modelName) => {
    const idx = gptSelected.findIndex(x => x.deploymentName === deploymentName);
  
    if (idx === -1) {
      // not yet selected → add
      gptSelected.push({ deploymentName, modelName });
    } else {
      // already selected → remove
      gptSelected.splice(idx, 1);
    }
  
    updateGptHiddenInput();  // rewrite the JSON payload
    renderGPTModels();       // refresh the button states
    markFormAsModified();    // mark form as modified
  };

function updateGptHiddenInput() {
    const gptInput = document.getElementById('gpt_model_json');
    if (!gptInput) return;
    const payload = {
        selected: gptSelected,
        all: gptAll
    };
    gptInput.value = JSON.stringify(payload);
}

const fetchEmbeddingBtn = document.getElementById('fetch_embedding_models_btn');
if (fetchEmbeddingBtn) {
    fetchEmbeddingBtn.addEventListener('click', async () => {
        const listDiv = document.getElementById('embedding_models_list');
        listDiv.innerHTML = 'Fetching...';
        try {
            const resp = await fetch('/api/models/embedding');
            const data = await resp.json();
            if (resp.ok && data.models && data.models.length > 0) {
                embeddingAll = data.models;
                renderEmbeddingModels();
                updateEmbeddingHiddenInput();
            } else {
                listDiv.innerHTML = `<p class="text-danger">Error: ${data.error || 'No embedding models found'}</p>`;
            }
        } catch (err) {
            listDiv.innerHTML = `<p class="text-danger">Error fetching embedding models: ${err.message}</p>`;
        }
    });
}

window.selectEmbeddingModel = (deploymentName, modelName) => {
    embeddingSelected = [{ deploymentName, modelName }];
    renderEmbeddingModels();
    updateEmbeddingHiddenInput();
    markFormAsModified();    // mark form as modified
    //alert(`Selected embedding model: ${deploymentName}`);
};

function updateEmbeddingHiddenInput() {
    const embInput = document.getElementById('embedding_model_json');
    if (!embInput) return;
    const payload = {
        selected: embeddingSelected,
        all: embeddingAll
    };
    embInput.value = JSON.stringify(payload);
}

const fetchImageBtn = document.getElementById('fetch_image_models_btn');
if (fetchImageBtn) {
    fetchImageBtn.addEventListener('click', async () => {
        const listDiv = document.getElementById('image_models_list');
        listDiv.innerHTML = 'Fetching...';
        try {
            const resp = await fetch('/api/models/image');
            const data = await resp.json();
            if (resp.ok && data.models && data.models.length > 0) {
                imageAll = data.models;
                renderImageModels();
                updateImageHiddenInput();
            } else {
                listDiv.innerHTML = `<p class="text-danger">Error: ${data.error || 'No image models found'}</p>`;
            }
        } catch (err) {
            listDiv.innerHTML = `<p class="text-danger">Error fetching image models: ${err.message}</p>`;
        }
    });
}

window.selectImageModel = (deploymentName, modelName) => {
    imageSelected = [{ deploymentName, modelName: modelName || null }];
    document.getElementById('image_gen_model').value = deploymentName;
    renderImageModels();
    updateImageHiddenInput();
    markFormAsModified();    // mark form as modified
    // alert(`Selected image model: ${deploymentName}`);
};

function updateImageHiddenInput() {
    const imgInput = document.getElementById('image_gen_model_json');
    if (!imgInput) return;
    const payload = {
        selected: imageSelected,
        all: imageAll
    };
    imgInput.value = JSON.stringify(payload);
}

// --- Helper to escape HTML for input values ---
function escapeHtml(unsafe) {
    if (unsafe === null || typeof unsafe === 'undefined') {
        return '';
    }
    return unsafe
         .toString()
         .replace(/&/g, "&amp;")
         .replace(/</g, "&lt;")
         .replace(/>/g, "&gt;")
         .replace(/"/g, "&quot;")
         .replace(/'/g, "&#039;");
}

// --- *** NEW: Classification Functions *** ---

/**
 * Sets up initial state and event listeners for the classification section.
 */
function setupClassification() {
    if (!classificationTbody || !enableClassificationToggle || !addClassificationBtn || !classificationSettingsDiv || !adminForm) {
        console.warn("Classification elements not found, skipping setup.");
        return;
    }

    // Initial render
    renderClassificationCategories();

    // Initial visibility based on toggle state (already handled by Jinja style, but good practice)
    toggleClassificationSettingsVisibility();

    // Event listener for the main enable/disable toggle
    enableClassificationToggle.addEventListener('change', toggleClassificationSettingsVisibility);

    // Event listener for the "Add New" button
    addClassificationBtn.addEventListener('click', handleAddClassification);

    // Event delegation for buttons within the table body
    classificationTbody.addEventListener('click', handleClassificationAction);

    // Event delegation for color input changes
    classificationTbody.addEventListener('input', handleClassificationColorChange);

    // Update hidden input before form submission
    adminForm.addEventListener('submit', updateClassificationJsonInput);
}

/**
 * Shows or hides the classification settings area based on the toggle switch.
 */
function toggleClassificationSettingsVisibility() {
    if (classificationSettingsDiv && enableClassificationToggle) {
        classificationSettingsDiv.style.display = enableClassificationToggle.checked ? 'block' : 'none';
    }
}

/**
 * Renders the classification category rows in the table body.
 */
function renderClassificationCategories() {
    if (!classificationTbody) return;

    classificationTbody.innerHTML = ''; // Clear existing rows
    classificationCategories.forEach((category, index) => {
        const row = createClassificationRow(category, index);
        classificationTbody.appendChild(row);
    });
    updateClassificationJsonInput(); // Update hidden input after rendering
}

/**
 * Creates a single table row (<tr>) for a classification category.
 * @param {object} category - The category object {label, color}.
 * @param {number} index - The index of the category in the array.
 * @param {boolean} isNew - Optional flag if the row is newly added and editable by default.
 * @returns {HTMLTableRowElement} The created table row element.
 */
function createClassificationRow(category, index, isNew = false) {
    const tr = document.createElement('tr');
    tr.setAttribute('data-index', index);
    if (isNew) {
        tr.setAttribute('data-is-new', 'true'); // Mark as new and unsaved
    }

    const safeLabel = escapeHtml(category.label);
    const safeColor = escapeHtml(category.color);

    const isEditable = isNew; // New rows are editable by default
    const inputState = isEditable ? '' : 'readonly';
    const colorInputState = isEditable ? '' : 'disabled';
    const editBtnDisplay = isEditable ? 'none' : 'inline-block';
    const saveBtnDisplay = isEditable ? 'inline-block' : 'none';
    const deleteBtnDisplay = 'inline-block'; // Always show delete initially

    tr.innerHTML = `
        <td>
            <input type="text" class="form-control form-control-sm classification-label" value="${safeLabel}" ${inputState} data-original-value="${safeLabel}">
        </td>
        <td>
            <div class="color-swatch-container">
                 <label for="color-input-${index}" class="color-input-swatch" style="background-color: ${safeColor};" title="Click to change color"></label>
                 <input type="color" id="color-input-${index}" class="classification-color-input" value="${safeColor}" ${colorInputState} data-original-value="${safeColor}">
                 <span class="classification-color-hex small ms-1">${safeColor}</span>
            </div>
        </td>
        <td>
            <button type="button" class="btn btn-sm btn-secondary edit-btn me-1" style="display: ${editBtnDisplay};" title="Edit">
                <i class="bi bi-pencil-fill"></i>
            </button>
            <button type="button" class="btn btn-sm btn-success save-btn me-1" style="display: ${saveBtnDisplay};" title="Save">
                <i class="bi bi-check-lg"></i>
            </button>
            <button type="button" class="btn btn-sm btn-danger delete-btn" style="display: ${deleteBtnDisplay};" title="Delete">
                <i class="bi bi-trash-fill"></i>
            </button>
        </td>
    `;
    return tr;
}

/**
 * Handles clicks on the "Add New Category" button.
 */
function handleAddClassification() {
    // Use a unique temporary index for new rows until saved
    const tempIndex = `new-${Date.now()}`;
    const newCategory = { label: '', color: '#808080' }; // Default new category
    const newRow = createClassificationRow(newCategory, tempIndex, true); // Pass true for isNew
    classificationTbody.appendChild(newRow);

    // Focus the new label input
    const newLabelInput = newRow.querySelector('.classification-label');
    if (newLabelInput) {
        newLabelInput.focus();
    }
    markFormAsModified(); // Mark form as modified when adding a new category
    // Do NOT update the main `classificationCategories` array or JSON input yet.
}

/**
 * Handles clicks within the classification table body (Edit, Save, Delete).
 * Uses event delegation.
 * @param {Event} event - The click event.
 */
function handleClassificationAction(event) {
    const target = event.target.closest('button'); // Find the clicked button, even if icon is clicked
    if (!target) return; // Exit if click wasn't on a button or its child

    const row = target.closest('tr');
    if (!row) return; // Exit if button is not within a row

    const indexAttr = row.getAttribute('data-index');
    const isNew = row.getAttribute('data-is-new') === 'true';

    if (target.classList.contains('edit-btn')) {
        handleEditClassification(row);
    } else if (target.classList.contains('save-btn')) {
        handleSaveClassification(row, indexAttr, isNew);
    } else if (target.classList.contains('delete-btn')) {
        handleDeleteClassification(row, indexAttr, isNew);
    }
}

/**
 * Handles clicks on the "Edit" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to make editable.
 */
function handleEditClassification(row) {
    const labelInput = row.querySelector('.classification-label');
    const colorInput = row.querySelector('.classification-color-input');
    const editBtn = row.querySelector('.edit-btn');
    const saveBtn = row.querySelector('.save-btn');

    if (labelInput) {
        labelInput.readOnly = false;
        // Store current value as original for potential cancellation (if implemented)
        labelInput.dataset.originalValue = labelInput.value;
    }
    if (colorInput) {
        colorInput.disabled = false;
        colorInput.dataset.originalValue = colorInput.value;
        // Trigger click on the hidden color input when swatch is clicked
         const swatch = row.querySelector('.color-input-swatch');
         if (swatch) {
             // Ensure only one listener is added
             swatch.onclick = () => colorInput.click();
         }
    }
    if (editBtn) editBtn.style.display = 'none';
    if (saveBtn) saveBtn.style.display = 'inline-block';

    labelInput?.focus();
}

/**
 * Handles clicks on the "Save" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to save.
 * @param {string|number} indexAttr - The original index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added row.
 */
function handleSaveClassification(row, indexAttr, isNew) {
    const labelInput = row.querySelector('.classification-label');
    const colorInput = row.querySelector('.classification-color-input');
    const colorHexSpan = row.querySelector('.classification-color-hex');
    const editBtn = row.querySelector('.edit-btn');
    const saveBtn = row.querySelector('.save-btn');
    const swatch = row.querySelector('.color-input-swatch');


    const newLabel = labelInput ? labelInput.value.trim() : '';
    const newColor = colorInput ? colorInput.value : '#000000';

    // Basic validation
    if (!newLabel) {
        alert('Label cannot be empty.');
        labelInput?.focus();
        return;
    }

    const updatedCategory = { label: newLabel, color: newColor };

    if (isNew) {
        // Add to the main array
        classificationCategories.push(updatedCategory);
        // Remove the 'new' marker and potentially update index if needed, but re-rendering handles this
        row.removeAttribute('data-is-new');
        // Re-render the whole table to get correct indices and state
        renderClassificationCategories();
        markFormAsModified(); // Mark form as modified
    } else {
        // Update existing item in the array
        const index = parseInt(indexAttr, 10);
        if (!isNaN(index) && index >= 0 && index < classificationCategories.length) {
            classificationCategories[index] = updatedCategory;

            // Update UI for the current row without full re-render
            if (labelInput) {
                labelInput.readOnly = true;
                labelInput.value = newLabel; // Ensure value is updated if different
                labelInput.dataset.originalValue = newLabel;
            }
            if (colorInput) {
                colorInput.disabled = true;
                colorInput.value = newColor; // Ensure value is updated
                colorInput.dataset.originalValue = newColor;
            }
             if (colorHexSpan) {
                 colorHexSpan.textContent = newColor;
             }
            if (swatch) {
                 swatch.style.backgroundColor = newColor;
                 swatch.onclick = null; // Remove click listener
            }
            if (editBtn) editBtn.style.display = 'inline-block';
            if (saveBtn) saveBtn.style.display = 'none';

            updateClassificationJsonInput(); // Update hidden input
            markFormAsModified(); // Mark form as modified
        } else {
            console.error("Invalid index for saving classification:", indexAttr);
            // Fallback to re-render if something went wrong
            renderClassificationCategories();
        }
    }
}


/**
 * Handles clicks on the "Delete" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to delete.
 * @param {string|number} indexAttr - The index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added, unsaved row.
 */
function handleDeleteClassification(row, indexAttr, isNew) {
    if (isNew) {
        // Just remove the row from the DOM, it's not in the array yet
        row.remove();
    } else {
        // Ask for confirmation for existing items
        if (confirm('Are you sure you want to delete this classification category?')) {
            const index = parseInt(indexAttr, 10);
            if (!isNaN(index) && index >= 0 && index < classificationCategories.length) {
                classificationCategories.splice(index, 1); // Remove from array
                // Re-render the table to update indices and UI
                renderClassificationCategories();
                markFormAsModified(); // Mark form as modified
            } else {
                console.error("Invalid index for deleting classification:", indexAttr);
                // Fallback: remove row from DOM and update JSON
                row.remove();
                updateClassificationJsonInput();
                markFormAsModified(); // Mark form as modified
            }
        }
    }
}

/**
 * Handles changes to the color input element.
 * @param {Event} event - The input event.
 */
function handleClassificationColorChange(event) {
    const target = event.target;
    if (target.classList.contains('classification-color-input')) {
        const row = target.closest('tr');
        if (row) {
            const colorHexSpan = row.querySelector('.classification-color-hex');
            const swatch = row.querySelector('.color-input-swatch');
            const newColor = target.value;
            if (colorHexSpan) {
                colorHexSpan.textContent = newColor;
            }
             if (swatch) {
                swatch.style.backgroundColor = newColor;
            }
            markFormAsModified(); // Mark form as modified when color changes
        }
    }
}

/**
 * Updates the hidden input field with the current classification categories as JSON.
 */
function updateClassificationJsonInput() {
    if (classificationJsonInput) {
        try {
            // First make sure classificationCategories is an array
            if (!Array.isArray(classificationCategories)) {
                classificationCategories = [];
            }
            
            // Ensure we only stringify valid categories with required properties
            const validCategories = classificationCategories.filter(cat => 
                cat && 
                typeof cat === 'object' &&
                typeof cat.label === 'string' && 
                typeof cat.color === 'string'
            );
            
            const jsonString = JSON.stringify(validCategories);
            classificationJsonInput.value = jsonString;
            return jsonString;
        } catch (e) {
            console.error("Error stringifying classification categories:", e);
            classificationJsonInput.value = "[]"; // Set to empty array on error
            return "[]";
        }
    }
    return "[]";
}

// --- *** NEW: External Links Functions *** ---

/**
 * Sets up initial state and event listeners for the external links section.
 */
function setupExternalLinks() {
    if (enableExternalLinksToggle) {
        enableExternalLinksToggle.addEventListener('change', toggleExternalLinksSettingsVisibility);
        toggleExternalLinksSettingsVisibility(); // Set initial state
    }

    if (addExternalLinkBtn) {
        addExternalLinkBtn.addEventListener('click', handleAddExternalLink);
    }

    if (externalLinksTbody) {
        externalLinksTbody.addEventListener('click', handleExternalLinksAction);
    }

    // Render existing external links
    renderExternalLinks();
    updateExternalLinksJsonInput();
}

/**
 * Shows or hides the external links settings area based on the toggle switch.
 */
function toggleExternalLinksSettingsVisibility() {
    if (externalLinksSettingsDiv && enableExternalLinksToggle) {
        externalLinksSettingsDiv.style.display = enableExternalLinksToggle.checked ? 'block' : 'none';
    }
}

/**
 * Renders the external links rows in the table body.
 */
function renderExternalLinks() {
    if (!externalLinksTbody) return;

    // Clear existing content
    externalLinksTbody.innerHTML = '';

    // Render each external link
    externalLinks.forEach((link, index) => {
        const row = createExternalLinkRow(link, index);
        externalLinksTbody.appendChild(row);
    });

    // Update hidden input
    updateExternalLinksJsonInput();
}

/**
 * Creates a single table row (<tr>) for an external link.
 * @param {object} link - The link object {label, url}.
 * @param {number} index - The index of the link in the array.
 * @param {boolean} isNew - Optional flag if the row is newly added and editable by default.
 * @returns {HTMLTableRowElement} The created table row element.
 */
function createExternalLinkRow(link, index, isNew = false) {
    const row = document.createElement('tr');
    row.setAttribute('data-index', index);

    if (isNew) {
        // Create an editable row for new links
        row.innerHTML = `
            <td>
                <input type="text" class="form-control form-control-sm external-link-label-input" 
                       value="${escapeHtml(link.label)}" placeholder="Link Label">
            </td>
            <td>
                <input type="url" class="form-control form-control-sm external-link-url-input" 
                       value="${escapeHtml(link.url)}" placeholder="https://example.com">
            </td>
            <td>
                <button type="button" class="btn btn-sm btn-success external-link-save-btn" data-index="${index}">Save</button>
                <button type="button" class="btn btn-sm btn-secondary ms-1 external-link-cancel-btn" data-index="${index}">Cancel</button>
            </td>
        `;
    } else {
        // Create a read-only row for existing links
        row.innerHTML = `
            <td class="external-link-label">${escapeHtml(link.label)}</td>
            <td class="external-link-url">
                <a href="${escapeHtml(link.url)}" target="_blank" rel="noopener noreferrer">
                    ${escapeHtml(link.url)}
                </a>
            </td>
            <td>
                <button type="button" class="btn btn-sm btn-outline-primary external-link-edit-btn" data-index="${index}">Edit</button>
                <button type="button" class="btn btn-sm btn-outline-danger ms-1 external-link-delete-btn" data-index="${index}">Delete</button>
            </td>
        `;
    }

    return row;
}

/**
 * Handles clicks on the "Add New Link" button.
 */
function handleAddExternalLink() {
    // Create a new temporary link for editing
    const newLink = { label: '', url: '' };
    const newIndex = `new-${Date.now()}`; // Use timestamp to avoid conflicts
    
    // Create and add the new row in edit mode
    const newRow = createExternalLinkRow(newLink, newIndex, true);
    newRow.setAttribute('data-index', newIndex);
    
    if (externalLinksTbody) {
        externalLinksTbody.appendChild(newRow);
    }
    
    // Focus on the label input
    const labelInput = newRow.querySelector('.external-link-label-input');
    if (labelInput) {
        labelInput.focus();
    }
    
    markFormAsModified();
}

/**
 * Handles clicks within the external links table body (Edit, Save, Delete, Cancel).
 * Uses event delegation.
 * @param {Event} event - The click event.
 */
function handleExternalLinksAction(event) {
    const target = event.target;
    if (!target.matches('button')) return;

    const row = target.closest('tr');
    if (!row) return;

    const indexAttr = target.getAttribute('data-index') || row.getAttribute('data-index');
    const isNew = typeof indexAttr === 'string' && indexAttr.startsWith('new-');

    if (target.classList.contains('external-link-edit-btn')) {
        handleEditExternalLink(row);
    } else if (target.classList.contains('external-link-save-btn')) {
        handleSaveExternalLink(row, indexAttr, isNew);
    } else if (target.classList.contains('external-link-cancel-btn')) {
        handleCancelExternalLink(row, indexAttr, isNew);
    } else if (target.classList.contains('external-link-delete-btn')) {
        handleDeleteExternalLink(row, indexAttr, isNew);
    }
}

/**
 * Handles clicks on the "Edit" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to make editable.
 */
function handleEditExternalLink(row) {
    const index = parseInt(row.getAttribute('data-index'));
    const link = externalLinks[index];
    if (!link) return;

    // Replace the row content with editable inputs
    row.innerHTML = `
        <td>
            <input type="text" class="form-control form-control-sm external-link-label-input" 
                   value="${escapeHtml(link.label)}" placeholder="Link Label">
        </td>
        <td>
            <input type="url" class="form-control form-control-sm external-link-url-input" 
                   value="${escapeHtml(link.url)}" placeholder="https://example.com">
        </td>
        <td>
            <button type="button" class="btn btn-sm btn-success external-link-save-btn" data-index="${index}">Save</button>
            <button type="button" class="btn btn-sm btn-secondary ms-1 external-link-cancel-btn" data-index="${index}">Cancel</button>
        </td>
    `;

    // Focus on the label input
    const labelInput = row.querySelector('.external-link-label-input');
    if (labelInput) {
        labelInput.focus();
    }

    markFormAsModified();
}

/**
 * Handles clicks on the "Save" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to save.
 * @param {string|number} indexAttr - The original index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added row.
 */
function handleSaveExternalLink(row, indexAttr, isNew) {
    const labelInput = row.querySelector('.external-link-label-input');
    const urlInput = row.querySelector('.external-link-url-input');

    if (!labelInput || !urlInput) return;

    const label = labelInput.value.trim();
    const url = urlInput.value.trim();

    // Validation
    if (!label) {
        alert('Please enter a label for the link.');
        labelInput.focus();
        return;
    }

    if (!url) {
        alert('Please enter a URL for the link.');
        urlInput.focus();
        return;
    }

    // Basic URL validation
    try {
        new URL(url);
    } catch (e) {
        alert('Please enter a valid URL (e.g., https://example.com).');
        urlInput.focus();
        return;
    }

    const linkData = { label, url };

    if (isNew) {
        // Add new link to the array
        externalLinks.push(linkData);
        const newIndex = externalLinks.length - 1;
        
        // Replace the row with a read-only version
        const newRow = createExternalLinkRow(linkData, newIndex, false);
        row.parentNode.replaceChild(newRow, row);
    } else {
        // Update existing link
        const index = parseInt(indexAttr);
        if (index >= 0 && index < externalLinks.length) {
            externalLinks[index] = linkData;
            
            // Replace the row with a read-only version
            const updatedRow = createExternalLinkRow(linkData, index, false);
            row.parentNode.replaceChild(updatedRow, row);
        }
    }

    updateExternalLinksJsonInput();
    markFormAsModified();
}

/**
 * Handles clicks on the "Cancel" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to cancel editing.
 * @param {string|number} indexAttr - The index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added, unsaved row.
 */
function handleCancelExternalLink(row, indexAttr, isNew) {
    if (isNew) {
        // Remove the row entirely for new, unsaved links
        row.remove();
    } else {
        // Restore the original read-only row for existing links
        const index = parseInt(indexAttr);
        const link = externalLinks[index];
        if (link) {
            const restoredRow = createExternalLinkRow(link, index, false);
            row.parentNode.replaceChild(restoredRow, row);
        }
    }
}

/**
 * Handles clicks on the "Delete" button for a specific row.
 * @param {HTMLTableRowElement} row - The table row to delete.
 * @param {string|number} indexAttr - The index attribute ('new-...' or number).
 * @param {boolean} isNew - Whether this was a newly added, unsaved row.
 */
function handleDeleteExternalLink(row, indexAttr, isNew) {
    if (isNew) {
        // Just remove the row for unsaved new links
        row.remove();
        return;
    }

    const index = parseInt(indexAttr);
    const link = externalLinks[index];
    
    if (link && confirm(`Are you sure you want to delete the link "${link.label}"?`)) {
        // Remove from array
        externalLinks.splice(index, 1);
        
        // Re-render all links to update indices
        renderExternalLinks();
        
        markFormAsModified();
    }
}

/**
 * Updates the hidden input field with the current external links as JSON.
 */
function updateExternalLinksJsonInput() {
    if (externalLinksJsonInput) {
        try {
            // First make sure externalLinks is an array
            if (!Array.isArray(externalLinks)) {
                externalLinks = [];
            }
            
            // Ensure we only stringify valid links with required properties
            const validLinks = externalLinks.filter(link => 
                link && 
                typeof link === 'object' &&
                typeof link.label === 'string' && 
                typeof link.url === 'string'
            );
            
            const jsonString = JSON.stringify(validLinks);
            externalLinksJsonInput.value = jsonString;
            return jsonString;
        } catch (e) {
            console.error("Error stringifying external links:", e);
            externalLinksJsonInput.value = "[]"; // Set to empty array on error
            return "[]";
        }
    }
    return "[]";
}

function setupToggles() {
    // --- Enable Agents (Semantic Kernel) Toggle ---
    const agentsMainContent = document.getElementById('agents-main-content');
    const agentsDisabledMsg = document.getElementById('agents-disabled-message');
    const pluginsMainContent = document.getElementById('plugins-main-content');
    const pluginsDisabledMsg = document.getElementById('plugins-disabled-message');
    // Use backend-rendered value to show/hide content
    if (typeof settings !== 'undefined' && settings) {
        const enabled = !!settings.enable_semantic_kernel;
        if (agentsMainContent && agentsDisabledMsg) {
            agentsMainContent.style.display = enabled ? 'block' : 'none';
            agentsDisabledMsg.style.display = enabled ? 'none' : 'block';
        }
        if (pluginsMainContent && pluginsDisabledMsg) {
            pluginsMainContent.style.display = enabled ? 'block' : 'none';
            pluginsDisabledMsg.style.display = enabled ? 'none' : 'block';
        }
    }
    if (document.getElementById('core-plugin-toggles')) {
        // --- Core Plugin Toggles ---
        const timeToggle = document.getElementById('toggle-time-plugin');
        const httpToggle = document.getElementById('toggle-http-plugin');
        const waitToggle = document.getElementById('toggle-wait-plugin');
        const mathToggle = document.getElementById('toggle-math-plugin');
        const textToggle = document.getElementById('toggle-text-plugin');
        const factMemoryToggle = document.getElementById('toggle-fact-memory-plugin');
        const embeddingToggle = document.getElementById('toggle-default-embedding-model-plugin');
        const allowUserPluginsToggle = document.getElementById('toggle-allow-user-plugins');
        const allowGroupPluginsToggle = document.getElementById('toggle-allow-group-plugins');
        const toggles = [timeToggle, httpToggle, waitToggle, mathToggle, textToggle, factMemoryToggle, embeddingToggle, allowUserPluginsToggle, allowGroupPluginsToggle];
        // Feedback area
        let feedbackDiv = document.getElementById('core-plugin-toggles-feedback');
        if (!feedbackDiv) {
            feedbackDiv = document.createElement('div');
            feedbackDiv.id = 'core-plugin-toggles-feedback';
            feedbackDiv.className = 'mt-2';
            const togglesDiv = document.getElementById('core-plugin-toggles');
            if (togglesDiv) togglesDiv.appendChild(feedbackDiv);
        }

        // Helper to show feedback
        function showFeedback(msg, type = 'info') {
            feedbackDiv.innerHTML = `<div class="alert alert-${type} py-1 px-2 mb-0">${msg}</div>`;
            setTimeout(() => { feedbackDiv.innerHTML = ''; }, 3000);
        }

        // Fetch current settings and set toggle states
        async function loadCorePluginToggles() {
            try {
                const resp = await fetch('/api/admin/plugins/settings');
                if (!resp.ok) throw new Error('Failed to fetch plugin settings');
                const settings = await resp.json();
                if (timeToggle) timeToggle.checked = !!settings.enable_time_plugin;
                if (httpToggle) httpToggle.checked = !!settings.enable_http_plugin;
                if (waitToggle) waitToggle.checked = !!settings.enable_wait_plugin;
                if (mathToggle) mathToggle.checked = !!settings.enable_math_plugin;
                if (textToggle) textToggle.checked = !!settings.enable_text_plugin;
                if (embeddingToggle) embeddingToggle.checked = !!settings.enable_default_embedding_model_plugin;
                if (factMemoryToggle) factMemoryToggle.checked = !!settings.enable_fact_memory_plugin;
                if (allowUserPluginsToggle) allowUserPluginsToggle.checked = !!settings.allow_user_plugins;
                if (allowGroupPluginsToggle) allowGroupPluginsToggle.checked = !!settings.allow_group_plugins;
            } catch (err) {
                showFeedback('Error loading plugin toggle states: ' + err.message, 'danger');
            }
        }
        // Initial load
        loadCorePluginToggles();

        // Handler for toggle changes
        function onToggleChange() {
            // Disable toggles while saving
            toggles.forEach(t => t && (t.disabled = true));
            const payload = {
                enable_time_plugin: timeToggle ? timeToggle.checked : false,
                enable_http_plugin: httpToggle ? httpToggle.checked : false,
                enable_wait_plugin: waitToggle ? waitToggle.checked : false,
                enable_math_plugin: mathToggle ? mathToggle.checked : false,
                enable_text_plugin: textToggle ? textToggle.checked : false,
                enable_default_embedding_model_plugin: embeddingToggle ? embeddingToggle.checked : false,
                enable_fact_memory_plugin: factMemoryToggle ? factMemoryToggle.checked : false,
                allow_user_plugins: allowUserPluginsToggle ? allowUserPluginsToggle.checked : false,
                allow_group_plugins: allowGroupPluginsToggle ? allowGroupPluginsToggle.checked : false
            };
            fetch('/api/admin/plugins/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload)
            })
            .then(async resp => {
                const data = await resp.json();
                if (resp.ok) {
                    showFeedback('Plugin settings updated. Restart required to take effect.', 'success');
                } else {
                    showFeedback('Error: ' + (data.error || 'Failed to update plugin settings'), 'danger');
                }
            })
            .catch(err => {
                showFeedback('Error: ' + err.message, 'danger');
            })
            .finally(() => {
                toggles.forEach(t => t && (t.disabled = false));
            });
        }
        toggles.forEach(t => t && t.addEventListener('change', onToggleChange));

        // --- Ensure toggles always reflect backend state on Plugins tab activation ---
        // Listen for Bootstrap tab activation events
        document.querySelectorAll('button[data-bs-toggle="tab"]').forEach(tabBtn => {
            tabBtn.addEventListener('shown.bs.tab', function (event) {
                const target = event.target.getAttribute('data-bs-target');
                if (target === '#plugins') {
                    loadCorePluginToggles();
                }
            });
        });
    }

    // --- User/Group Plugin Toggles ---
    const allowUserPluginsToggle = document.getElementById('allow_user_plugins');
    const allowGroupPluginsToggle = document.getElementById('allow_group_plugins');
    let pluginSettingsFeedbackDiv = document.getElementById('plugin-settings-feedback');
    if (!pluginSettingsFeedbackDiv) {
        pluginSettingsFeedbackDiv = document.createElement('div');
        pluginSettingsFeedbackDiv.id = 'plugin-settings-feedback';
        pluginSettingsFeedbackDiv.className = 'mt-2';
        // Try to append to plugins card
        const pluginsCard = document.getElementById('user-group-plugin-toggles');
        if (pluginsCard) pluginsCard.appendChild(pluginSettingsFeedbackDiv);
    }

    function showPluginSettingsFeedback(msg, type = 'info') {
        pluginSettingsFeedbackDiv.innerHTML = `<div class="alert alert-${type} py-1 px-2 mb-0">${msg}</div>`;
        setTimeout(() => { pluginSettingsFeedbackDiv.innerHTML = ''; }, 3000);
    }

    function saveUserGroupPluginSettings() {
        // Disable toggles while saving
        if (allowUserPluginsToggle) allowUserPluginsToggle.disabled = true;
        if (allowGroupPluginsToggle) allowGroupPluginsToggle.disabled = true;
        const payload = {
            allow_user_plugins: allowUserPluginsToggle ? allowUserPluginsToggle.checked : false,
            allow_group_plugins: allowGroupPluginsToggle ? allowGroupPluginsToggle.checked : false
        };
        fetch('/api/admin/plugins/settings', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        .then(async resp => {
            const data = await resp.json();
            if (resp.ok) {
                showPluginSettingsFeedback('Plugin settings updated.', 'success');
            } else {
                showPluginSettingsFeedback('Error: ' + (data.error || 'Failed to update plugin settings'), 'danger');
            }
        })
        .catch(err => {
            showPluginSettingsFeedback('Error: ' + err.message, 'danger');
        })
        .finally(() => {
            if (allowUserPluginsToggle) allowUserPluginsToggle.disabled = false;
            if (allowGroupPluginsToggle) allowGroupPluginsToggle.disabled = false;
        });
    }

    if (allowUserPluginsToggle) {
        allowUserPluginsToggle.addEventListener('change', saveUserGroupPluginSettings);
    }
    if (allowGroupPluginsToggle) {
        allowGroupPluginsToggle.addEventListener('change', saveUserGroupPluginSettings);
    }

    // --- Agent Settings Toggles (corrected) ---
    const allowUserAgentsToggle = document.getElementById('toggle-allow-user-agents');
    const allowUserCustomAgentEndpointsToggle = document.getElementById('toggle-allow-user-custom-agent-endpoints');
    const allowGroupAgentsToggle = document.getElementById('toggle-allow-group-agents');
    const allowGroupCustomAgentEndpointsToggle = document.getElementById('toggle-allow-group-custom-agent-endpoints');
    let agentSettingsFeedbackDiv = document.getElementById('agent-settings-feedback');
    if (!agentSettingsFeedbackDiv) {
        agentSettingsFeedbackDiv = document.createElement('div');
        agentSettingsFeedbackDiv.id = 'agent-settings-feedback';
        agentSettingsFeedbackDiv.className = 'mt-2';
        const agentTogglesCard = document.getElementById('agent-toggles-card');
        if (agentTogglesCard) {
            agentTogglesCard.insertAdjacentElement('afterend', agentSettingsFeedbackDiv);
        } else {
            // Fallback to previous behavior
            (document.getElementById('agents-main-content') || document.body).appendChild(agentSettingsFeedbackDiv);
        }
    }

    function showAgentSettingsFeedback(msg, type = 'info') {
        agentSettingsFeedbackDiv.innerHTML = `<div class="alert alert-${type} py-1 px-2 mb-0">${msg}</div>`;
        setTimeout(() => { agentSettingsFeedbackDiv.innerHTML = ''; }, 3000);
    }

    // Fetch agent settings and set toggles
    async function loadAgentSettings() {
        try {
            const resp = await fetch('/api/admin/agent/settings');
            if (!resp.ok) throw new Error('Failed to fetch agent settings');
            const settings = await resp.json();
            if (allowUserAgentsToggle) allowUserAgentsToggle.checked = !!settings.allow_user_agents;
            if (allowUserCustomAgentEndpointsToggle) allowUserCustomAgentEndpointsToggle.checked = !!settings.allow_user_custom_agent_endpoints;
            if (allowGroupAgentsToggle) allowGroupAgentsToggle.checked = !!settings.allow_group_agents;
            if (allowGroupCustomAgentEndpointsToggle) allowGroupCustomAgentEndpointsToggle.checked = !!settings.allow_group_custom_agent_endpoints;
        } catch (err) {
            showAgentSettingsFeedback('Error loading agent settings: ' + err.message, 'danger');
        }
    }
    // Initial load - only if agents are enabled
    if (typeof settings !== 'undefined' && settings && settings.enable_semantic_kernel) {
        loadAgentSettings();
    }

    // Handler for toggle changes
    function saveAgentSetting(settingName, value) {
        const toggleMap = {
            'allow_user_agents': allowUserAgentsToggle,
            'allow_user_custom_agent_endpoints': allowUserCustomAgentEndpointsToggle,
            'allow_group_agents': allowGroupAgentsToggle,
            'allow_group_custom_agent_endpoints': allowGroupCustomAgentEndpointsToggle
        };
        const toggle = toggleMap[settingName];
        if (toggle) toggle.disabled = true;
        fetch(`/api/admin/agents/settings/${settingName}`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ value })
        })
        .then(async resp => {
            const data = await resp.json();
            if (resp.ok) {
                showAgentSettingsFeedback('Agent setting updated.', 'success');
            } else {
                showAgentSettingsFeedback('Error: ' + (data.error || 'Failed to update agent setting'), 'danger');
            }
        })
        .catch(err => {
            showAgentSettingsFeedback('Error: ' + err.message, 'danger');
        })
        .finally(() => {
            if (toggle) toggle.disabled = false;
        });
    }

    if (allowUserAgentsToggle) {
        allowUserAgentsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_user_agents', allowUserAgentsToggle.checked);
        });
    }
    if (allowUserCustomAgentEndpointsToggle) {
        allowUserCustomAgentEndpointsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_user_custom_agent_endpoints', allowUserCustomAgentEndpointsToggle.checked);
        });
    }
    if (allowGroupAgentsToggle) {
        allowGroupAgentsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_group_agents', allowGroupAgentsToggle.checked);
        });
    }
    if (allowGroupCustomAgentEndpointsToggle) {
        allowGroupCustomAgentEndpointsToggle.addEventListener('change', () => {
            saveAgentSetting('allow_group_custom_agent_endpoints', allowGroupCustomAgentEndpointsToggle.checked);
        });
    }

    // --- Logging Toggle ---
    const enableAppInsightsLoggingToggle = document.getElementById('enable_appinsights_global_logging');
    if (enableAppInsightsLoggingToggle) {
        enableAppInsightsLoggingToggle.addEventListener('change', () => {
            markFormAsModified();
        });
    }

    const enableGptApim = document.getElementById('enable_gpt_apim');
    if (enableGptApim) {
        enableGptApim.addEventListener('change', function () {
            document.getElementById('non_apim_gpt_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_gpt_settings').style.display = this.checked ? 'block' : 'none';
            // Toggle visibility of APIM model note and fetch step in the walkthrough
            const apimModelNote = document.getElementById('apim-model-note');
            const fetchModelsStep = document.getElementById('fetch-models-step');
            if (apimModelNote && fetchModelsStep) {
                apimModelNote.style.display = this.checked ? 'block' : 'none';
                fetchModelsStep.style.display = this.checked ? 'none' : 'block';
            }
            markFormAsModified();
        });
    }

    const enableEmbeddingApim = document.getElementById('enable_embedding_apim');
    if (enableEmbeddingApim) {
        enableEmbeddingApim.addEventListener('change', function () {
            document.getElementById('non_apim_embedding_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_embedding_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableImageGen = document.getElementById('enable_image_generation');
    if (enableImageGen) {
        enableImageGen.addEventListener('change', function () {
            document.getElementById('image_gen_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableImageGenApim = document.getElementById('enable_image_gen_apim');
    if (enableImageGenApim) {
        enableImageGenApim.addEventListener('change', function () {
            document.getElementById('non_apim_image_gen_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_image_gen_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableRedisCache = document.getElementById('enable_redis_cache');
    const redisSettingsDiv = document.getElementById('redis_cache_settings');
    if (enableRedisCache && redisSettingsDiv) {
        // Set initial state
        redisSettingsDiv.style.display = enableRedisCache.checked ? 'block' : 'none';
        enableRedisCache.addEventListener('change', function () {
            redisSettingsDiv.style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableEnhancedCitation = document.getElementById('enable_enhanced_citations');
    if (enableEnhancedCitation) {
        toggleEnhancedCitation(enableEnhancedCitation.checked);
        enableEnhancedCitation.addEventListener('change', function(){
            toggleEnhancedCitation(this.checked);
            markFormAsModified();
        });
    }

    const enableContentSafetyCheckbox = document.getElementById('enable_content_safety');
    if (enableContentSafetyCheckbox) {
        enableContentSafetyCheckbox.addEventListener('change', function() {
            const safetySettings = document.getElementById('content_safety_settings');
            safetySettings.style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableContentSafetyApim = document.getElementById('enable_content_safety_apim');
    if (enableContentSafetyApim) {
        enableContentSafetyApim.addEventListener('change', function() {
            document.getElementById('non_apim_content_safety_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_content_safety_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableWebSearch = document.getElementById('enable_web_search');
    if (enableWebSearch) {
        enableWebSearch.addEventListener('change', function () {
            document.getElementById('web_search_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableWebSearchApim = document.getElementById('enable_web_search_apim');
    if (enableWebSearchApim) {
        enableWebSearchApim.addEventListener('change', function () {
            document.getElementById('non_apim_web_search_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_web_search_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableAiSearchApim = document.getElementById('enable_ai_search_apim');
    if (enableAiSearchApim) {
        enableAiSearchApim.addEventListener('change', function () {
            document.getElementById('non_apim_ai_search_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_ai_search_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const enableDocumentIntelligenceApim = document.getElementById('enable_document_intelligence_apim');
    if (enableDocumentIntelligenceApim) {
        enableDocumentIntelligenceApim.addEventListener('change', function () {
            document.getElementById('non_apim_document_intelligence_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_document_intelligence_settings').style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const gptAuthType = document.getElementById('azure_openai_gpt_authentication_type');
    if (gptAuthType) {
        gptAuthType.addEventListener('change', function () {
            document.getElementById('gpt_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const embeddingAuthType = document.getElementById('azure_openai_embedding_authentication_type');
    if (embeddingAuthType) {
        embeddingAuthType.addEventListener('change', function () {
            document.getElementById('embedding_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const imgAuthType = document.getElementById('azure_openai_image_gen_authentication_type');
    if (imgAuthType) {
        imgAuthType.addEventListener('change', function () {
            document.getElementById('image_gen_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const contentSafetyAuthType = document.getElementById('content_safety_authentication_type');
    if (contentSafetyAuthType) {
        contentSafetyAuthType.addEventListener('change', function () {
            document.getElementById('content_safety_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const aiSearchAuthType = document.getElementById('azure_ai_search_authentication_type');
    if (aiSearchAuthType) {
        aiSearchAuthType.addEventListener('change', function () {
            document.getElementById('azure_ai_search_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const docIntelAuthType = document.getElementById('azure_document_intelligence_authentication_type');
    if (docIntelAuthType) {
        docIntelAuthType.addEventListener('change', function () {
            document.getElementById('azure_document_intelligence_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const officeAuthType = document.getElementById('office_docs_authentication_type');
    const connStrGroup = document.getElementById('office_docs_storage_conn_str_group');
    const urlGroup = document.getElementById('office_docs_storage_url_group');
    const connStrInput = document.getElementById('office_docs_storage_account_url');
    const urlInput = document.getElementById('office_docs_storage_account_blob_endpoint');

    if (officeAuthType && connStrGroup && urlGroup && connStrInput && urlInput) {
        officeAuthType.addEventListener('change', function() {
            if (this.value === 'managed_identity') {
                connStrGroup.style.display = 'none';
                urlGroup.style.display = '';
            } else {
                connStrGroup.style.display = '';
                urlGroup.style.display = 'none';
            }
            markFormAsModified();
        });
    }

    // Toggle visibility of connection string
    const toggleConnStrBtn = document.getElementById('toggle_office_conn_str');
    if (toggleConnStrBtn && connStrInput) {
        toggleConnStrBtn.addEventListener('click', function() {
            connStrInput.type = connStrInput.type === 'password' ? 'text' : 'password';
            toggleConnStrBtn.textContent = connStrInput.type === 'password' ? 'Show' : 'Hide';
        });
    }

    // Toggle visibility of blob service endpoint URL
    const toggleUrlBtn = document.getElementById('toggle_office_url');
    if (toggleUrlBtn && urlInput) {
        toggleUrlBtn.addEventListener('click', function() {
            urlInput.type = urlInput.type === 'password' ? 'text' : 'password';
            toggleUrlBtn.textContent = urlInput.type === 'password' ? 'Show' : 'Hide';
        });
    }

    const videoAuthType = document.getElementById('video_files_authentication_type');
    if (videoAuthType) {
        videoAuthType.addEventListener('change', function(){
            document.getElementById('video_files_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    const audioAuthType = document.getElementById('audio_files_authentication_type');
    if (audioAuthType) {
        audioAuthType.addEventListener('change', function(){
            document.getElementById('audio_files_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
            markFormAsModified();
        });
    }

    // Redis auth type dropdown logic
    const redisAuthType = document.getElementById('redis_auth_type');
    if (redisAuthType) {
        const redisKeyContainer = document.getElementById('redis_key_container');
        // Set initial state on load
        if (redisKeyContainer) {
            redisKeyContainer.style.display = (redisAuthType.value === 'key') ? 'block' : 'none';
        }
        redisAuthType.addEventListener('change', function () {
            if (redisKeyContainer) {
                redisKeyContainer.style.display = (this.value === 'key') ? 'block' : 'none';
            }
        });
    }

    if (enableGroupWorkspacesToggle && createGroupPermissionSettingDiv) {
        // Initial state
        createGroupPermissionSettingDiv.style.display = enableGroupWorkspacesToggle.checked ? 'block' : 'none';
        // Listener for changes
        enableGroupWorkspacesToggle.addEventListener('change', function() {
            createGroupPermissionSettingDiv.style.display = this.checked ? 'block' : 'none';
            markFormAsModified();
        });
    }

    // Enable File Sharing toggle
    const enableFileSharingToggle = document.getElementById('enable_file_sharing');
    if (enableFileSharingToggle) {
        enableFileSharingToggle.addEventListener('change', function() {
            markFormAsModified();
        });
    }
    
    // --- Workspace Dependency Validation ---
    setupWorkspaceDependencyValidation();
}

/**
 * Set up validation for workspace dependencies
 */
function setupWorkspaceDependencyValidation() {
    const userWorkspaceToggle = document.getElementById('enable_user_workspace');
    const groupWorkspaceToggle = document.getElementById('enable_group_workspaces');
    const publicWorkspaceToggle = document.getElementById('enable_public_workspaces');
    
    // Create or find notification area for workspace dependencies
    let notificationArea = document.getElementById('workspace-dependency-notifications');
    if (!notificationArea) {
        notificationArea = document.createElement('div');
        notificationArea.id = 'workspace-dependency-notifications';
        notificationArea.className = 'mb-3';
        
        // Insert at the beginning of the workspaces tab content
        const workspacesTab = document.getElementById('workspaces');
        if (workspacesTab) {
            const firstCard = workspacesTab.querySelector('.card');
            if (firstCard) {
                workspacesTab.insertBefore(notificationArea, firstCard);
            } else {
                workspacesTab.appendChild(notificationArea);
            }
        }
    }
    
    /**
     * Check if workspace dependencies are configured
     */
    function checkWorkspaceDependencies() {
        const userEnabled = userWorkspaceToggle?.checked || false;
        const groupEnabled = groupWorkspaceToggle?.checked || false;
        const publicEnabled = publicWorkspaceToggle?.checked || false;
        const workspacesEnabled = userEnabled || groupEnabled || publicEnabled;
        
        if (!workspacesEnabled) {
            notificationArea.innerHTML = '';
            return;
        }
        
        const missingDependencies = [];
        
        // Check Embeddings configuration
        const embeddingConfigured = checkEmbeddingConfiguration();
        if (!embeddingConfigured) {
            missingDependencies.push('Embeddings');
        }
        
        // Check Azure AI Search configuration
        const searchConfigured = checkAzureSearchConfiguration();
        if (!searchConfigured) {
            missingDependencies.push('Azure AI Search');
        }
        
        // Check Document Intelligence configuration
        const docIntelConfigured = checkDocumentIntelligenceConfiguration();
        if (!docIntelConfigured) {
            missingDependencies.push('Document Intelligence');
        }
        
        // Display notification if dependencies are missing
        if (missingDependencies.length > 0) {
            const enabledWorkspaces = [];
            if (userEnabled) enabledWorkspaces.push('Personal Workspaces');
            if (groupEnabled) enabledWorkspaces.push('Group Workspaces');
            if (publicEnabled) enabledWorkspaces.push('Public Workspaces');
            
            notificationArea.innerHTML = `
                <div class="alert alert-warning" role="alert">
                    <div class="d-flex align-items-start">
                        <div class="me-3">
                            <i class="bi bi-exclamation-triangle-fill text-warning" style="font-size: 1.2rem;"></i>
                        </div>
                        <div class="flex-grow-1">
                            <h6 class="alert-heading mb-2">Missing Required Configuration</h6>
                            <p class="mb-2">
                                You have enabled <strong>${enabledWorkspaces.join(', ')}</strong> but some required services are not configured.
                            </p>
                            <p class="mb-2">
                                <strong>Missing configurations:</strong> ${missingDependencies.join(', ')}
                            </p>
                            <hr class="my-2">
                            <p class="mb-0 small">
                                <strong>To fix this:</strong> Please configure the missing services in their respective tabs:
                                ${missingDependencies.includes('Embeddings') ? '<a href="#ai-models" class="alert-link text-decoration-none" onclick="activateTab(\'#ai-models\')">AI Models</a>' : ''}
                                ${missingDependencies.includes('Azure AI Search') ? '<a href="#search-extract" class="alert-link text-decoration-none" onclick="activateTab(\'#search-extract\')">Search and Extract</a>' : ''}
                                ${missingDependencies.includes('Document Intelligence') ? '<a href="#search-extract" class="alert-link text-decoration-none" onclick="activateTab(\'#search-extract\')">Search and Extract</a>' : ''}
                            </p>
                        </div>
                    </div>
                </div>
            `;
        } else {
            notificationArea.innerHTML = `
                <div class="alert alert-success" role="alert">
                    <div class="d-flex align-items-center">
                        <i class="bi bi-check-circle-fill text-success me-2"></i>
                        <strong>Workspace Configuration Complete</strong> - All required dependencies are configured.
                    </div>
                </div>
            `;
        }
    }
    
    /**
     * Check if embeddings are properly configured
     */
    function checkEmbeddingConfiguration() {
        const useApim = document.getElementById('enable_embedding_apim')?.checked || false;
        
        if (useApim) {
            const endpoint = document.getElementById('azure_apim_embedding_endpoint')?.value;
            const key = document.getElementById('azure_apim_embedding_subscription_key')?.value;
            return endpoint && endpoint.trim() !== '' && key && key.trim() !== '';
        } else {
            const endpoint = document.getElementById('azure_openai_embedding_endpoint')?.value;
            const authType = document.getElementById('azure_openai_embedding_authentication_type')?.value;
            
            if (!endpoint || endpoint.trim() === '') return false;
            
            if (authType === 'key') {
                const key = document.getElementById('azure_openai_embedding_key')?.value;
                return key && key.trim() !== '';
            }
            
            return true; // Managed identity doesn't need key
        }
    }
    
    /**
     * Check if Azure AI Search is properly configured
     */
    function checkAzureSearchConfiguration() {
        const useApim = document.getElementById('enable_ai_search_apim')?.checked || false;
        
        if (useApim) {
            const endpoint = document.getElementById('azure_apim_ai_search_endpoint')?.value;
            const key = document.getElementById('azure_apim_ai_search_subscription_key')?.value;
            return endpoint && endpoint.trim() !== '' && key && key.trim() !== '';
        } else {
            const endpoint = document.getElementById('azure_ai_search_endpoint')?.value;
            const authType = document.getElementById('azure_ai_search_authentication_type')?.value;
            
            if (!endpoint || endpoint.trim() === '') return false;
            
            if (authType === 'key') {
                const key = document.getElementById('azure_ai_search_key')?.value;
                return key && key.trim() !== '';
            }
            
            return true; // Managed identity doesn't need key
        }
    }
    
    /**
     * Check if Document Intelligence is properly configured
     */
    function checkDocumentIntelligenceConfiguration() {
        const useApim = document.getElementById('enable_document_intelligence_apim')?.checked || false;
        
        if (useApim) {
            const endpoint = document.getElementById('azure_apim_document_intelligence_endpoint')?.value;
            const key = document.getElementById('azure_apim_document_intelligence_subscription_key')?.value;
            return endpoint && endpoint.trim() !== '' && key && key.trim() !== '';
        } else {
            const endpoint = document.getElementById('azure_document_intelligence_endpoint')?.value;
            const authType = document.getElementById('azure_document_intelligence_authentication_type')?.value;
            
            if (!endpoint || endpoint.trim() === '') return false;
            
            if (authType === 'key') {
                const key = document.getElementById('azure_document_intelligence_key')?.value;
                return key && key.trim() !== '';
            }
            
            return true; // Managed identity doesn't need key
        }
    }
    
    /**
     * Helper function to activate a tab
     */
    function activateTab(tabId) {
        const tabTrigger = document.querySelector(`[data-bs-target="${tabId}"]`);
        if (tabTrigger) {
            const tab = new bootstrap.Tab(tabTrigger);
            tab.show();
        }
    }
    
    // Make activateTab globally available for the alert links
    window.activateTab = activateTab;
    
    // Add event listeners to workspace toggles
    if (userWorkspaceToggle) {
        userWorkspaceToggle.addEventListener('change', checkWorkspaceDependencies);
    }
    if (groupWorkspaceToggle) {
        groupWorkspaceToggle.addEventListener('change', checkWorkspaceDependencies);
    }
    if (publicWorkspaceToggle) {
        publicWorkspaceToggle.addEventListener('change', checkWorkspaceDependencies);
    }
    
    // Initial check
    checkWorkspaceDependencies();
}

function setupTestButtons() {

    const testGptBtn = document.getElementById('test_gpt_button');
    if (testGptBtn) {
        testGptBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_gpt_result');
            resultDiv.innerHTML = 'Testing GPT...';

            const enableApim = document.getElementById('enable_gpt_apim').checked;
            
            const payload = {
                test_type: 'gpt',
                enable_apim: enableApim,
                selected_model: gptSelected[0] || null
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_gpt_endpoint').value,
                    api_version: document.getElementById('azure_apim_gpt_api_version').value,
                    deployment: document.getElementById('azure_apim_gpt_deployment').value,
                    subscription_key: document.getElementById('azure_apim_gpt_subscription_key').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_gpt_endpoint').value,
                    auth_type: document.getElementById('azure_openai_gpt_authentication_type').value,
                    subscription_id: document.getElementById('azure_openai_gpt_subscription_id').value,
                    resource_group: document.getElementById('azure_openai_gpt_resource_group').value,
                    key: document.getElementById('azure_openai_gpt_key').value,
                    api_version: document.getElementById('azure_openai_gpt_api_version').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing GPT'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testRedisBtn = document.getElementById('test_redis_button');
    if (testRedisBtn) {
        testRedisBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_redis_result');
            resultDiv.innerHTML = 'Testing Redis...';

            const payload = {
                test_type: 'redis',
                endpoint: document.getElementById('redis_url').value,
                key: document.getElementById('redis_key').value
            };

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Redis'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }


    const testEmbeddingBtn = document.getElementById('test_embedding_button');
    if (testEmbeddingBtn) {
        testEmbeddingBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_embedding_result');
            resultDiv.innerHTML = 'Testing Embeddings...';

            const enableApim = document.getElementById('enable_embedding_apim').checked;

            const payload = {
                test_type: 'embedding',
                enable_apim: enableApim,
                selected_model: embeddingSelected[0] || null
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_embedding_endpoint').value,
                    api_version: document.getElementById('azure_apim_embedding_api_version').value,
                    deployment: document.getElementById('azure_apim_embedding_deployment').value,
                    subscription_key: document.getElementById('azure_apim_embedding_subscription_key').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_embedding_endpoint').value,
                    auth_type: document.getElementById('azure_openai_embedding_authentication_type').value,
                    subscription_id: document.getElementById('azure_openai_embedding_subscription_id').value,
                    resource_group: document.getElementById('azure_openai_embedding_resource_group').value,
                    key: document.getElementById('azure_openai_embedding_key').value,
                    api_version: document.getElementById('azure_openai_embedding_api_version').value                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Embeddings'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testImageBtn = document.getElementById('test_image_button');
    if (testImageBtn) {
        testImageBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_image_result');
            resultDiv.innerHTML = 'Testing Image Generation...';

            const enableApim = document.getElementById('enable_image_gen_apim').checked;

            const payload = {
                test_type: 'image',
                enable_apim: enableApim,
                selected_model: imageSelected[0] || null
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_image_gen_endpoint').value,
                    api_version: document.getElementById('azure_apim_image_gen_api_version').value,
                    deployment: document.getElementById('azure_apim_image_gen_deployment').value,
                    subscription_key: document.getElementById('azure_apim_image_gen_subscription_key').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_image_gen_endpoint').value,
                    auth_type: document.getElementById('azure_openai_image_gen_authentication_type').value,
                    subscription_id: document.getElementById('azure_openai_image_gen_subscription_id').value,
                    resource_group: document.getElementById('azure_openai_image_gen_resource_group').value,
                    key: document.getElementById('azure_openai_image_gen_key').value,
                    api_version: document.getElementById('azure_openai_image_gen_api_version').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Image Gen'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testSafetyBtn = document.getElementById('test_safety_button');
    if (testSafetyBtn) {
        testSafetyBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_safety_result');
            resultDiv.innerHTML = 'Testing Safety...';

            const contentSafetyEnabled = document.getElementById('enable_content_safety').checked;
            const enableApim = document.getElementById('enable_content_safety_apim').checked;

            const payload = {
                test_type: 'safety',
                enabled: contentSafetyEnabled,
                enable_apim: enableApim
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_content_safety_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_content_safety_subscription_key').value,
                    deployment: document.getElementById('azure_apim_content_safety_deployment').value,
                    api_version: document.getElementById('azure_apim_content_safety_api_version').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('content_safety_endpoint').value,
                    auth_type: document.getElementById('content_safety_authentication_type').value,
                    key: document.getElementById('content_safety_key').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Safety'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }
    const testAzureSearchBtn = document.getElementById('test_azure_ai_search_button');
    if (testAzureSearchBtn) {
        testAzureSearchBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_azure_ai_search_result');
            resultDiv.innerHTML = 'Testing Azure AI Search...';

            const enableApim = document.getElementById('enable_ai_search_apim').checked;

            const payload = {
                test_type: 'azure_ai_search',
                enable_apim: enableApim
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_ai_search_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_ai_search_subscription_key').value,
                    deployment: document.getElementById('azure_apim_ai_search_deployment').value,
                    api_version: document.getElementById('azure_apim_ai_search_api_version').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_ai_search_endpoint').value,
                    auth_type: document.getElementById('azure_ai_search_authentication_type').value,
                    key: document.getElementById('azure_ai_search_key').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Azure AI Search'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testDocIntelBtn = document.getElementById('test_azure_doc_intelligence_button');
    if (testDocIntelBtn) {
        testDocIntelBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_azure_doc_intelligence_result');
            resultDiv.innerHTML = 'Testing Document Intelligence...';

            const enableApim = document.getElementById('enable_document_intelligence_apim').checked;

            const payload = {
                test_type: 'azure_doc_intelligence',
                enable_apim: enableApim
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_document_intelligence_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_document_intelligence_subscription_key').value,
                    deployment: document.getElementById('azure_apim_document_intelligence_deployment').value,
                    api_version: document.getElementById('azure_apim_document_intelligence_api_version').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_document_intelligence_endpoint').value,
                    auth_type: document.getElementById('azure_document_intelligence_authentication_type').value,
                    key: document.getElementById('azure_document_intelligence_key').value
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<span class="text-success">${data.message}</span>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Doc Intelligence'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger">Error: ${err.message}</span>`;
            }
        });
    }

    const testVisionBtn = document.getElementById('test_multimodal_vision_button');
    if (testVisionBtn) {
        testVisionBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_multimodal_vision_result');
            resultDiv.innerHTML = '<i class="bi bi-hourglass-split me-1"></i>Testing Vision Analysis...';

            const visionModel = document.getElementById('multimodal_vision_model').value;
            
            if (!visionModel) {
                resultDiv.innerHTML = '<span class="text-danger">Please select a vision model first</span>';
                return;
            }

            const enableApim = document.getElementById('enable_gpt_apim').checked;

            const payload = {
                test_type: 'multimodal_vision',
                enable_apim: enableApim,
                vision_model: visionModel
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_gpt_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_gpt_subscription_key').value,
                    api_version: document.getElementById('azure_apim_gpt_api_version').value,
                    deployment: visionModel
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('azure_openai_gpt_endpoint').value,
                    auth_type: document.getElementById('azure_openai_gpt_authentication_type').value,
                    key: document.getElementById('azure_openai_gpt_key').value,
                    api_version: document.getElementById('azure_openai_gpt_api_version').value,
                    deployment: visionModel
                };
            }

            try {
                const resp = await fetch('/api/admin/settings/test_connection', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const data = await resp.json();
                if (resp.ok) {
                    resultDiv.innerHTML = `<div class="alert alert-success mb-0">
                        <strong><i class="bi bi-check-circle me-1"></i>Success!</strong><br>
                        ${data.message}<br>
                        <small class="text-muted">${data.details || ''}</small>
                    </div>`;
                } else {
                    resultDiv.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>${data.error || 'Error testing Vision Analysis'}</span>`;
                }
            } catch (err) {
                resultDiv.innerHTML = `<span class="text-danger"><i class="bi bi-x-circle me-1"></i>Error: ${err.message}</span>`;
            }
        });
    }
}

function toggleEnhancedCitation(isEnabled) {
    const container = document.getElementById('enhanced_citation_settings');
    if (!container) return;
    container.style.display = isEnabled ? 'block' : 'none';
}


function switchTab(event, tabButtonId) {
    event.preventDefault();
    const triggerEl = document.getElementById(tabButtonId);
    const tabObj = new bootstrap.Tab(triggerEl);
    tabObj.show();
  }

function togglePassword(btnId, inputId) {
    const btn = document.getElementById(btnId);
    const inp = document.getElementById(inputId);
    if (btn && inp) {
        btn.addEventListener('click', function () {
            if (inp.type === 'password') {
                inp.type = 'text';
                this.textContent = 'Hide';
            } else {
                inp.type = 'password';
                this.textContent = 'Show';
            }
        });
    }
}

// --- Video Indexer Settings toggle ---
const videoSupportToggle = document.getElementById('enable_video_file_support');
const videoIndexerDiv    = document.getElementById('video_indexer_settings');
if (videoSupportToggle && videoIndexerDiv) {
  // on load
  videoIndexerDiv.style.display = videoSupportToggle.checked ? 'block' : 'none';
  // on change
  videoSupportToggle.addEventListener('change', () => {
    videoIndexerDiv.style.display = videoSupportToggle.checked ? 'block' : 'none';
    markFormAsModified();
  });
}

// --- Speech Service Settings toggle ---
const audioSupportToggle  = document.getElementById('enable_audio_file_support');
const audioServiceDiv     = document.getElementById('audio_service_settings');
if (audioSupportToggle && audioServiceDiv) {
  // initial visibility
  audioServiceDiv.style.display = audioSupportToggle.checked ? 'block' : 'none';
  audioSupportToggle.addEventListener('change', () => {
    audioServiceDiv.style.display = audioSupportToggle.checked ? 'block' : 'none';
    markFormAsModified();
  });
}

// Metadata Extraction UI
const extractToggle = document.getElementById('enable_extract_meta_data');
const extractModelDiv = document.getElementById('metadata_extraction_model_settings');
const extractSelect   = document.getElementById('metadata_extraction_model');

function populateExtractionModels() {
  // remember previously chosen value
  const prev = extractSelect.getAttribute('data-prev') || '';

  // clear out old options
  extractSelect.innerHTML = '';

  if (document.getElementById('enable_gpt_apim').checked) {
    // use comma-separated APIM deployments
    const text = document.getElementById('azure_apim_gpt_deployment').value || '';
    text.split(',')
        .map(s => s.trim())
        .filter(s => s)
        .forEach(d => {
          const opt = new Option(d, d);
          extractSelect.add(opt);
        });
  } else {
    // use direct GPT selected deployments
    (window.gptSelected || []).forEach(m => {
      const label = `${m.deploymentName} (${m.modelName})`;
      const opt = new Option(label, m.deploymentName);
      extractSelect.add(opt);
    });
  }

  // restore previous
  extractSelect.value = prev;
}

if (extractToggle) {
  // show/hide the model dropdown
  extractModelDiv.style.display = extractToggle.checked ? 'block' : 'none';
  extractToggle.addEventListener('change', () => {
    extractModelDiv.style.display = extractToggle.checked ? 'block' : 'none';
    markFormAsModified();
  });
}

// Multi-Modal Vision UI
const visionToggle = document.getElementById('enable_multimodal_vision');
const visionModelDiv = document.getElementById('multimodal_vision_model_settings');
const visionSelect = document.getElementById('multimodal_vision_model');

function populateVisionModels() {
  if (!visionSelect) return;
  
  // remember previously chosen value
  const prev = visionSelect.getAttribute('data-prev') || '';

  // clear out old options (except the placeholder)
  visionSelect.innerHTML = '<option value="">Select a vision-capable model...</option>';

  if (document.getElementById('enable_gpt_apim').checked) {
    // use comma-separated APIM deployments
    const text = document.getElementById('azure_apim_gpt_deployment').value || '';
    text.split(',')
        .map(s => s.trim())
        .filter(s => s)
        .forEach(d => {
          const opt = new Option(d, d);
          visionSelect.add(opt);
        });
  } else {
    // use direct GPT selected deployments - filter for vision-capable models
    (window.gptSelected || []).forEach(m => {
      // Only include models with vision capabilities
      // Vision-enabled models per Azure OpenAI docs:
      // - o-series reasoning models (o1, o3, etc.)
      // - GPT-5 series
      // - GPT-4.1 series
      // - GPT-4.5
      // - GPT-4o series (gpt-4o, gpt-4o-mini)
      // - GPT-4 vision models (gpt-4-vision, gpt-4-turbo-vision)
      const modelNameLower = (m.modelName || '').toLowerCase();
      const isVisionCapable = 
        modelNameLower.includes('vision') ||           // gpt-4-vision, gpt-4-turbo-vision
        modelNameLower.includes('gpt-4o') ||           // gpt-4o, gpt-4o-mini
        modelNameLower.includes('gpt-4.1') ||          // gpt-4.1 series
        modelNameLower.includes('gpt-4.5') ||          // gpt-4.5
        modelNameLower.includes('gpt-5') ||            // gpt-5 series
        modelNameLower.match(/^o\d+/) ||               // o1, o3, etc. (o-series)
        modelNameLower.includes('o1-') ||              // o1-preview, o1-mini
        modelNameLower.includes('o3-');                // o3-mini, etc.
      
      if (isVisionCapable) {
        const label = `${m.deploymentName} (${m.modelName})`;
        const opt = new Option(label, m.deploymentName);
        visionSelect.add(opt);
      }
    });
  }

  // restore previous
  if (prev) {
    visionSelect.value = prev;
  }
}

if (visionToggle && visionModelDiv) {
  // show/hide the model dropdown
  visionModelDiv.style.display = visionToggle.checked ? 'block' : 'none';
  visionToggle.addEventListener('change', () => {
    visionModelDiv.style.display = visionToggle.checked ? 'block' : 'none';
    markFormAsModified();
  });
}

// Listen for vision model selection changes
if (visionSelect) {
  visionSelect.addEventListener('change', () => {
    // Update data-prev to remember the selection
    visionSelect.setAttribute('data-prev', visionSelect.value);
    markFormAsModified();
  });
}

// when APIM‐toggle flips, repopulate
const apimToggle = document.getElementById('enable_gpt_apim');
if (apimToggle) {
  apimToggle.addEventListener('change', () => {
    populateExtractionModels();
    populateVisionModels();
  });
}

// on load, stash previous & populate
document.addEventListener('DOMContentLoaded', () => {
  if (extractSelect) {
    extractSelect.setAttribute('data-prev', extractSelect.value);
    populateExtractionModels();
  }
  if (visionSelect) {
    visionSelect.setAttribute('data-prev', visionSelect.value);
    populateVisionModels();
  }
});


document.addEventListener('DOMContentLoaded', () => {
    ['user','group','public'].forEach(type => {
      const warnDiv     = document.getElementById(`index-warning-${type}`);
      const missingSpan = document.getElementById(`missing-fields-${type}`);
      const fixBtn      = document.getElementById(`fix-${type}-index-btn`);
  
      // 1) check for missing fields
      fetch('/api/admin/settings/check_index_fields', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        credentials: 'same-origin',
        body: JSON.stringify({ indexType: type })
      })
      .then(r => {
        if (!r.ok) {
          return r.json().then(errorData => {
            throw new Error(errorData.error || `HTTP ${r.status}: ${r.statusText}`);
          });
        }
        return r.json();
      })
      .then(response => {
        if (response.missingFields && response.missingFields.length > 0) {
          missingSpan.textContent = response.missingFields.join(', ');
          warnDiv.style.display = 'block';
          if (fixBtn) {
            fixBtn.textContent = `Fix ${type} Index Fields`;
            fixBtn.style.display = 'inline-block';
          }
        } else if (response.indexExists) {
          // Index exists and is complete
          if (warnDiv) warnDiv.style.display = 'none';
          console.log(`${type} index is properly configured`);
        }
      })
      .catch(err => {
        console.warn(`Checking ${type} index fields:`, err.message);
        
        // Check if this is an index not found error
        if (err.message.includes('does not exist yet') || err.message.includes('not found')) {
          // Show a different message for missing index
          if (warnDiv && missingSpan && fixBtn) {
            missingSpan.textContent = `Index "${type}" does not exist yet`;
            warnDiv.style.display = 'block';
            fixBtn.textContent = `Create ${type} Index`;
            fixBtn.style.display = 'inline-block';
            fixBtn.dataset.action = 'create';
          }
        } else if (err.message.includes('not configured')) {
          // Azure AI Search not configured
          if (warnDiv && missingSpan) {
            missingSpan.textContent = 'Azure AI Search not configured';
            warnDiv.style.display = 'block';
            if (fixBtn) fixBtn.style.display = 'none';
          }
        } else {
          // Hide the warning div for other errors
          if (warnDiv) warnDiv.style.display = 'none';
        }
      });
  
      // 2) wire up the “fix” button
      fixBtn.addEventListener('click', () => {
        fixBtn.disabled = true;
        const action = fixBtn.dataset.action || 'fix';
        const endpoint = action === 'create' ? '/api/admin/settings/create_index' : '/api/admin/settings/fix_index_fields';
        const actionText = action === 'create' ? 'Creating' : 'Fixing';
        
        fixBtn.textContent = `${actionText}...`;
        
        fetch(endpoint, {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json'
          },
          credentials: 'same-origin',
          body: JSON.stringify({ indexType: type })
        })
        .then(r => {
          if (!r.ok) {
            return r.json().then(errorData => {
              throw new Error(errorData.error || `HTTP ${r.status}: ${r.statusText}`);
            });
          }
          return r.json();
        })
        .then(resp => {
          if (resp.status === 'success') {
            alert(resp.message || `Successfully ${action === 'create' ? 'created' : 'fixed'} ${type} index!`);
            window.location.reload();
          } else {
            alert(`Failed to ${action} ${type} index: ${resp.error}`);
            fixBtn.disabled = false;
            fixBtn.textContent = `${action === 'create' ? 'Create' : 'Fix'} ${type} Index`;
          }
        })
        .catch(err => {
          alert(`Error ${action === 'create' ? 'creating' : 'fixing'} ${type} index: ${err.message || err}`);
          fixBtn.disabled = false;
          fixBtn.textContent = `${action === 'create' ? 'Create' : 'Fix'} ${type} Index`;
        });
      });
    });
  });
  

togglePassword('toggle_gpt_key', 'azure_openai_gpt_key');
togglePassword('toggle_embedding_key', 'azure_openai_embedding_key');
togglePassword('toggle_image_gen_key', 'azure_openai_image_gen_key');
togglePassword('toggle_content_safety_key', 'content_safety_key');
togglePassword('toggle_search_key', 'azure_ai_search_key');
togglePassword('toggle_docintel_key', 'azure_document_intelligence_key');
togglePassword('toggle_azure_apim_gpt_subscription_key', 'azure_apim_gpt_subscription_key');
togglePassword('toggle_azure_apim_embedding_subscription_key', 'azure_apim_embedding_subscription_key');
togglePassword('toggle_azure_apim_image_gen_subscription_key', 'azure_apim_image_gen_subscription_key');
togglePassword('toggle_azure_apim_content_safety_subscription_key', 'azure_apim_content_safety_subscription_key');
togglePassword('toggle_azure_apim_web_search_subscription_key', 'azure_apim_web_search_subscription_key');
togglePassword('toggle_azure_apim_ai_search_subscription_key', 'azure_apim_ai_search_subscription_key');
togglePassword('toggle_azure_apim_document_intelligence_subscription_key', 'azure_apim_document_intelligence_subscription_key');
togglePassword('toggle_office_docs_key', 'office_docs_key');
togglePassword('toggle_video_files_key', 'video_files_key');
togglePassword('toggle_audio_files_key', 'audio_files_key');
togglePassword('toggle_office_conn_str', 'office_docs_storage_account_blob_endpoint');
togglePassword('toggle_video_conn_str', 'video_files_storage_account_url');
togglePassword('toggle_audio_conn_str', 'audio_files_storage_account_url');
togglePassword('toggle_video_indexer_api_key', 'video_indexer_api_key');
togglePassword('toggle_speech_service_key', 'speech_service_key');
togglePassword('toggle_redis_key', 'redis_key');
togglePassword('toggle_azure_apim_redis_subscription_key', 'azure_apim_redis_subscription_key');

/**
 * Checks if this is a first-time setup based on critical settings
 * @returns {boolean} True if this appears to be a first-time setup
 */
function isFirstTimeSetup() {
    // Check for critical settings that would indicate a first-time setup
    
    // 1. No GPT models selected
    if (!gptSelected || gptSelected.length === 0) {
        return true;
    }
    
    // 2. No embedding models selected but workspaces enabled
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    
    if ((workspaceEnabled || groupsEnabled) && 
        (!embeddingSelected || embeddingSelected.length === 0)) {
        return true;
    }
    
    // 3. Check if GPT endpoint is empty
    const useGptApim = document.getElementById('enable_gpt_apim')?.checked || false;
    
    if (!useGptApim) {
        const gptEndpoint = document.getElementById('azure_openai_gpt_endpoint')?.value;
        if (!gptEndpoint) {
            return true;
        }
    } else {
        const apimEndpoint = document.getElementById('azure_apim_gpt_endpoint')?.value;
        if (!apimEndpoint) {
            return true;
        }
    }
    
    // Not first time setup
    return false;
}

/**
 * Setup the walkthrough for first-time configuration
 */
function setupSettingsWalkthrough() {
    console.log("Setting up walkthrough...");
    
    // Setup the walkthrough buttons first thing
    setupWalkthroughButtons();
    
    // Check if this is a first-time setup
    if (isFirstTimeSetup()) {
        // Auto-show the walkthrough for first-time setup
        setTimeout(() => {
            showWalkthrough();
        }, 500); // Small delay to ensure DOM is ready
    }
    
    // Setup the manual walkthrough button
    const walkthroughBtn = document.getElementById('launch-walkthrough-btn');
    if (walkthroughBtn) {
        // Remove any existing listeners to prevent duplicates
        const newWalkthroughBtn = walkthroughBtn.cloneNode(true);
        if (walkthroughBtn.parentNode) {
            walkthroughBtn.parentNode.replaceChild(newWalkthroughBtn, walkthroughBtn);
        }
        
        // Add new event listener
        newWalkthroughBtn.addEventListener('click', function(e) {
            e.preventDefault();
            e.stopPropagation();
            console.log("Walkthrough button clicked");
            showWalkthrough();
        });
    } else {
        console.error("Walkthrough button not found in the DOM");
    }
    
    // Setup the close button
    const closeBtn = document.getElementById('close-walkthrough-btn');
    if (closeBtn) {
        const newCloseBtn = closeBtn.cloneNode(true);
        if (closeBtn.parentNode) {
            closeBtn.parentNode.replaceChild(newCloseBtn, closeBtn);
        }
        newCloseBtn.addEventListener('click', hideWalkthrough);
    }
}

/**
 * Shows the walkthrough container and resets to the first step
 */
function showWalkthrough() {
    try {
        console.log("Showing walkthrough");
        const walkthroughContainer = document.getElementById('settings-walkthrough-container');
        if (!walkthroughContainer) {
            console.error("Walkthrough container not found!");
            return;
        }
        
        // Make sure walkthrough button events are working
        setupWalkthroughButtons();
        
        // Show the container
        walkthroughContainer.style.display = 'block';
        
        // Sync walkthrough toggles with actual form toggles
        syncWalkthroughToggles();
        
        // Check if GPT APIM is enabled and update the model note visibility
        const enableGptApim = document.getElementById('enable_gpt_apim');
        if (enableGptApim) {
            const apimModelNote = document.getElementById('apim-model-note');
            const fetchModelsStep = document.getElementById('fetch-models-step');
            if (apimModelNote && fetchModelsStep) {
                apimModelNote.style.display = enableGptApim.checked ? 'block' : 'none';
                fetchModelsStep.style.display = enableGptApim.checked ? 'none' : 'block';
            }
        }
        
        // Reset to first step when launched
        setTimeout(() => {
            try {
                navigateToWalkthroughStep(1);
            } catch (err) {
                console.error("Error navigating to first walkthrough step:", err);
            }
        }, 100);
        
        // Setup field change listeners for automatic validation
        setupWalkthroughFieldListeners();
    } catch (err) {
        console.error("Error showing walkthrough:", err);
    }
}

/**
 * Make sure walkthrough navigation buttons are properly set up
 */
function setupWalkthroughButtons() {
    const nextButton = document.getElementById('walkthrough-next-btn');
    if (nextButton) {
        nextButton.onclick = function() {
            const currentStep = getCurrentWalkthroughStep();
            console.log("Next button clicked, current step:", currentStep);
            validateAndMoveToNextStep(currentStep);
        };
    }
    
    const prevButton = document.getElementById('walkthrough-prev-btn');
    if (prevButton) {
        prevButton.onclick = navigatePreviousStep;
    }
    
    const finishButton = document.getElementById('walkthrough-finish-btn');
    if (finishButton) {
        finishButton.onclick = finishSetupAndSave;
    }
}

/**
 * Synchronizes toggle states between the walkthrough and the main form
 */
function syncWalkthroughToggles() {
    const syncToggles = [
        // Content safety toggle removed from walkthrough
    ];
    
    syncToggles.forEach(pair => {
        const walkthroughToggle = document.getElementById(pair.walkthrough);
        const formToggle = document.getElementById(pair.form);
        if (walkthroughToggle && formToggle) {
            // Set walkthrough toggle to match form toggle
            walkthroughToggle.checked = formToggle.checked;
        }
    });
}

/**
 * Hides the walkthrough container
 */
function hideWalkthrough() {
    const walkthroughContainer = document.getElementById('settings-walkthrough-container');
    if (walkthroughContainer) {
        walkthroughContainer.style.display = 'none';
    }
}

/**
 * Navigate to the specified step in the walkthrough
 * @param {number} stepNumber - The step number to navigate to
 */
function navigateToWalkthroughStep(stepNumber) {
    // Get all steps and total count
    const steps = document.querySelectorAll('.walkthrough-step');
    const totalSteps = steps.length;
    
    // Validate step number
    if (stepNumber < 1) stepNumber = 1;
    if (stepNumber > totalSteps) stepNumber = totalSteps;
    
    // Check if we should skip this step (based on workspace and feature enablement)
    const shouldSkipStep = shouldSkipWalkthroughStep(stepNumber);
    if (shouldSkipStep && stepNumber < totalSteps && stepNumber > 1) {
        // Recursively navigate to next applicable step
        if (stepNumber > getCurrentWalkthroughStep()) {
            // Moving forward - go to next applicable step
            navigateToWalkthroughStep(findNextApplicableStep(stepNumber));
            return;
        } else {
            // Moving backward - go to previous applicable step
            navigateToWalkthroughStep(findPreviousApplicableStep(stepNumber));
            return;
        }
    }
    
    // Hide all steps
    steps.forEach(step => {
        step.style.display = 'none';
    });
    
    // Show the requested step
    const stepElement = document.getElementById(`walkthrough-step-${stepNumber}`);
    if (stepElement) {
        stepElement.style.display = 'block';
    }
    
    // Update the progress indicator - calculate visible steps
    const availableSteps = calculateAvailableWalkthroughSteps();
    const stepPosition = availableSteps.indexOf(stepNumber) + 1;
    const totalAvailableSteps = availableSteps.length;
    
    const progressBar = document.getElementById('walkthrough-progress');
    if (progressBar) {
        progressBar.style.width = `${(stepPosition / totalAvailableSteps) * 100}%`;
        progressBar.setAttribute('aria-valuenow', stepPosition);
    }
    
    // Handle special tab navigation based on step
    handleTabNavigation(stepNumber);
    
    // Update prev/next buttons
    const prevBtn = document.getElementById('walkthrough-prev-btn');
    const nextBtn = document.getElementById('walkthrough-next-btn');
    const finishBtn = document.getElementById('walkthrough-finish-btn');
    
    if (prevBtn) prevBtn.style.display = stepNumber === 1 ? 'none' : 'inline-block';
    
    if (nextBtn && finishBtn) {
        nextBtn.style.display = stepNumber === totalSteps ? 'none' : 'inline-block';
        finishBtn.style.display = stepNumber === totalSteps ? 'inline-block' : 'none';
    }
    
    // Update completion status for this step
    updateStepCompletionStatus(stepNumber);
    
    // Dispatch a custom event to notify that the step has changed
    const event = new CustomEvent('walkthroughStepChanged', { 
        detail: { step: stepNumber, totalSteps: totalSteps } 
    });
    document.getElementById('settings-walkthrough-container')?.dispatchEvent(event);
}

/**
 * Get the current step displayed in the walkthrough
 * @returns {number} Current step number or 1 if none found
 */
function getCurrentWalkthroughStep() {
    const currentStepElem = document.querySelector('.walkthrough-step:not([style*=\'display: none\'])');
    if (currentStepElem) {
        return parseInt(currentStepElem.id?.split('-')[2]) || 1;
    }
    return 1;
}

/**
 * Calculate which walkthrough steps should be available based on current settings
 * @returns {number[]} Array of step numbers that should be available
 */
function calculateAvailableWalkthroughSteps() {
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    const workspacesEnabled = workspaceEnabled || groupsEnabled;
    
    const videoEnabled = document.getElementById('enable_video_file_support')?.checked || false;
    const audioEnabled = document.getElementById('enable_audio_file_support')?.checked || false;
    
    const availableSteps = [1, 2, 3, 4]; // Base steps always available
    
    // Include workspace-dependent steps if workspaces enabled
    if (workspacesEnabled) {
        availableSteps.push(5, 6, 7); // Embedding, AI Search, Doc Intelligence
        
        if (videoEnabled) {
            availableSteps.push(8); // Video support
        }
        
        if (audioEnabled) {
            availableSteps.push(9); // Audio support
        }
    }
    
    // Optional steps always available
    availableSteps.push(10, 11, 12); // Safety, Feedback, Enhanced Citations
    
    return availableSteps.sort((a, b) => a - b); // Ensure steps are in order
}

/**
 * Determine if we should skip a particular walkthrough step
 * @param {number} stepNumber - The step to check
 * @returns {boolean} True if the step should be skipped, false otherwise
 */
function shouldSkipWalkthroughStep(stepNumber) {
    const availableSteps = calculateAvailableWalkthroughSteps();
    return !availableSteps.includes(stepNumber);
}

/**
 * Find the next applicable step based on enabled features
 * @param {number} currentStep - The current step number
 * @returns {number} The next applicable step number or -1 if none found
 */

function findNextApplicableStep(currentStep) {
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    const workspacesEnabled = workspaceEnabled || groupsEnabled;
    
    // Start checking from the next step
    let nextStep = currentStep + 1;
    
    // Maximum step to avoid infinite loop
    const maxSteps = 12;
    
    while (nextStep <= maxSteps) {
        // Check if this step is applicable based on conditions
        switch (nextStep) {
            case 5: // Embedding settings
            case 6: // AI Search settings 
            case 7: // Document Intelligence settings
                if (!workspacesEnabled) {
                    // Skip these steps if workspaces not enabled
                    nextStep++;
                    continue;
                }
                return nextStep;
                
            case 8: // Video support
                const videoEnabled = document.getElementById('enable_video_file_support')?.checked || false;
                if (!workspacesEnabled || !videoEnabled) {
                    // Skip this step if workspaces not enabled or video not enabled
                    nextStep++;
                    continue;
                }
                return nextStep;
                
            case 9: // Audio support
                const audioEnabled = document.getElementById('enable_audio_file_support')?.checked || false;
                if (!workspacesEnabled || !audioEnabled) {
                    // Skip this step if workspaces not enabled or audio not enabled
                    nextStep++;
                    continue;
                }
                return nextStep;
                
            default:
                // All other steps are always applicable
                return nextStep;
        }
    }
    
    // If we've gone past all steps, return -1
    return -1;
}

/**
 * Find the previous applicable step before a given step
 * @param {number} currentStep - Current step number
 * @returns {number} Previous applicable step number or 1 (first step) if none found
 */
function findPreviousApplicableStep(currentStep) {
    const availableSteps = calculateAvailableWalkthroughSteps();
    
    // Find the first available step before the current one (in reverse)
    for (let i = availableSteps.length - 1; i >= 0; i--) {
        if (availableSteps[i] < currentStep) {
            return availableSteps[i];
        }
    }
    
    return 1; // Default to first step if no previous step found
}

/**
 * Navigate to the appropriate tab based on the walkthrough step
 * @param {number} stepNumber - The current step number
 */
function handleTabNavigation(stepNumber) {
    // Map steps to tabs that need to be activated
    const stepToTab = {
        1: 'general-tab',     // App title and logo (General tab)
        2: 'ai-models-tab',   // GPT settings (now in AI Models tab)
        3: 'ai-models-tab',   // GPT model selection (now in AI Models tab)
        4: 'workspaces-tab',  // Workspace and groups settings
        5: 'ai-models-tab',   // Embedding settings (now in AI Models tab)
        6: 'search-extract-tab', // AI Search settings
        7: 'search-extract-tab', // Document Intelligence settings
        8: 'workspaces-tab',  // Video support
        9: 'workspaces-tab',  // Audio support
        10: 'safety-tab',     // Content safety
        11: 'system-tab',     // User feedback and archiving (renamed from other-tab)
        12: 'citation-tab'    // Enhanced Citations and Image Generation
    };
    
    // Activate the appropriate tab
    const tabId = stepToTab[stepNumber];
    if (tabId) {
        const tab = document.getElementById(tabId);
        if (tab) {
            // Use bootstrap Tab to show the tab
            const bootstrapTab = new bootstrap.Tab(tab);
            bootstrapTab.show();
            
            // Scroll to the relevant section after a small delay to allow tab to switch
            setTimeout(() => {
                // For tabs that need to jump to specific sections
                scrollToRelevantSection(stepNumber, tabId);
            }, 300);
        }
    }
}

/**
 * Scroll to relevant section within a tab based on the step
 * @param {number} stepNumber - The current step number
 * @param {string} tabId - The ID of the tab that was activated
 */
function scrollToRelevantSection(stepNumber, tabId) {
    // Define which sections to scroll to for each step
    let targetElement = null;
    
    switch (stepNumber) {
        case 4: // Workspaces toggle section
            targetElement = document.getElementById('enable_user_workspace')?.closest('.card');
            break;
        case 8: // Video file support
            targetElement = document.getElementById('enable_video_file_support')?.closest('.form-group');
            break;
        case 9: // Audio file support
            targetElement = document.getElementById('enable_audio_file_support')?.closest('.form-group');
            break;
        default:
            // For other steps, no specific scrolling
            break;
    }
    
    // If we found a target element, scroll to it
    if (targetElement) {
        targetElement.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }
}

/**
 * Check if a step is complete by validating its required fields
 * @param {number} stepNumber - The step number to validate
 * @returns {boolean} True if the step is complete, false otherwise
 */
function isStepComplete(stepNumber) {
    const workspaceEnabled = document.getElementById('enable_user_workspace')?.checked || false;
    const groupsEnabled = document.getElementById('enable_group_workspaces')?.checked || false;
    const workspacesEnabled = workspaceEnabled || groupsEnabled;
    
    switch (stepNumber) {
        case 1: // App title and logo - always complete (optional)
            return true;
            
        case 2: // GPT settings
            // Check if GPT endpoint is configured when required
            if (!document.getElementById('enable_gpt_apim').checked) {
                const endpoint = document.getElementById('azure_openai_gpt_endpoint').value;
                const authType = document.getElementById('azure_openai_gpt_authentication_type').value;
                const key = document.getElementById('azure_openai_gpt_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_gpt_endpoint').value;
                const apimKey = document.getElementById('azure_apim_gpt_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            return true;
            
        case 3: // GPT model selection
            if (!document.getElementById('enable_gpt_apim').checked) {
                // For direct Azure OpenAI, check if models are selected
                return gptSelected && gptSelected.length > 0;
            } else {
                // For APIM, check if deployment field is filled
                const apimDeployment = document.getElementById('azure_apim_gpt_deployment')?.value;
                return apimDeployment && apimDeployment.trim() !== '';
            }
            
        case 4: // Workspace and groups settings - always complete (optional)
            return true;
            
        case 5: // Embedding settings (if workspace or groups enabled)
            if (!workspacesEnabled) return true; // Not required if workspaces not enabled
            
            if (!document.getElementById('enable_embedding_apim').checked) {
                const endpoint = document.getElementById('azure_openai_embedding_endpoint').value;
                const authType = document.getElementById('azure_openai_embedding_authentication_type').value;
                const key = document.getElementById('azure_openai_embedding_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_embedding_endpoint').value;
                const apimKey = document.getElementById('azure_apim_embedding_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            
            // Also check if embedding models are selected or APIM deployment is specified
            if (!document.getElementById('enable_embedding_apim').checked) {
                // For direct Azure OpenAI, check models
                if (embeddingSelected.length === 0) return false;
            } else {
                // For APIM, check deployment field
                const apimDeployment = document.getElementById('azure_apim_embedding_deployment')?.value;
                if (!apimDeployment || apimDeployment.trim() === '') return false;
            }
            
            return true;
            
        case 6: // AI Search settings
            if (!workspacesEnabled) return true; // Not required if workspaces not enabled
            
            if (!document.getElementById('enable_ai_search_apim').checked) {
                const endpoint = document.getElementById('azure_ai_search_endpoint').value;
                const authType = document.getElementById('azure_ai_search_authentication_type').value;
                const key = document.getElementById('azure_ai_search_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_ai_search_endpoint').value;
                const apimKey = document.getElementById('azure_apim_ai_search_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            return true;
            
        case 7: // Document Intelligence settings
            if (!workspacesEnabled) return true; // Not required if workspaces not enabled
            
            if (!document.getElementById('enable_document_intelligence_apim').checked) {
                const endpoint = document.getElementById('azure_document_intelligence_endpoint').value;
                const authType = document.getElementById('azure_document_intelligence_authentication_type').value;
                const key = document.getElementById('azure_document_intelligence_key').value;
                
                if (!endpoint) return false;
                if (authType === 'key' && !key) return false;
            } else {
                const apimEndpoint = document.getElementById('azure_apim_document_intelligence_endpoint').value;
                const apimKey = document.getElementById('azure_apim_document_intelligence_subscription_key').value;
                
                if (!apimEndpoint) return false;
                if (!apimKey) return false;
            }
            return true;
            
        case 8: // Video support
            const videoEnabled = document.getElementById('enable_video_file_support').checked || false;
            
            // If workspaces not enabled or video not enabled, it's always complete
            if (!workspacesEnabled || !videoEnabled) return true;
            
            // Otherwise check settings
            const videoEndpoint = document.getElementById('video_indexer_endpoint')?.value;
            const videoLocation = document.getElementById('video_indexer_location')?.value;
            const videoAccountId = document.getElementById('video_indexer_account_id')?.value;
            
            return videoLocation && videoAccountId && videoEndpoint;
            
        case 9: // Audio support
            const audioEnabled = document.getElementById('enable_audio_file_support').checked || false;
            
            // If workspaces not enabled or audio not enabled, it's always complete
            if (!workspacesEnabled || !audioEnabled) return true;
            
            // Otherwise check settings
            const speechEndpoint = document.getElementById('speech_service_endpoint')?.value;
            const speechKey = document.getElementById('speech_service_key')?.value;
            
            return speechEndpoint && speechKey;
            
        case 10: // Content safety - always complete (optional)
        case 11: // User feedback and archiving - always complete (optional)
        case 12: // Enhanced Citations and Image Generation - always complete (optional)
            return true;
            
        default:
            return true; // Default to true for any unknown steps
    }
}

/**
 * Update UI to show completion status for a step
 * @param {number} stepNumber - The step number to update
 */
function updateStepCompletionStatus(stepNumber) {
    const isComplete = isStepComplete(stepNumber);
    const stepElement = document.getElementById(`walkthrough-step-${stepNumber}`);
    if (!stepElement) return;
    
    // Find badge elements in this step
    const badges = stepElement.querySelectorAll('.badge.bg-danger');
    const optionalBadges = stepElement.querySelectorAll('.badge.bg-secondary');
    const requirementAlert = stepElement.querySelector('.alert-danger');
    const optionalAlert = stepElement.querySelector('.alert-info');
    
    // Update next button state
    const nextButton = document.getElementById('walkthrough-next-btn');
    if (nextButton) {
        if (isComplete) {
            nextButton.classList.remove('btn-secondary');
            nextButton.classList.add('btn-primary');
            nextButton.disabled = false;
        } else {
            nextButton.classList.remove('btn-primary');
            nextButton.classList.add('btn-secondary');
            nextButton.disabled = true;
        }
    }
    
    // Check if optional features are enabled/configured for this step
    const optionalFeaturesEnabled = checkOptionalFeaturesEnabled(stepNumber);
    
    // Update required badges and alerts if step is complete
    if (isComplete) {
        // Update badge status for required items
        badges.forEach(badge => {
            badge.classList.remove('bg-danger');
            badge.classList.add('bg-success');
            badge.textContent = 'Complete';
        });
        
        // Update or hide the requirement alert
        if (requirementAlert) {
            requirementAlert.classList.remove('alert-danger');
            requirementAlert.classList.add('alert-success');
            requirementAlert.innerHTML = '<strong>Complete:</strong> Configuration finished for this step.';
        }
    } else {
        // Ensure badges show required status
        badges.forEach(badge => {
            badge.classList.remove('bg-success');
            badge.classList.add('bg-danger');
            badge.textContent = 'Required';
        });
        
        // Reset requirement alert if needed
        if (requirementAlert && requirementAlert.classList.contains('alert-success')) {
            requirementAlert.classList.remove('alert-success');
            requirementAlert.classList.add('alert-danger');
            
            // Reset alert text based on step number
            switch (stepNumber) {
                case 2:
                    requirementAlert.innerHTML = '<strong>Required:</strong> GPT API configuration is required for Simple Chat to function.';
                    break;
                case 3:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Select at least one GPT model for users to use.';
                    break;
                case 5:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Embedding API configuration is required if workspaces are enabled.';
                    break;
                case 6:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Azure AI Search is required if workspaces are enabled.';
                    break;
                case 7:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Document Intelligence is required if workspaces are enabled.';
                    break;
                case 8:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Video support configuration is required if workspaces are enabled.';
                    break;
                case 9:
                    requirementAlert.innerHTML = '<strong>Required:</strong> Audio support configuration is required if workspaces are enabled.';
                    break;
            }
        }
    }
    
    // Update optional features status if they're enabled/configured
    if (optionalFeaturesEnabled) {
        // Update optional badges to show as complete
        optionalBadges.forEach(badge => {
            badge.classList.remove('bg-secondary');
            badge.classList.add('bg-success');
            badge.textContent = 'Complete';
        });
        
        // Update optional alert if present
        if (optionalAlert) {
            optionalAlert.classList.remove('alert-info');
            optionalAlert.classList.add('alert-success');
            optionalAlert.innerHTML = '<strong>Complete:</strong> Optional features configured successfully.';
        }
    } else {
        // Keep optional badges as is
        optionalBadges.forEach(badge => {
            badge.classList.remove('bg-success');
            badge.classList.add('bg-secondary');
            badge.textContent = 'Optional';
        });
        
        // Reset optional alert if it was changed
        if (optionalAlert && optionalAlert.classList.contains('alert-success')) {
            optionalAlert.classList.remove('alert-success');
            optionalAlert.classList.add('alert-info');
            
            // Reset optional alert text based on step number
            switch (stepNumber) {
                case 1:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Configure your application title and logo.';
                    break;
                case 4:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable personal and group workspaces for document management.';
                    break;
                case 10:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable content safety features to filter inappropriate content.';
                    break;
                case 11:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable user feedback and conversation archiving.';
                    break;
                case 12:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> Enable enhanced citations and image generation features.';
                    break;
                default:
                    optionalAlert.innerHTML = '<strong>Optional:</strong> This configuration is optional.';
            }
        }
    }
}

/**
 * Setup field change listeners for real-time validation during walkthrough
 */
function setupWalkthroughFieldListeners() {
    // Define field groups by step number
    const fieldGroups = {
        2: [ // GPT settings
            {selector: '#azure_openai_gpt_endpoint', event: 'input'},
            {selector: '#azure_openai_gpt_key', event: 'input'},
            {selector: '#azure_openai_gpt_authentication_type', event: 'change'},
            {selector: '#azure_apim_gpt_endpoint', event: 'input'},
            {selector: '#azure_apim_gpt_subscription_key', event: 'input'},
            {selector: '#azure_apim_gpt_deployment', event: 'input'},
            {selector: '#enable_gpt_apim', event: 'change'}
        ],
        3: [ // GPT Models
            {selector: '#fetch_gpt_models_btn', event: 'click', delay: 1000}
        ],
        4: [ // Workspace toggles
            {selector: '#enable_user_workspace', event: 'change'},
            {selector: '#enable_group_workspaces', event: 'change'}
        ],
        5: [ // Embedding settings
            {selector: '#azure_openai_embedding_endpoint', event: 'input'},
            {selector: '#azure_openai_embedding_key', event: 'input'},
            {selector: '#azure_openai_embedding_authentication_type', event: 'change'},
            {selector: '#azure_apim_embedding_endpoint', event: 'input'},
            {selector: '#azure_apim_embedding_subscription_key', event: 'input'},
            {selector: '#enable_embedding_apim', event: 'change'},
            {selector: '#fetch_embedding_models_btn', event: 'click', delay: 1000}
        ],
        6: [ // AI Search settings
            {selector: '#azure_ai_search_endpoint', event: 'input'},
            {selector: '#azure_ai_search_key', event: 'input'},
            {selector: '#azure_ai_search_authentication_type', event: 'change'},
            {selector: '#azure_apim_ai_search_endpoint', event: 'input'},
            {selector: '#azure_apim_ai_search_subscription_key', event: 'input'},
            {selector: '#enable_ai_search_apim', event: 'change'}
        ],
        7: [ // Document Intelligence settings
            {selector: '#azure_document_intelligence_endpoint', event: 'input'},
            {selector: '#azure_document_intelligence_key', event: 'input'},
            {selector: '#azure_document_intelligence_authentication_type', event: 'change'},
            {selector: '#azure_apim_document_intelligence_endpoint', event: 'input'},
            {selector: '#azure_apim_document_intelligence_subscription_key', event: 'input'},
            {selector: '#enable_document_intelligence_apim', event: 'change'}
        ],
        8: [ // Video settings
            {selector: '#enable_video_file_support', event: 'change'},
            {selector: '#video_indexer_location', event: 'input'},
            {selector: '#video_indexer_account_id', event: 'input'},
            {selector: '#video_indexer_api_key', event: 'input'}
        ],
        9: [ // Audio settings
            {selector: '#enable_audio_file_support', event: 'change'},
            {selector: '#speech_service_endpoint', event: 'input'},
            {selector: '#speech_service_key', event: 'input'}
        ]
    };
    
    // Add listeners to each group of fields
    for (const [stepNumber, fields] of Object.entries(fieldGroups)) {
        const step = parseInt(stepNumber, 10);
        fields.forEach(field => {
            const element = document.querySelector(field.selector);
            if (element) {
                // Create the handler function, using any delay specified
                const handler = () => {
                    if (field.delay) {
                        setTimeout(() => updateStepCompletionStatus(step), field.delay);
                    } else {
                        updateStepCompletionStatus(step);
                    }
                };
                
                // Remove any existing listeners (to prevent duplicates)
                element.removeEventListener(field.event, handler);
                
                // Add the new listener
                element.addEventListener(field.event, handler);
            }
        });
    }
    
    // Special case for model selection buttons which are dynamically created
    // We'll use event delegation for these
    document.addEventListener('click', event => {
        if (event.target.matches('button') && event.target.onclick && 
            event.target.onclick.toString().includes('selectGptModel')) {
            setTimeout(() => updateStepCompletionStatus(3), 100);
        } else if (event.target.matches('button') && event.target.onclick && 
            event.target.onclick.toString().includes('selectEmbeddingModel')) {
            setTimeout(() => updateStepCompletionStatus(5), 100);
        }
    });
}

/**
 * Initialize Bootstrap tooltips for any elements with data-bs-toggle="tooltip"
 */
function initializeTooltips() {
    // Find all tooltip elements
    const tooltipTriggerList = document.querySelectorAll('[data-bs-toggle="tooltip"]');
    
    // Initialize Bootstrap tooltips
    if (tooltipTriggerList.length > 0) {
        const tooltipList = [...tooltipTriggerList].map(tooltipTriggerEl => new bootstrap.Tooltip(tooltipTriggerEl));
    }
}

/**
 * Check if optional features are enabled and configured for a specific step
 * @param {number} stepNumber - The step to check
 * @returns {boolean} True if optional features are enabled/configured
 */
function checkOptionalFeaturesEnabled(stepNumber) {
    switch (stepNumber) {
        case 1: // App title and logo
            // Check if title or logo is configured
            const appTitle = document.getElementById('app_title')?.value;
            const logoFile = document.getElementById('app_logo_file')?.files?.length > 0;
            const currentLogo = document.getElementById('current_logo_img');
            return appTitle || logoFile || (currentLogo && currentLogo.src && !currentLogo.src.includes('default_logo.png'));
        
        case 4: // Workspaces
            // Check if workspaces are enabled
            const userWorkspace = document.getElementById('enable_user_workspace')?.checked;
            const groupWorkspace = document.getElementById('enable_group_workspaces')?.checked;
            return userWorkspace || groupWorkspace;
            
        case 10: // Content Safety
            // Check if content safety is enabled and configured
            const safetyEnabled = document.getElementById('enable_content_safety')?.checked;
            if (!safetyEnabled) return false;
            
            // Check configuration based on APIM or direct
            const safetyApim = document.getElementById('enable_content_safety_apim')?.checked;
            if (safetyApim) {
                const apimEndpoint = document.getElementById('azure_apim_content_safety_endpoint')?.value;
                const apimKey = document.getElementById('azure_apim_content_safety_subscription_key')?.value;
                return apimEndpoint && apimKey;
            } else {
                const endpoint = document.getElementById('content_safety_endpoint')?.value;
                const key = document.getElementById('content_safety_key')?.value;
                return endpoint && key;
            }
        
        case 11: // User feedback and archiving
            // Check if feedback is enabled
            const feedbackEnabled = document.getElementById('enable_user_feedback')?.checked;
            const archivingEnabled = document.getElementById('enable_conversation_archiving')?.checked;
            return feedbackEnabled || archivingEnabled;
            
        case 12: // Enhanced citations and image generation
            // Check if enhanced citations or image generation is enabled
            const citationsEnabled = document.getElementById('enable_enhanced_citations')?.checked;
            const imageGenEnabled = document.getElementById('enable_image_generation')?.checked;
            
            // For image generation, check if it's properly configured when enabled
            if (imageGenEnabled) {
                const imageApim = document.getElementById('enable_image_gen_apim')?.checked;
                if (imageApim) {
                    const apimEndpoint = document.getElementById('azure_apim_image_gen_endpoint')?.value;
                    const apimKey = document.getElementById('azure_apim_image_gen_subscription_key')?.value;
                    return citationsEnabled || (apimEndpoint && apimKey);
                } else {
                    const endpoint = document.getElementById('azure_openai_image_gen_endpoint')?.value;
                    const key = document.getElementById('azure_openai_image_gen_key')?.value;
                    return citationsEnabled || (endpoint && key);
                }
            }
            
            return citationsEnabled;
            
        default:
            // For steps not specifically handled (like required steps), return false
            return false;
    }
}
function validateAndMoveToNextStep(currentStep) {
    // Synchronize walkthrough toggles with form before validation
    syncWalkthroughToggles();
    
    // Initialize tooltips for APIM help
    initializeTooltips();
    
    // Check if the current step is complete
    const complete = isStepComplete(currentStep);
    
    // If step is complete, we can proceed
    if (complete) {
        // Find next applicable step that should be shown
        const nextStep = findNextApplicableStep(currentStep);
        if (nextStep > 0) {
            navigateToWalkthroughStep(nextStep);
        } else {
            // If no more applicable steps, we're at the end
            navigateToWalkthroughStep(12); // Go to final step
        }
    } else {
        // Highlight missing fields with validation (handled by updateStepCompletionStatus)
        updateStepCompletionStatus(currentStep);
        
        // Show alert for what's missing (this is now handled through the UI indicators)
        // No need for individual alerts as the button is disabled and visual cues are present
    }
}

/**
 * Navigate to the previous step in the walkthrough
 */
function navigatePreviousStep() {
    // Get the current step
    const currentStep = getCurrentWalkthroughStep();
    
    // Find the previous applicable step
    const prevStep = findPreviousApplicableStep(currentStep);
    
    // Navigate to the previous step if one is found
    if (prevStep > 0) {
        navigateToWalkthroughStep(prevStep);
    } else {
        // If no previous step found, go to first step
        navigateToWalkthroughStep(1);
    }
}

/**
 * Sets up event listeners to track form changes
 */
function setupFormChangeTracking() {
    if (!adminForm || !saveButton) return;
    
    // Initialize button state
    updateSaveButtonState();
    
    // Add event listeners to all form inputs, selects, and textareas
    const formElements = adminForm.querySelectorAll('input, select, textarea');
    formElements.forEach(element => {
        // For checkboxes and radios, listen for change event
        if (element.type === 'checkbox' || element.type === 'radio') {
            element.addEventListener('change', markFormAsModified);
        } 
        // For other inputs, listen for input event
        else {
            element.addEventListener('input', markFormAsModified);
        }
    });
    
    // Reset form state when form is submitted
    adminForm.addEventListener('submit', () => {
        formModified = false;
        updateSaveButtonState();
    });
}

/**
 * Mark the form as modified and update the save button
 */
function markFormAsModified() {
    formModified = true;
    updateSaveButtonState();
}

/**
 * Update the save button appearance based on form state
 */
function updateSaveButtonState() {
    if (!saveButton) return;
    
    if (formModified) {
        // Enable button, make it blue, and update text
        saveButton.disabled = false;
        saveButton.classList.remove('btn-secondary');
        saveButton.classList.add('btn-primary');
        saveButton.innerHTML = '<i class="bi bi-floppy"></i> Save Pending';
    } else {
        // Disable button, make it grey, and reset text
        saveButton.disabled = true;
        saveButton.classList.remove('btn-primary');
        saveButton.classList.add('btn-secondary');
        saveButton.innerHTML = '<i class="bi bi-floppy"></i> Save Settings';
    }
}
