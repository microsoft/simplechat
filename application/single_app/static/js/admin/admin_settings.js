// admin_settings.js

let gptSelected = window.gptSelected || [];
let gptAll      = window.gptAll || [];

let embeddingSelected = window.embeddingSelected || [];
let embeddingAll      = window.embeddingAll || [];

let imageSelected = window.imageSelected || [];
let imageAll      = window.imageAll || [];

let classificationCategories = window.classificationCategories || [];
let enableDocumentClassification = window.enableDocumentClassification || false;

const enableClassificationToggle = document.getElementById('enable_document_classification');
const classificationSettingsDiv = document.getElementById('document_classification_settings');
const classificationTbody = document.getElementById('classification-categories-tbody');
const addClassificationBtn = document.getElementById('add-classification-btn');
const classificationJsonInput = document.getElementById('document_classification_categories_json');
const adminForm = document.getElementById('admin-settings-form');
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
});

function activateTabFromHash() {
    const hash = window.location.hash;
    if (hash) {
        const tabButton = document.querySelector(`button.nav-link[data-bs-target="${hash}"]`);
        if (tabButton) {
            const tab = new bootstrap.Tab(tabButton);
            tab.show();
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
            } else {
                console.error("Invalid index for deleting classification:", indexAttr);
                // Fallback: remove row from DOM and update JSON
                row.remove();
                updateClassificationJsonInput();
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
        }
    }
}

/**
 * Updates the hidden input field with the current classification categories as JSON.
 */
function updateClassificationJsonInput() {
    if (classificationJsonInput) {
        try {
             // Ensure we only stringify valid categories (though save/delete should keep the array clean)
             const validCategories = classificationCategories.filter(cat => cat && typeof cat.label === 'string' && typeof cat.color === 'string');
             classificationJsonInput.value = JSON.stringify(validCategories);
        } catch (e) {
             console.error("Error stringifying classification categories:", e);
             classificationJsonInput.value = "[]"; // Set to empty array on error
        }
    }
}

