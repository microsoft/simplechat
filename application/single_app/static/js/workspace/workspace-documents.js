// static/js/workspace/workspace-documents.js

import { escapeHtml } from "./workspace-utils.js";

// ------------- State Variables -------------
let docsCurrentPage = 1;
let docsPageSize = 10;
let docsSearchTerm = '';
let docsClassificationFilter = '';
let docsAuthorFilter = ''; // Added for Author filter
let docsKeywordsFilter = ''; // Added for Keywords filter
let docsAbstractFilter = ''; // Added for Abstract filter
const activePolls = new Set();

// ------------- DOM Elements (Documents Tab) -------------
const documentsTableBody = document.querySelector("#documents-table tbody");
const docsPaginationContainer = document.getElementById("docs-pagination-container");
const docsPageSizeSelect = document.getElementById("docs-page-size-select");
const fileInput = document.getElementById("file-input");
const uploadBtn = document.getElementById("upload-btn");
const uploadStatusSpan = document.getElementById("upload-status");
const docMetadataModalEl = document.getElementById("docMetadataModal") ? new bootstrap.Modal(document.getElementById("docMetadataModal")) : null;
const docMetadataForm = document.getElementById("doc-metadata-form");
const docsSharedOnlyFilter = document.getElementById("docs-shared-only-filter");

// --- Filter elements ---
const docsSearchInput = document.getElementById('docs-search-input');
// Conditionally get elements based on flags passed from template
const docsClassificationFilterSelect = (window.enable_document_classification === true || window.enable_document_classification === "true")
    ? document.getElementById('docs-classification-filter')
    : null;
const docsAuthorFilterInput = document.getElementById('docs-author-filter');
const docsKeywordsFilterInput = document.getElementById('docs-keywords-filter');
const docsAbstractFilterInput = document.getElementById('docs-abstract-filter');
// Buttons (get them regardless, they might be rendered in different places)
const docsApplyFiltersBtn = document.getElementById('docs-apply-filters-btn');
const docsClearFiltersBtn = document.getElementById('docs-clear-filters-btn');

// ------------- Helper Functions -------------
function isColorLight(hexColor) {
    if (!hexColor) return true; // Default to light if no color
    const cleanHex = hexColor.startsWith('#') ? hexColor.substring(1) : hexColor;
    if (cleanHex.length < 3) return true;

    let r, g, b;
    try {
        if (cleanHex.length === 3) {
            r = parseInt(cleanHex[0] + cleanHex[0], 16);
            g = parseInt(cleanHex[1] + cleanHex[1], 16);
            b = parseInt(cleanHex[2] + cleanHex[2], 16);
        } else if (cleanHex.length >= 6) {
            r = parseInt(cleanHex.substring(0, 2), 16);
            g = parseInt(cleanHex.substring(2, 4), 16);
            b = parseInt(cleanHex.substring(4, 6), 16);
        } else {
            return true; // Invalid hex length
        }
    } catch (e) {
        console.warn("Could not parse hex color:", hexColor, e);
        return true; // Default to light on parsing error
    }

    if (isNaN(r) || isNaN(g) || isNaN(b)) return true; // Parsing failed

    const luminance = (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255;
    return luminance > 0.5;
}

// ------------- Event Listeners -------------

// Page Size
if (docsPageSizeSelect) {
    docsPageSizeSelect.addEventListener("change", (e) => {
        docsPageSize = parseInt(e.target.value, 10);
        docsCurrentPage = 1; // Reset to first page
        fetchUserDocuments();
    });
}

// Filters - Apply Button
if (docsApplyFiltersBtn) {
    docsApplyFiltersBtn.addEventListener('click', () => {
        // Read values from all potentially available filter inputs
        docsSearchTerm = docsSearchInput ? docsSearchInput.value.trim() : '';
        docsClassificationFilter = docsClassificationFilterSelect ? docsClassificationFilterSelect.value : '';
        docsAuthorFilter = docsAuthorFilterInput ? docsAuthorFilterInput.value.trim() : '';
        docsKeywordsFilter = docsKeywordsFilterInput ? docsKeywordsFilterInput.value.trim() : '';
        docsAbstractFilter = docsAbstractFilterInput ? docsAbstractFilterInput.value.trim() : '';

        docsCurrentPage = 1; // Reset to first page
        fetchUserDocuments();
    });
}

// Listen for shared only filter change (optional: auto-apply on change)
if (docsSharedOnlyFilter) {
    docsSharedOnlyFilter.addEventListener('change', () => {
        docsCurrentPage = 1;
        fetchUserDocuments();
    });
}

// Filters - Clear Button
if (docsClearFiltersBtn) {
    // Remove any existing event listeners to prevent duplicates
    docsClearFiltersBtn.removeEventListener('click', clearDocsFilters);
    
    // Define the clear filters function
    function clearDocsFilters() {
        console.log("Clearing document filters...");
        // Clear all potentially available filter inputs and state variables
        if (docsSearchInput) docsSearchInput.value = '';
        if (docsClassificationFilterSelect) docsClassificationFilterSelect.value = '';
        if (docsAuthorFilterInput) docsAuthorFilterInput.value = '';
        if (docsKeywordsFilterInput) docsKeywordsFilterInput.value = '';
        if (docsAbstractFilterInput) docsAbstractFilterInput.value = '';

        docsSearchTerm = '';
        docsClassificationFilter = '';
        docsAuthorFilter = '';
        docsKeywordsFilter = '';
        docsAbstractFilter = '';

        docsCurrentPage = 1; // Reset to first page
        fetchUserDocuments();
    }
    
    // Add the event listener
    docsClearFiltersBtn.addEventListener('click', clearDocsFilters);
    
    // Make the function globally available for other components to use
    window.clearDocsFilters = clearDocsFilters;
}

// Optional: Trigger search on Enter key in primary search input
if (docsSearchInput) {
    docsSearchInput.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') {
            e.preventDefault(); // Prevent default form submission if it's in a form
            if (docsApplyFiltersBtn) docsApplyFiltersBtn.click(); // Trigger the apply button click
        }
    });
}
// Add similar listeners for metadata inputs if desired
[docsAuthorFilterInput, docsKeywordsFilterInput, docsAbstractFilterInput].forEach(input => {
    if (input) {
         input.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                if (docsApplyFiltersBtn) docsApplyFiltersBtn.click();
            }
        });
    }
});


