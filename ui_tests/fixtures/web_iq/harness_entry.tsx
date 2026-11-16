// harness_entry.tsx
// Version: 0.261.405
// Implemented in: 0.261.405

import React from 'react';
import { createRoot } from 'react-dom/client';
import { CitationChip } from '../../../application/v2_ui/src/components/chat/CitationChip';
import { AssistantMarkdown } from '../../../application/v2_ui/src/components/chat/AssistantMarkdown';
import { WebCitationCards, WebCitationLinks, WebCitationProvider } from '../../../application/v2_ui/src/components/chat/WebCitationCards';
import type { WebCitation } from '../../../application/v2_ui/src/lib/types';

const media = 'https://media.example.com/preview.png';
const sources: WebCitation[] = [
    {
        provider: 'web_iq', source_kind: 'image', delivery_mode: 'with_media',
        url: 'https://source.test/image', title: 'Cited landscape <script>bad()</script>',
        image_url: media, description: 'A cited image description.',
    },
    {
        provider: 'web_iq', source_kind: 'video', delivery_mode: 'with_media',
        url: 'https://source.test/video', title: 'Cited hosted video',
        video_url: 'https://video.test/watch?v=1', thumbnail_url: media,
        publisher: 'Example Publisher', duration: '2:30',
        moments: [
            { title: 'Opening moment', url: 'https://source.test/video?t=10', start_time: '0:10' },
            { title: 'Unsafe moment', url: 'javascript:bad()' },
            ...Array.from({ length: 7 }, (_, index) => ({
                title: `Moment ${index + 2}`, url: `https://source.test/video?t=${index + 20}`,
            })),
        ],
    },
    {
        provider: 'web_iq', source_kind: 'image', delivery_mode: 'text_only',
        url: 'https://source.test/text.jpg', title: 'Text-only source',
        video_url: 'https://source.test/text.mp4',
        image_url: media, description: 'Text-only description.',
    },
    {
        provider: 'web_iq', source_kind: 'image', delivery_mode: 'with_media',
        url: 'https://source.test/not-cited', title: 'Retrieved but not cited',
        image_url: media,
    },
];
const citedSources = sources.slice(0, 3);

createRoot(document.getElementById('root')!).render(
    <div className="mx-auto max-w-2xl p-4">
        <WebCitationProvider citations={sources}>
            <p>A cited answer <CitationChip group={{
                id: 'web', kind: 'web', fileName: sources[0].url!,
                locationLabel: 'Location', citations: [],
            }} /></p>
            <AssistantMarkdown content={
                '![Text-only markdown image](https://source.test/text.jpg)\n\n'
                + '[Text-only markdown clip](https://source.test/text.mp4)\n\n'
                + '![Historical duplicate](https://source.test/text.jpg)'
            } />
            <WebCitationCards citations={citedSources} />
            <WebCitationLinks citations={citedSources} />
        </WebCitationProvider>
    </div>,
);
