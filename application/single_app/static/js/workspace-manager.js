// workspace-manager.js
// Public Workspace Management Functionality

import { showToast } from "./chat/chat-toast.js";

window.WorkspaceManager = {
    currentWorkspaceId: null,
    
    // Initialize workspace management functionality
    init: function() {
        this.bindEvents();
    },

    // Bind event handlers
    bindEvents: function() {
        // Modal controls
        document.getElementById('workspaceStatusSelect')?.addEventListener('change', this.handleStatusChange);
        document.getElementById('workspaceOwnershipSelect')?.addEventListener('change', this.handleOwnershipChange);
        document.getElementById('saveWorkspaceChangesBtn')?.addEventListener('click', this.saveWorkspaceChanges);
        document.getElementById('deleteWorkspaceDocumentsBtn')?.addEventListener('click', this.deleteWorkspaceDocuments);
        document.getElementById('deleteWorkspaceBtn')?.addEventListener('click', this.deleteWorkspace);
        document.getElementById('confirmDeleteWorkspaceDocumentsBtn')?.addEventListener('click', () => this.confirmDeleteWorkspaceDocuments());
        document.getElementById('confirmDeleteWorkspaceBtn')?.addEventListener('click', () => this.confirmDeleteWorkspace());
        
        // Member management modal
        document.getElementById('manageWorkspaceMembersBtn')?.addEventListener('click', this.loadWorkspaceMembers);
        document.getElementById('addSingleWorkspaceMemberBtn')?.addEventListener('click', () => {
            WorkspaceManager.openAddMemberModal();
        });
        
        // Add member modal handlers
        document.getElementById('wsSearchUsersBtn')?.addEventListener('click', this.searchUsersForAdd);
        document.getElementById('addWorkspaceMemberForm')?.addEventListener('submit', (e) => {
            e.preventDefault();
            WorkspaceManager.addMemberDirectly();
        });
        document.getElementById('addBulkWorkspaceMemberBtn')?.addEventListener('click', () => {
            // Open the CSV bulk upload modal
            const csvModal = new bootstrap.Modal(document.getElementById('workspaceCsvBulkUploadModal'));
            csvModal.show();
        });
        
        // CSV Upload handlers
        document.getElementById('workspaceCsvExampleBtn')?.addEventListener('click', this.downloadWorkspaceCsvExample);
        document.getElementById('workspaceCsvConfigBtn')?.addEventListener('click', () => {
            const modal = new bootstrap.Modal(document.getElementById('csvFormatInfoModal'));
            modal.show();
            
            // Fix backdrop z-index to appear above the bulk upload modal
            setTimeout(() => {
                const backdrops = document.querySelectorAll('.modal-backdrop');
                if (backdrops.length > 1) {
                    backdrops[backdrops.length - 1].style.zIndex = '1059';
                }
            }, 10);
        });
        document.getElementById('workspaceCsvFileInput')?.addEventListener('change', this.handleWorkspaceCsvFileSelect);
        document.getElementById('workspaceCsvNextBtn')?.addEventListener('click', this.startWorkspaceCsvUpload);
        document.getElementById('workspaceCsvDoneBtn')?.addEventListener('click', () => {
            bootstrap.Modal.getInstance(document.getElementById('workspaceCsvBulkUploadModal')).hide();
            WorkspaceManager.loadWorkspaceMembers();
        });
        document.getElementById('workspaceCsvBulkUploadModal')?.addEventListener('hidden.bs.modal', () => {
            WorkspaceManager.resetWorkspaceCsvModal();
        });
        
        // Activity timeline modal
        document.getElementById('viewWorkspaceActivityBtn')?.addEventListener('click', () => {
            const workspaceId = document.getElementById('publicWorkspaceManagementModal').getAttribute('data-workspace-id');
            if (workspaceId) {
                event.preventDefault();
                WorkspaceManager.viewActivity(workspaceId);
            }
        });
        
        // Reset workspace management modal when closed
        document.getElementById('publicWorkspaceManagementModal')?.addEventListener('hidden.bs.modal', () => {
            document.getElementById('workspaceOwnershipSelect').value = '';
            document.getElementById('workspaceOwnershipReason').value = '';
            document.getElementById('ownershipReasonWorkspace').style.display = 'none';
            document.getElementById('transferUserWorkspace').style.display = 'none';
        });
        
        // Clean up activity modal when closed
        document.getElementById('workspaceActivityModal')?.addEventListener('hidden.bs.modal', () => {
            // Clear the timeline
            const timeline = document.getElementById('activityWorkspaceTimeline');
            if (timeline) {
                timeline.innerHTML = '<div class="text-center py-4"><div class="spinner-border text-primary" role="status"><span class="visually-hidden">Loading...</span></div><div class="mt-2">Loading activity...</div></div>';
            }
            
            // Only remove backdrops if no other modals are open
            const openModals = document.querySelectorAll('.modal.show');
            if (openModals.length === 0) {
                document.querySelectorAll('.modal-backdrop').forEach(backdrop => {
                    backdrop.remove();
                });
                document.body.classList.remove('modal-open');
                document.body.style.overflow = '';
                document.body.style.paddingRight = '';
            }
        });
    },

    // CSV Bulk Upload Functions
    csvParsedData: [],

    downloadWorkspaceCsvExample: function() {
        const csvContent = `userId,displayName,email,role
00000000-0000-0000-0000-000000000001,John Smith,john.smith@contoso.com,user
00000000-0000-0000-0000-000000000002,Jane Doe,jane.doe@contoso.com,admin
00000000-0000-0000-0000-000000000003,Bob Johnson,bob.johnson@contoso.com,document_manager`;
        
        const blob = new Blob([csvContent], { type: 'text/csv' });
        const url = window.URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = 'workspace_bulk_members_example.csv';
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        window.URL.revokeObjectURL(url);
    },

    validateEmail: function(email) {
        return ValidationUtils.validateEmail(email);
    },

    validateGuid: function(guid) {
        return ValidationUtils.validateGuid(guid);
    },

    handleWorkspaceCsvFileSelect: function(event) {
        const file = event.target.files[0];
        if (!file) {
            document.getElementById('workspaceCsvNextBtn').disabled = true;
            document.getElementById('workspaceCsvValidationResults').style.display = 'none';
            document.getElementById('workspaceCsvErrorDetails').style.display = 'none';
            return;
        }

        const reader = new FileReader();
        reader.onload = (e) => {
            const text = e.target.result;
            const lines = text.split(/\r?\n/).filter(line => line.trim());

            document.getElementById('workspaceCsvErrorDetails').style.display = 'none';
            document.getElementById('workspaceCsvValidationResults').style.display = 'none';

            if (lines.length < 2) {
                WorkspaceManager.showWorkspaceCsvError('CSV must contain at least a header row and one data row');
                return;
            }

            const header = lines[0].toLowerCase().trim();
            if (header !== 'userid,displayname,email,role') {
                WorkspaceManager.showWorkspaceCsvError('Invalid header. Expected: userId,displayName,email,role');
                return;
            }

            const dataRows = lines.slice(1);
            if (dataRows.length > 1000) {
                WorkspaceManager.showWorkspaceCsvError(`Too many rows. Maximum 1,000 members allowed (found ${dataRows.length})`);
                return;
            }

            WorkspaceManager.csvParsedData = [];
            const errors = [];
            const validRoles = ['user', 'admin', 'document_manager'];
            
            for (let i = 0; i < dataRows.length; i++) {
                const rowNum = i + 2;
                const row = dataRows[i].split(',');
                
                if (row.length !== 4) {
                    errors.push(`Row ${rowNum}: Expected 4 columns, found ${row.length}`);
                    continue;
                }

                const userId = row[0].trim();
                const displayName = row[1].trim();
                const email = row[2].trim();
                const role = row[3].trim().toLowerCase();

                if (!userId || !displayName || !email || !role) {
                    errors.push(`Row ${rowNum}: All fields are required`);
                    continue;
                }

                if (!WorkspaceManager.validateGuid(userId)) {
                    errors.push(`Row ${rowNum}: Invalid GUID format for userId`);
                    continue;
                }

                if (!WorkspaceManager.validateEmail(email)) {
                    errors.push(`Row ${rowNum}: Invalid email format`);
                    continue;
                }

                if (!validRoles.includes(role)) {
                    errors.push(`Row ${rowNum}: Invalid role '${role}'. Must be: user, admin, or document_manager`);
                    continue;
                }

                WorkspaceManager.csvParsedData.push({ userId, displayName, email, role });
            }

            if (errors.length > 0) {
                WorkspaceManager.showWorkspaceCsvError(`Found ${errors.length} validation error(s):\n` + errors.slice(0, 10).join('\n') + 
                           (errors.length > 10 ? `\n... and ${errors.length - 10} more` : ''));
                return;
            }

            const sampleRows = WorkspaceManager.csvParsedData.slice(0, 3);
            const escapeHtml = (text) => {
                const div = document.createElement('div');
                div.textContent = text;
                return div.innerHTML;
            };
            
            document.getElementById('workspaceCsvValidationDetails').innerHTML = `
                <p><strong>✓ Valid CSV file detected</strong></p>
                <p>Total members to add: <strong>${WorkspaceManager.csvParsedData.length}</strong></p>
                <p>Sample data (first 3):</p>
                <ul class="mb-0">
                    ${sampleRows.map(row => `<li>${escapeHtml(row.displayName)} (${escapeHtml(row.email)})</li>`).join('')}
                </ul>
            `;
            document.getElementById('workspaceCsvValidationResults').style.display = 'block';
            document.getElementById('workspaceCsvNextBtn').disabled = false;
        };

        reader.readAsText(file);
    },

    showWorkspaceCsvError: function(message) {
        const escapeHtml = (text) => {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        };
        document.getElementById('workspaceCsvErrorList').innerHTML = `<pre class="mb-0">${escapeHtml(message)}</pre>`;
        document.getElementById('workspaceCsvErrorDetails').style.display = 'block';
        document.getElementById('workspaceCsvNextBtn').disabled = true;
        WorkspaceManager.csvParsedData = [];
    },

    startWorkspaceCsvUpload: async function() {
        if (!WorkspaceManager.csvParsedData || WorkspaceManager.csvParsedData.length === 0) {
            showToast('No valid data to upload', 'warning');
            return;
        }

        document.getElementById('workspaceCsvStage1').style.display = 'none';
        document.getElementById('workspaceCsvStage2').style.display = 'block';
        document.getElementById('workspaceCsvNextBtn').style.display = 'none';
        document.getElementById('workspaceCsvCancelBtn').style.display = 'none';
        document.getElementById('workspaceCsvModalClose').style.display = 'none';

        const workspaceId = WorkspaceManager.currentWorkspaceId;
        let successCount = 0;
        let failedCount = 0;
        let skippedCount = 0;
        const failures = [];

        for (let i = 0; i < WorkspaceManager.csvParsedData.length; i++) {
            const member = WorkspaceManager.csvParsedData[i];
            const progress = Math.round(((i + 1) / WorkspaceManager.csvParsedData.length) * 100);
            
            WorkspaceManager.updateWorkspaceCsvProgress(progress, `Processing ${i + 1} of ${WorkspaceManager.csvParsedData.length}: ${member.displayName}`);

            try {
                const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/add-member`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        userId: member.userId,
                        displayName: member.displayName,
                        email: member.email,
                        role: member.role,
                        source: 'csv'
                    })
                });

                const data = await response.json();
                
                if (response.ok) {
                    if (data.skipped) {
                        skippedCount++;
                    } else {
                        successCount++;
                    }
                } else {
                    failedCount++;
                    failures.push(`${member.displayName}: ${data.error || 'Unknown error'}`);
                }
            } catch (error) {
                failedCount++;
                failures.push(`${member.displayName}: ${error.message}`);
            }
        }

        WorkspaceManager.showWorkspaceCsvSummary(successCount, failedCount, skippedCount, failures);
    },

    updateWorkspaceCsvProgress: function(percentage, statusText) {
        document.getElementById('workspaceCsvProgressBar').style.width = percentage + '%';
        document.getElementById('workspaceCsvProgressBar').setAttribute('aria-valuenow', percentage);
        document.getElementById('workspaceCsvProgressText').textContent = percentage + '%';
        document.getElementById('workspaceCsvStatusText').textContent = statusText;
    },

    showWorkspaceCsvSummary: function(successCount, failedCount, skippedCount, failures) {
        document.getElementById('workspaceCsvStage2').style.display = 'none';
        document.getElementById('workspaceCsvStage3').style.display = 'block';
        document.getElementById('workspaceCsvDoneBtn').style.display = 'block';

        const escapeHtml = (text) => {
            const div = document.createElement('div');
            div.textContent = text;
            return div.innerHTML;
        };

        let summaryHtml = `
            <p><strong>Upload Summary:</strong></p>
            <ul>
                <li>✅ Successfully added: <strong>${successCount}</strong></li>
                <li>⏭️ Skipped (already members): <strong>${skippedCount}</strong></li>
                <li>❌ Failed: <strong>${failedCount}</strong></li>
            </ul>
        `;

        if (failures.length > 0) {
            summaryHtml += `
                <hr>
                <p><strong>Failed Members:</strong></p>
                <ul class="text-danger">
                    ${failures.slice(0, 10).map(f => `<li>${escapeHtml(f)}</li>`).join('')}
                    ${failures.length > 10 ? `<li><em>... and ${failures.length - 10} more</em></li>` : ''}
                </ul>
            `;
        }

        document.getElementById('workspaceCsvSummary').innerHTML = summaryHtml;
    },

    resetWorkspaceCsvModal: function() {
        document.getElementById('workspaceCsvStage1').style.display = 'block';
        document.getElementById('workspaceCsvStage2').style.display = 'none';
        document.getElementById('workspaceCsvStage3').style.display = 'none';
        document.getElementById('workspaceCsvNextBtn').style.display = 'block';
        document.getElementById('workspaceCsvNextBtn').disabled = true;
        document.getElementById('workspaceCsvCancelBtn').style.display = 'block';
        document.getElementById('workspaceCsvDoneBtn').style.display = 'none';
        document.getElementById('workspaceCsvModalClose').style.display = 'block';
        document.getElementById('workspaceCsvValidationResults').style.display = 'none';
        document.getElementById('workspaceCsvErrorDetails').style.display = 'none';
        document.getElementById('workspaceCsvFileInput').value = '';
        WorkspaceManager.csvParsedData = [];
        WorkspaceManager.updateWorkspaceCsvProgress(0, 'Ready');
    },

    // Manage individual workspace
    manageWorkspace: async function(workspaceId) {
        console.log('Managing workspace:', workspaceId);
        
        // Store the workspace ID for later use (CSV upload, etc.)
        WorkspaceManager.currentWorkspaceId = workspaceId;
        
        try {
            // Fetch workspace details from API
            const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}`);
            if (!response.ok) {
                throw new Error(`Failed to fetch workspace details: ${response.statusText}`);
            }
            
            const workspace = await response.json();
            
            // Populate modal with workspace data
            document.getElementById('modalWorkspaceName').textContent = workspace.name || 'Unknown Workspace';
            document.getElementById('modalWorkspaceOwner').textContent = `${workspace.owner_name || workspace.owner || 'Unknown'} (${workspace.owner_email || 'No email'})`;
            document.getElementById('modalWorkspaceMembers').textContent = `${workspace.member_count || 0} active members`;
            document.getElementById('modalWorkspaceDocuments').textContent = `${workspace.document_count || 0} documents`;
            
            // Format dates
            const formatDate = (dateStr) => {
                if (!dateStr) return 'Unknown';
                try {
                    return new Date(dateStr).toLocaleDateString();
                } catch (e) {
                    return 'Unknown';
                }
            };
            
            document.getElementById('modalWorkspaceCreated').textContent = formatDate(workspace.created_at);
            document.getElementById('modalWorkspaceId').textContent = workspaceId;
            
            // Set workspace status
            const statusSelect = document.getElementById('workspaceStatusSelect');
            statusSelect.value = workspace.status || 'active';
            
            // Update help text to match current status
            WorkspaceManager.handleStatusChange({ target: statusSelect });
            
            // Reset ownership select to default
            document.getElementById('workspaceOwnershipSelect').value = '';
            document.getElementById('transferUserWorkspace').style.display = 'none';
            document.getElementById('ownershipReasonWorkspace').style.display = 'none';
            document.getElementById('workspaceOwnershipReason').value = '';
            
            // Load workspace members for ownership transfer dropdown
            await WorkspaceManager.loadWorkspaceMembersForTransfer(workspaceId);
            
            // Store current workspace ID for saving changes
            document.getElementById('publicWorkspaceManagementModal').setAttribute('data-workspace-id', workspaceId);
            
            // Show the modal
            const modal = new bootstrap.Modal(document.getElementById('publicWorkspaceManagementModal'));
            modal.show();
            
        } catch (error) {
            console.error('Error loading workspace details:', error);
            showToast(`Error loading workspace details: ${error.message}`, 'danger');
        }
    },

    // Handle status change
    handleStatusChange: function(event) {
        const status = event.target.value;
        const helpText = document.getElementById('workspaceStatusHelpText');
        
        const statusDescriptions = {
            'active': '<strong>🟢 Active:</strong> Full functionality enabled. Members can upload documents, chat, and search documents. All workspace features work normally.',
            'locked': '<strong>🔒 Locked (Read-only):</strong> Workspace is locked. Members can only view and search existing documents. No new chats, document uploads, or deletions are allowed.',
            'upload_disabled': '<strong>⚠️ Upload Disabled:</strong> Document uploads are disabled. Members can still chat, search, and view existing documents, but cannot add new files.',
            'inactive': '<strong>🔴 Inactive:</strong> Workspace is completely disabled. Members cannot access, chat, upload, or search documents. The workspace is effectively suspended.'
        };
        
        helpText.innerHTML = statusDescriptions[status] || '';
    },

    // Handle ownership change
    handleOwnershipChange: function(event) {
        const transferUserWorkspace = document.getElementById('transferUserWorkspace');
        const ownershipReasonWorkspace = document.getElementById('ownershipReasonWorkspace');
        
        if (event.target.value === 'transfer') {
            transferUserWorkspace.style.display = 'block';
            ownershipReasonWorkspace.style.display = 'block';
        } else if (event.target.value === 'admin') {
            transferUserWorkspace.style.display = 'none';
            ownershipReasonWorkspace.style.display = 'block';
        } else {
            transferUserWorkspace.style.display = 'none';
            ownershipReasonWorkspace.style.display = 'none';
        }
    },
    
    // Load workspace members for ownership transfer dropdown
    loadWorkspaceMembersForTransfer: async function(workspaceId) {
        const memberSelect = document.getElementById('workspaceNewOwnerSelect');
        
        try {
            const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/members`);
            if (!response.ok) {
                throw new Error('Failed to load workspace members');
            }
            
            const data = await response.json();
            const members = data.members || [];
            
            // Clear existing options (except the first placeholder)
            memberSelect.innerHTML = '<option value="">Select a workspace member...</option>';
            
            // Add member options (admins and document managers only)
            members.filter(m => m.role === 'admin' || m.role === 'documentManager').forEach(member => {
                const option = document.createElement('option');
                option.value = member.userId;
                option.textContent = `${member.displayName} (${member.email})`;
                memberSelect.appendChild(option);
            });
            
        } catch (error) {
            console.error('Error loading members for transfer:', error);
        }
    },

    // Save workspace changes
    saveWorkspaceChanges: async function() {
        const workspaceId = document.getElementById('publicWorkspaceManagementModal').getAttribute('data-workspace-id');
        const status = document.getElementById('workspaceStatusSelect').value;
        const ownershipAction = document.getElementById('workspaceOwnershipSelect').value;
        const saveButton = document.getElementById('saveWorkspaceChangesBtn');
        
        try {
            saveButton.disabled = true;
            saveButton.innerHTML = '<i class="bi bi-clock me-1"></i>Saving...';
            
            // Save status change
            const statusResponse = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/status`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ status })
            });
            
            if (!statusResponse.ok) {
                throw new Error('Failed to update workspace status');
            }
            
            // Handle ownership transfer if selected
            if (ownershipAction && ownershipAction !== '') {
                const reason = document.getElementById('workspaceOwnershipReason').value;
                if (!reason || reason.trim() === '') {
                    showToast('Please provide a reason for the ownership change', 'warning');
                    saveButton.disabled = false;
                    saveButton.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Changes';
                    return;
                }
                
                let ownershipResponse;
                
                if (ownershipAction === 'transfer') {
                    // Transfer to another member
                    const newOwnerId = document.getElementById('workspaceNewOwnerSelect').value;
                    if (!newOwnerId) {
                        showToast('Please select a new owner', 'warning');
                        saveButton.disabled = false;
                        saveButton.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Changes';
                        return;
                    }
                    
                    ownershipResponse = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/ownership`, {
                        method: 'PUT',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ newOwnerId: newOwnerId, reason: reason })
                    });
                } else if (ownershipAction === 'admin') {
                    // Admin take ownership
                    ownershipResponse = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/take-ownership`, {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ reason: reason })
                    });
                }
                
                if (ownershipResponse && !ownershipResponse.ok) {
                    const error = await ownershipResponse.json().catch(() => ({ error: 'Failed to process ownership change' }));
                    showToast(`Ownership change request failed: ${error.message || error.error}`, 'danger');
                } else if (ownershipResponse) {
                    const result = await ownershipResponse.json();
                    if (result.requires_approval || result.status === 'pending') {
                        showToast(`Ownership change approval request created successfully. Approval ID: ${result.approval_id}. The request is pending approval from the workspace owner or another admin.`, 'success');
                    } else {
                        showToast('Ownership change completed successfully!', 'success');
                    }
                }
            }
            
            showToast('Workspace updated successfully!', 'success');
            
            // Close modal and refresh table
            bootstrap.Modal.getInstance(document.getElementById('publicWorkspaceManagementModal')).hide();
            if (window.controlCenter) {
                window.controlCenter.loadPublicWorkspaces();
            }
            
        } catch (error) {
            console.error('Error saving workspace changes:', error);
            showToast(`Error saving changes: ${error.message}`, 'danger');
        } finally {
            saveButton.disabled = false;
            saveButton.innerHTML = '<i class="bi bi-check-lg me-1"></i>Save Changes';
        }
    },

    // Delete workspace documents
    deleteWorkspaceDocuments: function() {
        // Clear previous reason and show modal
        document.getElementById('deleteWorkspaceDocumentsReason').value = '';
        const modal = new bootstrap.Modal(document.getElementById('deleteWorkspaceDocumentsModal'));
        modal.show();
    },

    // Delete entire workspace
    deleteWorkspace: function() {
        const modal = new bootstrap.Modal(document.getElementById('deleteWorkspaceModal'));
        modal.show();
    },

    // Confirm delete workspace documents
    confirmDeleteWorkspaceDocuments: async function() {
        const workspaceId = document.getElementById('publicWorkspaceManagementModal').getAttribute('data-workspace-id');
        const reason = document.getElementById('deleteWorkspaceDocumentsReason').value.trim();
        const confirmBtn = document.getElementById('confirmDeleteWorkspaceDocumentsBtn');
        
        if (!reason) {
            showToast('Please provide a reason for this action.', 'warning');
            document.getElementById('deleteWorkspaceDocumentsReason').focus();
            return;
        }
        
        try {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span>Submitting...';
            
            const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/documents`, {
                method: 'DELETE',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({
                    reason: reason
                })
            });
            
            if (!response.ok) {
                const errorData = await response.json();
                throw new Error(errorData.error || 'Failed to create document deletion request');
            }
            
            const result = await response.json();
            console.log('Document deletion request created:', result);
            
            // Close delete modal
            bootstrap.Modal.getInstance(document.getElementById('deleteWorkspaceDocumentsModal')).hide();
            
            // Show success message
            showToast(
                `Document deletion request submitted! Status: Pending Approval (ID: ${result.approval_id}). The request requires approval from the workspace owner or another admin.`,
                'success'
            );
            
        } catch (error) {
            console.error('Error creating document deletion request:', error);
            showToast(`Error: ${error.message}`, 'danger');
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = '<i class="bi bi-trash me-1"></i>Submit Request';
        }
    },

    // Confirm delete entire workspace
    confirmDeleteWorkspace: async function() {
        const workspaceId = document.getElementById('publicWorkspaceManagementModal').getAttribute('data-workspace-id');
        const confirmBtn = document.getElementById('confirmDeleteWorkspaceBtn');
        
        try {
            confirmBtn.disabled = true;
            confirmBtn.innerHTML = '<i class="bi bi-clock me-1"></i>Deleting...';
            
            const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}`, {
                method: 'DELETE'
            });
            
            if (!response.ok) {
                throw new Error('Failed to delete workspace');
            }
            
            showToast('Workspace deleted successfully!', 'success');
            
            // Close all modals
            bootstrap.Modal.getInstance(document.getElementById('deleteWorkspaceModal')).hide();
            bootstrap.Modal.getInstance(document.getElementById('publicWorkspaceManagementModal')).hide();
            
            // Refresh table
            if (window.controlCenter) {
                window.controlCenter.loadPublicWorkspaces();
            }
            
        } catch (error) {
            console.error('Error deleting workspace:', error);
            showToast(`Error deleting workspace: ${error.message}`, 'danger');
        } finally {
            confirmBtn.disabled = false;
            confirmBtn.innerHTML = '<i class="bi bi-trash me-1"></i>Delete Workspace';
        }
    },

    // Load workspace members
    loadWorkspaceMembers: async function() {
        console.log('[Workspace Members] loadWorkspaceMembers called');
        const workspaceId = document.getElementById('publicWorkspaceManagementModal').getAttribute('data-workspace-id');
        console.log('[Workspace Members] Workspace ID:', workspaceId);
        const tbody = document.getElementById('workspaceMembersTableBody');
        console.log('[Workspace Members] Table body element:', tbody);
        
        try {
            console.log('[Workspace Members] Fetching members from API...');
            const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/members`);
            console.log('[Workspace Members] API response status:', response.status);
            if (!response.ok) {
                throw new Error('Failed to load workspace members');
            }
            
            const data = await response.json();
            console.log('[Workspace Members] API data received:', data);
            const members = data.members || [];
            console.log('[Workspace Members] Members array:', members, 'Count:', members.length);
            
            // Populate table
            tbody.innerHTML = '';
            members.forEach(member => {
                const row = document.createElement('tr');
                
                // Format role with badge styling matching groups
                const roleConfig = {
                    'owner': { class: 'bg-danger', text: 'Owner' },
                    'admin': { class: 'bg-warning text-dark', text: 'Admin' },
                    'documentManager': { class: 'bg-info text-dark', text: 'Document Manager' },
                    'user': { class: 'bg-secondary', text: 'Member' }
                };
                const roleInfo = roleConfig[member.role] || roleConfig['user'];
                
                // Show email in the name cell (like groups)
                const displayName = member.displayName || 'Unknown';
                const email = member.email || 'No email';
                
                row.innerHTML = `
                    <td>
                        <div>${displayName}</div>
                        <div class="text-muted small">${email}</div>
                    </td>
                    <td><span class="badge ${roleInfo.class}">${roleInfo.text}</span></td>
                `;
                tbody.appendChild(row);
            });
            
            // Update workspace name in modal
            const workspaceName = document.getElementById('modalWorkspaceName').textContent;
            document.getElementById('membersWorkspaceName').textContent = `${workspaceName} - Members`;
            
            // Modal is automatically shown by Bootstrap via data-bs-toggle
            
        } catch (error) {
            console.error('Error loading workspace members:', error);
            showToast(`Error loading members: ${error.message}`, 'danger');
        }
    },

    // View workspace activity
    viewActivity: async function(workspaceId) {
        console.log('[Activity] viewActivity called with workspaceId:', workspaceId);
        
        try {
            // Set the current workspace ID for loading activity
            WorkspaceManager.currentWorkspaceId = workspaceId;
            
            // Fetch workspace details to get the name
            const workspaceResponse = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}`);
            if (!workspaceResponse.ok) {
                throw new Error('Failed to fetch workspace details');
            }
            const workspace = await workspaceResponse.json();
            
            // Set the workspace name in the modal
            const workspaceNameElement = document.getElementById('activityWorkspaceName');
            if (workspaceNameElement) {
                workspaceNameElement.textContent = `${workspace.name || 'Unknown Workspace'} - Activity Timeline`;
            }
            
            // Show the modal
            const modalElement = document.getElementById('workspaceActivityModal');
            if (!modalElement) {
                throw new Error('Activity modal element not found');
            }
            
            const modal = new bootstrap.Modal(modalElement);
            modal.show();
            
            // Load initial activity (default: 30 days)
            await WorkspaceManager.loadWorkspaceActivity(workspaceId, 30);
            
            // Set up time range change listener
            const timeRangeSelect = document.getElementById('activityWorkspaceTimeRange');
            if (timeRangeSelect) {
                timeRangeSelect.onchange = async function(e) {
                    await WorkspaceManager.loadWorkspaceActivity(workspaceId, e.target.value);
                };
            }
            
            // Set up export button
            const exportBtn = document.getElementById('exportWorkspaceActivityBtn');
            if (exportBtn) {
                exportBtn.onclick = function() {
                    WorkspaceManager.exportWorkspaceActivity(workspaceId);
                };
            }
            
        } catch (error) {
            console.error('[Activity] Error in viewActivity:', error);
            showToast(`Error loading workspace activity: ${error.message}`, 'danger');
        }
    },

    // Load workspace activity
    loadWorkspaceActivity: async function(workspaceId, days) {
        console.log(`[Activity] Loading activity for workspace ${workspaceId}, days: ${days}`);
        const timeline = document.getElementById('activityWorkspaceTimeline');
        
        if (!timeline) {
            console.error('[Activity] Timeline element not found!');
            return;
        }
        
        // Show loading state
        timeline.innerHTML = `
            <div class="text-center py-4">
                <div class="spinner-border text-primary" role="status">
                    <span class="visually-hidden">Loading...</span>
                </div>
                <div class="mt-2">Loading activity...</div>
            </div>
        `;
        
        try {
            console.log(`[Activity] Fetching from API: /api/admin/control-center/public-workspaces/${workspaceId}/activity?days=${days}`);
            const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/activity?days=${days}`);
            
            console.log(`[Activity] API response status: ${response.status}`);
            
            if (!response.ok) {
                const errorText = await response.text();
                console.error('[Activity] API error:', errorText);
                throw new Error(`Failed to fetch workspace activity: ${response.status}`);
            }
            
            const data = await response.json();
            console.log(`[Activity] Received ${data.activities?.length || 0} activities`);
            const activities = data.activities || [];
            const rawActivities = data.raw_activities || activities;  // Use raw activities for modal
            
            // Store RAW activities for modal access (not the formatted ones)
            WorkspaceManager.currentActivities = rawActivities;
            
            if (activities.length === 0) {
                console.log('[Activity] No activities found');
                timeline.innerHTML = `
                    <div class="text-center py-5 text-muted">
                        <i class="bi bi-inbox" style="font-size: 3rem;"></i>
                        <p class="mt-3">No activity found for the selected time range</p>
                    </div>
                `;
                return;
            }
            
            // Render timeline using same logic as groups
            console.log('[Activity] Rendering activities...');
            timeline.innerHTML = activities.map((activity, index) => WorkspaceManager.renderActivityItem(activity, index)).join('');
            console.log('[Activity] Activities rendered successfully');
            
        } catch (error) {
            console.error('[Activity] Error loading workspace activity:', error);
            timeline.innerHTML = `
                <div class="alert alert-danger">
                    <i class="bi bi-exclamation-triangle me-2"></i>
                    Error loading activity: ${WorkspaceManager.escapeHtml(error.message)}
                </div>
            `;
        }
    },
    
    // Render a single activity item (same as GroupManager)
    renderActivityItem: function(activity, index) {
        const timestamp = new Date(activity.timestamp);
        const relativeTime = WorkspaceManager.getRelativeTime(timestamp);
        const formattedTime = timestamp.toLocaleString();
        
        // Build activity-specific content
        let content = '';
        let title = '';
        
        switch (activity.type) {
            case 'document_creation':
                title = 'Document Uploaded';
                const doc = activity.document || {};
                const sizeStr = WorkspaceManager.formatFileSize(doc.file_size_bytes);
                content = `
                    <div><strong>${WorkspaceManager.escapeHtml(doc.file_name || 'Unknown')}</strong></div>
                    <div class="text-muted small">
                        ${doc.file_type || 'Unknown type'} • ${sizeStr}
                        ${doc.page_count ? ` • ${doc.page_count} pages` : ''}
                    </div>
                `;
                break;
                
            case 'document_deletion':
                title = 'Document Deleted';
                const delDoc = activity.document || {};
                content = `
                    <div><strong>${WorkspaceManager.escapeHtml(delDoc.file_name || 'Unknown')}</strong></div>
                    <div class="text-muted small">${delDoc.file_type || 'Unknown type'}</div>
                `;
                break;
                
            case 'document_metadata_update':
                title = 'Document Updated';
                const updDoc = activity.document || {};
                content = `
                    <div><strong>${WorkspaceManager.escapeHtml(updDoc.file_name || 'Unknown')}</strong></div>
                    <div class="text-muted small">Metadata updated</div>
                `;
                break;
                
            case 'public_workspace_status_change':
                title = 'Status Changed';
                const statusChange = activity.status_change || {};
                content = `
                    <div class="d-flex align-items-center gap-2">
                        <span class="badge bg-secondary">${WorkspaceManager.formatStatus(statusChange.from_status)}</span>
                        <i class="bi bi-arrow-right"></i>
                        <span class="badge bg-${WorkspaceManager.getStatusColor(statusChange.to_status)}">${WorkspaceManager.formatStatus(statusChange.to_status)}</span>
                    </div>
                `;
                break;
                
            case 'token_usage':
                const tokenUsage = activity.token_usage || {};
                const tokenType = tokenUsage.token_type || 'unknown';
                title = tokenType === 'chat' ? 'Tokens Used - Chat' : tokenType === 'embedding' ? 'Tokens Used - Embedding' : 'Tokens Used';
                
                let tokenDetails = `
                    <div class="mb-2">
                        <span class="badge bg-info">${WorkspaceManager.escapeHtml(tokenUsage.model || 'Unknown Model')}</span>
                        <span class="badge bg-secondary ms-1">${tokenType.charAt(0).toUpperCase() + tokenType.slice(1)}</span>
                    </div>
                    <div class="row g-2 small">
                        <div class="col-auto">
                            <strong>Total:</strong> <span class="text-primary">${(tokenUsage.total_tokens || 0).toLocaleString()}</span> tokens
                        </div>
                `;
                
                if (tokenType === 'chat' && (tokenUsage.prompt_tokens || tokenUsage.completion_tokens)) {
                    tokenDetails += `
                        <div class="col-auto">
                            <strong>Prompt:</strong> ${(tokenUsage.prompt_tokens || 0).toLocaleString()}
                        </div>
                        <div class="col-auto">
                            <strong>Completion:</strong> ${(tokenUsage.completion_tokens || 0).toLocaleString()}
                        </div>
                    `;
                }
                
                tokenDetails += `</div>`;
                
                // Add context-specific details
                if (tokenUsage.file_name) {
                    tokenDetails += `<div class="text-muted small mt-1"><i class="bi bi-file-earmark me-1"></i>${WorkspaceManager.escapeHtml(tokenUsage.file_name)}</div>`;
                }
                
                content = tokenDetails;
                break;
                
            default:
                title = activity.type || 'Activity';
                content = `<div class="text-muted small">${WorkspaceManager.escapeHtml(activity.description || 'No details available')}</div>`;
        }
        
        return `
            <div class="activity-item mb-3 p-3 border rounded" style="cursor: pointer;" onclick="WorkspaceManager.showRawActivityModal(${index})" title="Click to view raw activity data">
                <div class="d-flex align-items-start gap-3">
                    <div class="activity-icon">
                        <i class="bi bi-${activity.icon || 'circle'} text-${activity.color || 'secondary'}" style="font-size: 1.5rem;"></i>
                    </div>
                    <div class="flex-grow-1">
                        <div class="d-flex justify-content-between align-items-start mb-1">
                            <h6 class="mb-0">${title}</h6>
                            <small class="text-muted" title="${formattedTime}">${relativeTime}</small>
                        </div>
                        ${content}
                    </div>
                </div>
            </div>
        `;
    },
    
    // Helper: Format file size
    formatFileSize: function(bytes) {
        if (!bytes || bytes === 0) return '0 B';
        const units = ['B', 'KB', 'MB', 'GB'];
        let size = bytes;
        let unitIndex = 0;
        while (size >= 1024 && unitIndex < units.length - 1) {
            size /= 1024;
            unitIndex++;
        }
        return `${size.toFixed(1)} ${units[unitIndex]}`;
    },
    
    // Helper: Get relative time string
    getRelativeTime: function(date) {
        const now = new Date();
        const diffMs = now - date;
        const diffSecs = Math.floor(diffMs / 1000);
        const diffMins = Math.floor(diffSecs / 60);
        const diffHours = Math.floor(diffMins / 60);
        const diffDays = Math.floor(diffHours / 24);
        
        if (diffSecs < 60) return 'Just now';
        if (diffMins < 60) return `${diffMins}m ago`;
        if (diffHours < 24) return `${diffHours}h ago`;
        if (diffDays < 7) return `${diffDays}d ago`;
        if (diffDays < 30) return `${Math.floor(diffDays / 7)}w ago`;
        if (diffDays < 365) return `${Math.floor(diffDays / 30)}mo ago`;
        return `${Math.floor(diffDays / 365)}y ago`;
    },
    
    // Helper: Format status name
    formatStatus: function(status) {
        if (!status) return 'Unknown';
        return status.replace(/_/g, ' ').split(' ').map(w => w.charAt(0).toUpperCase() + w.slice(1)).join(' ');
    },
    
    // Helper: Get Bootstrap color for status
    getStatusColor: function(status) {
        const colorMap = {
            'active': 'success',
            'locked': 'danger',
            'upload_disabled': 'warning',
            'inactive': 'secondary'
        };
        return colorMap[status] || 'secondary';
    },

    // Show raw activity modal (matching group modal functionality)
    showRawActivityModal: function(activityIndex) {
        if (!WorkspaceManager.currentActivities || activityIndex >= WorkspaceManager.currentActivities.length) {
            showToast('Activity data not available', 'warning');
            return;
        }

        const activity = WorkspaceManager.currentActivities[activityIndex];
        const modalBody = document.getElementById('rawWorkspaceActivityModalBody');
        const modalTitle = document.getElementById('rawWorkspaceActivityModalTitle');
        
        if (!modalBody || !modalTitle) {
            showToast('Modal elements not found', 'danger');
            return;
        }

        // Set title
        const activityType = activity.type || 'Activity';
        const timestamp = new Date(activity.timestamp).toLocaleString();
        modalTitle.textContent = `${activityType} - ${timestamp}`;

        // Display JSON with pretty formatting
        modalBody.innerHTML = `<pre class="mb-0" style="max-height: 500px; overflow-y: auto;">${WorkspaceManager.escapeHtml(JSON.stringify(activity, null, 2))}</pre>`;

        // Show modal
        const modal = new bootstrap.Modal(document.getElementById('rawWorkspaceActivityModal'));
        modal.show();
    },
    
    // Copy raw activity to clipboard
    copyRawWorkspaceActivityToClipboard: function() {
        const rawText = document.getElementById('rawWorkspaceActivityModalBody')?.textContent;
        if (!rawText) {
            showToast('No activity data to copy', 'warning');
            return;
        }

        navigator.clipboard.writeText(rawText).then(() => {
            // Show success message
            showToast('Activity data copied to clipboard', 'success');
        }).catch(err => {
            console.error('Failed to copy:', err);
            showToast('Failed to copy to clipboard', 'danger');
        });
    },

    // Export workspace activity
    exportWorkspaceActivity: async function(workspaceId) {
        try {
            const days = document.getElementById('activityWorkspaceTimeRange').value;
            const response = await fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/activity?days=${days}&export=true`);
            
            if (!response.ok) {
                throw new Error('Failed to export activity');
            }
            
            const blob = await response.blob();
            const url = window.URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `workspace_${workspaceId}_activity_${new Date().toISOString().split('T')[0]}.csv`;
            document.body.appendChild(a);
            a.click();
            window.URL.revokeObjectURL(url);
            document.body.removeChild(a);
            
        } catch (error) {
            console.error('Error exporting activity:', error);
            alert(`Error exporting activity: ${error.message}`);
        }
    },

    // Add Member Modal Functions
    openAddMemberModal: function() {
        // Clear form fields
        document.getElementById('wsUserSearchTerm').value = '';
        document.getElementById('wsNewUserId').value = '';
        document.getElementById('wsNewUserDisplayName').value = '';
        document.getElementById('wsNewUserEmail').value = '';
        document.getElementById('wsNewUserRole').value = 'document_manager';
        document.getElementById('wsSearchResultsContainer').style.display = 'none';
        
        // Open modal
        const modal = new bootstrap.Modal(document.getElementById('addWorkspaceMemberModal'));
        modal.show();
    },

    searchUsersForAdd: function() {
        const searchTerm = document.getElementById('wsUserSearchTerm').value.trim();
        if (!searchTerm || searchTerm.length < 2) {
            alert('Please enter at least 2 characters to search');
            return;
        }
        
        const searchBtn = document.getElementById('wsSearchUsersBtn');
        searchBtn.disabled = true;
        searchBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Searching...';
        
        fetch(`/api/userSearch?query=${encodeURIComponent(searchTerm)}`)
            .then(response => {
                if (response.status === 401) {
                    window.location.href = '/login';
                    return;
                }
                return response.json();
            })
            .then(users => {
                if (!users) return;
                
                if (users && users.length > 0) {
                    WorkspaceManager.renderUserSearchResults(users);
                } else {
                    document.getElementById('wsSearchResultsContainer').style.display = 'block';
                    document.getElementById('wsSearchResults').innerHTML = `
                        <tr>
                            <td colspan="4" class="text-center text-muted">
                                <i class="bi bi-search me-1"></i> No users found matching "${searchTerm}"
                            </td>
                        </tr>
                    `;
                }
            })
            .catch(error => {
                console.error('Error searching users:', error);
                alert('Failed to search users');
            })
            .finally(() => {
                searchBtn.disabled = false;
                searchBtn.innerHTML = 'Search';
            });
    },

    renderUserSearchResults: function(users) {
        let html = '';
        if (!users || users.length === 0) {
            html = `
                <tr>
                    <td colspan="4" class="text-center text-muted">
                        <i class="bi bi-search me-1"></i> No results found
                    </td>
                </tr>
            `;
        } else {
            users.forEach(user => {
                const userId = WorkspaceManager.escapeJsString(user.id || '');
                const displayName = WorkspaceManager.escapeJsString(user.displayName || '');
                const email = WorkspaceManager.escapeJsString(user.email || '');
                
                html += `
                    <tr>
                        <td>${WorkspaceManager.escapeHtml(user.displayName || '(no name)')}</td>
                        <td>${WorkspaceManager.escapeHtml(user.email || '')}</td>
                        <td><small class="font-monospace">${WorkspaceManager.escapeHtml(user.id || '')}</small></td>
                        <td class="text-end">
                            <button type="button" class="btn btn-sm btn-primary" 
                                    onclick="WorkspaceManager.selectUserForAdd('${userId}', '${displayName}', '${email}')">
                                <i class="bi bi-check-circle me-1"></i>Select
                            </button>
                        </td>
                    </tr>
                `;
            });
        }
        
        document.getElementById('wsSearchResults').innerHTML = html;
        document.getElementById('wsSearchResultsContainer').style.display = 'block';
    },

    escapeJsString: function(str) {
        if (!str) return '';
        return str.replace(/\\/g, '\\\\').replace(/'/g, "\\'").replace(/"/g, '\\"').replace(/\n/g, '\\n').replace(/\r/g, '\\r');
    },

    escapeHtml: function(str) {
        if (!str) return '';
        const div = document.createElement('div');
        div.textContent = str;
        return div.innerHTML;
    },

    selectUserForAdd: function(userId, displayName, email) {
        document.getElementById('wsNewUserId').value = userId;
        document.getElementById('wsNewUserDisplayName').value = displayName;
        document.getElementById('wsNewUserEmail').value = email;
        
        // Hide search results after selection
        document.getElementById('wsSearchResultsContainer').style.display = 'none';
        document.getElementById('wsUserSearchTerm').value = '';
        
        alert('User selected. Choose a role and click Add Member.');
    },

    addMemberDirectly: function() {
        const userId = document.getElementById('wsNewUserId').value.trim();
        const displayName = document.getElementById('wsNewUserDisplayName').value.trim();
        const email = document.getElementById('wsNewUserEmail').value.trim();
        const role = document.getElementById('wsNewUserRole').value;
        
        // Validate required fields
        if (!userId) {
            alert('User ID is required');
            return;
        }
        if (!displayName) {
            alert('Display Name is required');
            return;
        }
        if (!email) {
            alert('Email is required');
            return;
        }
        if (!role) {
            alert('Role is required');
            return;
        }
        
        // Validate GUID format for user ID
        const guidRegex = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
        if (!guidRegex.test(userId)) {
            alert('User ID must be a valid GUID format');
            return;
        }
        
        // Validate email format
        const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
        if (!emailRegex.test(email)) {
            alert('Invalid email format');
            return;
        }
        
        const submitBtn = document.querySelector('#addWorkspaceMemberForm button[type="submit"]');
        submitBtn.disabled = true;
        submitBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Adding...';
        
        const workspaceId = WorkspaceManager.currentWorkspaceId;
        
        fetch(`/api/admin/control-center/public-workspaces/${workspaceId}/add-member-single`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                userId: userId,
                displayName: displayName,
                email: email,
                role: role
            })
        })
        .then(response => {
            if (!response.ok) {
                throw new Error('Failed to add member');
            }
            return response.json();
        })
        .then(data => {
            if (data.error) {
                alert(data.error);
            } else {
                alert(`Successfully added ${displayName} as ${role}`);
                
                // Close modal
                const modalElement = document.getElementById('addWorkspaceMemberModal');
                const modal = bootstrap.Modal.getInstance(modalElement) || new bootstrap.Modal(modalElement);
                modal.hide();
                
                // Refresh member list
                WorkspaceManager.loadWorkspaceMembers();
            }
        })
        .catch(error => {
            console.error('Error adding member:', error);
            alert('Failed to add member');
        })
        .finally(() => {
            submitBtn.disabled = false;
            submitBtn.innerHTML = 'Add Member';
        });
    }
};

// Initialize on page load
document.addEventListener('DOMContentLoaded', function() {
    WorkspaceManager.init();
});
