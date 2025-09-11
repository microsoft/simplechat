// chat-enhanced-citations.js
// Enhanced citation handling for different media types

import { showToast } from "./chat-toast.js";
import { showLoadingIndicator, hideLoadingIndicator } from "./chat-loading-indicator.js";
import { getDocumentMetadata } from './chat-documents.js';

/**
 * Determine file type from filename extension
 * @param {string} fileName - The file name
 * @returns {string} - File type: 'image', 'pdf', 'video', 'audio', or 'other'
 */
export function getFileType(fileName) {
    if (!fileName) return 'other';
    
    const ext = fileName.toLowerCase().split('.').pop();
    
    const imageExtensions = ['jpg', 'jpeg', 'png', 'bmp', 'tiff', 'tif', 'heif'];
    const videoExtensions = ['mp4', 'mov', 'avi', 'mkv', 'flv', 'webm', 'wmv'];
    const audioExtensions = ['mp3', 'wav', 'ogg', 'aac', 'flac', 'm4a'];
    
    if (imageExtensions.includes(ext)) return 'image';
    if (ext === 'pdf') return 'pdf';
    if (videoExtensions.includes(ext)) return 'video';
    if (audioExtensions.includes(ext)) return 'audio';
    
    return 'other';
}

/**
 * Show enhanced citation modal based on file type
 * @param {string} docId - Document ID
 * @param {string|number} pageNumberOrTimestamp - Page number for PDF or timestamp for video/audio
 * @param {string} citationId - Citation ID for fallback
 */
export function showEnhancedCitationModal(docId, pageNumberOrTimestamp, citationId) {
    // Get document metadata to determine file type
    const docMetadata = getDocumentMetadata(docId);
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
