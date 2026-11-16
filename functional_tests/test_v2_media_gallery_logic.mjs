// test_v2_media_gallery_logic.mjs
// Version: 0.261.262
// Implemented in: 0.261.262
// Runs the real V2 gallery plugin inside the real react-markdown pipeline (remark-gfm and
// remark-breaks, as the chat renders replies) over the shapes agents actually answer with: a
// caption line over each image or clip, one paragraph alternating caption and media, images on
// their own, and evidence lists that link a clip after each item's sentence with a still below.
// Also checks what must not group (a single image, a recording, a link mid-sentence, a table,
// unsafe or inline data URLs), that react-markdown's URL transform still runs on every grouped
// image and clip, and the download file naming and still-frame helpers.

import assert from 'node:assert/strict';
import { createRequire } from 'node:module';
import { pathToFileURL } from 'node:url';
import './test_support/tsResolve.mjs';

const hadWindow = 'window' in globalThis;
const previousWindow = globalThis.window;
globalThis.window = { location: { href: 'https://chat.example.test/chat', origin: 'https://chat.example.test' } };

const require = createRequire(new URL('../application/v2_ui/package.json', import.meta.url));
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const load = (name) => import(pathToFileURL(require.resolve(name)).href);

const checks = [];
const check = (name, run) => checks.push([name, run]);

