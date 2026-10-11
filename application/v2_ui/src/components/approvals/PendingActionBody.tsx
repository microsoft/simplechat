// PendingActionBody.tsx

import { useEffect, useId, useRef, useState } from 'react';
import { loadDomPurify } from '../../lib/vendorAssets';

/** Five rendered lines, measured again when wrapping or the saved content changes. */
export function PendingActionBody({ body, contentType, expanded, onExpand, truncated = false, loading = false }: {
    body: string;
    contentType?: string;
    expanded: boolean;
    onExpand: (open: boolean) => void;
    truncated?: boolean;
    loading?: boolean;
}) {
    const id = useId();
    const content = useRef<HTMLDivElement>(null);
    const [safeHtml, setSafeHtml] = useState<{ body: string; html: string } | null>(null);
    const [overflow, setOverflow] = useState(false);
    const [failedBody, setFailedBody] = useState<string | null>(null);
    const [attempt, setAttempt] = useState(0);
    const html = contentType?.toLowerCase() === 'html';
    const previewReady = !html || safeHtml?.body === body;

    useEffect(() => {
        if (!html) return;
        let active = true;
        setSafeHtml(null);
        setFailedBody(null);
        void loadDomPurify().then((purify) => {
            // Email is untrusted HTML. Keep prose formatting and safe links, never styles,
            // remote images, forms, executable markup or embedded content.
            const sanitized = purify.sanitize(body, {
                ALLOWED_TAGS: ['p', 'div', 'span', 'br', 'strong', 'b', 'em', 'i', 'u', 's', 'ul', 'ol', 'li', 'blockquote', 'a', 'h1', 'h2', 'h3', 'h4', 'pre', 'code'],
                ALLOWED_ATTR: ['href', 'title'],
            });
            if (active) setSafeHtml({ body, html: sanitized });
        }).catch(() => {
            if (active) {
                setSafeHtml(null);
                setFailedBody(body);
            }
        });
        return () => { active = false; };
    }, [body, html, attempt]);

    useEffect(() => {
        const element = content.current;
        if (!element) return;
        const measure = () => setOverflow(element.scrollHeight > 120 + 1);
        measure();
        const observer = new ResizeObserver(measure);
        observer.observe(element);
        return () => observer.disconnect();
    }, [body, safeHtml, expanded, failedBody, html]);

    return (
        <div className="space-y-1.5">
            <div id={id} style={{ maxHeight: expanded ? undefined : 120, overflow: expanded ? undefined : 'hidden' }}
                onFocusCapture={(event) => {
                    if (!expanded && event.target instanceof HTMLElement && event.target.closest('a')) onExpand(true);
                }}>
                {html && safeHtml?.body === body ? (
                    // xss-check: ignore reviewed: component-private safeHtml.html only receives the async locally vendored DOMPurify.sanitize result with fixed prose/link allowlists; raw body never enters this HTML sink.
                    <div ref={content} data-testid="v2-pending-action-body"
                        className="break-words text-sm text-text-1 [line-height:24px] [&_*]:[line-height:24px] [&_*]:[font-size:inherit] [&_*]:[margin:0] [&_a]:text-accent [&_a]:underline [&_li]:ml-5 [&_pre]:whitespace-pre-wrap"
                        style={{ lineHeight: '24px' }}
                        dangerouslySetInnerHTML={{ __html: safeHtml.html }} />
                ) : html ? (
                    failedBody === body ? (
                        <div className="space-y-1.5">
                            <p role="alert" className="text-sm text-danger">Formatted preview unavailable. The body is hidden until it can be safely displayed.</p>
                            <button type="button" onClick={() => setAttempt((value) => value + 1)}
                                className="rounded-md text-sm font-medium text-accent underline underline-offset-2">
                                Retry formatted preview
                            </button>
                        </div>
                    ) : <p role="status" className="text-sm text-text-3">Preparing formatted preview…</p>
                ) : (
                    <div ref={content} data-testid="v2-pending-action-body"
                        style={{ lineHeight: '24px', whiteSpace: 'pre-wrap' }}
                        className="whitespace-pre-wrap break-words text-sm text-text-1 [line-height:24px]">{body}</div>
                )}
            </div>
            {previewReady && (overflow || truncated) ? (
                <button type="button" aria-expanded={expanded} aria-controls={id} disabled={loading}
                    onClick={() => onExpand(!expanded)}
                    className="rounded-md text-sm font-medium text-accent underline underline-offset-2 disabled:opacity-50">
                    {loading ? 'Loading full body…' : expanded ? 'Show Less' : 'Show More'}
                </button>
            ) : null}
        </div>
    );
}
