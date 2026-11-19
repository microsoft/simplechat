// ThemeCardDialogs.tsx
// Share a color mode as a Theme Card image, and import one someone else shared.
//
// Sharing draws the card in the browser (themeCardImage.ts) and offers it as a download, or
// the plain text code for pasting. Importing reads only the code out of the image (the PNG's
// own text chunk, or else its QR code), checks it, and shows what it would apply before
// anything changes. The image itself never leaves the browser; the caller saves the eleven
// validated colors through the normal settings API, where the server checks them again.

import { useCallback, useEffect, useRef, useState, type ChangeEvent, type DragEvent } from 'react';
import { clsx } from 'clsx';
import { CheckCircle2, Copy, Download, ImageUp, ShieldCheck, ShieldX } from 'lucide-react';
import { Modal } from '../ui/Modal';
import { GlassButton } from '../ui/primitives';
import { toast } from '../../stores/toastStore';
import {
    THEME_CARD_ERROR_MESSAGES,
    decodeThemeCardCode,
    encodeThemeCardCode,
    readabilityProblems,
    type CustomColorMode,
} from '../../lib/colorScheme';
import {
    THEME_CARD_ACCEPT,
    THEME_CARD_FILE_ERROR_MESSAGES,
    readThemeCardCodeFromFile,
    renderThemeCardPng,
    themeCardFileName,
} from '../../lib/themeCardImage';
import { ColorPreview } from './ColorControls';

export function ShareThemeCardDialog({ mode, onClose }: { mode: CustomColorMode; onClose: () => void }) {
    const [code, setCode] = useState<string | null>(null);
    const [imageUrl, setImageUrl] = useState<string | null>(null);
    const [failed, setFailed] = useState(false);

    useEffect(() => {
        let url: string | null = null;
        let cancelled = false;
        (async () => {
            try {
                const nextCode = await encodeThemeCardCode(mode);
                const blob = await renderThemeCardPng(mode, nextCode);
                if (cancelled) {
                    return;
                }
                url = URL.createObjectURL(blob);
                setCode(nextCode);
                setImageUrl(url);
            } catch {
                if (!cancelled) {
                    setFailed(true);
                }
            }
        })();
        return () => {
            cancelled = true;
            if (url) {
                URL.revokeObjectURL(url);
            }
        };
    }, [mode]);

    const copyCode = async () => {
        if (!code) {
            return;
        }
        try {
            await navigator.clipboard.writeText(code);
            toast.success('Theme Card code copied.');
        } catch {
            toast.error("Couldn't copy to the clipboard.");
        }
    };

    return (
        <Modal
            title="Share your color mode"
            description="Download a Theme Card image. Anyone can drop it into SimpleChat to get the same colors."
            onClose={onClose}
            size="xl"
            footer={
                <div className="flex w-full flex-wrap items-center justify-between gap-2">
                    <GlassButton variant="subtle" size="sm" onClick={copyCode} disabled={!code}>
                        <Copy size={14} aria-hidden="true" /> Copy as text code
                    </GlassButton>
                    <div className="flex gap-2">
                        <GlassButton variant="ghost" onClick={onClose}>Close</GlassButton>
                        {imageUrl ? (
                            <a
                                href={imageUrl}
                                download={themeCardFileName(mode.name)}
                                className="inline-flex h-10 items-center gap-2 rounded-xl bg-accent px-4 text-sm font-medium text-on-accent shadow-sm hover:bg-accent-hover"
                            >
                                <Download size={16} aria-hidden="true" /> Download Theme Card
                            </a>
                        ) : null}
                    </div>
                </div>
            }
        >
            <div className="flex flex-wrap items-start gap-6">
                <div className="w-[340px] max-w-full shrink-0">
                    {imageUrl ? (
                        <img src={imageUrl} alt={`Theme Card for ${mode.name}`} className="w-full rounded-[18px] shadow-[0_18px_40px_rgb(15_23_42/0.28)]" />
                    ) : (
                        <div className="flex aspect-[680/514] w-full items-center justify-center rounded-[18px] border border-edge-strong bg-surface-2 text-sm text-text-3">
                            {failed ? "The card couldn't be drawn in this browser." : 'Drawing your card…'}
                        </div>
                    )}
                </div>
                <div className="min-w-[16rem] flex-1 space-y-3 text-sm text-text-2">
                    <p className="font-semibold text-text-1">What's in the card</p>
                    <ul className="space-y-2">
                        <li className="flex gap-2"><CheckCircle2 size={16} className="mt-0.5 shrink-0 text-ok" aria-hidden="true" />The QR code holds your 11 colors and a checksum, so a screenshot or a resend in Teams still imports.</li>
                        <li className="flex gap-2"><CheckCircle2 size={16} className="mt-0.5 shrink-0 text-ok" aria-hidden="true" />The same code is stored inside the PNG, so the original image imports exactly.</li>
                        <li className="flex gap-2"><ShieldCheck size={16} className="mt-0.5 shrink-0 text-accent" aria-hidden="true" />If anyone edits the code, the card is rejected on import. Only plain colors are ever applied.</li>
                    </ul>
                </div>
            </div>
        </Modal>
    );
}

