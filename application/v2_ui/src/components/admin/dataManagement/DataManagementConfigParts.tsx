// DataManagementConfigParts.tsx
// Shared card chrome keeps the three backup configuration cards aligned without moving settings ownership into foundation files.

import { useEffect, useMemo, type ReactNode } from 'react';
import { RefreshCw } from 'lucide-react';
import { type DmEditableKey, type DmSettings } from '../../../lib/dataManagement';
import { dmDirtyKeys } from '../../../lib/dataManagementLogic';
import { useDataManagementStore } from '../../../stores/dataManagementStore';
import { GlassButton, Skeleton } from '../../ui/primitives';
import { DmNotice } from './DmShared';

export function useDmConfigCard(ownerKeys: readonly DmEditableKey[], fallbackForSaveError = false) {
    const status = useDataManagementStore((state) => state.status);
    const loadError = useDataManagementStore((state) => state.loadError);
    const settings = useDataManagementStore((state) => state.settings);
    const draft = useDataManagementStore((state) => state.draft);
    const saveError = useDataManagementStore((state) => state.saveError);
    const saving = useDataManagementStore((state) => state.saving);

    useEffect(() => {
        void useDataManagementStore.getState().ensureLoaded();
    }, []);

    const ownedSaveError = useMemo(() => {
        if (!saveError) return null;
        const dirty = dmDirtyKeys(settings, draft);
        const ownsDirtyKey = dirty.some((key) => ownerKeys.includes(key));
        if (ownsDirtyKey || (fallbackForSaveError && dirty.length === 0)) {
            return saveError;
        }
        return null;
    }, [draft, fallbackForSaveError, ownerKeys, saveError, settings]);

    return {
        status,
        loadError,
        settings,
        saving,
        saveError: ownedSaveError,
    };
}

export function DmLoadingRows({ rows = 5 }: { rows?: number }) {
    return (
        <div className="space-y-3" aria-label="Loading backup settings">
            {Array.from({ length: rows }).map((_, index) => (
                <div key={index} className="space-y-2 rounded-xl border border-edge bg-surface-solid p-3">
                    <Skeleton className="h-4 w-40" />
                    <Skeleton className="h-9 w-full" />
                </div>
            ))}
        </div>
    );
}

export function DmLoadError({ message }: { message: string | null }) {
    return (
        <DmNotice
            tone="danger"
            role="alert"
            title="Backup settings could not be loaded"
            action={
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    onClick={() => void useDataManagementStore.getState().reload()}
                >
                    <RefreshCw size={14} aria-hidden="true" />
                    Retry
                </GlassButton>
            }
        >
            {message || 'Reload the settings and try again.'}
        </DmNotice>
    );
}

export function DmCardSaveError({ message }: { message: string | null }) {
    if (!message) return null;
    return (
        <DmNotice tone="danger" role="alert" title="Save failed" className="mb-3">
            {message}
        </DmNotice>
    );
}

export function DmDefinitionReadout({
    label,
    value,
    children,
}: {
    label: string;
    value: ReactNode;
    children?: ReactNode;
}) {
    return (
        <div className="min-w-0 rounded-lg border border-edge bg-surface-1 px-3 py-2">
            <dt className="text-xs font-medium text-text-3">{label}</dt>
            <dd className="mt-0.5 text-sm font-semibold break-words text-text-1">{value}</dd>
            {children ? <dd className="mt-1 text-xs leading-relaxed text-text-3">{children}</dd> : null}
        </div>
    );
}

export function hasGeneratedKey(settings: DmSettings | null | undefined): boolean {
    const reference = settings?.encryption_key_reference;
    return typeof reference === 'string' ? reference.trim().length > 0 : Boolean(reference);
}
