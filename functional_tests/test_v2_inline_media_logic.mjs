// test_v2_inline_media_logic.mjs
// Version: 0.261.222
// Implemented in: 0.261.222
// Executes the real V2 inline media helpers: which links play in place, which URLs a player or
// link may use, how titles and times read, and that only one recording plays at a time.

import assert from 'node:assert/strict';

// The helpers resolve relative links against the page, as they do in the browser.
globalThis.window = { location: { href: 'https://chat.example.test/chat?conversationId=abc' } };

const {
    claimPlayback, formatMediaTime, inlineMediaKind, inlineMediaTitle, PLAYBACK_RATES, safeMarkdownHref, safeMediaUrl,
} = await import('../application/v2_ui/src/lib/inlineMedia.ts');

const checks = [];
const check = (name, run) => checks.push([name, run]);

check('audio and video are recognised by the extension of the URL path only', () => {
    assert.equal(inlineMediaKind('https://media.example.test/media/rec-7713042.wav?exp=1&sig=abc'), 'audio');
    assert.equal(inlineMediaKind('https://media.example.test/a/B.MP3'), 'audio');
    assert.equal(inlineMediaKind('https://media.example.test/a/call.m4a'), 'audio');
    assert.equal(inlineMediaKind('https://media.example.test/media/clip.mp4?sig=1'), 'video');
    assert.equal(inlineMediaKind('/media/clip.webm'), 'video');
    assert.equal(inlineMediaKind('https://media.example.test/view?file=clip.mp4'), null);
    assert.equal(inlineMediaKind('https://media.example.test/clip.mp4/details'), null);
    assert.equal(inlineMediaKind('https://media.example.test/report.pdf'), null);
    assert.equal(inlineMediaKind('https://media.example.test/'), null);
});

check('only http and https media can load, and relative paths become absolute', () => {
    assert.equal(safeMediaUrl('/media/a.wav'), 'https://chat.example.test/media/a.wav');
    assert.equal(safeMediaUrl('  https://media.example.test/a.wav  '), 'https://media.example.test/a.wav');
    assert.equal(safeMediaUrl('javascript:alert(1)//.mp3'), null);
    assert.equal(inlineMediaKind('javascript:alert(1)//.mp3'), null);
    assert.equal(safeMediaUrl('data:audio/wav;base64,AAAA'), null);
    assert.equal(safeMediaUrl('ftp://media.example.test/a.mp3'), null);
    assert.equal(safeMediaUrl(''), null);
    assert.equal(safeMediaUrl(undefined), null);
});

check('links keep only the schemes markdown allows by default', () => {
    assert.equal(safeMarkdownHref('https://example.test/a'), 'https://example.test/a');
    assert.equal(safeMarkdownHref('mailto:someone@example.test'), 'mailto:someone@example.test');
    assert.equal(safeMarkdownHref('/workspace/documents'), '/workspace/documents');
    assert.equal(safeMarkdownHref('#section'), '#section');
    assert.equal(safeMarkdownHref('relative/path:with-colon'), 'relative/path:with-colon');
    assert.equal(safeMarkdownHref('javascript:alert(1)'), undefined);
    assert.equal(safeMarkdownHref('JavaScript:alert(1)'), undefined);
    assert.equal(safeMarkdownHref('java\tscript:alert(1)'), undefined);
    assert.equal(safeMarkdownHref('vbscript:msgbox(1)'), undefined);
    assert.equal(safeMarkdownHref('data:text/html,<b>x</b>'), undefined);
    assert.equal(safeMarkdownHref(undefined), undefined);
});

check('titles drop the action wording and fall back to the file name', () => {
    const url = 'https://media.example.test/media/cra-audio-REC-7713042.wav';
    assert.equal(inlineMediaTitle('Open audio: Call audio REC-7713042', url), 'Call audio REC-7713042');
    assert.equal(inlineMediaTitle('Open video: Counter camera 2 clip', url), 'Counter camera 2 clip');
    assert.equal(inlineMediaTitle('Listen to the recording - follow-up interview', url), 'follow-up interview');
    assert.equal(inlineMediaTitle('Witness call', url), 'Witness call');
    assert.equal(inlineMediaTitle(url, url), 'cra-audio-REC-7713042.wav');
    assert.equal(inlineMediaTitle('', url), 'cra-audio-REC-7713042.wav');
});

check('times read as m:ss, or h:mm:ss past an hour', () => {
    assert.equal(formatMediaTime(0), '0:00');
    assert.equal(formatMediaTime(65.4), '1:05');
    assert.equal(formatMediaTime(3725), '1:02:05');
    assert.equal(formatMediaTime(Number.NaN), '0:00');
    assert.equal(formatMediaTime(-3), '0:00');
    assert.equal(PLAYBACK_RATES[0], 1);
});

check('starting one recording pauses the one already playing', () => {
    const element = () => ({ paused: false, pause() { this.paused = true; } });
    const first = element();
    const second = element();
    claimPlayback(first);
    claimPlayback(second);
    assert.equal(first.paused, true);
    assert.equal(second.paused, false);
    claimPlayback(second);
    assert.equal(second.paused, false);
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
    process.exit(1);
}
