// chat-export.js
import { showToast } from "./chat-toast.js";

'use strict';

/**
 * Conversation Export Wizard Module
 *
 * Provides a multi-step modal wizard for exporting conversations
 * in JSON or Markdown format with single-file or ZIP packaging.
 */

// --- Wizard State ---
let exportConversationIds = [];
let exportConversationTitles = {};
let exportFormat = 'json';
let exportPackaging = 'single';
let includeSummaryIntro = false;
let summaryModelDeployment = '';
let currentStep = 1;
let totalSteps = 3;
let skipSelectionStep = false;

// Modal reference
let exportModal = null;

// --- DOM Helpers ---
function getEl(id) {
    return document.getElementById(id);
}

// --- Initialize ---
document.addEventListener('DOMContentLoaded', () => {
    const modalEl = getEl('export-wizard-modal');
    if (modalEl) {
        exportModal = new bootstrap.Modal(modalEl);
    }
});

// --- Public Entry Point ---

/**
 * Open the export wizard.
 * @param {string[]} conversationIds - Array of conversation IDs to export.
 * @param {boolean} skipSelection - If true, skip step 1 (review) and start at format choice.
 */
function openExportWizard(conversationIds, skipSelection) {
    if (!conversationIds || conversationIds.length === 0) {
        showToast('No conversations selected for export.', 'warning');
        return;
    }

    // Reset state
    exportConversationIds = [...conversationIds];
    exportConversationTitles = {};
    exportFormat = 'json';
    exportPackaging = conversationIds.length > 1 ? 'zip' : 'single';
    includeSummaryIntro = false;
    summaryModelDeployment = _getDefaultSummaryModel();
    skipSelectionStep = !!skipSelection;

    // Determine step configuration
    if (skipSelectionStep) {
        totalSteps = 4;
        currentStep = 1; // Format step (mapped to visual step)
    } else {
        totalSteps = 5;
        currentStep = 1; // Selection review step
    }

    // Initialize the modal if not already
    if (!exportModal) {
        const modalEl = getEl('export-wizard-modal');
        if (modalEl) {
            exportModal = new bootstrap.Modal(modalEl);
        }
    }

    if (!exportModal) {
        showToast('Export wizard not available.', 'danger');
        return;
    }

    // Load conversation titles, then show the modal
    _loadConversationTitles().then(() => {
        _renderCurrentStep();
        _updateStepIndicators();
        _updateNavigationButtons();
        exportModal.show();
    });
}

// --- Step Navigation ---

function nextStep() {
    if (currentStep < totalSteps) {
        currentStep++;
        _renderCurrentStep();
        _updateStepIndicators();
        _updateNavigationButtons();
    }
}

function prevStep() {
    if (currentStep > 1) {
        currentStep--;
        _renderCurrentStep();
        _updateStepIndicators();
        _updateNavigationButtons();
    }
}

// --- Data Loading ---

async function _loadConversationTitles() {
    try {
        const response = await fetch('/api/get_conversations');
        if (!response.ok) throw new Error('Failed to fetch conversations');
        const data = await response.json();
        const conversations = data.conversations || [];
        exportConversationTitles = {};
        conversations.forEach(c => {
            if (exportConversationIds.includes(c.id)) {
                exportConversationTitles[c.id] = c.title || 'Untitled';
            }
        });
        // Fill in any missing titles
        exportConversationIds.forEach(id => {
            if (!exportConversationTitles[id]) {
                exportConversationTitles[id] = 'Untitled Conversation';
            }
        });
    } catch (err) {
        console.error('Error loading conversation titles for export:', err);
        // Use placeholder titles
        exportConversationIds.forEach(id => {
            exportConversationTitles[id] = exportConversationTitles[id] || 'Conversation';
        });
    }
}

// --- Step Rendering ---

function _renderCurrentStep() {
    const stepBody = getEl('export-wizard-body');
    if (!stepBody) return;

    if (skipSelectionStep) {
        // Steps: 1=Format, 2=Packaging, 3=Summary, 4=Download
        switch (currentStep) {
            case 1: _renderFormatStep(stepBody); break;
            case 2: _renderPackagingStep(stepBody); break;
            case 3: _renderSummaryStep(stepBody); break;
            case 4: _renderDownloadStep(stepBody); break;
        }
    } else {
        // Steps: 1=Selection, 2=Format, 3=Packaging, 4=Summary, 5=Download
        switch (currentStep) {
            case 1: _renderSelectionStep(stepBody); break;
            case 2: _renderFormatStep(stepBody); break;
            case 3: _renderPackagingStep(stepBody); break;
            case 4: _renderSummaryStep(stepBody); break;
            case 5: _renderDownloadStep(stepBody); break;
        }
    }
}

