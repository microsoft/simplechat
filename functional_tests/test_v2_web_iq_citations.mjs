// test_v2_web_iq_citations.mjs
// Version: 0.261.405
// Implemented in: 0.261.405
// Real V2 source policy: selected persisted citations, safe URLs, no text-only previews.

import assert from 'node:assert/strict';
import './test_support/tsResolve.mjs';
// Registration must finish before the real modules resolve extensionless TS imports.
const { citedWebMedia, safeWebSourceUrl, safeWebPreviewUrl, webSourcePreview, webSourceProviderLabel, rehypeWebCitationMedia } = await import('../application/v2_ui/src/lib/webCitations.ts');
const { galleryMediaKind } = await import('../application/v2_ui/src/lib/mediaGallery.ts');
const { completionCitations, readSources } = await import('../application/v2_ui/src/lib/messageDetails.ts');

const image = {
    provider: 'web_iq', source_kind: 'image', delivery_mode: 'with_media',
    url: 'https://example.test/source', image_url: 'https://example.test/image.png',
};
const video = {
    ...image, source_kind: 'video', url: 'https://example.test/video',
    video_url: 'https://video.test/watch?v=1', thumbnail_url: 'https://example.test/thumb.jpg',
};
assert.equal(webSourcePreview(image), image.image_url);
assert.equal(webSourcePreview(video), video.thumbnail_url);
assert.equal(webSourcePreview({ ...image, delivery_mode: 'text_only' }), '');
assert.equal(webSourcePreview({ ...video, thumbnail_url: undefined }), '');
for (const url of [
    'http://public.example.com/image.png', 'https://localhost/image.png',
    'https://sub.localhost/image.png', 'https://host.local/image.png',
    'https://localhost./image.png', 'https://host.local./image.png',
    'https://127.0.0.1/image.png', 'https://10.0.0.1/image.png',
    'https://192.168.1.2/image.png', 'https://169.254.169.254/image.png',
    'https://8.8.8.8/image.png', 'https://[::1]/image.png',
    'https://[2001:4860:4860::8888]/image.png', 'https://2130706433/image.png',
]) assert.equal(safeWebPreviewUrl(url), '');
assert.equal(safeWebPreviewUrl('https://images.example.com/photo.png'), 'https://images.example.com/photo.png');
assert.equal(webSourceProviderLabel(image), 'Web IQ');
assert.equal(webSourceProviderLabel({ provider: 'source_review' }), '');
assert.equal(webSourceProviderLabel({ provider: 'web_iq', source_type: 'source_review' }), '');
assert.equal(webSourceProviderLabel({ provider: 'foundry' }), '');
for (const url of ['javascript:alert(1)', 'data:text/html,x', '//evil.test', 'https://user:password@evil.test', 'https://evil.test\\path', 'https://evil.test/\n']) {
    assert.equal(safeWebSourceUrl(url), '');
}
assert.deepEqual(citedWebMedia([
    image, image, video,
    { ...image, cited: false },
    { ...image, provider: 'source_review' },
    { ...image, url: 'javascript:evil()' },
    { ...image, source_kind: 'news' },
]), [image, video]);
assert.deepEqual(citedWebMedia(undefined), []);
assert.deepEqual(citedWebMedia([{ ...image, delivery_mode: 'text_only' }]), []);
const raw = [image, video, { ...image, url: 'https://uncited.test/image' }];
const selected = [image];
assert.deepEqual(completionCitations({ web_search_citations: raw, cited_web_search_citations: selected }).cited_web_search_citations, selected);
assert.deepEqual(completionCitations({ web_search_citations: raw, cited_web_search_citations: selected }).web_search_citations, raw);
assert.deepEqual(readSources({ web_search_citations: raw, cited_web_search_citations: selected }).web, selected);
assert.deepEqual(readSources({ web_search_citations: raw }).web, []);
const historical = {
    ...image, delivery_mode: 'text_only', url: 'https://example.test/imported.jpg',
    video_url: 'https://example.test/imported.mp4',
};
const tree = { type: 'root', children: [
    { type: 'element', tagName: 'img', properties: { src: historical.url, alt: 'Text only' }, children: [] },
    { type: 'element', tagName: 'a', properties: { href: historical.video_url }, children: [{ type: 'text', value: 'Clip' }] },
    { type: 'element', tagName: 'img', properties: { src: 'https://unrelated.test/image.png' }, children: [] },
] };
rehypeWebCitationMedia({ citations: [historical] })(tree);
assert.equal(tree.children[0].tagName, 'a');
assert.equal(tree.children[0].properties.href, historical.url);
assert.equal(tree.children[1].properties.href, historical.url);
assert.equal(galleryMediaKind(tree.children[0]), null);
assert.equal(galleryMediaKind(tree.children[1]), null);
assert.equal(tree.children[2].tagName, 'img');
console.log('Web IQ citation policy checks passed.');
