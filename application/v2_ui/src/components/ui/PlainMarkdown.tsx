// PlainMarkdown.tsx
// Markdown rendering for content a person authored directly.
//
// Deliberately not `AssistantMarkdown`: that renderer parses citation markers, applies masking
// ranges and hosts diagram and chart blocks, none of which apply to a landing page, an
// agreement or a saved prompt, and all of which would misread ordinary prose. A prompt that
// happens to contain a bracketed number should show a bracketed number, not a broken citation.
//
// `react-markdown` does not render raw HTML unless `rehype-raw` is added, which it is not here.
// Authored markdown therefore cannot inject script or event handlers into the page, which is
// what makes it safe to preview content typed by a user.
//
// This was `components/admin/AdminMarkdown.tsx` until the prompts workbench needed the same
// renderer; that path is now a re-export so admin call sites did not have to change.

import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { clsx } from 'clsx';

/**
 * Type scale. `sm` suits a preview card inside a settings form; `md` is for the same content
 * rendered as the page itself, where settings-preview sizing would look shrunken.
 */
export type MarkdownSize = 'sm' | 'md';

const sizeClass: Record<MarkdownSize, string> = {
    sm: clsx(
        'space-y-2 text-sm',
        '[&_h1]:text-base [&_h2]:text-sm [&_h3]:text-sm',
    ),
    md: clsx(
        'space-y-3 text-base',
        '[&_h1]:text-2xl [&_h2]:text-xl [&_h3]:text-lg',
    ),
};

export function PlainMarkdown({
    content,
    className,
    align = 'left',
    size = 'sm',
    emptyLabel = 'Nothing to preview yet.',
}: {
    content: string;
    className?: string;
    /** Mirrors `landing_page_alignment` so the preview matches the real page. */
    align?: 'left' | 'center' | 'right';
    size?: MarkdownSize;
    /** What to show for empty content, so each surface can say something apt. */
    emptyLabel?: string;
}) {
    const trimmed = content.trim();

    if (!trimmed) {
        return <p className="text-sm text-text-3 italic">{emptyLabel}</p>;
    }

    return (
        <div
            className={clsx(
                'leading-relaxed text-text-2',
                sizeClass[size],
                '[&_a]:text-accent [&_a]:underline',
                '[&_code]:rounded [&_code]:bg-surface-sunken [&_code]:px-1 [&_code]:py-0.5',
                '[&_h1]:font-semibold [&_h1]:text-text-1',
                '[&_h2]:font-semibold [&_h2]:text-text-1',
                '[&_h3]:font-medium [&_h3]:text-text-1',
                '[&_li]:ml-4 [&_li]:list-disc',
                '[&_ol_li]:list-decimal',
                '[&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-surface-sunken [&_pre]:p-3',
                '[&_strong]:font-semibold [&_strong]:text-text-1',
                '[&_table]:w-full [&_table]:border-collapse',
                '[&_td]:border [&_td]:border-edge [&_td]:px-2 [&_td]:py-1',
                '[&_th]:border [&_th]:border-edge [&_th]:px-2 [&_th]:py-1 [&_th]:text-left',
                align === 'center' && 'text-center',
                align === 'right' && 'text-right',
                className,
            )}
        >
            <Markdown remarkPlugins={[remarkGfm, remarkBreaks]}>{trimmed}</Markdown>
        </div>
    );
}
