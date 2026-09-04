// test_v2_chat_context_tokens.mjs
//
// Runtime test for the `#[…]` grammar behind the V2 chat context picker.
// Version: 0.261.087
// Implemented in: 0.261.087
//
// The composer holds each context reference twice: as a chip above the input and as literal
// text inside it. Everything that can go wrong with that arrangement is a silent wrong answer
// rather than a visible failure, which is why these are worth pinning:
//
//   - A token that survives an edit it should not have survived leaves a chip that keeps
//     putting a document into the request after the message stopped naming it.
//   - A `#` that opens the menu mid-word, inside an existing token, or over prose swallows the
//     Enter meant to send the message.
//   - Two documents sharing a title produce two identical tokens, and removing one then
//     removes both.
//   - Careless excision leaves a run of double spaces in the sentence the user is writing.
//
// Run directly with `node functional_tests/test_v2_chat_context_tokens.mjs`. Requires Node
// 22.6 or newer, which strips the TypeScript types so the real module is imported.

import assert from 'node:assert/strict';
import {
    MAX_CONTEXT_LABEL_LENGTH,
    appendContextToken,
    buildContextToken,
    insertContextToken,
    parseContextTokens,
    readContextQuery,
    reconcileContextItems,
    removeContextToken,
    sanitizeContextLabel,
    uniqueContextLabel,
} from '../application/v2_ui/src/lib/chatContextTokens.ts';

const checks = [];
function check(name, run) {
    checks.push([name, run]);
}

/* -------------------------------------------------------------------------- */
/* Label sanitisation                                                          */
/* -------------------------------------------------------------------------- */

check('brackets in a title cannot truncate their own token', () => {
    // `Report [final].pdf` would close the token early and leave `.pdf]` as loose text.
    const label = sanitizeContextLabel('Report [final].pdf');
    assert.equal(label, 'Report (final).pdf');
    assert.equal(parseContextTokens(buildContextToken(label)).length, 1);
});

check('newlines and runs of whitespace collapse', () => {
    assert.equal(sanitizeContextLabel('Q3\n\nContract   final.pdf'), 'Q3 Contract final.pdf');
});

check('an over-long title is capped so the message box stays readable', () => {
    const label = sanitizeContextLabel('x'.repeat(200));
    assert.ok(label.length <= MAX_CONTEXT_LABEL_LENGTH + 1, label.length);
    assert.ok(label.endsWith('…'));
});

check('colliding labels are disambiguated rather than duplicated', () => {
    const first = uniqueContextLabel('Contract.pdf', []);
    const second = uniqueContextLabel('Contract.pdf', [first]);
    const third = uniqueContextLabel('Contract.pdf', [first, second]);

    assert.equal(first, 'Contract.pdf');
    assert.equal(second, 'Contract.pdf (2)');
    assert.equal(third, 'Contract.pdf (3)');
    assert.equal(new Set([first, second, third]).size, 3);
});

/* -------------------------------------------------------------------------- */
/* Parsing                                                                     */
/* -------------------------------------------------------------------------- */

check('multi-word labels round-trip', () => {
    const text = 'compare #[Q3 Contract.pdf] against #[Q2 Contract.pdf] please';
    assert.deepEqual(
        parseContextTokens(text).map((entry) => entry.label),
        ['Q3 Contract.pdf', 'Q2 Contract.pdf'],
    );
});

check('an unclosed bracket does not swallow the next token', () => {
    // Without the `[^\]\n]+` bound, `#[oops` would run on and consume `#[Real.pdf]`.
    const found = parseContextTokens('#[oops\nand #[Real.pdf]');
    assert.deepEqual(found.map((entry) => entry.label), ['Real.pdf']);
});

check('parsing does not depend on who parsed last', () => {
    // A shared global regex keeps `lastIndex` between calls, so the second call would start
    // mid-string and silently return fewer tokens.
    const text = '#[A] #[B]';
    assert.equal(parseContextTokens(text).length, 2);
    assert.equal(parseContextTokens(text).length, 2);
});

check('an empty token is not a token', () => {
    assert.deepEqual(parseContextTokens('#[]'), []);
});

/* -------------------------------------------------------------------------- */
/* Query detection                                                             */
/* -------------------------------------------------------------------------- */

check('a hash opening a word starts a query', () => {
    const query = readContextQuery('look at #contr', 14);
    assert.deepEqual(query, { query: 'contr', start: 8, end: 14 });
});

check('a hash mid-word does not', () => {
    assert.equal(readContextQuery('C#', 2), null);
    assert.equal(readContextQuery('issue#42', 8), null);
});

check('a caret inside a finished token does not reopen the menu', () => {
    const text = '#[Contract.pdf]';
    // Just past the `#`, which is where a click lands when correcting the start of a token.
    assert.equal(readContextQuery(text, 1), null);
    assert.equal(readContextQuery(text, text.length), null);
});

check('a hash followed by a space is prose, not a search', () => {
    // `# ` trims to an empty query, which the suggestion builder reads as "offer everything",
    // holding the menu open over an ordinary sentence and swallowing the Enter meant to send it.
    assert.equal(readContextQuery('# heading', 2), null);
    assert.equal(readContextQuery('a # b', 4), null);
});

