// AssistantMarkdown.tsx
// Markdown rendering for assistant output: prose, citations, masks, maths, diagrams, charts
// and image proposals.
//
// Split out of MessageList so that "what a message looks like" is separable from "how the
// thread is laid out". The renderer carries the whole substitution pipeline and the fence
// types that render as something other than code, which is a distinct concern from the
// scrolling list around it.

import { Children, isValidElement, useMemo } from 'react';
import { clsx } from 'clsx';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkBreaks from 'remark-breaks';
import { rehypeHighlightSubset } from '../../lib/rehypeHighlightSubset';
import {
    CITATION_PLACEHOLDER_PATTERN,
    parseCitations,
    type CitationGroup,
} from '../../lib/citations';
import { applyMasks, MASK_PLACEHOLDER_PATTERN, type MaskedRange } from '../../lib/masking';
import { MaskedSpan } from './MaskedSpan';
import { CitationChip } from './CitationChip';
import { InlineChart } from './InlineChart';
import { InlineImageProposal } from './InlineImageProposal';
import { MathDisplay, MathInline } from './MathBlock';
import { MermaidDiagram } from './MermaidDiagram';
import {
    IMAGE_PROPOSAL_LANGUAGE,
    INLINE_CHART_LANGUAGE,
    MERMAID_LANGUAGE,
    markPendingFences,
    readPendingKind,
} from '../../lib/richBlocks';
import { MATH_PLACEHOLDER_PATTERN, parseMath, type MathSegment } from '../../lib/mathSegments';

/** Fence info strings that render as something other than a code block. */
const RICH_FENCE_LANGUAGES = new Set<string>([
    MERMAID_LANGUAGE,
    INLINE_CHART_LANGUAGE,
    IMAGE_PROPOSAL_LANGUAGE,
]);

/** Read the `language-xxx` class a fenced code block carries. */
function readFenceLanguage(className: unknown): string {
    const classes = Array.isArray(className) ? className.join(' ') : String(className ?? '');
    for (const entry of classes.split(/\s+/)) {
        if (entry.startsWith('language-')) {
            return entry.slice('language-'.length).toLowerCase();
        }
    }
    return '';
}

/**
 * The literal text inside a fence.
 *
 * Walked rather than read straight off `children`, because a fence may already have been
 * turned into highlighted spans, and a chart's JSON payload has to come back intact.
 */
function fenceText(children: React.ReactNode): string {
    if (typeof children === 'string') {
        return children;
    }
    if (typeof children === 'number') {
        return String(children);
    }
    if (Array.isArray(children)) {
        return children.map(fenceText).join('');
    }
    if (isValidElement(children)) {
        return fenceText((children.props as { children?: React.ReactNode }).children);
    }
    return '';
}

interface HastLike {
    tagName?: string;
    properties?: { className?: unknown };
    children?: HastLike[];
}

/** True when a `<pre>` wraps a fence this renderer replaces outright. */
function isRichFence(node: unknown): boolean {
    const code = (node as HastLike | undefined)?.children?.find(
        (candidate) => candidate?.tagName === 'code',
    );
    if (!code) {
        return false;
    }
    const language = readFenceLanguage(code.properties?.className);
    return RICH_FENCE_LANGUAGES.has(language) || readPendingKind(language) !== null;
}

/**
 * Stand-in for a diagram, chart or image proposal that has not finished streaming.
 *
 * Sized like the block it will become, so the reply below it does not jump when the real
 * thing renders.
 */
function PendingRichBlock({ kind }: { kind: string }) {
    const label =
        kind === INLINE_CHART_LANGUAGE
            ? 'Preparing chart…'
            : kind === IMAGE_PROPOSAL_LANGUAGE
              ? 'Preparing image proposal…'
              : 'Preparing diagram…';

    return (
        <div className="my-3 flex h-24 items-center justify-center rounded-xl bg-surface-sunken text-xs text-text-3">
            {label}
        </div>
    );
}

