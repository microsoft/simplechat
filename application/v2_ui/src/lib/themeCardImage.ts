// themeCardImage.ts
// Draws a Theme Card PNG and reads one back.
//
// A Theme Card is a picture someone can drop into chat or email: the color mode's name, a
// stripe of its colors, and a QR code drawn in those colors. The QR code holds the Theme Card
// code (see colorScheme.ts), so a screenshot or a copy that Teams recompressed still imports.
// The same code is also written into the PNG itself as a tEXt chunk, which makes importing
// the original file exact and instant.
//
// Nothing here trusts the image. Reading returns only the text code, which then goes through
// decodeThemeCardCode and, when saved, the server's own validation. The image is never
// uploaded.

import qrcode from 'qrcode-generator';
import jsQR from 'jsqr';
import { suggestReadableColor, contrastRatio, type CustomColorMode } from './colorScheme';

export const THEME_CARD_PNG_KEYWORD = 'simplechat-theme';
export const THEME_CARD_MAX_BYTES = 2 * 1024 * 1024;
export const THEME_CARD_ACCEPT = 'image/png,image/jpeg,image/webp';

const PNG_SIGNATURE = [137, 80, 78, 71, 13, 10, 26, 10];

/* -------------------------------------------------------------------------- */
/* PNG tEXt chunk                                                              */
/* -------------------------------------------------------------------------- */

let crcTable: Uint32Array | null = null;

function crc32(bytes: Uint8Array): number {
    if (!crcTable) {
        crcTable = new Uint32Array(256);
        for (let n = 0; n < 256; n += 1) {
            let c = n;
            for (let k = 0; k < 8; k += 1) {
                c = c & 1 ? 0xedb88320 ^ (c >>> 1) : c >>> 1;
            }
            crcTable[n] = c >>> 0;
        }
    }
    let crc = 0xffffffff;
    for (const byte of bytes) {
        crc = crcTable[(crc ^ byte) & 0xff] ^ (crc >>> 8);
    }
    return (crc ^ 0xffffffff) >>> 0;
}

function isPng(bytes: Uint8Array): boolean {
    return PNG_SIGNATURE.every((value, index) => bytes[index] === value);
}

/** Returns a copy of `png` with a tEXt chunk inserted after IHDR. */
export function addPngTextChunk(png: Uint8Array, keyword: string, text: string): Uint8Array {
    const encoder = new TextEncoder();
    const data = new Uint8Array([...encoder.encode(keyword), 0, ...encoder.encode(text)]);
    const type = encoder.encode('tEXt');
    const chunk = new Uint8Array(12 + data.length);
    const view = new DataView(chunk.buffer);
    view.setUint32(0, data.length);
    chunk.set(type, 4);
    chunk.set(data, 8);
    view.setUint32(8 + data.length, crc32(new Uint8Array([...type, ...data])));
    // IHDR is always the first chunk: 8-byte signature + 4 length + 4 type + 13 data + 4 CRC.
    const insertAt = 8 + 25;
    const out = new Uint8Array(png.length + chunk.length);
    out.set(png.subarray(0, insertAt), 0);
    out.set(chunk, insertAt);
    out.set(png.subarray(insertAt), insertAt + chunk.length);
    return out;
}

/** Returns the text of the first tEXt chunk with `keyword`, or null. */
export function readPngTextChunk(bytes: Uint8Array, keyword: string): string | null {
    if (!isPng(bytes)) {
        return null;
    }
    const view = new DataView(bytes.buffer, bytes.byteOffset, bytes.byteLength);
    const decoder = new TextDecoder('latin1');
    let offset = 8;
    while (offset + 12 <= bytes.length) {
        const length = view.getUint32(offset);
        const type = decoder.decode(bytes.subarray(offset + 4, offset + 8));
        const dataStart = offset + 8;
        if (dataStart + length > bytes.length) {
            return null;
        }
        if (type === 'tEXt') {
            const data = bytes.subarray(dataStart, dataStart + length);
            const separator = data.indexOf(0);
            if (separator > 0 && decoder.decode(data.subarray(0, separator)) === keyword) {
                return decoder.decode(data.subarray(separator + 1));
            }
        }
        if (type === 'IEND') {
            return null;
        }
        offset = dataStart + length + 4;
    }
    return null;
}

/* -------------------------------------------------------------------------- */
/* Drawing                                                                     */
/* -------------------------------------------------------------------------- */

const CARD_WIDTH = 680;
const SCALE = 2;

