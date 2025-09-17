// admin_plugins.js (updated to use new multi-step modal)
import { showToast } from "../chat/chat-toast.js"
import { renderPluginsTable as sharedRenderPluginsTable, validatePluginManifest as sharedValidatePluginManifest } from "../plugin_common.js";

// Main logic
document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('agents-tab')) return;

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
        const plugins = await res.json();
        
        sharedRenderPluginsTable({
            plugins,
            tbodySelector: '#admin-plugins-table-body',
            onEdit: name => editPlugin(name),
            onDelete: name => deletePlugin(name),
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
        const modal = window.pluginModalStepper.showModal(plugin);
        
        // Set up save handler
        setupSaveHandler(plugin, modal);
    } else {
        alert('Action modal not available. Please refresh the page.');
    }
}

function setupSaveHandler(plugin, modal) {
    const saveBtn = document.getElementById('save-plugin-btn');
    if (saveBtn) {
        // Remove any existing handlers
        saveBtn.onclick = null;
        
        saveBtn.onclick = async (event) => {
            event.preventDefault();
            
            try {
                // Get form data from the stepper
                const formData = window.pluginModalStepper.getFormData();
                
                // Validate with JSON schema
                const valid = await sharedValidatePluginManifest(formData);
                if (!valid) {
                    window.pluginModalStepper.showError('Validation error: Invalid action data.');
                    return;
                }
                
                // Save the action
                await savePlugin(formData, plugin);
                
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
        };
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
        const errorText = await saveRes.text();
        throw new Error(`Failed to save action: ${errorText}`);
    }
}

// Edit plugin modal logic
async function editPlugin(name) {
    try {
        const res = await fetch('/api/admin/plugins');
        if (!res.ok) throw new Error('Failed to load actions');
        const plugins = await res.json();
        const plugin = plugins.find(p => p.name === name);
        
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
