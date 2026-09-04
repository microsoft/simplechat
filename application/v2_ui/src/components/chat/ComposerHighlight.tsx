// ComposerHighlight.tsx
// Drawing `#[…]` references as chips inside the message box.
//
// A reference lives in two places: as a chip above the input, and as literal text within it,
// so it stays part of the sentence the user actually sends. Left unstyled that text reads as
// punctuation noise -- `compare #[Q3 Contract.pdf] against #[Q2 Contract.pdf]` is a lot of
// brackets -- and the reference stops looking like the resolved thing it is.
//
// A textarea cannot style its own content, so this is the standard backdrop arrangement: an
// element behind the textarea holding the same text with the same metrics, and a textarea
// whose glyphs are transparent while its caret and selection stay visible.
//
// THE ONE RULE: the backdrop and the textarea must lay text out identically. Any difference in
// font, size, spacing, padding or wrapping shows up as chips drifting away from the words they
// belong to. That is why both read their box metrics from COMPOSER_TEXT_CLASS below rather
// than each carrying its own copy, and why the backdrop is not merely `whitespace-pre-wrap`
// but matched on word breaking too.

import { useEffect, type CSSProperties, type RefObject } from 'react';
import { parseContextTokens } from '../../lib/chatContextTokens';

/**
 * The typography and box metrics the textarea and its backdrop share.
 *
 * Exported so the textarea uses this exact string. Two hand-kept copies of these values is the
 * defect this constant exists to prevent.
 */
export const COMPOSER_TEXT_CLASS =
    'w-full px-3 py-2.5 text-[15px] leading-relaxed whitespace-pre-wrap break-words';

/**
 * Caret and selection have to be set explicitly once the text is transparent.
 *
 * `caret-color` is independent of `color`, so the caret survives; without naming it the
 * browser would draw it in the transparent text colour and the user would be typing into what
 * looks like a dead box.
 */
export const COMPOSER_TRANSPARENT_TEXT_STYLE: CSSProperties = {
    color: 'transparent',
    caretColor: 'var(--text-1)',
    WebkitTextFillColor: 'transparent',
};

/**
 * Keep the backdrop's scroll position tied to the textarea's.
 *
 * The composer grows to 224px and then scrolls. Without this the chips stay put while the
 * words move, which is worse than not styling them at all.
 */
export function useHighlightScrollSync(
    textareaRef: RefObject<HTMLTextAreaElement>,
    backdropRef: RefObject<HTMLDivElement>,
    text: string,
) {
    useEffect(() => {
        const textarea = textareaRef.current;
        const backdrop = backdropRef.current;
        if (!textarea || !backdrop) {
            return;
        }

        const sync = () => {
            backdrop.scrollTop = textarea.scrollTop;
            backdrop.scrollLeft = textarea.scrollLeft;
        };

        sync();
        textarea.addEventListener('scroll', sync);
        return () => textarea.removeEventListener('scroll', sync);
        // `text` is a dependency because growing the box changes the scroll offset without
        // ever firing a scroll event.
    }, [textareaRef, backdropRef, text]);
}

/**
 * The message text with its resolved references drawn as chips.
 *
 * Only tokens that a chip still backs are styled. A hand-typed `#[Something]` that resolves to
 * nothing stays plain, so the styling means "this is a real reference" rather than "this looks
 * like one" -- the same distinction `reconcileContextItems` makes on the data side.
 *
 * A trailing newline gets a zero-width space so the backdrop keeps the height the textarea
 * gives that line; without it the last line's chips sit one row too high.
 */
export function ComposerHighlight({
    text,
    tokens,
    backdropRef,
}: {
    text: string;
    /** The tokens currently backed by a chip. */
    tokens: ReadonlySet<string>;
    backdropRef: RefObject<HTMLDivElement>;
}) {
    const parsed = parseContextTokens(text);
    const pieces: Array<{ key: string; value: string; chip: boolean }> = [];

    let cursor = 0;
    parsed.forEach((token, index) => {
        if (token.start > cursor) {
            pieces.push({
                key: `text-${cursor}`,
                value: text.slice(cursor, token.start),
                chip: false,
            });
        }
        pieces.push({
            key: `token-${index}-${token.start}`,
            value: token.token,
            chip: tokens.has(token.token),
        });
        cursor = token.end;
    });
    if (cursor < text.length) {
        pieces.push({ key: `text-${cursor}`, value: text.slice(cursor), chip: false });
    }

    return (
        <div
            ref={backdropRef}
            aria-hidden="true"
            className={`pointer-events-none absolute inset-0 overflow-hidden text-text-1 ${COMPOSER_TEXT_CLASS}`}
        >
            {pieces.map((piece) =>
                piece.chip ? (
                    <span
                        key={piece.key}
                        className="rounded bg-accent-soft text-accent"
                        // Padding is horizontal only and applied as a negative-free inline box:
                        // vertical padding would change the line box and push the backdrop's
                        // wrapping out of step with the textarea's.
                        style={{ paddingLeft: '2px', paddingRight: '2px' }}
                    >
                        {piece.value}
                    </span>
                ) : (
                    <span key={piece.key}>{piece.value}</span>
                ),
            )}
            {text.endsWith('\n') && <span>{'\u200b'}</span>}
        </div>
    );
}