function _renderSelectionStep(container) {
    const count = exportConversationIds.length;
    let listHtml = '';
    exportConversationIds.forEach(id => {
        const title = _escapeHtml(exportConversationTitles[id] || 'Untitled');
        listHtml += `
            <div class="d-flex align-items-center justify-content-between py-2 px-3 border-bottom export-conversation-item" data-id="${id}">
                <div class="d-flex align-items-center">
                    <i class="bi bi-chat-dots me-2 text-primary"></i>
                    <span>${title}</span>
                </div>
                <button class="btn btn-sm btn-outline-danger export-remove-btn" data-id="${id}" title="Remove from export">
                    <i class="bi bi-x-lg"></i>
                </button>
            </div>`;
    });

    container.innerHTML = `
        <div class="mb-3">
            <h6 class="mb-1">Review Conversations</h6>
            <p class="text-muted small mb-3">You have <strong>${count}</strong> conversation${count !== 1 ? 's' : ''} selected for export. Remove any you don't want to include.</p>
        </div>
        <div class="border rounded" style="max-height: 300px; overflow-y: auto;">
            ${listHtml || '<div class="p-3 text-muted text-center">No conversations selected</div>'}
        </div>`;

    // Wire remove buttons
    container.querySelectorAll('.export-remove-btn').forEach(btn => {
        btn.addEventListener('click', (e) => {
            e.preventDefault();
            const removeId = btn.dataset.id;
            exportConversationIds = exportConversationIds.filter(id => id !== removeId);
            delete exportConversationTitles[removeId];
            if (exportConversationIds.length === 0) {
                showToast('All conversations removed. Closing export wizard.', 'warning');
                exportModal.hide();
                return;
            }
            _renderSelectionStep(container);
            _updateNavigationButtons();
        });
    });
}

function _renderFormatStep(container) {
    container.innerHTML = `
        <div class="mb-3">
            <h6 class="mb-1">Choose Export Format</h6>
            <p class="text-muted small mb-3">Select the format for your exported conversations.</p>
        </div>
        <div class="row g-3">
            <div class="col-4">
                <div class="action-type-card card h-100 text-center p-3 ${exportFormat === 'json' ? 'selected' : ''}" data-format="json" role="button" tabindex="0">
                    <div class="card-body d-flex flex-column align-items-center justify-content-center">
                        <i class="bi bi-filetype-json display-5 mb-2 text-primary"></i>
                        <h6 class="mb-1">JSON</h6>
                        <p class="text-muted small mb-0">Structured data format. Ideal for programmatic analysis or re-import.</p>
                    </div>
                </div>
            </div>
            <div class="col-4">
                <div class="action-type-card card h-100 text-center p-3 ${exportFormat === 'markdown' ? 'selected' : ''}" data-format="markdown" role="button" tabindex="0">
                    <div class="card-body d-flex flex-column align-items-center justify-content-center">
                        <i class="bi bi-filetype-md display-5 mb-2 text-success"></i>
                        <h6 class="mb-1">Markdown</h6>
                        <p class="text-muted small mb-0">Human-readable format. Great for documentation and sharing.</p>
                    </div>
                </div>
            </div>
            <div class="col-4">
                <div class="action-type-card card h-100 text-center p-3 ${exportFormat === 'pdf' ? 'selected' : ''}" data-format="pdf" role="button" tabindex="0">
                    <div class="card-body d-flex flex-column align-items-center justify-content-center">
                        <i class="bi bi-filetype-pdf display-5 mb-2 text-danger"></i>
                        <h6 class="mb-1">PDF</h6>
                        <p class="text-muted small mb-0">Print-ready format with chat bubbles. Ideal for archiving and printing.</p>
                    </div>
                </div>
            </div>
        </div>`;

    // Wire card clicks
    container.querySelectorAll('.action-type-card[data-format]').forEach(card => {
        card.addEventListener('click', () => {
            exportFormat = card.dataset.format;
            container.querySelectorAll('.action-type-card[data-format]').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
        });
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                card.click();
            }
        });
    });
}

