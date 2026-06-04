// workspace-identities.js

function initializeWorkspaceIdentityRoot(root) {
    if (!root || root.dataset.workspaceIdentityInitialized === 'true') {
        return;
    }
    root.dataset.workspaceIdentityInitialized = 'true';

    const apiBase = root.dataset.identityApiBase || root.dataset.apiBase || '';
    const rootKey = root.id || `workspace-identities-${Math.random().toString(36).slice(2, 10)}`;
    const permissionMessage = root.dataset.permissionMessage || 'You do not have permission to manage or view identities for this workspace.';
    const readCanManage = () => root.dataset.canManage !== 'false';
    const state = {
        identities: [],
        canManage: readCanManage(),
    };

    const capabilityConfigs = {
        file_sync: {
            label: 'File Sync',
            help: 'Use this identity for File Sync sources, including SMB, Azure Files, and admin-approved cloud drive connectors.',
            provider: 'smb',
            sourceTypes: ['smb', 'azure_files', 'onedrive', 'google_drive', 'google_shared_drive'],
            usageContexts: ['file_sync'],
            authTypes: ['username_password', 'anonymous', 'managed_identity', 'client_secret', 'connection_string'],
        },
        action: {
            label: 'Actions',
            help: 'Use this identity for tools and plugin-style actions that agents or workflows call.',
            provider: 'action',
            sourceTypes: ['action'],
            usageContexts: ['action'],
            authTypes: ['api_key', 'bearer_token', 'client_secret', 'connection_string', 'username_password', 'managed_identity'],
        },
        model_endpoint: {
            label: 'Model Endpoints',
            help: 'Use this identity for custom model endpoint authentication.',
            provider: 'model_endpoint',
            sourceTypes: ['model_endpoint'],
            usageContexts: ['model_endpoint'],
            authTypes: ['api_key', 'bearer_token', 'client_secret', 'managed_identity'],
        },
    };

    const authTypeLabels = {
        anonymous: 'Anonymous',
        api_key: 'API key',
        bearer_token: 'Bearer token',
        client_secret: 'Client secret',
        connection_string: 'Connection string',
        managed_identity: 'Managed identity',
        username_password: 'Username and password',
    };

    const usageAliases = {
        agent: 'action',
        plugin: 'action',
        general: 'action',
    };

    const parseList = (value) => String(value || '')
        .split(/[,;\n]+/)
        .map((item) => item.trim().toLowerCase())
        .filter((item, index, allItems) => item && allItems.indexOf(item) === index);

    const normalizeCapability = (value) => {
        const normalizedValue = String(value || '').trim().toLowerCase();
        return usageAliases[normalizedValue] || normalizedValue;
    };

    const configuredCapabilities = parseList(root.dataset.capabilityOptions || root.dataset.usageContextOptions || 'file_sync,action,model_endpoint')
        .map(normalizeCapability)
        .filter((value, index, allValues) => capabilityConfigs[value] && allValues.indexOf(value) === index);
    const capabilityOptions = configuredCapabilities.length > 0 ? configuredCapabilities : ['action'];
    const configuredAuthTypes = parseList(root.dataset.authTypeOptions || 'username_password,anonymous,api_key,bearer_token,client_secret,connection_string,managed_identity');
    const configuredDefaultCapabilities = parseList(root.dataset.defaultCapabilities || root.dataset.defaultCapability || root.dataset.defaultUsageContexts)
        .map(normalizeCapability)
        .filter((value, index, allValues) => capabilityOptions.includes(value) && allValues.indexOf(value) === index);
    const defaultCapabilities = configuredDefaultCapabilities.length > 0 ? configuredDefaultCapabilities : [capabilityOptions[0]];

    const createElement = (tagName, options = {}) => {
        const element = document.createElement(tagName);
        if (options.className) {
            element.className = options.className;
        }
        if (options.text !== undefined) {
            element.textContent = options.text;
        }
        if (options.attributes) {
            Object.entries(options.attributes).forEach(([name, value]) => {
                element.setAttribute(name, value);
            });
        }
        return element;
    };

    const appendChildren = (parent, children) => {
        children.forEach((child) => parent.appendChild(child));
        return parent;
    };

    const createIcon = (iconClass) => createElement('i', { className: iconClass, attributes: { 'aria-hidden': 'true' } });

    const createButton = (className, label, iconClass = '') => {
        const button = createElement('button', { className, attributes: { type: 'button' } });
        if (iconClass) {
            button.appendChild(createIcon(`${iconClass} me-1`));
        }
        if (label) {
            button.appendChild(createElement('span', { text: label }));
        }
        return button;
    };

    const createHelpIcon = (helpText) => createElement('i', {
        className: 'bi bi-info-circle ms-2 text-muted',
        attributes: {
            tabindex: '0',
            role: 'img',
            'aria-label': helpText,
            title: helpText,
            'data-bs-toggle': 'tooltip',
        },
    });

    const createLabel = (id, labelText, helpText = '') => {
        const label = createElement('label', { className: 'form-label', attributes: { for: id } });
        label.appendChild(createElement('span', { text: labelText }));
        if (helpText) {
            label.appendChild(createHelpIcon(helpText));
        }
        return label;
    };

    const createSectionHeading = (labelText, helpText = '') => {
        const heading = createElement('h6', { className: 'card-title mb-3' });
        heading.appendChild(createElement('span', { text: labelText }));
        if (helpText) {
            heading.appendChild(createHelpIcon(helpText));
        }
        return heading;
    };

    const initializeTooltips = (container) => {
        if (!window.bootstrap?.Tooltip) {
            return;
        }
        container.querySelectorAll('[data-bs-toggle="tooltip"]').forEach((element) => {
            window.bootstrap.Tooltip.getOrCreateInstance(element);
        });
    };

    const formatAuthType = (authType) => authTypeLabels[authType] || String(authType || '').replace(/_/g, ' ');

    const formatDate = (value) => {
        if (!value) {
            return '';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return String(value);
        }
        return date.toLocaleString();
    };

    const getCapabilityConfig = (capability) => capabilityConfigs[capability] || capabilityConfigs.action;

    const getCapabilitiesFromIdentity = (identity = {}) => {
        const usageContexts = Array.isArray(identity.usage_contexts) ? identity.usage_contexts.map(normalizeCapability) : [];
        const supportedSourceTypes = Array.isArray(identity.supported_source_types) ? identity.supported_source_types.map(normalizeCapability) : [];
        const provider = String(identity.provider || identity.source_type || '').toLowerCase();
        const capabilities = capabilityOptions.filter((capability) => {
            const capabilityConfig = getCapabilityConfig(capability);
            const matchesUsage = capabilityConfig.usageContexts.some((usageContext) => usageContexts.includes(usageContext));
            const matchesSourceType = capabilityConfig.sourceTypes.some((sourceType) => supportedSourceTypes.includes(sourceType));
            return matchesUsage || matchesSourceType || provider === capabilityConfig.provider;
        });
        return capabilities.length > 0 ? capabilities : [...defaultCapabilities];
    };

    const getAllowedAuthTypes = (capabilities) => {
        const configuredSet = new Set(configuredAuthTypes);
        const authTypes = [];
        const capabilityValues = Array.isArray(capabilities) ? capabilities : [capabilities];
        capabilityValues.forEach((capability) => {
            getCapabilityConfig(capability).authTypes.forEach((authType) => {
                if (configuredSet.has(authType) && !authTypes.includes(authType)) {
                    authTypes.push(authType);
                }
            });
        });
        return authTypes.length > 0 ? authTypes : ['username_password'];
    };

    const getCapabilityPayloadValues = (capabilities) => {
        const usageContexts = [];
        const sourceTypes = [];
        const capabilityValues = Array.isArray(capabilities) && capabilities.length > 0 ? capabilities : [...defaultCapabilities];
        capabilityValues.forEach((capability) => {
            const capabilityConfig = getCapabilityConfig(capability);
            capabilityConfig.usageContexts.forEach((usageContext) => {
                if (!usageContexts.includes(usageContext)) {
                    usageContexts.push(usageContext);
                }
            });
            capabilityConfig.sourceTypes.forEach((sourceType) => {
                if (!sourceTypes.includes(sourceType)) {
                    sourceTypes.push(sourceType);
                }
            });
        });
        return {
            provider: sourceTypes[0] || getCapabilityConfig(capabilityValues[0]).provider,
            sourceTypes,
            usageContexts,
        };
    };

    const formatCapabilities = (capabilities) => capabilities
        .map((capability) => getCapabilityConfig(capability).label)
        .join(', ');

    const getPrincipalText = (identity = {}) => {
        const credentials = identity.credentials || {};
        if (credentials.username) {
            return credentials.domain ? `${credentials.domain}\\${credentials.username}` : credentials.username;
        }
        if (credentials.auth_type === 'managed_identity') {
            return 'Managed identity';
        }
        if (credentials.identity) {
            return credentials.identity;
        }
        if (credentials.secret_stored) {
            return 'Stored secret';
        }
        if (credentials.password_stored) {
            return 'Stored password';
        }
        return '';
    };

    const setStatus = (message, type = 'info') => {
        const status = root.querySelector('[data-workspace-identity-status]');
        if (!status) {
            return;
        }
        status.textContent = message;
        status.className = `alert alert-${type} py-2 mb-3`;
    };

    const clearStatus = () => {
        const status = root.querySelector('[data-workspace-identity-status]');
        if (!status) {
            return;
        }
        status.textContent = '';
        status.className = 'alert alert-info py-2 mb-3 d-none';
    };

    const renderPermissionNotice = () => {
        root.replaceChildren();
        root.appendChild(createElement('div', {
            className: 'alert alert-warning mb-0',
            text: permissionMessage,
            attributes: {
                role: 'alert',
                'data-workspace-identity-permission-message': 'true',
            },
        }));
    };

    const fetchJson = async (url, options = {}) => {
        const response = await fetch(url, {
            credentials: 'same-origin',
            headers: {
                'Content-Type': 'application/json',
                ...(options.headers || {}),
            },
            ...options,
        });
        const payload = await response.json().catch(() => ({}));
        if (!response.ok) {
            throw new Error(payload.error || payload.message || `Request failed with ${response.status}`);
        }
        return payload;
    };

    const buildTextField = (id, labelText, value = '', options = {}) => {
        const wrapper = createElement('div', { className: options.wrapperClass || 'col-md-6' });
        const label = createLabel(id, labelText, options.help || '');
        const inputAttributes = {
            id,
            type: options.type || 'text',
            value,
            placeholder: options.placeholder || '',
        };
        if (options.assistiveText) {
            inputAttributes['aria-describedby'] = `${id}-help`;
        }
        const input = createElement('input', {
            className: 'form-control',
            attributes: inputAttributes,
        });
        appendChildren(wrapper, [label, input]);
        if (options.assistiveText) {
            wrapper.appendChild(createElement('div', {
                className: 'form-text',
                text: options.assistiveText,
                attributes: { id: `${id}-help` },
            }));
        }
        return { wrapper, input, label };
    };

    const buildSelectField = (id, labelText, values, selectedValue, helpText = '') => {
        const wrapper = createElement('div', { className: 'col-md-6' });
        const label = createLabel(id, labelText, helpText);
        const select = createElement('select', { className: 'form-select', attributes: { id } });
        values.forEach((value) => {
            const option = createElement('option', { text: formatAuthType(value), attributes: { value } });
            option.selected = value === selectedValue;
            select.appendChild(option);
        });
        appendChildren(wrapper, [label, select]);
        return { wrapper, select };
    };

    const buildCard = (titleText, children, helpText = '') => {
        const card = createElement('div', { className: 'card border-0 shadow-sm mb-3' });
        const body = createElement('div', { className: 'card-body' });
        appendChildren(body, [createSectionHeading(titleText, helpText), ...children]);
        card.appendChild(body);
        return card;
    };

    const buildDetailRow = (labelText, valueText) => {
        const row = createElement('div', { className: 'row py-1' });
        row.appendChild(createElement('div', { className: 'col-sm-4 text-muted', text: labelText }));
        row.appendChild(createElement('div', { className: 'col-sm-8', text: valueText || '' }));
        return row;
    };

    const showModal = (modalElement) => {
        document.body.appendChild(modalElement);
        initializeTooltips(modalElement);
        if (window.bootstrap?.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modalElement, { backdrop: 'static' }).show();
            return;
        }
        modalElement.classList.add('show', 'd-block');
        modalElement.removeAttribute('aria-hidden');
    };

    const hideModal = (modalElement) => {
        if (window.bootstrap?.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modalElement).hide();
            return;
        }
        modalElement.remove();
    };

    const loadIdentities = async () => {
        if (!state.canManage) {
            state.identities = [];
            renderPermissionNotice();
            return;
        }
        if (!apiBase) {
            setStatus('Identity API is not configured.', 'danger');
            return;
        }
        try {
            clearStatus();
            const payload = await fetchJson(`${apiBase}/identities`);
            state.identities = Array.isArray(payload.identities) ? payload.identities : [];
            renderTable();
        } catch (error) {
            state.identities = [];
            renderTable();
            setStatus(error.message, 'danger');
        }
    };

    const openDeleteIdentityModal = (identity) => {
        const modalId = `${rootKey}-delete-${identity.id || 'identity'}`;
        const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true', 'aria-labelledby': `${modalId}-title` } });
        const dialog = createElement('div', { className: 'modal-dialog modal-dialog-centered' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', { className: 'modal-title', text: 'Delete Identity', attributes: { id: `${modalId}-title` } });
        const closeButton = createButton('btn-close', '');
        closeButton.setAttribute('aria-label', 'Close');
        const body = createElement('div', { className: 'modal-body' });
        body.appendChild(createElement('p', { className: 'mb-1', text: identity.name || 'Identity' }));
        body.appendChild(createElement('p', { className: 'text-muted small mb-0', text: 'Delete this reusable identity.' }));
        const footer = createElement('div', { className: 'modal-footer' });
        const cancelButton = createButton('btn btn-outline-secondary', 'Cancel');
        const deleteButton = createButton('btn btn-danger', 'Delete', 'bi bi-trash');

        closeButton.addEventListener('click', () => hideModal(modal));
        cancelButton.addEventListener('click', () => hideModal(modal));
        deleteButton.addEventListener('click', async () => {
            try {
                deleteButton.disabled = true;
                await fetchJson(`${apiBase}/identities/${identity.id}`, { method: 'DELETE' });
                hideModal(modal);
                await loadIdentities();
                setStatus('Identity deleted.', 'success');
            } catch (error) {
                setStatus(error.message, 'danger');
            } finally {
                deleteButton.disabled = false;
            }
        });

        modal.addEventListener('hidden.bs.modal', () => modal.remove(), { once: true });
        appendChildren(header, [title, closeButton]);
        appendChildren(footer, [cancelButton, deleteButton]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modal.appendChild(dialog);
        showModal(modal);
    };

    const openIdentityModal = (initialMode = 'create', identity = null) => {
        const modalId = `${rootKey}-modal-${Math.random().toString(36).slice(2, 10)}`;
        let mode = initialMode;
        const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true', 'aria-labelledby': `${modalId}-title` } });
        const dialog = createElement('div', { className: 'modal-dialog modal-xl modal-dialog-scrollable' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', { className: 'modal-title', attributes: { id: `${modalId}-title` } });
        const closeButton = createButton('btn-close', '');
        closeButton.setAttribute('aria-label', 'Close');
        const body = createElement('div', { className: 'modal-body' });
        const footer = createElement('div', { className: 'modal-footer' });

        const renderView = () => {
            const capabilities = getCapabilitiesFromIdentity(identity || {});
            const credentials = identity?.credentials || {};
            const identityDetails = createElement('div');
            appendChildren(identityDetails, [
                buildDetailRow('Name', identity?.name || ''),
                buildDetailRow('Description', identity?.description || ''),
                buildDetailRow('Identity ID', identity?.id || ''),
            ]);
            const usageDetails = createElement('div');
            appendChildren(usageDetails, [
                buildDetailRow('Used For', formatCapabilities(capabilities)),
            ]);
            const authDetails = createElement('div');
            appendChildren(authDetails, [
                buildDetailRow('Authentication', formatAuthType(credentials.auth_type || '')),
                buildDetailRow('Principal', getPrincipalText(identity || {})),
                buildDetailRow('Secret', credentials.secret_stored || credentials.password_stored ? 'Stored' : ''),
                buildDetailRow('Updated', formatDate(identity?.updated_at)),
            ]);
            appendChildren(body, [
                buildCard('Identity Details', [identityDetails]),
                buildCard('Used For', [usageDetails]),
                buildCard('Authentication', [authDetails]),
            ]);
        };

        const renderForm = () => {
            const formIdentity = identity || {};
            const credentials = formIdentity.credentials || {};
            let selectedCapabilities = getCapabilitiesFromIdentity(formIdentity);
            let selectedAuthType = credentials.auth_type || getAllowedAuthTypes(selectedCapabilities)[0];
            const nameField = buildTextField(`${modalId}-name`, 'Identity name', formIdentity.name || '', { help: 'A friendly name shown in identity pickers.' });
            const descriptionField = buildTextField(`${modalId}-description`, 'Description', formIdentity.description || '', { help: 'Optional note for admins or workspace managers.' });
            const capabilityWrapper = createElement('div', { className: 'd-flex flex-wrap gap-3' });
            const authTypeField = buildSelectField(
                `${modalId}-auth-type`,
                'Authentication',
                getAllowedAuthTypes(selectedCapabilities),
                selectedAuthType,
                'The credential method this identity stores.',
            );
            const usernameField = buildTextField(`${modalId}-username`, 'Username', credentials.username || '');
            const domainField = buildTextField(`${modalId}-domain`, 'Domain (optional)', credentials.domain || '', {
                placeholder: 'Leave blank when no domain is required',
                help: 'Use a domain only for accounts that require one.',
                assistiveText: 'Leave this blank when the account signs in without a domain.',
            });
            const clientIdField = buildTextField(`${modalId}-client-id`, 'Client ID', credentials.identity || '', { placeholder: 'Application or service principal client ID' });
            const secretField = buildTextField(`${modalId}-secret`, 'Secret', '', {
                type: 'password',
                placeholder: credentials.secret_stored || credentials.password_stored ? 'Stored value unchanged' : '',
            });
            const modalStatus = createElement('div', { className: 'alert alert-info py-2 mb-3 d-none', attributes: { role: 'alert' } });

            const setModalStatus = (message, type = 'info') => {
                modalStatus.textContent = message;
                modalStatus.className = `alert alert-${type} py-2 mb-3`;
            };

            const renderAuthOptions = () => {
                const authTypes = getAllowedAuthTypes(selectedCapabilities);
                if (!authTypes.includes(selectedAuthType)) {
                    selectedAuthType = authTypes[0];
                }
                authTypeField.select.replaceChildren();
                authTypes.forEach((authType) => {
                    const option = createElement('option', { text: formatAuthType(authType), attributes: { value: authType } });
                    option.selected = authType === selectedAuthType;
                    authTypeField.select.appendChild(option);
                });
            };

            const updateAuthVisibility = () => {
                selectedAuthType = authTypeField.select.value;
                const usesUsernamePassword = selectedAuthType === 'username_password';
                const usesManagedIdentity = selectedAuthType === 'managed_identity';
                const usesClientSecret = selectedAuthType === 'client_secret';
                const usesSecret = ['api_key', 'bearer_token', 'client_secret', 'connection_string'].includes(selectedAuthType);
                usernameField.wrapper.classList.toggle('d-none', !usesUsernamePassword);
                domainField.wrapper.classList.toggle('d-none', !usesUsernamePassword);
                clientIdField.wrapper.classList.toggle('d-none', !usesClientSecret);
                secretField.wrapper.classList.toggle('d-none', selectedAuthType === 'anonymous' || usesManagedIdentity);
                if (usesUsernamePassword) {
                    secretField.label.textContent = credentials.password_stored ? 'Password (stored)' : 'Password';
                } else if (usesClientSecret) {
                    secretField.label.textContent = credentials.secret_stored ? 'Client secret (stored)' : 'Client secret';
                } else {
                    secretField.label.textContent = credentials.secret_stored ? 'Secret (stored)' : 'Secret';
                }
                if (!usesUsernamePassword && !usesSecret) {
                    secretField.input.value = '';
                }
            };

            const updateCapabilitySelection = () => {
                capabilityWrapper.querySelectorAll('[data-workspace-identity-capability]').forEach((input) => {
                    input.checked = selectedCapabilities.includes(input.value);
                });
                renderAuthOptions();
                updateAuthVisibility();
            };

            capabilityOptions.forEach((capability) => {
                const capabilityConfig = getCapabilityConfig(capability);
                const optionId = `${modalId}-capability-${capability}`;
                const optionWrapper = createElement('div', { className: 'form-check border rounded px-3 py-2' });
                const input = createElement('input', {
                    className: 'form-check-input',
                    attributes: {
                        type: 'checkbox',
                        id: optionId,
                        value: capability,
                        'data-workspace-identity-capability': 'true',
                    },
                });
                const label = createElement('label', { className: 'form-check-label', attributes: { for: optionId } });
                label.appendChild(createElement('span', { text: capabilityConfig.label }));
                label.appendChild(createHelpIcon(capabilityConfig.help));
                input.checked = selectedCapabilities.includes(capability);
                input.addEventListener('change', () => {
                    if (input.checked && !selectedCapabilities.includes(input.value)) {
                        selectedCapabilities.push(input.value);
                    } else if (!input.checked && selectedCapabilities.length > 1) {
                        selectedCapabilities = selectedCapabilities.filter((capabilityValue) => capabilityValue !== input.value);
                    } else if (!input.checked) {
                        input.checked = true;
                    }
                    selectedAuthType = getAllowedAuthTypes(selectedCapabilities).includes(selectedAuthType)
                        ? selectedAuthType
                        : getAllowedAuthTypes(selectedCapabilities)[0];
                    updateCapabilitySelection();
                });
                appendChildren(optionWrapper, [input, label]);
                capabilityWrapper.appendChild(optionWrapper);
            });

            authTypeField.select.addEventListener('change', updateAuthVisibility);

            const detailsGrid = createElement('div', { className: 'row g-3' });
            appendChildren(detailsGrid, [nameField.wrapper, descriptionField.wrapper]);
            const authGrid = createElement('div', { className: 'row g-3' });
            appendChildren(authGrid, [
                authTypeField.wrapper,
                usernameField.wrapper,
                domainField.wrapper,
                clientIdField.wrapper,
                secretField.wrapper,
            ]);

            appendChildren(body, [
                modalStatus,
                buildCard('Identity Details', [detailsGrid], 'Name and describe the reusable identity.'),
                buildCard('Used For', [capabilityWrapper], 'Choose the SimpleChat capability that can use this identity.'),
                buildCard('Authentication', [authGrid], 'Store the credential material used by the selected capability.'),
            ]);

            updateCapabilitySelection();

            const saveButton = createButton('btn btn-success', mode === 'edit' ? 'Save Identity' : 'Add Identity', 'bi bi-check2');
            saveButton.addEventListener('click', async () => {
                const capabilityPayload = getCapabilityPayloadValues(selectedCapabilities);
                const credentialsPayload = {
                    auth_type: selectedAuthType,
                    username: usernameField.input.value.trim(),
                    domain: domainField.input.value.trim(),
                    identity: selectedAuthType === 'client_secret' ? clientIdField.input.value.trim() : '',
                    client_id: selectedAuthType === 'client_secret' ? clientIdField.input.value.trim() : '',
                };
                if (selectedAuthType === 'username_password') {
                    credentialsPayload.password = secretField.input.value;
                } else {
                    credentialsPayload.secret = secretField.input.value;
                }
                const payload = {
                    name: nameField.input.value.trim(),
                    description: descriptionField.input.value.trim(),
                    provider: capabilityPayload.provider,
                    source_type: capabilityPayload.provider,
                    usage_contexts: capabilityPayload.usageContexts,
                    supported_source_types: capabilityPayload.sourceTypes,
                    credentials: credentialsPayload,
                };

                try {
                    saveButton.disabled = true;
                    const url = mode === 'edit' ? `${apiBase}/identities/${identity.id}` : `${apiBase}/identities`;
                    await fetchJson(url, {
                        method: mode === 'edit' ? 'PATCH' : 'POST',
                        body: JSON.stringify(payload),
                    });
                    hideModal(modal);
                    await loadIdentities();
                    setStatus('Identity saved.', 'success');
                } catch (error) {
                    setModalStatus(error.message, 'danger');
                } finally {
                    saveButton.disabled = false;
                }
            });
            footer.appendChild(saveButton);
        };

        const renderContent = () => {
            body.replaceChildren();
            footer.replaceChildren();
            title.textContent = mode === 'view' ? 'Identity Details' : (mode === 'edit' ? 'Edit Identity' : 'Add Identity');
            if (mode === 'view') {
                renderView();
                const editButton = createButton('btn btn-primary', 'Edit', 'bi bi-pencil');
                editButton.addEventListener('click', () => {
                    mode = 'edit';
                    renderContent();
                    initializeTooltips(modal);
                });
                footer.appendChild(editButton);
            } else {
                renderForm();
            }
            const closeFooterButton = createButton('btn btn-outline-secondary', 'Close');
            closeFooterButton.addEventListener('click', () => hideModal(modal));
            footer.appendChild(closeFooterButton);
        };

        closeButton.addEventListener('click', () => hideModal(modal));
        modal.addEventListener('hidden.bs.modal', () => modal.remove(), { once: true });
        appendChildren(header, [title, closeButton]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modal.appendChild(dialog);
        renderContent();
        showModal(modal);
    };

    const renderTable = () => {
        if (!state.canManage) {
            return;
        }
        const tableBody = root.querySelector('[data-workspace-identity-rows]');
        if (!tableBody) {
            return;
        }
        tableBody.replaceChildren();
        if (state.identities.length === 0) {
            const row = createElement('tr');
            row.appendChild(createElement('td', { className: 'text-muted', text: 'No identities configured.', attributes: { colspan: '5' } }));
            tableBody.appendChild(row);
            return;
        }

        state.identities.forEach((identity) => {
            const credentials = identity.credentials || {};
            const capabilities = getCapabilitiesFromIdentity(identity);
            const row = createElement('tr');
            const actionsCell = createElement('td', { className: 'text-end text-nowrap' });
            const viewButton = createButton('btn btn-sm btn-outline-secondary me-2', 'View', 'bi bi-eye');
            const editButton = createButton('btn btn-sm btn-outline-primary me-2', 'Edit', 'bi bi-pencil');
            const deleteButton = createButton('btn btn-sm btn-outline-danger', 'Delete', 'bi bi-trash');

            viewButton.addEventListener('click', () => openIdentityModal('view', identity));
            editButton.addEventListener('click', () => openIdentityModal('edit', identity));
            deleteButton.addEventListener('click', () => openDeleteIdentityModal(identity));

            appendChildren(actionsCell, [viewButton, editButton, deleteButton]);
            appendChildren(row, [
                createElement('td', { text: identity.name || '' }),
                createElement('td', { text: formatCapabilities(capabilities) }),
                createElement('td', { text: formatAuthType(credentials.auth_type || '') }),
                createElement('td', { text: formatDate(identity.updated_at) }),
                actionsCell,
            ]);
            tableBody.appendChild(row);
        });
    };

    const renderLayout = () => {
        root.replaceChildren();
        if (!state.canManage) {
            renderPermissionNotice();
            return;
        }
        const toolbar = createElement('div', { className: 'd-flex flex-wrap gap-2 justify-content-start align-items-center mb-3' });
        const addButton = createButton('btn btn-success btn-sm', 'Add Identity', 'bi bi-plus-lg');
        const status = createElement('div', { className: 'alert alert-info py-2 mb-3 d-none', attributes: { 'data-workspace-identity-status': 'true', role: 'alert' } });
        const tableWrapper = createElement('div', { className: 'table-responsive' });
        const table = createElement('table', { className: 'table table-sm align-middle' });
        const thead = createElement('thead');
        const headRow = createElement('tr');
        ['Identity', 'Used For', 'Authentication', 'Updated', 'Actions'].forEach((headerText) => {
            headRow.appendChild(createElement('th', { text: headerText }));
        });
        const tbody = createElement('tbody', { attributes: { 'data-workspace-identity-rows': 'true' } });

        addButton.addEventListener('click', () => openIdentityModal('create'));

        toolbar.appendChild(addButton);
        thead.appendChild(headRow);
        appendChildren(table, [thead, tbody]);
        tableWrapper.appendChild(table);
        appendChildren(root, [toolbar, status, tableWrapper]);
    };

    const refreshIdentities = () => {
        state.canManage = readCanManage();
        if (!state.canManage) {
            state.identities = [];
            renderPermissionNotice();
            return;
        }
        renderLayout();
        renderTable();
        loadIdentities();
    };

    root.addEventListener('workspace-identities:permissions-changed', refreshIdentities);
    root.addEventListener('workspace-identities:refresh', refreshIdentities);
    root.workspaceIdentityRefresh = refreshIdentities;

    renderLayout();
    if (state.canManage) {
        renderTable();
        loadIdentities();
    }
}

window.initializeWorkspaceIdentityRoot = initializeWorkspaceIdentityRoot;
document.querySelectorAll('[data-workspace-identity-root]').forEach((root) => {
    initializeWorkspaceIdentityRoot(root);
});
