// chat-enhanced-citations.js
// Enhanced citation handling for different media types

import { showToast } from "./chat-toast.js";
import { showLoadingIndicator, hideLoadingIndicator } from "./chat-loading-indicator.js";
import { getDocumentMetadata, fetchDocumentMetadata } from './chat-documents.js';

/**
 * Determine file type from filename extension
 * @param {string} fileName - The file name
 * @returns {string} - File type: 'image', 'pdf', 'video', 'audio', or 'other'
 */
export function getFileType(fileName) {
    if (!fileName) return 'other';
    
    const ext = fileName.toLowerCase().split('.').pop();
    
    const imageExtensions = ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif'];
    const videoExtensions = ['mp4', 'mov', 'avi', 'mkv', 'flv', 'webm', 'wmv', 'm4v', '3gp'];
    const audioExtensions = ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a'];
    const tabularExtensions = ['csv', 'xlsx', 'xls', 'xlsm'];

    if (imageExtensions.includes(ext)) return 'image';
    if (ext === 'pdf') return 'pdf';
    if (videoExtensions.includes(ext)) return 'video';
    if (audioExtensions.includes(ext)) return 'audio';
    if (tabularExtensions.includes(ext)) return 'tabular';
    
    return 'other';
}

/**
 * Show enhanced citation modal based on file type
 * @param {string} docId - Document ID
 * @param {string|number} pageNumberOrTimestamp - Page number for PDF or timestamp for video/audio
 * @param {string} citationId - Citation ID for fallback
 * @param {string|null} initialSheetName - Workbook sheet to open initially for tabular files
 */
export async function showEnhancedCitationModal(docId, pageNumberOrTimestamp, citationId, initialSheetName = null) {
    // Get document metadata to determine file type. Historical cited revisions
    // are not in the current workspace list, so fetch on demand when needed.
    let docMetadata = getDocumentMetadata(docId);
    if (!docMetadata || !docMetadata.file_name) {
        docMetadata = await fetchDocumentMetadata(docId);
    }

    if (!docMetadata || !docMetadata.file_name) {
        console.warn('Document metadata not found, falling back to text citation');
        // Import fetchCitedText dynamically to avoid circular imports
        import('./chat-citations.js').then(module => {
            module.fetchCitedText(citationId);
        });
        return;
    }

    const fileType = getFileType(docMetadata.file_name);
    
    switch (fileType) {
        case 'image':
            showImageModal(docId, docMetadata.file_name);
            break;
        case 'pdf':
            showPdfModal(docId, pageNumberOrTimestamp, citationId);
            break;
        case 'video':
            // For video/audio files, pageNumberOrTimestamp is actually the chunk_sequence (seconds offset)
            // Convert to timestamp for seeking
            const videoTimestamp = convertTimestampToSeconds(pageNumberOrTimestamp);
            showVideoModal(docId, videoTimestamp, docMetadata.file_name);
            break;
        case 'audio':
            // For video/audio files, pageNumberOrTimestamp is actually the chunk_sequence (seconds offset)
            // Convert to timestamp for seeking
            const audioTimestamp = convertTimestampToSeconds(pageNumberOrTimestamp);
            showAudioModal(docId, audioTimestamp, docMetadata.file_name);
            break;
        case 'tabular':
            showTabularDownloadModal(docId, docMetadata.file_name, initialSheetName);
            break;
        default:
            // Fall back to text citation for unsupported types
            import('./chat-citations.js').then(module => {
                module.fetchCitedText(citationId);
            });
            break;
    }
}

/**
 * Show image in a modal
 * @param {string} docId - Document ID
 * @param {string} fileName - File name
 */
export function showImageModal(docId, fileName) {
    console.log(`Showing image modal for docId: ${docId}, fileName: ${fileName}`);
    showLoadingIndicator();
    
    // Create or get image modal
    let imageModal = document.getElementById("enhanced-image-modal");
    if (!imageModal) {
        imageModal = createImageModal();
    }
    
    // Set image source and title directly to the server endpoint
    const img = imageModal.querySelector("#enhanced-image");
    const title = imageModal.querySelector(".modal-title");
    
    // Use the server-side rendering endpoint directly as image source
    const imageUrl = `/api/enhanced_citations/image?doc_id=${encodeURIComponent(docId)}`;
    
    img.onload = function() {
        hideLoadingIndicator();
        console.log('Image loaded successfully');
    };
    
    img.onerror = function() {
        hideLoadingIndicator();
        console.error('Error loading image');
        showToast('Could not load image', 'danger');
    };
    
    img.src = imageUrl;
    title.textContent = `Image: ${fileName}`;
    
    // Show modal
    const modalInstance = new bootstrap.Modal(imageModal);
    modalInstance.show();
}

