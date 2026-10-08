// model_ca_bundles.js

const selectionRequests = new WeakMap();
const bundleIdPattern = /^ca-[0-9a-f]{32}$/;

export class CABundleRequestError extends Error {}

export async function requestCertificateApi(url, options = {}) {
    try {
        const response = await fetch(url, options);
        const data = await response.json();
        if (!response.ok) {
            throw new CABundleRequestError(
                typeof data.error === "string" ? data.error : "The certificate operation could not be completed."
            );
        }
        if (!data || typeof data !== "object") {
            throw new CABundleRequestError("The certificate service returned an invalid response.");
        }
        return data;
    } catch (error) {
        if (error instanceof CABundleRequestError) {
            throw error;
        }
        if (error instanceof TypeError || error instanceof SyntaxError) {
            throw new CABundleRequestError("Unable to reach the certificate service. Refresh and try again.");
        }
        throw error;
    }
}

function baseOptions() {
    return [
        new Option("Existing application trust (legacy path or public roots)", "inherit"),
        new Option("Public certificate authorities", "public")
    ];
}

function savedChoice(endpoint) {
    const connection = endpoint.connection || {};
    if (connection.ca_bundle_mode === "bundle") {
        return connection.ca_bundle_id || "";
    }
    return connection.ca_bundle_mode || (endpoint.id ? "inherit" : "public");
}

export async function populateEndpointCaBundleSelection(endpoint, scope, custom) {
    const group = document.getElementById("model-endpoint-ca-bundle-group");
    const select = document.getElementById("model-endpoint-ca-bundle");
    const error = document.getElementById("model-endpoint-ca-bundle-error");
    if (!group || !select || !error) {
        return;
    }
    group.classList.toggle("d-none", !custom);
    const requestId = {};
    selectionRequests.set(select, requestId);
    error.classList.add("d-none");
    const initial = savedChoice(endpoint);
    select.replaceChildren(...baseOptions());
    if (bundleIdPattern.test(initial)) {
        select.add(new Option(`Saved CA bundle (${initial})`, initial));
    }
    if (!["inherit", "public"].includes(initial) && !bundleIdPattern.test(initial)) {
        error.textContent = "The saved trust selection is invalid. Choose a supported certificate trust mode.";
        error.classList.remove("d-none");
        select.add(new Option("Invalid saved trust selection", initial));
    }
    select.value = initial;
    if (!custom) {
        return;
    }
    const prefix = scope === "global" ? "/api" : `/api/${scope}`;
    try {
        const data = await requestCertificateApi(`${prefix}/models/ca-bundle-options`);
        if (!Array.isArray(data.bundles) || data.bundles.some(
            (bundle) => !bundleIdPattern.test(bundle.id) || typeof bundle.name !== "string"
        )) {
            throw new CABundleRequestError("The certificate service returned invalid bundle choices.");
        }
        if (selectionRequests.get(select) !== requestId) {
            return;
        }
        const selected = select.value;
        select.replaceChildren(...baseOptions());
        for (const bundle of data.bundles) {
            select.add(new Option(`${bundle.name} (${bundle.id.slice(-8)})`, bundle.id));
        }
        if (selected && !Array.from(select.options).some((option) => option.value === selected)) {
            select.add(new Option(`Saved selection unavailable (${selected})`, selected));
            error.textContent = "The saved CA bundle is unavailable. Select another bundle or public trust; it will not be silently replaced.";
            error.classList.remove("d-none");
        }
        select.value = selected;
    } catch (failure) {
        if (selectionRequests.get(select) === requestId) {
            error.textContent = failure instanceof CABundleRequestError
                ? `${failure.message} Existing trust selection is retained.`
                : "Unable to load certificate choices. Existing trust selection is retained.";
            error.classList.remove("d-none");
        }
    }
}

export function collectEndpointCaTrust(connection, savedConnection, custom) {
    const select = document.getElementById("model-endpoint-ca-bundle");
    delete connection.ca_bundle_mode;
    delete connection.ca_bundle_id;
    if (!custom || !select) {
        return;
    }
    const choice = select.value;
    if (choice === "inherit" && !Object.prototype.hasOwnProperty.call(savedConnection || {}, "ca_bundle_mode")) {
        return;
    }
    if (choice === "inherit" || choice === "public") {
        connection.ca_bundle_mode = choice;
    } else if (bundleIdPattern.test(choice)) {
        connection.ca_bundle_mode = "bundle";
        connection.ca_bundle_id = choice;
    } else {
        throw new CABundleRequestError("Choose a supported certificate trust selection.");
    }
}
