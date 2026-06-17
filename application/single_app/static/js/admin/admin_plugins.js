// admin_plugins.js (updated to use new multi-step modal)
import { showToast } from "../chat/chat-toast.js"
import { renderPluginsTable as sharedRenderPluginsTable, validatePluginManifest as sharedValidatePluginManifest, getErrorMessageFromResponse } from "../plugin_common.js";

let adminPlugins = [];

// Main logic
document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('actions-configuration')) return;

    // Load and render plugins table
    loadPlugins();

    // Add action button uses new multi-step modal
    document.getElementById('add-plugin-btn').addEventListener('click', function () {
        openPluginModal();
    });
});

async function loadPlugins() {
    try {
        const res = await fetch('/api/admin/plugins');
        if (!res.ok) throw new Error('Failed to load actions');
        adminPlugins = await res.json();
        
        sharedRenderPluginsTable({
            plugins: adminPlugins,
            tbodySelector: '#admin-plugins-table-body',
            onEdit: name => editPlugin(name),
            onDelete: name => deletePlugin(name),
            onToggleEnabled: name => togglePluginEnabled(name),
            onGovern: name => governPlugin(name, adminPlugins),
            onDuplicate: name => duplicatePlugin(name, adminPlugins),
            ensureTable: false,
            isAdmin: true
        });
    } catch (error) {
        console.error('Error loading actions:', error);
        showToast('Failed to load actions', 'danger');
    }
}

function openPluginModal(plugin = null) {
    // Use the new multi-step modal
    if (window.pluginModalStepper) {
        window.pluginModalStepper.setActionScope({
            scope: 'global',
            apiBase: '/api/admin/workspace-identities/global'
        });
        const modal = window.pluginModalStepper.showModal(plugin);
        
        // Set up save handler
        setupSaveHandler(plugin, modal);
    } else {
        alert('Action modal not available. Please refresh the page.');
    }
}

function makePluginCopyName(name, plugins = []) {
    const baseName = `${String(name || 'action').trim() || 'action'}_copy`;
    const existingNames = new Set((plugins || []).map((plugin) => String(plugin.name || '').trim().toLowerCase()));
    if (!existingNames.has(baseName.toLowerCase())) {
        return baseName;
    }

    let suffix = 2;
    while (existingNames.has(`${baseName}_${suffix}`.toLowerCase())) {
        suffix += 1;
    }
    return `${baseName}_${suffix}`;
}

function duplicatePlugin(name, plugins = []) {
    const plugin = (plugins || []).find(p => p.name === name);
    if (!plugin) {
        showToast(`Action "${name}" not found`, 'danger');
        return;
    }

    const duplicate = JSON.parse(JSON.stringify(plugin));
    delete duplicate.id;
    duplicate.name = makePluginCopyName(plugin.name, plugins);
    duplicate.display_name = `${plugin.display_name || plugin.name || 'Action'} Copy`;
    const modal = window.pluginModalStepper?.showModal(duplicate);
    if (window.pluginModalStepper) {
        window.pluginModalStepper.isEditMode = false;
        window.pluginModalStepper.originalPlugin = null;
        const title = document.getElementById('plugin-modal-title');
        if (title) {
            title.textContent = 'Add Action';
        }
    }
    setupSaveHandler(null, modal);
}

function governPlugin(name, plugins = []) {
    const plugin = (plugins || []).find(p => p.name === name);
    const pluginId = String(plugin?.id || '').trim();
    if (!pluginId) {
        showToast('This action does not have a stable ID for governance.', 'warning');
        return;
    }
    if (typeof window.openGovernanceDelegatedItemEditor === 'function') {
        window.openGovernanceDelegatedItemEditor({
            entityType: 'global_action',
            itemId: pluginId,
            resourceLabel: plugin.display_name || plugin.name || pluginId,
        });
    } else {
        showToast('Governance editor is still loading. Try again in a moment.', 'warning');
    }
}

