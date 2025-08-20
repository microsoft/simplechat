// admin_plugins.js
import { showToast } from "../chat/chat-toast.js"
import { renderPluginsTable as sharedRenderPluginsTable, validatePluginManifest as sharedValidatePluginManifest } from "../plugin_common.js";
import PluginWizard from "../plugin_wizard.js";

// Global wizard instance
let pluginWizard;

// Main logic
document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('plugins-tab')) return;

    // Initialize the plugin wizard
    pluginWizard = new PluginWizard();

    // Add plugin button uses new wizard
    document.getElementById('add-plugin-btn').addEventListener('click', async function () {
        await pluginWizard.show();
    });

    // Save plugin (add or edit) - now handled by wizard
    document.getElementById('save-plugin-btn').addEventListener('click', async function (event) {
        event.preventDefault();
        
        console.log('🔧 Starting plugin save process...');
        
        // Validate final step
        if (!pluginWizard.validateCurrentStep()) {
            console.error('❌ Final step validation failed');
            return;
        }

        // Collect form data from wizard
        const pluginData = pluginWizard.collectFormData();
        console.log('📋 Collected form data:', JSON.stringify(pluginData, null, 2));
        
        // Validate required fields
        if (!pluginData.name || !pluginData.type) {
            const error = 'Name and type are required.';
            console.error('❌ Missing required fields:', { name: pluginData.name, type: pluginData.type });
            showPluginModalError(error);
            return;
        }

        // Check for spaces in name (maintain backward compatibility)
        if (/\s/.test(pluginData.name)) {
            const error = 'Internal name cannot contain spaces.';
            console.error('❌ Invalid name format:', pluginData.name);
            showPluginModalError(error);
            return;
        }

        // Validate endpoint if present
        if (pluginData.additionalFields.endpoint && 
            !pluginData.additionalFields.endpoint.startsWith('https://')) {
            const error = 'Endpoint must start with https://';
            console.error('❌ Invalid endpoint format:', pluginData.additionalFields.endpoint);
            showPluginModalError(error);
            return;
        }

        const editing = document.getElementById('plugin-modal').getAttribute('data-editing');
        const method = editing ? 'PUT' : 'POST';
        const url = editing ? `/api/admin/plugins/${encodeURIComponent(editing)}` : '/api/admin/plugins';

        // Build plugin manifest for API
        const pluginManifest = {
            name: pluginData.name,
            displayName: pluginData.displayName,
            type: pluginData.type,
            description: pluginData.description,
            endpoint: pluginData.additionalFields.endpoint || '',
            auth: pluginData.auth,
            metadata: pluginData.metadata,
            additionalFields: pluginData.additionalFields
        };

        console.log('📦 Built plugin manifest:', JSON.stringify(pluginManifest, null, 2));

        // Use shared validation
        try {
            console.log('🔍 Validating plugin manifest...');
            const valid = await sharedValidatePluginManifest(pluginManifest);
            if (!valid) {
                console.error('❌ Plugin manifest validation failed');
                showPluginModalError('Validation error: Invalid plugin data. Check console for details.');
                return;
            }
            console.log('✅ Plugin manifest validation passed');
        } catch (e) {
            console.error('❌ Schema validation error:', e);
            showPluginModalError('Schema validation failed: ' + e.message);
            return;
        }

        // Save plugin
        console.log(`🚀 Sending ${method} request to ${url}...`);
        fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(pluginManifest)
        })
            .then(res => {
                console.log('📡 Server response status:', res.status, res.statusText);
                return res.json().then(data => ({ ok: res.ok, status: res.status, data }));
            })
            .then(({ ok, status, data }) => {
                console.log('📨 Server response data:', JSON.stringify(data, null, 2));
                if (ok && data.success) {
                    console.log('✅ Plugin saved successfully');
                    fetchPlugins();
                    bootstrap.Modal.getInstance(document.getElementById('plugin-modal')).hide();
                    showToast('Plugin saved successfully', 'success');
                } else {
                    console.error('❌ Server returned error:', data);
                    const errorMsg = data.error || data.message || `Server error (${status})`;
                    showPluginModalError(`Error saving plugin: ${errorMsg}`);
                }
            })
            .catch(err => {
                console.error('❌ Network/fetch error:', err);
                showPluginModalError('Error saving plugin: ' + err.message);
            });
    });

    document.getElementById('plugins-tab').addEventListener('shown.bs.tab', function () {
        fetchPlugins();
    });

    function handleEdit(name) { editPlugin(name); }
    function handleDelete(name) { deletePlugin(name); }
    function renderTable(plugins) {
        sharedRenderPluginsTable({
            plugins,
            tbodySelector: '#plugins-table-body',
            onEdit: handleEdit,
            onDelete: handleDelete,
            ensureTable: false // Table is already present in admin view
        });
    }

    function fetchPlugins() {
        fetch('/api/admin/plugins')
            .then(res => {
                if (!res.ok) throw new Error('Failed to fetch plugins');
                return res.json();
            })
            .then(plugins => renderTable(plugins))
            .catch(err => showToast('Error loading plugins: ' + err.message, 'danger'));
    }

    // Initial table load
    fetchPlugins();
});