/**
 * Show PDF modal using server-side rendering
 * @param {string} docId - Document ID  
 * @param {string|number} pageNumber - Page number
 * @param {string} citationId - Citation ID for fallback
 */
export function showPdfModal(docId, pageNumber, citationId) {
    console.log(`Showing PDF modal for docId: ${docId}, page: ${pageNumber}`);
    showLoadingIndicator();
    
    // Use the new server-side rendering endpoint
    const pdfUrl = `/api/enhanced_citations/pdf?doc_id=${encodeURIComponent(docId)}&page=${encodeURIComponent(pageNumber)}`;
    
    // Get or create PDF modal
    let pdfModal = document.getElementById('pdfModal');
    if (!pdfModal) {
        pdfModal = createPdfModal();
        document.body.appendChild(pdfModal);
    }
    
    const pdfFrame = pdfModal.querySelector('#pdfFrame');
    const pdfTitle = pdfModal.querySelector('#pdfModalTitle');
    
    // Set the PDF source directly to our server-side rendering endpoint
    pdfFrame.src = pdfUrl;
    pdfTitle.textContent = `PDF Document - Page ${pageNumber}`;
    
    // Handle loading and error states
    pdfFrame.onload = function() {
        hideLoadingIndicator();
        console.log('PDF loaded successfully');
    };
    
    pdfFrame.onerror = function() {
        hideLoadingIndicator();
        console.error('Failed to load PDF');
        showToast('Failed to load PDF document', 'error');
        
        // Fall back to text citation
        import('./chat-citations.js').then(module => {
            module.fetchCitedText(citationId);
        });
    };
    
    // Show the modal
    const modalInstance = new bootstrap.Modal(pdfModal);
    modalInstance.show();
}

/**
 * Show video in a modal with timestamp navigation
 * @param {string} docId - Document ID
 * @param {string|number} timestamp - Timestamp in format "HH:MM:SS" or seconds
 * @param {string} fileName - File name
 */
export function showVideoModal(docId, timestamp, fileName) {
    console.log(`Showing video modal for docId: ${docId}, timestamp: ${timestamp}, fileName: ${fileName}`);
    showLoadingIndicator();
    
    // Create or get video modal
    let videoModal = document.getElementById("enhanced-video-modal");
    if (!videoModal) {
        videoModal = createVideoModal();
    }
    
    // Set video source and title directly to the server endpoint
    const video = videoModal.querySelector("#enhanced-video");
    const title = videoModal.querySelector(".modal-title");
    
    // Use the server-side rendering endpoint directly as video source
    const videoUrl = `/api/enhanced_citations/video?doc_id=${encodeURIComponent(docId)}`;
    
    video.onloadedmetadata = function() {
        hideLoadingIndicator();
        console.log(`Video loaded. Duration: ${video.duration} seconds.`);
        
        // Convert timestamp to seconds if needed
        const timeInSeconds = convertTimestampToSeconds(timestamp);
        console.log(`Setting video time to: ${timeInSeconds} seconds`);
        
        if (timeInSeconds > 0 && timeInSeconds < video.duration) {
            video.currentTime = timeInSeconds;
        } else if (timeInSeconds >= video.duration) {
            console.warn(`Timestamp ${timeInSeconds} is beyond video duration ${video.duration}, setting to end`);
            video.currentTime = Math.max(0, video.duration - 1);
        }
    };
    
    video.onerror = function() {
        hideLoadingIndicator();
        console.error('Error loading video');
        showToast('Could not load video', 'danger');
    };
    
    video.src = videoUrl;
    title.textContent = `Video: ${fileName}`;
    
    // Show modal
    const modalInstance = new bootstrap.Modal(videoModal);
    
    // Add event listener to stop video when modal is hidden
    videoModal.addEventListener('hidden.bs.modal', function () {
        const video = videoModal.querySelector('#enhanced-video');
        if (video) {
            video.pause();
            video.currentTime = 0; // Reset to beginning for next time
        }
    }, { once: true }); // Use once: true to prevent multiple listeners
    
    modalInstance.show();
}

