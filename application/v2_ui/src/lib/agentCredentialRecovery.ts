// agentCredentialRecovery.ts

/** Recovery links can only open the named agent's local connection editor. */
export function normalizeAgentCredentialEditUrl(value: unknown): string | null {
    if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
    if (!('can_edit' in value) || value.can_edit !== true
        || !('edit_url' in value) || typeof value.edit_url !== 'string'
        || !('scope' in value)) return null;
    const patterns = {
        personal: /^\/v2\/workspace\/agents\/([A-Za-z0-9._~%-]+)\?section=model$/,
        group: /^\/v2\/groups\/([A-Za-z0-9._~%-]+)\/agents\/([A-Za-z0-9._~%-]+)\?section=model$/,
        global: /^\/v2\/admin\/agents\/([A-Za-z0-9._~%-]+)\?section=model$/,
    };
    const scope = value.scope;
    if (scope !== 'personal' && scope !== 'group' && scope !== 'global') return null;
    const match = patterns[scope].exec(value.edit_url);
    if (!match) return null;
    try {
        for (const segment of match.slice(1)) {
            const id = decodeURIComponent(segment);
            if (!id || id.length > 512 || id !== id.trim() || id === '.' || id === '..'
                || /[/\\?#,\x00-\x1f\x7f]/.test(id)) return null;
        }
    } catch {
        // A malformed encoded identifier must never become a navigation target.
        return null;
    }
    return value.edit_url;
}