// Edit plugin modal logic
async function editPlugin(name) {
    const res = await fetch('/api/admin/plugins');
    const plugins = await res.json();
    const plugin = plugins.find(p => p.name === name);
    
    if (plugin) {
        // Set editing mode
        document.getElementById('plugin-modal').setAttribute('data-editing', plugin.name);
        
        // Show wizard with plugin data
        await pluginWizard.show(plugin);
    }
}

// Delete plugin logic
function deletePlugin(name) {
    if (confirm(`Are you sure you want to delete plugin "${name}"?`)) {
        fetch(`/api/admin/plugins/${encodeURIComponent(name)}`, {
            method: 'DELETE'
        })
            .then(res => res.json())
            .then(data => {
                if (data.success) {
                    fetchPlugins();
                    showToast('Plugin deleted successfully', 'success');
                } else {
                    showToast('Error deleting plugin: ' + (data.error || 'Unknown error'), 'danger');
                }
            })
            .catch(err => showToast('Error deleting plugin: ' + err.message, 'danger'));
    }
}

function showPluginModalError(msg) {
    pluginWizard.showError(msg);
}

// Main logic
document.addEventListener('DOMContentLoaded', function () {
    if (!document.getElementById('plugins-tab')) return;

    // Use shared logic to populate plugin types
    sharedPopulatePluginTypes({
      endpoint: '/api/admin/plugins/types',
      typeSelect: document.getElementById('plugin-type')
    });

    // Auth type toggle logic
    const authTypeSelect = document.getElementById('plugin-auth-type');
    const authKeyGroup = document.getElementById('auth-key-group');
    const authIdentityGroup = document.getElementById('auth-identity-group');
    const authTenantIdGroup = document.getElementById('auth-tenantid-group');
    const authKeyLabel = document.getElementById('auth-key-label');
    const authIdentityLabel = document.getElementById('auth-identity-label');
    const authTenantIdLabel = document.getElementById('auth-tenantid-label');
    authTypeSelect.addEventListener('change', function() {
        sharedToggleAuthFields({
            authTypeSelect,
            authKeyGroup,
            authIdentityGroup,
            authTenantIdGroup,
            authKeyLabel,
            authIdentityLabel,
            authTenantIdLabel
        });
    });

    // Add plugin button uses shared modal logic
    document.getElementById('add-plugin-btn').addEventListener('click', async function () {
        await sharedShowPluginModal({
          plugin: null,
          populateTypes: () => sharedPopulatePluginTypes({ endpoint: '/api/admin/plugins/types', typeSelect: document.getElementById('plugin-type') }),
          nameField: document.getElementById('plugin-name'),
          typeField: document.getElementById('plugin-type'),
          descField: document.getElementById('plugin-description'),
          endpointField: document.getElementById('plugin-endpoint'),
          authTypeField: document.getElementById('plugin-auth-type'),
          authKeyField: document.getElementById('plugin-auth-key'),
          authIdentityField: document.getElementById('plugin-auth-identity'),
          authTenantIdField: document.getElementById('plugin-auth-tenant-id'),
          metadataField: document.getElementById('plugin-metadata'),
          additionalFieldsField: document.getElementById('plugin-additional-fields'),
          errorDiv: document.getElementById('plugin-modal-error'),
          modalEl: document.getElementById('plugin-modal'),
          afterShow: () => sharedToggleAuthFields({
            authTypeSelect,
            authKeyGroup,
            authIdentityGroup,
            authTenantIdGroup,
            authKeyLabel,
            authIdentityLabel,
            authTenantIdLabel
          })
        });
    });

    // Save plugin (add or edit)
    document.getElementById('save-plugin-btn').addEventListener('click', async function (event) {
        event.preventDefault();
        const name = document.getElementById('plugin-name').value.trim();
        if (/\s/.test(name)) {
            showPluginModalError('Name cannot contain spaces.');
            return;
        }
        const endpoint = document.getElementById('plugin-endpoint').value.trim();
        if (endpoint && !endpoint.startsWith('https://')) {
            showPluginModalError('Endpoint must start with https://');
            return;
        }
        // Use shared validation before saving
        const type = document.getElementById('plugin-type').value.trim();
        const description = document.getElementById('plugin-description').value.trim();
        const authType = document.getElementById('plugin-auth-type').value.trim();
        const authKey = document.getElementById('plugin-auth-key').value.trim();
        const authIdentity = document.getElementById('plugin-auth-identity').value.trim();
        const authTenantId = document.getElementById('plugin-auth-tenant-id').value.trim();
        let metadata, additionalFields;
        try {
            metadata = JSON.parse(document.getElementById('plugin-metadata').value.trim() || '{}');
        } catch (e) {
            showPluginModalError('Metadata must be valid JSON.');
            return;
        }
        try {
            additionalFields = JSON.parse(document.getElementById('plugin-additional-fields').value.trim() || '{}');
        } catch (e) {
            showPluginModalError('Additional Fields must be valid JSON.');
            return;
        }
        const editing = document.getElementById('plugin-modal').getAttribute('data-editing');
        const method = editing ? 'PUT' : 'POST';
        const url = editing ? `/api/admin/plugins/${encodeURIComponent(editing)}` : '/api/admin/plugins';
        const auth = { type: authType };
        if (authType === 'key') {
            auth.key = authKey;
        } else if (authType === 'identity') {
            auth.identity = authIdentity;
        } else if (authType === 'servicePrincipal') {
            auth.identity = authIdentity; // clientId
            auth.key = authKey; // clientSecret
            auth.tenantId = authTenantId;
        }
        const pluginManifest = {
            name,
            type,
            description,
            endpoint,
            auth,
            metadata,
            additionalFields
        };
        // Use shared validation
        const valid = await sharedValidatePluginManifest(pluginManifest);
        if (!valid) {
            showPluginModalError('Validation error: Invalid plugin data.');
            return;
        }
        // Save plugin
        fetch(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(pluginManifest)
        })
            .then(res => res.json().then(data => ({ ok: res.ok, data })))
            .then(({ ok, data }) => {
                if (ok && data.success) {
                    fetchPlugins();
                    bootstrap.Modal.getInstance(document.getElementById('plugin-modal')).hide();
                    showToast('Plugin saved successfully', 'success');
                } else {
                    showPluginModalError(data.error || 'Error saving plugin.');
                }
            })
            .catch(err => showPluginModalError('Error saving plugin: ' + err.message));
    });

    document.getElementById('plugin-endpoint').addEventListener('focus', function() {
        if (!this.value) this.value = 'https://';
    });

    document.getElementById('plugins-tab').addEventListener('shown.bs.tab', function () {
        fetchPlugins();
    });

    function handleEdit(name) { editPlugin(name); }
    function handleDelete(name) { deletePlugin(name); }
    function renderTable(plugins) {
        sharedRenderPluginsTable({
            plugins,
            tbodySelector: '#plugins-table-body',
            onEdit: handleEdit,
            onDelete: handleDelete,
            ensureTable: false // Table is already present in admin view
        });
    }

    function fetchPlugins() {
        fetch('/api/admin/plugins')
            .then(res => {
                if (!res.ok) throw new Error('Failed to fetch plugins');
                return res.json();
            })
            .then(plugins => renderTable(plugins))
            .catch(err => showToast('Error loading plugins: ' + err.message, 'danger'));
    }

    // Initial table load
    fetchPlugins();
});