function setupToggles() {
    // Existing toggles...
    const enableGptApim = document.getElementById('enable_gpt_apim');
    if (enableGptApim) {
        enableGptApim.addEventListener('change', function () {
            document.getElementById('non_apim_gpt_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_gpt_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableEmbeddingApim = document.getElementById('enable_embedding_apim');
    if (enableEmbeddingApim) {
        enableEmbeddingApim.addEventListener('change', function () {
            document.getElementById('non_apim_embedding_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_embedding_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableImageGen = document.getElementById('enable_image_generation');
    if (enableImageGen) {
        enableImageGen.addEventListener('change', function () {
            document.getElementById('image_gen_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableImageGenApim = document.getElementById('enable_image_gen_apim');
    if (enableImageGenApim) {
        enableImageGenApim.addEventListener('change', function () {
            document.getElementById('non_apim_image_gen_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_image_gen_settings').style.display = this.checked ? 'block' : 'none';
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
        });
    }

    const enableContentSafetyCheckbox = document.getElementById('enable_content_safety');
    if (enableContentSafetyCheckbox) {
        enableContentSafetyCheckbox.addEventListener('change', function() {
            const safetySettings = document.getElementById('content_safety_settings');
            safetySettings.style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableContentSafetyApim = document.getElementById('enable_content_safety_apim');
    if (enableContentSafetyApim) {
        enableContentSafetyApim.addEventListener('change', function() {
            document.getElementById('non_apim_content_safety_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_content_safety_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableWebSearch = document.getElementById('enable_web_search');
    if (enableWebSearch) {
        enableWebSearch.addEventListener('change', function () {
            document.getElementById('web_search_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableWebSearchApim = document.getElementById('enable_web_search_apim');
    if (enableWebSearchApim) {
        enableWebSearchApim.addEventListener('change', function () {
            document.getElementById('non_apim_web_search_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_web_search_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableAiSearchApim = document.getElementById('enable_ai_search_apim');
    if (enableAiSearchApim) {
        enableAiSearchApim.addEventListener('change', function () {
            document.getElementById('non_apim_ai_search_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_ai_search_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const enableDocumentIntelligenceApim = document.getElementById('enable_document_intelligence_apim');
    if (enableDocumentIntelligenceApim) {
        enableDocumentIntelligenceApim.addEventListener('change', function () {
            document.getElementById('non_apim_document_intelligence_settings').style.display = this.checked ? 'none' : 'block';
            document.getElementById('apim_document_intelligence_settings').style.display = this.checked ? 'block' : 'none';
        });
    }

    const gptAuthType = document.getElementById('azure_openai_gpt_authentication_type');
    if (gptAuthType) {
        gptAuthType.addEventListener('change', function () {
            document.getElementById('gpt_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const embeddingAuthType = document.getElementById('azure_openai_embedding_authentication_type');
    if (embeddingAuthType) {
        embeddingAuthType.addEventListener('change', function () {
            document.getElementById('embedding_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const imgAuthType = document.getElementById('azure_openai_image_gen_authentication_type');
    if (imgAuthType) {
        imgAuthType.addEventListener('change', function () {
            document.getElementById('image_gen_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const contentSafetyAuthType = document.getElementById('content_safety_authentication_type');
    if (contentSafetyAuthType) {
        contentSafetyAuthType.addEventListener('change', function () {
            document.getElementById('content_safety_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const aiSearchAuthType = document.getElementById('azure_ai_search_authentication_type');
    if (aiSearchAuthType) {
        aiSearchAuthType.addEventListener('change', function () {
            document.getElementById('azure_ai_search_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const docIntelAuthType = document.getElementById('azure_document_intelligence_authentication_type');
    if (docIntelAuthType) {
        docIntelAuthType.addEventListener('change', function () {
            document.getElementById('azure_document_intelligence_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const officeAuthType = document.getElementById('office_docs_authentication_type');
    if (officeAuthType) {
        officeAuthType.addEventListener('change', function(){
            document.getElementById('office_docs_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const videoAuthType = document.getElementById('video_files_authentication_type');
    if (videoAuthType) {
        videoAuthType.addEventListener('change', function(){
            document.getElementById('video_files_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }

    const audioAuthType = document.getElementById('audio_files_authentication_type');
    if (audioAuthType) {
        audioAuthType.addEventListener('change', function(){
            document.getElementById('audio_files_key_container').style.display =
                (this.value === 'key') ? 'block' : 'none';
        });
    }}

    if (enableGroupWorkspacesToggle && createGroupPermissionSettingDiv) {
        // Initial state
        createGroupPermissionSettingDiv.style.display = enableGroupWorkspacesToggle.checked ? 'block' : 'none';
        // Listener for changes
        enableGroupWorkspacesToggle.addEventListener('change', function() {
            createGroupPermissionSettingDiv.style.display = this.checked ? 'block' : 'none';
        });
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

            const enableApim = document.getElementById('enable_redis_apim').checked;

            const payload = {
                test_type: 'redis',
                enable_apim: enableApim
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_redis_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_redis_subscription_key').value,
                    deployment: document.getElementById('azure_apim_redis_deployment').value,
                    api_version: document.getElementById('azure_apim_redis_api_version').value
                };
            } else {
                payload.direct = {
                    endpoint: document.getElementById('redis_endpoint').value,
                    auth_type: document.getElementById('redis_authentication_type').value,
                    key: document.getElementById('redis_key').value
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

    const testWebSearchBtn = document.getElementById('test_web_search_button');
    if (testWebSearchBtn) {
        testWebSearchBtn.addEventListener('click', async () => {
            const resultDiv = document.getElementById('test_web_search_result');
            resultDiv.innerHTML = 'Testing Bing Web Search...';

            const webSearchEnabled = document.getElementById('enable_web_search').checked;
            const enableApim = document.getElementById('enable_web_search_apim').checked;

            const payload = {
                test_type: 'web_search',
                enabled: webSearchEnabled,
                enable_apim: enableApim
            };

            if (enableApim) {
                payload.apim = {
                    endpoint: document.getElementById('azure_apim_web_search_endpoint').value,
                    subscription_key: document.getElementById('azure_apim_web_search_subscription_key').value,
                    deployment: document.getElementById('azure_apim_web_search_deployment').value,
                    api_version: document.getElementById('azure_apim_web_search_api_version').value
                };
            } else {
                payload.direct = {
                    key: document.getElementById('bing_search_key').value
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
                    resultDiv.innerHTML = `<span class="text-danger">${data.error || 'Error testing Web Search'}</span>`;
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
  });
}

// when APIM‐toggle flips, repopulate
const apimToggle = document.getElementById('enable_gpt_apim');
if (apimToggle) {
  apimToggle.addEventListener('change', populateExtractionModels);
}

// on load, stash previous & populate
document.addEventListener('DOMContentLoaded', () => {
  if (extractSelect) {
    extractSelect.setAttribute('data-prev', extractSelect.value);
    populateExtractionModels();
  }
});


document.addEventListener('DOMContentLoaded', () => {
    ['user','group'].forEach(type => {
      const warnDiv     = document.getElementById(`index-warning-${type}`);
      const missingSpan = document.getElementById(`missing-fields-${type}`);
      const fixBtn      = document.getElementById(`fix-${type}-index-btn`);
  
      // 1) check for missing fields
      fetch('/api/admin/settings/check_index_fields', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ indexType: type })
      })
      .then(r => r.json())
      .then(({ missingFields }) => {
        if (missingFields?.length) {
          missingSpan.textContent = missingFields.join(', ');
          warnDiv.style.display   = 'block';
        }
      })
      .catch(err => console.error(`Error checking ${type} index:`, err));
  
      // 2) wire up the “fix” button
      fixBtn.addEventListener('click', () => {
        fixBtn.disabled = true;
        fetch('/api/admin/settings/fix_index_fields', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ indexType: type })
        })
        .then(r => r.json())
        .then(resp => {
          if (resp.status === 'success') {
            window.location.reload();
          } else {
            alert(`Failed to fix ${type} index: ${resp.error}`);
            fixBtn.disabled = false;
          }
        })
        .catch(err => {
          alert(`Error fixing ${type} index: ${err}`);
          fixBtn.disabled = false;
        });
      });
    });
  });
  

togglePassword('toggle_gpt_key', 'azure_openai_gpt_key');
togglePassword('toggle_embedding_key', 'azure_openai_embedding_key');
togglePassword('toggle_image_gen_key', 'azure_openai_image_gen_key');
togglePassword('toggle_content_safety_key', 'content_safety_key');
togglePassword('toggle_bing_search_key', 'bing_search_key');
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
togglePassword('toggle_office_conn_str', 'office_docs_storage_account_url');
togglePassword('toggle_video_conn_str', 'video_files_storage_account_url');
togglePassword('toggle_audio_conn_str', 'audio_files_storage_account_url');
togglePassword('toggle_video_indexer_api_key', 'video_indexer_api_key');
togglePassword('toggle_speech_service_key', 'speech_service_key');
togglePassword('toggle_redis_key', 'redis_key');
togglePassword('toggle_azure_apim_redis_subscription_key', 'azure_apim_redis_subscription_key');
