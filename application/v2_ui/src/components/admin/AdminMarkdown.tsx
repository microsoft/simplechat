// AdminMarkdown.tsx
// Markdown preview for administrator-authored content.
//
// Deliberately not `AssistantMarkdown`: that renderer parses citations, applies masking
// ranges and hosts diagram and chart blocks, none of which apply to a landing page or an
// agreement, and all of which would misread ordinary admin copy.
//
// `react-markdown` does not render raw HTML unless `rehype-raw` is added, which it is not
// here. Admin-authored markdown therefore cannot inject script or event handlers into the
// settings page.

import Markdown from 'react-markdown';
import remarkBreaks from 'remark-breaks';
import remarkGfm from 'remark-gfm';
import { clsx } from 'clsx';

export function AdminMarkdown({
    content,
    className,
    align = 'left',
}: {
    content: string;
    className?: string;
    /** Mirrors `landing_page_alignment` so the preview matches the real page. */
    align?: 'left' | 'center' | 'right';
}) {
    const trimmed = content.trim();

    if (!trimmed) {
        return <p className="text-sm text-text-3 italic">Nothing to preview yet.</p>;
    }

    return (
        <div
            className={clsx(
                'space-y-2 text-sm leading-relaxed text-text-2',
                '[&_a]:text-accent [&_a]:underline',
                '[&_code]:rounded [&_code]:bg-surface-sunken [&_code]:px-1 [&_code]:py-0.5',
                '[&_h1]:text-base [&_h1]:font-semibold [&_h1]:text-text-1',
                '[&_h2]:text-sm [&_h2]:font-semibold [&_h2]:text-text-1',
                '[&_h3]:text-sm [&_h3]:font-medium [&_h3]:text-text-1',
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
