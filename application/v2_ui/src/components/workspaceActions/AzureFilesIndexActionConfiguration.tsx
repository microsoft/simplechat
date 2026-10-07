// AzureFilesIndexActionConfiguration.tsx

import { useId } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { EditorDependents, EditorFieldset, EditorGroup, EditorPanel, EditorSwitch } from '../workspace/EditorLayout';
import { ACTION_INPUT_CLASS, ActionField } from './ActionFields';
import {
    AZURE_FILES_INDEX_LIMITS, AZURE_FILES_INDEX_LAYOUT_DEFAULTS,
    addAzureFilesStorageShare, applyAzureFilesIndexLayoutPreset, azureFilesIndexEffectiveField,
    azureFilesIndexLayout, azureFilesIndexPermissionMode, azureFilesIndexQueryMode, azureFilesStorageShares,
    removeAzureFilesStorageShare, updateAzureFilesStorageShare,
} from '../../lib/azureFilesIndexAction';
import { actionFieldError, actionText, changeActionField } from '../../lib/workspaceActionLogic';
import type { ActionConnectorProps } from '../../lib/workspaceActionTypes';

const LAYOUT_HELP = {
    document_per_file: 'One search document per file from the standard Azure Files indexer fields.',
    chunked: 'Integrated vectorization or index projections with one search document per chunk.',
    custom: 'Use custom field names; content, path, and file name fields are required.',
};

function NumberField({
    id, label, help, value, min, max, disabled, error, onChange,
}: {
    id: string; label: string; help: string; value: unknown; min: number; max: number;
    disabled: boolean; error?: string; onChange: (value: number | undefined) => void;
}) {
    return (
        <ActionField id={id} label={label} help={`${help} Range: ${min}-${max}.`} error={error} width="compact">
            <input id={id} type="number" min={min} max={max} step={1} className={ACTION_INPUT_CLASS}
                value={typeof value === 'number' ? value : ''} disabled={disabled}
                aria-invalid={Boolean(error)} aria-describedby={`${id}-help ${id}-error`}
                onChange={(event) => onChange(event.target.value === '' ? undefined : event.target.valueAsNumber)} />
        </ActionField>
    );
}

function MappingField({
    id, label, value, placeholder, disabled, error, required, onChange,
}: {
    id: string; label: string; value: unknown; placeholder?: string | boolean; disabled: boolean;
    error?: string; required?: boolean; onChange: (value: string) => void;
}) {
    return (
        <ActionField id={id} label={label} required={required} error={error}>
            <input id={id} className={ACTION_INPUT_CLASS} value={actionText(value)} disabled={disabled}
                required={required} placeholder={typeof placeholder === 'string' ? placeholder : undefined}
                aria-invalid={Boolean(error)} aria-describedby={`${id}-help ${id}-error`}
                onChange={(event) => onChange(event.target.value)} />
        </ActionField>
    );
}

