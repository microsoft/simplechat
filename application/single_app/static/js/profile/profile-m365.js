// profile-m365.js
(() => {
    'use strict';

    function initialize() {
        const root = document.getElementById('m365-profile-settings');
        const api = window.SimpleChatM365Approvals;
        if (!root) {
            return;
        }
        if (!api) {
            document.getElementById('m365-preferences-status').textContent = 'Microsoft 365 controls are unavailable. Reload before changing permissions.';
            return;
        }
        let connection = null;
        let bindingContinuation = null;
        let revocation = null;
        let revocationBusy = false;
        let revocationTrigger = null;
        const revokeElement = document.getElementById('m365RevokeModal');
        document.body.appendChild(revokeElement);

        function showStatus(id, text, type = 'info') {
            const element = document.getElementById(id);
            element.className = `alert alert-${type}`;
            element.textContent = text;
            element.classList.remove('d-none');
        }

        function applyPreferences(preferences) {
            const fields = document.getElementById('m365-preferences-fields');
            fields.disabled = true;
            root.querySelectorAll('[data-m365-sharing]').forEach(select => {
                const value = preferences.sources?.[select.dataset.m365Sharing];
                if (!['ask', 'request', 'today', 'always'].includes(value)) {
                    throw new Error('The server returned an unsupported sharing preference. No changes have been made.');
                }
                select.value = value;
            });
            root.querySelectorAll('[data-m365-analysis]').forEach(select => {
                const value = preferences.extended_analysis?.[select.dataset.m365Analysis];
                if (!['ask', 'always', 'fast'].includes(value)) {
                    throw new Error('The server returned an unsupported analysis preference. No changes have been made.');
                }
                select.value = value;
            });
            document.getElementById('m365-profile-timezone').textContent = Intl.DateTimeFormat().resolvedOptions().timeZone || 'Unavailable; confirm when approving sharing.';
            fields.disabled = false;
        }

        async function loadPreferences() {
            document.getElementById('m365-preferences-fields').disabled = true;
            try {
                const response = await api.requestJson('/api/m365/preferences');
                applyPreferences(response.preferences);
                showStatus('m365-preferences-status', 'Preferences loaded. Sharing decisions remain subject to each source action\'s policy.');
            } catch (error) {
                showStatus('m365-preferences-status', error.message, 'danger');
            }
        }

        async function savePreferences(event) {
            event.preventDefault();
            const button = document.getElementById('m365-preferences-save');
            button.disabled = true;
            try {
                const changes = { sources: {}, extended_analysis: {} };
                root.querySelectorAll('[data-m365-sharing]').forEach(select => {
                    changes.sources[select.dataset.m365Sharing] = select.value;
                });
                root.querySelectorAll('[data-m365-analysis]').forEach(select => {
                    changes.extended_analysis[select.dataset.m365Analysis] = select.value;
                });
                const response = await api.requestJson('/api/m365/preferences', { method: 'PATCH', body: changes });
                applyPreferences(response.preferences);
                showStatus('m365-preferences-status', 'Preferences saved. Previously published history is unchanged.', 'success');
            } catch (error) {
                showStatus('m365-preferences-status', error.message, 'danger');
            } finally {
                button.disabled = false;
            }
        }

        function updateOptionalPermissions() {
            const sources = new Set(Array.from(root.querySelectorAll('[data-m365-connect-source]:checked')).map(input => input.dataset.m365ConnectSource));
            root.querySelectorAll('[data-m365-extra-scope]').forEach(input => {
                input.disabled = !input.dataset.m365ExtraSources.split(' ').some(source => sources.has(source));
                if (input.disabled) {
                    input.checked = false;
                }
            });
        }

        async function loadConnection() {
            const fields = document.getElementById('m365-connection-fields');
            fields.disabled = true;
            try {
                const response = await api.requestJson('/api/m365/connections');
                if (!Object.prototype.hasOwnProperty.call(response, 'connection')) {
                    throw new Error('The workflow connection status could not be verified.');
                }
                connection = response.connection;
                const status = connection?.status || 'disconnected';
                const details = document.getElementById('m365-connection-details');
                details.replaceChildren();
                [
                    ['Account', connection?.account_username || 'Not connected'],
                    ['Tenant', connection?.tenant_id || 'Not connected'],
                    ['Cloud', connection?.cloud || 'Deployment configuration'],
                    ['Authorized sources', (connection?.sources || []).map(source => api.sourceLabels[source] || source).join(', ') || 'None'],
                    ['Delegated permissions', (connection?.authorized_scopes || []).join(', ') || 'None']
                ].forEach(([label, value]) => {
                    const term = document.createElement('dt');
                    term.className = 'col-sm-3';
                    term.textContent = label;
                    const description = document.createElement('dd');
                    description.className = 'col-sm-9 text-break';
                    description.textContent = value;
                    details.append(term, description);
                });
                root.querySelectorAll('[data-m365-connect-source]').forEach(checkbox => {
                    checkbox.checked = (connection?.sources || []).includes(checkbox.dataset.m365ConnectSource);
                });
                const grantedScopes = new Set((connection?.authorized_scopes || []).map(scope => scope.split('/').pop().toLowerCase()));
                root.querySelectorAll('[data-m365-extra-scope]').forEach(input => {
                    input.checked = grantedScopes.has(input.dataset.m365ExtraScope.toLowerCase());
                });
                updateOptionalPermissions();
                fields.disabled = false;
                document.getElementById('m365-connect-btn').textContent = connection?.id ? 'Reconnect Microsoft 365 for workflows' : 'Connect Microsoft 365 for workflows';
                document.getElementById('m365-disconnect-btn').disabled = !connection?.id || status === 'disconnected';
                showStatus('m365-connection-status', `Workflow connection: ${status.replaceAll('_', ' ')}. Connecting is separate from approving a workflow.`, status === 'connected' ? 'success' : 'info');
            } catch (error) {
                showStatus('m365-connection-status', error.message, 'danger');
            }
        }

        async function connect() {
            const button = document.getElementById('m365-connect-btn');
            button.disabled = true;
            try {
                const sources = Array.from(root.querySelectorAll('[data-m365-connect-source]:checked')).map(input => input.dataset.m365ConnectSource);
                if (!sources.length) {
                    throw new Error('Select at least one source to connect for workflows.');
                }
                const scopes = Array.from(root.querySelectorAll('[data-m365-extra-scope]:checked')).map(input => input.dataset.m365ExtraScope);
                const body = scopes.length ? { sources, scopes } : { sources };
                const result = await api.requestJson('/api/m365/connections/connect', { method: 'POST', body });
                const target = new URL(result.authorization_url);
                if (target.protocol !== 'https:' || !target.hostname || target.username || target.password) {
                    throw new Error('The server did not return a valid Microsoft 365 sign-in URL.');
                }
                window.location.assign(target.href);
            } catch (error) {
                showStatus('m365-connection-status', error.message, 'danger');
                button.disabled = false;
            }
        }

        function confirmRevocation(description, task) {
            if (!window.bootstrap?.Modal) {
                showStatus('m365-preferences-status', 'The confirmation dialog is unavailable. No permission has been changed.', 'danger');
                return;
            }
            revocation = task;
            revocationTrigger = document.activeElement;
            document.getElementById('m365-revoke-description').textContent = description;
            document.getElementById('m365-revoke-error').classList.add('d-none');
            bootstrap.Modal.getOrCreateInstance(revokeElement).show();
        }

        async function revoke() {
            if (!revocation || revocationBusy) {
                return;
            }
            const button = document.getElementById('m365-revoke-confirm');
            button.disabled = true;
            revocationBusy = true;
            try {
                await revocation();
                revocationBusy = false;
                bootstrap.Modal.getInstance(revokeElement).hide();
                await refresh();
            } catch (error) {
                showStatus('m365-revoke-error', error.message, 'danger');
            } finally {
                revocationBusy = false;
                button.disabled = false;
            }
        }

        async function loadBindings(append = false) {
            const more = document.getElementById('m365-bindings-more');
            more.disabled = true;
            try {
                const query = new URLSearchParams({ page_size: '20' });
                if (append && bindingContinuation) {
                    query.set('continuation_token', bindingContinuation);
                }
                const response = await api.requestJson(`/api/m365/bindings?${query}`);
                if (!Array.isArray(response.items)) {
                    throw new Error('Workflow authorizations could not be read.');
                }
                const list = document.getElementById('m365-workflow-bindings');
                if (!append) {
                    list.replaceChildren();
                }
                response.items.forEach(binding => {
                    const row = document.createElement('div');
                    row.className = 'border rounded p-3';
                    const title = document.createElement('p');
                    title.className = 'small text-break mb-1';
                    title.textContent = `Workflow ${binding.context?.workflow_id || 'authorization'}: ${api.describeStatus(binding)}`;
                    row.appendChild(title);
                    if (['pending', 'approved'].includes(binding.status)) {
                        const button = document.createElement('button');
                        button.type = 'button';
                        button.className = 'btn btn-outline-danger btn-sm';
                        button.textContent = 'Revoke workflow authorization';
                        button.addEventListener('click', () => confirmRevocation(
                            'Revoke this workflow revision\'s permission to use your Microsoft 365 account?',
                            () => api.requestJson(`/api/m365/bindings/${encodeURIComponent(binding.id)}/revoke`, { method: 'POST', body: {} })
                        ));
                        row.appendChild(button);
                    }
                    list.appendChild(row);
                });
                bindingContinuation = response.continuation_token || null;
                more.classList.toggle('d-none', !bindingContinuation);
                document.getElementById('m365-bindings-status').textContent = list.childElementCount ? 'Only your own authorizations are shown. Pending requests can be decided from Approvals.' : 'No workflow authorizations.';
            } catch (error) {
                showStatus('m365-bindings-status', error.message, 'danger');
                more.classList.add('d-none');
            } finally {
                more.disabled = false;
            }
        }

        async function refresh() {
            await loadPreferences();
            await Promise.all([loadConnection(), loadBindings()]);
        }

        root.querySelectorAll('[data-m365-revoke-source]').forEach(button => {
            const source = button.dataset.m365RevokeSource;
            button.addEventListener('click', () => confirmRevocation(
                `Revoke existing ${api.sourceLabels[source]} sharing approvals and ask again before future publication?`,
                () => api.requestJson(`/api/m365/sources/${encodeURIComponent(source)}/revoke`, { method: 'POST', body: {} })
            ));
        });
        document.getElementById('m365-disconnect-btn').addEventListener('click', () => {
            if (!connection?.id) {
                showStatus('m365-connection-status', 'Refresh to verify the account before disconnecting.', 'danger');
                return;
            }
            const connectionId = connection.id;
            confirmRevocation('Disconnect this workflow account and invalidate its future workflow use and authorizations?', () =>
                api.requestJson('/api/m365/connections/disconnect', { method: 'POST', body: { connection_id: connectionId } }));
        });
        revokeElement.addEventListener('hide.bs.modal', event => {
            if (revocationBusy) {
                event.preventDefault();
            }
        });
        revokeElement.addEventListener('shown.bs.modal', () => document.getElementById('m365-revoke-confirm').focus());
        revokeElement.addEventListener('hidden.bs.modal', () => {
            revocation = null;
            if (revocationTrigger?.isConnected) {
                revocationTrigger.focus();
            }
        });
        document.getElementById('m365-preferences-form').addEventListener('submit', savePreferences);
        document.getElementById('m365-connect-btn').addEventListener('click', connect);
        root.querySelectorAll('[data-m365-connect-source]').forEach(input => {
            input.addEventListener('change', updateOptionalPermissions);
        });
        document.getElementById('m365-revoke-confirm').addEventListener('click', revoke);
        document.getElementById('m365-profile-refresh').addEventListener('click', refresh);
        document.getElementById('m365-bindings-more').addEventListener('click', () => loadBindings(true));
        refresh();
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', initialize, { once: true });
    } else {
        initialize();
    }
})();
