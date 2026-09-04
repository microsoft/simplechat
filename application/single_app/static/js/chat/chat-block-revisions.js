// chat-block-revisions.js
// Reading, from the classic client, the block revisions the V2 client stores.
//
// A diagram or a chart in a reply can be edited in V2. The edit is stored against the message
// rather than written into it, so a reader who opens the same conversation here would otherwise
// see the version the model first produced, with no sign that it had been changed — and would
// then export that stale version.
//
// Both rich block kinds resolve their revisions the same way, and they have to, because the
// rule is subtle enough that two implementations of it would eventually disagree: an entry is
// found by position and *confirmed by fingerprint*; when that fails the fingerprint is searched
// for across the message and used only when the match is unambiguous; and every way this can go
// wrong leaves the original in place. The server applies the same rule in
// ``functions_message_block_revisions.py``.

/**
 * The exact set `String.prototype.trim` removes.
 *
 * Spelled out because the fingerprint below has to agree, character for character, with
 * `fingerprintSource` in the V2 client and `fingerprint_source` on the server. A regular
 * `.trim()` would in fact do, but writing the set down is what makes the agreement checkable.
 */
const JS_TRIM_PATTERN = /^[\s\uFEFF\u00A0]+|[\s\uFEFF\u00A0]+$/g;

/**
 * Fingerprint a block's source.
 *
 * A port of `fingerprintSource` in application/v2_ui/src/lib/visualPalettes.ts, which is what
 * computes the hashes that get stored. A revision is filed under the fingerprint of the block's
 * original source, so classic can only find the right entry by computing the same value.
 */
export function fingerprintSource(value) {
    const normalized = String(value ?? '').replace(/\r\n/g, '\n').replace(JS_TRIM_PATTERN, '');
    let hash = 0x811c9dc5;
    for (let index = 0; index < normalized.length; index += 1) {
        hash ^= normalized.charCodeAt(index);
        hash = Math.imul(hash, 0x01000193);
    }
    return (hash >>> 0).toString(16).padStart(8, '0');
}

/** The source a stored entry currently points at, or null when the original still applies. */
export function readCurrentRevisionSource(entry) {
    if (!entry || typeof entry !== 'object' || !Array.isArray(entry.revisions)) {
        return null;
    }
    const current = entry.current;
    if (!Number.isInteger(current) || current <= 0 || current >= entry.revisions.length) {
        return null;
    }
    const source = entry.revisions[current]?.source;
    return typeof source === 'string' && source ? source : null;
}

/**
 * Swap the current version into every block that has one.
 *
 * `applyRevision` is given the block and the resolved source, and returns the block to show. It
 * returns null when the revision is not usable — a chart payload that no longer parses, say —
 * which keeps the original on screen rather than replacing it with nothing.
 */
export function applyStoredBlockRevisions(blocks, blockRevisions, language, applyRevision) {
    const entries = blockRevisions && typeof blockRevisions === 'object'
        ? blockRevisions[language]
        : null;
    if (!entries || typeof entries !== 'object' || !Array.isArray(blocks)) {
        return blocks;
    }

    return blocks.map((block, index) => {
        if (!block || block.pending || typeof block.sourceHash !== 'string') {
            return block;
        }

        let entry = entries[String(index)];
        if (!entry || entry.source_hash !== block.sourceHash) {
            // The position disagrees, which happens when the two clients number the fences
            // differently. Fall back to the fingerprint, and only when it is unambiguous.
            const matches = Object.values(entries).filter(
                candidate => candidate && candidate.source_hash === block.sourceHash,
            );
            entry = matches.length === 1 ? matches[0] : null;
        }

        const source = readCurrentRevisionSource(entry);
        if (!source) {
            return block;
        }

        return applyRevision(block, source) || block;
    });
}