/**
 * Show audio player in a modal with timestamp navigation
 * @param {string} docId - Document ID
 * @param {string|number} timestamp - Timestamp in format "HH:MM:SS" or seconds
 * @param {string} fileName - File name
 */
export function showAudioModal(docId, timestamp, fileName) {
    console.log(`Showing audio modal for docId: ${docId}, timestamp: ${timestamp}, fileName: ${fileName}`);
    showLoadingIndicator();
    
    // Create or get audio modal
    let audioModal = document.getElementById("enhanced-audio-modal");
    if (!audioModal) {
        audioModal = createAudioModal();
    }
    
    // Set audio source and title directly to the server endpoint
    const audio = audioModal.querySelector("#enhanced-audio");
    const title = audioModal.querySelector(".modal-title");
    
    // Use the server-side rendering endpoint directly as audio source
    const audioUrl = `/api/enhanced_citations/audio?doc_id=${encodeURIComponent(docId)}`;
    
    audio.onloadedmetadata = function() {
        hideLoadingIndicator();
        console.log(`Audio loaded. Duration: ${audio.duration} seconds.`);
        
        // Convert timestamp to seconds if needed
        const timeInSeconds = convertTimestampToSeconds(timestamp);
        console.log(`Setting audio time to: ${timeInSeconds} seconds`);
        
        if (timeInSeconds > 0 && timeInSeconds < audio.duration) {
            audio.currentTime = timeInSeconds;
        } else if (timeInSeconds >= audio.duration) {
            console.warn(`Timestamp ${timeInSeconds} is beyond audio duration ${audio.duration}, setting to end`);
            audio.currentTime = Math.max(0, audio.duration - 1);
        }
    };
    
    audio.onerror = function() {
        hideLoadingIndicator();
        console.error('Error loading audio');
        showToast('Could not load audio', 'danger');
    };
    
    audio.src = audioUrl;
    title.textContent = `Audio: ${fileName}`;
    
    // Show modal
    const modalInstance = new bootstrap.Modal(audioModal);
    
    // Add event listener to stop audio when modal is hidden
    audioModal.addEventListener('hidden.bs.modal', function () {
        const audio = audioModal.querySelector('#enhanced-audio');
        if (audio) {
            audio.pause();
            audio.currentTime = 0; // Reset to beginning for next time
        }
    }, { once: true }); // Use once: true to prevent multiple listeners
    
    modalInstance.show();
}

function triggerBlobDownload(blob, filename) {
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = filename;
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
    window.setTimeout(() => URL.revokeObjectURL(url), 0);
}

function getDownloadFilename(response, fallbackFilename) {
    const contentDisposition = response.headers.get('Content-Disposition') || '';
    const utf8Match = contentDisposition.match(/filename\*=UTF-8''([^;]+)/i);
    if (utf8Match && utf8Match[1]) {
        try {
            return decodeURIComponent(utf8Match[1]);
        } catch (error) {
            console.warn('Could not decode UTF-8 filename from Content-Disposition:', error);
            return utf8Match[1];
        }
    }

    const quotedMatch = contentDisposition.match(/filename="([^"]+)"/i);
    if (quotedMatch && quotedMatch[1]) {
        return quotedMatch[1];
    }

    const unquotedMatch = contentDisposition.match(/filename=([^;]+)/i);
    if (unquotedMatch && unquotedMatch[1]) {
        return unquotedMatch[1].trim();
    }

    return fallbackFilename || 'download';
}

