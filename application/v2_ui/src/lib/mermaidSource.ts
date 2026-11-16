// mermaidSource.ts
// Repairs the mistakes models actually make when writing Mermaid, so a diagram that would
// otherwise be shown as a wall of source renders instead.
//
// Every rule here corresponds to a failure reproduced against the vendored mermaid 11.17.2
// bundle in Chromium, configured exactly as MermaidDiagram.tsx configures it. Nothing is
// speculative: a rule that could not be made to fail was not written.
//
// This runs only on a SECOND attempt, after mermaid has already rejected the source. A diagram
// that renders today is handed to mermaid untouched and is never rewritten, so this cannot
// regress anything that currently works. That ordering matters more than the rules themselves:
// repairing model output is inherently lossy, and the correct source is always preferred.

/**
 * Words the flowchart grammar reserves, which cannot be used as a node id.
 *
 * `end` is the one models hit constantly, because it is the natural name for the last box in a
 * flow. `default` is deliberately absent: it parses, so renaming it would be a change with no
 * failure behind it.
 */
const RESERVED_NODE_IDS = new Set(['end', 'graph', 'class', 'style', 'subgraph', 'click']);

/** Suffix appended when a reserved id has to be renamed. Unlikely to collide with a real id. */
const RENAME_SUFFIX = '_node';

/** Characters that look like quotes to a model but are not the quote the grammar wants. */
const SMART_QUOTES = /[\u2018\u2019\u201a\u201b\u2032]/g;
const SMART_DOUBLE_QUOTES = /[\u201c\u201d\u201e\u201f\u2033]/g;

/** Whitespace that survives a copy-paste and is not the whitespace the lexer expects. */
const EXOTIC_SPACES = /[\u00a0\u2000-\u200a\u202f\u205f\u3000]/g;
const ZERO_WIDTH = /[\u200b-\u200d\u2060\ufeff]/g;

/** `<br>` in any of the spellings a model reaches for. */
const BR_VARIANTS = /<\s*br\s*\/?\s*>/gi;

/** A quoted label, used only once every label is known to hold no bare quotes. */
const QUOTED_LABEL = /"([^"\n]*)"/g;

/** A square node declaration: an id, a `[`, its text, and the first `]` after it. */
const SQUARE_NODE = /([\w-]+)\[([^\]\n]*)\]/g;

/** An edge label between pipes. */
const EDGE_LABEL = /\|([^|\n]*)\|/g;

/** An opening `subgraph` statement. */
const SUBGRAPH_LINE = /^\s*subgraph\b/;

/** A terminator, in the only spelling the grammar accepts and the ones it does not. */
const END_LINE = /^\s*end\s*$/;
const MISCASED_END_LINE = /^\s*(END|End|eNd|enD|EnD|ENd|eND)\s*$/;

/**
 * Normalise the characters a model picked up from whatever it was reading.
 *
 * A leading byte-order mark is the sharpest of these: it makes the very first token
 * `\ufeffflowchart` rather than `flowchart`, so mermaid reports that no diagram type was
 * detected when the source is otherwise perfect.
 */
function normalizeCharacters(source: string): string {
    return source
        .replace(ZERO_WIDTH, '')
        .replace(/\r\n?/g, '\n')
        .replace(EXOTIC_SPACES, ' ')
        .replace(SMART_QUOTES, "'")
        .replace(SMART_DOUBLE_QUOTES, '"')
        .replace(BR_VARIANTS, '<br/>');
}

/**
 * True for a line that is a comment rather than a statement.
 *
 * Used to leave alone any line the statement-level rules should not touch.
 */
function isCommentLine(line: string): boolean {
    return /^\s*%%/.test(line);
}

/** Placeholder standing in for `<br/>` while the rest of a label is escaped around it. */
const BR_PLACEHOLDER = '\u0001BR\u0001';

/** Delimiter for text held aside while a pattern runs over everything around it. */
const STASH_OPEN = '\u0002';

/** Put stashed text back where it came from. */
function unstash(text: string, stash: string[]): string {
    return text.replace(
        new RegExp(`${STASH_OPEN}(\\d+)${STASH_OPEN}`, 'g'),
        (_match, index: string) => stash[Number(index)],
    );
}

/**
 * Escape everything in a label's text that the grammar or the sanitizer would take as syntax.
 *
 * A bare `"` is the sharpest of these: the string token runs to the next quote, so a label like
 * `"He said "hello" loudly"` ends after `said ` and the remainder is parsed as syntax. Braces
 * and angle brackets are escaped for the same reason, and because a model transcribing a header
 * such as `x-ms-client-request-id: <random GUID>` has no idea it is writing markup — mermaid's
 * sanitizer would otherwise drop the placeholder entirely and lose the text.
 *
 * `<br/>` is protected first. It is the one piece of markup a label is meant to contain, and it
 * is what the guidance in functions_diagram_operations.py explicitly asks models to use.
 */
