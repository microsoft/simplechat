// control-center-usage.js
// Content-free reporting; only the server calculates totals.

const root = document.getElementById('runtimeUsagePanel');
const usageKeys = ['usage_kind', 'usage_entity_id', 'usage_scope_type', 'usage_scope_id',
    'usage_host', 'usage_auth', 'usage_operation', 'usage_outcome'];

function node(tag, text, className = '') {
    const element = document.createElement(tag);
    if (text !== undefined) element.textContent = text;
    if (className) element.className = className;
    return element;
}

function button(text, handler) {
    const element = node('button', text, 'btn btn-outline-secondary btn-sm');
    element.type = 'button';
    element.addEventListener('click', handler);
    return element;
}

if (root) {
    const details = node('details', undefined, 'border rounded p-3');
    details.append(node('summary', 'Agent, action & workflow usage', 'fw-semibold'));
    details.append(node('p', 'Recorded completed attempts, including retries. Uses these usage filters, not log search or token filters. No prompts, inputs, outputs or credentials.', 'small mt-3'));
    const form = node('form', undefined, 'row g-2 align-items-end mb-3');
    const controls = {};
    const initial = new URLSearchParams(window.location.search);
    const end = new Date();
    const start = new Date(end);
    start.setUTCDate(start.getUTCDate() - 29);
    const fields = [
        ['start_date', 'Start date (UTC)', start.toISOString().slice(0, 10), 'date'],
        ['end_date', 'End date (UTC)', end.toISOString().slice(0, 10), 'date'],
        ['usage_kind', 'Entity kind', '', ['agent', 'action', 'workflow']],
        ['usage_outcome', 'Outcome', '', ['succeeded', 'failed', 'cancelled', 'timeout', 'partial', 'unknown']],
        ['usage_entity_id', 'Entity ID', '', 'text'],
        ['usage_scope_type', 'Configuration scope', '', ['personal', 'group', 'global', 'public', 'unknown']],
        ['usage_scope_id', 'Configuration scope ID', '', 'text'],
        ['usage_host', 'Configured host', '', 'text'],
        ['usage_auth', 'Authentication category', '', 'text'],
        ['usage_operation', 'Operation', '', 'text'],
        ['user_id', 'Executing user ID', '', 'text'],
        ['workspace_type', 'Execution workspace', '', ['personal', 'group', 'public']],
        ['workspace_id', 'Execution workspace ID', '', 'text'],
    ];
    for (const [key, title, fallback, type] of fields) {
        const wrapper = node('div', undefined, 'col-12 col-sm-6 col-xl-3');
        const label = node('label', title, 'form-label small');
        label.htmlFor = `usage-${key}`;
        const control = node(Array.isArray(type) ? 'select' : 'input', undefined,
            Array.isArray(type) ? 'form-select form-select-sm' : 'form-control form-control-sm');
        control.id = `usage-${key}`;
        control.name = key;
        if (Array.isArray(type)) {
            const all = node('option', 'All');
            all.value = '';
            control.append(all);
            for (const option of type) {
                const item = node('option', option);
                item.value = option;
                control.append(item);
            }
        } else {
            control.type = type;
            control.maxLength = 256;
        }
        control.value = initial.get(key) || fallback;
        controls[key] = control;
        wrapper.append(label, control);
        form.append(wrapper);
    }
    const actions = node('div', undefined, 'col-12 d-flex flex-wrap gap-2');
    const apply = button('Apply usage filters', () => form.requestSubmit());
    const clear = button('Clear usage filters', () => {
        for (const key of usageKeys) controls[key].value = '';
        document.dispatchEvent(new CustomEvent('runtime-usage-filter', { detail: {} }));
        load();
    });
    const reload = button('Reload usage', () => load());
    const exportLink = node('a', 'Export usage CSV', 'btn btn-outline-success btn-sm');
    actions.append(apply, clear, reload, exportLink);
    form.append(actions);
    const status = node('p', '', 'small');
    status.setAttribute('role', 'status');
    const content = node('div');
    details.append(form, status, content);
    root.append(details);
    let controller;
    let loaded = false;
    let report;
    let page = 0;
    let applied = '';

    function params() {
        const query = new URLSearchParams();
        for (const [key, control] of Object.entries(controls)) {
            if (control.value.trim()) query.set(key, control.value.trim());
        }
        return query;
    }

    function drill(entity) {
        const query = new URLSearchParams(applied);
        for (const [key, field] of [
            ['usage_kind', 'kind'], ['usage_entity_id', 'entity_id'], ['usage_scope_type', 'scope_type'],
            ['usage_scope_id', 'scope_id'], ['usage_host', 'endpoint_host'],
            ['usage_auth', 'auth_type'], ['usage_operation', 'operation'],
        ]) query.set(key, entity[field]);
        query.set('usage_view', 'true');
        document.dispatchEvent(new CustomEvent('runtime-usage-filter', { detail: Object.fromEntries(query) }));
        const logTable = document.getElementById('activityLogsTable');
        logTable?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
        status.textContent = 'The activity log now shows matching usage events. Clear usage filters to restore all activity.';
    }

    function render() {
        content.replaceChildren();
        const totals = node('dl', undefined, 'd-flex flex-wrap gap-4 small');
        for (const [kind, total] of Object.entries(report.totals)) {
            const item = node('div');
            item.append(node('dt', `${kind} attempts`),
                node('dd', `${total.invocations.toLocaleString()} · ${total.unique_users.toLocaleString()} distinct users`),
                node('dd', Object.entries(total.outcomes).map(([outcome, count]) => `${outcome}: ${count}`).join(' · ') || 'No outcomes'));
            totals.append(item);
        }
        content.append(totals, node('p', 'Missing historical metadata is unknown, not zero or no authentication. Nested durations overlap.', 'small'));
        if (!report.entities.length) {
            content.append(node('p', 'No recorded usage matches these filters.'));
            return;
        }
        const wrapper = node('div', undefined, 'table-responsive');
        const table = node('table', undefined, 'table table-sm align-middle runtime-usage-table');
        table.append(node('caption', 'Ranked recorded runtime usage'));
        const header = node('tr');
        for (const text of ['Entity', 'Host / authentication', 'Operation', 'Attempts / users', 'Outcomes', 'Average duration', 'Coverage', 'Events']) {
            const cell = node('th', text);
            cell.scope = 'col';
            header.append(cell);
        }
        const head = node('thead');
        head.append(header);
        const body = node('tbody');
        for (const entity of report.entities.slice(page * 20, (page + 1) * 20)) {
            const row = node('tr');
            for (const value of [
                `${entity.name} (${entity.kind}, ${entity.scope_type}: ${entity.scope_id || 'unknown'}) · ${entity.entity_id}`,
                `${entity.endpoint_host} / ${entity.auth_type}`, entity.operation,
                `${entity.invocations} / ${entity.unique_users}`,
                Object.entries(entity.outcomes).map(([key, count]) => `${key}: ${count}`).join(', '),
                entity.average_duration_ms === null ? 'Unknown' : `${entity.average_duration_ms} ms`,
                `${entity.duration_count} timed; ${entity.legacy_records} legacy`,
            ]) row.append(node('td', String(value), 'text-break'));
            const cell = node('td');
            cell.append(button('View events', () => drill(entity)));
            row.append(cell);
            body.append(row);
        }
        table.append(head, body);
        wrapper.append(table);
        const paging = node('div', undefined, 'd-flex align-items-center gap-3');
        const previous = button('Previous entities', () => { page -= 1; render(); });
        const next = button('Next entities', () => { page += 1; render(); });
        previous.disabled = page === 0;
        next.disabled = (page + 1) * 20 >= report.entities.length;
        paging.append(previous, node('span', `Page ${page + 1} of ${Math.ceil(report.entities.length / 20)}`), next);
        content.append(wrapper, paging);
    }

    async function load() {
        controller?.abort();
        const request = new AbortController();
        controller = request;
        status.className = 'small';
        status.textContent = 'Loading usage...';
        content.replaceChildren();
        exportLink.removeAttribute('href');
        const query = params();
        const queryString = query.toString();
        try {
            const response = await fetch(`/api/admin/control-center/activity-logs/usage?${queryString}&refresh=true`, { signal: request.signal });
            const result = await response.json();
            if (!response.ok || !result.complete) throw new Error(result.error || 'Unable to load complete usage. Narrow the date range.');
            if (request.signal.aborted) return;
            report = result;
            applied = queryString;
            exportLink.href = `/api/admin/control-center/activity-logs/usage?${queryString}&format=csv`;
            page = 0;
            loaded = true;
            status.textContent = `Updated ${new Date(result.recorded_at).toLocaleString()}.`;
            render();
        } catch (error) {
            if (!request.signal.aborted) {
                status.className = 'alert alert-danger small';
                status.textContent = error.message || 'Unable to load usage. Retry.';
            }
        }
    }
    form.addEventListener('submit', (event) => {
        event.preventDefault();
        load();
    });
    details.addEventListener('toggle', () => { if (details.open && !loaded) load(); });
}
