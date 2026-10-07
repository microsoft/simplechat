// DataManagementEncryption.tsx
// Encryption: separates mode, key state and replacement risk so admins can see what older backups will accept.

import { useState } from 'react';
import { KeyRound, Loader2 } from 'lucide-react';
import { type DmEditableKey, errorMessage, generateEncryptionKey } from '../../../lib/dataManagement';
import { LINKED_SECTION_IDS, keyStorageLabel, readKeyStorage } from '../../../lib/dataManagementLogic';
import { currentEpoch, isCurrentEpoch, useDataManagementStore } from '../../../stores/dataManagementStore';
import { toast } from '../../../stores/toastStore';
import { ConfirmDialog } from '../../ui/ConfirmDialog';
import { GlassButton } from '../../ui/primitives';
import { DmField } from './DmField';
import { DmIntro, DmNotice, type DmCardProps } from './DmShared';
import { useSaveFirst } from './useSaveFirst';
import {
    DmCardSaveError,
    DmDefinitionReadout,
    DmLoadError,
    DmLoadingRows,
    hasGeneratedKey,
    useDmConfigCard,
} from './DataManagementConfigParts';

const ENCRYPTION_KEYS: readonly DmEditableKey[] = ['encryption_enabled'];

function KeyVaultNotice({ onNavigate }: { onNavigate: (sectionId: string) => void }) {
    const settings = useDataManagementStore((state) => state.settings);
    const storage = readKeyStorage(settings);
    const keyVaultEnabled = settings?.key_vault_secret_storage_enabled === true;
    const keyVaultConfigured = settings?.key_vault_name_configured === true;

    if (storage === 'key_vault') {
        return (
            <DmNotice
                tone="success"
                role="status"
                title="Backup encryption key is stored in Key Vault"
                action={
                    <GlassButton
                        type="button"
                        variant="subtle"
                        size="sm"
                        onClick={() => onNavigate(LINKED_SECTION_IDS.keyVault)}
                    >
                        Review Key Vault settings
                    </GlassButton>
                }
            >
                This key is protected by Azure Key Vault. Review Key Vault settings before changing the vault
                or identity.
            </DmNotice>
        );
    }

    if (keyVaultEnabled && keyVaultConfigured) {
        return (
            <DmNotice
                tone="info"
                role="status"
                title="Key Vault is enabled for future backup keys"
                action={
                    <GlassButton
                        type="button"
                        variant="subtle"
                        size="sm"
                        onClick={() => onNavigate(LINKED_SECTION_IDS.keyVault)}
                    >
                        Open Key Vault settings
                    </GlassButton>
                }
            >
                Generate a new backup encryption key to store it in Key Vault. Existing settings-stored keys
                stay there until they are replaced.
            </DmNotice>
        );
    }

    return (
        <DmNotice
            tone="warning"
            role="status"
            title="Key Vault is strongly recommended"
            action={
                <GlassButton
                    type="button"
                    variant="subtle"
                    size="sm"
                    onClick={() => onNavigate(LINKED_SECTION_IDS.keyVault)}
                >
                    Enable Key Vault
                </GlassButton>
            }
        >
            Generated backup encryption keys are stored in the data-management settings document when Key
            Vault secret storage is not enabled or no vault is configured.
        </DmNotice>
    );
}

export function DataManagementEncryption({ help, onNavigate, disabled }: DmCardProps) {
    const { status, loadError, settings, saveError, saving } = useDmConfigCard(ENCRYPTION_KEYS);
    const { ensure, dialog } = useSaveFirst();
    const [confirmingReplace, setConfirmingReplace] = useState(false);
    const [generating, setGenerating] = useState(false);
    const [generationError, setGenerationError] = useState<string | null>(null);
    const storage = readKeyStorage(settings);
    const keyExists = hasGeneratedKey(settings);
    const locked = disabled || saving || generating;
    const replaceSettingsKey = keyExists && storage === 'settings';

    const runGenerate = async () => {
        const token = currentEpoch();
        setGenerating(true);
        setGenerationError(null);
        try {
            const response = await useDataManagementStore.getState().trackRequest(generateEncryptionKey());
            if (!isCurrentEpoch(token)) return;
            useDataManagementStore.getState().rebase(response);
            toast.success('Backup encryption key generated.');
            setConfirmingReplace(false);
        } catch (error) {
            if (!isCurrentEpoch(token)) return;
            setGenerationError(errorMessage(error, 'Backup encryption key could not be generated.'));
        } finally {
            if (isCurrentEpoch(token)) {
                setGenerating(false);
            }
        }
    };

    const requestGenerate = async () => {
        setGenerationError(null);
        if (!(await ensure('generate-key'))) return;
        if (keyExists) {
            setConfirmingReplace(true);
            return;
        }
        await runGenerate();
    };

    return (
        <div data-testid="dm-encryption" className="@container min-w-0 py-1">
            {help ? <DmIntro>{help}</DmIntro> : null}
            {status === 'error' ? (
                <DmLoadError message={loadError} />
            ) : status !== 'ready' ? (
                <DmLoadingRows rows={4} />
            ) : (
                <div className="space-y-3">
                    <DmCardSaveError message={saveError} />
                    <div className="flex flex-wrap items-start justify-between gap-3">
                        <div className="min-w-0 flex-1 basis-64">
                            <DmField dmKey="encryption_enabled" emphasis="primary" disabled={disabled} />
                        </div>
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            disabled={locked}
                            onClick={() => void requestGenerate()}
                        >
                            {generating ? (
                                <Loader2 size={14} aria-hidden="true" className="animate-spin" />
                            ) : (
                                <KeyRound size={14} aria-hidden="true" />
                            )}
                            {keyExists ? 'Replace key' : 'Generate key'}
                        </GlassButton>
                    </div>
                    <dl className="grid gap-2 @xl:grid-cols-2">
                        <DmDefinitionReadout label="Key storage" value={keyStorageLabel(storage)} />
                        <DmDefinitionReadout
                            label="Key"
                            value={keyExists ? 'Generated (hidden)' : 'Not generated'}
                        />
                    </dl>
                    {generationError ? (
                        <DmNotice tone="danger" role="alert" title="Key generation failed">
                            {generationError}
                        </DmNotice>
                    ) : null}
                    <KeyVaultNotice onNavigate={onNavigate} />
                    <DmNotice tone="warning" role="note">
                        Restore review checks each backup against the encryption mode and key identity it was
                        written with. Turning encryption on or off, or replacing a key stored in settings, can
                        make earlier backups fail review until settings match again; Key Vault backups keep
                        the secret version they used.
                    </DmNotice>
                    {confirmingReplace ? (
                        <ConfirmDialog
                            title="Replace backup encryption key?"
                            description={
                                replaceSettingsKey
                                    ? 'Backups encrypted with the current settings-stored key can no longer pass restore review after it is replaced.'
                                    : 'Earlier backups keep the Key Vault secret version they were written with. New backups use the replacement key.'
                            }
                            confirmLabel="Replace key"
                            confirmIcon={<KeyRound size={14} aria-hidden="true" />}
                            tone={replaceSettingsKey ? 'danger' : 'primary'}
                            busy={generating}
                            onConfirm={() => void runGenerate()}
                            onClose={() => {
                                if (!generating) setConfirmingReplace(false);
                            }}
                        >
                            <p className="text-xs leading-relaxed text-text-2">
                                This changes the key used by future encrypted backups.
                            </p>
                        </ConfirmDialog>
                    ) : null}
                    {dialog}
                </div>
            )}
        </div>
    );
}