// Metadata Modal Form Submission
if (docMetadataForm && docMetadataModalEl) { // Check both exist
    docMetadataForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const docSaveBtn = document.getElementById("doc-save-btn");
        if (!docSaveBtn) return;
        docSaveBtn.disabled = true;
        docSaveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...`;

        const docId = document.getElementById("doc-id").value;
        const payload = {
            title: document.getElementById("doc-title")?.value.trim() || null,
            abstract: document.getElementById("doc-abstract")?.value.trim() || null,
            keywords: document.getElementById("doc-keywords")?.value.trim() || null,
            publication_date: document.getElementById("doc-publication-date")?.value.trim() || null,
            authors: document.getElementById("doc-authors")?.value.trim() || null,
        };

        if (payload.keywords) {
            payload.keywords = payload.keywords.split(",").map(kw => kw.trim()).filter(Boolean);
        } else { payload.keywords = []; }
        if (payload.authors) {
            payload.authors = payload.authors.split(",").map(a => a.trim()).filter(Boolean);
        } else { payload.authors = []; }

        // Add classification if enabled AND selected (handle 'none' value)
        // Use the window flag to check if classification is enabled
        if (window.enable_document_classification === true || window.enable_document_classification === "true") {
            const classificationSelect = document.getElementById("doc-classification");
            let selectedClassification = classificationSelect?.value || null;
            // Treat 'none' selection as null/empty on the backend
            if (selectedClassification === 'none') {
                selectedClassification = null;
            }
             payload.document_classification = selectedClassification;
        }

        fetch(`/api/documents/${docId}`, {
            method: "PATCH",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(payload),
        })
            .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
            .then(updatedDoc => {
                if (docMetadataModalEl) docMetadataModalEl.hide();
                fetchUserDocuments(); // Refresh the table
            })
            .catch(err => {
                console.error("Error updating document:", err);
                alert("Error updating document: " + (err.error || err.message || "Unknown error"));
            })
            .finally(() => {
                docSaveBtn.disabled = false;
                docSaveBtn.textContent = "Save Metadata";
            });
    });
}

// Upload Button Handler
if (uploadBtn && fileInput && uploadStatusSpan) {
    uploadBtn.addEventListener("click", async () => {
        const files = fileInput.files;
        if (!files || files.length === 0) {
            alert("Please select at least one file to upload.");
            return;
        }

        uploadBtn.disabled = true;
        uploadBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Preparing...`;
        uploadStatusSpan.textContent = `Preparing ${files.length} file(s)...`;

        // Per-file progress container
        const progressContainer = document.getElementById("workspace-upload-progress-container");
        if (progressContainer) progressContainer.innerHTML = "";

        let completed = 0;
        let failed = 0;

        // Helper to create a unique ID for each file
        function makeId(file) {
            return 'progress-' + Math.random().toString(36).slice(2, 10) + '-' + encodeURIComponent(file.name.replace(/\W+/g, ''));
        }

        // Helper to create progress bar/status for a file
        function createProgressBar(file, id) {
            const wrapper = document.createElement('div');
            wrapper.className = 'mb-2';
            wrapper.id = id + '-wrapper';
            wrapper.innerHTML = `
              <div class="progress" style="height: 10px;" title="Status: Uploading ${escapeHtml(file.name)} (0%)">
                <div id="${id}" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: 0%;" aria-valuenow="0" aria-valuemin="0" aria-valuemax="100"></div>
              </div>
              <div class="text-muted text-end small" id="${id}-text">Uploading ${escapeHtml(file.name)} (0%)</div>
            `;
            return wrapper;
        }

        // Upload each file individually with progress
        Array.from(files).forEach(file => {
            const id = makeId(file);
            if (progressContainer) progressContainer.appendChild(createProgressBar(file, id));

            const progressBar = document.getElementById(id);
            const statusText = document.getElementById(id + '-text');

            const formData = new FormData();
            formData.append("file", file, file.name);

            const xhr = new XMLHttpRequest();
            xhr.open("POST", "/api/documents/upload", true);

            xhr.upload.onprogress = function (e) {
                if (e.lengthComputable) {
                    const percent = Math.round((e.loaded / e.total) * 100);
                    if (progressBar) {
                        progressBar.style.width = percent + '%';
                        progressBar.setAttribute('aria-valuenow', percent);
                    }
                    if (statusText) {
                        statusText.textContent = `Uploading ${file.name} (${percent}%)`;
                    }
                }
            };

            xhr.onload = function () {
                if (xhr.status >= 200 && xhr.status < 300) {
                    if (progressBar) {
                        progressBar.classList.remove('bg-info');
                        progressBar.classList.add('bg-success');
                        progressBar.classList.remove('progress-bar-animated');
                    }
                    if (statusText) {
                        statusText.textContent = `Uploaded ${file.name} (100%)`;
                    }
                    completed++;
                } else {
                    if (progressBar) {
                        progressBar.classList.remove('bg-info');
                        progressBar.classList.add('bg-danger');
                        progressBar.classList.remove('progress-bar-animated');
                    }
                    if (statusText) {
                        statusText.textContent = `Failed to upload ${file.name}`;
                    }
                    failed++;
                }
                // Update summary status
                uploadStatusSpan.textContent = `Uploaded ${completed}/${files.length}${failed ? `, Failed: ${failed}` : ''}`;
                if (completed + failed === files.length) {
                    fileInput.value = '';
                    docsCurrentPage = 1;
                    fetchUserDocuments();
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = "Upload Document(s)";
                    // Clear upload progress bars after all uploads and table refresh
                    if (progressContainer) progressContainer.innerHTML = '';
                }
            };

            xhr.onerror = function () {
                if (progressBar) {
                    progressBar.classList.remove('bg-info');
                    progressBar.classList.add('bg-danger');
                    progressBar.classList.remove('progress-bar-animated');
                }
                if (statusText) {
                    statusText.textContent = `Failed to upload ${file.name}`;
                }
                failed++;
                uploadStatusSpan.textContent = `Uploaded ${completed}/${files.length}${failed ? `, Failed: ${failed}` : ''}`;
                if (completed + failed === files.length) {
                    fileInput.value = '';
                    docsCurrentPage = 1;
                    fetchUserDocuments();
                    uploadBtn.disabled = false;
                    uploadBtn.innerHTML = "Upload Document(s)";
                    if (progressContainer) progressContainer.innerHTML = '';
                }
            };

            xhr.send(formData);
        });
    });
}

