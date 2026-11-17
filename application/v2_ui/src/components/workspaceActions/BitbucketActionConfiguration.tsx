// BitbucketActionConfiguration.tsx

import { useId, useState } from 'react';
import { api, request } from '../../lib/apiClient';
import { isRecord } from '../../lib/workspaceAuthoring';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';
import { changeActionCredentialSource, changeActionField } from '../../lib/workspaceActionLogic';
import { ActionField, ActionSecretInput, ACTION_INPUT_CLASS } from './ActionFields';
import { EditorFieldset } from '../workspace/EditorLayout';

interface Repository {
    id: string;
    project: string;
    slug: string;
    name: string;
    branch_mode: string;
    default_branch: string;
}

function repositories(value: unknown): Repository[] {
    return Array.isArray(value) ? value.filter(isRecord).map((item) => ({
        id: String(item.id ?? ''), project: String(item.project ?? ''), slug: String(item.slug ?? ''),
        name: String(item.name ?? ''), branch_mode: String(item.branch_mode ?? 'any'),
        default_branch: String(item.default_branch ?? ''),
    })) : [];
}

export function BitbucketActionConfiguration(props: ActionConnectorProps) {
    const { draft, onChange, readOnly } = props;
    const id = useId();
    const [project, setProject] = useState('');
    const [options, setOptions] = useState<Repository[]>([]);
    const [cursor, setCursor] = useState<number | string | null>(null);
    const [message, setMessage] = useState('');
    const [busy, setBusy] = useState(false);
    const method = String(draft.additionalFields.auth_method ?? 'oauth');
    const edition = String(draft.additionalFields.edition ?? 'data_center');
    const selected = repositories(draft.additionalFields.repositories);
    const personal = Boolean(draft.credential_requirements?.slots.service);
    const scope = props.globalScope ? 'global:global' : props.groupScope ? `group:${props.groupScope.id}` : 'personal:self';
    const reference = draft.id ? `${scope}:${draft.id}` : '';
    const update = (path: string, value: unknown) => onChange((current) => changeActionField(current, path, value));
    const updateRepo = (index: number, patch: Partial<Repository>) =>
        update('/additionalFields/repositories', selected.map((repo, i) => i === index ? { ...repo, ...patch } : repo));

    async function discover(next: number | string = 0) {
        setBusy(true);
        setMessage('');
        try {
            const status = await api.get<{ csrf_token: string }>(`/api/bitbucket/connection?action_ref=${encodeURIComponent(reference)}`);
            const result = await request<{ repositories: unknown; next_cursor: number | string | null }>('/api/bitbucket/discover',
                { method: 'POST', body: { action_ref: reference, project, cursor: next },
                    headers: { 'X-CSRFToken': status.csrf_token } });
            setOptions((previous) => next ? [...previous, ...repositories(result.repositories)] : repositories(result.repositories));
            setCursor(result.next_cursor);
            setMessage(result.repositories && Array.isArray(result.repositories) && result.repositories.length
                ? 'Select permitted repositories below. Save again to apply changes.'
                : 'No repositories are accessible in this project or workspace.');
        } catch (error) {
            setMessage(error instanceof Error ? error.message : 'Repository discovery failed.');
        } finally {
            setBusy(false);
        }
    }

    return <div className="space-y-5">
        <p className="text-sm text-text-2">Read source and compare branches. This action cannot change repositories or post reviews.</p>
        <ActionField id={`${id}-edition`} label="Bitbucket edition">
            <select id={`${id}-edition`} className={ACTION_INPUT_CLASS} value={edition} disabled={readOnly}
                onChange={(event) => {
                    update('/additionalFields/edition', event.target.value);
                    if (event.target.value === 'cloud') update('/endpoint', 'https://api.bitbucket.org');
                }}>
                <option value="data_center">Self-hosted Data Center</option><option value="cloud">Bitbucket Cloud</option>
            </select>
        </ActionField>
        <ActionField id={`${id}-endpoint`} label="Bitbucket HTTPS base URL" help="Include a Data Center context path if configured. Private DNS must be reachable from SimpleChat.">
            <input id={`${id}-endpoint`} className={ACTION_INPUT_CLASS} value={draft.endpoint} disabled={readOnly || edition === 'cloud'}
                onChange={(event) => update('/endpoint', event.target.value)} />
        </ActionField>
        <ActionField id={`${id}-method`} label="Bitbucket authentication">
            <select id={`${id}-method`} className={ACTION_INPUT_CLASS} value={method} disabled={readOnly}
                onChange={(event) => onChange((current) => ({
                    ...current, identity_id: '', credential_requirements: undefined,
                    auth: { type: event.target.value === 'oauth' ? 'user' : event.target.value === 'username_password' ? 'username_password' : 'key' },
                    additionalFields: { ...current.additionalFields, auth_method: event.target.value },
                }))}>
                <option value="oauth">Each user's OAuth connection (SSO / smart card)</option>
                <option value="bearer_token">HTTP access / bearer token</option>
                {edition === 'cloud' ? <option value="username_password">Atlassian email and scoped API token</option> : null}
            </select>
        </ActionField>
        {method === 'oauth' ? <>
            <ActionField id={`${id}-client`} label="OAuth client ID" help="Register an incoming application link in Data Center, or an OAuth consumer in Cloud, with repository-read permissions only.">
                <input id={`${id}-client`} className={ACTION_INPUT_CLASS} value={String(draft.auth.identity ?? '')} disabled={readOnly}
                    onChange={(event) => update('/auth/identity', event.target.value)} />
            </ActionField>
            <ActionSecretInput id={`${id}-secret`} label="OAuth client secret" value={draft.auth.key}
                storedValue={props.original?.record.auth.key} disabled={readOnly}
                onChange={(value) => update('/auth/key', value)} />
            {reference ? <a href={`/bitbucket/connect?action_ref=${encodeURIComponent(reference)}`}
                target="_blank" rel="noopener noreferrer" className="text-sm text-accent underline">Connect / reconnect my Bitbucket account</a>
                : <p className="text-sm text-text-2">Save this action first, connect your account, then reopen it to select permitted repositories.</p>}
            <p className="text-xs text-text-3">Connections belong to the invoking user, not the action author. SimpleChat and Microsoft 365 session tokens are never reused.</p>
        </> : <>
            <ActionField id={`${id}-source`} label="Token credential source">
                <select id={`${id}-source`} className={ACTION_INPUT_CLASS} disabled={readOnly}
                    value={draft.credential_requirements?.slots.service ? 'personal' : draft.identity_id || draft.auth.type === 'identity' ? 'identity' : 'shared'}
                    onChange={(event) => {
                        if (event.target.value === 'personal') onChange((current) => changeActionCredentialSource(current, 'service', true));
                        else onChange((current) => ({
                            ...current, credential_requirements: undefined, identity_id: '',
                            auth: { type: event.target.value === 'identity' ? 'identity' : method === 'username_password' ? 'username_password' : 'key', identity: '', key: '' },
                        }));
                    }}>
                    <option value="personal">Each user's private identity, requested in chat</option>
                    <option value="shared">Shared action credential</option>
                    <option value="identity">Saved workspace identity (shared by action users)</option>
                </select>
            </ActionField>
            {!draft.credential_requirements?.slots.service ? <>
                <ActionField id={`${id}-identity`} label="Saved token identity" help="Use a compatible identity from this action's workspace, or enter a shared action credential below.">
                    <select id={`${id}-identity`} className={ACTION_INPUT_CLASS} value={draft.identity_id ?? ''} disabled={readOnly || props.identitiesLoading}
                        onChange={(event) => onChange((current) => ({ ...current, identity_id: event.target.value,
                            auth: { ...current.auth, type: event.target.value ? 'identity' : method === 'username_password' ? 'username_password' : 'key', identity: event.target.value, key: '' } }))}>
                        <option value="">Use action credential below</option>
                        {draft.identity_id && !props.identities.some((candidate) => candidate.id === draft.identity_id)
                            ? <option value={draft.identity_id} disabled>Unavailable identity — kept as is</option> : null}
                        {props.identities.filter((identity) => identity.auth_type === method).map((identity) =>
                            <option key={identity.id} value={identity.id}>{identity.name}</option>)}
                    </select>
                </ActionField>
                {props.identitiesError ? <p role="alert" className="text-sm text-danger">{props.identitiesError}</p> : null}
                {!draft.identity_id ? <>
                    {method === 'username_password' ? <ActionField id={`${id}-email`} label="Atlassian email">
                        <input id={`${id}-email`} className={ACTION_INPUT_CLASS} value={String(draft.auth.identity ?? '')} disabled={readOnly}
                            onChange={(event) => update('/auth/identity', event.target.value)} />
                    </ActionField> : null}
                    <ActionSecretInput id={`${id}-token`} label="Read-only token" value={draft.auth.key} storedValue={props.original?.record.auth.key}
                        disabled={readOnly} onChange={(value) => update('/auth/key', value)} />
                </> : null}
            </> : <p className="text-sm text-text-2">Each invoking user supplies a compatible personal token identity privately in chat. No shared token is saved here.</p>}
        </>}
        <EditorFieldset legend="Permitted repositories" help="Save connection changes before discovery. Empty selections cannot read code. Users choose among permitted repositories in chat.">
            <ActionField id={`${id}-project`} label={edition === 'cloud' ? 'Cloud workspace' : 'Data Center project key'}>
                <input id={`${id}-project`} className={ACTION_INPUT_CLASS} value={project} disabled={readOnly}
                    onChange={(event) => { setProject(event.target.value); setOptions([]); setCursor(null); }} />
            </ActionField>
            <button type="button" className="btn-secondary" disabled={readOnly || busy || personal || !reference || !project} onClick={() => void discover()}>
                {busy ? 'Loading repositories...' : 'Find repositories'}
            </button>
            {personal ? <p className="text-sm text-text-2">Discover using OAuth or a saved/shared token before switching to per-user tokens.</p> : null}
            {cursor !== null ? <button type="button" className="btn-secondary" disabled={readOnly || busy || personal}
                onClick={() => void discover(cursor)}>Load more repositories</button> : null}
            {message ? <p role="status" className="text-sm text-text-2">{message}</p> : null}
            {options.map((repo) => <label key={repo.id} className="flex items-center gap-2 text-sm">
                <input type="checkbox" checked={selected.some((item) => item.id === repo.id)} disabled={readOnly}
                    onChange={(event) => update('/additionalFields/repositories', event.target.checked
                        ? [...selected, repo] : selected.filter((item) => item.id !== repo.id))} />
                {repo.name} ({repo.slug})
            </label>)}
            {selected.map((repo, index) => <EditorFieldset key={repo.id} legend={repo.name || repo.slug}
                help={`${repo.project}/${repo.slug}`}>
                <ActionField id={`${id}-${index}-branch-mode`} label="Allowed branches">
                    <select id={`${id}-${index}-branch-mode`} className={ACTION_INPUT_CLASS} value={repo.branch_mode} disabled={readOnly}
                        onChange={(event) => updateRepo(index, { branch_mode: event.target.value })}>
                        <option value="any">Any branch</option><option value="fixed">One fixed branch</option>
                    </select>
                </ActionField>
                <ActionField id={`${id}-${index}-default`} label={repo.branch_mode === 'fixed' ? 'Fixed branch' : 'Default branch (optional)'}
                    help={repo.branch_mode === 'fixed' ? 'Other branches, including comparison inputs, are denied.' : "Leave blank to use Bitbucket's default branch."}>
                    <input id={`${id}-${index}-default`} className={ACTION_INPUT_CLASS} value={repo.default_branch} disabled={readOnly}
                        onChange={(event) => updateRepo(index, { default_branch: event.target.value })} />
                </ActionField>
                <button type="button" className="btn-secondary" disabled={readOnly}
                    onClick={() => update('/additionalFields/repositories', selected.filter((item) => item.id !== repo.id))}>Remove repository</button>
            </EditorFieldset>)}
        </EditorFieldset>
    </div>;
}
