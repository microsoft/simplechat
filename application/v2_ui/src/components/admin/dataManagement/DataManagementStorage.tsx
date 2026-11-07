// DataManagementStorage.tsx
// Storage: isolates backup artifacts because restore review depends on the exact account, path and sign-in used.

import { useState } from 'react';
import { Loader2, PlugZap } from 'lucide-react';
import { type DmEditableKey, errorMessage, testBackupStorage } from '../../../lib/dataManagement';
import { asText, buildDmSettingsPayload, readDmValues } from '../../../lib/dataManagementLogic';
import { currentEpoch, isCurrentEpoch, useDataManagementStore } from '../../../stores/dataManagementStore';
import { GlassButton } from '../../ui/primitives';
import { DmField, useDmValue } from './DmField';
import { DmIntro, DmNotice, type DmCardProps } from './DmShared';
import { DmCardSaveError, DmLoadError, DmLoadingRows, useDmConfigCard } from './DataManagementConfigParts';

const STORAGE_KEYS: readonly DmEditableKey[] = [
    'backup_storage_authentication_type',
    'backup_storage_blob_endpoint',
    'backup_storage_connection_string',
    'backup_storage_container_name',
    'backup_storage_path_prefix',
];

type StorageTestState = { tone: 'success'; message: string } | { tone: 'danger'; message: string } | null;

function storageSuccessMessage(containerName: string, created?: boolean, exists?: boolean): string {
    if (created) return `Connected. Container ${containerName} was created.`;
    if (exists) return `Connected. Container ${containerName} was found.`;
    return `Connected. Container ${containerName} was not found.`;
}

export function DataManagementStorage({ help, disabled }: DmCardProps) {
    const { status, loadError, saveError, saving } = useDmConfigCard(STORAGE_KEYS);
    const authType = asText(useDmValue('backup_storage_authentication_type'), 'managed_identity');
    const [testing, setTesting] = useState(false);
    const [testState, setTestState] = useState<StorageTestState>(null);
    const locked = disabled || saving || testing;

    const runTest = async () => {
        const token = currentEpoch();
        setTesting(true);
        setTestState(null);
        try {
            const state = useDataManagementStore.getState();
            if (!state.settings) {
                throw new Error('Backup settings have not loaded yet.');
            }
            const payload = buildDmSettingsPayload(readDmValues(state.settings, state.draft));
            const result = await state.trackRequest(testBackupStorage(payload));
            if (!isCurrentEpoch(token)) return;
            const containerName =
                result.container_name || asText(payload.backup_storage_container_name, 'simplechat-backups');
            setTestState({
                tone: 'success',
                message: storageSuccessMessage(
                    containerName,
                    result.container_created,
                    result.container_exists,
                ),
            });
        } catch (error) {
            if (!isCurrentEpoch(token)) return;
            setTestState({
                tone: 'danger',
                message: errorMessage(error, 'Backup storage connection test failed.'),
            });
        } finally {
            if (isCurrentEpoch(token)) {
                setTesting(false);
            }
        }
    };

    return (
        <div data-testid="dm-storage" className="@container min-w-0 py-1">
            {help ? <DmIntro>{help}</DmIntro> : null}
            {status === 'error' ? (
                <DmLoadError message={loadError} />
            ) : status !== 'ready' ? (
                <DmLoadingRows rows={5} />
            ) : (
                <div className="space-y-3">
                    <DmCardSaveError message={saveError} />
                    <DmNotice tone="info" role="note">
                        Use a storage account dedicated to backups. While Enhanced Citations is on, saving is
                        refused if backup storage uses the same connection string or Blob endpoint.
                    </DmNotice>
                    <DmField dmKey="backup_storage_authentication_type" disabled={disabled} />
                    {authType === 'connection_string' ? (
                        <DmField dmKey="backup_storage_connection_string" disabled={disabled} />
                    ) : (
                        <DmField dmKey="backup_storage_blob_endpoint" disabled={disabled} />
                    )}
                    <DmField dmKey="backup_storage_container_name" disabled={disabled} />
                    <DmField dmKey="backup_storage_path_prefix" disabled={disabled} />
                    <div className="rounded-xl border border-edge bg-surface-solid p-3">
                        <div className="flex flex-wrap items-start justify-between gap-3">
                            <div className="min-w-0 flex-1 basis-64">
                                <p className="text-sm font-semibold text-text-1">Test storage</p>
                                <p className="mt-0.5 text-xs leading-relaxed text-text-3">
                                    Sends the current values without saving. The test creates the container if
                                    it is missing, and the dedicated-storage check compares against the saved
                                    Enhanced Citations settings.
                                </p>
                            </div>
                            <GlassButton
                                type="button"
                                variant="subtle"
                                size="sm"
                                disabled={locked}
                                onClick={() => void runTest()}
                            >
                                {testing ? (
                                    <Loader2 size={14} aria-hidden="true" className="animate-spin" />
                                ) : (
                                    <PlugZap size={14} aria-hidden="true" />
                                )}
                                {testing ? 'Testing…' : 'Test storage'}
                            </GlassButton>
                        </div>
                        <div aria-live="polite" className="mt-3">
                            {testState ? (
                                <DmNotice
                                    tone={testState.tone}
                                    role={testState.tone === 'danger' ? 'alert' : 'status'}
                                >
                                    {testState.message}
                                </DmNotice>
                            ) : null}
                        </div>
                    </div>
                    <DmNotice tone="warning" role="note">
                        Earlier backups record the container, path prefix and storage identity they were
                        written with. If any of those change, restore review rejects those backups until the
                        settings are changed back.
                    </DmNotice>
                </div>
            )}
        </div>
    );
}
