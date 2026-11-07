// CustomNetworkPolicyEditor.tsx

import { useEffect, useState } from 'react';
import type { CustomNetworkPolicy } from '../../lib/customModelConnections';
import { saveCustomNetworkPolicy } from '../../lib/modelConnections';
import { toast } from '../../stores/toastStore';
import { GlassButton } from '../ui/primitives';

export function CustomNetworkPolicyEditor({ policy, onSaved }: {
    policy: CustomNetworkPolicy;
    onSaved: (policy: CustomNetworkPolicy) => void;
}) {
    const [draft, setDraft] = useState(policy);
    const [saving, setSaving] = useState(false);
    const [error, setError] = useState('');
    useEffect(() => setDraft(policy), [policy]);

    const save = async () => {
        setSaving(true);
        setError('');
        try {
            const response = await saveCustomNetworkPolicy(draft);
            onSaved(response.settings);
            toast.success('Saved Custom network policy.');
        } catch {
            setError('The Custom network policy could not be saved.');
        } finally {
            setSaving(false);
        }
    };

    return (
        <details className="my-3 rounded-lg border border-edge p-3 text-xs text-text-3">
            <summary className="cursor-pointer font-medium text-text-2">Custom endpoint network policy</summary>
            <p className="my-2">Applies to all Custom connections and OAuth2 token requests. Loopback, link-local, platform metadata addresses, redirects, and environment proxies remain blocked.</p>
            <label className="my-2 flex items-center gap-2">
                <input type="checkbox" checked={draft.allow_private_custom_model_endpoints} disabled={saving} onChange={(event) => setDraft({ ...draft, allow_private_custom_model_endpoints: event.target.checked })} />
                Allow private Custom endpoint hosts
            </label>
            <label className="my-2 flex items-center gap-2">
                <input type="checkbox" checked={draft.allow_insecure_custom_model_endpoints} disabled={saving} onChange={(event) => setDraft({ ...draft, allow_insecure_custom_model_endpoints: event.target.checked })} />
                Allow plaintext HTTP (also requires private-host permission)
            </label>
            <p className="mb-2 text-warn">HTTP transmits prompts and credentials without TLS. Prefer a private CA bundle instead.</p>
            <label htmlFor="custom-global-ca-path" className="mb-1 block text-text-2">Custom CA bundle path</label>
            <input
                id="custom-global-ca-path"
                className="w-full rounded-lg border border-edge bg-surface-1 px-3 py-2 text-text-1"
                value={draft.custom_model_endpoint_ca_bundle_path}
                disabled={saving}
                spellCheck={false}
                onChange={(event) => setDraft({ ...draft, custom_model_endpoint_ca_bundle_path: event.target.value })}
            />
            <p className="my-2">Optional deployment-mounted trust bundle. Empty uses public roots. Certificate verification is always required for HTTPS.</p>
            {error ? <p role="alert" className="my-2 text-danger">{error}</p> : null}
            <GlassButton type="button" size="sm" variant="subtle" disabled={saving} onClick={() => void save()}>
                {saving ? 'Saving…' : 'Save Custom network policy'}
            </GlassButton>
        </details>
    );
}