async function downloadTabularFile(downloadUrl, fallbackFilename, downloadBtn) {
    const originalMarkup = downloadBtn.innerHTML;
    downloadBtn.disabled = true;
    downloadBtn.classList.add('disabled');
    downloadBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1" role="status" aria-hidden="true"></span>Downloading...';

    try {
        const response = await fetch(downloadUrl, {
            credentials: 'same-origin',
        });

        if (!response.ok) {
            let errorMessage = `Could not download file (${response.status}).`;
            const contentType = response.headers.get('Content-Type') || '';

            if (contentType.includes('application/json')) {
                const errorData = await response.json().catch(() => null);
                if (errorData && errorData.error) {
                    errorMessage = errorData.error;
                }
            } else {
                const errorText = await response.text().catch(() => '');
                if (errorText) {
                    errorMessage = errorText;
                }
            }

            throw new Error(errorMessage);
        }

        const blob = await response.blob();
        const downloadFilename = getDownloadFilename(response, fallbackFilename);
        triggerBlobDownload(blob, downloadFilename);
    } catch (error) {
        console.error('Error downloading tabular file:', error);
        showToast(error.message || 'Could not download file.', 'danger');
    } finally {
        downloadBtn.disabled = false;
        downloadBtn.classList.remove('disabled');
        downloadBtn.innerHTML = originalMarkup;
    }
}

/**
 * Show tabular file preview modal with data table
 * @param {string} docId - Document ID
 * @param {string} fileName - File name
 * @param {string|null} initialSheetName - Workbook sheet to open initially
 */
export function showTabularDownloadModal(docId, fileName, initialSheetName = null) {
    console.log(`Showing tabular preview modal for docId: ${docId}, fileName: ${fileName}`);
    showLoadingIndicator();

    // Create or get tabular modal
    let tabularModal = document.getElementById("enhanced-tabular-modal");
    if (!tabularModal) {
        tabularModal = createTabularModal();
    }

    const title = tabularModal.querySelector(".modal-title");
    const tableContainer = tabularModal.querySelector("#enhanced-tabular-table-container");
    const rowInfo = tabularModal.querySelector("#enhanced-tabular-row-info");
    const downloadBtn = tabularModal.querySelector("#enhanced-tabular-download");
    const errorContainer = tabularModal.querySelector("#enhanced-tabular-error");
    const sheetControls = tabularModal.querySelector("#enhanced-tabular-sheet-controls");
    const sheetSelect = tabularModal.querySelector("#enhanced-tabular-sheet-select");

    title.textContent = `Tabular Data: ${fileName}`;
    tableContainer.innerHTML = '<div class="text-center p-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-2 text-muted">Loading data preview...</p></div>';
    rowInfo.textContent = '';
    errorContainer.classList.add('d-none');
    sheetControls.classList.add('d-none');
    sheetSelect.innerHTML = '';

    const downloadUrl = `/api/enhanced_citations/tabular_workspace?doc_id=${encodeURIComponent(docId)}`;
    downloadBtn.onclick = (event) => {
        event.preventDefault();
        downloadTabularFile(downloadUrl, fileName, downloadBtn);
    };

    // Show modal immediately with loading state
    const modalInstance = new bootstrap.Modal(tabularModal);
    modalInstance.show();

    const escapeOptionValue = (value) => String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;');

    const loadTabularPreview = (selectedSheetName = null) => {
        errorContainer.classList.add('d-none');

        const params = new URLSearchParams({
            doc_id: docId,
        });
        if (selectedSheetName) {
            params.set('sheet_name', selectedSheetName);
        }

        const previewUrl = `/api/enhanced_citations/tabular_preview?${params.toString()}`;
        fetch(previewUrl)
            .then(response => {
                if (!response.ok) throw new Error(`HTTP ${response.status}`);
                return response.json();
            })
            .then(data => {
                hideLoadingIndicator();
                if (data.error) {
                    showTabularError(tableContainer, errorContainer, data.error);
                    return;
                }

                title.textContent = data.selected_sheet
                    ? `Tabular Data: ${fileName} [${data.selected_sheet}]`
                    : `Tabular Data: ${fileName}`;

                const sheetNames = Array.isArray(data.sheet_names) ? data.sheet_names : [];
                if (sheetNames.length > 1) {
                    sheetControls.classList.remove('d-none');
                    sheetSelect.innerHTML = sheetNames
                        .map(sheetName => {
                            const isSelected = sheetName === data.selected_sheet ? ' selected' : '';
                            return `<option value="${escapeOptionValue(sheetName)}"${isSelected}>${escapeOptionValue(sheetName)}</option>`;
                        })
                        .join('');
                    sheetSelect.onchange = () => {
                        showLoadingIndicator();
                        loadTabularPreview(sheetSelect.value);
                    };
                } else {
                    sheetControls.classList.add('d-none');
                    sheetSelect.innerHTML = '';
                }

                renderTabularPreview(tableContainer, rowInfo, data);
            })
            .catch(error => {
                hideLoadingIndicator();
                console.error('Error loading tabular preview:', error);
                showTabularError(tableContainer, errorContainer, 'Could not load data preview.');
            });
    };

    loadTabularPreview(initialSheetName);
}