// ------------- Document Functions -------------

function fetchUserDocuments() {
    if (!documentsTableBody) return; // Don't proceed if table body isn't found

    // Show loading state
    documentsTableBody.innerHTML = `
        <tr class="table-loading-row">
            <td colspan="4">
                <div class="spinner-border spinner-border-sm me-2" role="status"><span class="visually-hidden">Loading...</span></div>
                Loading documents...
            </td>
        </tr>`;
    if (docsPaginationContainer) docsPaginationContainer.innerHTML = ''; // Clear pagination

    // Build query parameters - Include all active filters
    const params = new URLSearchParams({
        page: docsCurrentPage,
        page_size: docsPageSize,
    });
    if (docsSearchTerm) {
        params.append('search', docsSearchTerm); // File Name / Title search
    }
    if (docsClassificationFilter) {
        params.append('classification', docsClassificationFilter);
    }
    // Add new metadata filters if they have values
    if (docsAuthorFilter) {
        params.append('author', docsAuthorFilter); // Assumes backend uses 'author'
    }
    if (docsKeywordsFilter) {
        params.append('keywords', docsKeywordsFilter); // Assumes backend uses 'keywords'
    }
    if (docsAbstractFilter) {
        params.append('abstract', docsAbstractFilter); // Assumes backend uses 'abstract'
    }
    // Add shared only filter
    if (docsSharedOnlyFilter && docsSharedOnlyFilter.checked) {
        params.append('shared_only', 'true');
    }

    console.log("Fetching documents with params:", params.toString()); // Debugging: Check params

    fetch(`/api/documents?${params.toString()}`)
        .then(response => response.ok ? response.json() : response.json().then(err => Promise.reject(err)))
        .then(data => {
            if (data.needs_legacy_update_check) {
                showLegacyUpdatePrompt();
              }

            documentsTableBody.innerHTML = ""; // Clear loading/existing rows
            if (!data.documents || data.documents.length === 0) {
                // Check if any filters are active
                const filtersActive = docsSearchTerm || docsClassificationFilter || docsAuthorFilter || docsKeywordsFilter || docsAbstractFilter;
                documentsTableBody.innerHTML = `
                    <tr>
                        <td colspan="4" class="text-center p-4 text-muted">
                            ${ filtersActive
                                ? 'No documents found matching the current filters.'
                                : 'No documents found. Upload a document to get started.'
                            }
                            ${ filtersActive
                                ? '<br><button class="btn btn-link btn-sm p-0" id="docs-reset-filter-msg-btn">Clear filters</button> to see all documents.'
                                : ''
                            }
                        </td>
                    </tr>`;
                 // Add event listener for the reset button within the message
                 const resetButton = document.getElementById('docs-reset-filter-msg-btn');
                 if (resetButton && docsClearFiltersBtn) { // Ensure clear button exists
                     resetButton.addEventListener('click', () => {
                         docsClearFiltersBtn.click(); // Simulate clicking the main clear button
                     });
                 }
            } else {
                // If backend does not support shared_only, filter client-side as fallback
                let docs = data.documents;
                if (docsSharedOnlyFilter && docsSharedOnlyFilter.checked) {
                    docs = docs.filter(doc =>
                        Array.isArray(doc.shared_user_ids) && doc.shared_user_ids.length > 0
                    );
                }
                window.lastFetchedDocs = docs;
                docs.forEach(doc => renderDocumentRow(doc));
            }
            renderDocsPaginationControls(data.page, data.page_size, data.total_count);
        })
        .catch(error => {
            console.error("Error fetching documents:", error);
            // Check for embedding/vector error keywords
            const errMsg = (error.error || error.message || '').toLowerCase();
            let displayMsg;
            if (errMsg.includes('embedding') || errMsg.includes('vector')) {
                displayMsg = "There was an issue with the embedding process. Please check with an admin on embedding configuration.";
            } else {
                displayMsg = `Error loading documents: ${escapeHtml(error.error || error.message || 'Unknown error')}`;
            }
            documentsTableBody.innerHTML = `<tr><td colspan="4" class="text-center text-danger p-4">${displayMsg}</td></tr>`;
            renderDocsPaginationControls(1, docsPageSize, 0); // Show empty pagination on error
        });
}