function fontFamily(): string {
    try {
        return getComputedStyle(document.body).fontFamily || 'system-ui, sans-serif';
    } catch {
        return 'system-ui, sans-serif';
    }
}

function roundedRect(ctx: CanvasRenderingContext2D, x: number, y: number, w: number, h: number, r: number) {
    ctx.beginPath();
    ctx.roundRect(x, y, w, h, r);
}

/** Module colors for the QR code: the palette, darkened until each reads on white. */
function qrColors(mode: CustomColorMode): { modules: string[]; finder: string } {
    const { colors } = mode;
    const modules = [colors.accent, colors.info, colors.danger, colors.warn, colors.ok].map((color) =>
        contrastRatio(color, '#FFFFFF') >= 4.5 ? color : suggestReadableColor(color, '#FFFFFF'),
    );
    const finderSource = mode.base === 'dark' ? colors.backdrop : colors.text1;
    const finder = contrastRatio(finderSource, '#FFFFFF') >= 7 ? finderSource : '#111111';
    return { modules, finder };
}

function drawQr(ctx: CanvasRenderingContext2D, code: string, mode: CustomColorMode, x: number, y: number, size: number) {
    const qr = qrcode(0, 'M');
    qr.addData(code, 'Byte');
    qr.make();
    const count = qr.getModuleCount();
    const quiet = 3;
    const cell = size / (count + quiet * 2);
    const { modules, finder } = qrColors(mode);
    ctx.fillStyle = '#FFFFFF';
    roundedRect(ctx, x, y, size, size, 14);
    ctx.fill();
    const inFinder = (row: number, col: number) =>
        (row < 7 && col < 7) || (row < 7 && col >= count - 7) || (row >= count - 7 && col < 7);
    for (let row = 0; row < count; row += 1) {
        for (let col = 0; col < count; col += 1) {
            if (!qr.isDark(row, col)) {
                continue;
            }
            const band = Math.min(modules.length - 1, Math.floor(((row + col) / (count * 2)) * modules.length));
            ctx.fillStyle = inFinder(row, col) ? finder : modules[band];
            // Whole-pixel cells with no gaps keep the code easy for a scanner to read.
            const px = Math.floor(x + (col + quiet) * cell);
            const py = Math.floor(y + (row + quiet) * cell);
            ctx.fillRect(px, py, Math.ceil(cell), Math.ceil(cell));
        }
    }
}

function fitText(ctx: CanvasRenderingContext2D, text: string, maxWidth: number): string {
    if (ctx.measureText(text).width <= maxWidth) {
        return text;
    }
    let trimmed = text;
    while (trimmed.length > 1 && ctx.measureText(`${trimmed}…`).width > maxWidth) {
        trimmed = trimmed.slice(0, -1);
    }
    return `${trimmed}…`;
}

/** Draws the card and returns it as a PNG with the code embedded. */
export async function renderThemeCardPng(mode: CustomColorMode, code: string): Promise<Blob> {
    const { colors } = mode;
    const family = fontFamily();
    const header = 150;
    const stripe = 64;
    const footer = 300;
    const height = header + stripe + footer;
    const canvas = document.createElement('canvas');
    canvas.width = CARD_WIDTH * SCALE;
    canvas.height = height * SCALE;
    const ctx = canvas.getContext('2d');
    if (!ctx) {
        throw new Error('Canvas is not available.');
    }
    ctx.scale(SCALE, SCALE);

    // Card body, with rounded corners on a transparent background.
    ctx.save();
    roundedRect(ctx, 0, 0, CARD_WIDTH, height, 28);
    ctx.clip();
    ctx.fillStyle = colors.backdrop;
    ctx.fillRect(0, 0, CARD_WIDTH, header);

    ctx.fillStyle = colors.accent;
    ctx.font = `700 15px ${family}`;
    ctx.fillText('SIMPLECHAT COLOR MODE', 36, 52);
    ctx.fillStyle = colors.text1;
    ctx.font = `800 40px ${family}`;
    ctx.fillText(fitText(ctx, mode.name, CARD_WIDTH - 72), 36, 100);
    ctx.fillStyle = colors.text2;
    ctx.font = `500 17px ${family}`;
    ctx.fillText(mode.base === 'dark' ? 'Dark color mode' : 'Light color mode', 36, 130);

    const stripeColors = [colors.accent, colors.backdrop, colors.panel, colors.border, colors.text1, colors.text2, colors.ok, colors.warn, colors.danger, colors.info];
    const segment = CARD_WIDTH / stripeColors.length;
    stripeColors.forEach((color, index) => {
        ctx.fillStyle = color;
        ctx.fillRect(Math.floor(index * segment), header, Math.ceil(segment) + 1, stripe);
    });

    ctx.fillStyle = colors.panel;
    ctx.fillRect(0, header + stripe, CARD_WIDTH, footer);
    const qrSize = 240;
    drawQr(ctx, code, mode, 30, header + stripe + 30, qrSize);

    const textX = 30 + qrSize + 32;
    ctx.fillStyle = colors.text1;
    ctx.font = `700 22px ${family}`;
    ctx.fillText('Make it yours', textX, header + stripe + 82);
    ctx.fillStyle = colors.text2;
    ctx.font = `500 16px ${family}`;
    ['Open SimpleChat, go to', 'Settings › Preferences › Color mode,', 'and choose Import Theme Card.'].forEach((line, index) => {
        ctx.fillText(line, textX, header + stripe + 116 + index * 24);
    });
    [colors.accent, colors.text1, colors.text2, colors.border, colors.ok].forEach((color, index) => {
        ctx.fillStyle = color;
        ctx.beginPath();
        ctx.arc(textX + 14 + index * 34, header + stripe + 222, 12, 0, Math.PI * 2);
        ctx.fill();
    });
    ctx.restore();

    const blob = await new Promise<Blob | null>((resolve) => canvas.toBlob(resolve, 'image/png'));
    if (!blob) {
        throw new Error('The card image could not be created.');
    }
    const withCode = addPngTextChunk(new Uint8Array(await blob.arrayBuffer()), THEME_CARD_PNG_KEYWORD, code);
    return new Blob([withCode], { type: 'image/png' });
}

