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
    };

    const apiBase = root.dataset.apiBase;
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
        parseList(root.dataset.visibleSourceTypes === undefined ? 'smb' : root.dataset.visibleSourceTypes)
            .map((sourceTypeValue) => sourceTypeValue.toLowerCase())
            .filter((sourceTypeValue) => sourceTypes.some((sourceType) => sourceType.value === sourceTypeValue)),
    );
    const isSourceTypeVisible = (sourceTypeValue) => visibleSourceTypeValues.has(sourceTypeValue);
    const isSourceTypeSelectable = (sourceTypeValue) => isSourceTypeVisible(sourceTypeValue) && isSourceTypeEnabled(sourceTypeValue);
    const getVisibleSourceTypes = () => sourceTypes.filter((sourceType) => isSourceTypeVisible(sourceType.value));
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

    const buildTagSelector = (id, labelText, selectedValues = []) => {
        const wrapper = createElement('div', { className: 'col-md-6' });
        const label = createElement('label', { className: 'form-label', text: labelText, attributes: { for: id } });
        const selectedTags = new Set(parseList(Array.isArray(selectedValues) ? selectedValues.join(',') : selectedValues).map(normalizeTagName).filter(Boolean));
        const chipContainer = createElement('div', { className: 'd-flex flex-wrap gap-2 mb-2' });
        const inputGroup = createElement('div', { className: 'input-group' });
        const input = createElement('input', {
            className: 'form-control',
            attributes: {
                id,
                type: 'text',
                placeholder: 'Add tag',
            },
        });
        const addButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Add', attributes: { type: 'button' } });

        const renderChips = () => {
            chipContainer.replaceChildren();
            if (selectedTags.size === 0) {
                chipContainer.appendChild(createElement('span', { className: 'text-muted small', text: 'No fixed tags selected.' }));
                return;
            }
            selectedTags.forEach((tagName) => {
                const chip = createElement('span', { className: 'badge text-bg-light border d-inline-flex align-items-center gap-1' });
                const text = createElement('span', { text: tagName });
                const removeButton = createElement('button', {
                    className: 'btn-close btn-close-sm',
                    attributes: {
                        type: 'button',
                        'aria-label': `Remove ${tagName}`,
                    },
                });
                removeButton.addEventListener('click', () => {
                    selectedTags.delete(tagName);
                    renderChips();
                });
                appendChildren(chip, [text, removeButton]);
                chipContainer.appendChild(chip);
            });
        };

        const addTags = (rawValue) => {
            parseList(rawValue).map(normalizeTagName).filter(Boolean).forEach((tagName) => selectedTags.add(tagName));
            input.value = '';
            renderChips();
        };

        addButton.addEventListener('click', () => addTags(input.value));
        input.addEventListener('keydown', (event) => {
            if (event.key === 'Enter') {
                event.preventDefault();
                addTags(input.value);
            }
        });
        appendChildren(inputGroup, [input, addButton]);
        appendChildren(wrapper, [label, chipContainer, inputGroup]);

        const availableTagNames = state.availableTags
            .map((tag) => normalizeTagName(tag.name || tag))
            .filter(Boolean)
            .filter((tagName, index, allTags) => allTags.indexOf(tagName) === index)
            .sort();
        if (availableTagNames.length > 0) {
            const select = createElement('select', { className: 'form-select mb-2', attributes: { 'aria-label': 'Choose existing tag' } });
            select.appendChild(createElement('option', { text: 'Choose existing tag', attributes: { value: '' } }));
            availableTagNames.forEach((tagName) => {
                select.appendChild(createElement('option', { text: tagName, attributes: { value: tagName } }));
            });
            select.addEventListener('change', () => {
                if (select.value) {
                    selectedTags.add(select.value);
                    select.value = '';
                    renderChips();
                }
            });
            wrapper.insertBefore(select, inputGroup);
        }

        renderChips();
        return {
            wrapper,
            getValues: () => Array.from(selectedTags),
        };
    };

    const sourceToFormValues = (source = {}) => ({
        sourceType: source.source_type || 'smb',
        name: source.name || '',
        enabled: source.enabled !== false,
        recursive: source.recursive !== false && recursiveAllowed,
        uncPath: source.connection?.unc_path || '',
        username: source.credentials?.username || '',
        domain: source.credentials?.domain || '',
        password: '',
        scheduleEnabled: source.schedule?.enabled === true,
        intervalMinutes: source.schedule?.interval_minutes || 60,
        includePatterns: (source.filters?.include_patterns || []).join('\n'),
        excludePatterns: (source.filters?.exclude_patterns || []).join('\n'),
        allowedExtensions: (source.filters?.allowed_extensions || []).join(', '),
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
        const typeSummary = createElement('div', { className: 'alert alert-light border py-2 mb-3' });
        const typeLabel = createElement('span', { className: 'fw-semibold me-2', text: 'Source Type' });
        const typeValue = createElement('span', { text: formatSourceType(selectedSourceType) });
        appendChildren(typeSummary, [typeLabel, typeValue]);

        const row = createElement('div', { className: 'row g-3' });
        const nameField = buildLabeledInput('file-sync-source-name', 'Source name', 'text', values.name);
        const uncField = buildLabeledInput('file-sync-unc-path', 'UNC path', 'text', values.uncPath);
        const usernameField = buildLabeledInput('file-sync-username', 'Username', 'text', values.username);
        const domainField = buildLabeledInput('file-sync-domain', 'Domain', 'text', values.domain);
        const passwordField = buildLabeledInput('file-sync-password', source?.credentials?.password_stored ? 'Password (stored)' : 'Password', 'password', values.password);
        const intervalField = buildIntervalControl('file-sync-interval', 'Schedule interval minutes', values.intervalMinutes);
        const includeField = buildLabeledTextarea('file-sync-include-patterns', 'Include patterns', values.includePatterns);
        const excludeField = buildLabeledTextarea('file-sync-exclude-patterns', 'Exclude patterns', values.excludePatterns);
        const extensionsField = buildLabeledInput('file-sync-extensions', 'File type filters', 'text', values.allowedExtensions);
        const tagsField = buildTagSelector('file-sync-tags', 'Fixed tags', values.fixedTags);
        const enabledField = buildCheckbox('file-sync-enabled', 'Enabled', values.enabled);
        const scheduleField = buildCheckbox('file-sync-schedule-enabled', 'Scheduled sync', values.scheduleEnabled);
        const recursiveField = buildCheckbox(
            'file-sync-recursive',
            recursiveAllowed ? 'Include subfolders' : 'Include subfolders (disabled by admin)',
            values.recursive,
        );
        recursiveField.input.disabled = !recursiveAllowed;

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

        appendChildren(row, [
            nameField.wrapper,
            uncField.wrapper,
            usernameField.wrapper,
            domainField.wrapper,
            passwordField.wrapper,
            intervalField.wrapper,
            includeField.wrapper,
            excludeField.wrapper,
            extensionsField.wrapper,
            tagsField.wrapper,
            folderWrapper,
            deleteWrapper,
        ]);

        const switches = createElement('div', { className: 'd-flex flex-wrap gap-4 mt-3' });
        appendChildren(switches, [enabledField.wrapper, scheduleField.wrapper, recursiveField.wrapper]);
        appendChildren(content, [typeSummary, row, switches]);

        const buildPayload = () => ({
            name: nameField.input.value.trim(),
            source_type: selectedSourceType,
            enabled: enabledField.input.checked,
            recursive: recursiveAllowed && recursiveField.input.checked,
            connection: {
                unc_path: uncField.input.value.trim(),
            },
            credentials: {
                auth_type: 'username_password',
                username: usernameField.input.value.trim(),
                domain: domainField.input.value.trim(),
                password: passwordField.input.value,
            },
            filters: {
                include_patterns: parseList(includeField.textarea.value),
                exclude_patterns: parseList(excludeField.textarea.value),
                allowed_extensions: parseList(extensionsField.input.value),
                fixed_tags: tagsField.getValues(),
                folder_tag_mode: folderSelect.value,
            },
            schedule: {
                enabled: scheduleField.input.checked,
                interval_minutes: Number.parseInt(intervalField.input.value, 10) || 60,
            },
            remote_delete_policy: deleteSelect.value,
        });

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

    const formatCounts = (counts = {}) => [
        `queued ${counts.queued || 0}`,
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
        const sourceName = createElement('p', { className: 'fw-semibold mb-1', text: source.name || 'SMB Source' });
        const sourcePath = createElement('p', { className: 'text-muted small mb-3', text: source.connection?.unc_path || '' });
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
            const nameText = createElement('div', { className: 'fw-semibold', text: source.name || 'SMB Source' });
            const pathText = createElement('div', { className: 'small text-muted', text: source.connection?.unc_path || '' });
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
        const toolbar = createElement('div', { className: 'd-flex flex-wrap gap-2 justify-content-between align-items-center mb-3' });
        const title = createElement('h5', { className: 'mb-0', text: 'Sync Sources' });
        const actions = createElement('div', { className: 'd-flex gap-2' });
        const addButton = createElement('button', { className: 'btn btn-primary btn-sm', text: 'Add Source', attributes: { type: 'button' } });
        const refreshButton = createElement('button', { className: 'btn btn-outline-secondary btn-sm', text: 'Refresh', attributes: { type: 'button' } });
        appendChildren(actions, [addButton, refreshButton]);
        appendChildren(toolbar, [title, actions]);

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
        refreshButton.addEventListener('click', loadSources);

        appendChildren(root, [toolbar, status, tableWrapper, history, sourceModal]);
    };

    renderLayout();
    loadAvailableTags();
    loadSources();
}

window.initializeFileSyncRoot = initializeFileSyncRoot;
document.querySelectorAll('#file-sync-root, [data-file-sync-root]').forEach((root) => {
    initializeFileSyncRoot(root);
});