export function AzureFilesIndexActionConfiguration(props: ActionConnectorProps) {
    const { draft, onChange, readOnly, errors } = props;
    const id = useId();
    const fields = draft.additionalFields;
    const layout = azureFilesIndexLayout(fields.index_layout);
    const queryMode = azureFilesIndexQueryMode(fields.query_mode);
    const permissionMode = azureFilesIndexPermissionMode(fields.permission_mode);
    const shares = azureFilesStorageShares(fields.storage_shares);
    const fieldError = (path: string) => actionFieldError(errors, path);
    const updateField = (path: string, value: unknown) => onChange((current) => changeActionField(current, path, value));
    const updateAdditional = (key: string, value: unknown) => updateField(`/additionalFields/${key}`, value);
    const effective = (key: keyof typeof AZURE_FILES_INDEX_LAYOUT_DEFAULTS.document_per_file) =>
        azureFilesIndexEffectiveField(draft, key);
    const disabled = readOnly || Boolean(props.original?.read_only);

    return (
        <div className="min-w-0 space-y-5" data-testid="azure-files-index-configuration">
            <p className="text-[0.8125rem] leading-relaxed text-text-2">
                Search an existing Azure AI Search index created by the Azure Files indexer. SimpleChat checks
                file permissions before returning results, so agents only see files the signed-in user can open.
            </p>

            <EditorPanel title="Search index"
                description="Point at the customer-managed Search service and describe the index shape the Azure Files indexer produced.">
                <ActionField id={`${id}-endpoint`} label="Search service endpoint" required
                    help="Use the Azure AI Search service endpoint, for example https://contoso.search.windows.net."
                    error={fieldError('/endpoint')}>
                    <input id={`${id}-endpoint`} className={ACTION_INPUT_CLASS} required disabled={disabled}
                        value={draft.endpoint} aria-invalid={Boolean(fieldError('/endpoint'))}
                        aria-describedby={`${id}-endpoint-help ${id}-endpoint-error`}
                        onChange={(event) => onChange((current) => ({ ...current, endpoint: event.target.value }))} />
                </ActionField>
                <ActionField id={`${id}-index-name`} label="Index name" required
                    help="The Azure AI Search index built from Azure Files. Use lowercase letters, numbers, and single dashes."
                    error={fieldError('/additionalFields/index_name')}>
                    <input id={`${id}-index-name`} className={ACTION_INPUT_CLASS} required disabled={disabled}
                        value={actionText(fields.index_name)} aria-invalid={Boolean(fieldError('/additionalFields/index_name'))}
                        aria-describedby={`${id}-index-name-help ${id}-index-name-error`}
                        onChange={(event) => updateAdditional('index_name', event.target.value)} />
                </ActionField>
                <ActionField id={`${id}-layout`} label="Index layout" required width="standard"
                    help={LAYOUT_HELP[layout]} error={fieldError('/additionalFields/index_layout')}>
                    <select id={`${id}-layout`} className={ACTION_INPUT_CLASS} value={layout} disabled={disabled}
                        aria-describedby={`${id}-layout-help ${id}-layout-error`}
                        onChange={(event) => onChange((current) => applyAzureFilesIndexLayoutPreset(current, azureFilesIndexLayout(event.target.value)))}>
                        <option value="document_per_file">Document per file</option>
                        <option value="chunked">Chunked</option>
                        <option value="custom">Custom</option>
                    </select>
                </ActionField>
                <ActionField id={`${id}-query-mode`} label="Query mode" required width="standard"
                    help="Semantic and hybrid search use the index semantic configuration; hybrid also needs a vector field."
                    error={fieldError('/additionalFields/query_mode')}>
                    <select id={`${id}-query-mode`} className={ACTION_INPUT_CLASS} value={queryMode} disabled={disabled}
                        aria-describedby={`${id}-query-mode-help ${id}-query-mode-error`}
                        onChange={(event) => updateAdditional('query_mode', event.target.value)}>
                        <option value="keyword">Keyword</option>
                        <option value="semantic">Semantic</option>
                        <option value="hybrid">Hybrid</option>
                    </select>
                </ActionField>
                {queryMode === 'semantic' || queryMode === 'hybrid' ? (
                    <ActionField id={`${id}-semantic-configuration`} label="Semantic configuration"
                        help="Leave blank to use the index default semantic configuration."
                        error={fieldError('/additionalFields/semantic_configuration')}>
                        <input id={`${id}-semantic-configuration`} className={ACTION_INPUT_CLASS}
                            value={actionText(fields.semantic_configuration)} disabled={disabled}
                            aria-invalid={Boolean(fieldError('/additionalFields/semantic_configuration'))}
                            aria-describedby={`${id}-semantic-configuration-help ${id}-semantic-configuration-error`}
                            onChange={(event) => updateAdditional('semantic_configuration', event.target.value)} />
                    </ActionField>
                ) : null}
                <EditorGroup summary="Advanced field mapping"
                    hint={layout === 'custom' ? 'Required for custom layout' : 'Preset defaults applied'}
                    defaultOpen={layout === 'custom'}>
                    {layout !== 'custom' ? <p className="text-xs leading-relaxed text-text-3">
                        These fields use the selected preset. You can override a field if your index names differ.
                    </p> : null}
                    <MappingField id={`${id}-content-field`} label="Content field" value={fields.content_field}
                        placeholder={effective('content_field')} disabled={disabled} required={layout === 'custom'}
                        error={fieldError('/additionalFields/content_field')}
                        onChange={(value) => updateAdditional('content_field', value)} />
                    <MappingField id={`${id}-title-field`} label="Title field" value={fields.title_field}
                        placeholder={effective('title_field')} disabled={disabled}
                        error={fieldError('/additionalFields/title_field')}
                        onChange={(value) => updateAdditional('title_field', value)} />
                    <MappingField id={`${id}-path-field`} label="Path field" value={fields.path_field}
                        placeholder={effective('path_field')} disabled={disabled} required={layout === 'custom'}
                        error={fieldError('/additionalFields/path_field')}
                        onChange={(value) => updateAdditional('path_field', value)} />
                    <MappingField id={`${id}-name-field`} label="Name field" value={fields.name_field}
                        placeholder={effective('name_field')} disabled={disabled} required={layout === 'custom'}
                        error={fieldError('/additionalFields/name_field')}
                        onChange={(value) => updateAdditional('name_field', value)} />
                    <MappingField id={`${id}-last-modified-field`} label="Last modified field" value={fields.last_modified_field}
                        placeholder={effective('last_modified_field')} disabled={disabled}
                        error={fieldError('/additionalFields/last_modified_field')}
                        onChange={(value) => updateAdditional('last_modified_field', value)} />
                    <MappingField id={`${id}-vector-field`} label="Vector field" value={fields.vector_field}
                        placeholder={effective('vector_field')} disabled={disabled} required={queryMode === 'hybrid'}
                        error={fieldError('/additionalFields/vector_field')}
                        onChange={(value) => updateAdditional('vector_field', value)} />
                    <EditorSwitch label="Select content field"
                        description="Return the mapped content field for snippets. Chunked indexes usually enable this; whole-file indexes can use captions or highlights instead."
                        checked={fields.select_content === true} disabled={disabled}
                        error={fieldError('/additionalFields/select_content')}
                        onChange={(value) => updateAdditional('select_content', value)} />
                </EditorGroup>
            </EditorPanel>

            <EditorPanel title="File permissions"
                description="SimpleChat checks each file's NTFS permissions and share access for the signed-in user; files it can't verify are withheld and logged for admins.">
                <ActionField id={`${id}-permission-mode`} label="Permission mode" required width="standard"
                    help="Live ACL is recommended for production. Disable checks only for tightly governed internal indexes."
                    error={fieldError('/additionalFields/permission_mode')}>
                    <select id={`${id}-permission-mode`} className={ACTION_INPUT_CLASS} value={permissionMode} disabled={disabled}
                        aria-describedby={`${id}-permission-mode-help ${id}-permission-mode-error`}
                        onChange={(event) => updateAdditional('permission_mode', event.target.value)}>
                        <option value="live_acl">Live ACL checks (recommended)</option>
                        <option value="none">No permission checks</option>
                    </select>
                </ActionField>
                {permissionMode === 'none' ? <div className="space-y-3 rounded-xl border border-warn/40 bg-warn-soft p-3 text-sm text-warn">
                    <p>Permission checks are disabled. Everyone who can use this action can search every file in the index.</p>
                    <label className="form-check flex items-start gap-2 text-sm">
                        <input type="checkbox" className="form-check-input mt-1"
                            checked={fields.permission_mode_none_acknowledged === true} disabled={disabled}
                            aria-invalid={Boolean(fieldError('/additionalFields/permission_mode_none_acknowledged'))}
                            onChange={(event) => updateAdditional('permission_mode_none_acknowledged', event.target.checked)} />
                        <span>Everyone who can use this action can search every file in the index.</span>
                    </label>
                    {fieldError('/additionalFields/permission_mode_none_acknowledged')
                        ? <p role="alert" className="text-sm text-danger">{fieldError('/additionalFields/permission_mode_none_acknowledged')}</p> : null}
                </div> : null}
                {permissionMode === 'live_acl' ? (
                    <EditorFieldset legend="Storage shares"
                        help="List every Azure Files share that contributed documents to this index. Results from other shares are withheld.">
                        {shares.length ? shares.map((share, index) => (
                            <div key={index} className="space-y-3 rounded-xl border border-edge bg-surface-1 p-3">
                                <div className="flex items-center justify-between gap-3">
                                    <p className="text-sm font-semibold text-text-1">Share {index + 1}</p>
                                    <GlassButton type="button" size="sm" variant="subtle" disabled={disabled}
                                        aria-label={`Remove storage share ${index + 1}`}
                                        onClick={() => onChange((current) => removeAzureFilesStorageShare(current, index))}>
                                        <Trash2 size={14} />Remove
                                    </GlassButton>
                                </div>
                                <ActionField id={`${id}-share-${index}-resource`} label="Storage account resource ID"
                                    error={fieldError(`/additionalFields/storage_shares/${index}/storage_account_resource_id`)}>
                                    <input id={`${id}-share-${index}-resource`} className={ACTION_INPUT_CLASS}
                                        value={share.storage_account_resource_id} disabled={disabled}
                                        placeholder="/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/account"
                                        aria-invalid={Boolean(fieldError(`/additionalFields/storage_shares/${index}/storage_account_resource_id`))}
                                        onChange={(event) => onChange((current) =>
                                            updateAzureFilesStorageShare(current, index, 'storage_account_resource_id', event.target.value))} />
                                </ActionField>
                                <ActionField id={`${id}-share-${index}-name`} label="Share name" width="standard"
                                    error={fieldError(`/additionalFields/storage_shares/${index}/share_name`)}>
                                    <input id={`${id}-share-${index}-name`} className={ACTION_INPUT_CLASS}
                                        value={share.share_name} disabled={disabled} placeholder="documents"
                                        aria-invalid={Boolean(fieldError(`/additionalFields/storage_shares/${index}/share_name`))}
                                        onChange={(event) => onChange((current) =>
                                            updateAzureFilesStorageShare(current, index, 'share_name', event.target.value))} />
                                </ActionField>
                            </div>
                        )) : <p className="text-sm text-text-3">No storage shares configured yet.</p>}
                        {fieldError('/additionalFields/storage_shares')
                            ? <p role="alert" className="text-sm text-danger">{fieldError('/additionalFields/storage_shares')}</p> : null}
                        <GlassButton type="button" variant="subtle" disabled={disabled || shares.length >= 50}
                            onClick={() => onChange((current) => addAzureFilesStorageShare(current))}>
                            <Plus size={15} />Add storage share
                        </GlassButton>
                    </EditorFieldset>
                ) : null}
                <ActionField id={`${id}-share-access-check`} label="Share-level check" width="standard"
                    help="RBAC checks share-level permissions and Azure role assignments before file ACLs. Skip relies on NTFS permissions only."
                    error={fieldError('/additionalFields/share_access_check')}>
                    <select id={`${id}-share-access-check`} className={ACTION_INPUT_CLASS}
                        value={actionText(fields.share_access_check) || 'rbac'} disabled={disabled}
                        aria-describedby={`${id}-share-access-check-help ${id}-share-access-check-error`}
                        onChange={(event) => updateAdditional('share_access_check', event.target.value)}>
                        <option value="rbac">Check share access and RBAC</option>
                        <option value="skip">Skip share-level check</option>
                    </select>
                </ActionField>
                <EditorSwitch label="Treat BUILTIN\\Users as every signed-in user"
                    description="Leave off unless your file shares intentionally grant broad access through BUILTIN\\Users; otherwise those ACL entries are ignored."
                    checked={fields.treat_builtin_users_as_member === true} disabled={disabled}
                    error={fieldError('/additionalFields/treat_builtin_users_as_member')}
                    onChange={(value) => updateAdditional('treat_builtin_users_as_member', value)} />
            </EditorPanel>

            <EditorPanel title="Limits" description="Bound result volume and permission-checking work for predictable responses.">
                <NumberField id={`${id}-top-n`} label="Default results" value={fields.default_top_n}
                    min={AZURE_FILES_INDEX_LIMITS.default_top_n.min} max={AZURE_FILES_INDEX_LIMITS.default_top_n.max}
                    disabled={disabled} error={fieldError('/additionalFields/default_top_n')}
                    help="Results returned when the agent does not ask for a count."
                    onChange={(value) => updateAdditional('default_top_n', value)} />
                <NumberField id={`${id}-candidates`} label="Candidates examined" value={fields.max_candidates}
                    min={AZURE_FILES_INDEX_LIMITS.max_candidates.min} max={AZURE_FILES_INDEX_LIMITS.max_candidates.max}
                    disabled={disabled} error={fieldError('/additionalFields/max_candidates')}
                    help="Search hits examined before permission checks."
                    onChange={(value) => updateAdditional('max_candidates', value)} />
                <NumberField id={`${id}-snippet-chars`} label="Snippet length" value={fields.max_snippet_chars}
                    min={AZURE_FILES_INDEX_LIMITS.max_snippet_chars.min} max={AZURE_FILES_INDEX_LIMITS.max_snippet_chars.max}
                    disabled={disabled} error={fieldError('/additionalFields/max_snippet_chars')}
                    help="Maximum characters returned per result."
                    onChange={(value) => updateAdditional('max_snippet_chars', value)} />
                <NumberField id={`${id}-time-budget`} label="Time budget" value={fields.time_budget_seconds}
                    min={AZURE_FILES_INDEX_LIMITS.time_budget_seconds.min} max={AZURE_FILES_INDEX_LIMITS.time_budget_seconds.max}
                    disabled={disabled} error={fieldError('/additionalFields/time_budget_seconds')}
                    help="Seconds allowed for ACL checks; files not checked in time are withheld."
                    onChange={(value) => updateAdditional('time_budget_seconds', value)} />
            </EditorPanel>

            <EditorPanel title="Required Azure roles"
                description="Grant the app identity Search Index Data Reader on the search service; Storage File Data Privileged Reader and Reader on each storage account.">
                <p className="text-sm leading-relaxed text-text-2">
                    Key authentication only covers Azure AI Search. Live ACL checks still need the app identity to read file
                    security descriptors from every listed Azure Files storage account.
                </p>
                {permissionMode === 'live_acl' ? <EditorDependents>
                    <p className="text-xs leading-relaxed text-text-3">
                        The connection test verifies the index and reports share checks independently so administrators can fix missing roles before agents use the action.
                    </p>
                </EditorDependents> : null}
            </EditorPanel>
        </div>
    );
}
