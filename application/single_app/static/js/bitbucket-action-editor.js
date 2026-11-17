// bitbucket-action-editor.js
export class BitbucketActionEditor {
    constructor(stepper) {
        this.stepper = stepper;
        this.root = document.getElementById('bitbucket-config-section');
        this.selected = [];
        this.options = [];
        this.cursor = null;
        this.value('edition').addEventListener('change', () => {
            if (this.value('edition').value === 'cloud') this.value('endpoint').value = 'https://api.bitbucket.org';
            this.refresh();
        });
        this.value('method').addEventListener('change', () => {
            this.value('credential').value = '';
            this.value('username').value = '';
            this.value('identity').value = '';
            this.refresh();
        });
        this.value('source').addEventListener('change', () => this.refresh());
        this.value('discover').addEventListener('click', () => this.discover(0));
        this.value('more').addEventListener('click', () => this.discover(this.cursor));
    }

    value(name) {
        return document.getElementById(`bitbucket-${name}`);
    }

    reference() {
        const action = this.stepper.originalPlugin;
        if (!action?.id) return '';
        const scope = this.stepper.actionIdentityScope.scope;
        if (scope === 'global') return `global:global:${action.id}`;
        if (scope === 'group') return action.group_id ? `group:${action.group_id}:${action.id}` : '';
        return `personal:self:${action.id}`;
    }

    populate(action = {}) {
        const fields = action.additionalFields || {};
        this.selected = structuredClone(fields.repositories || []);
        this.options = [];
        this.cursor = null;
        this.value('edition').value = fields.edition || 'data_center';
        this.value('endpoint').value = action.endpoint || '';
        this.value('method').value = fields.auth_method || 'oauth';
        this.value('source').value = action.credential_requirements?.slots?.service ? 'personal' : action.identity_id ? 'identity' : 'shared';
        this.savedIdentity = action.identity_id || '';
        this.value('username').value = action.auth?.identity || '';
        this.value('credential').value = action.auth?.key || '';
        this.value('project').value = '';
        this.value('status').textContent = '';
        this.refresh();
    }

    refresh() {
        const cloud = this.value('edition').value === 'cloud';
        const method = this.value('method').value;
        const oauth = method === 'oauth';
        this.value('email-option').disabled = !cloud;
        this.value('endpoint').disabled = cloud;
        this.value('source-group').classList.toggle('d-none', oauth);
        const personal = !oauth && this.value('source').value === 'personal';
        const identity = !oauth && this.value('source').value === 'identity';
        this.value('identity-group').classList.toggle('d-none', !identity);
        this.value('username-group').classList.toggle('d-none', personal || identity || method === 'bearer_token');
        this.value('credential-group').classList.toggle('d-none', personal || identity);
        this.value('username-label').textContent = oauth ? 'OAuth client ID' : 'Atlassian email';
        this.value('credential-label').textContent = oauth ? 'OAuth client secret' : 'Read-only token';
        this.value('connect').classList.toggle('d-none', !oauth || !this.reference());
        this.value('connect').href = `/bitbucket/connect?action_ref=${encodeURIComponent(this.reference())}`;
        this.value('discover').disabled = !this.reference() || personal;
        this.value('more').classList.toggle('d-none', this.cursor === null);
        const select = this.value('identity');
        const current = select.value || this.savedIdentity;
        select.replaceChildren(new Option('Choose a compatible saved identity', ''));
        const identities = this.stepper.actionIdentities.filter((item) => item.auth_type === method);
        for (const item of identities) select.add(new Option(item.name, item.id));
        if (current && !identities.some((item) => item.id === current)) select.add(new Option('Unavailable identity — kept as is', current));
        select.value = current;
        this.renderRepositories();
    }

