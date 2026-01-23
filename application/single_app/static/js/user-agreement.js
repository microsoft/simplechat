// user-agreement.js
// Shared module for User Agreement prompts before file uploads

/**
 * User Agreement Manager
 * Handles checking and prompting for user agreement acceptance before file uploads
 */
window.UserAgreementManager = (function() {
    'use strict';

    let modal = null;
    let pendingCallback = null;
    let pendingFiles = null;

    /**
     * Initialize the User Agreement Manager
     * Sets up event listeners for the modal
     */
    function init() {
        // Get modal element
        const modalEl = document.getElementById('userAgreementUploadModal');
        if (!modalEl) {
            console.warn('[UserAgreement] Modal element not found');
            return;
        }

        modal = new bootstrap.Modal(modalEl);

        // Accept button handler
        const acceptBtn = document.getElementById('userAgreementUploadAcceptBtn');
        if (acceptBtn) {
            acceptBtn.addEventListener('click', function() {
                onAccept();
            });
        }

        // Cancel button handler - clear pending state
        const cancelBtn = document.getElementById('userAgreementUploadCancelBtn');
        if (cancelBtn) {
            cancelBtn.addEventListener('click', function() {
                onCancel();
            });
        }

        // Modal close handler (X button or backdrop click)
        modalEl.addEventListener('hidden.bs.modal', function() {
            // If modal was closed without accepting, treat as cancel
            if (pendingCallback) {
                pendingCallback = null;
                pendingFiles = null;
            }
        });

        console.log('[UserAgreement] Manager initialized');
    }

    /**
     * Check if user agreement is required for a workspace type
     * @param {string} workspaceType - 'personal', 'group', 'public', or 'chat'
     * @param {string} workspaceId - The workspace ID (can be empty for personal/chat)
     * @returns {Promise<Object>} - { needsAgreement, agreementText, enableDailyAcceptance }
     */
    async function checkAgreement(workspaceType, workspaceId) {
        try {
            const params = new URLSearchParams({
                workspace_type: workspaceType,
                workspace_id: workspaceId || 'default',
                action_context: 'file_upload'
            });

            const response = await fetch(`/api/user_agreement/check?${params.toString()}`, {
                method: 'GET',
                headers: {
                    'Content-Type': 'application/json'
                }
            });

            if (!response.ok) {
                console.warn('[UserAgreement] Check failed:', response.status);
                return { needsAgreement: false };
            }

            return await response.json();
        } catch (error) {
            console.error('[UserAgreement] Error checking agreement:', error);
            return { needsAgreement: false };
        }
    }

    /**
     * Record that user accepted the agreement
     * @param {string} workspaceType - 'personal', 'group', 'public', or 'chat'
     * @param {string} workspaceId - The workspace ID
     * @returns {Promise<boolean>} - Success status
     */
    async function recordAcceptance(workspaceType, workspaceId) {
        try {
            const response = await fetch('/api/user_agreement/accept', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    workspace_type: workspaceType,
                    workspace_id: workspaceId || 'default',
                    action_context: 'file_upload'
                })
            });

            if (!response.ok) {
                console.warn('[UserAgreement] Accept failed:', response.status);
                return false;
            }

            const data = await response.json();
            return data.success === true;
        } catch (error) {
            console.error('[UserAgreement] Error recording acceptance:', error);
            return false;
        }
    }

    /**
     * Show the user agreement modal
     * @param {string} agreementText - The agreement text (markdown)
     * @param {boolean} enableDailyAcceptance - Whether daily acceptance is enabled
     */
    function showModal(agreementText, enableDailyAcceptance) {
        const contentDiv = document.getElementById('userAgreementUploadContent');
        const dailyCheckDiv = document.getElementById('userAgreementUploadDailyCheck');

        if (contentDiv) {
            // Render markdown if marked is available
            if (typeof marked !== 'undefined') {
                let html = marked.parse(agreementText);
                // Sanitize if DOMPurify is available
                if (typeof DOMPurify !== 'undefined') {
                    html = DOMPurify.sanitize(html);
                }
                contentDiv.innerHTML = html;
            } else {
                // Fallback: preserve line breaks
                contentDiv.textContent = agreementText;
            }
        }

        // Show/hide daily acceptance info
        if (dailyCheckDiv) {
            dailyCheckDiv.style.display = enableDailyAcceptance ? 'block' : 'none';
        }

        // Show modal
        if (modal) {
            modal.show();
        }
    }

    /**
     * Handle accept button click
     */
    async function onAccept() {
        if (!pendingCallback || !pendingFiles) {
            if (modal) modal.hide();
            return;
        }

        // Get workspace info from pending state
        const workspaceType = pendingFiles.workspaceType;
        const workspaceId = pendingFiles.workspaceId;

        // Record acceptance
        await recordAcceptance(workspaceType, workspaceId);

        // Hide modal
        if (modal) modal.hide();

        // Execute the pending callback with the files
        const callback = pendingCallback;
        const files = pendingFiles.files;
        
        // Clear pending state
        pendingCallback = null;
        pendingFiles = null;

        // Execute upload
        callback(files);
    }

    /**
     * Handle cancel button click
     */
    function onCancel() {
        pendingCallback = null;
        pendingFiles = null;
        if (modal) modal.hide();
    }

    /**
     * Check for user agreement and prompt if needed before file upload
     * @param {FileList|File[]} files - The files to upload
     * @param {string} workspaceType - 'personal', 'group', 'public', or 'chat'
     * @param {string} workspaceId - The workspace ID
     * @param {Function} uploadCallback - Function to call with files if agreement is accepted
     * @returns {Promise<boolean>} - True if upload should proceed immediately, false if modal is shown
     */
    async function checkBeforeUpload(files, workspaceType, workspaceId, uploadCallback) {
        if (!files || files.length === 0) {
            return false;
        }

        // Check if agreement is needed
        const result = await checkAgreement(workspaceType, workspaceId);

        if (!result.needsAgreement) {
            // No agreement needed, proceed with upload
            uploadCallback(files);
            return true;
        }

        // Agreement is needed - show modal
        pendingCallback = uploadCallback;
        pendingFiles = {
            files: files,
            workspaceType: workspaceType,
            workspaceId: workspaceId
        };

        showModal(result.agreementText, result.enableDailyAcceptance);
        return false;
    }

    // Public API
    return {
        init: init,
        checkBeforeUpload: checkBeforeUpload,
        checkAgreement: checkAgreement,
        recordAcceptance: recordAcceptance
    };
})();

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', function() {
    window.UserAgreementManager.init();
});