function _renderPackagingStep(container) {
    const count = exportConversationIds.length;
    const singleDesc = count > 1
        ? 'All conversations combined into one file.'
        : 'Export as a single file.';
    const zipDesc = count > 1
        ? 'Each conversation in a separate file, bundled in a ZIP archive.'
        : 'Single conversation wrapped in a ZIP archive.';

    container.innerHTML = `
        <div class="mb-3">
            <h6 class="mb-1">Choose Output Packaging</h6>
            <p class="text-muted small mb-3">Select how the exported file(s) should be packaged.</p>
        </div>
        <div class="row g-3">
            <div class="col-6">
                <div class="action-type-card card h-100 text-center p-3 ${exportPackaging === 'single' ? 'selected' : ''}" data-packaging="single" role="button" tabindex="0">
                    <div class="card-body d-flex flex-column align-items-center justify-content-center">
                        <i class="bi bi-file-earmark display-5 mb-2 text-info"></i>
                        <h6 class="mb-1">Single File</h6>
                        <p class="text-muted small mb-0">${singleDesc}</p>
                    </div>
                </div>
            </div>
            <div class="col-6">
                <div class="action-type-card card h-100 text-center p-3 ${exportPackaging === 'zip' ? 'selected' : ''}" data-packaging="zip" role="button" tabindex="0">
                    <div class="card-body d-flex flex-column align-items-center justify-content-center">
                        <i class="bi bi-file-earmark-zip display-5 mb-2 text-warning"></i>
                        <h6 class="mb-1">ZIP Archive</h6>
                        <p class="text-muted small mb-0">${zipDesc}</p>
                    </div>
                </div>
            </div>
        </div>`;

    // Wire card clicks
    container.querySelectorAll('.action-type-card[data-packaging]').forEach(card => {
        card.addEventListener('click', () => {
            exportPackaging = card.dataset.packaging;
            container.querySelectorAll('.action-type-card[data-packaging]').forEach(c => c.classList.remove('selected'));
            card.classList.add('selected');
        });
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                card.click();
            }
        });
    });
}

function _renderSummaryStep(container) {
    const mainModelSelect = getEl('model-select');
    const hasModelOptions = Boolean(mainModelSelect && mainModelSelect.options.length > 0);
    const defaultSummaryModel = summaryModelDeployment || _getDefaultSummaryModel();
    const perConversationText = exportConversationIds.length > 1
        ? 'An intro will be generated for each exported conversation.'
        : 'An intro will be generated for this conversation.';

    container.innerHTML = `
        <div class="mb-3">
            <h6 class="mb-1">Optional Intro Summary</h6>
            <p class="text-muted small mb-3">Add a short abstract before the exported transcript. ${perConversationText}</p>
        </div>
        <div class="form-check form-switch mb-3">
            <input class="form-check-input" type="checkbox" role="switch" id="export-summary-toggle" ${includeSummaryIntro ? 'checked' : ''}>
            <label class="form-check-label" for="export-summary-toggle">Include AI-generated intro summary</label>
        </div>
        <div id="export-summary-model-container" class="card ${includeSummaryIntro ? '' : 'd-none'}">
            <div class="card-body">
                <label for="export-summary-model" class="form-label">Summary model</label>
                <select id="export-summary-model" class="form-select" ${hasModelOptions ? '' : 'disabled'}>
                    ${hasModelOptions ? mainModelSelect.innerHTML : '<option value="">No chat models available</option>'}
                </select>
                <div class="form-text">Uses the same model list as the chat composer.</div>
            </div>
        </div>`;

    const toggle = getEl('export-summary-toggle');
    const modelContainer = getEl('export-summary-model-container');
    const summaryModelSelect = getEl('export-summary-model');

    if (summaryModelSelect && hasModelOptions) {
        summaryModelSelect.value = defaultSummaryModel || summaryModelSelect.value;
        summaryModelDeployment = summaryModelSelect.value;
        summaryModelSelect.addEventListener('change', () => {
            summaryModelDeployment = summaryModelSelect.value;
        });
    }

    if (toggle) {
        toggle.addEventListener('change', () => {
            includeSummaryIntro = toggle.checked;
            if (modelContainer) {
                modelContainer.classList.toggle('d-none', !includeSummaryIntro);
            }
            if (includeSummaryIntro && summaryModelSelect && !summaryModelSelect.value) {
                summaryModelSelect.value = _getDefaultSummaryModel();
                summaryModelDeployment = summaryModelSelect.value;
            }
        });
    }
}