check('a bare hash opens the menu on its defaults', () => {
    // The caret sits immediately after the `#` and nothing has been typed yet, which is when
    // the menu should offer recent documents rather than wait for a character.
    assert.deepEqual(readContextQuery('a #', 3), { query: '', start: 2, end: 3 });
});

check('a numeric query is still a query', () => {
    // `#1` reads as prose in "rank #1", but it is also how `#1099-form.pdf` starts. Excluding
    // digits would make that document unreachable; an unmatched query simply draws no menu,
    // which is the same outcome without the cost.
    assert.deepEqual(readContextQuery('rank #1', 7), { query: '1', start: 5, end: 7 });
});

check('a newline ends the query', () => {
    assert.equal(readContextQuery('#contract\nnext', 14), null);
});

check('an over-long query is prose, not a search', () => {
    assert.equal(readContextQuery(`#${'x'.repeat(80)}`, 81), null);
});

/* -------------------------------------------------------------------------- */
/* Insertion                                                                   */
/* -------------------------------------------------------------------------- */

check('picking a suggestion replaces the query it was typed for', () => {
    const text = 'compare #contr';
    const query = readContextQuery(text, text.length);
    const result = insertContextToken(text, query.start, query.end, '#[Q3 Contract.pdf]');

    assert.equal(result.text, 'compare #[Q3 Contract.pdf] ');
    assert.equal(result.caret, result.text.length);
});

check('two references in a row do not accumulate spaces', () => {
    const first = insertContextToken('compare ', 8, 8, '#[A.pdf]');
    const second = insertContextToken(first.text, first.caret, first.caret, '#[B.pdf]');

    assert.equal(second.text, 'compare #[A.pdf] #[B.pdf] ');
    assert.ok(!/ {2}/.test(second.text));
});

check('inserting before existing text keeps a single separator', () => {
    const result = insertContextToken('a  b', 2, 2, '#[X]');
    assert.equal(result.text, 'a #[X] b');
});

check('the hand-off appends onto an empty composer without a leading space', () => {
    assert.equal(appendContextToken('', '#[A]'), '#[A] ');
    assert.equal(appendContextToken('note', '#[A]'), 'note #[A] ');
    assert.equal(appendContextToken('note ', '#[A]'), 'note #[A] ');
});

/* -------------------------------------------------------------------------- */
/* Removal                                                                     */
/* -------------------------------------------------------------------------- */

check('removing a mid-sentence reference leaves one space', () => {
    assert.equal(removeContextToken('compare #[A] with #[B]', '#[A]'), 'compare with #[B]');
});

check('removing every reference in turn never doubles a space', () => {
    let text = 'compare #[A] with #[B] and #[C] too';
    for (const token of ['#[A]', '#[B]', '#[C]']) {
        text = removeContextToken(text, token);
    }
    assert.equal(text, 'compare with and too');
    assert.ok(!/ {2}/.test(text));
});

check('removing a repeated reference removes all of it', () => {
    assert.equal(removeContextToken('#[A] then #[A]', '#[A]'), 'then');
});

check('removing a token that is not there changes nothing', () => {
    assert.equal(removeContextToken('compare #[A]', '#[Z]'), 'compare #[A]');
});

check('a token at the very start is removed cleanly', () => {
    assert.equal(removeContextToken('#[A] summarise this', '#[A]'), 'summarise this');
});

/* -------------------------------------------------------------------------- */
/* Reconciliation                                                              */
/* -------------------------------------------------------------------------- */

const items = [
    { key: 'document:a', token: '#[A.pdf]' },
    { key: 'document:b', token: '#[B.pdf]' },
];

check('editing a token out of the text retires its chip', () => {
    assert.deepEqual(
        reconcileContextItems('compare #[B.pdf]', items).map((item) => item.key),
        ['document:b'],
    );
});

check('backspacing through a token retires its chip', () => {
    // Mid-delete the token is malformed, which must already count as gone -- otherwise the
    // chip lingers over a message that no longer names the document.
    assert.deepEqual(reconcileContextItems('compare #[A.pd', items), []);
});

check('a hand-typed token never invents a chip', () => {
    // There is no id behind it, so adopting it would put a document into the request that the
    // user never chose from the menu.
    assert.deepEqual(reconcileContextItems('#[A.pdf] #[Invented.pdf]', items), [items[0]]);
});

check('chip order follows the row, not the sentence', () => {
    assert.deepEqual(
        reconcileContextItems('#[B.pdf] then #[A.pdf]', items).map((item) => item.key),
        ['document:a', 'document:b'],
    );
});

check('reconciling an empty row is a no-op', () => {
    assert.deepEqual(reconcileContextItems('#[A.pdf]', []), []);
});

/* -------------------------------------------------------------------------- */

let failed = 0;
for (const [name, run] of checks) {
    try {
        run();
        console.log(`  PASS  ${name}`);
    } catch (error) {
        failed += 1;
        console.error(`  FAIL  ${name}`);
        console.error(`        ${error.message}`);
    }
}

console.log(`\n${checks.length - failed}/${checks.length} checks passed`);
process.exit(failed === 0 ? 0 : 1);