    async discover(cursor) {
        this.value('discover').disabled = true;
        this.value('more').disabled = true;
        try {
            const reference = this.reference();
            const statusResponse = await fetch(`/api/bitbucket/connection?action_ref=${encodeURIComponent(reference)}`);
            const status = await statusResponse.json();
            if (!statusResponse.ok) throw new Error(status.error || 'Cannot check Bitbucket connection.');
            const response = await fetch('/api/bitbucket/discover', {
                method: 'POST', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': status.csrf_token },
                body: JSON.stringify({ action_ref: reference, project: this.value('project').value.trim(), cursor }),
            });
            const result = await response.json();
            if (!response.ok) throw new Error(result.error || 'Repository discovery failed.');
            this.options = cursor ? [...this.options, ...result.repositories] : result.repositories;
            this.cursor = result.next_cursor;
            this.value('status').textContent = this.options.length
                ? 'Select permitted repositories, then save again to apply changes.' : 'No repositories found.';
            this.renderRepositories();
        } catch (error) {
            this.value('status').textContent = error.message;
        } finally {
            this.value('discover').disabled = !this.reference();
            this.value('more').disabled = false;
            this.value('more').classList.toggle('d-none', this.cursor === null);
        }
    }

    renderRepositories() {
        const options = this.value('options');
        options.replaceChildren();
        for (const repo of this.options) {
            const label = document.createElement('label');
            label.className = 'form-check mb-2';
            const input = document.createElement('input');
            input.className = 'form-check-input';
            input.type = 'checkbox';
            input.checked = this.selected.some((item) => item.id === repo.id);
            input.addEventListener('change', () => {
                this.selected = input.checked ? [...this.selected, { ...repo }] : this.selected.filter((item) => item.id !== repo.id);
                this.renderRepositories();
            });
            label.append(input, document.createTextNode(`${repo.name} (${repo.project}/${repo.slug})`));
            options.append(label);
        }
        const selected = this.value('repositories');
        selected.replaceChildren();
        for (const [index, repo] of this.selected.entries()) {
            const fieldset = document.createElement('fieldset');
            fieldset.className = 'border rounded p-3 mb-3';
            const legend = document.createElement('legend');
            legend.className = 'fs-6';
            legend.textContent = `${repo.name || repo.slug} (${repo.project}/${repo.slug})`;
            const modeLabel = document.createElement('label');
            modeLabel.className = 'form-label';
            modeLabel.htmlFor = `bitbucket-repo-mode-${index}`;
            modeLabel.textContent = 'Allowed branches';
            const mode = document.createElement('select');
            mode.id = modeLabel.htmlFor;
            mode.className = 'form-select mb-2';
            mode.add(new Option('Any branch', 'any'));
            mode.add(new Option('One fixed branch', 'fixed'));
            mode.value = repo.branch_mode;
            mode.addEventListener('change', () => {
                repo.branch_mode = mode.value;
                this.renderRepositories();
            });
            const branchLabel = document.createElement('label');
            branchLabel.className = 'form-label';
            branchLabel.htmlFor = `bitbucket-repo-default-${index}`;
            branchLabel.textContent = repo.branch_mode === 'fixed' ? 'Fixed branch (required)' : "Default branch (blank uses Bitbucket's default)";
            const branch = document.createElement('input');
            branch.id = branchLabel.htmlFor;
            branch.className = 'form-control mb-2';
            branch.value = repo.default_branch;
            branch.addEventListener('input', () => { repo.default_branch = branch.value; });
            const remove = document.createElement('button');
            remove.type = 'button';
            remove.className = 'btn btn-outline-secondary btn-sm';
            remove.textContent = 'Remove repository';
            remove.addEventListener('click', () => {
                this.selected = this.selected.filter((item) => item.id !== repo.id);
                this.renderRepositories();
            });
            fieldset.append(legend, modeLabel, mode, branchLabel, branch, remove);
            selected.append(fieldset);
        }
    }

    collect() {
        const method = this.value('method').value;
        const source = this.value('source').value;
        const personal = method !== 'oauth' && source === 'personal';
        const identity = method !== 'oauth' && source === 'identity' ? this.value('identity').value : '';
        if (method !== 'oauth' && source === 'identity' && !identity) throw new Error('Choose a compatible saved Bitbucket identity.');
        return {
            endpoint: this.value('endpoint').value.trim(),
            auth: {
                type: identity ? 'identity' : method === 'oauth' ? 'user' : method === 'bearer_token' ? 'key' : 'username_password',
                identity: personal ? '' : identity || this.value('username').value.trim(),
                key: personal || identity ? '' : this.value('credential').value,
            },
            identity_id: identity,
            credential_requirements: personal ? { version: 1, slots: { service: { source: 'personal', auth_type: method } } } : undefined,
            additionalFields: {
                edition: this.value('edition').value, auth_method: method, repositories: structuredClone(this.selected),
            },
        };
    }
}