try {
    const { default: Markdown, defaultUrlTransform } = await load('react-markdown');
    const { default: remarkGfm } = await load('remark-gfm');
    const { default: remarkBreaks } = await load('remark-breaks');
    const { readMediaGallery, rehypeMediaGallery } = await import('../application/v2_ui/src/lib/mediaGallery.ts');
    const { mediaFileName } = await import('../application/v2_ui/src/lib/mediaDownload.ts');
    const { posterFrameUrl } = await import('../application/v2_ui/src/lib/inlineMedia.ts');

    const MEDIA = 'https://media.example.test/media';

    /** Render as the chat does, recording what the renderer reads off each gallery. */
    function render(markdown, urlTransform = defaultUrlTransform) {
        const galleries = [];
        const html = renderToStaticMarkup(React.createElement(Markdown, {
            remarkPlugins: [remarkGfm, remarkBreaks],
            rehypePlugins: [rehypeMediaGallery],
            urlTransform,
            components: {
                div: ({ node, children, ...props }) => {
                    const items = readMediaGallery(node);
                    if (items) {
                        galleries.push(items);
                    }
                    return React.createElement('div', props, children);
                },
            },
        }, markdown));
        return { html, galleries };
    }

    const count = (html, pattern) => (html.match(pattern) ?? []).length;
    const captions = (html) => [...html.matchAll(/<figcaption>([\s\S]*?)<\/figcaption>/g)].map((match) => match[1]);

    check('caption paragraphs over each image or clip become one captioned gallery', () => {
        const { html, galleries } = render([
            'Here is what the records returned.',
            '',
            'Lobby camera still \u2014 record R-1; October 4, 13:38.  ',
            `![Lobby camera at 13:38](${MEDIA}/lobby-still-1.png?exp=1&sig=a)`,
            '',
            'Badge photo \u2014 record R-1.  ',
            `![Badge photo](${MEDIA}/badge-1.png?exp=1&sig=b)`,
            '',
            'Loading dock clip \u2014 record R-2; October 4, 13:37.  ',
            `[Open video: Loading dock camera clip at 13:37 (8 s)](${MEDIA}/dock-clip-2.mp4?exp=1&sig=c)`,
            '',
            'Receipt scan \u2014 record R-3.  ',
            `![Receipt R-3](${MEDIA}/receipt-3.png)`,
            '',
            'Initial call \u2014 recording C-1.  ',
            `[Open audio: Call audio C-1](${MEDIA}/call-1.wav?exp=1&sig=d)`,
        ].join('\n'));
        assert.equal(galleries.length, 1, html);
        assert.deepEqual(galleries[0].map((item) => [item.kind, item.title, item.detail]), [
            ['image', 'Lobby camera still \u2014 record R-1; October 4, 13:38.', 'Lobby camera at 13:38'],
            ['image', 'Badge photo \u2014 record R-1.', 'Badge photo'],
            ['video', 'Loading dock clip \u2014 record R-2; October 4, 13:37.', 'Loading dock camera clip at 13:37 (8 s)'],
            ['image', 'Receipt scan \u2014 record R-3.', 'Receipt R-3'],
        ]);
        assert.equal(galleries[0][0].src, `${MEDIA}/lobby-still-1.png?exp=1&sig=a`, 'a signed link keeps its query');
        assert.match(html, /^<p>Here is what the records returned\.<\/p>\s*<div data-media-gallery="4">/);
        assert.equal(count(html, /<figure data-media-kind="image">/g), 3);
        assert.equal(count(html, /<figure data-media-kind="video">/g), 1);
        assert.deepEqual([...html.matchAll(/data-media-tile="(\d+)"/g)].map((match) => match[1]), ['0', '1', '2', '3']);
        // The recording keeps its own player, after the gallery, with its caption beside it.
        assert.match(html, /<\/div>\s*<p>Initial call \u2014 recording C-1\.<br\/>\s*<a href="[^"]*call-1\.wav[^"]*">Open audio: Call audio C-1<\/a><\/p>$/);
    });

    check('one paragraph alternating caption and media lines groups the same way', () => {
        const { html, galleries } = render([
            'Lobby camera still \u2014 record R-1.',
            `![Lobby camera at 13:38](${MEDIA}/lobby-still-1.png)`,
            'Loading dock clip \u2014 record R-2.',
            `[Open video: Loading dock camera clip](${MEDIA}/dock-clip-2.mp4)`,
            'Receipt scan \u2014 record R-3.',
            `![Receipt R-3](${MEDIA}/receipt-3.png)`,
            'Initial call \u2014 recording C-1.',
            `[Open audio: Call audio C-1](${MEDIA}/call-1.wav)`,
        ].join('\n'));
        assert.equal(galleries.length, 1);
        assert.deepEqual(galleries[0].map((item) => item.title), [
            'Lobby camera still \u2014 record R-1.', 'Loading dock clip \u2014 record R-2.', 'Receipt scan \u2014 record R-3.',
        ]);
        assert.match(html, /<\/div>\s*<p>Initial call \u2014 recording C-1\.<br\/>\s*<a href=/, 'the recording and its caption stay text');
    });

    check('images in paragraphs of their own group under their alt text', () => {
        const { html, galleries } = render([
            '## Images',
            '',
            `![Identity document scan](${MEDIA}/document.png)`,
            '',
            `![Arrival photo](${MEDIA}/arrival.png)`,
        ].join('\n'));
        assert.equal(galleries.length, 1);
        assert.deepEqual(galleries[0].map((item) => [item.title, item.detail]), [
            ['Identity document scan', ''], ['Arrival photo', ''],
        ]);
        assert.deepEqual(captions(html), ['Identity document scan', 'Arrival photo']);
        assert.match(html, /^<h2>Images<\/h2>\s*<div data-media-gallery="2">/);
    });

    check('a single image keeps its full-size rendering', () => {
        const { html, galleries } = render(`Intro.\n\n![Only one](${MEDIA}/one.png)\n\nOutro.`);
        assert.equal(galleries.length, 0);
        assert.match(html, /<p><img src="[^"]*one\.png" alt="Only one"\/><\/p>/);
    });

    check('a line ending in a colon over several images introduces them and stays text', () => {
        const { html, galleries } = render([
            'Stills from both cameras:',
            `![North camera](${MEDIA}/north.png)`,
            `![South camera](${MEDIA}/south.png)`,
            'That is everything.',
        ].join('\n'));
        assert.equal(galleries.length, 1);
        assert.deepEqual(galleries[0].map((item) => item.title), ['North camera', 'South camera']);
        assert.match(html, /^<p>Stills from both cameras:<\/p>\s*<div data-media-gallery="2">[\s\S]*<\/div>\s*<p>That is everything\.<\/p>$/);
    });

    check('a label ending in a colon over a single image captions it, without the colon', () => {
        const { html, galleries } = render([
            '## Signed documents',
            '',
            '**Search of room 117** (application A-1; execute by October 19):  ',
            `![Signed document A-1](${MEDIA}/document-a1.png)`,
            '',
            '**Search of the vehicle** (application A-2):  ',
            `![Signed document A-2](${MEDIA}/document-a2.png)`,
        ].join('\n'));
        assert.equal(galleries.length, 1, html);
        assert.deepEqual(galleries[0].map((item) => [item.title, item.detail]), [
            ['Search of room 117 (application A-1; execute by October 19)', 'Signed document A-1'],
            ['Search of the vehicle (application A-2)', 'Signed document A-2'],
        ]);
        assert.deepEqual(captions(html), [
            '<strong>Search of room 117</strong> (application A-1; execute by October 19)',
            '<strong>Search of the vehicle</strong> (application A-2)',
        ]);
    });

    check('an evidence list puts each item\'s clip and still in a row under its text', () => {
        const { html, galleries } = render([
            `- **06:31, camera 12:** Gray sedan heading west on Main Street. [Video](${MEDIA}/clip-12-0631.mp4)  `,
            `  ![Camera 12 still 06:31](${MEDIA}/still-12-0631.png)`,
            '',
            `- **07:01, camera 12:** Same sedan heading east. [Video](${MEDIA}/clip-12-0701.mp4)  `,
            `  ![Camera 12 still 07:01](${MEDIA}/still-12-0701.png)`,
        ].join('\n'));
        assert.equal(galleries.length, 2, html);
        for (const gallery of galleries) {
            assert.deepEqual(gallery.map((item) => item.kind), ['video', 'image']);
            assert.equal(gallery[0].title, 'Video');
        }
        assert.match(html, /<li>\s*<p><strong>06:31, camera 12:<\/strong> Gray sedan heading west on Main Street\.<\/p>\s*<div data-media-gallery="2">/);
        assert.doesNotMatch(html, /Main Street\. <a /, 'the clip link moved into the row');
    });

    check('a tight list item groups its photos, and an item without media is left alone', () => {
        const { html, galleries } = render([
            '- **Citation 4410 \u2014 issued 08:40.** A sedan was cited near the inn.',
            `  ![Citation photo 1](${MEDIA}/citation-1.png)`,
            `  ![Citation photo 2](${MEDIA}/citation-2.png)`,
            '- **06:31 \u2014 camera 12:** Full read, westbound.',
            `  ![Camera 12 still](${MEDIA}/still-12.png)`,
            '- No media in this item.',
        ].join('\n'));
        assert.deepEqual(galleries.map((gallery) => gallery.length), [2, 1]);
        assert.match(html, /<li><strong>Citation 4410 \u2014 issued 08:40\.<\/strong> A sedan was cited near the inn\.<div data-media-gallery="2">/);
        assert.match(html, /<li>No media in this item\.<\/li>/);
    });

    check('clips linked mid-sentence stay where they are', () => {
        const { html, galleries } = render(
            `- Compare [the first clip](${MEDIA}/a.mp4) with [the second](${MEDIA}/b.mp4)`,
        );
        assert.equal(galleries.length, 0);
        assert.equal(count(html, /<a href=/g), 2);
    });

    check('three clips in a row group without their "Open video" wording', () => {
        const { galleries } = render([
            `[Open video: North gate clip](${MEDIA}/north.mp4)`,
            `[Watch the clip - South gate](${MEDIA}/south.webm)`,
            `[${MEDIA}/east.mov](${MEDIA}/east.mov)`,
        ].join('\n'));
        assert.deepEqual(galleries[0].map((item) => [item.kind, item.title]), [
            ['video', 'North gate clip'], ['video', 'South gate'], ['video', 'east.mov'],
        ]);
    });

    check('unsafe and inline data sources never group', () => {
        const { html, galleries } = render([
            '![Bad](javascript:alert(1))',
            '![Inline](data:image/png;base64,AAAA)',
            '[Open video: Bad clip](javascript:alert(1)//x.mp4)',
            `![Not served here](/static/x.png)`,
        ].join('\n'));
        assert.equal(galleries.length, 0);
        assert.doesNotMatch(html, /javascript:|data:image/, 'react-markdown still empties unsafe URLs');
    });

    check('block quotes group, tables do not', () => {
        const quoted = render(`> ![Quoted one](${MEDIA}/q1.png)\n> ![Quoted two](${MEDIA}/q2.png)`);
        assert.equal(quoted.galleries.length, 1);
        assert.match(quoted.html, /^<blockquote>\s*<div data-media-gallery="2">/);
        const table = render([
            '| A | B |',
            '| --- | --- |',
            `| ![one](${MEDIA}/t1.png) | ![two](${MEDIA}/t2.png) |`,
        ].join('\n'));
        assert.equal(table.galleries.length, 0);
    });

    check('titles drop citation and maths placeholders and stand in for masked text', () => {
        const { html, galleries } = render([
            'Camera still \u27E6cite:0\u27E7 \u2014 reviewed by \u27E6mask:1\u27E7.',
            `![Still A](${MEDIA}/a.png)`,
            'Second still \u27E6math:0\u27E7.',
            `![Still B](${MEDIA}/b.png)`,
        ].join('\n'));
        assert.deepEqual(galleries[0].map((item) => item.title), [
            'Camera still \u2014 reviewed by [masked].', 'Second still.',
        ]);
        // The caption keeps its placeholders, for the renderer to swap for chips and redactions.
        assert.match(captions(html)[0], /\u27E6cite:0\u27E7/);
    });

    check('react-markdown\'s URL transform still runs on every grouped image and clip', () => {
        const seen = [];
        const { html, galleries } = render([
            `![One](${MEDIA}/1.png)`,
            `[Open video: Two](${MEDIA}/2.mp4)`,
        ].join('\n'), (url, key) => {
            seen.push(key);
            return `${url}#checked`;
        });
        assert.deepEqual(galleries[0].map((item) => item.src), [`${MEDIA}/1.png#checked`, `${MEDIA}/2.mp4#checked`]);
        assert.deepEqual(seen.sort(), ['href', 'src']);
        assert.match(html, /src="[^"]*1\.png#checked"/);
    });

    check('downloads are named after the file in the URL, else the title', () => {
        assert.equal(mediaFileName(`${MEDIA}/call-1.wav?exp=1&sig=d`, 'Call audio C-1', 'audio'), 'call-1.wav');
        assert.equal(mediaFileName(`${MEDIA}/a%20b.mp3`, 'x', 'audio'), 'a b.mp3');
        assert.equal(mediaFileName('https://media.example.test/api/clip/123', 'Dock clip', 'video', 'video/webm'), 'Dock clip.webm');
        assert.equal(mediaFileName('data:image/png;base64,AAAA', 'Lobby: still?', 'image', 'image/png'), 'Lobby still.png');
        assert.equal(mediaFileName(`${MEDIA}/`, '', 'video'), 'video.mp4');
        assert.equal(mediaFileName(`${MEDIA}/..%2F..%2Fevil.mp4`, 'x', 'video'), 'evil.mp4');
        assert.equal(mediaFileName('javascript:alert(1)', 'Clip', 'video', 'text/html'), 'Clip.mp4');
    });

    check('a still frame is asked for without touching the signed query', () => {
        assert.equal(posterFrameUrl(`${MEDIA}/a.mp4?sig=1`), `${MEDIA}/a.mp4?sig=1#t=0.1`);
        assert.equal(posterFrameUrl(`${MEDIA}/a.mp4#t=5`), `${MEDIA}/a.mp4#t=0.1`);
        assert.equal(posterFrameUrl(null), undefined);
    });

    let failures = 0;
    for (const [name, run] of checks) {
        try {
            run();
            console.log(`PASS ${name}`);
        } catch (error) {
            failures += 1;
            console.error(`FAIL ${name}\n${error.stack}`);
        }
    }
    if (failures) {
        process.exitCode = 1;
    }
} finally {
    if (hadWindow) {
        globalThis.window = previousWindow;
    } else {
        delete globalThis.window;
    }
}
