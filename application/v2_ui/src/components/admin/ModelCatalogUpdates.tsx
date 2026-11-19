// ModelCatalogUpdates.tsx
import { useEffect, useState } from 'react';
import { request } from '../../lib/apiClient';
import { GlassButton, Toggle } from '../ui/primitives';

interface Manifest {
    revision: string;
    publishedAt?: string;
    keyId?: string;
    [key: string]: unknown;
}

interface UpdateStatus {
    etag: string;
    onlineEnabled: boolean;
    publisherConfigured: boolean;
    repository: string;
    discoveryUrl: string;
    installed: Manifest;
    canRollback: boolean;
    check?: { status: string; attemptedAt: string; downloadUrl?: string; digest?: string };
}

interface Preview {
    digest: string | null;
    etag: string;
    manifest: Manifest;
    changes: { added: string[]; changed: string[]; removed: string[]; operationMetadataChanged: boolean };
}

export function ModelCatalogUpdates({ onApplied, locked }: { onApplied: () => void; locked: boolean }) {
    const [status, setStatus] = useState<UpdateStatus | null>(null);
    const [preview, setPreview] = useState<Preview | null>(null);
    const [rollback, setRollback] = useState(false);
    const [busy, setBusy] = useState(false);
    const [notice, setNotice] = useState<{ text: string; failed: boolean } | null>(null);

    useEffect(() => {
        const controller = new AbortController();
        request<UpdateStatus>('/api/admin/model-catalog/updates', { signal: controller.signal })
            .then(setStatus)
            .catch((error: unknown) => {
                if (!controller.signal.aborted) setNotice({
                    text: error instanceof Error ? error.message : 'Unable to load catalog update status.', failed: true,
                });
            });
        return () => controller.abort();
    }, []);

    async function run(operation?: string, body: Record<string, unknown> = {}) {
        if (busy) return false;
        setBusy(true);
        setNotice(null);
        try {
            const options = operation ? { method: 'POST', body: { operation, ...body } } : {};
            if (operation && ['upload', 'preview', 'rollback-preview'].includes(operation)) {
                const result = await request<Preview>('/api/admin/model-catalog/updates', options);
                setPreview(result);
                setRollback(operation === 'rollback-preview');
            } else {
                const result = await request<UpdateStatus>('/api/admin/model-catalog/updates', options);
                setStatus(result);
                setPreview(null);
                if (operation === 'apply' || operation === 'rollback') {
                    setNotice({ text: 'Catalog revision applied. New model operations use this revision.', failed: false });
                    onApplied();
                }
            }
            return true;
        } catch (error) {
            setNotice({
                text: error instanceof Error ? error.message : 'Unable to update the catalog. Reload and retry.',
                failed: true,
            });
            return false;
        } finally {
            setBusy(false);
        }
    }

    return (
        <section aria-label="Catalog updates" aria-busy={busy} className="mb-5 border-b border-line pb-4">
            <h3 className="mb-2 text-sm font-semibold">Catalog updates</h3>
            {notice && <p role={notice.failed ? 'alert' : 'status'} className={notice.failed ? 'text-sm text-danger' : 'text-sm text-ok'}>{notice.text}</p>}
            {status?.installed ? (
                <fieldset disabled={busy || locked} className="min-w-0 space-y-3">
                    <legend className="sr-only">Signed catalog updates</legend>
                    <p className="text-sm">Installed: {status.installed.revision} · Published: {status.installed.publishedAt}</p>
                    <p className="break-all text-xs text-text-3">Official repository: {status.repository}<br />Discovery URL: {status.discoveryUrl}</p>
                    <p className="max-w-[72ch] text-sm text-text-2">Online checks contact GitHub from the server. No chats, documents, connection settings, or credentials are sent. Packages are never installed automatically.</p>
                    <Toggle
                        label="Allow online catalog update checks"
                        checked={status.onlineEnabled}
                        disabled={busy || locked}
                        onChange={async (enabled) => {
                            const previous = status;
                            setStatus({ ...status, onlineEnabled: enabled });
                            const saved = await run('online', { enabled, etag: previous.etag });
                            if (!saved) setStatus(previous);
                        }}
                    />
                    {!status.publisherConfigured && <p className="text-sm text-warn">Publisher verification key is not configured. Install the trusted public key before publishing or importing packages.</p>}
                    <div className="flex flex-wrap items-center gap-3">
                        <GlassButton type="button" size="sm" variant="subtle" disabled={!status.onlineEnabled || !status.publisherConfigured}
                            onClick={() => void run('check')}>Check for updates</GlassButton>
                        <label className="min-w-0 text-sm">
                            Upload signed package
                            <input type="file" accept=".json,application/json" className="block max-w-full text-xs" disabled={!status.publisherConfigured}
                                onChange={async (event) => {
                                    const file = event.target.files?.[0];
                                    if (!file) return;
                                    if (file.size > 1536000) {
                                        setNotice({ text: 'The catalog package exceeds its size limit.', failed: true });
                                        return;
                                    }
                                    try {
                                        const text = await file.text();
                                        await run('upload', { package: text });
                                    } catch {
                                        setNotice({ text: 'Unable to read the selected package.', failed: true });
                                    }
                                }} />
                        </label>
                        <GlassButton type="button" size="sm" variant="subtle" disabled={!status.canRollback}
                            onClick={() => void run('rollback-preview')}>Preview rollback</GlassButton>
                        <GlassButton type="button" size="sm" variant="subtle" onClick={() => void run()}>Reload update status</GlassButton>
                    </div>
                    {status.check && (
                        <div className="space-y-2 text-xs">
                            <p>Last check: {status.check.status} · {status.check.attemptedAt}</p>
                            {status.check.downloadUrl && <p className="break-all">Download URL: {status.check.downloadUrl}</p>}
                            {status.check.status === 'available' && <GlassButton type="button" size="sm" onClick={() => void run('preview', { digest: status.check?.digest })}>Preview available update</GlassButton>}
                        </div>
                    )}
                    {preview && (
                        <div className="space-y-2">
                            <h4 className="text-sm font-semibold">Review {rollback ? 'rollback' : 'update'}: {preview.manifest.revision}</h4>
                            <p className="text-sm">{rollback && !preview.digest ? 'Bundled application catalog.' : 'Publisher signature verified.'}</p>
                            <p className="break-all text-xs">SHA-256 package digest: {preview.digest || 'bundled'}</p>
                            <pre className="max-h-64 overflow-auto whitespace-pre-wrap break-all text-xs">{JSON.stringify({ manifest: preview.manifest, changes: preview.changes }, null, 2)}</pre>
                            <p className="text-sm">Applying changes affects new model operations across this deployment. Existing connection overrides and custom profiles are preserved.</p>
                            <GlassButton type="button" size="sm" onClick={() => void run(rollback ? 'rollback' : 'apply', { digest: preview.digest, etag: preview.etag })}>{rollback ? 'Apply rollback' : 'Apply catalog update'}</GlassButton>
                            <GlassButton type="button" size="sm" variant="subtle" onClick={() => setPreview(null)}>Cancel update preview</GlassButton>
                        </div>
                    )}
                </fieldset>
            ) : <GlassButton type="button" size="sm" variant="subtle" disabled={busy} onClick={() => void run()}>Reload update status</GlassButton>}
        </section>
    );
}