/**
 * Render tabular data as an HTML table
 * @param {HTMLElement} container - Table container element
 * @param {HTMLElement} rowInfo - Row info display element
 * @param {Object} data - Preview data from API
 */
function renderTabularPreview(container, rowInfo, data) {
    const { columns, rows, total_rows, truncated, selected_sheet } = data;

    // Build table HTML
    let html = '<table class="table table-striped table-bordered table-sm table-hover mb-0">';

    // Header
    html += '<thead class="table-dark sticky-top"><tr>';
    for (const col of columns) {
        const escaped = col.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
        html += `<th class="text-nowrap">${escaped}</th>`;
    }
    html += '</tr></thead>';

    // Body
    html += '<tbody>';
    for (const row of rows) {
        html += '<tr>';
        for (const cell of row) {
            const val = cell === null || cell === undefined ? '' : String(cell);
            const escaped = val.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
            html += `<td>${escaped}</td>`;
        }
        html += '</tr>';
    }
    html += '</tbody></table>';

    container.innerHTML = html;

    // Row info
    const displayedRows = rows.length;
    const hasTotalRows = total_rows !== null && total_rows !== undefined;
    const totalFormatted = hasTotalRows ? total_rows.toLocaleString() : displayedRows.toLocaleString();
    const sheetPrefix = selected_sheet ? `Sheet ${selected_sheet} · ` : '';
    if (truncated) {
        const truncationSuffix = hasTotalRows ? `${totalFormatted} rows` : `${displayedRows.toLocaleString()}+ rows`;
        rowInfo.textContent = `${sheetPrefix}Showing ${displayedRows.toLocaleString()} of ${truncationSuffix}`;
    } else {
        rowInfo.textContent = `${sheetPrefix}${totalFormatted} rows, ${columns.length} columns`;
    }
}

/**
 * Show error state in tabular modal with download fallback
 * @param {HTMLElement} tableContainer - Table container element
 * @param {HTMLElement} errorContainer - Error display element
 * @param {string} message - Error message
 */
function showTabularError(tableContainer, errorContainer, message) {
    tableContainer.innerHTML = '<div class="text-center p-4"><i class="bi bi-file-earmark-spreadsheet display-1 text-success"></i></div>';
    errorContainer.textContent = message + ' You can still download the file below.';
    errorContainer.classList.remove('d-none');
}

/**
 * Convert timestamp string to seconds
 * @param {string|number} timestamp - Timestamp in various formats
 * @returns {number} - Time in seconds
 */
function convertTimestampToSeconds(timestamp) {
    console.log(`Converting timestamp: ${timestamp} (type: ${typeof timestamp})`);
    
    if (typeof timestamp === 'number') {
        console.log(`Timestamp is already a number: ${timestamp} seconds`);
        return timestamp;
    }
    
    if (typeof timestamp === 'string') {
        // Try to parse as number first (for chunk_sequence values)
        const numericTimestamp = parseFloat(timestamp);
        if (!isNaN(numericTimestamp)) {
            console.log(`Parsed timestamp as number: ${numericTimestamp} seconds`);
            return numericTimestamp;
        }
        
        // Try to parse as HH:MM:SS or MM:SS format
        if (timestamp.includes(':')) {
            const parts = timestamp.split(':').map(part => parseFloat(part));
            if (parts.length === 3) {
                // HH:MM:SS
                const seconds = parts[0] * 3600 + parts[1] * 60 + parts[2];
                console.log(`Parsed HH:MM:SS timestamp: ${timestamp} = ${seconds} seconds`);
                return seconds;
            } else if (parts.length === 2) {
                // MM:SS
                const seconds = parts[0] * 60 + parts[1];
                console.log(`Parsed MM:SS timestamp: ${timestamp} = ${seconds} seconds`);
                return seconds;
            }
        }
    }
    
    console.warn(`Could not parse timestamp: ${timestamp}, defaulting to 0`);
    return 0;
}

