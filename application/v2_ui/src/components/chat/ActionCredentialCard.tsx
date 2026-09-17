// ActionCredentialCard.tsx

import { useEffect, useId, useRef, useState } from 'react';
import { KeyRound, LockKeyhole } from 'lucide-react';
import { GlassButton } from '../ui/primitives';
import { ActionIdentityCredentialForm } from '../workspaceActions/ActionIdentityCredentialForm';
import { ActionField, ACTION_INPUT_CLASS } from '../workspaceActions/ActionFields';
import {
    ACTION_AUTH_PROFILES, saveActionAuthCredentials,
    type ActionAuthRequirement, type ActionCredentialValues,
} from '../../lib/actionAuth';
import { actionAuthController, type ActionAuthInteraction, type ActionAuthSurface } from '../../lib/actionAuthController';
import { useActionAuthInteraction } from '../../lib/useActionAuth';
import { useBootstrapStore } from '../../stores/bootstrapStore';

export function ActionCredentialCard({ surface = 'chat' }: { surface?: ActionAuthSurface }) {
    const interaction = useActionAuthInteraction();
    if (!interaction || interaction.surface !== surface) return null;
    return <PrivateCredentialCard key={interaction.id} interaction={interaction} />;
}

function PrivateCredentialCard({ interaction }: { interaction: ActionAuthInteraction }) {
    const headingRef = useRef<HTMLHeadingElement>(null);
    const id = useId();
    const [sharingAccepted, setSharingAccepted] = useState(false);
    const workspace = useBootstrapStore((state) => state.data?.workspace);
    const manualAvailable = workspace?.enabled === true && workspace.sections?.identities?.enabled === true;
    const state = interaction.state;
    const requirement = state?.requirements[0];
    const shared = state?.uses_personal_credentials && state.shared_conversation;
    const checking = interaction.phase === 'checking';
    const cancel = () => actionAuthController.cancel(interaction.surface);

    useEffect(() => {
        const previous = document.activeElement as HTMLElement | null;
        headingRef.current?.focus();
        return () => { if (previous?.isConnected) previous.focus(); };
    }, []);

    return (
        <section aria-labelledby={`${id}-heading`} data-testid="action-credential-card"
            className="my-3 space-y-4 rounded-2xl border border-edge-strong bg-surface-sunken p-4"
            onKeyDown={(event) => {
                if (event.key === 'Escape') { event.preventDefault(); cancel(); }
            }}>
            <div className="flex flex-wrap items-center gap-2">
                <KeyRound size={18} className="text-accent" aria-hidden="true" />
                <h2 id={`${id}-heading`} ref={headingRef} tabIndex={-1} className="text-sm font-semibold text-text-1">Connect Yamcs</h2>
                <span className="ml-auto inline-flex items-center gap-1 text-xs text-text-3">
                    <LockKeyhole size={13} aria-hidden="true" /> Private to you
                </span>
            </div>
            <p className="text-xs text-text-3">
                Credentials are saved only to your personal identity. This form is not a chat message and is never sent to the model or other participants.
            </p>
            {interaction.repair ? <p role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                {interaction.executionStarted === true
                    ? 'The started request was interrupted. Connecting will not replay it. Review any existing results before deliberately submitting another request.'
                    : interaction.executionStarted === false
                        ? 'This request was not started. Connect your personal identity, then explicitly retry or submit the request.'
                        : 'Execution status is unconfirmed. Connecting will not replay the request. Review any saved results before deliberately trying again.'}
            </p> : null}
            {shared ? <div className="space-y-2 rounded-xl border border-warn/30 bg-warn-soft p-3" data-testid="action-auth-sharing-notice">
                <p className="text-sm text-text-1">{state.sharing_notice}</p>
                <p className="text-xs text-text-2">Previous prompts and results remain shared history. Connecting your account does not make earlier results private.</p>
                <label className="flex items-start gap-2 text-sm text-text-1">
                    <input type="checkbox" className="mt-1" checked={sharingAccepted} disabled={interaction.phase === 'saving'}
                        onChange={(event) => {
                            setSharingAccepted(event.target.checked);
                            actionAuthController.acknowledgeSharing(event.target.checked);
                        }} />
                    I understand that my message and returned data are shared.
                </label>
            </div> : null}
            {checking ? <p role="status" className="text-sm text-text-3">Checking your personal connection…</p> : null}
            {requirement && !checking ? (
                <CredentialRequirementForm key={JSON.stringify([requirement.id, requirement.profile, requirement.destination, requirement.reason])} requirement={requirement} interaction={interaction}
                    disabled={Boolean(shared && !sharingAccepted)} onCancel={cancel} />
            ) : <>
                {interaction.error ? <p role="alert" className="rounded-xl bg-danger-soft p-3 text-sm text-danger">{interaction.error}</p> : null}
                {state?.status === 'ready' ? <p role="status" className="text-sm text-text-2">Your personal connection is ready.</p> : null}
                <div className="flex flex-wrap justify-between gap-2">
                    <GlassButton type="button" size="sm" onClick={cancel}>Cancel</GlassButton>
                    {state?.status === 'ready' ? (
                        <GlassButton type="button" size="sm" variant="primary" disabled={checking || Boolean(shared && !sharingAccepted)}
                            onClick={() => actionAuthController.continue()}>
                            {interaction.repair ? 'Done — do not replay' : 'Continue with my account'}
                        </GlassButton>
                    ) : !interaction.repairTargetUnavailable
                        ? <GlassButton type="button" size="sm" disabled={checking} onClick={() => void actionAuthController.checkAgain()}>Check again</GlassButton>
                        : null}
                </div>
            </>}
            {requirement ? <details className="border-t border-edge pt-3 text-xs text-text-3">
                <summary className="cursor-pointer text-text-2">Set up this identity manually</summary>
                {manualAvailable ? <ol className="mt-2 list-decimal space-y-2 pl-5">
                    <li>Open <a href="/v2/workspace/identities" target="_blank" rel="noopener noreferrer" className="text-accent underline">My Workspace &gt; Identities</a> in a separate tab.</li>
                    <li>Add an identity named <strong>{requirement.identity_name}</strong> with Actions usage and {requirement.auth_type.replaceAll('_', ' ')} credentials.</li>
                    <li>Save it, return here, and choose Check again. Confirm the destination before continuing.</li>
                </ol> : <p className="mt-2">My Workspace &gt; Identities is not enabled here. Use this private form instead; personal action-authoring permission is not needed.</p>}
            </details> : null}
            {requirement ? <GlassButton type="button" size="sm" disabled={checking || interaction.phase === 'saving'}
                onClick={() => void actionAuthController.checkAgain()}>Check again</GlassButton> : null}
        </section>
    );
}

