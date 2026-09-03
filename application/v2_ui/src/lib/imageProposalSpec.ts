// imageProposalSpec.ts
// Parses the ```simpleimage payload a model emits to propose a generated image.
//
// The grammar and every sanitisation cap are taken from two places that must agree:
// static/js/chat/chat-inline-image-proposals.js, which is what the classic client shows for
// the same message, and normalize_image_proposal in functions_image_generation.py, which is
// what the server accepts when the proposal is approved. A card that displayed something the
// server would then reject on approval would be worse than not rendering the card at all.
//
// Nothing here trusts the payload: it is model output. Every string is length-capped, the
// visual id is reduced to a known character set, and a proposal with no prompt is not a
// proposal, because the prompt is the only field the server actually requires.

import type { ChatMessage, Json } from './types';

/** Fence language the image proposal guidance tells models to emit. */
export const IMAGE_PROPOSAL_LANGUAGE = 'simpleimage';

/**
 * Caps, matching IMAGE_PROPOSAL_* in functions_image_generation.py.
 *
 * Title and visual type are capped harder here than the server's 600, matching the classic
 * client: these are headings in a card, not stored values, and the server re-normalises
 * whatever is sent anyway.
 */
export const PROMPT_MAX_LENGTH = 4000;
const TEXT_MAX_LENGTH = 600;
const TITLE_MAX_LENGTH = 160;
const VISUAL_TYPE_MAX_LENGTH = 80;
const VISUAL_ID_MAX_LENGTH = 120;
const SLIDE_LABEL_MAX_LENGTH = 40;

export interface ImageProposalSpec {
    version: 1;
    visualId: string;
    title: string;
    description: string;
    prompt: string;
    visualType: string;
    context: string;
    /** A slide reference is a number when it reads as one, and a short label otherwise. */
    slideNumber?: number | string;
}

/**
 * Outcome of reading a fence.
 *
 * Failure carries a reason so the card can say why it is showing a status instead of a
 * proposal. The raw payload is never surfaced: it is untrusted, and a wall of JSON is not
 * something a reader can act on.
 */
export type ParsedImageProposal =
    | { ok: true; spec: ImageProposalSpec }
    | { ok: false; reason: string };

/** Collapse whitespace and cap length, matching `_trim_text` on the server. */
function trimText(value: unknown, maxLength: number): string {
    return String(value ?? '')
        .replace(/\s+/g, ' ')
        .trim()
        .slice(0, maxLength)
        .trimEnd();
}

/**
 * Normalise a prompt, keeping its line structure.
 *
 * Deliberately not `trimText`: a prompt is the one field the user can edit, and collapsing
 * the newlines out of a multi-line prompt in the editor would silently rewrite what they
 * typed. The server collapses it on arrival, which is where that decision belongs.
 */
export function normalizePrompt(value: unknown): string {
    return String(value ?? '')
        .replace(/\r\n?/g, '\n')
        .trim()
        .slice(0, PROMPT_MAX_LENGTH);
}

/** Reduce a visual id to the character set `_normalize_visual_id` allows on the server. */
function normalizeVisualId(value: unknown): string {
    return trimText(value, VISUAL_ID_MAX_LENGTH)
        .replace(/[^a-zA-Z0-9_.-]+/g, '_')
        .replace(/^[_\-.]+|[_\-.]+$/g, '');
}

/** Accept both the camelCase the guidance asks for and the snake_case models often emit. */
function readAlias(source: Record<string, unknown>, camel: string, snake: string): unknown {
    return source[camel] ?? source[snake];
}

/** Normalise a decoded payload, or return null when it cannot be a proposal. */
export function normalizeImageProposal(raw: unknown): ImageProposalSpec | null {
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) {
        return null;
    }

    const source = raw as Record<string, unknown>;
    const prompt = normalizePrompt(source.prompt);
    if (!prompt) {
        return null;
    }

    const spec: ImageProposalSpec = {
        version: 1,
        visualId: normalizeVisualId(readAlias(source, 'visualId', 'visual_id')),
        // Left empty when the model gives none, exactly as the server stores it. A default
        // injected here would be posted on approval and stored, and two untitled proposals in
        // one message would then share a title and could claim each other's image. The card
        // supplies a heading for display instead.
        title: trimText(source.title, TITLE_MAX_LENGTH),
        description: trimText(source.description, TEXT_MAX_LENGTH),
        prompt,
        visualType: trimText(readAlias(source, 'visualType', 'visual_type'), VISUAL_TYPE_MAX_LENGTH),
        context: trimText(source.context, TEXT_MAX_LENGTH),
    };

    const slideNumber = readAlias(source, 'slideNumber', 'slide_number');
    if (slideNumber !== undefined && slideNumber !== null && String(slideNumber).trim() !== '') {
        const numeric = Number(slideNumber);
        spec.slideNumber = Number.isFinite(numeric)
            ? numeric
            : trimText(slideNumber, SLIDE_LABEL_MAX_LENGTH);
    }

    return spec;
}

