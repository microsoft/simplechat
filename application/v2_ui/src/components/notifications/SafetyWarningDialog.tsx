// SafetyWarningDialog.tsx
// The dialog a safety warning from an administrator appears in, over whatever page is open.
//
// A warning has to be acknowledged, so the dialog has no close button and Escape or a click
// outside it leaves it on screen -- as a workflow alert that needs acknowledgment never tucks
// away. "I understand" records the acknowledgment on the server and shows the next waiting
// warning, if there is one. A reload, another tab or another device shows it again until then.
//
// Everything shown is the warning's own text, rendered as text.

import { Loader2, ShieldAlert } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import { describeSafetyWarningCategories, formatSafetyWarningDate, safetyWarningKey } from '../../lib/safetyWarnings';
import { refreshNotificationCount } from '../../stores/notificationStore';
import { useSafetyWarningStore } from '../../stores/safetyWarningStore';

const DIALOG_TITLE = 'A warning from your administrators';

function keepOpen(): void {
    // Escape and the backdrop do nothing: only "I understand" closes a warning.
}

export function SafetyWarningDialogHost() {
    const warning = useSafetyWarningStore((state) => state.warnings[0] ?? null);
    const waiting = useSafetyWarningStore((state) => state.warnings.length);
    const acknowledgingKey = useSafetyWarningStore((state) => state.acknowledgingKey);
    const error = useSafetyWarningStore((state) => state.error);
    const acknowledge = useSafetyWarningStore((state) => state.acknowledge);

    if (!warning) {
        return null;
    }

    const busy = acknowledgingKey === safetyWarningKey(warning);
    const issued = formatSafetyWarningDate(warning.issuedAt);
    const categories = describeSafetyWarningCategories(warning.categories);

    const onAcknowledge = async () => {
        if (await acknowledge(warning)) {
            // The warning's notice in the bell was marked read with it.
            void refreshNotificationCount();
        }
    };

    return (
        <Modal
            title={DIALOG_TITLE}
            onClose={keepOpen}
            banner={
                <div className="flex items-start gap-3 border-b border-edge px-4 py-3">
                    <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-xl bg-warn-soft text-warn">
                        <ShieldAlert size={18} aria-hidden="true" />
                    </span>
                    <div className="min-w-0">
                        <h2 className="text-sm font-semibold text-text-1">{DIALOG_TITLE}</h2>
                        <p className="mt-0.5 text-xs text-text-3">
                            {waiting > 1 ? `Warning 1 of ${waiting}. ` : ''}
                            Read it, then confirm you understand it to carry on.
                        </p>
                    </div>
                </div>
            }
            footer={
                <>
                    {error ? (
                        <p role="alert" className="mr-auto text-xs text-danger">
                            {error}
                        </p>
                    ) : null}
                    <GlassButton
                        type="button"
                        variant="primary"
                        size="sm"
                        disabled={busy}
                        onClick={() => void onAcknowledge()}
                        data-testid="v2-safety-warning-acknowledge"
                    >
                        {busy ? <Loader2 size={14} className="animate-spin" aria-hidden="true" /> : null}
                        I understand
                    </GlassButton>
                </>
            }
        >
            <div className="space-y-3" data-testid="v2-safety-warning">
                <h3 className="text-base font-semibold break-words text-text-1">{warning.title}</h3>
                <p
                    className="rounded-xl border border-edge bg-surface-sunken p-3 text-sm leading-relaxed break-words whitespace-pre-wrap text-text-1"
                    data-testid="v2-safety-warning-message"
                >
                    {warning.message}
                </p>
                <dl className="grid gap-x-3 gap-y-1 text-xs sm:grid-cols-[max-content_1fr]">
                    {issued ? (
                        <>
                            <dt className="font-medium text-text-2">Sent</dt>
                            <dd className="text-text-1">{issued}</dd>
                        </>
                    ) : null}
                    {categories ? (
                        <>
                            <dt className="font-medium text-text-2">Flagged categories</dt>
                            <dd className="text-text-1">{categories}</dd>
                        </>
                    ) : null}
                    <dt className="font-medium text-text-2">Reference</dt>
                    <dd className="break-all text-text-1">{warning.id}</dd>
                </dl>
            </div>
        </Modal>
    );
}