function CredentialRequirementForm({
    requirement, interaction, disabled, onCancel,
}: {
    requirement: ActionAuthRequirement;
    interaction: ActionAuthInteraction;
    disabled: boolean;
    onCancel: () => void;
}) {
    const id = useId();
    const credentialRejected = /rejected/.test(requirement.reason);
    const [identityId, setIdentityId] = useState('');
    const [replace, setReplace] = useState(credentialRejected);
    const [confirmed, setConfirmed] = useState(false);
    const saving = interaction.phase === 'saving';
    useEffect(() => {
        if (identityId && !requirement.identities.some((identity) => identity.id === identityId)) {
            setIdentityId(''); setReplace(false); setConfirmed(false);
        }
    }, [identityId, requirement.identities]);
    const save = async (credentials: ActionCredentialValues | undefined) => {
        if (!confirmed || disabled) return;
        const submission = actionAuthController.startSubmission();
        if (!submission) return;
        try {
            const state = await saveActionAuthCredentials(
                submission.requestId, requirement.id, identityId || undefined, credentials, submission.signal,
            );
            actionAuthController.completeSubmission(submission, state);
        } catch (error) {
            actionAuthController.failSubmission(submission, error);
        }
    };
    return (
        <div className="space-y-3">
            {credentialRejected ? <p role="status" className="rounded-xl bg-warn-soft p-3 text-sm text-warn">
                Yamcs rejected the saved credential. Enter a replacement or choose another working personal identity. No identity has been selected for you.
            </p> : requirement.reason === 'ambiguous' ? <p role="status" className="text-sm text-text-2">
                More than one compatible identity is available. Select the one you want to use; none has been chosen for you.
            </p> : requirement.reason === 'incompatible' ? <p role="status" className="text-sm text-text-2">
                The named identity is not compatible with this authentication profile. Create a compatible identity or choose another one.
            </p> : null}
            <dl className="grid gap-1 text-sm text-text-2">
                <div><dt className="inline font-medium">Action: </dt><dd className="inline">{requirement.action_name}</dd></div>
                <div><dt className="inline font-medium">Identity name: </dt><dd className="inline">{requirement.identity_name}</dd></div>
                <div><dt className="inline font-medium">Authentication: </dt><dd className="inline">{ACTION_AUTH_PROFILES[requirement.profile].label}</dd></div>
                <div className="break-all"><dt className="inline font-medium">Credential destination: </dt><dd className="inline">{requirement.destination}</dd></div>
            </dl>
            <ActionField id={`${id}-identity`} label="Personal identity">
                <select id={`${id}-identity`} className={ACTION_INPUT_CLASS} value={identityId} disabled={saving}
                    onChange={(event) => { setIdentityId(event.target.value); setReplace(credentialRejected); setConfirmed(false); }}>
                    <option value="">Create {requirement.identity_name}</option>
                    {requirement.identities.map((identity) => <option key={identity.id} value={identity.id}>
                        {identity.name} · {identity.auth_type.replaceAll('_', ' ')} · {identity.id}
                    </option>)}
                </select>
            </ActionField>
            {identityId ? <label className="flex items-center gap-2 text-sm text-text-2">
                <input type="checkbox" checked={replace} disabled={saving} onChange={(event) => setReplace(event.target.checked)} />
                Replace this identity’s credential
            </label> : null}
            <ActionIdentityCredentialForm key={`${identityId}:${replace}`} authType={requirement.auth_type}
                collectCredentials={!identityId || replace} busy={saving} disabled={disabled || !confirmed}
                error={interaction.error} submitLabel={interaction.repair ? 'Save connection' : 'Save and continue'}
                onSubmit={save} onCancel={onCancel}
                afterFields={<label className="flex items-start gap-2 text-sm text-text-2">
                    <input type="checkbox" className="mt-1" checked={confirmed} disabled={saving}
                        onChange={(event) => setConfirmed(event.target.checked)} />
                    I approve sending this identity’s credential to {requirement.destination}.
                </label>} />
        </div>
    );
}