/**
 * Markdown renderer for assistant output.
 *
 * Raw HTML is deliberately not enabled (no rehype-raw): model output is untrusted input,
 * and react-markdown's default of escaping HTML is what keeps this XSS-safe.
 *
 * Citation markers, masked spans and TeX expressions are all lifted out before rendering and
 * swapped back in afterwards as components, so the markdown pipeline never sees them and no
 * HTML is injected to support any of them.
 *
 * `remark-breaks` makes a single newline a line break. This deliberately differs from the
 * classic UI, which uses marked's defaults (`breaks: false`) so single newlines collapse
 * into the surrounding paragraph. Without it, identical text renders differently depending
 * on who sent it, because user messages are shown with `whitespace-pre-wrap` and keep every
 * newline. Models also emit single newlines expecting them to be honoured, and the classic
 * UI's own Word export uses markdown2's `break-on-newline` for exactly that reason.
 */
function Markdown({
    content,
    citations,
    masks,
    math,
}: {
    content: string;
    citations?: CitationGroup[];
    masks?: MaskedRange[];
    math?: MathSegment[];
}) {
    const groups = citations ?? [];
    const maskRanges = masks ?? [];
    const mathSegments = math ?? [];

    /**
     * Substitute components for the placeholder tokens left in the text.
     *
     * Citations, masks and maths all survive markdown as inert tokens and are swapped back
     * in here, so none of them injects HTML into model output. A single text node can carry
     * more than one kind, so each pattern is applied in turn over the results of the last.
     */
    const renderTokens = (children: React.ReactNode): React.ReactNode => {
        if (groups.length === 0 && maskRanges.length === 0 && mathSegments.length === 0) {
            return children;
        }

        const substitutions: {
            tag: string;
            pattern: RegExp;
            render: (index: number, key: string) => React.ReactNode;
        }[] = [
            {
                tag: 'mask',
                pattern: MASK_PLACEHOLDER_PATTERN,
                render: (index, key) => <MaskedSpan key={key} range={maskRanges[index]} />,
            },
            {
                tag: 'cite',
                pattern: CITATION_PLACEHOLDER_PATTERN,
                render: (index, key) => {
                    const group = groups[index];
                    return group ? <CitationChip key={key} group={group} /> : null;
                },
            },
            {
                tag: 'math',
                pattern: MATH_PLACEHOLDER_PATTERN,
                render: (index, key) => {
                    const segment = mathSegments[index];
                    if (!segment) {
                        return null;
                    }
                    return segment.display ? (
                        <MathDisplay key={key} tex={segment.tex} />
                    ) : (
                        <MathInline key={key} tex={segment.tex} />
                    );
                },
            },
        ];

        return Children.map(children, (child) => {
            if (typeof child !== 'string') {
                return child;
            }

            let nodes: React.ReactNode[] = [child];
            for (const substitution of substitutions) {
                const next: React.ReactNode[] = [];
                nodes.forEach((node, nodeIndex) => {
                    if (typeof node !== 'string') {
                        next.push(node);
                        return;
                    }
                    // String.split with a capturing group interleaves text and captures, so
                    // odd indices hold the captured index.
                    node.split(substitution.pattern).forEach((part, partIndex) => {
                        if (partIndex % 2 === 1) {
                            next.push(
                                substitution.render(
                                    Number(part),
                                    `${substitution.tag}-${nodeIndex}-${partIndex}`,
                                ),
                            );
                            return;
                        }
                        if (part !== '') {
                            next.push(part);
                        }
                    });
                });
                nodes = next;
            }

            return nodes;
        });
    };

    return (
        <div
            className={clsx(
                'text-[15px] leading-relaxed break-words',
                '[&_p]:my-2 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0',
                '[&_ul]:my-2 [&_ul]:list-disc [&_ul]:pl-5',
                '[&_ol]:my-2 [&_ol]:list-decimal [&_ol]:pl-5',
                '[&_li]:my-0.5',
                '[&_h1]:mt-4 [&_h1]:mb-2 [&_h1]:text-lg [&_h1]:font-semibold',
                '[&_h2]:mt-4 [&_h2]:mb-2 [&_h2]:text-base [&_h2]:font-semibold',
                '[&_h3]:mt-3 [&_h3]:mb-1.5 [&_h3]:text-sm [&_h3]:font-semibold',
                '[&_a]:text-accent [&_a]:underline',
                '[&_code]:rounded [&_code]:bg-surface-sunken [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_code]:text-[13px]',
                '[&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-xl [&_pre]:bg-surface-sunken [&_pre]:p-3',
                '[&_pre_code]:bg-transparent [&_pre_code]:p-0',
                '[&_blockquote]:my-2 [&_blockquote]:border-l-2 [&_blockquote]:border-edge-strong [&_blockquote]:pl-3 [&_blockquote]:text-text-2',
                '[&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_table]:text-sm',
                '[&_th]:border [&_th]:border-edge-strong [&_th]:bg-surface-sunken [&_th]:px-2 [&_th]:py-1 [&_th]:text-left',
                '[&_td]:border [&_td]:border-edge-strong [&_td]:px-2 [&_td]:py-1',
            )}
        >
            <ReactMarkdown
                remarkPlugins={[remarkGfm, remarkBreaks]}
                rehypePlugins={[rehypeHighlightSubset]}
                components={{
                    // Every block a citation or mask placeholder can land in. A block left
                    // out here would render the raw ⟦cite:N⟧ token as visible text.
                    p: ({ children }) => <p>{renderTokens(children)}</p>,
                    li: ({ children }) => <li>{renderTokens(children)}</li>,
                    td: ({ children }) => <td>{renderTokens(children)}</td>,
                    th: ({ children }) => <th>{renderTokens(children)}</th>,
                    h1: ({ children }) => <h1>{renderTokens(children)}</h1>,
                    h2: ({ children }) => <h2>{renderTokens(children)}</h2>,
                    h3: ({ children }) => <h3>{renderTokens(children)}</h3>,
                    h4: ({ children }) => <h4>{renderTokens(children)}</h4>,
                    blockquote: ({ children }) => (
                        <blockquote>{renderTokens(children)}</blockquote>
                    ),
                    em: ({ children }) => <em>{renderTokens(children)}</em>,
                    strong: ({ children }) => <strong>{renderTokens(children)}</strong>,

                    // A diagram, chart or image proposal replaces the whole code block, so
                    // the <pre> wrapper markdown puts around it is dropped: leaving it would
                    // box the rendered output in the code block's background and padding.
                    pre: ({ children, node }) =>
                        isRichFence(node) ? <>{children}</> : <pre>{children}</pre>,

                    code: ({ className, children, ...props }) => {
                        const language = readFenceLanguage(className);

                        if (language === MERMAID_LANGUAGE) {
                            return <MermaidDiagram source={fenceText(children)} />;
                        }
                        if (language === INLINE_CHART_LANGUAGE) {
                            return <InlineChart source={fenceText(children)} />;
                        }
                        if (language === IMAGE_PROPOSAL_LANGUAGE) {
                            return <InlineImageProposal source={fenceText(children)} />;
                        }

                        const pendingKind = readPendingKind(language);
                        if (pendingKind) {
                            return <PendingRichBlock kind={pendingKind} />;
                        }

                        return (
                            <code className={className} {...props}>
                                {children}
                            </code>
                        );
                    },
                }}
            >
                {content}
            </ReactMarkdown>
        </div>
    );
}