export function themeCardFileName(name: string): string {
    const slug = name.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'color-mode';
    return `${slug}.simplechat-theme.png`;
}

/* -------------------------------------------------------------------------- */
/* Reading                                                                     */
/* -------------------------------------------------------------------------- */

export type ThemeCardFileError = 'unsupported-type' | 'too-large' | 'unreadable' | 'no-code';

export const THEME_CARD_FILE_ERROR_MESSAGES: Record<ThemeCardFileError, string> = {
    'unsupported-type': 'Choose a PNG, JPG or WebP image.',
    'too-large': 'That image is larger than 2 MB.',
    unreadable: "That image couldn't be opened.",
    'no-code': "No Theme Card code was found in that image. Try the original PNG, or a sharper screenshot of the card.",
};

async function decodeQr(file: Blob): Promise<string | null> {
    let bitmap: ImageBitmap;
    try {
        bitmap = await createImageBitmap(file);
    } catch {
        return null;
    }
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d', { willReadFrequently: true });
    if (!ctx) {
        return null;
    }
    // Large screenshots decode faster and often better when scaled down; small ones up.
    const longest = Math.max(bitmap.width, bitmap.height);
    const scales = longest > 1600 ? [1600 / longest, 1] : longest < 500 ? [2, 1] : [1, 0.5];
    for (const scale of scales) {
        canvas.width = Math.max(1, Math.round(bitmap.width * scale));
        canvas.height = Math.max(1, Math.round(bitmap.height * scale));
        ctx.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
        const image = ctx.getImageData(0, 0, canvas.width, canvas.height);
        const result = jsQR(image.data, image.width, image.height, { inversionAttempts: 'attemptBoth' });
        if (result?.data) {
            bitmap.close();
            return result.data;
        }
    }
    bitmap.close();
    return null;
}

/** Reads the Theme Card code out of an image file: the PNG chunk first, then the QR code. */
export async function readThemeCardCodeFromFile(file: File): Promise<{ ok: true; code: string } | { ok: false; error: ThemeCardFileError }> {
    if (!THEME_CARD_ACCEPT.split(',').includes(file.type)) {
        return { ok: false, error: 'unsupported-type' };
    }
    if (file.size > THEME_CARD_MAX_BYTES) {
        return { ok: false, error: 'too-large' };
    }
    let bytes: Uint8Array;
    try {
        bytes = new Uint8Array(await file.arrayBuffer());
    } catch {
        return { ok: false, error: 'unreadable' };
    }
    const embedded = readPngTextChunk(bytes, THEME_CARD_PNG_KEYWORD);
    if (embedded) {
        return { ok: true, code: embedded };
    }
    const scanned = await decodeQr(file);
    return scanned ? { ok: true, code: scanned } : { ok: false, error: 'no-code' };
}