function renderDocumentRow(doc) {
    if (!documentsTableBody) return;
    const docId = doc.id;
    // Ensure percentage_complete is treated as a number, default to 0 if invalid/null
    const pctString = String(doc.percentage_complete);
    const pct = /^\d+(\.\d+)?$/.test(pctString) ? parseFloat(pctString) : 0;
    const docStatus = doc.status || "";
    const isComplete = pct >= 100 || docStatus.toLowerCase().includes("complete") || docStatus.toLowerCase().includes("error");
    const hasError = docStatus.toLowerCase().includes("error");

    const docRow = document.createElement("tr");
    docRow.id = `doc-row-${docId}`;
    docRow.innerHTML = `
        <td class="align-middle">
            ${isComplete && !hasError ?
                `<button class="btn btn-link p-0" onclick="window.toggleDetails('${docId}')" title="Show/Hide Details">
                    <span id="arrow-icon-${docId}" class="bi bi-chevron-right"></span>
                    </button>` :
                    (hasError ? `<span class="text-danger" title="Processing Error: ${escapeHtml(docStatus)}"><i class="bi bi-exclamation-triangle-fill"></i></span>`
                             : `<span class="text-muted" title="Processing: ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)"><i class="bi bi-hourglass-split"></i></span>`)
            }
        </td>
        <td class="align-middle" title="${escapeHtml(doc.file_name || "")}">${escapeHtml(doc.file_name || "")}</td>
        <td class="align-middle" title="${escapeHtml(doc.title || "")}">${escapeHtml(doc.title || "N/A")}</td>
        <td class="align-middle text-end">
            ${(() => {
                // Check if current user is the owner of the document
                const currentUserId = window.current_user_id; // This should be set in the template
                const isOwner = doc.user_id === currentUserId;
                
                let buttonsHtml = '';
                let sharedUserEntry = null;
                if (isComplete && !hasError) {
                    if (isOwner) {
                        // Owner sees Share and Delete buttons
                        const shareCount = doc.shared_user_ids && doc.shared_user_ids.length > 0 ? doc.shared_user_ids.length : 0;
                        if (window.enable_file_sharing === true || window.enable_file_sharing === "true") {
                            buttonsHtml += `<button class="btn btn-sm btn-info me-1 d-inline-flex align-items-center"
                                onclick="window.shareDocument('${docId}', '${escapeHtml(doc.file_name || '')}')"
                                title="Share Document"
                                aria-label="Share Document: ${escapeHtml(doc.file_name || 'Untitled')}"
                            >
                                <i class="bi bi-share-fill me-1" aria-hidden="true"></i>
                                <span class="badge bg-light text-dark ms-1">${shareCount}</span>
                                <span class="visually-hidden">users shared</span>
                            </button>`;
                        }
                        buttonsHtml += `<button class="btn btn-sm btn-danger me-1"
                            onclick="window.deleteDocument('${docId}', event)"
                            title="Delete Document"
                            aria-label="Delete Document: ${escapeHtml(doc.file_name || 'Untitled')}"
                        >
                            <i class="bi bi-trash-fill" aria-hidden="true"></i>
                            <span class="visually-hidden">Delete</span>
                        </button>`;
                        // Owner: always show chat button
                        buttonsHtml += `<button class="btn btn-sm btn-primary"
                            onclick="window.redirectToChat('${docId}')"
                            title="Open Chat for Document"
                            aria-label="Open Chat for Document: ${escapeHtml(doc.file_name || 'Untitled')}"
                        >
                            <i class="bi bi-chat-dots-fill" aria-hidden="true"></i>
                            <span class="visually-hidden">Open Chat</span>
                            Chat
                        </button>`;
                    } else {
                        // Non-owner with shared access: check approval status
                        sharedUserEntry = (doc.shared_user_ids || []).find(
                            entry => entry.startsWith(currentUserId + ",")
                        );
                        if (sharedUserEntry && sharedUserEntry.endsWith(",not_approved")) {
                            // Debug: log owner_id and user_id for this doc
                            console.log('Approve button debug:', {
                                docId: docId,
                                owner_id: doc.owner_id,
                                user_id: doc.user_id
                            });
                            // Show Approve button
                            buttonsHtml += `<button class="btn btn-sm btn-success me-1"
                                onclick="window.approveSharedDocument('${docId}', this, '${escapeHtml(doc.owner_id || doc.user_id)}')"
                                title="Approve access to this shared document"
                                aria-label="Approve access to shared document: ${escapeHtml(doc.file_name || 'Untitled')}"
                            >
                                <i class="bi bi-check-circle" aria-hidden="true"></i>
                                <span class="visually-hidden">Approve Shared Document</span>
                                Approve
                            </button>`;
                        } else {
                            // Approved: show Remove button
                            buttonsHtml += `<button class="btn btn-sm btn-danger me-1"
                                onclick="window.removeSelfFromDocument('${docId}', event)"
                                title="Remove yourself from this shared document"
                                aria-label="Remove yourself from shared document: ${escapeHtml(doc.file_name || 'Untitled')}"
                            >
                                <i class="bi bi-x-circle-fill" aria-hidden="true"></i>
                                <span class="visually-hidden">Remove from Shared Document</span>
                            </button>`;
                        }
                        // Chat button is available to everyone with access, but only if approved
                        if (!sharedUserEntry || sharedUserEntry.endsWith(",approved")) {
                            buttonsHtml += `<button class="btn btn-sm btn-primary"
                                onclick="window.redirectToChat('${docId}')"
                                title="Open Chat for Document"
                                aria-label="Open Chat for Document: ${escapeHtml(doc.file_name || 'Untitled')}"
                            >
                                <i class="bi bi-chat-dots-fill" aria-hidden="true"></i>
                                <span class="visually-hidden">Open Chat</span>
                                Chat
                            </button>`;
                        }
                    }
                } else if (isOwner) {
                    // Only owners can delete incomplete/error documents
                    buttonsHtml += `<button class="btn btn-sm btn-danger me-1" onclick="window.deleteDocument('${docId}', event)" title="Delete Document">
                        <i class="bi bi-trash-fill"></i>
                    </button>`;
                }
                
                return buttonsHtml;
            })()}
        </td>
    `;
    docRow.__docData = doc; // Attach the full doc object for modal use
    documentsTableBody.appendChild(docRow);

    // Only add details row if complete and no error
    if (isComplete && !hasError) {
        const detailsRow = document.createElement("tr");
        detailsRow.id = `details-row-${docId}`;
        detailsRow.style.display = "none"; // Initially hidden

        let classificationDisplayHTML = '';
        // Check window flag before rendering classification - CORRECTED CHECK
        if (window.enable_document_classification === true || window.enable_document_classification === "true") {
                classificationDisplayHTML += `<p class="mb-1"><strong>Classification:</strong> `;
                const currentLabel = doc.document_classification || null; // Treat empty string or null as no classification
                const categories = window.classification_categories || [];
                const category = categories.find(cat => cat.label === currentLabel);

                if (category) {
                    const bgColor = category.color || '#6c757d'; // Default to secondary color
                    const useDarkText = isColorLight(bgColor);
                    const textColorClass = useDarkText ? 'text-dark' : '';
                    classificationDisplayHTML += `<span class="classification-badge ${textColorClass}" style="background-color: ${escapeHtml(bgColor)};">${escapeHtml(category.label)}</span>`;
                } else if (currentLabel) { // Has a label, but no matching category found
                    classificationDisplayHTML += `<span class="badge bg-warning text-dark" title="Category config not found">${escapeHtml(currentLabel)} (?)</span>`;
                } else { // No classification label (null or empty string)
                     classificationDisplayHTML += `<span class="badge bg-secondary">None</span>`;
                }
                classificationDisplayHTML += `</p>`;
            }

        let detailsHtml = `
            <td colspan="4">
                <div class="bg-light p-3 border rounded small">
                    ${classificationDisplayHTML}
                    <p class="mb-1"><strong>Version:</strong> ${escapeHtml(doc.version || "N/A")}</p>
                    <p class="mb-1"><strong>Authors:</strong> ${escapeHtml(Array.isArray(doc.authors) ? doc.authors.join(", ") : doc.authors || "N/A")}</p>
                    <p class="mb-1"><strong>Pages:</strong> ${escapeHtml(doc.number_of_pages || "N/A")}</p>
                    <p class="mb-1"><strong>Citations:</strong> ${doc.enhanced_citations ? '<span class="badge bg-success">Enhanced</span>' : '<span class="badge bg-secondary">Standard</span>'}</p>
                    <p class="mb-1"><strong>Publication Date:</strong> ${escapeHtml(doc.publication_date || "N/A")}</p>
                    <p class="mb-1"><strong>Keywords:</strong> ${escapeHtml(Array.isArray(doc.keywords) ? doc.keywords.join(", ") : doc.keywords || "N/A")}</p>
                    <p class="mb-0"><strong>Abstract:</strong> ${escapeHtml(doc.abstract || "N/A")}</p>
                    <hr class="my-2">
                    <div class="d-flex flex-wrap gap-2">
                         <button class="btn btn-sm btn-info" onclick="window.onEditDocument('${docId}')" title="Edit Metadata">
                            <i class="bi bi-pencil-fill"></i> Edit Metadata
                         </button>
            `;

        // Check window flag before rendering extract button - CORRECTED CHECK
        if (window.enable_extract_meta_data === true || window.enable_extract_meta_data === "true") {
            detailsHtml += `
                <button class="btn btn-sm btn-warning" onclick="window.onExtractMetadata('${docId}', event)" title="Re-run Metadata Extraction">
                    <i class="bi bi-magic"></i> Extract Metadata
                </button>
            `;
        }

        detailsHtml += `</div></div></td>`;
        detailsRow.innerHTML = detailsHtml;
        documentsTableBody.appendChild(detailsRow);
    }

    // Add status row if not complete OR if there's an error
    if (!isComplete || hasError) {
        const statusRow = document.createElement("tr");
        statusRow.id = `status-row-${docId}`;
        if (hasError) {
             statusRow.innerHTML = `
                <td colspan="4">
                    <div class="alert alert-danger alert-sm py-1 px-2 mb-0 small" role="alert">
                        <i class="bi bi-exclamation-triangle-fill me-1"></i> Error: ${escapeHtml(docStatus)}
                    </div>
                </td>`;
        } else if (pct < 100) { // Still processing
             statusRow.innerHTML = `
                <td colspan="4">
                    <div class="progress" style="height: 10px;" title="Status: ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)">
                        <div id="progress-bar-${docId}" class="progress-bar progress-bar-striped progress-bar-animated bg-info" role="progressbar" style="width: ${pct}%;" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"></div>
                    </div>
                    <div class="text-muted text-end small" id="status-text-${docId}">${escapeHtml(docStatus)} (${pct.toFixed(0)}%)</div>
                </td>`;
        } else { // Should technically be complete now, but edge case?
             statusRow.innerHTML = `
                <td colspan="4">
                    <small class="text-muted">Status: Finalizing...</small>
                </td>`;
        }

        documentsTableBody.appendChild(statusRow);

        // Start polling only if it's still processing (not if it's already errored)
        if (!isComplete && !hasError) {
            pollDocumentStatus(docId);
        }
    }
}


