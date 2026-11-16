// BrandingImageField.tsx
// Upload control for a logo or favicon.
//
// Branding images cannot ride along with the JSON settings PATCH, so this control saves
// immediately through the multipart branding endpoint rather than joining the page's
// buffered draft. That is a deliberate exception to the save-bar model: a file input has no
// meaningful "unsaved" state to show, and the server has to convert the image before
// anything can be previewed.

import { useRef, useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Check, ImageOff, Loader2, Upload } from 'lucide-react';
import { ApiError, uploadFile } from '../../lib/apiClient';
import type { AdminField, BrandingAsset, BrandingUploadResponse } from '../../lib/adminFields';
import { GlassButton } from '../ui/primitives';

export function BrandingImageField({
    field,
    asset,
    scalePercent,
    onUploaded,
}: {
    field: AdminField;
    asset?: BrandingAsset;
    /** Applied to the preview so the logo size control can be judged against the real image. */
    scalePercent?: number;
    onUploaded: (target: string, result: BrandingUploadResponse) => void;
}) {
    const inputRef = useRef<HTMLInputElement>(null);
    const [uploading, setUploading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [savedAt, setSavedAt] = useState<number | null>(null);

    const target = field.upload_target;
    const isFavicon = target === 'favicon';

    const handleFile = async (file: File) => {
        if (!target) {
            return;
        }
        setUploading(true);
        setError(null);
        setSavedAt(null);

        const formData = new FormData();
        formData.append('target', target);
        formData.append('file', file);

        try {
            const result = await uploadFile<BrandingUploadResponse>(
                '/api/v2/admin/settings/branding-image',
                formData,
            );
            onUploaded(target, result);
            setSavedAt(Date.now());
        } catch (uploadError) {
            setError(
                uploadError instanceof ApiError || uploadError instanceof Error
                    ? uploadError.message
                    : 'The upload failed.',
            );
        } finally {
            setUploading(false);
            // Clearing the input lets the same file be chosen again after a failure.
            if (inputRef.current) {
                inputRef.current.value = '';
            }
        }
    };

    return (
        <div className="py-3">
            <div className="mb-1.5 flex items-baseline justify-between gap-3">
                <span className="text-sm font-medium text-text-1">{field.label}</span>
                {asset?.present ? (
                    <span className="text-xs text-text-3">version {asset.version}</span>
                ) : null}
            </div>

            <div className="flex items-start gap-3">
                <div
                    className={clsx(
                        'flex shrink-0 items-center justify-center overflow-hidden rounded-lg',
                        'border border-edge bg-surface-sunken',
                        isFavicon ? 'h-16 w-16' : 'h-16 w-28',
                    )}
                >
                    {asset?.url ? (
                        <img
                            src={asset.url}
                            alt={`${field.label} preview`}
                            className="max-h-full max-w-full object-contain"
                            style={
                                scalePercent && !isFavicon
                                    ? { transform: `scale(${Math.min(scalePercent, 100) / 100})` }
                                    : undefined
                            }
                        />
                    ) : (
                        <ImageOff size={18} className="text-text-3" aria-hidden="true" />
                    )}
                </div>

                <div className="min-w-0 flex-1">
                    <input
                        ref={inputRef}
                        type="file"
                        accept={field.accept}
                        className="sr-only"
                        aria-label={`Upload ${field.label}`}
                        onChange={(event) => {
                            const file = event.target.files?.[0];
                            if (file) {
                                void handleFile(file);
                            }
                        }}
                    />
                    <div className="flex items-center gap-2">
                        <GlassButton
                            type="button"
                            variant="subtle"
                            size="sm"
                            disabled={uploading}
                            onClick={() => inputRef.current?.click()}
                        >
                            {uploading ? (
                                <Loader2 size={14} className="animate-spin" />
                            ) : (
                                <Upload size={14} />
                            )}
                            {asset?.present ? 'Replace' : 'Upload'}
                        </GlassButton>

                        {savedAt ? (
                            <span className="flex items-center gap-1 text-xs text-ok">
                                <Check size={13} />
                                Saved
                            </span>
                        ) : null}
                    </div>

                    {field.help ? (
                        <p className="mt-1.5 text-xs leading-relaxed text-text-3">{field.help}</p>
                    ) : null}

                    {error ? (
                        <p
                            role="alert"
                            className="mt-1.5 flex items-start gap-1.5 text-xs text-danger"
                        >
                            <AlertCircle size={13} className="mt-0.5 shrink-0" />
                            {error}
                        </p>
                    ) : null}
                </div>
            </div>
        </div>
    );
}
