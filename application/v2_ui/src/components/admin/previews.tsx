// previews.tsx
// Live previews for the notice settings.
//
// Both mirror what a user will actually see, because these settings are judged visually:
// a banner colour pair either reads clearly or it does not, and an agreement written in
// markdown is hard to check as source. Both preview the unsaved draft, so the effect of an
// edit is visible before it is committed.

import { useState } from 'react';
import { Eye } from 'lucide-react';
import { AdminMarkdown } from './AdminMarkdown';
import { AdminModal } from './AdminModal';
import { GlassButton } from '../ui/primitives';

const HEX = /^#[0-9a-fA-F]{6}$/;

export function ClassificationBannerPreview({
    text,
    color,
    textColor,
}: {
    text: string;
    color: string;
    textColor: string;
}) {
    // An invalid hex is shown as a neutral swatch rather than being passed to the style
    // attribute, so a half-typed value cannot produce a confusing render.
    const background = HEX.test(color) ? color : '#ffc107';
    const foreground = HEX.test(textColor) ? textColor : '#ffffff';

    return (
        <div className="py-3">
            <span className="mb-1.5 block text-sm font-medium text-text-1">Preview</span>
            <div
                className="rounded-lg px-4 py-2 text-center text-sm font-semibold"
                style={{ background, color: foreground }}
            >
                {text.trim() || 'Banner Preview'}
            </div>
            {(!HEX.test(color) || !HEX.test(textColor)) && (
                <p className="mt-1.5 text-xs text-warn">
                    Showing default colours until both values are six-digit hex.
                </p>
            )}
        </div>
    );
}

export function UserAgreementPreview({ text }: { text: string }) {
    const [open, setOpen] = useState(false);

    return (
        <div className="py-3">
            <GlassButton
                type="button"
                variant="subtle"
                size="sm"
                onClick={() => setOpen(true)}
            >
                <Eye size={14} />
                Test preview
            </GlassButton>
            <p className="mt-1.5 text-xs text-text-3">
                Shows the agreement as a user will see it, including unsaved edits.
            </p>

            {open ? (
                <AdminModal
                    title="User Agreement"
                    description="Preview only. Nothing is recorded."
                    onClose={() => setOpen(false)}
                    footer={
                        <>
                            <GlassButton
                                type="button"
                                variant="ghost"
                                size="sm"
                                onClick={() => setOpen(false)}
                            >
                                Decline
                            </GlassButton>
                            <GlassButton
                                type="button"
                                variant="primary"
                                size="sm"
                                onClick={() => setOpen(false)}
                            >
                                Accept
                            </GlassButton>
                        </>
                    }
                >
                    <AdminMarkdown content={text} />
                </AdminModal>
            ) : null}
        </div>
    );
}