function renderDocsPaginationControls(page, pageSize, totalCount) {
    if (!docsPaginationContainer) return;
    docsPaginationContainer.innerHTML = ""; // clear old
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
        if (docsCurrentPage > 1) {
            docsCurrentPage -= 1;
            fetchUserDocuments(); // Call the correct fetch function
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
        if (docsCurrentPage < totalPages) {
            docsCurrentPage += 1;
            fetchUserDocuments(); // Call the correct fetch function
        }
    });
    nextLi.appendChild(nextA);

    // Determine page numbers to display
    const maxPagesToShow = 5; // Max number of page links shown (e.g., 1 ... 4 5 6 ... 10)
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
        firstA.addEventListener('click', (e) => { e.preventDefault(); docsCurrentPage = 1; fetchUserDocuments(); });
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
            if (docsCurrentPage !== p) {
                docsCurrentPage = p;
                fetchUserDocuments(); // Call the correct fetch function
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
        lastA.addEventListener('click', (e) => { e.preventDefault(); docsCurrentPage = totalPages; fetchUserDocuments(); });
        lastLi.appendChild(lastA); ul.appendChild(lastLi);
    }

    ul.appendChild(nextLi);
    docsPaginationContainer.appendChild(ul); // Append to the correct container
}


window.toggleDetails = function (docId) {
    const detailsRow = document.getElementById(`details-row-${docId}`);
    const arrowIcon = document.getElementById(`arrow-icon-${docId}`);
    if (!detailsRow || !arrowIcon) return;

    if (detailsRow.style.display === "none") {
        detailsRow.style.display = ""; // Use "" to revert to default table row display
        arrowIcon.classList.remove("bi-chevron-right");
        arrowIcon.classList.add("bi-chevron-down");
    } else {
        detailsRow.style.display = "none";
        arrowIcon.classList.remove("bi-chevron-down");
        arrowIcon.classList.add("bi-chevron-right");
    }
};


