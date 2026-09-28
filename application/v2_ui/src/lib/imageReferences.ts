// imageReferences.ts

/**
 * Reference images: existing images (uploads, workspace images, generated images) sent to the
 * image model as visual input, so a prompt like "make a cartoon of my house" can see the house.
 *
 * The request shape matches `parse_image_references` in `functions_image_references.py`.
 * The server authorizes and re-reads every reference; nothing here is trusted beyond naming
 * which image was meant.
 */

import { apiUrl } from './apiClient';
import { buildChatImagePreviewUrl, type ChatImagePreviewVariant } from './chatImagePreview';
import type { ImageEditCapability } from './types';

export const MAX_APP_REFERENCE_IMAGES = 10;

export type ImageReferenceScope = 'personal' | 'group' | 'public';

export interface MessageImageReference {
    type: 'message';
    message_id: string;
}

export interface DocumentImageReference {
    type: 'document';
    document_id: string;
    scope: ImageReferenceScope;
    scope_id: string | null;
}

export type ImageReferenceRequest = MessageImageReference | DocumentImageReference;

/** The sanitized provenance the server stores in `metadata.image_references`. */
export interface ImageReferenceProvenance {
    type: 'message' | 'document';
    message_id?: string;
    document_id?: string;
    scope?: ImageReferenceScope | null;
    scope_id?: string | null;
    file_name?: string;
    width?: number | null;
    height?: number | null;
}

// The reference-capable image formats that the chat upload route also accepts. HEIC/HEIF is
// left out because the server can't decode it into a model input.
const REFERENCE_IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'bmp', 'tif', 'tiff']);
const HEIF_EXTENSIONS = new Set(['heic', 'heif']);
const SCOPES = new Set<ImageReferenceScope>(['personal', 'group', 'public']);

export const HEIF_REFERENCE_HINT =
    'HEIC images can\'t be used as reference images yet. Convert the image to JPG or PNG and upload it again.';

function extensionOf(fileName: string): string {
    const value = String(fileName ?? '').trim().toLowerCase();
    const index = value.lastIndexOf('.');
    return index >= 0 ? value.slice(index + 1) : '';
}

export function isReferenceImageFileName(fileName: string): boolean {
    return REFERENCE_IMAGE_EXTENSIONS.has(extensionOf(fileName));
}

export function isHeifFileName(fileName: string): boolean {
    return HEIF_EXTENSIONS.has(extensionOf(fileName));
}

/** The number of references the selected image model accepts: 0 when it can't edit. */
export function effectiveReferenceImageLimit(capability: ImageEditCapability | null | undefined): number {
    if (!capability || !capability.enabled || !capability.editing) {
        return 0;
    }
    const limit = Math.trunc(Number(capability.max_reference_images) || 0);
    return Math.max(0, Math.min(MAX_APP_REFERENCE_IMAGES, limit));
}

export function imageReferenceKey(reference: ImageReferenceRequest): string {
    return reference.type === 'message'
        ? `message:${reference.message_id}`
        : `document:${reference.scope}:${reference.scope_id ?? ''}:${reference.document_id}`;
}

function cleanId(value: unknown): string {
    return String(value ?? '').trim();
}

/** Validate one loosely-typed reference, or return null. */
export function toImageReferenceRequest(value: unknown): ImageReferenceRequest | null {
    if (!value || typeof value !== 'object') {
        return null;
    }
    const item = value as Record<string, unknown>;
    if (item.type === 'message') {
        const messageId = cleanId(item.message_id);
        return messageId ? { type: 'message', message_id: messageId } : null;
    }
    if (item.type === 'document') {
        const documentId = cleanId(item.document_id);
        const scope = cleanId(item.scope).toLowerCase() as ImageReferenceScope;
        if (!documentId || !SCOPES.has(scope)) {
            return null;
        }
        const scopeId = scope === 'personal' ? null : cleanId(item.scope_id) || null;
        if (scope !== 'personal' && !scopeId) {
            return null;
        }
        return { type: 'document', document_id: documentId, scope, scope_id: scopeId };
    }
    return null;
}

/** Drop invalid entries and duplicates, keep the first occurrence's order, then cap. */
export function normalizeImageReferences(
    values: readonly unknown[],
    limit: number = MAX_APP_REFERENCE_IMAGES,
): ImageReferenceRequest[] {
    const seen = new Set<string>();
    const references: ImageReferenceRequest[] = [];
    for (const value of values) {
        const reference = toImageReferenceRequest(value);
        if (!reference) {
            continue;
        }
        const key = imageReferenceKey(reference);
        if (seen.has(key)) {
            continue;
        }
        seen.add(key);
        references.push(reference);
    }
    return references.slice(0, Math.max(0, limit));
}

/** Read the provenance stored on a message, ignoring anything malformed. */
export function readImageReferenceProvenance(metadata: unknown): ImageReferenceProvenance[] {
    if (!metadata || typeof metadata !== 'object') {
        return [];
    }
    const raw = (metadata as Record<string, unknown>).image_references;
    if (!Array.isArray(raw)) {
        return [];
    }
    const items: ImageReferenceProvenance[] = [];
    for (const entry of raw) {
        const reference = toImageReferenceRequest(entry);
        if (!reference) {
            continue;
        }
        const record = entry as Record<string, unknown>;
        const width = Number(record.width);
        const height = Number(record.height);
        items.push({
            ...reference,
            file_name: typeof record.file_name === 'string' ? record.file_name : undefined,
            width: Number.isFinite(width) && width > 0 ? width : null,
            height: Number.isFinite(height) && height > 0 ? height : null,
        });
    }
    return items;
}

export function buildWorkspaceImagePreviewUrl(
    documentId: string,
    scope: ImageReferenceScope,
    scopeId: string | null,
    variant: ChatImagePreviewVariant = 'thumbnail',
): string {
    const params = new URLSearchParams({ doc_id: documentId, scope, variant });
    if (scope !== 'personal' && scopeId) {
        params.set('scope_id', scopeId);
    }
    return apiUrl(`/api/workspace_documents/image_preview?${params.toString()}`);
}

/** The preview URL for a reference: the chat image endpoint or the workspace preview endpoint. */
export function imageReferencePreviewUrl(
    reference: ImageReferenceRequest | ImageReferenceProvenance,
    variant: ChatImagePreviewVariant = 'thumbnail',
): string {
    if (reference.type === 'message') {
        const messageId = cleanId(reference.message_id);
        return messageId ? buildChatImagePreviewUrl(messageId, variant) : '';
    }
    const documentId = cleanId(reference.document_id);
    const scope = cleanId(reference.scope).toLowerCase() as ImageReferenceScope;
    if (!documentId || !SCOPES.has(scope)) {
        return '';
    }
    return buildWorkspaceImagePreviewUrl(documentId, scope, cleanId(reference.scope_id) || null, variant);
}