function _renderDownloadStep(container) {
    const count = exportConversationIds.length;
    const formatLabels = { json: 'JSON', markdown: 'Markdown', pdf: 'PDF' };
    const formatLabel = formatLabels[exportFormat] || exportFormat.toUpperCase();
    const packagingLabel = exportPackaging === 'zip' ? 'ZIP Archive' : 'Single File';
    const extMap = { json: '.json', markdown: '.md', pdf: '.pdf' };
    const ext = exportPackaging === 'zip' ? '.zip' : (extMap[exportFormat] || '.bin');
    const summaryLabel = includeSummaryIntro ? 'Enabled' : 'Disabled';
    const summaryModelLabel = includeSummaryIntro ? (summaryModelDeployment || 'Configured default') : '—';

    let conversationsList = '';
    exportConversationIds.forEach(id => {
        const title = _escapeHtml(exportConversationTitles[id] || 'Untitled');
        conversationsList += `<li class="list-group-item py-1 px-2 small"><i class="bi bi-chat-dots me-1 text-muted"></i>${title}</li>`;
    });

    container.innerHTML = `
        <div class="mb-3">
            <h6 class="mb-1">Ready to Export</h6>
            <p class="text-muted small mb-3">Review your export settings and click Download.</p>
        </div>
        <div class="card mb-3">
            <div class="card-body">
                <div class="row mb-2">
                    <div class="col-5 text-muted small">Conversations:</div>
                    <div class="col-7 fw-semibold small">${count} conversation${count !== 1 ? 's' : ''}</div>
                </div>
                <div class="row mb-2">
                    <div class="col-5 text-muted small">Format:</div>
                    <div class="col-7 fw-semibold small">${formatLabel}</div>
                </div>
                <div class="row mb-2">
                    <div class="col-5 text-muted small">Packaging:</div>
                    <div class="col-7 fw-semibold small">${packagingLabel}</div>
                </div>
                <div class="row mb-2">
                    <div class="col-5 text-muted small">Intro summary:</div>
                    <div class="col-7 fw-semibold small">${summaryLabel}</div>
                </div>
                <div class="row mb-2">
                    <div class="col-5 text-muted small">Summary model:</div>
                    <div class="col-7 fw-semibold small">${_escapeHtml(summaryModelLabel)}</div>
                </div>
                <div class="row">
                    <div class="col-5 text-muted small">File type:</div>
                    <div class="col-7 fw-semibold small">${ext}</div>
                </div>
            </div>
        </div>
        <div class="mb-3" style="max-height: 150px; overflow-y: auto;">
            <ul class="list-group list-group-flush">
                ${conversationsList}
            </ul>
        </div>
        <div class="text-center">
            <button class="btn btn-primary btn-lg" id="export-download-btn">
                <i class="bi bi-download me-2"></i>Download Export
            </button>
        </div>
        <div id="export-download-status" class="text-center mt-2"></div>`;

    // Wire download button
    const downloadBtn = getEl('export-download-btn');
    if (downloadBtn) {
        downloadBtn.addEventListener('click', _executeExport);
    }
}

// --- Step Indicator & Navigation ---

function _updateStepIndicators() {
    const stepsContainer = getEl('export-steps-container');
    if (!stepsContainer) return;

    let steps;
    if (skipSelectionStep) {
        steps = [
            { label: 'Format', icon: 'bi-filetype-json' },
            { label: 'Packaging', icon: 'bi-box' },
            { label: 'Summary', icon: 'bi-card-text' },
            { label: 'Download', icon: 'bi-download' }
        ];
    } else {
        steps = [
            { label: 'Select', icon: 'bi-list-check' },
            { label: 'Format', icon: 'bi-filetype-json' },
            { label: 'Packaging', icon: 'bi-box' },
            { label: 'Summary', icon: 'bi-card-text' },
            { label: 'Download', icon: 'bi-download' }
        ];
    }

    let html = '';
    steps.forEach((step, index) => {
        const stepNum = index + 1;
        let circleClass = 'step-circle';
        let indicatorClass = 'step-indicator';
        if (stepNum < currentStep) {
            circleClass += ' completed';
            indicatorClass += ' completed';
        } else if (stepNum === currentStep) {
            circleClass += ' active';
            indicatorClass += ' active';
        }

        // Add connector line between steps
        const connector = index < steps.length - 1
            ? '<div class="step-connector"></div>'
            : '';

        html += `
            <div class="${indicatorClass}">
                <div class="${circleClass}">${stepNum < currentStep ? '<i class="bi bi-check-lg"></i>' : stepNum}</div>
                <div class="step-label">${step.label}</div>
                ${connector}
            </div>`;
    });

    stepsContainer.innerHTML = html;
}

