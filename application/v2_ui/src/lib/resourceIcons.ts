// resourceIcons.ts

import { api } from './apiClient';

export interface ResourceIcon {
    kind: 'bootstrap' | 'image';
    value: string;
    mime_type?: string;
}

export function isResourceIconImage(value: unknown): value is string {
    return typeof value === 'string' && value.length <= 350000
        && /^data:image\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(value);
}

export async function loadResourceIconNames(): Promise<string[]> {
    const css = await api.get<string>('/static/css/bootstrap-icons.css');
    const names = [...new Set([...css.matchAll(/\.bi-([a-z0-9][a-z0-9-]*)::before/g)]
        .map((match) => `bi-${match[1]}`))].sort();
    if (!names.length) throw new Error('The local icon catalogue could not be read.');
    return names;
}

export async function resizeResourceIcon(file: File): Promise<string> {
    if (!['image/png', 'image/jpeg'].includes(file.type)) throw new Error('Choose a PNG or JPEG image.');
    const url = URL.createObjectURL(file);
    try {
        const image = new Image();
        image.src = url;
        await image.decode();
        const scale = Math.min(1, 128 / Math.max(image.width, image.height));
        const canvas = document.createElement('canvas');
        canvas.width = Math.max(1, Math.round(image.width * scale));
        canvas.height = Math.max(1, Math.round(image.height * scale));
        const context = canvas.getContext('2d');
        if (!context) throw new Error('This browser cannot resize the icon.');
        context.drawImage(image, 0, 0, canvas.width, canvas.height);
        const data = canvas.toDataURL('image/png');
        if (!isResourceIconImage(data)) throw new Error('The resized icon exceeds the 350000-character limit.');
        return data;
    } finally {
        URL.revokeObjectURL(url);
    }
}
