// GuideDialog.tsx
// The frame and building blocks every in-app setup guide is written with.
//
// Some settings only work alongside steps taken outside SimpleChat -- app roles created in
// Entra, a health check path set on the App Service -- and the server-rendered page carried
// those walkthroughs in modals beside the section. The V2 guides keep them one click from the
// setting they serve, written with a small, consistent vocabulary: sections with real
// headings, numbered steps, code that copies itself, and notes whose tone matches their
// weight. The documentation site has the same material for reading away from the page.

import type { ReactNode } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, ArrowUpRight, Info } from 'lucide-react';
import { safeHttpsUrl } from '../../../lib/adminOperations';
import { Modal } from '../../ui/Modal';
import { GlassButton } from '../../ui/primitives';
import { CopyButton } from '../CopyValue';

export function GuideDialog({
    title,
    description,
    docsUrl,
    onClose,
    children,
}: {
    title: string;
    description?: string;
    docsUrl?: string;
    onClose: () => void;
    children: ReactNode;
}) {
    // The documentation address comes from the server; anything but plain HTTPS is dropped.
    const docsHref = safeHttpsUrl(docsUrl);
    return (
        <Modal
            title={title}
            description={description}
            size="lg"
            onClose={onClose}
            footer={
                <>
                    {docsHref ? (
                        <a
                            href={docsHref}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="mr-auto inline-flex items-center gap-1 text-sm font-medium text-accent hover:underline"
                        >
                            Read this in the documentation
                            <ArrowUpRight size={14} aria-hidden="true" />
                            <span className="sr-only">(opens in a new tab)</span>
                        </a>
                    ) : null}
                    <GlassButton type="button" variant="primary" size="sm" onClick={onClose}>
                        Done
                    </GlassButton>
                </>
            }
        >
            {/* Role names such as ControlCenterDashboardReader are single long words; the
                admin cards let them break anywhere, and the guides, portalled outside the
                cards, need the same rule to fit a phone at large text sizes. */}
            <div className="space-y-6 py-1 text-[0.8125rem] leading-relaxed text-text-2 [overflow-wrap:anywhere]">
                {children}
            </div>
        </Modal>
    );
}

export function GuideSection({ title, children }: { title: string; children: ReactNode }) {
    return (
        <section className="space-y-2.5">
            <h3 className="text-sm font-semibold text-text-1">{title}</h3>
            {children}
        </section>
    );
}

export function GuideSteps({ children }: { children: ReactNode }) {
    return <ol className="list-decimal space-y-1.5 ps-5 marker:text-text-3">{children}</ol>;
}

export function GuideList({ children }: { children: ReactNode }) {
    return <ul className="list-disc space-y-1.5 ps-5 marker:text-text-3">{children}</ul>;
}

/** A name on screen in the Azure portal or Entra, set apart so it can be found there. */
export function UiName({ children }: { children: ReactNode }) {
    return <strong className="font-semibold text-text-1">{children}</strong>;
}

/** A literal value -- a path, a role value -- in the same monospace as the code blocks. */
export function Literal({ children }: { children: string }) {
    return (
        <code className="rounded bg-surface-2 px-1 py-0.5 font-mono text-[0.75rem] text-text-1">
            {children}
        </code>
    );
}

export function GuideCode({ code, label }: { code: string; label: string }) {
    return (
        <div className="relative">
            <pre className="overflow-x-auto rounded-lg border border-edge bg-surface-sunken py-2.5 ps-3 pe-10 font-mono text-xs leading-relaxed text-text-1">
                <code>{code}</code>
            </pre>
            <div className="absolute top-1.5 right-1.5">
                <CopyButton value={code} label={label} />
            </div>
        </div>
    );
}

export function GuideNote({ tone = 'info', children }: { tone?: 'info' | 'warning'; children: ReactNode }) {
    const Icon = tone === 'warning' ? AlertCircle : Info;
    return (
        <div
            className={clsx(
                'flex items-start gap-2 rounded-lg border px-3 py-2 text-xs leading-relaxed',
                tone === 'warning'
                    ? 'border-warn/40 bg-warn-soft text-text-1'
                    : 'border-edge bg-surface-2 text-text-2',
            )}
        >
            <Icon
                size={13}
                aria-hidden="true"
                className={clsx('mt-0.5 shrink-0', tone === 'warning' ? 'text-warn' : 'text-text-3')}
            />
            <div className="min-w-0">{children}</div>
        </div>
    );
}

/** A symptom and its likely causes, for troubleshooting that reads as problem then fixes. */
export function GuideIssue({ symptom, children }: { symptom: string; children: ReactNode }) {
    return (
        <div className="space-y-1.5">
            <p className="font-medium text-text-1">{symptom}</p>
            <GuideList>{children}</GuideList>
        </div>
    );
}

export function GuideLinks({ links }: { links: { label: string; href: string }[] }) {
    return (
        <ul className="space-y-1.5">
            {links.map((link) => {
                const href = safeHttpsUrl(link.href);
                return href ? (
                    <li key={link.href}>
                        <a
                            href={href}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="inline-flex items-center gap-1 text-accent hover:underline"
                        >
                            {link.label}
                            <ArrowUpRight size={13} aria-hidden="true" />
                            <span className="sr-only">(opens in a new tab)</span>
                        </a>
                    </li>
                ) : null;
            })}
        </ul>
    );
}