// Edit plugin modal logic
async function editPlugin(name) {
    const res = await fetch('/api/admin/plugins');
    const plugins = await res.json();
    const plugin = plugins.find(p => p.name === name);
    if (plugin) await sharedShowPluginModal({
        plugin,
        populateTypes: () => sharedPopulatePluginTypes({ endpoint: '/api/admin/plugins/types', typeSelect: document.getElementById('plugin-type') }),
        nameField: document.getElementById('plugin-name'),
        typeField: document.getElementById('plugin-type'),
        descField: document.getElementById('plugin-description'),
        endpointField: document.getElementById('plugin-endpoint'),
        authTypeField: document.getElementById('plugin-auth-type'),
        authKeyField: document.getElementById('plugin-auth-key'),
        authIdentityField: document.getElementById('plugin-auth-identity'),
        authTenantIdField: document.getElementById('plugin-auth-tenant-id'),
        metadataField: document.getElementById('plugin-metadata'),
        additionalFieldsField: document.getElementById('plugin-additional-fields'),
        errorDiv: document.getElementById('plugin-modal-error'),
        modalEl: document.getElementById('plugin-modal'),
        afterShow: () => sharedToggleAuthFields({
            authTypeSelect: document.getElementById('plugin-auth-type'),
            authKeyGroup: document.getElementById('auth-key-group'),
            authIdentityGroup: document.getElementById('auth-identity-group'),
            authTenantIdGroup: document.getElementById('auth-tenantid-group'),
            authKeyLabel: document.getElementById('auth-key-label'),
            authIdentityLabel: document.getElementById('auth-identity-label'),
            authTenantIdLabel: document.getElementById('auth-tenantid-label')
        })
    });
}

// Delete plugin logic
function deletePlugin(name) {
    const modalEl = document.getElementById('plugin-modal');
    if (modalEl && bootstrap.Modal.getInstance(modalEl)) {
        bootstrap.Modal.getInstance(modalEl).hide();
    }
    if (!confirm('Delete this plugin?')) return;
    fetch(`/api/admin/plugins/${encodeURIComponent(name)}`, {
        method: 'DELETE',
        headers: {}
    })
        .then(res => res.json().then(data => ({ ok: res.ok, data })))
        .then(({ ok, data }) => {
            if (ok && data.success) {
                // Reload table
                document.querySelector('#plugins-tab').dispatchEvent(new CustomEvent('shown.bs.tab'));
                showToast('Plugin deleted', 'success');
            } else {
                showToast(data.error || 'Error deleting plugin.', 'danger');
            }
        })
        .catch(err => showToast('Error deleting plugin: ' + err.message, 'danger'));
}

function showPluginModalError(msg) {
    const errDiv = document.getElementById('plugin-modal-error');
    errDiv.textContent = msg;
    errDiv.classList.remove('d-none');
}