/** Read a fence body into a proposal. */
export function parseImageProposal(source: string): ParsedImageProposal {
    const text = String(source ?? '').trim();
    if (!text) {
        return { ok: false, reason: 'The image proposal was empty.' };
    }

    let decoded: unknown;
    try {
        decoded = JSON.parse(text);
    } catch {
        return { ok: false, reason: 'The image proposal JSON was not recognised.' };
    }

    const spec = normalizeImageProposal(decoded);
    if (!spec) {
        return { ok: false, reason: 'The image proposal is missing a prompt.' };
    }

    return { ok: true, spec };
}

/** Matches a closed proposal fence, as the classic client's extractor does. */
const PROPOSAL_FENCE_PATTERN = new RegExp(
    `\`\`\`${IMAGE_PROPOSAL_LANGUAGE}\\s*([\\s\\S]*?)\`\`\``,
    'gi',
);

/**
 * Every proposal a message actually contains.
 *
 * Used to work out which approved images a message's cards will be able to show. Without it
 * the thread would have to assume that an image tagged with a message id can always be
 * reunited with a card in that message, and an image that could not be would then be hidden
 * from the thread while appearing in no card either — visible nowhere.
 */
export function extractProposalSpecs(content: string): ImageProposalSpec[] {
    const text = String(content ?? '');
    if (!text.includes(IMAGE_PROPOSAL_LANGUAGE)) {
        return [];
    }

    const specs: ImageProposalSpec[] = [];
    PROPOSAL_FENCE_PATTERN.lastIndex = 0;

    let match = PROPOSAL_FENCE_PATTERN.exec(text);
    while (match) {
        const parsed = parseImageProposal(match[1] ?? '');
        if (parsed.ok) {
            specs.push(parsed.spec);
        }
        match = PROPOSAL_FENCE_PATTERN.exec(text);
    }

    return specs;
}

/**
 * A stable identity for one proposal card within its message.
 *
 * Approval state is held by the message's proposal scope rather than by the card, so it has
 * to be filed under something that still names the same card after the markdown subtree is
 * rebuilt. The fence index `rehypeRichBlockIndex` stamps is exactly that: it is assigned per
 * kind in document order, so it is unique within the message and does not move when an
 * unrelated block above it changes.
 *
 * The spec is only consulted when there is no index, which happens if the plugin did not run.
 * The visual id comes first because it is the one field the guidance asks the model to make
 * unique; the prompt is the fallback because it is the one field a proposal cannot omit. Two
 * proposals identical in both are indistinguishable to `findResultForSpec` as well, so
 * sharing a key costs nothing that was not already lost.
 */
export function proposalCardKey(spec: ImageProposalSpec | null, blockIndex?: number): string {
    if (typeof blockIndex === 'number' && Number.isInteger(blockIndex) && blockIndex >= 0) {
        return `block:${blockIndex}`;
    }
    if (!spec) {
        return 'invalid';
    }

    const visualId = normalizeVisualId(spec.visualId);
    if (visualId) {
        return `visual:${visualId}`;
    }
    return `prompt:${trimText(spec.prompt, PROMPT_MAX_LENGTH)}`;
}

/** Short badges describing what the proposal is for. */
export function proposalBadges(spec: ImageProposalSpec): string[] {
    const badges: string[] = [];
    if (spec.visualType) {
        badges.push(spec.visualType);
    }
    if (spec.slideNumber !== undefined && String(spec.slideNumber).trim() !== '') {
        badges.push(`Slide ${spec.slideNumber}`);
    }
    if (spec.context) {
        badges.push(spec.context);
    }
    return badges;
}

/* -------------------------------------------------------------------------- */
/* Approved results                                                            */
/* -------------------------------------------------------------------------- */