function escapeLabelText(text: string): string {
    return text
        .split('<br/>')
        .join(BR_PLACEHOLDER)
        .replace(/&(?![a-zA-Z][a-zA-Z0-9]{1,10};|#\d{1,6};|#x[0-9a-fA-F]{1,5};)/g, '&amp;')
        .replace(/"/g, '&quot;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/\{/g, '&#123;')
        .replace(/\}/g, '&#125;')
        .split(BR_PLACEHOLDER)
        .join('<br/>');
}

/**
 * Rewrite one label's raw text into a quoted, escaped label.
 *
 * Returns null when nothing needs doing, which is what keeps the repair a no-op for a diagram
 * that is merely a different kind of broken — and what lets `isRepairWorthTrying` answer
 * honestly.
 */
function repairLabelBody(body: string): string | null {
    const trimmed = body.trim();
    if (trimmed === '') {
        // An empty label fails to parse. A single space keeps the node, unlabelled, rather
        // than dropping it: it is still part of the answer the model gave.
        return ' ';
    }

    const quoted = trimmed.length >= 2 && trimmed.startsWith('"') && trimmed.endsWith('"');
    const inner = quoted ? trimmed.slice(1, -1) : trimmed;

    if (inner.trim() === '') {
        return ' ';
    }

    const escaped = escapeLabelText(inner);
    if (quoted && escaped === inner) {
        return null;
    }
    return escaped;
}

/**
 * Quote and escape node and edge labels.
 *
 * Only the square node form and the piped edge form are handled. Those are where every
 * reproduced failure came from, and they are the two whose extent can be determined without
 * guessing: a body containing the shape's own delimiter is skipped rather than mis-split.
 *
 * Square nodes are rewritten first and stashed. A pipe is legal inside a node label, and the
 * edge-label pattern has no notion of quoting, so without stashing it would pair a pipe inside
 * a label with the pipe that opens the real edge label and rewrite the arrow between them.
 */
function repairLabels(line: string): string {
    const stash: string[] = [];

    const withNodes = line.replace(SQUARE_NODE, (_match, id: string, body: string) => {
        let rebuilt: string;
        if (body.includes('[')) {
            rebuilt = `${id}[${body}]`;
        } else {
            const fixed = repairLabelBody(body);
            rebuilt = fixed === null ? `${id}[${body}]` : `${id}["${fixed}"]`;
        }
        stash.push(rebuilt);
        return `${STASH_OPEN}${stash.length - 1}${STASH_OPEN}`;
    });

    // An odd number of remaining pipes means they cannot all be label delimiters, so pairing
    // them would be a guess. Left alone rather than rewritten wrongly.
    const pipes = (withNodes.match(/\|/g) ?? []).length;
    const withEdges =
        pipes % 2 === 0
            ? withNodes.replace(EDGE_LABEL, (_match, body: string) => {
                  // `||` is an empty edge label in a flowchart, but it is also cardinality in
                  // an erDiagram. Left alone either way: there is nothing in it to repair.
                  if (body.trim() === '') {
                      return `|${body}|`;
                  }
                  const fixed = repairLabelBody(body);
                  return fixed === null ? `|${body}|` : `|"${fixed}"|`;
              })
            : withNodes;

    return unstash(withEdges, stash);
}

/**
 * True when the source is a flowchart.
 *
 * Every rule below the character normalisation is flowchart grammar. `subgraph`, `end`, square
 * node labels and piped edge labels all mean something else, or nothing, in the ten other
 * diagram types mermaid supports, and rewriting a sequence diagram with flowchart rules would
 * turn one failure into a different one.
 */
function isFlowchart(source: string): boolean {
    for (const line of source.split('\n')) {
        const trimmed = line.trim();
        if (trimmed === '' || trimmed.startsWith('%%')) {
            continue;
        }
        return /^(flowchart|graph)\b/.test(trimmed);
    }
    return false;
}

/**
 * Rename node ids the grammar reserves.
 *
 * Every occurrence of the identifier is rewritten, not just its declaration, so the edges that
 * referred to it still connect. Bounded to word boundaries, and skipped inside quoted labels,
 * comments and `subgraph` terminators, so prose that merely contains the word is untouched.
 *
 * Excluding terminators is what makes `end` safe to rename at all. A lowercase `end` on its own
 * line closes a `subgraph`; renaming those alongside a node called `end` would silently move
 * everything that followed a terminator inside the group it was meant to close, and the result
 * still parses, so the reader would be shown a diagram with the wrong structure rather than an
 * error.
 */
function renameReservedIds(source: string): string {
    const stash: string[] = [];
    const hold = (text: string) => {
        stash.push(text);
        return `${STASH_OPEN}${stash.length - 1}${STASH_OPEN}`;
    };

    const stashed = source
        .split('\n')
        .map((line) => {
            if (isCommentLine(line) || END_LINE.test(line)) {
                return hold(line);
            }
            return line.replace(QUOTED_LABEL, (match) => hold(match));
        })
        .join('\n');

    let repaired = stashed;
    for (const reserved of RESERVED_NODE_IDS) {
        // A declaration: the reserved word immediately followed by a shape opener. `subgraph`
        // and `click` are keywords followed by a space, so only the shape form can be a node.
        const declaration = new RegExp(`(^|[^\\w-])${reserved}(\\s*[\\[({])`, 'gm');
        if (!declaration.test(repaired)) {
            continue;
        }
        repaired = repaired.replace(
            new RegExp(`(^|[^\\w-])${reserved}(?![\\w-])`, 'gm'),
            (_match, prefix: string) => `${prefix}${reserved}${RENAME_SUFFIX}`,
        );
    }

    return unstash(repaired, stash);
}

/**
 * Fix the terminator's case and close any subgraph that was left open.
 *
 * The grammar accepts only lowercase `end`. An unclosed `subgraph` swallows everything after
 * it, so the error mermaid reports points at the last line of the diagram rather than at the
 * statement that is actually wrong — which makes it one of the harder failures to read.
 */
function balanceSubgraphs(source: string): string {
    const lines = source.split('\n').map((line) => {
        if (MISCASED_END_LINE.test(line)) {
            return line.replace(/(END|End|eNd|enD|EnD|ENd|eND)/, 'end');
        }
        return line;
    });

    let open = 0;
    for (const line of lines) {
        if (isCommentLine(line)) {
            continue;
        }
        if (SUBGRAPH_LINE.test(line)) {
            open += 1;
        } else if (END_LINE.test(line) && open > 0) {
            open -= 1;
        }
    }

    for (let index = 0; index < open; index += 1) {
        lines.push('end');
    }

    return lines.join('\n');
}

/**
 * Drop a statement that names a source but no target.
 *
 * A reply truncated mid-diagram ends in a dangling `A -->`, which fails to parse and takes the
 * whole diagram with it. The rest of the diagram is still worth drawing.
 */
function dropDanglingEdges(source: string): string {
    return source
        .split('\n')
        .filter((line) => !/^\s*[\w-]+\s*(-{2,}>?|={2,}>?|-\.->?)\s*$/.test(line))
        .join('\n');
}

/** Split node declarations that a model ran together onto one line. */
function splitRunTogetherStatements(source: string): string {
    return source
        .split('\n')
        .map((line) => {
            if (isCommentLine(line) || /-->|---|-\.-|==>/.test(line)) {
                return line;
            }
            const indent = /^\s*/.exec(line)?.[0] ?? '';
            return line.replace(
                /(\]|\)|\})\s+(?=[\w-]+\s*[\[({])/g,
                (_match, close: string) => `${close}\n${indent}`,
            );
        })
        .join('\n');
}

/**
 * A best-effort rewrite of diagram source mermaid has already rejected.
 *
 * Pure and synchronous, so it can be unit tested without a browser. Returns the source
 * unchanged when nothing applies, which the caller uses to skip a pointless second render.
 */
export function repairMermaidSource(source: string): string {
    if (!source) {
        return source;
    }

    const normalized = normalizeCharacters(source);
    if (!isFlowchart(normalized)) {
        return normalized.trim();
    }

    let repaired = splitRunTogetherStatements(normalized);
    repaired = repaired
        .split('\n')
        .map((line) => (isCommentLine(line) ? line : repairLabels(line)))
        .join('\n');
    repaired = renameReservedIds(repaired);
    repaired = balanceSubgraphs(repaired);
    repaired = dropDanglingEdges(repaired);

    return repaired.trim();
}

/** True when repairing would produce something different, so a retry is worth attempting. */
export function isRepairWorthTrying(source: string): boolean {
    const trimmed = source.trim();
    return repairMermaidSource(trimmed) !== trimmed;
}

/**
 * A short, readable reason a diagram could not be drawn.
 *
 * Mermaid's own messages are multi-line parser dumps with a caret diagram in them. The first
 * line carries the useful part; the rest belongs in the details disclosure, not in a summary.
 * The two limit errors are recognised and reworded, because "Edge limit exceeded" tells a
 * reader nothing about what to do next.
 */
export function describeMermaidError(error: unknown): string {
    const raw =
        error instanceof Error
            ? error.message
            : typeof error === 'string'
              ? error
              : '';
    const text = raw.trim();

    if (!text) {
        return 'The diagram could not be drawn.';
    }
    if (/edge limit exceeded/i.test(text)) {
        return 'The diagram has too many connections to draw.';
    }
    if (/maximum text size/i.test(text)) {
        return 'The diagram source is too large to draw.';
    }
    if (/no diagram type detected/i.test(text)) {
        return 'The first line does not name a diagram type mermaid recognises.';
    }

    const firstLine = text.split('\n', 1)[0].trim();
    return firstLine.length > 200 ? `${firstLine.slice(0, 197)}…` : firstLine;
}
