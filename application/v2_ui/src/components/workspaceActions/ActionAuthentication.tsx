// ActionAuthentication.tsx

import { useId } from 'react';
import { ActionField, ActionSecretInput, ACTION_INPUT_CLASS } from './ActionFields';
import {
    actionAuthMethod, actionAuthModes, actionFieldError, actionText, actionValueAt,
    changeActionAuth, changeActionField, selectActionIdentity,
} from '../../lib/workspaceActionLogic';
import { nativeActionDefinition, sqlConnectionMethod } from '../../lib/workspaceActionRegistry';
import type { ActionTypeDefinition } from '../../lib/workspaceAuthoring';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';

export function ActionAuthentication(props: ActionConnectorProps & { definition: ActionTypeDefinition }) {
    const { draft, onChange, readOnly, definition } = props;
    const id = useId();
    const native = nativeActionDefinition(draft.type);
    const modes = actionAuthModes(draft.type, definition.allowed_auth_types);
    const method = actionAuthMethod(draft);
    const selected = modes.find((choice) => choice.value === method);
    const identityTypes = native.identityTypes ?? ['api_key', 'bearer_token', 'client_secret', 'connection_string', 'managed_identity', 'username_password'];
    const identities = props.identities.filter((identity) => identityTypes.includes(identity.auth_type));
    const identity = identities.find((candidate) => candidate.id === draft.identity_id);
    const identityMissing = Boolean(draft.identity_id && !identity);
    const sql = ['sql_query', 'sql_schema'].includes(draft.type);

    const textField = (path: string, label: string, help?: string, required = false) => props.original?.secret_paths.includes(path)
        ? secretField(path, label, help) : (
        <ActionField key={path} id={`${id}${path}`} label={label} error={actionFieldError(props.errors, path)} help={help} required={required}>
            <input id={`${id}${path}`} className={ACTION_INPUT_CLASS} value={actionText(actionValueAt(draft, path))}
                required={required} disabled={readOnly} aria-invalid={Boolean(actionFieldError(props.errors, path))}
                onChange={(event) => onChange((current) => changeActionField(current, path, event.target.value))} />
        </ActionField>
    );
    const secretField = (path: string, label: string, help?: string, multiline = false) => (
        <ActionSecretInput key={path} id={`${id}${path}`} label={label} help={help} multiline={multiline}
            value={actionValueAt(draft, path)} storedValue={actionValueAt(props.original?.record, path)}
            disabled={readOnly} error={actionFieldError(props.errors, path)}
            onChange={(value) => onChange((current) => changeActionField(current, path, value))} />
    );

    if (native.internal) return (
        <p className="text-sm text-text-2">
            {draft.auth.type === 'user'
                ? 'Uses the signed-in user’s permissions. No credentials or reusable identity are needed.'
                : 'No connector credentials are required. Application and workspace authorization still apply.'}
        </p>
    );

    const keyLabel = draft.type === 'azure_maps_openlayers' ? 'Azure Maps subscription key' :
        draft.type === 'cosmos_query' || draft.type === 'blob_storage' && draft.auth.type === 'key' ? 'Account key' :
            draft.auth.type === 'connection_string' ? 'Connection string' :
                draft.auth.type === 'servicePrincipal' ? 'Client secret' :
                    draft.type === 'snowflake' && method === 'key_pair' ? 'PEM private key' :
                        draft.type === 'snowflake' && method === 'oauth' ? 'OAuth access token' :
                            ['username_password', 'basic'].includes(draft.auth.type) ? 'Password' :
                                ['pat', 'personal_access_token'].includes(method) ? 'Personal access token' :
                                    ['bearer', 'bearer_token'].includes(method) ? 'Bearer token' : 'API key';

    return (
        <div className="space-y-5">
            {identityTypes.length || draft.identity_id ? (
                <div className="space-y-2">
                    <ActionField id={`${id}-identity`} label="Reusable identity"
                        help="Use an existing identity from My Workspace, or enter credentials for this action. Credentials are resolved on the server."
                        error={actionFieldError(props.errors, '/identity_id')}>
                        <select id={`${id}-identity`} className={ACTION_INPUT_CLASS} value={draft.identity_id || ''}
                            disabled={readOnly || props.identitiesLoading}
                            onChange={(event) => {
                                const next = identities.find((candidate) => candidate.id === event.target.value);
                                if (event.target.value && !next) return;
                                onChange((current) => {
                                    const changed = selectActionIdentity(current, next ?? null);
                                    return !next && modes.length ? changeActionAuth(changed, modes[0]) : changed;
                                });
                            }}>
                            <option value="">Use action-specific credentials</option>
                            {identityMissing ? <option value={draft.identity_id} disabled>Unavailable identity — {draft.identity_id}</option> : null}
                            {identities.map((candidate) => <option key={candidate.id} value={candidate.id}>
                                {candidate.name} · {candidate.auth_type.replaceAll('_', ' ')} · {candidate.scope_type || 'personal'} · {candidate.id}
                            </option>)}
                        </select>
                    </ActionField>
                    {props.identitiesLoading ? <p role="status" className="text-xs text-text-3">Loading permitted identities…</p> : null}
                    {props.identitiesError ? <p role="alert" className="text-sm text-danger">{props.identitiesError} The existing identity has not been changed.</p> : null}
                    {identityMissing ? <p role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                        The selected identity is unavailable or no longer compatible. Its ID is retained until you explicitly choose a replacement; a same-name identity will never be substituted.
                    </p> : null}
                    {identity ? <p className="text-xs text-text-3">{identity.description || 'This action will use the selected identity when it runs.'}</p> : null}
                </div>
            ) : null}
            {!draft.identity_id ? <>
                <ActionField id={`${id}-auth`} label="Authentication method" error={actionFieldError(props.errors, '/auth/type')}>
                    <select id={`${id}-auth`} className={ACTION_INPUT_CLASS} value={selected ? method : 'existing'}
                        disabled={readOnly || modes.length === 0}
                        onChange={(event) => {
                            const choice = modes.find((candidate) => candidate.value === event.target.value);
                            if (choice) onChange((current) => changeActionAuth(current, choice));
                        }}>
                        {!selected ? <option value="existing" disabled>Existing method: {method || draft.auth.type}</option> : null}
                        {modes.map((choice) => <option key={choice.value} value={choice.value}>{choice.label}</option>)}
                    </select>
                </ActionField>
                {sql && method === 'service_principal' ? <p role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                    These service-principal fields are retained for compatibility, but the current SQL action runtime does not use them.
                    Use a supported authentication mode or a complete connection string instead. A connection test will not report these fields as working credentials.
                </p> : null}
                {sql && sqlConnectionMethod(draft) === 'connection_string' ? <p className="text-xs text-text-3">
                    Connection-string mode uses the authentication specified in the connection string, not separate database credentials.
                </p> : null}
                {sql && method === 'username_password' && sqlConnectionMethod(draft) === 'parameters' && draft.additionalFields.database_type !== 'sqlite' ? (
                    <div className="grid gap-4 sm:grid-cols-2">
                        {textField('/additionalFields/username', 'Database username', undefined, true)}
                        {secretField('/additionalFields/password', 'Database password')}
                    </div>
                ) : null}
                {draft.auth.type === 'servicePrincipal' ? <>
                    <div className="grid gap-4 sm:grid-cols-2">
                        {textField('/auth/identity', 'Client ID', undefined, true)}
                        {textField('/auth/tenantId', 'Tenant ID', undefined, true)}
                    </div>
                    {secretField('/auth/key', keyLabel)}
                </> : null}
                {['username_password', 'basic'].includes(draft.auth.type) && draft.type !== 'snowflake'
                    ? textField('/auth/identity', 'Username', undefined, true) : null}
                {draft.type === 'tableau' && method === 'personal_access_token'
                    ? textField('/auth/identity', 'Personal access token name', undefined, true) : null}
                {['key', 'connection_string', 'username_password', 'basic'].includes(draft.auth.type)
                    ? secretField('/auth/key', keyLabel, draft.type === 'snowflake' && method === 'key_pair'
                        ? 'Paste the complete PEM private key, including BEGIN/END lines. A replacement is visible only while editing this field.'
                        : undefined, draft.type === 'snowflake' && method === 'key_pair') : null}
                {draft.type === 'snowflake' && method === 'key_pair'
                    ? secretField('/additionalFields/private_key_passphrase', 'Private key passphrase', 'Only needed for an encrypted private key.') : null}
                {draft.type === 'rocksdb' && method === 'api_key'
                    ? textField('/additionalFields/api_key_header', 'API key header name', 'Defaults to X-API-Key.') : null}
                {draft.auth.type === 'identity' && !sql && !['cosmos_query', 'databricks', 'databricks_table', 'blob_storage'].includes(draft.type)
                    ? textField('/auth/identity', 'Managed identity client ID', 'Use managed_identity for the system-assigned application identity, or the configured user-assigned client ID.') : null}
                {draft.auth.type === 'identity' ? <p className="text-xs text-text-3">
                    {method === 'integrated' ? 'Integrated authentication uses the application server’s database login.' :
                        method === 'connection_string_only' ? 'Credentials are supplied by the database connection string.' :
                            'Managed identity uses the application’s Azure identity. Grant it the required data access on the target resource.'}
                </p> : null}
                {draft.auth.type === 'user' && !sql ? <p className="text-xs text-text-3">Runs on behalf of the signed-in user.</p> : null}
                {draft.type === 'log_analytics' && draft.auth.type === 'key' ? <p className="text-xs text-warn">
                    Key authentication is supported only by custom Log Analytics-compatible endpoints.
                </p> : null}
                {draft.auth.type === 'NoAuth' ? <p className="text-xs text-text-3">No authentication headers or credentials will be used.</p> : null}
            </> : null}
            {draft.identity_id && draft.type === 'tableau' && (identity?.auth_type === 'api_key' || method === 'personal_access_token')
                ? textField('/additionalFields/pat_name', 'Personal access token name', 'The reusable identity contains the PAT secret; its token name is configured on this action.', true) : null}
            {draft.identity_id && draft.type === 'snowflake' && method === 'key_pair'
                ? secretField('/additionalFields/private_key_passphrase', 'Private key passphrase', 'Only needed for an encrypted private key.') : null}
            <p className="text-xs leading-relaxed text-text-3">
                Stored secrets are never returned to this form. Keep their masked state, enter a replacement, or choose Clear.
                Changing another field does not replace credentials or erase hidden configuration.
            </p>
        </div>
    );
}