type ImportState =
    | { status: 'idle' }
    | { status: 'reading' }
    | { status: 'ready'; mode: CustomColorMode; source: string }
    | { status: 'error'; message: string; source: string };

export function ImportThemeCardDialog({
    onClose,
    onImport,
    importLabel,
    description,
    requireReadable,
}: {
    onClose: () => void;
    onImport: (mode: CustomColorMode) => void | Promise<void>;
    importLabel: string;
    description?: string;
    /** When set, a card whose text would be hard to read is refused, as the server would. */
    requireReadable?: boolean;
}) {
    const [state, setState] = useState<ImportState>({ status: 'idle' });
    const [pasted, setPasted] = useState('');
    const [dragging, setDragging] = useState(false);
    const [importing, setImporting] = useState(false);
    const inputRef = useRef<HTMLInputElement>(null);

    const checkCode = useCallback(
        async (code: string, source: string) => {
            const result = await decodeThemeCardCode(code);
            if (!result.ok) {
                setState({ status: 'error', message: THEME_CARD_ERROR_MESSAGES[result.error], source });
                return;
            }
            if (requireReadable && readabilityProblems(result.mode.colors).length) {
                setState({
                    status: 'error',
                    message: 'This card’s text would be hard to read, and your administrator requires readable colors.',
                    source,
                });
                return;
            }
            setState({ status: 'ready', mode: result.mode, source });
        },
        [requireReadable],
    );

    const readFile = useCallback(
        async (file: File) => {
            setState({ status: 'reading' });
            const result = await readThemeCardCodeFromFile(file);
            if (!result.ok) {
                setState({ status: 'error', message: THEME_CARD_FILE_ERROR_MESSAGES[result.error], source: file.name });
                return;
            }
            await checkCode(result.code, file.name);
        },
        [checkCode],
    );

    useEffect(() => {
        const onPaste = (event: ClipboardEvent) => {
            const file = Array.from(event.clipboardData?.files ?? []).find((item) => item.type.startsWith('image/'));
            if (file) {
                event.preventDefault();
                void readFile(file);
            }
        };
        window.addEventListener('paste', onPaste);
        return () => window.removeEventListener('paste', onPaste);
    }, [readFile]);

    const onDrop = (event: DragEvent<HTMLDivElement>) => {
        event.preventDefault();
        setDragging(false);
        const file = event.dataTransfer.files?.[0];
        if (file) {
            void readFile(file);
        }
    };

    const onChoose = (event: ChangeEvent<HTMLInputElement>) => {
        const file = event.target.files?.[0];
        event.target.value = '';
        if (file) {
            void readFile(file);
        }
    };

    const confirm = async () => {
        if (state.status !== 'ready') {
            return;
        }
        setImporting(true);
        try {
            await onImport(state.mode);
        } finally {
            setImporting(false);
        }
    };

    return (
        <Modal
            title="Import a Theme Card"
            description={description ?? "Drop a Theme Card image someone shared with you. It's checked before anything changes."}
            onClose={onClose}
            size="xl"
            footer={
                <div className="flex w-full justify-end gap-2">
                    <GlassButton variant="ghost" onClick={onClose}>Cancel</GlassButton>
                    <GlassButton variant="primary" onClick={confirm} disabled={state.status !== 'ready' || importing}>
                        {importLabel}
                    </GlassButton>
                </div>
            }
        >
            <div className="space-y-4">
                <div
                    onDragOver={(event) => {
                        event.preventDefault();
                        setDragging(true);
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={onDrop}
                    className={clsx(
                        'flex flex-col items-center justify-center gap-1 rounded-2xl border-2 border-dashed px-4 py-5 text-center transition-colors',
                        dragging ? 'border-accent bg-accent-soft' : 'border-accent/40 bg-accent-soft/40',
                    )}
                >
                    <ImageUp size={22} className="text-accent" aria-hidden="true" />
                    <p className="text-sm font-semibold text-accent">
                        Drop a Theme Card here, paste it, or{' '}
                        <button type="button" className="underline" onClick={() => inputRef.current?.click()}>
                            browse
                        </button>
                    </p>
                    <p className="text-xs text-text-3">PNG, JPG or WebP up to 2 MB. Only the color code inside the image is used.</p>
                    <input ref={inputRef} type="file" accept={THEME_CARD_ACCEPT} className="sr-only" onChange={onChoose} aria-label="Choose a Theme Card image" />
                </div>

                <div className="flex flex-wrap items-center gap-2">
                    <input
                        value={pasted}
                        onChange={(event) => setPasted(event.target.value)}
                        placeholder="Or paste a text code (SCTHEME1…)"
                        aria-label="Theme Card text code"
                        spellCheck={false}
                        className="h-9 min-w-0 flex-1 rounded-lg border border-edge-strong bg-surface-solid px-3 font-mono text-xs text-text-1"
                    />
                    <GlassButton variant="subtle" size="sm" disabled={!pasted.trim()} onClick={() => void checkCode(pasted, 'Pasted code')}>
                        Check code
                    </GlassButton>
                </div>

                {state.status === 'reading' ? <p className="text-sm text-text-3">Reading the card…</p> : null}

                {state.status === 'ready' ? (
                    <div className="flex flex-wrap items-start gap-5 rounded-2xl border border-ok/30 bg-ok-soft/50 p-4">
                        <div className="min-w-[14rem] flex-1">
                            <div className="flex flex-wrap items-center gap-2">
                                <p className="text-lg font-semibold text-text-1">{state.mode.name}</p>
                                <span className="inline-flex items-center gap-1 rounded-full border border-ok/30 bg-ok-soft px-2 py-0.5 text-xs font-medium text-ok">
                                    <ShieldCheck size={12} aria-hidden="true" /> Verified
                                </span>
                            </div>
                            <p className="text-xs text-text-3">
                                {state.mode.base === 'dark' ? 'Dark' : 'Light'} · {state.source}
                            </p>
                            <ul className="mt-3 space-y-1.5 text-sm text-text-2">
                                {['Theme Card code found', 'Checksum matches · not edited', '11 of 11 colors valid'].map((line) => (
                                    <li key={line} className="flex items-center gap-2">
                                        <CheckCircle2 size={15} className="shrink-0 text-ok" aria-hidden="true" />
                                        {line}
                                    </li>
                                ))}
                            </ul>
                        </div>
                        <div className="w-80 max-w-full shrink-0">
                            <ColorPreview palette={state.mode.colors} height={190} compact />
                        </div>
                    </div>
                ) : null}

                {state.status === 'error' ? (
                    <div role="alert" className="flex items-center gap-3 rounded-2xl border border-danger/30 bg-danger-soft/50 px-4 py-3">
                        <ShieldX size={20} className="shrink-0 text-danger" aria-hidden="true" />
                        <div className="min-w-0 flex-1">
                            <p className="text-sm font-semibold text-text-1">{state.source} wasn't imported</p>
                            <p className="text-xs text-text-3">{state.message}</p>
                        </div>
                    </div>
                ) : null}
            </div>
        </Modal>
    );
}