/**
 * The proposal an image message was generated from.
 *
 * Written by `_build_image_proposal_metadata` (functions_image_generation.py) as the
 * normalised proposal plus `approved_at` and the id of the assistant message that proposed
 * it. That last field is what lets an approved image be shown next to the text that asked
 * for it instead of as a loose bubble at the end of the thread.
 */
export interface ImageProposalMetadata {
    visualId?: unknown;
    visual_id?: unknown;
    title?: unknown;
    prompt?: unknown;
    approved_at?: unknown;
    source_assistant_message_id?: unknown;
    [key: string]: unknown;
}

/** The `image_proposal` metadata on a message, or null when it is not a proposal result. */
export function readImageProposalMetadata(message: unknown): ImageProposalMetadata | null {
    const metadata = (message as { metadata?: Json } | null)?.metadata;
    if (!metadata || typeof metadata !== 'object' || Array.isArray(metadata)) {
        return null;
    }

    const proposal = metadata.image_proposal;
    if (!proposal || typeof proposal !== 'object' || Array.isArray(proposal)) {
        return null;
    }

    return proposal as ImageProposalMetadata;
}

/** The assistant message an approved image belongs under, or '' when it stands alone. */
export function proposalSourceMessageId(message: unknown): string {
    return String(readImageProposalMetadata(message)?.source_assistant_message_id ?? '').trim();
}

/**
 * Group approved proposal images by the assistant message that proposed them.
 *
 * Mirrors `groupGeneratedImageProposalMessages` in the classic client. Images without the
 * metadata — an ordinary image generation from the composer's Image toggle, say — are left
 * out, because they belong in the thread on their own.
 */
export function groupProposalImages(messages: ChatMessage[]): Map<string, ChatMessage[]> {
    const grouped = new Map<string, ChatMessage[]>();

    for (const message of messages) {
        if (message?.role !== 'image') {
            continue;
        }

        const sourceId = proposalSourceMessageId(message);
        if (!sourceId) {
            continue;
        }

        const existing = grouped.get(sourceId);
        if (existing) {
            existing.push(message);
        } else {
            grouped.set(sourceId, [message]);
        }
    }

    return grouped;
}

/**
 * Find the approved image belonging to a card.
 *
 * Each field is tried across **every** result before moving to the next, rather than trying
 * every field against each result in turn. The difference matters when one message proposes
 * several images: with the weaker ordering, two proposals that happen to share a title would
 * both resolve to whichever image came first, so one image would be shown twice and the other
 * would be shown nowhere near its own proposal.
 *
 * The visual id is tried first because it is the only field the guidance asks the model to
 * make unique. The prompt comes next, and is compared with its whitespace collapsed as well as
 * verbatim: the server stores prompts through `_trim_text`, which flattens the newlines out of
 * a multi-line prompt, so a verbatim comparison alone would fail to reunite exactly those
 * cards with their own image. The title is last, because it is the field most likely to
 * repeat, and it still matters because it survives the user editing the prompt before
 * approving.
 */
export function findResultForSpec(
    spec: ImageProposalSpec,
    results: ChatMessage[],
): ChatMessage | null {
    const visualId = normalizeVisualId(spec.visualId);
    const title = trimText(spec.title, TITLE_MAX_LENGTH).toLowerCase();
    const prompt = normalizePrompt(spec.prompt);
    const flatPrompt = trimText(prompt, PROMPT_MAX_LENGTH);

    const candidates: { result: ChatMessage; proposal: ImageProposalMetadata }[] = [];
    for (const result of results) {
        const proposal = readImageProposalMetadata(result);
        if (proposal) {
            candidates.push({ result, proposal });
        }
    }

    if (visualId) {
        for (const { result, proposal } of candidates) {
            const resultVisualId = normalizeVisualId(readAlias(proposal, 'visualId', 'visual_id'));
            if (resultVisualId && visualId === resultVisualId) {
                return result;
            }
        }
    }

    if (prompt) {
        for (const { result, proposal } of candidates) {
            const resultPrompt = normalizePrompt(proposal.prompt);
            if (!resultPrompt) {
                continue;
            }
            if (prompt === resultPrompt) {
                return result;
            }
            if (flatPrompt && flatPrompt === trimText(resultPrompt, PROMPT_MAX_LENGTH)) {
                return result;
            }
        }
    }

    if (title) {
        for (const { result, proposal } of candidates) {
            const resultTitle = trimText(proposal.title, TITLE_MAX_LENGTH).toLowerCase();
            if (resultTitle && title === resultTitle) {
                return result;
            }
        }
    }

    return null;
}