function pollDocumentStatus(documentId) {
    if (activePolls.has(documentId)) {
        // console.log(`Polling already active for ${documentId}`);
        return; // Already polling this document
    }
    activePolls.add(documentId);
    // console.log(`Started polling for ${documentId}`);

    const intervalId = setInterval(() => {
        // Check if the document elements still exist in the DOM
        const docRow = document.getElementById(`doc-row-${documentId}`);
        const statusRow = document.getElementById(`status-row-${documentId}`);
        if (!docRow && !statusRow) { // Row likely removed (e.g., deleted, or page changed)
            // console.log(`Stopping polling for ${documentId} - elements not found.`);
            clearInterval(intervalId);
            activePolls.delete(documentId);
            return;
        }

        fetch(`/api/documents/${documentId}`)
            .then(r => {
                if (r.status === 404) { return Promise.reject(new Error('Document not found (likely deleted).')); }
                return r.ok ? r.json() : r.json().then(err => Promise.reject(err));
             })
            .then(doc => {
                 // Recalculate completion status based on latest data
                 const pctString = String(doc.percentage_complete);
                 const pct = /^\d+(\.\d+)?$/.test(pctString) ? parseFloat(pctString) : 0;
                 const docStatus = doc.status || "";
                 const isComplete = pct >= 100 || docStatus.toLowerCase().includes("complete") || docStatus.toLowerCase().includes("error");
                 const hasError = docStatus.toLowerCase().includes("error");

                if (!isComplete && statusRow) {
                     // Update progress bar and status text if still processing
                     const progressBar = statusRow.querySelector(`#progress-bar-${documentId}`);
                     const statusText = statusRow.querySelector(`#status-text-${documentId}`);
                     if (progressBar) {
                        progressBar.style.width = pct + "%";
                        progressBar.setAttribute("aria-valuenow", pct);
                        progressBar.parentNode.setAttribute('title', `Status: ${escapeHtml(docStatus)} (${pct.toFixed(0)}%)`);
                     }
                     if (statusText) { statusText.textContent = `${escapeHtml(docStatus)} (${pct.toFixed(0)}%)`; }
                     // console.log(`Polling ${documentId}: Status ${docStatus}, ${pct}%`);
                }
                else { // Processing is complete (or errored)
                    // console.log(`Polling ${documentId}: Completed/Errored. Status: ${docStatus}, ${pct}%`);
                    clearInterval(intervalId);
                    activePolls.delete(documentId);
                    if (statusRow) { statusRow.remove(); } // Remove the progress/status row
                    // Wait 5 seconds, then reload the table to show the detail button
                    setTimeout(() => {
                        const docRow = document.getElementById(`doc-row-${documentId}`);
                        if (docRow) fetchUserDocuments();
                    }, 5000);

                     if (docRow) { // Found the main row, let's replace it with the final version
                        const parent = docRow.parentNode;
                        const detailsRow = document.getElementById(`details-row-${documentId}`); // Check if details row exists from a previous render
                        docRow.remove(); // Remove old main row
                        if (detailsRow) detailsRow.remove(); // Remove old details row if it existed

                        // Re-render using the latest doc data which now indicates completion/error
                        renderDocumentRow(doc);
                     } else {
                         // Should not happen often, but if the row vanished unexpectedly, refresh list
                         console.warn(`Doc row ${documentId} not found after completion, refreshing full list.`);
                         fetchUserDocuments();
                     }
                }
            })
            .catch(err => {
                console.error(`Error polling document ${documentId}:`, err);
                clearInterval(intervalId);
                activePolls.delete(documentId);
                // Update UI to show polling failed
                if (statusRow) {
                    statusRow.innerHTML = `<td colspan="4"><div class="alert alert-warning alert-sm py-1 px-2 mb-0 small" role="alert"><i class="bi bi-exclamation-triangle-fill me-1"></i>Could not retrieve status: ${escapeHtml(err.message || 'Polling failed')}</div></td>`;
                }
                 // Maybe update the icon in the main row too if status row isn't visible
                 if (docRow && docRow.cells[0]) {
                    const currentIcon = docRow.cells[0].querySelector('span i'); // Find any icon
                     // Only change if it's not already an error icon
                     if (currentIcon && !currentIcon.classList.contains('bi-exclamation-triangle-fill')) {
                         docRow.cells[0].innerHTML = '<span class="text-warning" title="Status Unavailable"><i class="bi bi-question-circle-fill"></i></span>';
                     }
                 }
            });
    }, 5000); // Poll every 5 seconds
}

// --- show the upgrade alert into your placeholder ---
function showLegacyUpdatePrompt() {
    // don’t re‑show if it’s already there
    if (document.getElementById('legacy-update-alert')) return;
  
    const placeholder = document.getElementById('legacy-update-prompt-placeholder');
    if (!placeholder) return;
  
    placeholder.innerHTML = `
      <div
        id="legacy-update-alert"
        class="alert alert-info alert-dismissible fade show mt-3"
        role="alert"
      >
        <h5 class="alert-heading">
          <i class="bi bi-info-circle-fill me-2"></i>
          Update Older Documents
        </h5>
        <p class="mb-2 small">
          Some of your documents were uploaded with an older version.
          Updating them now will restore full compatibility
          (including metadata display, search, etc.).
        </p>
        <button
          type="button"
          class="btn btn-primary btn-sm me-2"
          id="confirm-legacy-update-btn"
        >
          Update Now
        </button>
        <button
          type="button"
          class="btn btn-secondary btn-sm"
          data-bs-dismiss="alert"
          aria-label="Close"
        >
          Maybe Later
        </button>
      </div>
    `;
  
    document
      .getElementById('confirm-legacy-update-btn')
      .addEventListener('click', handleLegacyUpdateConfirm);
  }
  
  // --- call the upgrade_legacy endpoint on confirmation ---
  async function handleLegacyUpdateConfirm() {
    const btn = document.getElementById('confirm-legacy-update-btn');
    if (!btn) return;
  
    btn.disabled = true;
    btn.innerHTML = `
      <span
        class="spinner-border spinner-border-sm me-2"
        role="status"
        aria-hidden="true"
      ></span>Updating...
    `;
  
    try {
      const res = await fetch('/api/documents/upgrade_legacy', { method: 'POST' });
      const json = await res.json();
      if (!res.ok) throw new Error(json.error || res.statusText);
  
      // if your endpoint returns { updated_count, failed_count }, you can use those
      alert(json.message || 'All done!');
  
      // hide the prompt & reload
      document.getElementById('legacy-update-alert')?.remove();
      fetchUserDocuments();
    } catch (err) {
      console.error('Legacy update failed', err);
      alert('Failed to upgrade documents: ' + err.message);
      btn.disabled = false;
      btn.textContent = 'Update Now';
    }
  }
  

