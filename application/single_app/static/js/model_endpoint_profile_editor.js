// model_endpoint_profile_editor.js

export const GENAI_MIL_PROFILE = "genai_mil";
const defaultEndpoint = "https://api.genai.mil/v1";
const apiKeyHeaderInput = document.getElementById("model-endpoint-api-key-header");
const apiKeyPrefixInput = document.getElementById("model-endpoint-api-key-prefix");
const blockedCredentialHeaders = new Set([
    "host", "content-length", "transfer-encoding", "connection", "cookie", "set-cookie"
]);

export function selectedCustomProfile() {
    return document.getElementById("model-endpoint-profile")?.value || "";
}

export function populateCustomProfile(endpoint, custom) {
    const group = document.getElementById("model-endpoint-profile-group");
    const select = document.getElementById("model-endpoint-profile");
    if (!group || !select) {
        return;
    }
    group.classList.toggle("d-none", !custom);
    select.value = endpoint.profile || "";
    for (const [input, value] of [
        [apiKeyHeaderInput, endpoint.auth?.api_key_header],
        [apiKeyPrefixInput, endpoint.auth?.api_key_prefix]
    ]) {
        if (input) {
            input.value = value ?? "";
            input.setCustomValidity("");
            input.setAttribute("aria-invalid", "false");
        }
    }
    document.getElementById("model-endpoint-origin-approved").checked = false;
    updateCustomProfileVisibility(custom);
}

export function updateCustomProfileVisibility(custom) {
    const group = document.getElementById("model-endpoint-profile-group");
    const approval = document.getElementById("model-endpoint-origin-approval-group");
    const customApiKey = custom && selectedCustomProfile() !== GENAI_MIL_PROFILE;
    group?.classList.toggle("d-none", !custom);
    approval?.classList.toggle("d-none", !custom || selectedCustomProfile() !== GENAI_MIL_PROFILE);
    document.getElementById("model-endpoint-api-key-overrides")?.classList.toggle("d-none", !customApiKey);
    if (apiKeyHeaderInput) apiKeyHeaderInput.disabled = !customApiKey;
    if (apiKeyPrefixInput) apiKeyPrefixInput.disabled = !customApiKey;
}

export function applyCustomProfileDefaults() {
    if (selectedCustomProfile() !== GENAI_MIL_PROFILE) {
        return;
    }
    const endpoint = document.getElementById("model-endpoint-endpoint");
    if (endpoint && !endpoint.value.trim()) {
        endpoint.value = defaultEndpoint;
    }
    document.getElementById("model-endpoint-api-type").value = "openai";
}

export function collectCustomProfile(auth, custom) {
    const profile = custom ? selectedCustomProfile() : "";
    if (profile === GENAI_MIL_PROFILE) {
        auth.api_key_header = "Authorization";
        auth.api_key_prefix = "Bearer";
    } else if (custom) {
        if (!apiKeyHeaderInput || !apiKeyPrefixInput) {
            throw new Error("Custom authentication controls could not be loaded. Reload the page.");
        }
        const header = apiKeyHeaderInput.value.trim();
        const prefix = apiKeyPrefixInput.value.trim();
        const invalidHeader = header && (
            header.length > 128
            || !/^[!#$%&'*+.^_`|~0-9A-Za-z-]+$/.test(header)
            || blockedCredentialHeaders.has(header.toLowerCase())
        );
        const invalidPrefix = prefix.length > 128 || /[^\x20-\x7E]/.test(prefix);
        apiKeyHeaderInput.setCustomValidity(
            invalidHeader ? "Enter a valid authentication header name, not a transport or cookie header." : ""
        );
        apiKeyPrefixInput.setCustomValidity(
            invalidPrefix ? "Enter an API key prefix of at most 128 printable ASCII characters." : ""
        );
        apiKeyHeaderInput.setAttribute("aria-invalid", invalidHeader ? "true" : "false");
        apiKeyPrefixInput.setAttribute("aria-invalid", invalidPrefix ? "true" : "false");
        if (!apiKeyHeaderInput.reportValidity() || !apiKeyPrefixInput.reportValidity()) {
            return null;
        }
        auth.api_key_header = header;
        auth.api_key_prefix = prefix;
    }
    return {
        profile,
        ...(profile === GENAI_MIL_PROFILE ? {
            credential_origin_approved: document.getElementById("model-endpoint-origin-approved").checked
        } : {})
    };
}
