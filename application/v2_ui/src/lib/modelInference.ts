// modelInference.ts
// Keep the selected chat API separate from the connection's reusable base URL.

interface InferenceConnection {
    endpoint?: string;
    use_responses_api?: boolean;
}

export function usesResponsesApi(connection: InferenceConnection | undefined): boolean {
    if (connection?.use_responses_api === true) return true;
    try {
        return /\/responses\/?$/i.test(new URL(connection?.endpoint ?? '').pathname);
    } catch {
        return false;
    }
}

export function normalizeInferenceConnection<T extends InferenceConnection>(connection: T): T {
    const endpoint = connection.endpoint?.trim() ?? '';
    try {
        const parsed = new URL(endpoint);
        const match = parsed.pathname.replace(/\/$/, '').match(/\/(responses|chat\/completions)$/i);
        if (match && !parsed.search && !parsed.hash) {
            return {
                ...connection,
                endpoint: endpoint.replace(/\/(?:responses|chat\/completions)\/?$/i, ''),
                use_responses_api: match[1].toLowerCase() === 'responses',
            };
        }
    } catch {
        // Leave incomplete text intact so the connection form can show its validation error.
    }
    return { ...connection, endpoint };
}