window.onEditDocument = function(docId) {
    if (!docMetadataModalEl) {
        console.error("Metadata modal element not found.");
        return;
    }
    fetch(`/api/documents/${docId}`)
        .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
        .then(doc => {
            const docIdInput = document.getElementById("doc-id");
            const docTitleInput = document.getElementById("doc-title");
            const docAbstractInput = document.getElementById("doc-abstract");
            const docKeywordsInput = document.getElementById("doc-keywords");
            const docPubDateInput = document.getElementById("doc-publication-date");
            const docAuthorsInput = document.getElementById("doc-authors");
            const classificationSelect = document.getElementById("doc-classification"); // Use the correct ID

            if (docIdInput) docIdInput.value = doc.id;
            if (docTitleInput) docTitleInput.value = doc.title || "";
            if (docAbstractInput) docAbstractInput.value = doc.abstract || "";
            if (docKeywordsInput) docKeywordsInput.value = Array.isArray(doc.keywords) ? doc.keywords.join(", ") : (doc.keywords || "");
            if (docPubDateInput) docPubDateInput.value = doc.publication_date || "";
            if (docAuthorsInput) docAuthorsInput.value = Array.isArray(doc.authors) ? doc.authors.join(", ") : (doc.authors || "");

            // Handle classification dropdown visibility and value based on the window flag - CORRECTED CHECK
            if ((window.enable_document_classification === true || window.enable_document_classification === "true") && classificationSelect) {
                 // Set value to 'none' if classification is null/empty/undefined, otherwise set to the label
                 const currentClassification = doc.document_classification || 'none';
                 classificationSelect.value = currentClassification;
                 // Double-check if the value actually exists in the options, otherwise default to "" (All) or 'none'
                 if (![...classificationSelect.options].some(option => option.value === classificationSelect.value)) {
                      console.warn(`Classification value "${currentClassification}" not found in dropdown, defaulting.`);
                      classificationSelect.value = "none"; // Default to 'none' if value is invalid
                 }
                classificationSelect.closest('.mb-3').style.display = ''; // Ensure container is visible
            } else if (classificationSelect) {
                 // Hide classification if the feature flag is false
                 classificationSelect.closest('.mb-3').style.display = 'none';
            }

            docMetadataModalEl.show();
        })
        .catch(err => {
            console.error("Error retrieving document for edit:", err);
            alert("Error retrieving document details: " + (err.error || err.message || "Unknown error"));
        });
}