function _updateNavigationButtons() {
    const prevBtn = getEl('export-prev-btn');
    const nextBtn = getEl('export-next-btn');

    if (prevBtn) {
        prevBtn.style.display = currentStep > 1 ? 'inline-block' : 'none';
        prevBtn.onclick = prevStep;
    }

    if (nextBtn) {
        const isLastStep = currentStep === totalSteps;
        nextBtn.style.display = isLastStep ? 'none' : 'inline-block';
        nextBtn.onclick = nextStep;

        // Validate selection step — need at least 1 conversation
        if (!skipSelectionStep && currentStep === 1 && exportConversationIds.length === 0) {
            nextBtn.disabled = true;
        } else {
            nextBtn.disabled = false;
        }
    }
}

// --- Export Execution ---

async function _executeExport() {
    const downloadBtn = getEl('export-download-btn');
    const statusDiv = getEl('export-download-status');

    if (downloadBtn) {
        downloadBtn.disabled = true;
        downloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Generating export...';
    }
    if (statusDiv) {
        statusDiv.innerHTML = '<span class="text-muted small">This may take a moment for large conversations...</span>';
    }

    try {
        const response = await fetch('/api/conversations/export', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                conversation_ids: exportConversationIds,
                format: exportFormat,
                packaging: exportPackaging,
                include_summary_intro: includeSummaryIntro,
                summary_model_deployment: includeSummaryIntro ? summaryModelDeployment : null
            })
        });

        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.error || `Server responded with status ${response.status}`);
        }

        // Get filename from Content-Disposition header
        const disposition = response.headers.get('Content-Disposition') || '';
        const filenameMatch = disposition.match(/filename="?([^"]+)"?/);
        const fallbackExtMap = { json: 'json', markdown: 'md', pdf: 'pdf' };
        const filename = filenameMatch ? filenameMatch[1] : `conversations_export.${exportPackaging === 'zip' ? 'zip' : (fallbackExtMap[exportFormat] || 'bin')}`;

        // Download the blob
        const blob = await response.blob();
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = filename;
        document.body.appendChild(a);
        a.click();
        window.URL.revokeObjectURL(url);
        document.body.removeChild(a);

        if (downloadBtn) {
            downloadBtn.disabled = false;
            downloadBtn.innerHTML = '<i class="bi bi-check-circle me-2"></i>Downloaded!';
            downloadBtn.classList.remove('btn-primary');
            downloadBtn.classList.add('btn-success');
        }
        if (statusDiv) {
            statusDiv.innerHTML = '<span class="text-success small"><i class="bi bi-check-circle-fill me-1"></i>Export downloaded successfully.</span>';
        }

        showToast('Conversations exported successfully.', 'success');

        // Auto-close modal after a short delay
        setTimeout(() => {
            if (exportModal) exportModal.hide();
        }, 1500);

    } catch (err) {
        console.error('Export error:', err);
        if (downloadBtn) {
            downloadBtn.disabled = false;
            downloadBtn.innerHTML = '<i class="bi bi-download me-2"></i>Retry Download';
        }
        if (statusDiv) {
            statusDiv.innerHTML = `<span class="text-danger small"><i class="bi bi-exclamation-circle-fill me-1"></i>Error: ${_escapeHtml(err.message)}</span>`;
        }
        showToast(`Export failed: ${err.message}`, 'danger');
    }
}

// --- Utility ---

function _escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

function _getDefaultSummaryModel() {
    const mainModelSelect = getEl('model-select');
    if (!mainModelSelect) {
        return '';
    }

    return mainModelSelect.value || (mainModelSelect.options[0] ? mainModelSelect.options[0].value : '');
}

// --- Expose Globally ---
window.chatExport = {
    openExportWizard
};