/**
 * Create image modal HTML structure
 * @returns {HTMLElement} - Modal element
 */
function createImageModal() {
    const modal = document.createElement("div");
    modal.id = "enhanced-image-modal";
    modal.classList.add("modal", "fade");
    modal.tabIndex = -1;
    modal.innerHTML = `
        <div class="modal-dialog modal-lg modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Image Citation</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body text-center">
                    <img id="enhanced-image" class="img-fluid" alt="Citation Image" style="max-height: 70vh; object-fit: contain;">
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    return modal;
}

/**
 * Create video modal HTML structure
 * @returns {HTMLElement} - Modal element
 */
function createVideoModal() {
    const modal = document.createElement("div");
    modal.id = "enhanced-video-modal";
    modal.classList.add("modal", "fade");
    modal.tabIndex = -1;
    modal.innerHTML = `
        <div class="modal-dialog modal-xl modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Video Citation</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <video id="enhanced-video" controls class="w-100" style="max-height: 70vh;">
                        Your browser does not support the video tag.
                    </video>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    return modal;
}

/**
 * Create audio modal HTML structure
 * @returns {HTMLElement} - Modal element
 */
function createAudioModal() {
    const modal = document.createElement("div");
    modal.id = "enhanced-audio-modal";
    modal.classList.add("modal", "fade");
    modal.tabIndex = -1;
    modal.innerHTML = `
        <div class="modal-dialog modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Audio Citation</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body text-center">
                    <div class="mb-3">
                        <i class="bi bi-music-note-beamed display-1 text-primary"></i>
                    </div>
                    <audio id="enhanced-audio" controls class="w-100">
                        Your browser does not support the audio tag.
                    </audio>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    return modal;
}

/**
 * Create PDF modal for enhanced citations
 * @returns {HTMLElement} - The PDF modal element
 */
function createPdfModal() {
    const modal = document.createElement('div');
    modal.className = 'modal fade';
    modal.id = 'pdfModal';
    modal.tabIndex = -1;
    modal.innerHTML = `
        <div class="modal-dialog modal-xl modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title" id="pdfModalTitle">PDF Citation</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body">
                    <iframe id="pdfFrame" class="w-100" style="height: 70vh; border: none;">
                        Your browser does not support PDF viewing.
                    </iframe>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    return modal;
}

/**
 * Create tabular file preview modal HTML structure
 * @returns {HTMLElement} - Modal element
 */
function createTabularModal() {
    const modal = document.createElement("div");
    modal.id = "enhanced-tabular-modal";
    modal.classList.add("modal", "fade");
    modal.tabIndex = -1;
    modal.innerHTML = `
        <div class="modal-dialog modal-xl modal-dialog-centered">
            <div class="modal-content">
                <div class="modal-header">
                    <h5 class="modal-title">Tabular Data Citation</h5>
                    <button type="button" class="btn-close" data-bs-dismiss="modal" aria-label="Close"></button>
                </div>
                <div class="modal-body p-0">
                    <div id="enhanced-tabular-error" class="alert alert-warning m-3 d-none"></div>
                    <div id="enhanced-tabular-sheet-controls" class="px-3 pt-3 d-none">
                        <label for="enhanced-tabular-sheet-select" class="form-label small text-muted mb-1">Worksheet</label>
                        <select id="enhanced-tabular-sheet-select" class="form-select form-select-sm"></select>
                    </div>
                    <div id="enhanced-tabular-table-container" style="max-height: 60vh; overflow: auto;"></div>
                </div>
                <div class="modal-footer d-flex justify-content-between align-items-center">
                    <span id="enhanced-tabular-row-info" class="text-muted small"></span>
                    <button type="button" id="enhanced-tabular-download" class="btn btn-primary btn-sm">
                        <i class="bi bi-download me-1"></i>Download File
                    </button>
                </div>
            </div>
        </div>
    `;
    document.body.appendChild(modal);
    return modal;
}
