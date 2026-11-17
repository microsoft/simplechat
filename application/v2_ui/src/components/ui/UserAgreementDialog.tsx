// UserAgreementDialog.tsx
// The User Agreement an administrator requires before files are uploaded.
//
// Rendered by whichever component sends files (the chat composer, the documents explorer) from the
// state `useUserAgreementGate` keeps. It is the V2 counterpart of the classic upload modal and reads
// the same way: the agreement, a note when acceptance is remembered for the day, Cancel and Accept.
//
// The agreement is rendered with PlainMarkdown, the renderer the administrator's own preview uses, so
// what a person is asked to accept is what the administrator saw. It does not render raw HTML, so
// agreement text cannot inject markup into the page.
//
// Cancel, Escape, the close button and a click on the backdrop all mean "do not upload"; none of them
// touches what the person had selected. While a request is in flight the dialog cannot be dismissed,
// so an acceptance that is being recorded is never also reported as declined. A failed check is shown
// here as well (with Try again), because holding an upload silently would look like a broken page.
//
// Links in the agreement open in a new tab. Following one in this tab would leave the page and discard
// the upload the person is being asked about.

import { useEffect, useRef } from 'react';
import { Info, Loader2 } from 'lucide-react';
import type { MouseEvent } from 'react';
import type { UserAgreementGate, UserAgreementPrompt } from '../../lib/useUserAgreementGate';
import { Modal } from './Modal';
import { PlainMarkdown } from './PlainMarkdown';
import { GlassButton } from './primitives';

const IGNORE_CLOSE = () => undefined;

/** The absolute address of a link worth opening in a tab: http and https only, never a script or data URL. */
function safeAgreementLinkUrl(href: string): string | null {
    return /^https?:\/\//i.test(href) ? href : null;
}

function openLinksInNewTab(event: MouseEvent<HTMLElement>) {
    const anchor = event.target instanceof Element ? event.target.closest('a[href]') : null;
    const url = anchor instanceof HTMLAnchorElement ? safeAgreementLinkUrl(anchor.href) : null;
    if (!url) {
        return;
    }
    event.preventDefault();
    window.open(url, '_blank', 'noopener,noreferrer');
}

export function UserAgreementPromptDialog({
    prompt,
    onAccept,
    onCancel,
}: {
    prompt: UserAgreementPrompt;
    onAccept: () => void;
    onCancel: () => void;
}) {
    const panel = useRef<HTMLDivElement>(null);
    const unavailable = prompt.kind === 'unavailable';
    const files = prompt.fileCount === 1 ? '1 file' : `${prompt.fileCount} files`;

    // A request that fails leaves its button enabled again but focus on the page behind the dialog,
    // because a button that is disabled while busy gives up focus. Hand it back to the action to retry.
    useEffect(() => {
        if (!prompt.busy && prompt.error) {
            panel.current?.querySelector<HTMLElement>('[data-user-agreement-primary]')?.focus();
        }
    }, [prompt.busy, prompt.error]);

    // A retried check that finds an agreement replaces the failure with the agreement itself. Focus goes to
    // the dialog so a screen reader announces its new name, instead of staying behind on a button that went.
    const shownKind = useRef(prompt.kind);
    useEffect(() => {
        if (shownKind.current !== prompt.kind) {
            shownKind.current = prompt.kind;
            panel.current?.focus();
        }
    }, [prompt.kind]);

    return (
        <Modal
            title={unavailable ? 'User agreement could not be checked' : 'User Agreement Required'}
            description={unavailable
                ? 'Your upload is on hold until this check succeeds.'
                : 'Please read and accept the following agreement before uploading files.'}
            onClose={prompt.busy ? IGNORE_CLOSE : onCancel}
            panelRef={panel}
            footer={(
                <>
                    <GlassButton variant="ghost" size="sm" disabled={prompt.busy} onClick={onCancel}>
                        Cancel
                    </GlassButton>
                    <GlassButton variant="primary" size="sm" disabled={prompt.busy} onClick={onAccept}
                        data-user-agreement-primary="">
                        {prompt.busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                        {unavailable ? 'Try again' : 'Accept'}
                    </GlassButton>
                </>
            )}
        >
            <div className="space-y-3">
                {unavailable ? null : (
                    <>
                        <p className="text-xs text-text-3">
                            {`Accepting records your acceptance and continues the upload of ${files}.`}
                        </p>
                        <div
                            tabIndex={0}
                            role="region"
                            aria-label="User agreement text"
                            onClick={openLinksInNewTab}
                            className="max-h-[45vh] overflow-y-auto rounded-xl border border-edge bg-surface-1 p-3"
                        >
                            <PlainMarkdown
                                content={prompt.agreementText}
                                emptyLabel="No agreement text has been configured."
                            />
                        </div>
                        {prompt.enableDailyAcceptance ? (
                            <p className="flex items-center gap-1.5 text-xs text-text-3">
                                <Info size={13} aria-hidden="true" className="shrink-0" />
                                Your acceptance will be remembered for today.
                            </p>
                        ) : null}
                    </>
                )}
                {/* Always present so a screen reader announces the change when it is filled in. */}
                <p role="status" className="sr-only">
                    {prompt.busy ? (unavailable ? 'Checking the user agreement…' : 'Recording your acceptance…') : ''}
                </p>
                {prompt.error ? (
                    <p role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3 py-2 text-sm text-danger">
                        {prompt.error}
                    </p>
                ) : null}
            </div>
        </Modal>
    );
}

/** The dialog for a gate's state, or nothing while no one is being asked. */
export function UserAgreementDialog({ gate }: { gate: Pick<UserAgreementGate, 'prompt' | 'accept' | 'cancel'> }) {
    return gate.prompt ? (
        <UserAgreementPromptDialog prompt={gate.prompt} onAccept={gate.accept} onCancel={gate.cancel} />
    ) : null;
}