function setupSaveHandler(plugin, modal) {
    const saveBtn = document.getElementById('save-plugin-btn');
    if (saveBtn) {
        const boundSaveBtn = saveBtn.cloneNode(true);
        saveBtn.replaceWith(boundSaveBtn);

        boundSaveBtn.addEventListener('click', async (event) => {
            event.preventDefault();
            const errorDiv = document.getElementById('plugin-modal-error');
            if (errorDiv) {
                errorDiv.classList.add('d-none');
                errorDiv.textContent = '';
            }
            try {
                // Get form data from the stepper
                const formData = window.pluginModalStepper.getFormData();
                
                // Validate with JSON schema
                const validation = await sharedValidatePluginManifest(formData);
                const validationFailed = validation === false || (validation && validation.valid === false);
                if (validationFailed) {
                    const message = validation?.errors?.join('\n') || 'Validation error: Invalid action data.';
                    window.pluginModalStepper.showError(message);
                    return;
                }
                
                const originalText = boundSaveBtn.textContent || 'Save';
                const spinner = document.createElement('span');
                spinner.className = 'spinner-border spinner-border-sm me-2';
                spinner.setAttribute('role', 'status');
                spinner.setAttribute('aria-hidden', 'true');
                boundSaveBtn.replaceChildren(spinner, document.createTextNode('Saving...'));
                boundSaveBtn.disabled = true;
                // Save the action
                try {
                    await savePlugin(formData, plugin);
                } catch (error) {
                    window.pluginModalStepper.showError(error.message);
                    return;
                } finally {
                    boundSaveBtn.textContent = originalText;
                    boundSaveBtn.disabled = false;
                }
                
                // Close modal and refresh
                if (modal && typeof modal.hide === 'function') {
                    modal.hide();
                } else {
                    bootstrap.Modal.getInstance(document.getElementById('plugin-modal')).hide();
                }
                
                loadPlugins();
                showToast(plugin ? 'Action updated successfully' : 'Action created successfully', 'success');
                
            } catch (error) {
                console.error('Error saving action:', error);
                window.pluginModalStepper.showError(error.message);
            }
        });
    }
}

async function savePlugin(pluginData, existingPlugin = null) {
    // For admin, we save individual plugins directly
    const endpoint = existingPlugin ? 
        `/api/admin/plugins/${encodeURIComponent(existingPlugin.name)}` : 
        '/api/admin/plugins';
    
    const method = existingPlugin ? 'PUT' : 'POST';
    
    const saveRes = await fetch(endpoint, {
        method: method,
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(pluginData)
    });
    
    if (!saveRes.ok) {
        const errorMessage = await getErrorMessageFromResponse(saveRes, 'Failed to save action');
        throw new Error(errorMessage);
    }
}

// Edit plugin modal logic
async function editPlugin(name) {
    try {
        const plugin = adminPlugins.find(p => p.name === name);
        
        if (plugin) {
            openPluginModal(plugin);
        } else {
            showToast(`Action "${name}" not found`, 'danger');
        }
    } catch (error) {
        console.error('Error loading action for edit:', error);
        showToast('Failed to load action for editing', 'danger');
    }
}

async function togglePluginEnabled(name) {
    const plugin = adminPlugins.find(item => item.name === name);
    if (!plugin) {
        showToast(`Action "${name}" not found`, 'danger');
        return;
    }

    const nextEnabledState = plugin.is_enabled === false;

    try {
        const res = await fetch(`/api/admin/plugins/${encodeURIComponent(name)}/enabled`, {
            method: 'PATCH',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ is_enabled: nextEnabledState })
        });

        if (!res.ok) {
            const errorMessage = await getErrorMessageFromResponse(res, 'Failed to update action state');
            throw new Error(errorMessage);
        }

        await loadPlugins();
        showToast(`Action "${name}" ${nextEnabledState ? 'enabled' : 'disabled'} successfully`, 'success');
    } catch (error) {
        console.error('Error updating action enabled state:', error);
        showToast('Error updating action state: ' + error.message, 'danger');
    }
}

async function deletePlugin(name) {
    if (!confirm(`Are you sure you want to delete action "${name}"?`)) return;
    
    try {
        const res = await fetch(`/api/admin/plugins/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        });
        
        if (!res.ok) {
            const errorText = await res.text();
            throw new Error(`Failed to delete action: ${errorText}`);
        }
        
        loadPlugins();
        showToast(`Action "${name}" deleted successfully`, 'success');
    } catch (error) {
        console.error('Error deleting action:', error);
        showToast('Error deleting action: ' + error.message, 'danger');
    }
}

function showPluginModalError(msg) {
    if (window.pluginModalStepper) {
        window.pluginModalStepper.showError(msg);
    } else {
        // Fallback to legacy error display
        const errDiv = document.getElementById('plugin-modal-error');
        if (errDiv) {
            errDiv.textContent = msg;
            errDiv.classList.remove('d-none');
        }
    }
}
