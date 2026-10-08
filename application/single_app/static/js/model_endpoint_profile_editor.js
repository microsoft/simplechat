// model_endpoint_profile_editor.js

export const GENAI_MIL_PROFILE = "genai_mil";
const defaultEndpoint = "https://api.genai.mil/v1";

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
    document.getElementById("model-endpoint-origin-approved").checked = false;
    updateCustomProfileVisibility(custom);
}

export function updateCustomProfileVisibility(custom) {
    const group = document.getElementById("model-endpoint-profile-group");
    const approval = document.getElementById("model-endpoint-origin-approval-group");
    group?.classList.toggle("d-none", !custom);
    approval?.classList.toggle("d-none", !custom || selectedCustomProfile() !== GENAI_MIL_PROFILE);
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
    }
    return {
        profile,
        ...(profile === GENAI_MIL_PROFILE ? {
            credential_origin_approved: document.getElementById("model-endpoint-origin-approved").checked
        } : {})
    };
}
