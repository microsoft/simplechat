// CustomConnectionFields.tsx

import type { CustomApiTypeDescriptor } from '../../lib/customModelConnections';
import type { ModelConnection } from '../../lib/modelConnections';

interface Props {
    draft: ModelConnection;
    descriptors: CustomApiTypeDescriptor[];
    errors: Record<string, string>;
    busy: boolean;
    inputClass: string;
    onChange: (path: string, value: string) => void;
}

function TextField({ label, field, value, secret = false, help, ...props }: Props & {
    label: string;
    field: string;
    value: string;
    secret?: boolean;
    help?: string;
}) {
    const id = `custom-${field.replace('.', '-')}`;
    const key = field.split('.').at(-1) || field;
    return (
        <div className="py-2">
            <label htmlFor={id} className="mb-1.5 block text-sm font-medium text-text-1">{label}</label>
            <input
                id={id}
                type={secret ? 'password' : 'text'}
                autoComplete={secret ? 'new-password' : 'off'}
                className={props.inputClass}
                value={value}
                disabled={props.busy}
                spellCheck={false}
                onChange={(event) => props.onChange(field, event.target.value)}
            />
            {help ? <p className="mt-1 text-xs text-text-3">{help}</p> : null}
            {props.errors[key] ? <p role="alert" className="mt-1 text-xs text-danger">{props.errors[key]}</p> : null}
        </div>
    );
}

export function CustomConnectionFields(props: Props) {
    const { draft, descriptors, errors, busy, inputClass, onChange } = props;
    const descriptor = descriptors.find((option) => option.value === draft.api_type);
    return (
        <div data-testid="custom-connection-fields">
            <div className="py-2">
                <label htmlFor="custom-api-type" className="mb-1.5 block text-sm font-medium text-text-1">Custom API type</label>
                <select
                    id="custom-api-type"
                    className={inputClass}
                    value={draft.api_type || ''}
                    disabled={busy || !descriptors.length}
                    onChange={(event) => onChange('api_type', event.target.value)}
                >
                    {!descriptors.length ? <option value="">API types unavailable; reload connections</option> : null}
                    {descriptors.length ? <option value="">Choose a Custom API type</option> : null}
                    {descriptors.map((option) => <option key={option.value} value={option.value}>{option.label}</option>)}
                </select>
                {descriptor ? <p className="mt-1 text-xs text-text-3">{descriptor.description}</p> : null}
                {errors.api_type ? <p role="alert" className="text-xs text-danger">{errors.api_type}</p> : null}
            </div>
            <div className="py-2">
                <label htmlFor="custom-url-mode" className="mb-1.5 block text-sm font-medium text-text-1">URL handling</label>
                <select
                    id="custom-url-mode"
                    className={inputClass}
                    value={draft.connection?.url_mode || 'auto'}
                    disabled={busy}
                    onChange={(event) => onChange('connection.url_mode', event.target.value)}
                >
                    <option value="auto">Automatic for this API type</option>
                    <option value="exact">Exact configured API base / messages URL</option>
                </select>
                <p className="mt-1 text-xs text-text-3">
                    Automatic preserves gateway prefixes. Exact adds no version or deployment prefix; for Anthropic, enter the full messages URL.
                </p>
            </div>
            {descriptor?.versionField ? (
                <TextField
                    {...props}
                    label={descriptor.value === 'anthropic' ? 'Anthropic version' : 'API version'}
                    field={`connection.${descriptor.versionField}`}
                    value={String(draft.connection?.[descriptor.versionField] ?? descriptor.defaultVersion)}
                />
            ) : (
                <p className="py-2 text-xs text-text-3">This API type does not use an Azure api-version query parameter.</p>
            )}
            <details className="my-2 text-xs text-text-3">
                <summary className="cursor-pointer py-1 text-text-2">Client certificate (mTLS)</summary>
                <p>Optional deployment-mounted PEM files. Do not paste certificates or private keys. TLS verification cannot be disabled.</p>
                <TextField {...props} label="Client certificate path" field="connection.client_cert_path" value={draft.connection?.client_cert_path || ''} />
                <TextField {...props} label="Client private key path" field="connection.client_key_path" value={draft.connection?.client_key_path || ''} help="Leave blank when the certificate PEM includes its private key." />
            </details>
        </div>
    );
}

export function CustomAuthenticationFields(props: Props) {
    const { draft, descriptors } = props;
    const auth = draft.auth ?? {};
    const descriptor = descriptors.find((option) => option.value === draft.api_type);
    return (
        <>
            {auth.type === 'api_key' ? (
                <details className="my-2 text-xs text-text-3">
                    <summary className="cursor-pointer py-1 text-text-2">Gateway API key header</summary>
                    <p>Default: {descriptor?.defaultApiKeyHeader || 'Authorization'}{descriptor?.defaultApiKeyPrefix ? `: ${descriptor.defaultApiKeyPrefix} …` : ''}. A named override with an empty prefix sends the key without a prefix.</p>
                    <TextField {...props} label="API key header override" field="auth.api_key_header" value={auth.api_key_header || ''} />
                    <TextField {...props} label="API key prefix" field="auth.api_key_prefix" value={auth.api_key_prefix ?? (auth.api_key_header ? '' : descriptor?.defaultApiKeyPrefix ?? '')} />
                </details>
            ) : null}
            {auth.type === 'bearer' ? (
                <TextField
                    {...props} label="Bearer token" field="auth.bearer_token" value={auth.bearer_token || ''} secret
                    help={draft.has_bearer_token ? 'A token is stored. Leave blank to keep it.' : 'Stored in Key Vault when configured.'}
                />
            ) : null}
            {auth.type === 'oauth2_client_credentials' ? (
                <>
                    <TextField {...props} label="OAuth2 token URL" field="auth.token_url" value={auth.token_url || ''} help="The same DNS, private-network, TLS, and no-redirect policy applies to token requests." />
                    <TextField {...props} label="OAuth2 client ID" field="auth.client_id" value={auth.client_id || ''} />
                    <TextField {...props} label="OAuth2 client secret" field="auth.client_secret" value={auth.client_secret || ''} secret help={draft.has_client_secret ? 'A secret is stored. Leave blank to keep it.' : 'Stored in Key Vault when configured.'} />
                    <TextField {...props} label="OAuth2 scope (optional)" field="auth.scope" value={auth.scope || ''} />
                </>
            ) : null}
        </>
    );
}
