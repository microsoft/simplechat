// termsOfUse.ts
// Calls behind the V2 Terms of Use page. The server owns every decision here -- whether
// the terms apply, where to return, where a decline goes -- so the page only renders and
// follows what these return.

import { request } from './apiClient';
import type { BootstrapPayload } from './types';

export type TermsOfUseBranding = Pick<
    BootstrapPayload['branding'],
    'app_title' | 'hide_app_title' | 'show_logo' | 'logo_url' | 'logo_dark_url' | 'classification_banner'
>;

export interface TermsOfUsePayload {
    /** False when no terms are configured; the page then just continues. */
    enabled: boolean;
    /** False when the user's acceptance is still current. */
    required: boolean;
    title: string;
    /** Plain text. Rendered as text, never as HTML. */
    message: string;
    accept_button_text: string;
    decline_button_text: string;
    /** The local path the server will return to after acceptance. */
    return_path: string;
    branding: TermsOfUseBranding;
}

export interface TermsOfUseDecision {
    success: boolean;
    redirect_url: string;
}

export function fetchTermsOfUse(next: string | null): Promise<TermsOfUsePayload> {
    const query = next ? `?${new URLSearchParams({ next }).toString()}` : '';
    return request<TermsOfUsePayload>(`/api/v2/terms-of-use${query}`);
}

export function acceptTermsOfUse(): Promise<TermsOfUseDecision> {
    return request<TermsOfUseDecision>('/api/v2/terms-of-use/accept', { method: 'POST', body: {} });
}

export function declineTermsOfUse(): Promise<TermsOfUseDecision> {
    return request<TermsOfUseDecision>('/api/v2/terms-of-use/decline', { method: 'POST', body: {} });
}