window.onExtractMetadata = function (docId, event) {
    // Check window flag - CORRECTED CHECK
    if (!(window.enable_extract_meta_data === true || window.enable_extract_meta_data === "true")) {
        alert("Metadata extraction is not enabled."); return;
    }
    if (!confirm("Run metadata extraction for this document? This may overwrite existing metadata.")) return;

    const extractBtn = event ? event.target.closest('button') : null;
    if (extractBtn) {
        extractBtn.disabled = true;
        extractBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Extracting...`;
    }

    fetch(`/api/documents/${docId}/extract_metadata`, { method: "POST", headers: { "Content-Type": "application/json" } })
        .then(r => r.ok ? r.json() : r.json().then(err => Promise.reject(err)))
        .then(data => {
            console.log("Metadata extraction started/completed:", data);
            // Refresh the list after a short delay to allow backend processing
            setTimeout(fetchUserDocuments, 1500);
            //alert(data.message || "Metadata extraction process initiated.");
            // Optionally close the details view if open
            const detailsRow = document.getElementById(`details-row-${docId}`);
            if (detailsRow && detailsRow.style.display !== "none") {
                 window.toggleDetails(docId); // Close details to show updated summary row first
            }
        })
        .catch(err => {
            console.error("Error calling extract metadata:", err);
            alert("Error extracting metadata: " + (err.error || err.message || "Unknown error"));
        })
        .finally(() => {
            if (extractBtn) {
                 // Check if button still exists before re-enabling
                 if (document.body.contains(extractBtn)) {
                    extractBtn.disabled = false;
                    extractBtn.innerHTML = '<i class="bi bi-magic"></i> Extract Metadata';
                 }
            }
        });
};


window.deleteDocument = function(documentId, event) {
    if (!confirm("Are you sure you want to delete this document? This action cannot be undone.")) return;

    const deleteBtn = event ? event.target.closest('button') : null;
    if (deleteBtn) {
        deleteBtn.disabled = true;
        deleteBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;
    }

    // Stop polling if active for this document
    if (activePolls.has(documentId)) {
        // Find the interval ID associated with this poll to clear it (more robust approach needed if storing interval IDs)
        // For now, just remove from the active set; the poll will eventually fail or stop when elements disappear
        activePolls.delete(documentId);
        // Ideally, you'd store intervalId with the docId in a map to clear it here.
    }


    fetch(`/api/documents/${documentId}`, { method: "DELETE" })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => Promise.reject(data)).catch(() => Promise.reject({ error: `Server responded with status ${response.status}` }));
            }
            return response.json();
        })
        .then(data => {
            console.log("Document deleted successfully:", data);
            const docRow = document.getElementById(`doc-row-${documentId}`);
            const detailsRow = document.getElementById(`details-row-${documentId}`);
            const statusRow = document.getElementById(`status-row-${documentId}`);
            if (docRow) docRow.remove();
            if (detailsRow) detailsRow.remove();
            if (statusRow) statusRow.remove();

             // Refresh if the table body becomes empty OR to update pagination total count
             if (documentsTableBody && documentsTableBody.childElementCount === 0) {
                 fetchUserDocuments(); // Refresh to show 'No documents' message and correct pagination
             } else {
                  // Maybe just decrement total count locally and re-render pagination?
                  // For simplicity, a full refresh might be acceptable unless dealing with huge lists/slow API
                  fetchUserDocuments(); // Refresh to update pagination potentially
             }

        })
        .catch(error => {
            console.error("Error deleting document:", error);
            alert("Error deleting document: " + (error.error || error.message || "Unknown error"));
            // Re-enable button only if it still exists
            if (deleteBtn && document.body.contains(deleteBtn)) {
                 deleteBtn.disabled = false;
                 deleteBtn.innerHTML = '<i class="bi bi-trash-fill"></i>';
            }
        });
}

window.removeSelfFromDocument = function(documentId, event) {
    if (!confirm("Are you sure you want to remove yourself from this shared document? You will no longer have access to it.")) return;

    const removeBtn = event ? event.target.closest('button') : null;
    if (removeBtn) {
        removeBtn.disabled = true;
        removeBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span>`;
    }

    fetch(`/api/documents/${documentId}/remove-self`, { method: "DELETE" })
        .then(response => {
            if (!response.ok) {
                return response.json().then(data => Promise.reject(data)).catch(() => Promise.reject({ error: `Server responded with status ${response.status}` }));
            }
            return response.json();
        })
        .then(data => {
            console.log("Successfully removed from document:", data);
            // Remove the document row from the table since user no longer has access
            const docRow = document.getElementById(`doc-row-${documentId}`);
            const detailsRow = document.getElementById(`details-row-${documentId}`);
            const statusRow = document.getElementById(`status-row-${documentId}`);
            if (docRow) docRow.remove();
            if (detailsRow) detailsRow.remove();
            if (statusRow) statusRow.remove();

            // Refresh if the table body becomes empty OR to update pagination total count
            if (documentsTableBody && documentsTableBody.childElementCount === 0) {
                fetchUserDocuments(); // Refresh to show 'No documents' message and correct pagination
            } else {
                fetchUserDocuments(); // Refresh to update pagination potentially
            }

            // Show success message
            if (window.showToast) {
                window.showToast('Successfully removed from shared document', 'success');
            }
        })
        .catch(error => {
            console.error("Error removing self from document:", error);
            alert("Error removing yourself from document: " + (error.error || error.message || "Unknown error"));
            // Re-enable button only if it still exists
            if (removeBtn && document.body.contains(removeBtn)) {
                removeBtn.disabled = false;
                removeBtn.innerHTML = '<i class="bi bi-x-circle"></i>';
            }
        });
}

window.redirectToChat = function(documentId) {
    window.location.href = `/chats?search_documents=true&doc_scope=personal&document_id=${documentId}`;
}

// Make fetchUserDocuments globally available for workspace-init.js
window.fetchUserDocuments = fetchUserDocuments;

// Approve shared document handler
window.approveSharedDocument = async function(documentId, btn, ownerOid) {
    let ownerInfo = { display_name: "the owner", email: "" };
    if (ownerOid) {
        try {
            const resp = await fetch(`/api/user/info/${ownerOid}`);
            if (resp.ok) {
                const data = await resp.json();
                ownerInfo.display_name = data.display_name || data.displayName || "the owner";
                ownerInfo.email = data.email || "";
            }
        } catch (e) {}
    }
    let msg = `This file was shared with you by <strong>${escapeHtml(ownerInfo.display_name)}</strong>`;
    if (ownerInfo.email) msg += ` (<span class="text-muted">${escapeHtml(ownerInfo.email)}</span>)`;
    msg += ".<br>Do you want to approve access to this shared document?";

    // Populate and show the modal
    const modalEl = document.getElementById("approveSharedModal");
    const modalBody = document.getElementById("approveSharedModalBody");
    const approveBtn = document.getElementById("approveSharedModalApproveBtn");
    const cancelBtn = document.getElementById("approveSharedModalCancelBtn");
    if (!modalEl || !modalBody || !approveBtn) {
        alert("Approval modal not found in the page.");
        return;
    }
    modalBody.innerHTML = msg;
    approveBtn.disabled = false;
    approveBtn.innerHTML = "Approve";
    // Remove previous event listeners
    approveBtn.onclick = null;
    cancelBtn.onclick = null;

    // Approve action
    approveBtn.onclick = async function() {
        approveBtn.disabled = true;
        approveBtn.innerHTML = `<span class="spinner-border spinner-border-sm" role="status" aria-hidden="true"></span> Approving...`;
        try {
            const response = await fetch(`/api/documents/${documentId}/approve-share`, { method: "POST" });
            const data = await response.json();
            if (response.ok) {
                if (window.showToast) window.showToast('Document access approved', 'success');
                // Hide modal
                bootstrap.Modal.getOrCreateInstance(modalEl).hide();
                fetchUserDocuments();
            } else {
                alert(data.error || "Failed to approve document");
                approveBtn.disabled = false;
                approveBtn.innerHTML = "Approve";
            }
        } catch (err) {
            alert("Error approving document: " + (err.error || err.message || "Unknown error"));
            approveBtn.disabled = false;
            approveBtn.innerHTML = "Approve";
        }
    };
    // Cancel just closes the modal
    cancelBtn.onclick = function() {
        bootstrap.Modal.getOrCreateInstance(modalEl).hide();
    };
    // Show the modal
    bootstrap.Modal.getOrCreateInstance(modalEl).show();
};