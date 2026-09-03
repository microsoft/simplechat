// HomePage.tsx
// The V2 landing page.
//
// The classic interface opens on a home page that carries the logo, an administrator's
// landing copy and a link into chat. V2 had no equivalent, so /v2 redirected straight to
// the chat page and three Appearance settings -- the landing text, its alignment and the
// home page logo size -- configured a page that did not exist in this interface.
//
// Everything here comes from the bootstrap payload, so opening the home page costs no
// extra request.

import { Link } from 'react-router-dom';
import { MessageSquarePlus } from 'lucide-react';
import { useBootstrapStore } from '../stores/bootstrapStore';
import { useUiStore } from '../stores/uiStore';
import { AdminMarkdown } from '../components/admin/AdminMarkdown';

/**
 * Map the stored alignment onto the wrapper.
 *
 * Only the landing copy is aligned. The logo and the call to action stay centred in both
 * interfaces, so alignment reads as a choice about the prose rather than about the page.
 */
const alignmentClass: Record<'left' | 'center' | 'right', string> = {
    left: 'text-left',
    center: 'text-center',
    right: 'text-right',
};

export function HomePage() {
    const branding = useBootstrapStore((state) => state.data?.branding);
    const theme = useUiStore((state) => state.theme);

    const logoUrl = theme === 'dark' ? branding?.logo_dark_url : branding?.logo_url;
    const showLogo = Boolean(branding?.show_logo && logoUrl);
    const title = branding?.app_title || 'SimpleChat';
    const alignment = branding?.landing_page_alignment ?? 'left';
    // Checked for content rather than presence: AdminMarkdown is a settings preview and
    // says "Nothing to preview yet" when handed nothing, which is the wrong thing for a
    // landing page whose copy an administrator deliberately cleared.
    const landingText = (branding?.landing_page_text ?? '').trim();

    // "Main Page Logo Size" is stored as a percentage but the classic home page applies it
    // as a pixel height, so 100 renders a 100px logo. Matched here rather than corrected,
    // because the slider is calibrated against what an administrator already sees.
    const logoHeight = branding?.landing_page_logo_scale_percent ?? 100;

    return (
        <div className="min-h-0 flex-1 overflow-y-auto">
            <div className="mx-auto flex w-full max-w-3xl flex-col items-center px-6 py-16">
                {showLogo ? (
                    <img
                        src={logoUrl ?? undefined}
                        alt={title}
                        style={{ height: `${logoHeight}px` }}
                        className="mb-8 w-auto max-w-full object-contain"
                    />
                ) : null}

                {!branding?.hide_app_title && (
                    <h1 className="mb-6 text-center text-3xl font-semibold text-text-1">
                        {title}
                    </h1>
                )}

                {landingText ? (
                    <AdminMarkdown
                        content={landingText}
                        size="md"
                        align={alignment}
                        className={`mb-10 w-full ${alignmentClass[alignment]}`}
                    />
                ) : null}

                <Link
                    to="/chat"
                    className="inline-flex items-center gap-2 rounded-xl bg-accent px-6 py-3 text-base font-medium text-on-accent transition-colors hover:bg-accent-hover"
                >
                    <MessageSquarePlus size={18} />
                    Start chatting
                </Link>
            </div>
        </div>
    );
}
