// SupportSendFeedbackPage.tsx
// The Support menu's Send Feedback page: a bug report or a feature request for this
// organisation's own support mailbox.
//
// The V2 counterpart of the classic `/support/send-feedback` page. Whether it is offered comes
// from the bootstrap payload (`navigation.send_feedback`), which already requires an application
// role, the Support menu and this destination switched on, and a support mailbox configured. The
// submission endpoint enforces the same rules again, so this check only decides what to draw.
//
// Not to be confused with Admin Settings > Send Feedback, which reaches the SimpleChat product
// team rather than this organisation's administrators.

import { Lock } from 'lucide-react';
import { PageHeader } from '../components/layout/PageHeader';
import { SupportFeedbackForm } from '../components/support/SupportFeedbackForm';
import { EmptyState, GlassPanel } from '../components/ui/primitives';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { isSendFeedbackAvailable } from '../lib/supportMenu';

export function SupportSendFeedbackPage() {
    const bootstrap = useBootstrapStore((state) => state.data);
    const available = isSendFeedbackAvailable(bootstrap?.navigation);
    const appTitle = bootstrap?.branding?.app_title || 'SimpleChat';

    return (
        <div className="flex h-full min-h-0 flex-col">
            <PageHeader
                title="Send Feedback"
                description={`Report a problem or request an improvement from your ${appTitle} administrators.`}
            />
            <div
                data-testid="support-page-scroll"
                className="min-h-0 flex-1 overflow-y-auto px-4 py-5 lg:px-6"
            >
                <div className="mx-auto w-full max-w-2xl space-y-4 pb-10">
                    {available ? (
                        <>
                            <p className="max-w-[72ch] text-sm leading-relaxed text-text-2">
                                Fill in the form and your mail app opens a draft addressed to your
                                support team, ready for you to review. The draft is text only: to
                                include screenshots or files, attach them in your mail app.
                            </p>
                            <GlassPanel edge className="p-4 sm:p-6">
                                <SupportFeedbackForm
                                    defaultName={bootstrap?.user?.display_name ?? ''}
                                    defaultEmail={bootstrap?.user?.email ?? ''}
                                    appVersion={bootstrap?.version ?? ''}
                                />
                            </GlassPanel>
                        </>
                    ) : (
                        <EmptyState
                            icon={<Lock size={28} />}
                            title="Send Feedback is not available"
                            description="Your administrators have not set up a support mailbox for feedback."
                        />
                    )}
                </div>
            </div>
        </div>
    );
}