/**
 * Assistant text with its citation markers turned into chips, masked spans redacted and TeX
 * lifted out for rendering.
 *
 * Order matters. Masks are applied FIRST: their offsets are canonical positions in the raw
 * content, and citation parsing rewrites the string, which would invalidate them. Maths is
 * lifted LAST, so it scans text that already has its markers removed and cannot mistake a
 * citation marker for part of an expression.
 *
 * While streaming, an unterminated trailing diagram, chart or image proposal fence is swapped
 * for a pending placeholder, because markdown would otherwise hand the renderer half a
 * diagram on every token.
 *
 * Parsing is memoised because it runs on every render of a long thread, and the streaming
 * bubble re-renders on each token.
 */
export function AssistantMarkdown({
    content,
    masks,
    streaming = false,
}: {
    content: string;
    masks?: MaskedRange[];
    streaming?: boolean;
}) {
    const { text, groups, ranges, segments } = useMemo(() => {
        const masked = applyMasks(content, masks ?? []);
        const parsed = parseCitations(masked.text);
        const guarded = streaming ? markPendingFences(parsed.text) : parsed.text;
        const withMath = parseMath(guarded);
        return {
            text: withMath.text,
            groups: parsed.groups,
            ranges: masked.ranges,
            segments: withMath.segments,
        };
    }, [content, masks, streaming]);

    return <Markdown content={text} citations={groups} masks={ranges} math={segments} />;
}
