// workspace-file-sync.js

function initializeFileSyncRoot(root) {
    if (!root || root.dataset.fileSyncInitialized === 'true') {
        return;
    }
    root.dataset.fileSyncInitialized = 'true';

    const state = {
        sources: [],
        editingSourceId: null,
        historySourceId: null,
        sourceModalStep: 'type',
        selectedSourceType: 'smb',
        availableTags: [],
        tagsLoaded: false,
        identities: [],
        identitiesLoaded: false,
    };

    const apiBase = root.dataset.apiBase;
    const scopeType = root.dataset.scope || '';
    const identityApiBase = root.dataset.identityApiBase || apiBase
        .replace('/api/admin/file-sync/', '/api/admin/workspace-identities/')
        .replace('/api/file-sync/', '/api/workspace-identities/');
    const tagApiUrl = root.dataset.tagsApi || '';
    const recursiveAllowed = root.dataset.recursiveAllowed !== 'false';
    const sourceTypes = [
        {
            value: 'smb',
            label: 'SMB Share',
            description: 'Windows or SMB-compatible file share.',
            enabled: true,
        },
        {
            value: 'azure_files',
            label: 'Azure Files',
            description: 'Azure Storage file share endpoint.',
            enabled: true,
        },
        {
            value: 'onedrive',
            label: 'OneDrive',
            description: 'Files and folders from a personal OneDrive.',
            enabled: true,
            scopes: ['personal'],
        },
        {
            value: 'sharepoint_on_prem',
            label: 'On-prem SharePoint',
            description: 'Coming soon.',
            enabled: false,
        },
        {
            value: 'google_workspace',
            label: 'Google Workspace',
            description: 'Coming soon.',
            enabled: false,
        },
    ];

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

    const getSourceTypeDefinition = (sourceTypeValue) => sourceTypes.find((sourceType) => sourceType.value === sourceTypeValue);

    const formatSourceType = (sourceTypeValue) => {
        const sourceType = getSourceTypeDefinition(sourceTypeValue || 'smb');
        if (sourceType) {
            return sourceType.label;
        }
        return String(sourceTypeValue || 'smb').toUpperCase();
    };

    const isSourceTypeEnabled = (sourceTypeValue) => getSourceTypeDefinition(sourceTypeValue)?.enabled === true;

    const parseList = (value) => String(value || '')
        .split(/[\n,;]+/)
        .map((item) => item.trim())
        .filter((item, index, allItems) => item && allItems.indexOf(item) === index);

    const visibleSourceTypeValues = new Set(
        parseList(root.dataset.visibleSourceTypes === undefined ? 'smb,azure_files' : root.dataset.visibleSourceTypes)
            .map((sourceTypeValue) => sourceTypeValue.toLowerCase())
            .filter((sourceTypeValue) => sourceTypes.some((sourceType) => sourceType.value === sourceTypeValue)),
    );
    const isSourceTypeAllowedForScope = (sourceType) => !Array.isArray(sourceType.scopes) || sourceType.scopes.includes(scopeType);
    const isSourceTypeVisible = (sourceTypeValue) => visibleSourceTypeValues.has(sourceTypeValue);
    const isSourceTypeSelectable = (sourceTypeValue) => {
        const sourceType = getSourceTypeDefinition(sourceTypeValue);
        return sourceType && isSourceTypeVisible(sourceTypeValue) && isSourceTypeEnabled(sourceTypeValue) && isSourceTypeAllowedForScope(sourceType);
    };
    const getVisibleSourceTypes = () => sourceTypes.filter((sourceType) => isSourceTypeVisible(sourceType.value) && isSourceTypeAllowedForScope(sourceType));
    const sourceTypeAuthTypes = {
        smb: ['username_password', 'anonymous'],
        azure_files: ['managed_identity', 'client_secret', 'connection_string'],
        onedrive: ['global_identity'],
    };
    const authTypeLabels = {
        anonymous: 'Anonymous',
        client_secret: 'Service principal',
        connection_string: 'Connection string',
        global_identity: 'Global connector identity',
        managed_identity: 'Managed identity',
        username_password: 'Username and password',
    };
    const getSourceTypeAuthTypes = (sourceTypeValue) => sourceTypeAuthTypes[sourceTypeValue || 'smb'] || ['username_password', 'anonymous'];
    const formatAuthType = (authType) => authTypeLabels[authType] || String(authType || '').replace(/_/g, ' ');
    const identitySupportsFileSync = (identity, sourceTypeValue) => {
        const usageContexts = Array.isArray(identity.usage_contexts) && identity.usage_contexts.length > 0
            ? identity.usage_contexts
            : ['general'];
        const supportedSourceTypes = Array.isArray(identity.supported_source_types) && identity.supported_source_types.length > 0
            ? identity.supported_source_types
            : [identity.source_type || identity.provider || 'generic'];
        const authType = identity.credentials?.auth_type || '';
        const sourceType = sourceTypeValue || 'smb';
        return (usageContexts.includes('file_sync') || usageContexts.includes('general'))
            && (supportedSourceTypes.includes(sourceType) || supportedSourceTypes.includes('generic') || (identity.source_type || '') === sourceType)
            && getSourceTypeAuthTypes(sourceType).includes(authType);
    };
    const getDefaultSourceTypeValue = () => {
        const visibleEnabledSourceType = getVisibleSourceTypes().find((sourceType) => sourceType.enabled);
        if (visibleEnabledSourceType) {
            return visibleEnabledSourceType.value;
        }
        return getVisibleSourceTypes()[0]?.value || '';
    };

    const showStatus = (message, type = 'info') => {
        const status = root.querySelector('[data-file-sync-status]');
        if (!status) {
            return;
        }
        status.className = `alert alert-${type} py-2 mb-3`;
        status.textContent = message;
        status.classList.remove('d-none');
    };

    const hideStatus = () => {
        const status = root.querySelector('[data-file-sync-status]');
        if (status) {
            status.classList.add('d-none');
        }
    };

    const showModalStatus = (message, type = 'info') => {
        const status = root.querySelector('[data-file-sync-modal-status]');
        if (!status) {
            return;
        }
        status.className = `alert alert-${type} py-2 mb-3`;
        status.textContent = message;
        status.classList.remove('d-none');
    };

    const hideModalStatus = () => {
        const status = root.querySelector('[data-file-sync-modal-status]');
        if (status) {
            status.classList.add('d-none');
        }
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

    const loadAvailableTags = async () => {
        if (!tagApiUrl || state.tagsLoaded) {
            return;
        }
        try {
            const payload = await fetchJson(tagApiUrl);
            state.availableTags = Array.isArray(payload.tags) ? payload.tags : [];
        } catch (error) {
            state.availableTags = [];
        } finally {
            state.tagsLoaded = true;
        }
    };

    const loadIdentities = async (force = false) => {
        if (state.identitiesLoaded && !force) {
            return;
        }
        try {
            const payload = await fetchJson(`${identityApiBase}/identities`);
            state.identities = Array.isArray(payload.identities) ? payload.identities : [];
        } catch (error) {
            state.identities = [];
        } finally {
            state.identitiesLoaded = true;
        }
    };

    const buildLabeledInput = (id, labelText, type = 'text', value = '') => {
        const wrapper = createElement('div', { className: 'col-md-6' });
        const label = createElement('label', { className: 'form-label', text: labelText, attributes: { for: id } });
        const input = createElement('input', {
            className: 'form-control',
            attributes: {
                id,
                type,
                value,
            },
        });
        appendChildren(wrapper, [label, input]);
        return { wrapper, input };
    };

    const createInput = (id, labelText, type = 'text', value = '', options = {}) => {
        const wrapper = createElement('div', { className: 'mb-3' });
        const label = createElement('label', { className: 'form-label', text: labelText, attributes: { for: id } });
        let input;
        if (type === 'select') {
            input = createElement('select', { className: 'form-select', attributes: { id } });
            (options.options || []).forEach((optionConfig) => {
                const option = createElement('option', { text: optionConfig.label, attributes: { value: optionConfig.value } });
                option.selected = String(optionConfig.value) === String(value);
                if (optionConfig.disabled) {
                    option.disabled = true;
                }
                input.appendChild(option);
            });
        } else {
            input = createElement('input', {
                className: 'form-control',
                attributes: {
                    id,
                    type,
                    value,
                    placeholder: options.placeholder || '',
                },
            });
        }
        appendChildren(wrapper, [label, input]);
        return { wrapper, input };
    };

    const buildLabeledTextarea = (id, labelText, value = '') => {
        const wrapper = createElement('div', { className: 'col-md-6' });
        const label = createElement('label', { className: 'form-label', text: labelText, attributes: { for: id } });
        const textarea = createElement('textarea', {
            className: 'form-control',
            attributes: {
                id,
                rows: '3',
            },
        });
        textarea.value = value;
        appendChildren(wrapper, [label, textarea]);
        return { wrapper, textarea };
    };

    const buildCheckbox = (id, labelText, checked = false) => {
        const wrapper = createElement('div', { className: 'form-check form-switch mb-2' });
        const input = createElement('input', {
            className: 'form-check-input',
            attributes: {
                id,
                type: 'checkbox',
            },
        });
        input.checked = checked;
        const label = createElement('label', { className: 'form-check-label ms-2', text: labelText, attributes: { for: id } });
        appendChildren(wrapper, [input, label]);
        return { wrapper, input };
    };

    const buildIntervalControl = (id, labelText, value = 60) => {
        const wrapper = createElement('div', { className: 'col-md-6' });
        const label = createElement('label', { className: 'form-label', text: labelText, attributes: { for: id } });
        const range = createElement('input', {
            className: 'form-range',
            attributes: {
                id,
                type: 'range',
                min: '5',
                max: '1440',
                step: '5',
                value: String(value),
            },
        });
        const numberInput = createElement('input', {
            className: 'form-control',
            attributes: {
                type: 'number',
                min: '5',
                max: '10080',
                value: String(value),
                'aria-label': labelText,
            },
        });
        range.addEventListener('input', () => {
            numberInput.value = range.value;
        });
        numberInput.addEventListener('input', () => {
            const parsedValue = Number.parseInt(numberInput.value, 10);
            if (!Number.isNaN(parsedValue)) {
                range.value = String(Math.max(5, Math.min(1440, parsedValue)));
            }
        });
        appendChildren(wrapper, [label, range, numberInput]);
        return { wrapper, input: numberInput };
    };

    const normalizeTagName = (value) => String(value || '')
        .trim()
        .toLowerCase()
        .replace(/[^a-z0-9_-]+/g, '-')
        .replace(/^-+|-+$/g, '')
        .slice(0, 50);

    const getAvailableTag = (tagName) => state.availableTags.find((tag) => normalizeTagName(tag.name || tag) === normalizeTagName(tagName));

    const createTagBadge = (tagName, onRemove) => {
        const sourceTag = getAvailableTag(tagName) || {};
        const badge = createElement('span', { className: 'badge border d-inline-flex align-items-center gap-1' });
        badge.style.backgroundColor = sourceTag.color || '#f8f9fa';
        badge.style.color = sourceTag.text_color || '#212529';
        badge.style.borderColor = sourceTag.color || '#dee2e6';
        const text = createElement('span', { text: tagName });
        const removeButton = createElement('button', {
            className: 'btn-close btn-close-sm',
            attributes: {
                type: 'button',
                'aria-label': `Remove ${tagName}`,
            },
        });
        removeButton.addEventListener('click', onRemove);
        appendChildren(badge, [text, removeButton]);
        return badge;
    };

    const getTagModalAdapter = () => {
        const adapters = window.simpleChatTagModalAdapters || {};
        if (root.dataset.tagAdapter && adapters[root.dataset.tagAdapter]) {
            return adapters[root.dataset.tagAdapter];
        }
        if (root.dataset.scope && adapters[root.dataset.scope]) {
            return adapters[root.dataset.scope];
        }
        if (apiBase.includes('/personal') && adapters.personal) {
            return adapters.personal;
        }
        if (apiBase.includes('/group') && adapters.group) {
            return adapters.group;
        }
        if (apiBase.includes('/public') && adapters.public) {
            return adapters.public;
        }
        if (typeof window.showTagManagementModal === 'function') {
            return window.simpleChatPersonalTagModalAdapter || null;
        }
        return null;
    };

    const showFallbackTagPicker = async (selectedTags, onChange) => {
        await loadAvailableTags(true);
        const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true' } });
        const dialog = createElement('div', { className: 'modal-dialog modal-dialog-scrollable' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', { className: 'modal-title', text: 'Choose Existing Tags' });
        const closeButton = createElement('button', { className: 'btn-close', attributes: { type: 'button', 'data-bs-dismiss': 'modal', 'aria-label': 'Close' } });
        const body = createElement('div', { className: 'modal-body' });
        const footer = createElement('div', { className: 'modal-footer' });
        const doneButton = createElement('button', { className: 'btn btn-primary', text: 'Done', attributes: { type: 'button' } });
        const choices = new Set(selectedTags);

        const tagNames = state.availableTags
            .map((tag) => normalizeTagName(tag.name || tag))
            .filter(Boolean)
            .filter((tagName, index, allTags) => allTags.indexOf(tagName) === index)
            .sort();
        if (tagNames.length === 0) {
            body.appendChild(createElement('p', { className: 'text-muted mb-0', text: 'No tags are available yet.' }));
        } else {
            const list = createElement('div', { className: 'list-group' });
            tagNames.forEach((tagName) => {
                const label = createElement('label', { className: 'list-group-item d-flex align-items-center gap-2' });
                const checkbox = createElement('input', { className: 'form-check-input m-0', attributes: { type: 'checkbox', value: tagName } });
                checkbox.checked = choices.has(tagName);
                checkbox.addEventListener('change', () => {
                    if (checkbox.checked) {
                        choices.add(tagName);
                    } else {
                        choices.delete(tagName);
                    }
                });
                appendChildren(label, [checkbox, createElement('span', { text: tagName })]);
                list.appendChild(label);
            });
            body.appendChild(list);
        }

        doneButton.addEventListener('click', () => {
            selectedTags.clear();
            choices.forEach((tagName) => selectedTags.add(tagName));
            onChange();
            window.bootstrap.Modal.getOrCreateInstance(modal).hide();
        });
        modal.addEventListener('hidden.bs.modal', () => modal.remove());
        appendChildren(header, [title, closeButton]);
        appendChildren(footer, [createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button', 'data-bs-dismiss': 'modal' } }), doneButton]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modal.appendChild(dialog);
        document.body.appendChild(modal);
        window.bootstrap.Modal.getOrCreateInstance(modal).show();
    };

    const buildFixedTagSelector = (selectedValues = []) => {
        const wrapper = createElement('div');
        const label = createElement('label', { className: 'form-label', text: 'Fixed tags' });
        const selectedTags = new Set(parseList(Array.isArray(selectedValues) ? selectedValues.join(',') : selectedValues).map(normalizeTagName).filter(Boolean));
        const badgeContainer = createElement('div', { className: 'd-flex flex-wrap gap-2 mb-2' });
        const actionRow = createElement('div', { className: 'd-flex flex-wrap gap-2' });
        const chooseButton = createElement('button', { className: 'btn btn-outline-primary btn-sm', text: 'Choose Existing Tags', attributes: { type: 'button' } });
        const createButton = createElement('button', { className: 'btn btn-outline-secondary btn-sm', text: 'Create Tag', attributes: { type: 'button' } });

        const renderBadges = () => {
            badgeContainer.replaceChildren();
            if (selectedTags.size === 0) {
                badgeContainer.appendChild(createElement('span', { className: 'text-muted small', text: 'No fixed tags selected.' }));
                return;
            }
            selectedTags.forEach((tagName) => {
                badgeContainer.appendChild(createTagBadge(tagName, () => {
                    selectedTags.delete(tagName);
                    renderBadges();
                }));
            });
        };

        chooseButton.addEventListener('click', async () => {
            const adapter = getTagModalAdapter();
            if (adapter?.openSelector) {
                adapter.openSelector({
                    selectedTags: Array.from(selectedTags),
                    onDone: (tagNames) => {
                        selectedTags.clear();
                        (tagNames || []).map(normalizeTagName).filter(Boolean).forEach((tagName) => selectedTags.add(tagName));
                        renderBadges();
                    },
                });
                return;
            }
            await showFallbackTagPicker(selectedTags, renderBadges);
        });
        createButton.addEventListener('click', async () => {
            const adapter = getTagModalAdapter();
            if (adapter?.openManager) {
                adapter.openManager({ onTagsChanged: () => loadAvailableTags(true) });
                return;
            }
            if (typeof window.showGroupTagManagementModal === 'function') {
                window.showGroupTagManagementModal();
                return;
            }
            if (typeof window.showPublicTagManagementModal === 'function') {
                window.showPublicTagManagementModal();
                return;
            }
            if (typeof window.showTagManagementModal === 'function') {
                window.showTagManagementModal();
            }
        });

        appendChildren(actionRow, [chooseButton, createButton]);
        appendChildren(wrapper, [label, badgeContainer, actionRow]);
        renderBadges();
        return {
            wrapper,
            getValues: () => Array.from(selectedTags),
        };
    };

    const showPatternEditorModal = (onSave) => {
        const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true' } });
        const dialog = createElement('div', { className: 'modal-dialog' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', { className: 'modal-title', text: 'Add Path Pattern' });
        const closeButton = createElement('button', { className: 'btn-close', attributes: { type: 'button', 'data-bs-dismiss': 'modal', 'aria-label': 'Close' } });
        const body = createElement('div', { className: 'modal-body' });
        const typeGroup = createInput('file-sync-pattern-type', 'Pattern type', 'select', '', {
            options: [
                { value: 'include', label: 'Include' },
                { value: 'exclude', label: 'Exclude' },
            ],
        });
        const patternGroup = createInput('file-sync-pattern-value', 'Pattern', 'text', '', { placeholder: '*.pdf' });
        const examples = createElement('div', { className: 'form-text', text: 'Examples: *.pdf, Reports/*, */Archive/*' });
        const footer = createElement('div', { className: 'modal-footer' });
        const saveButton = createElement('button', { className: 'btn btn-primary', text: 'Add Pattern', attributes: { type: 'button' } });
        saveButton.addEventListener('click', () => {
            const pattern = patternGroup.input.value.trim();
            if (!pattern) {
                patternGroup.input.focus();
                return;
            }
            onSave({ type: typeGroup.input.value, pattern });
            window.bootstrap.Modal.getOrCreateInstance(modal).hide();
        });
        modal.addEventListener('hidden.bs.modal', () => modal.remove());
        appendChildren(header, [title, closeButton]);
        appendChildren(body, [typeGroup.wrapper, patternGroup.wrapper, examples]);
        appendChildren(footer, [createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button', 'data-bs-dismiss': 'modal' } }), saveButton]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modal.appendChild(dialog);
        document.body.appendChild(modal);
        window.bootstrap.Modal.getOrCreateInstance(modal).show();
    };

    const buildPatternListControl = (includePatterns = [], excludePatterns = []) => {
        const wrapper = createElement('div');
        const header = createElement('div', { className: 'd-flex align-items-center justify-content-between gap-2 mb-2' });
        const label = createElement('label', { className: 'form-label mb-0', text: 'Path patterns' });
        const addButton = createElement('button', { className: 'btn btn-outline-primary btn-sm', text: 'Add Pattern', attributes: { type: 'button' } });
        const list = createElement('div', { className: 'list-group list-group-flush border rounded' });
        const patterns = [
            ...includePatterns.map((pattern) => ({ type: 'include', pattern })),
            ...excludePatterns.map((pattern) => ({ type: 'exclude', pattern })),
        ];
        const renderPatterns = () => {
            list.replaceChildren();
            if (patterns.length === 0) {
                list.appendChild(createElement('div', { className: 'list-group-item text-muted small', text: 'No include or exclude patterns.' }));
                return;
            }
            patterns.forEach((item, index) => {
                const row = createElement('div', { className: 'list-group-item d-flex align-items-center justify-content-between gap-2' });
                const textWrap = createElement('div', { className: 'd-flex align-items-center gap-2' });
                const badgeClass = item.type === 'include' ? 'badge text-bg-success' : 'badge text-bg-secondary';
                appendChildren(textWrap, [createElement('span', { className: badgeClass, text: item.type }), createElement('code', { text: item.pattern })]);
                const removeButton = createElement('button', { className: 'btn btn-sm btn-outline-danger', text: 'Remove', attributes: { type: 'button' } });
                removeButton.addEventListener('click', () => {
                    patterns.splice(index, 1);
                    renderPatterns();
                });
                appendChildren(row, [textWrap, removeButton]);
                list.appendChild(row);
            });
        };
        addButton.addEventListener('click', () => showPatternEditorModal((item) => {
            patterns.push(item);
            renderPatterns();
        }));
        appendChildren(header, [label, addButton]);
        appendChildren(wrapper, [header, list]);
        renderPatterns();
        return {
            wrapper,
            getValues: () => ({
                includePatterns: patterns.filter((item) => item.type === 'include').map((item) => item.pattern),
                excludePatterns: patterns.filter((item) => item.type === 'exclude').map((item) => item.pattern),
            }),
        };
    };

    const showExtensionEditorModal = (onSave) => {
        const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true' } });
        const dialog = createElement('div', { className: 'modal-dialog' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', { className: 'modal-title', text: 'Add File Type' });
        const closeButton = createElement('button', { className: 'btn-close', attributes: { type: 'button', 'data-bs-dismiss': 'modal', 'aria-label': 'Close' } });
        const body = createElement('div', { className: 'modal-body' });
        const extensionGroup = createInput('file-sync-extension-value', 'Extension', 'text', '', { placeholder: 'pdf' });
        const examples = createElement('div', { className: 'form-text', text: 'Examples: pdf, docx, xlsx. Leave the list empty to allow all supported file types.' });
        const footer = createElement('div', { className: 'modal-footer' });
        const saveButton = createElement('button', { className: 'btn btn-primary', text: 'Add File Type', attributes: { type: 'button' } });
        saveButton.addEventListener('click', () => {
            const extension = extensionGroup.input.value.trim().replace(/^\./, '').toLowerCase();
            if (!extension) {
                extensionGroup.input.focus();
                return;
            }
            onSave(extension);
            window.bootstrap.Modal.getOrCreateInstance(modal).hide();
        });
        modal.addEventListener('hidden.bs.modal', () => modal.remove());
        appendChildren(header, [title, closeButton]);
        appendChildren(body, [extensionGroup.wrapper, examples]);
        appendChildren(footer, [createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button', 'data-bs-dismiss': 'modal' } }), saveButton]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modal.appendChild(dialog);
        document.body.appendChild(modal);
        window.bootstrap.Modal.getOrCreateInstance(modal).show();
    };

    const buildExtensionListControl = (extensions = []) => {
        const wrapper = createElement('div');
        const header = createElement('div', { className: 'd-flex align-items-center justify-content-between gap-2 mb-2' });
        const label = createElement('label', { className: 'form-label mb-0', text: 'File type filters' });
        const addButton = createElement('button', { className: 'btn btn-outline-primary btn-sm', text: 'Add File Type', attributes: { type: 'button' } });
        const list = createElement('div', { className: 'd-flex flex-wrap gap-2 border rounded p-2 min-vh-0' });
        const selectedExtensions = Array.from(new Set(extensions.map((extension) => String(extension || '').replace(/^\./, '').toLowerCase()).filter(Boolean)));
        const renderExtensions = () => {
            list.replaceChildren();
            if (selectedExtensions.length === 0) {
                list.appendChild(createElement('span', { className: 'text-muted small', text: 'All supported file types are allowed.' }));
                return;
            }
            selectedExtensions.forEach((extension, index) => {
                const badge = createElement('span', { className: 'badge text-bg-light border d-inline-flex align-items-center gap-1' });
                const removeButton = createElement('button', { className: 'btn-close btn-close-sm', attributes: { type: 'button', 'aria-label': `Remove ${extension}` } });
                removeButton.addEventListener('click', () => {
                    selectedExtensions.splice(index, 1);
                    renderExtensions();
                });
                appendChildren(badge, [createElement('span', { text: `.${extension}` }), removeButton]);
                list.appendChild(badge);
            });
        };
        addButton.addEventListener('click', () => showExtensionEditorModal((extension) => {
            if (!selectedExtensions.includes(extension)) {
                selectedExtensions.push(extension);
                selectedExtensions.sort();
                renderExtensions();
            }
        }));
        appendChildren(header, [label, addButton]);
        appendChildren(wrapper, [header, list]);
        renderExtensions();
        return {
            wrapper,
            getValues: () => selectedExtensions,
        };
    };

    const normalizeSelectedPath = (value) => String(value || '')
        .replace(/\\+/g, '/')
        .replace(/^\/+|\/+$/g, '')
        .split('/')
        .map((part) => part.trim())
        .filter((part) => part && part !== '.' && part !== '..')
        .join('/');

    const showSelectedPathEditorModal = (onSave) => {
        const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true' } });
        const dialog = createElement('div', { className: 'modal-dialog' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', { className: 'modal-title', text: 'Add Folder or File' });
        const closeButton = createElement('button', { className: 'btn-close', attributes: { type: 'button', 'data-bs-dismiss': 'modal', 'aria-label': 'Close' } });
        const body = createElement('div', { className: 'modal-body' });
        const pathGroup = createInput('file-sync-selected-path-value', 'Path below source root', 'text', '', { placeholder: 'Folder/Subfolder or Folder/file.pdf' });
        const help = createElement('div', { className: 'form-text', text: 'Leave the selected-path list empty to sync the configured root.' });
        const footer = createElement('div', { className: 'modal-footer' });
        const saveButton = createElement('button', { className: 'btn btn-primary', text: 'Add', attributes: { type: 'button' } });
        saveButton.addEventListener('click', () => {
            const selectedPath = normalizeSelectedPath(pathGroup.input.value);
            if (!selectedPath) {
                pathGroup.input.focus();
                return;
            }
            onSave(selectedPath);
            window.bootstrap.Modal.getOrCreateInstance(modal).hide();
        });
        modal.addEventListener('hidden.bs.modal', () => modal.remove());
        appendChildren(header, [title, closeButton]);
        appendChildren(body, [pathGroup.wrapper, help]);
        appendChildren(footer, [createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button', 'data-bs-dismiss': 'modal' } }), saveButton]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modal.appendChild(dialog);
        document.body.appendChild(modal);
        window.bootstrap.Modal.getOrCreateInstance(modal).show();
    };

    const buildSelectedPathControl = (selectedValues = [], sourceTypeValue = 'smb', getPayload = () => ({})) => {
        const wrapper = createElement('div');
        const header = createElement('div', { className: 'd-flex align-items-center justify-content-between gap-2 mb-2' });
        const label = createElement('label', { className: 'form-label mb-0', text: 'Selected folders and files' });
        const actions = createElement('div', { className: 'd-flex flex-wrap gap-2' });
        const browseButton = createElement('button', { className: 'btn btn-outline-primary btn-sm', text: 'Browse', attributes: { type: 'button' } });
        const addButton = createElement('button', { className: 'btn btn-outline-secondary btn-sm', text: 'Add Path', attributes: { type: 'button' } });
        const clearButton = createElement('button', { className: 'btn btn-outline-danger btn-sm', text: 'Sync Root', attributes: { type: 'button' } });
        const list = createElement('div', { className: 'list-group list-group-flush border rounded' });
        const selectedPaths = Array.from(new Set((selectedValues || []).map(normalizeSelectedPath).filter(Boolean)));

        const addSelectedPath = (pathValue) => {
            const selectedPath = normalizeSelectedPath(pathValue);
            if (selectedPath && !selectedPaths.includes(selectedPath)) {
                selectedPaths.push(selectedPath);
                selectedPaths.sort();
                renderSelectedPaths();
            }
        };

        const renderSelectedPaths = () => {
            list.replaceChildren();
            if (selectedPaths.length === 0) {
                list.appendChild(createElement('div', { className: 'list-group-item text-muted small', text: 'Syncing the configured source root.' }));
                clearButton.disabled = true;
                return;
            }
            clearButton.disabled = false;
            selectedPaths.forEach((selectedPath, index) => {
                const row = createElement('div', { className: 'list-group-item d-flex align-items-center justify-content-between gap-2' });
                const code = createElement('code', { text: selectedPath });
                const removeButton = createElement('button', { className: 'btn btn-sm btn-outline-danger', text: 'Remove', attributes: { type: 'button' } });
                removeButton.addEventListener('click', () => {
                    selectedPaths.splice(index, 1);
                    renderSelectedPaths();
                });
                appendChildren(row, [code, removeButton]);
                list.appendChild(row);
            });
        };

        const openBrowseModal = () => {
            const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true' } });
            const dialog = createElement('div', { className: 'modal-dialog modal-lg modal-dialog-scrollable' });
            const content = createElement('div', { className: 'modal-content' });
            const header = createElement('div', { className: 'modal-header' });
            const title = createElement('h5', { className: 'modal-title', text: `Browse ${formatSourceType(sourceTypeValue)}` });
            const closeButton = createElement('button', { className: 'btn-close', attributes: { type: 'button', 'data-bs-dismiss': 'modal', 'aria-label': 'Close' } });
            const body = createElement('div', { className: 'modal-body' });
            const status = createElement('div', { className: 'alert d-none', attributes: { role: 'alert' } });
            const navRow = createElement('div', { className: 'd-flex gap-2 mb-3' });
            const pathInput = createElement('input', { className: 'form-control', attributes: { type: 'text', 'aria-label': 'Browse path', placeholder: 'Folder path' } });
            const upButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Up', attributes: { type: 'button' } });
            const loadButton = createElement('button', { className: 'btn btn-outline-primary', text: 'Load', attributes: { type: 'button' } });
            const entriesList = createElement('div', { className: 'list-group' });
            const footer = createElement('div', { className: 'modal-footer' });
            let currentPath = '';

            const setBrowseStatus = (message, type = 'info') => {
                status.textContent = message;
                status.className = `alert alert-${type}`;
            };

            const renderEntries = (entries = []) => {
                entriesList.replaceChildren();
                if (entries.length === 0) {
                    entriesList.appendChild(createElement('div', { className: 'list-group-item text-muted', text: 'No folders or files found.' }));
                    return;
                }
                entries.forEach((entry) => {
                    const row = createElement('div', { className: 'list-group-item d-flex align-items-center justify-content-between gap-2' });
                    const details = createElement('div');
                    const name = createElement('div', { className: 'fw-semibold', text: entry.name || entry.path || '' });
                    const meta = createElement('div', { className: 'small text-muted', text: `${entry.type || 'item'} ${entry.path || ''}`.trim() });
                    const buttons = createElement('div', { className: 'btn-group btn-group-sm' });
                    const selectButton = createElement('button', { className: 'btn btn-outline-primary', text: 'Select', attributes: { type: 'button' } });
                    selectButton.addEventListener('click', () => addSelectedPath(entry.path));
                    buttons.appendChild(selectButton);
                    if (entry.type === 'folder') {
                        const openButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Open', attributes: { type: 'button' } });
                        openButton.addEventListener('click', () => loadPath(entry.path || ''));
                        buttons.appendChild(openButton);
                    }
                    appendChildren(details, [name, meta]);
                    appendChildren(row, [details, buttons]);
                    entriesList.appendChild(row);
                });
            };

            const loadPath = async (pathValue = '') => {
                currentPath = normalizeSelectedPath(pathValue);
                pathInput.value = currentPath;
                try {
                    loadButton.disabled = true;
                    const browseUrl = state.editingSourceId
                        ? `${apiBase}/sources/${state.editingSourceId}/browse`
                        : `${apiBase}/sources/browse`;
                    const browsePayload = { ...(getPayload() || {}), browse_path: currentPath };
                    const payload = await fetchJson(browseUrl, {
                        method: 'POST',
                        body: JSON.stringify(browsePayload),
                    });
                    const browse = payload.browse || {};
                    status.className = 'alert d-none';
                    renderEntries(Array.isArray(browse.entries) ? browse.entries : []);
                } catch (error) {
                    setBrowseStatus(error.message, 'danger');
                    renderEntries([]);
                } finally {
                    loadButton.disabled = false;
                }
            };

            upButton.addEventListener('click', () => {
                const parts = currentPath.split('/').filter(Boolean);
                parts.pop();
                loadPath(parts.join('/'));
            });
            loadButton.addEventListener('click', () => loadPath(pathInput.value));
            modal.addEventListener('shown.bs.modal', () => loadPath(''));
            modal.addEventListener('hidden.bs.modal', () => modal.remove());
            appendChildren(header, [title, closeButton]);
            appendChildren(navRow, [pathInput, upButton, loadButton]);
            appendChildren(body, [status, navRow, entriesList]);
            footer.appendChild(createElement('button', { className: 'btn btn-outline-secondary', text: 'Done', attributes: { type: 'button', 'data-bs-dismiss': 'modal' } }));
            appendChildren(content, [header, body, footer]);
            dialog.appendChild(content);
            modal.appendChild(dialog);
            document.body.appendChild(modal);
            window.bootstrap.Modal.getOrCreateInstance(modal, { backdrop: 'static' }).show();
        };

        addButton.addEventListener('click', () => showSelectedPathEditorModal(addSelectedPath));
        browseButton.addEventListener('click', openBrowseModal);
        clearButton.addEventListener('click', () => {
            selectedPaths.splice(0, selectedPaths.length);
            renderSelectedPaths();
        });

        appendChildren(actions, [browseButton, addButton, clearButton]);
        appendChildren(header, [label, actions]);
        appendChildren(wrapper, [header, list]);
        renderSelectedPaths();
        return {
            wrapper,
            getValues: () => selectedPaths.slice(),
        };
    };

    const sourceToFormValues = (source = {}) => ({
        sourceType: source.source_type || 'smb',
        name: source.name || '',
        enabled: source.enabled !== false,
        recursive: source.recursive !== false && recursiveAllowed,
        uncPath: source.connection?.unc_path || '',
        accountUrl: source.connection?.account_url || source.connection?.share_url || '',
        shareName: source.connection?.share_name || '',
        directoryPath: source.connection?.directory_path || '',
        selectedPaths: source.connection?.selected_paths || [],
        identityId: source.identity_id || '',
        authType: source.credentials?.auth_type || 'username_password',
        username: source.credentials?.username || '',
        domain: source.credentials?.domain || '',
        clientId: source.credentials?.identity || source.credentials?.managed_identity_client_id || '',
        password: '',
        secret: '',
        scheduleEnabled: source.schedule?.enabled === true,
        intervalMinutes: source.schedule?.interval_minutes || 60,
        includePatterns: source.filters?.include_patterns || [],
        excludePatterns: source.filters?.exclude_patterns || [],
        allowedExtensions: source.filters?.allowed_extensions || [],
        fixedTags: source.filters?.fixed_tags || [],
        folderTagMode: source.filters?.folder_tag_mode || 'parent',
        remoteDeletePolicy: source.remote_delete_policy || 'ignore',
    });

    const getFormSource = () => state.sources.find((source) => source.id === state.editingSourceId) || null;

    const getSourceModalElement = () => root.querySelector('[data-file-sync-source-modal]');

    const resetSourceModalState = () => {
        state.editingSourceId = null;
        state.sourceModalStep = 'type';
        state.selectedSourceType = getDefaultSourceTypeValue();
        hideModalStatus();
    };

    const closeSourceModal = () => {
        const modalElement = getSourceModalElement();
        if (!modalElement) {
            resetSourceModalState();
            return;
        }
        if (window.bootstrap?.Modal) {
            const modalInstance = window.bootstrap.Modal.getInstance(modalElement);
            if (modalInstance) {
                modalInstance.hide();
                return;
            }
        }
        modalElement.classList.remove('show', 'd-block');
        modalElement.setAttribute('aria-hidden', 'true');
        resetSourceModalState();
    };

    const renderSourceTypeStep = (content, footer) => {
        const visibleSourceTypes = getVisibleSourceTypes();
        if (!isSourceTypeVisible(state.selectedSourceType)) {
            state.selectedSourceType = getDefaultSourceTypeValue();
        }

        if (visibleSourceTypes.length === 0) {
            content.appendChild(createElement('div', {
                className: 'alert alert-info mb-0',
                text: 'No source types are visible for this workspace. Ask an admin to enable a source type before adding a sync source.',
            }));
        }

        const typeGrid = createElement('div', { className: 'row g-3' });
        visibleSourceTypes.forEach((sourceType) => {
            const column = createElement('div', { className: 'col-md-4' });
            const optionButton = createElement('button', {
                className: `btn w-100 h-100 text-start border rounded p-3 ${state.selectedSourceType === sourceType.value ? 'border-primary bg-primary-subtle' : 'btn-light'}`,
                attributes: {
                    type: 'button',
                    'aria-pressed': String(state.selectedSourceType === sourceType.value),
                },
            });
            optionButton.disabled = !sourceType.enabled;
            const heading = createElement('div', { className: 'fw-semibold mb-1', text: sourceType.label });
            const description = createElement('div', { className: 'small text-muted', text: sourceType.description });
            const badge = createElement('span', {
                className: `badge mt-3 ${sourceType.enabled ? 'text-bg-primary' : 'text-bg-secondary'}`,
                text: sourceType.enabled ? 'Available' : 'Coming soon',
            });
            optionButton.addEventListener('click', () => {
                state.selectedSourceType = sourceType.value;
                renderSourceModal();
            });
            appendChildren(optionButton, [heading, description, badge]);
            column.appendChild(optionButton);
            typeGrid.appendChild(column);
        });

        const cancelButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button' } });
        const nextButton = createElement('button', { className: 'btn btn-primary', text: 'Configure Source', attributes: { type: 'button' } });
        nextButton.disabled = !isSourceTypeSelectable(state.selectedSourceType);
        cancelButton.addEventListener('click', closeSourceModal);
        nextButton.addEventListener('click', () => {
            state.sourceModalStep = 'configure';
            renderSourceModal();
        });

        if (visibleSourceTypes.length > 0) {
            content.appendChild(typeGrid);
        }
        appendChildren(footer, [cancelButton, nextButton]);
    };

    const renderConfigureStep = (content, footer, source) => {
        const values = sourceToFormValues(source || { source_type: state.selectedSourceType });
        state.selectedSourceType = values.sourceType;
        const selectedSourceType = values.sourceType || 'smb';
        if (!getSourceTypeAuthTypes(selectedSourceType).includes(values.authType)) {
            values.authType = getSourceTypeAuthTypes(selectedSourceType)[0];
        }
        let buildPayload = () => ({});
        const typeSummary = createElement('div', { className: 'alert alert-light border py-2 mb-3' });
        const typeLabel = createElement('span', { className: 'fw-semibold me-2', text: 'Source Type' });
        const typeValue = createElement('span', { text: formatSourceType(selectedSourceType) });
        appendChildren(typeSummary, [typeLabel, typeValue]);

        const createConfigCard = (titleText, children) => {
            const card = createElement('div', { className: 'card border-0 shadow-sm mb-3' });
            const body = createElement('div', { className: 'card-body' });
            const title = createElement('h6', { className: 'card-title mb-3', text: titleText });
            appendChildren(body, [title, ...children]);
            card.appendChild(body);
            return card;
        };

        const formGrid = createElement('div', { className: 'row g-3' });
        const nameField = buildLabeledInput('file-sync-source-name', 'Source name', 'text', values.name);
        const uncField = buildLabeledInput('file-sync-unc-path', 'UNC path', 'text', values.uncPath);
        const accountUrlField = buildLabeledInput('file-sync-account-url', 'File service URL', 'url', values.accountUrl);
        const shareNameField = buildLabeledInput('file-sync-share-name', 'Share name', 'text', values.shareName);
        const directoryPathField = buildLabeledInput('file-sync-directory-path', 'Directory path', 'text', values.directoryPath);
        const enabledField = buildCheckbox('file-sync-enabled', 'Enabled', values.enabled);
        const recursiveField = buildCheckbox(
            'file-sync-recursive',
            recursiveAllowed ? 'Include subfolders' : 'Include subfolders (disabled by admin)',
            values.recursive,
        );
        recursiveField.input.disabled = !recursiveAllowed;

        formGrid.appendChild(nameField.wrapper);
        if (selectedSourceType === 'azure_files') {
            appendChildren(formGrid, [accountUrlField.wrapper, shareNameField.wrapper, directoryPathField.wrapper]);
        } else if (selectedSourceType === 'onedrive') {
            const oneDriveSummary = createElement('div', { className: 'col-12 text-muted small', text: 'OneDrive sync uses an admin-managed global connector identity with Microsoft Graph application permissions.' });
            formGrid.appendChild(oneDriveSummary);
        } else {
            formGrid.appendChild(uncField.wrapper);
        }

        const generalSwitches = createElement('div', { className: 'd-flex flex-wrap gap-4 mt-3' });
        appendChildren(generalSwitches, [enabledField.wrapper]);

        const identityWrapper = createElement('div', { className: 'mb-3' });
        const identityHeader = createElement('div', { className: 'd-flex align-items-center justify-content-between gap-2 mb-2' });
        const identityLabel = createElement('label', { className: 'form-label mb-0', text: 'Reusable identity', attributes: { for: 'file-sync-identity' } });
        const identitySelect = createElement('select', { className: 'form-select', attributes: { id: 'file-sync-identity' } });
        identitySelect.appendChild(createElement('option', { text: 'Source-local credentials', attributes: { value: '' } }));
        state.identities
            .filter((identity) => identitySupportsFileSync(identity, selectedSourceType))
            .forEach((identity) => {
                const option = createElement('option', { text: identity.name || 'File Sync Identity', attributes: { value: identity.id } });
                option.selected = identity.id === values.identityId;
                identitySelect.appendChild(option);
            });
        identityHeader.appendChild(identityLabel);
        appendChildren(identityWrapper, [identityHeader, identitySelect]);
        const globalConnectorNotice = createElement('div', {
            className: 'alert alert-info py-2 mb-0',
            text: 'OneDrive uses the admin-managed global File Sync connector identity. Personal users choose what to sync, not tenant credentials.',
        });

        const localCredentialsWrapper = createElement('div', { className: 'row g-3' });
        const authTypeWrapper = createElement('div', { className: 'col-md-6' });
        const authTypeLabel = createElement('label', { className: 'form-label', text: 'Authentication', attributes: { for: 'file-sync-auth-type' } });
        const authTypeSelect = createElement('select', { className: 'form-select', attributes: { id: 'file-sync-auth-type' } });
        getSourceTypeAuthTypes(selectedSourceType).forEach((value) => {
            const option = createElement('option', { text: formatAuthType(value), attributes: { value } });
            option.selected = values.authType === value;
            authTypeSelect.appendChild(option);
        });
        appendChildren(authTypeWrapper, [authTypeLabel, authTypeSelect]);
        const usernameField = buildLabeledInput('file-sync-username', 'Username', 'text', values.username);
        const domainField = buildLabeledInput('file-sync-domain', 'Domain', 'text', values.domain);
        const clientIdField = buildLabeledInput('file-sync-client-id', 'Client ID', 'text', values.clientId);
        const passwordField = buildLabeledInput('file-sync-password', source?.credentials?.password_stored || source?.credentials?.secret_stored ? 'Secret (stored)' : 'Secret', 'password', values.password || values.secret);
        appendChildren(localCredentialsWrapper, [authTypeWrapper, usernameField.wrapper, domainField.wrapper, clientIdField.wrapper, passwordField.wrapper]);

        const updateCredentialVisibility = () => {
            const usingIdentity = Boolean(identitySelect.value);
            localCredentialsWrapper.classList.toggle('d-none', usingIdentity);
            const authType = authTypeSelect.value;
            const usesUsernamePassword = authType === 'username_password';
            const usesClientSecret = authType === 'client_secret';
            const usesSecret = ['client_secret', 'connection_string'].includes(authType);
            usernameField.wrapper.classList.toggle('d-none', !usesUsernamePassword);
            domainField.wrapper.classList.toggle('d-none', !usesUsernamePassword);
            clientIdField.wrapper.classList.toggle('d-none', !usesClientSecret);
            passwordField.wrapper.classList.toggle('d-none', ['anonymous', 'managed_identity', 'global_identity'].includes(authType));
            const passwordLabel = passwordField.wrapper.querySelector('label');
            if (passwordLabel) {
                if (usesUsernamePassword) {
                    passwordLabel.textContent = source?.credentials?.password_stored ? 'Password (stored)' : 'Password';
                } else if (usesClientSecret) {
                    passwordLabel.textContent = source?.credentials?.secret_stored ? 'Client secret (stored)' : 'Client secret';
                } else if (authType === 'connection_string') {
                    passwordLabel.textContent = source?.credentials?.secret_stored ? 'Connection string (stored)' : 'Connection string';
                } else {
                    passwordLabel.textContent = source?.credentials?.secret_stored ? 'Secret (stored)' : 'Secret';
                }
            }
            if (!usesUsernamePassword && !usesSecret) {
                passwordField.input.value = '';
            }
        };
        identitySelect.addEventListener('change', updateCredentialVisibility);
        authTypeSelect.addEventListener('change', updateCredentialVisibility);
        updateCredentialVisibility();

        const selectedPathControl = buildSelectedPathControl(values.selectedPaths, selectedSourceType, () => buildPayload());
        const patternControl = buildPatternListControl(values.includePatterns, values.excludePatterns);
        const extensionControl = buildExtensionListControl(values.allowedExtensions);

        const folderGrid = createElement('div', { className: 'row g-3 mt-2' });
        const folderWrapper = createElement('div', { className: 'col-md-6' });
        const folderLabel = createElement('label', { className: 'form-label', text: 'Folder tags', attributes: { for: 'file-sync-folder-tags' } });
        const folderSelect = createElement('select', { className: 'form-select', attributes: { id: 'file-sync-folder-tags' } });
        [
            ['none', 'None'],
            ['parent', 'Parent folder'],
            ['full_path', 'Full path'],
        ].forEach(([value, text]) => {
            const option = createElement('option', { text, attributes: { value } });
            option.selected = values.folderTagMode === value;
            folderSelect.appendChild(option);
        });
        appendChildren(folderWrapper, [folderLabel, folderSelect]);

        const deleteWrapper = createElement('div', { className: 'col-md-6' });
        const deleteLabel = createElement('label', { className: 'form-label', text: 'Remote delete policy', attributes: { for: 'file-sync-delete-policy' } });
        const deleteSelect = createElement('select', { className: 'form-select', attributes: { id: 'file-sync-delete-policy' } });
        [
            ['ignore', 'Keep SimpleChat copy'],
            ['hard_delete', 'Delete SimpleChat copy'],
        ].forEach(([value, text]) => {
            const option = createElement('option', { text, attributes: { value } });
            option.selected = values.remoteDeletePolicy === value;
            deleteSelect.appendChild(option);
        });
        appendChildren(deleteWrapper, [deleteLabel, deleteSelect]);

        appendChildren(folderGrid, [folderWrapper, deleteWrapper]);
        const tagsField = buildFixedTagSelector(values.fixedTags);

        const scheduleField = buildCheckbox('file-sync-schedule-enabled', 'Scheduled sync', values.scheduleEnabled);
        const intervalField = buildIntervalControl('file-sync-interval', 'Schedule interval minutes', values.intervalMinutes);
        intervalField.wrapper.classList.remove('col-md-6');
        intervalField.wrapper.classList.toggle('d-none', !scheduleField.input.checked);
        scheduleField.input.addEventListener('change', () => {
            intervalField.wrapper.classList.toggle('d-none', !scheduleField.input.checked);
        });

        appendChildren(content, [
            typeSummary,
            createConfigCard('General', [formGrid, generalSwitches]),
            createConfigCard('Identity and Authentication', selectedSourceType === 'onedrive' ? [globalConnectorNotice] : [identityWrapper, localCredentialsWrapper]),
            createConfigCard('Selection, Subfolders, and Filters', [recursiveField.wrapper, selectedPathControl.wrapper, patternControl.wrapper, extensionControl.wrapper, folderGrid]),
            createConfigCard('Tags', [tagsField.wrapper]),
            createConfigCard('Sync Schedule', [scheduleField.wrapper, intervalField.wrapper]),
        ]);

        buildPayload = () => {
            const credentials = {
                auth_type: authTypeSelect.value,
                username: usernameField.input.value.trim(),
                domain: domainField.input.value.trim(),
                password: passwordField.input.value,
                secret: passwordField.input.value,
                client_secret: passwordField.input.value,
                connection_string: passwordField.input.value,
                identity: clientIdField.input.value.trim(),
                client_id: clientIdField.input.value.trim(),
            };
            if (authTypeSelect.value === 'managed_identity') {
                credentials.password = '';
                credentials.secret = '';
                credentials.client_secret = '';
                credentials.connection_string = '';
            }
            if (selectedSourceType === 'onedrive') {
                credentials.auth_type = 'global_identity';
                credentials.password = '';
                credentials.secret = '';
                credentials.client_secret = '';
                credentials.connection_string = '';
            }
            const selectedPaths = selectedPathControl.getValues();
            const connection = selectedSourceType === 'azure_files'
                ? {
                    account_url: accountUrlField.input.value.trim(),
                    share_name: shareNameField.input.value.trim(),
                    directory_path: directoryPathField.input.value.trim(),
                    selected_paths: selectedPaths,
                }
                : selectedSourceType === 'onedrive'
                    ? {
                        selected_paths: selectedPaths,
                    }
                    : {
                        unc_path: uncField.input.value.trim(),
                        selected_paths: selectedPaths,
                    };
            return {
                name: nameField.input.value.trim(),
                source_type: selectedSourceType,
                enabled: enabledField.input.checked,
                recursive: recursiveAllowed && recursiveField.input.checked,
                identity_id: selectedSourceType === 'onedrive' ? '' : identitySelect.value,
                connection,
                credentials,
                filters: {
                    include_patterns: patternControl.getValues().includePatterns,
                    exclude_patterns: patternControl.getValues().excludePatterns,
                    allowed_extensions: extensionControl.getValues(),
                    fixed_tags: tagsField.getValues(),
                    folder_tag_mode: folderSelect.value,
                },
                schedule: {
                    enabled: scheduleField.input.checked,
                    interval_minutes: Number.parseInt(intervalField.input.value, 10) || 60,
                },
                remote_delete_policy: deleteSelect.value,
            };
        };

        if (!source) {
            const backButton = createElement('button', { className: 'btn btn-outline-secondary me-auto', text: 'Back', attributes: { type: 'button' } });
            backButton.addEventListener('click', () => {
                state.sourceModalStep = 'type';
                renderSourceModal();
            });
            footer.appendChild(backButton);
        }

        const testButton = createElement('button', { className: 'btn btn-outline-primary', text: 'Test Connection', attributes: { type: 'button' } });
        const cancelButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button' } });
        const saveButton = createElement('button', { className: 'btn btn-primary', text: source ? 'Save Source' : 'Add Source', attributes: { type: 'button' } });
        cancelButton.addEventListener('click', closeSourceModal);

        testButton.addEventListener('click', async () => {
            try {
                testButton.disabled = true;
                const testUrl = state.editingSourceId
                    ? `${apiBase}/sources/${state.editingSourceId}/test-connection`
                    : `${apiBase}/sources/test-connection`;
                const payload = await fetchJson(testUrl, {
                    method: 'POST',
                    body: JSON.stringify(buildPayload()),
                });
                const connection = payload.connection || {};
                showModalStatus(`Connection OK. Checked ${connection.entries_checked || 0} top-level item(s).`, 'success');
            } catch (error) {
                showModalStatus(error.message, 'danger');
            } finally {
                testButton.disabled = false;
            }
        });

        saveButton.addEventListener('click', async (event) => {
            event.preventDefault();
            const payload = buildPayload();

            try {
                saveButton.disabled = true;
                if (state.editingSourceId) {
                    await fetchJson(`${apiBase}/sources/${state.editingSourceId}`, {
                        method: 'PATCH',
                        body: JSON.stringify(payload),
                    });
                    showStatus('Source saved.', 'success');
                } else {
                    await fetchJson(`${apiBase}/sources`, {
                        method: 'POST',
                        body: JSON.stringify(payload),
                    });
                    showStatus('Source added.', 'success');
                }
                closeSourceModal();
                await loadSources();
            } catch (error) {
                showModalStatus(error.message, 'danger');
            } finally {
                saveButton.disabled = false;
            }
        });

        appendChildren(footer, [testButton, cancelButton, saveButton]);
    };

    const renderSourceModal = () => {
        const modalElement = getSourceModalElement();
        if (!modalElement) {
            return;
        }
        const source = getFormSource();
        const title = modalElement.querySelector('[data-file-sync-source-modal-title]');
        const steps = modalElement.querySelector('[data-file-sync-source-modal-steps]');
        const content = modalElement.querySelector('[data-file-sync-source-modal-content]');
        const footer = modalElement.querySelector('[data-file-sync-source-modal-footer]');
        title.textContent = source ? `Edit ${formatSourceType(source.source_type || 'smb')} Source` : 'Add Sync Source';
        steps.replaceChildren();
        content.replaceChildren();
        footer.replaceChildren();
        hideModalStatus();

        const stepGroup = createElement('div', { className: 'btn-group w-100 mb-3', attributes: { role: 'group', 'aria-label': 'File Sync source steps' } });
        [
            ['type', '1. Source Type'],
            ['configure', '2. Configure'],
        ].forEach(([stepValue, stepLabel]) => {
            const stepButton = createElement('button', {
                className: `btn ${state.sourceModalStep === stepValue ? 'btn-primary' : 'btn-outline-primary'}`,
                text: stepLabel,
                attributes: {
                    type: 'button',
                    'aria-pressed': String(state.sourceModalStep === stepValue),
                },
            });
            stepButton.disabled = stepValue === 'configure' && !isSourceTypeSelectable(state.selectedSourceType);
            stepButton.addEventListener('click', () => {
                if (stepValue === 'configure' && !isSourceTypeSelectable(state.selectedSourceType)) {
                    return;
                }
                state.sourceModalStep = stepValue;
                renderSourceModal();
            });
            stepGroup.appendChild(stepButton);
        });
        steps.appendChild(stepGroup);

        if (state.sourceModalStep === 'configure') {
            renderConfigureStep(content, footer, source);
            return;
        }
        renderSourceTypeStep(content, footer);
    };

    const openSourceModal = async (sourceId = null) => {
        state.editingSourceId = sourceId;
        const source = getFormSource();
        state.selectedSourceType = source?.source_type || getDefaultSourceTypeValue();
        state.sourceModalStep = source ? 'configure' : 'type';
        await loadAvailableTags();
        await loadIdentities();
        renderSourceModal();
        const modalElement = getSourceModalElement();
        if (!modalElement) {
            return;
        }
        if (window.bootstrap?.Modal) {
            window.bootstrap.Modal.getOrCreateInstance(modalElement, { backdrop: 'static' }).show();
            return;
        }
        modalElement.classList.add('show', 'd-block');
        modalElement.removeAttribute('aria-hidden');
    };

    const openIdentitiesModal = async () => {
        await loadIdentities(true);
        const modal = createElement('div', { className: 'modal fade', attributes: { tabindex: '-1', 'aria-hidden': 'true' } });
        const dialog = createElement('div', { className: 'modal-dialog modal-xl modal-dialog-scrollable' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', { className: 'modal-title', text: 'Workspace Identities' });
        const closeButton = createElement('button', { className: 'btn-close', attributes: { type: 'button', 'data-bs-dismiss': 'modal', 'aria-label': 'Close' } });
        const body = createElement('div', { className: 'modal-body' });
        const status = createElement('div', { className: 'alert d-none', attributes: { role: 'alert' } });
        const formCard = createElement('div', { className: 'card border-0 shadow-sm mb-3' });
        const formBody = createElement('div', { className: 'card-body' });
        const formTitle = createElement('h6', { className: 'card-title', text: 'Add Identity' });
        const formGrid = createElement('div', { className: 'row g-3' });
        const nameField = buildLabeledInput('file-sync-identity-name', 'Identity name', 'text', '');
        const descriptionField = buildLabeledInput('file-sync-identity-description', 'Description', 'text', '');
        const authWrapper = createElement('div', { className: 'col-md-6' });
        const authLabel = createElement('label', { className: 'form-label', text: 'Authentication', attributes: { for: 'file-sync-identity-auth-type' } });
        const authSelect = createElement('select', { className: 'form-select', attributes: { id: 'file-sync-identity-auth-type' } });
        [
            ['username_password', 'Username and password', false],
            ['anonymous', 'Anonymous', false],
            ['managed_identity', 'Managed identity', false],
        ].forEach(([value, text, disabled]) => {
            const option = createElement('option', { text, attributes: { value } });
            option.disabled = disabled;
            authSelect.appendChild(option);
        });
        appendChildren(authWrapper, [authLabel, authSelect]);
        const usernameField = buildLabeledInput('file-sync-identity-username', 'Username', 'text', '');
        const domainField = buildLabeledInput('file-sync-identity-domain', 'Domain', 'text', '');
        const passwordField = buildLabeledInput('file-sync-identity-password', 'Password', 'password', '');
        const formActions = createElement('div', { className: 'd-flex gap-2 mt-3' });
        const saveButton = createElement('button', { className: 'btn btn-success', text: 'Add Identity', attributes: { type: 'button' } });
        const clearButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Clear', attributes: { type: 'button' } });
        const tableWrap = createElement('div', { className: 'table-responsive' });
        const table = createElement('table', { className: 'table table-sm align-middle mb-0' });
        const editing = { id: null };

        const setIdentityStatus = (message, type = 'info') => {
            status.textContent = message;
            status.className = `alert alert-${type}`;
        };
        const clearIdentityStatus = () => {
            status.textContent = '';
            status.className = 'alert d-none';
        };
        const resetForm = () => {
            editing.id = null;
            formTitle.textContent = 'Add Identity';
            saveButton.textContent = 'Add Identity';
            nameField.input.value = '';
            descriptionField.input.value = '';
            authSelect.value = 'username_password';
            usernameField.input.value = '';
            domainField.input.value = '';
            passwordField.input.value = '';
            passwordField.wrapper.querySelector('label').textContent = 'Password';
            clearIdentityStatus();
            updateIdentityCredentialVisibility();
        };
        const renderIdentityTable = () => {
            table.replaceChildren();
            const thead = createElement('thead');
            const headRow = createElement('tr');
            ['Name', 'Type', 'Authentication', 'Username', 'Updated', ''].forEach((heading) => {
                headRow.appendChild(createElement('th', { text: heading }));
            });
            thead.appendChild(headRow);
            const tbody = createElement('tbody');
            if (state.identities.length === 0) {
                const row = createElement('tr');
                const cell = createElement('td', { className: 'text-muted', text: 'No reusable identities yet.', attributes: { colspan: '6' } });
                row.appendChild(cell);
                tbody.appendChild(row);
            } else {
                state.identities.forEach((identity) => {
                    const row = createElement('tr');
                    const credentials = identity.credentials || {};
                    const actions = createElement('td', { className: 'text-end text-nowrap' });
                    const editButton = createElement('button', { className: 'btn btn-sm btn-outline-primary me-2', text: 'Edit', attributes: { type: 'button' } });
                    const deleteButton = createElement('button', { className: 'btn btn-sm btn-outline-danger', text: 'Delete', attributes: { type: 'button' } });
                    editButton.addEventListener('click', () => {
                        editing.id = identity.id;
                        formTitle.textContent = 'Edit Identity';
                        saveButton.textContent = 'Save Identity';
                        nameField.input.value = identity.name || '';
                        descriptionField.input.value = identity.description || '';
                        authSelect.value = credentials.auth_type || 'username_password';
                        usernameField.input.value = credentials.username || '';
                        domainField.input.value = credentials.domain || '';
                        passwordField.input.value = '';
                        passwordField.wrapper.querySelector('label').textContent = credentials.password_stored ? 'Password (stored)' : 'Password';
                        updateIdentityCredentialVisibility();
                        clearIdentityStatus();
                    });
                    deleteButton.addEventListener('click', async () => {
                        try {
                            deleteButton.disabled = true;
                            await fetchJson(`${identityApiBase}/identities/${identity.id}`, { method: 'DELETE' });
                            await loadIdentities(true);
                            renderIdentityTable();
                            resetForm();
                            setIdentityStatus('Identity deleted.', 'success');
                        } catch (error) {
                            setIdentityStatus(error.message, 'danger');
                        } finally {
                            deleteButton.disabled = false;
                        }
                    });
                    appendChildren(actions, [editButton, deleteButton]);
                    appendChildren(row, [
                        createElement('td', { text: identity.name || '' }),
                        createElement('td', { text: formatSourceType(identity.source_type || 'smb') }),
                        createElement('td', { text: formatAuthType(credentials.auth_type || 'username_password') }),
                        createElement('td', { text: credentials.username || '' }),
                        createElement('td', { text: formatDate(identity.updated_at) }),
                        actions,
                    ]);
                    tbody.appendChild(row);
                });
            }
            appendChildren(table, [thead, tbody]);
        };
        const updateIdentityCredentialVisibility = () => {
            const noSecretAuth = authSelect.value === 'anonymous' || authSelect.value === 'managed_identity';
            usernameField.wrapper.classList.toggle('d-none', noSecretAuth);
            domainField.wrapper.classList.toggle('d-none', noSecretAuth);
            passwordField.wrapper.classList.toggle('d-none', noSecretAuth);
        };

        authSelect.addEventListener('change', updateIdentityCredentialVisibility);
        clearButton.addEventListener('click', resetForm);
        saveButton.addEventListener('click', async () => {
            const payload = {
                name: nameField.input.value.trim(),
                description: descriptionField.input.value.trim(),
                provider: 'smb',
                source_type: 'smb',
                usage_contexts: ['file_sync'],
                supported_source_types: ['smb', 'azure_files'],
                credentials: {
                    auth_type: authSelect.value,
                    username: usernameField.input.value.trim(),
                    domain: domainField.input.value.trim(),
                    password: passwordField.input.value,
                },
            };
            try {
                saveButton.disabled = true;
                const url = editing.id ? `${identityApiBase}/identities/${editing.id}` : `${identityApiBase}/identities`;
                await fetchJson(url, {
                    method: editing.id ? 'PATCH' : 'POST',
                    body: JSON.stringify(payload),
                });
                await loadIdentities(true);
                renderIdentityTable();
                resetForm();
                setIdentityStatus('Identity saved.', 'success');
            } catch (error) {
                setIdentityStatus(error.message, 'danger');
            } finally {
                saveButton.disabled = false;
            }
        });

        appendChildren(formGrid, [nameField.wrapper, descriptionField.wrapper, authWrapper, usernameField.wrapper, domainField.wrapper, passwordField.wrapper]);
        appendChildren(formActions, [saveButton, clearButton]);
        appendChildren(formBody, [formTitle, formGrid, formActions]);
        formCard.appendChild(formBody);
        tableWrap.appendChild(table);
        appendChildren(body, [status, formCard, tableWrap]);
        appendChildren(header, [title, closeButton]);
        const footer = createElement('div', { className: 'modal-footer' });
        footer.appendChild(createElement('button', { className: 'btn btn-outline-secondary', text: 'Close', attributes: { type: 'button', 'data-bs-dismiss': 'modal' } }));
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modal.appendChild(dialog);
        modal.addEventListener('hidden.bs.modal', () => modal.remove());
        document.body.appendChild(modal);
        renderIdentityTable();
        updateIdentityCredentialVisibility();
        window.bootstrap.Modal.getOrCreateInstance(modal, { backdrop: 'static' }).show();
    };

    const formatDate = (value) => {
        if (!value) {
            return '';
        }
        const date = new Date(value);
        if (Number.isNaN(date.getTime())) {
            return value;
        }
        return date.toLocaleString();
    };

    const getSourceConnectionLabel = (source = {}) => {
        const connection = source.connection || {};
        const selectedPaths = Array.isArray(connection.selected_paths) ? connection.selected_paths : [];
        const selectedPathLabel = selectedPaths.length > 0 ? ` (${selectedPaths.length} selected)` : '';
        if ((source.source_type || 'smb') === 'onedrive') {
            return `OneDrive${selectedPathLabel}`;
        }
        if ((source.source_type || 'smb') === 'azure_files') {
            const baseLabel = connection.share_url || [connection.account_url, connection.share_name, connection.directory_path]
                .filter(Boolean)
                .join('/');
            return `${baseLabel}${selectedPathLabel}`;
        }
        return `${connection.unc_path || ''}${selectedPathLabel}`;
    };

    const formatCounts = (counts = {}) => [
        `queued ${counts.queued || 0}`,
        `created ${counts.created || 0}`,
        `updated ${counts.updated || 0}`,
        `unchanged ${counts.unchanged || 0}`,
        `skipped ${counts.skipped || 0}`,
        `failed ${counts.failed || 0}`,
    ].join(', ');

    const showDeleteSourceModal = (source) => new Promise((resolve) => {
        const modalId = `file-sync-delete-source-${source.id || 'source'}`;
        const modalElement = createElement('div', {
            className: 'modal fade',
            attributes: {
                id: modalId,
                tabindex: '-1',
                'aria-labelledby': `${modalId}-title`,
                'aria-hidden': 'true',
            },
        });
        const dialog = createElement('div', { className: 'modal-dialog modal-dialog-centered' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', {
            className: 'modal-title',
            text: 'Delete File Sync Source',
            attributes: { id: `${modalId}-title` },
        });
        const closeButton = createElement('button', {
            className: 'btn-close',
            attributes: {
                type: 'button',
                'aria-label': 'Close',
            },
        });
        const body = createElement('div', { className: 'modal-body' });
        const sourceName = createElement('p', { className: 'fw-semibold mb-1', text: source.name || 'File Sync Source' });
        const sourcePath = createElement('p', { className: 'text-muted small mb-3', text: getSourceConnectionLabel(source) });
        const promptText = createElement('p', { className: 'mb-2', text: 'Choose what should happen to documents already synced from this source.' });
        const keepText = createElement('p', { className: 'small mb-1', text: 'Delete sync source keeps the documents in SimpleChat.' });
        const deleteText = createElement('p', { className: 'small text-danger mb-0', text: 'Delete all files removes the synced documents and then deletes the source.' });
        const footer = createElement('div', { className: 'modal-footer' });
        const cancelButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button' } });
        const sourceOnlyButton = createElement('button', { className: 'btn btn-outline-danger', text: 'Delete Sync Source', attributes: { type: 'button' } });
        const deleteAllButton = createElement('button', { className: 'btn btn-danger', text: 'Delete All Files', attributes: { type: 'button' } });
        let selectedAction = null;
        let modalInstance = null;
        let resolved = false;

        const finish = (action) => {
            selectedAction = action;
            if (modalInstance) {
                modalInstance.hide();
                return;
            }
            if (!resolved) {
                resolved = true;
                modalElement.remove();
                resolve(selectedAction);
            }
        };

        modalElement.addEventListener('hidden.bs.modal', () => {
            if (!resolved) {
                resolved = true;
                modalElement.remove();
                resolve(selectedAction);
            }
        }, { once: true });

        closeButton.addEventListener('click', () => finish(null));
        cancelButton.addEventListener('click', () => finish(null));
        sourceOnlyButton.addEventListener('click', () => finish('source_only'));
        deleteAllButton.addEventListener('click', () => finish('delete_all_files'));

        appendChildren(header, [title, closeButton]);
        appendChildren(body, [sourceName, sourcePath, promptText, keepText, deleteText]);
        appendChildren(footer, [cancelButton, sourceOnlyButton, deleteAllButton]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modalElement.appendChild(dialog);
        document.body.appendChild(modalElement);

        if (window.bootstrap?.Modal) {
            modalInstance = new window.bootstrap.Modal(modalElement, { backdrop: 'static' });
            modalInstance.show();
            return;
        }
        modalElement.classList.add('show');
        modalElement.removeAttribute('aria-hidden');
    });

    const renderSources = () => {
        const tableBody = root.querySelector('[data-file-sync-source-rows]');
        tableBody.replaceChildren();

        if (state.sources.length === 0) {
            const row = createElement('tr');
            const cell = createElement('td', { className: 'text-muted', text: 'No sync sources configured.', attributes: { colspan: '7' } });
            row.appendChild(cell);
            tableBody.appendChild(row);
            return;
        }

        state.sources.forEach((source) => {
            const row = createElement('tr');
            const nameCell = createElement('td');
            const nameText = createElement('div', { className: 'fw-semibold', text: source.name || 'File Sync Source' });
            const pathText = createElement('div', { className: 'small text-muted', text: getSourceConnectionLabel(source) });
            const recursionText = createElement('div', { className: 'small text-muted', text: source.recursive === false ? 'Top folder only' : 'Includes subfolders' });
            appendChildren(nameCell, [nameText, pathText, recursionText]);

            const statusText = source.enabled ? 'Enabled' : 'Disabled';
            const typeCell = createElement('td');
            typeCell.appendChild(createElement('span', { className: 'badge text-bg-light border', text: formatSourceType(source.source_type || 'smb') }));
            const statusCell = createElement('td', { text: statusText });
            const scheduleCell = createElement('td', { text: source.schedule?.enabled ? `${source.schedule.interval_minutes || ''} min` : 'Manual' });
            const lastRunCell = createElement('td');
            appendChildren(lastRunCell, [
                createElement('div', { text: source.last_run_status || '' }),
                createElement('div', { className: 'small text-muted', text: formatDate(source.last_run_at) }),
            ]);

            const countsCell = createElement('td', { className: 'small', text: formatCounts(source.last_run_counts || {}) });
            const actionsCell = createElement('td');
            const actionGroup = createElement('div', { className: 'btn-group btn-group-sm', attributes: { role: 'group' } });
            const syncButton = createElement('button', { className: 'btn btn-outline-primary', text: 'Sync', attributes: { type: 'button' } });
            const historyButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'History', attributes: { type: 'button' } });
            const editButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Edit', attributes: { type: 'button' } });
            const deleteButton = createElement('button', { className: 'btn btn-outline-danger', text: 'Delete', attributes: { type: 'button' } });

            syncButton.addEventListener('click', async () => {
                try {
                    syncButton.disabled = true;
                    await fetchJson(`${apiBase}/sources/${source.id}/sync`, { method: 'POST', body: JSON.stringify({}) });
                    showStatus('Sync run queued.', 'success');
                    await loadSources();
                } catch (error) {
                    showStatus(error.message, 'danger');
                } finally {
                    syncButton.disabled = false;
                }
            });

            historyButton.addEventListener('click', async () => {
                state.historySourceId = source.id;
                await loadHistory(source.id);
            });

            editButton.addEventListener('click', async () => {
                await openSourceModal(source.id);
            });

            deleteButton.addEventListener('click', async () => {
                const deleteChoice = await showDeleteSourceModal(source);
                if (!deleteChoice) {
                    return;
                }
                try {
                    deleteButton.disabled = true;
                    const payload = {
                        delete_associated_files: deleteChoice === 'delete_all_files',
                    };
                    const result = await fetchJson(`${apiBase}/sources/${source.id}`, {
                        method: 'DELETE',
                        body: JSON.stringify(payload),
                    });
                    const deleteResult = result.delete_result || {};
                    const deletedDocuments = deleteResult.documents_deleted || 0;
                    showStatus(
                        payload.delete_associated_files
                            ? `Source deleted with ${deletedDocuments} associated file(s).`
                            : 'Source deleted. Associated files were kept.',
                        'success',
                    );
                    await loadSources();
                } catch (error) {
                    showStatus(error.message, 'danger');
                } finally {
                    deleteButton.disabled = false;
                }
            });

            appendChildren(actionGroup, [syncButton, historyButton, editButton, deleteButton]);
            actionsCell.appendChild(actionGroup);
            appendChildren(row, [nameCell, typeCell, statusCell, scheduleCell, lastRunCell, countsCell, actionsCell]);
            tableBody.appendChild(row);
        });
    };

    const renderHistory = (runs = []) => {
        const history = root.querySelector('[data-file-sync-history]');
        history.replaceChildren();
        if (!state.historySourceId) {
            return;
        }

        const title = createElement('h6', { className: 'mt-4 mb-2', text: 'Sync History' });
        const table = createElement('table', { className: 'table table-sm align-middle' });
        const head = createElement('thead');
        const headRow = createElement('tr');
        ['Status', 'Trigger', 'Started', 'Completed', 'Counts'].forEach((headerText) => {
            headRow.appendChild(createElement('th', { text: headerText }));
        });
        head.appendChild(headRow);
        const body = createElement('tbody');

        if (runs.length === 0) {
            const row = createElement('tr');
            row.appendChild(createElement('td', { className: 'text-muted', text: 'No runs yet.', attributes: { colspan: '5' } }));
            body.appendChild(row);
        } else {
            runs.forEach((run) => {
                const row = createElement('tr');
                appendChildren(row, [
                    createElement('td', { text: run.status || '' }),
                    createElement('td', { text: run.trigger || '' }),
                    createElement('td', { text: formatDate(run.started_at) }),
                    createElement('td', { text: formatDate(run.completed_at) }),
                    createElement('td', { className: 'small', text: formatCounts(run.counts || {}) }),
                ]);
                body.appendChild(row);
            });
        }

        appendChildren(table, [head, body]);
        appendChildren(history, [title, table]);
    };

    const loadHistory = async (sourceId) => {
        try {
            const payload = await fetchJson(`${apiBase}/sources/${sourceId}/runs`);
            renderHistory(payload.runs || []);
        } catch (error) {
            showStatus(error.message, 'danger');
        }
    };

    const loadSources = async () => {
        try {
            hideStatus();
            const payload = await fetchJson(`${apiBase}/sources`);
            state.sources = payload.sources || [];
            renderSources();
            if (state.historySourceId) {
                await loadHistory(state.historySourceId);
            }
        } catch (error) {
            showStatus(error.message, 'danger');
        }
    };

    const buildSourceModal = () => {
        const modalId = `file-sync-source-modal-${Math.random().toString(36).slice(2, 10)}`;
        const modalElement = createElement('div', {
            className: 'modal fade',
            attributes: {
                id: modalId,
                tabindex: '-1',
                'aria-labelledby': `${modalId}-title`,
                'aria-hidden': 'true',
                'data-file-sync-source-modal': 'true',
            },
        });
        const dialog = createElement('div', { className: 'modal-dialog modal-xl modal-dialog-scrollable' });
        const content = createElement('div', { className: 'modal-content' });
        const header = createElement('div', { className: 'modal-header' });
        const title = createElement('h5', {
            className: 'modal-title',
            text: 'Add Sync Source',
            attributes: {
                id: `${modalId}-title`,
                'data-file-sync-source-modal-title': 'true',
            },
        });
        const closeButton = createElement('button', {
            className: 'btn-close',
            attributes: {
                type: 'button',
                'aria-label': 'Close',
                'data-bs-dismiss': 'modal',
            },
        });
        const body = createElement('div', { className: 'modal-body' });
        const status = createElement('div', { className: 'alert alert-info py-2 mb-3 d-none', attributes: { 'data-file-sync-modal-status': 'true' } });
        const steps = createElement('div', { attributes: { 'data-file-sync-source-modal-steps': 'true' } });
        const modalContent = createElement('div', { attributes: { 'data-file-sync-source-modal-content': 'true' } });
        const footer = createElement('div', { className: 'modal-footer', attributes: { 'data-file-sync-source-modal-footer': 'true' } });

        closeButton.addEventListener('click', closeSourceModal);
        modalElement.addEventListener('hidden.bs.modal', resetSourceModalState);
        appendChildren(header, [title, closeButton]);
        appendChildren(body, [status, steps, modalContent]);
        appendChildren(content, [header, body, footer]);
        dialog.appendChild(content);
        modalElement.appendChild(dialog);
        return modalElement;
    };

    const renderLayout = () => {
        root.replaceChildren();
        const toolbar = createElement('div', { className: 'd-flex flex-wrap gap-2 justify-content-start align-items-center mb-3' });
        const addButton = createElement('button', { className: 'btn btn-success btn-sm', text: 'Add Source', attributes: { type: 'button' } });
        toolbar.appendChild(addButton);

        const status = createElement('div', { className: 'alert alert-info py-2 mb-3 d-none', attributes: { 'data-file-sync-status': 'true' } });
        const tableWrapper = createElement('div', { className: 'table-responsive' });
        const table = createElement('table', { className: 'table table-striped align-middle' });
        const head = createElement('thead');
        const headRow = createElement('tr');
        ['Source', 'Type', 'Status', 'Schedule', 'Last run', 'Counts', 'Actions'].forEach((headerText) => {
            headRow.appendChild(createElement('th', { text: headerText }));
        });
        head.appendChild(headRow);
        const body = createElement('tbody', { attributes: { 'data-file-sync-source-rows': 'true' } });
        appendChildren(table, [head, body]);
        tableWrapper.appendChild(table);
        const history = createElement('div', { attributes: { 'data-file-sync-history': 'true' } });
        const sourceModal = buildSourceModal();

        addButton.addEventListener('click', async () => {
            await openSourceModal();
        });

        appendChildren(root, [toolbar, status, tableWrapper, history, sourceModal]);
    };

    renderLayout();
    loadAvailableTags();
    loadIdentities();
    loadSources();
    const autoRefreshInterval = window.setInterval(() => {
        if (!root.isConnected) {
            window.clearInterval(autoRefreshInterval);
            return;
        }
        if (!document.hidden) {
            loadSources();
        }
    }, 30000);
}

window.initializeFileSyncRoot = initializeFileSyncRoot;
document.querySelectorAll('#file-sync-root, [data-file-sync-root]').forEach((root) => {
    initializeFileSyncRoot(root);
});