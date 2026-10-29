// workspace-m365-workflows.js

export function createMicrosoft365RunAsControl(anchor, getScope) {
    if (!anchor) {
        return null;
    }
    const wrapper = document.createElement('div');
    wrapper.className = 'mt-3';
    const label = document.createElement('label');
    label.className = 'form-label';
    label.htmlFor = 'workflow-m365-run-as';
    label.textContent = 'Microsoft 365 Run as';
    const select = document.createElement('select');
    select.id = 'workflow-m365-run-as';
    select.className = 'form-select';
    select.setAttribute('aria-describedby', 'workflow-m365-run-as-help');
    const help = document.createElement('div');
    help.id = 'workflow-m365-run-as-help';
    help.className = 'form-text';
    help.textContent = 'Microsoft 365 actions use this account for manual and scheduled runs. '
        + 'The selected person must connect Microsoft 365 and approve this workflow. '
        + 'Changes to instructions, capabilities, or destinations require approval again.';
    const status = document.createElement('div');
    status.className = 'alert alert-warning mt-2 d-none';
    status.setAttribute('role', 'status');
    wrapper.append(label, select, help, status);
    anchor.parentElement.appendChild(wrapper);

    function reset() {
        select.replaceChildren(new Option('No Microsoft 365 account selected', ''));
        status.classList.add('d-none');
        status.textContent = '';
    }
    reset();

    return {
        reset,
        getValue: () => select.value,
        getLabel: () => select.selectedOptions[0]?.textContent || 'Not selected',
        async load(workflow = null) {
            reset();
            const scope = getScope();
            const query = new URLSearchParams({ scope: scope.scope });
            if (scope.groupId) {
                query.set('group_id', scope.groupId);
            }
            select.disabled = true;
            try {
                const response = await fetch(`/api/workflows/m365-run-as-users?${query}`, {
                    credentials: 'same-origin',
                });
                if (!response.ok) {
                    throw new Error('Unable to load eligible Microsoft 365 accounts.');
                }
                const payload = await response.json();
                for (const user of payload.users || []) {
                    select.appendChild(new Option(user.display_name || user.id, user.id));
                }
                const savedId = workflow?.m365_run_as_user_id || '';
                if (savedId && !Array.from(select.options).some(option => option.value === savedId)) {
                    select.appendChild(new Option('Previously selected account (review required)', savedId));
                }
                select.value = savedId;
            } catch (error) {
                status.textContent = error.message;
                status.classList.remove('d-none');
                if (workflow?.m365_run_as_user_id) {
                    select.appendChild(new Option(
                        'Saved account (unable to verify)',
                        workflow.m365_run_as_user_id,
                    ));
                    select.value = workflow.m365_run_as_user_id;
                }
            } finally {
                select.disabled = false;
            }
        },
    };
}
