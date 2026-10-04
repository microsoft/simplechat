// test_chat_math_segments.js
// Version: 0.261.047. Implemented in: 0.261.047.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { test } = require('node:test');

const appRoot = path.join(__dirname, '..', 'application', 'single_app');
const source = fs.readFileSync(path.join(appRoot, 'static', 'js', 'chat', 'chat-math-segments.js'), 'utf8');
const parser = import(`data:text/javascript;base64,${Buffer.from(source).toString('base64')}`);
const { marked } = require(path.join(appRoot, 'static', 'js', 'chat', 'marked.min.js'));
const katex = require(path.join(appRoot, 'static', 'vendor', 'katex-0.18.4', 'katex.min.js'));

test('V2 delimiters survive V1 Markdown and render fractions and matrix rows', async () => {
    const { parseMath, restoreMathSource } = await parser;
    for (const [input, display] of [
        [String.raw`Inline \(x_n = \frac{X_c}{Z_c}\).`, false],
        [String.raw`\[\mathbf{X}_c = \begin{bmatrix}X_c \\ Y_c \\ Z_c\end{bmatrix}\]`, true],
        ['$$x^2$$', true],
        ['Value $$x^2$$ here.', false],
    ]) {
        const parsed = parseMath(input);
        assert.equal(parsed.segments.length, 1);
        assert.equal(parsed.segments[0].display, display);
        assert.match(marked.parse(parsed.text), parsed.pattern);
        assert.equal(restoreMathSource(parsed.text, parsed), input);
        const html = katex.renderToString(parsed.segments[0].tex, { displayMode: display, trust: false });
        assert.match(html, /class="katex"/);
        if (input.includes('bmatrix')) assert(parsed.segments[0].tex.includes(String.raw`X_c \\ Y_c`));
    }
});

test('currency, code, attributes, link destinations and incomplete streams remain unchanged', async () => {
    const { parseMath } = await parser;
    for (const input of [
        'Costs $5 to $10 per user.',
        String.raw`literal \\(x\\) and \$5`,
        '`\\(x\\)` and `` $$x$$ ``',
        '```tex\n\\[x\\]\n```',
        '~~~tex\n$$x$$\n~~~',
        '````tex\n```\n\\[x\\]\n````',
        '   ```\n$$x$$\n   ```',
        '```tex\n\\[x\\]',
        String.raw`\[x +`,
        String.raw`\( \)`,
        String.raw`[reference](https://example.test/\(x\))`,
        String.raw`[reference]: https://example.test/$$x$$`,
        String.raw`<span title="\[x\]">text</span>`,
    ]) {
        const parsed = parseMath(input);
        assert.equal(parsed.text, input);
        assert.equal(parsed.segments.length, 0, input);
    }
});

test('complete expressions emerge during streaming and source restoration is exact', async () => {
    const { parseMath, restoreMathSource } = await parser;
    const input = String.raw`Before \(x\), then \[ \frac{1}{2} \] after.`;
    for (let length = 0; length <= input.length; length += 1) {
        const partial = input.slice(0, length);
        const parsed = parseMath(partial);
        assert.equal(restoreMathSource(parsed.text, parsed), partial);
        for (const segment of parsed.segments) assert(segment.tex.trim());
    }
});

test('expression count, length and placeholder collisions are bounded', async () => {
    const { parseMath, restoreMathSource, MAX_MATH_LENGTH } = await parser;
    assert.equal(parseMath('\\[' + 'x'.repeat(MAX_MATH_LENGTH) + '\\]').segments.length, 1);
    assert.equal(parseMath('\\[' + 'x'.repeat(MAX_MATH_LENGTH + 1) + '\\]').segments.length, 0);
    const many = String.raw`\(x\) `.repeat(150);
    const parsed = parseMath(many);
    assert.equal(parsed.segments.length, 100);
    assert.equal(restoreMathSource(parsed.text, parsed), many);
    const collision = '\u27e6scmath:0:0\u27e7 ' + String.raw`\(x\)`;
    const safe = parseMath(collision);
    assert(safe.text.startsWith('\u27e6scmath:0:0\u27e7 '));
    assert.equal(restoreMathSource(safe.text, safe), collision);
});
