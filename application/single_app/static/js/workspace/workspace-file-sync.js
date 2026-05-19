// workspace-file-sync.js

const root = document.getElementById('file-sync-root');

if (root) {
    const state = {
        sources: [],
        editingSourceId: null,
        historySourceId: null,
    };

    const apiBase = root.dataset.apiBase;

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

    const parseList = (value) => value
        .split(/[\n,;]+/)
        .map((item) => item.trim())
        .filter((item, index, allItems) => item && allItems.indexOf(item) === index);

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

    const sourceToFormValues = (source = {}) => ({
        name: source.name || '',
        enabled: source.enabled !== false,
        uncPath: source.connection?.unc_path || '',
        username: source.credentials?.username || '',
        domain: source.credentials?.domain || '',
        password: '',
        scheduleEnabled: source.schedule?.enabled === true,
        intervalMinutes: source.schedule?.interval_minutes || 60,
        includePatterns: (source.filters?.include_patterns || []).join('\n'),
        excludePatterns: (source.filters?.exclude_patterns || []).join('\n'),
        allowedExtensions: (source.filters?.allowed_extensions || []).join(', '),
        fixedTags: (source.filters?.fixed_tags || []).join(', '),
        folderTagMode: source.filters?.folder_tag_mode || 'parent',
        remoteDeletePolicy: source.remote_delete_policy || 'ignore',
    });

    const getFormSource = () => state.sources.find((source) => source.id === state.editingSourceId) || null;

    const renderForm = () => {
        const formContainer = root.querySelector('[data-file-sync-form]');
        formContainer.replaceChildren();
        const source = getFormSource();
        const values = sourceToFormValues(source || {});

        const form = createElement('form', { className: 'border rounded p-3 mb-3' });
        form.noValidate = true;

        const title = createElement('h6', { className: 'mb-3', text: source ? 'Edit SMB Source' : 'Add SMB Source' });
        const row = createElement('div', { className: 'row g-3' });

        const nameField = buildLabeledInput('file-sync-source-name', 'Source name', 'text', values.name);
        const uncField = buildLabeledInput('file-sync-unc-path', 'UNC path', 'text', values.uncPath);
        const usernameField = buildLabeledInput('file-sync-username', 'Username', 'text', values.username);
        const domainField = buildLabeledInput('file-sync-domain', 'Domain', 'text', values.domain);
        const passwordField = buildLabeledInput('file-sync-password', source?.credentials?.password_stored ? 'Password (stored)' : 'Password', 'password', values.password);
        const intervalField = buildLabeledInput('file-sync-interval', 'Schedule interval minutes', 'number', String(values.intervalMinutes));
        intervalField.input.min = '5';
        const includeField = buildLabeledTextarea('file-sync-include-patterns', 'Include patterns', values.includePatterns);
        const excludeField = buildLabeledTextarea('file-sync-exclude-patterns', 'Exclude patterns', values.excludePatterns);
        const extensionsField = buildLabeledInput('file-sync-extensions', 'File type filters', 'text', values.allowedExtensions);
        const tagsField = buildLabeledInput('file-sync-tags', 'Tags', 'text', values.fixedTags);
        const enabledField = buildCheckbox('file-sync-enabled', 'Enabled', values.enabled);
        const scheduleField = buildCheckbox('file-sync-schedule-enabled', 'Scheduled sync', values.scheduleEnabled);

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
        appendChildren(switches, [enabledField.wrapper, scheduleField.wrapper]);

        const actions = createElement('div', { className: 'd-flex gap-2 justify-content-end mt-3' });
        const cancelButton = createElement('button', { className: 'btn btn-outline-secondary', text: 'Cancel', attributes: { type: 'button' } });
        const saveButton = createElement('button', { className: 'btn btn-primary', text: source ? 'Save Source' : 'Add Source', attributes: { type: 'submit' } });
        appendChildren(actions, [cancelButton, saveButton]);

        cancelButton.addEventListener('click', () => {
            state.editingSourceId = null;
            formContainer.classList.add('d-none');
        });

        form.addEventListener('submit', async (event) => {
            event.preventDefault();
            const payload = {
                name: nameField.input.value.trim(),
                source_type: 'smb',
                enabled: enabledField.input.checked,
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
                    fixed_tags: parseList(tagsField.input.value),
                    folder_tag_mode: folderSelect.value,
                },
                schedule: {
                    enabled: scheduleField.input.checked,
                    interval_minutes: Number.parseInt(intervalField.input.value, 10) || 60,
                },
                remote_delete_policy: deleteSelect.value,
            };

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
                state.editingSourceId = null;
                formContainer.classList.add('d-none');
                await loadSources();
            } catch (error) {
                showStatus(error.message, 'danger');
            } finally {
                saveButton.disabled = false;
            }
        });

        appendChildren(form, [title, row, switches, actions]);
        formContainer.appendChild(form);
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

    const renderSources = () => {
        const tableBody = root.querySelector('[data-file-sync-source-rows]');
        tableBody.replaceChildren();

        if (state.sources.length === 0) {
            const row = createElement('tr');
            const cell = createElement('td', { className: 'text-muted', text: 'No sync sources configured.', attributes: { colspan: '6' } });
            row.appendChild(cell);
            tableBody.appendChild(row);
            return;
        }

        state.sources.forEach((source) => {
            const row = createElement('tr');
            const nameCell = createElement('td');
            const nameText = createElement('div', { className: 'fw-semibold', text: source.name || 'SMB Source' });
            const pathText = createElement('div', { className: 'small text-muted', text: source.connection?.unc_path || '' });
            appendChildren(nameCell, [nameText, pathText]);

            const statusText = source.enabled ? 'Enabled' : 'Disabled';
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

            editButton.addEventListener('click', () => {
                state.editingSourceId = source.id;
                const formContainer = root.querySelector('[data-file-sync-form]');
                renderForm();
                formContainer.classList.remove('d-none');
            });

            deleteButton.addEventListener('click', async () => {
                if (deleteButton.dataset.confirm !== 'true') {
                    deleteButton.dataset.confirm = 'true';
                    deleteButton.textContent = 'Confirm';
                    return;
                }
                try {
                    await fetchJson(`${apiBase}/sources/${source.id}`, { method: 'DELETE' });
                    showStatus('Source deleted.', 'success');
                    await loadSources();
                } catch (error) {
                    showStatus(error.message, 'danger');
                }
            });

            appendChildren(actionGroup, [syncButton, historyButton, editButton, deleteButton]);
            actionsCell.appendChild(actionGroup);
            appendChildren(row, [nameCell, statusCell, scheduleCell, lastRunCell, countsCell, actionsCell]);
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
        const formContainer = createElement('div', { className: 'd-none', attributes: { 'data-file-sync-form': 'true' } });
        const table = createElement('table', { className: 'table table-striped align-middle' });
        const head = createElement('thead');
        const headRow = createElement('tr');
        ['Source', 'Status', 'Schedule', 'Last run', 'Counts', 'Actions'].forEach((headerText) => {
            headRow.appendChild(createElement('th', { text: headerText }));
        });
        head.appendChild(headRow);
        const body = createElement('tbody', { attributes: { 'data-file-sync-source-rows': 'true' } });
        appendChildren(table, [head, body]);
        const history = createElement('div', { attributes: { 'data-file-sync-history': 'true' } });

        addButton.addEventListener('click', () => {
            state.editingSourceId = null;
            renderForm();
            formContainer.classList.toggle('d-none');
        });
        refreshButton.addEventListener('click', loadSources);

        appendChildren(root, [toolbar, status, formContainer, table, history]);
    };

    renderLayout();
    loadSources();
}