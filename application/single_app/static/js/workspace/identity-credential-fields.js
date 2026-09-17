// identity-credential-fields.js
// Shared, non-persisted input fields for personal identities and action connections.

const identityFields = Object.freeze({
    username_password: [
        { name: 'username', label: 'Username', type: 'text', required: true },
        { name: 'password', label: 'Password', type: 'password', required: true },
    ],
    api_key: [{ name: 'secret', label: 'API key', type: 'password', required: true }],
    bearer_token: [{ name: 'secret', label: 'Bearer token', type: 'password', required: true }],
});

export function getIdentityCredentialFields(authType) {
    const fields = identityFields[authType];
    if (!fields) {
        throw new Error('This identity credential type is not supported here.');
    }
    return fields.map(field => ({ ...field }));
}

export function createIdentityCredentialField({
    id, name, label, type = 'password', required = false, stored = false,
    value = '', wrapperClass = 'col-md-6', ownerDocument = document,
}) {
    const wrapper = ownerDocument.createElement('div');
    wrapper.className = wrapperClass;
    const labelElement = ownerDocument.createElement('label');
    labelElement.className = 'form-label';
    labelElement.htmlFor = id;
    labelElement.textContent = label;
    const input = ownerDocument.createElement('input');
    input.id = id;
    input.name = name || '';
    input.className = 'form-control';
    input.type = type === 'text' ? 'text' : 'password';
    input.required = required && !stored;
    input.autocomplete = type === 'text' ? 'off' : 'new-password';
    input.maxLength = type === 'text' ? 255 : 8192;
    input.spellcheck = false;
    input.setAttribute('autocapitalize', 'none');
    input.setAttribute('data-private-credential', 'true');
    input.setAttribute('data-bwignore', 'true');
    input.setAttribute('data-1p-ignore', 'true');
    input.setAttribute('data-lpignore', 'true');
    input.placeholder = stored ? 'Stored value unchanged' : '';
    // Never put a credential in a value attribute, dataset, or HTML string.
    input.value = type === 'text' ? value : '';
    wrapper.append(labelElement, input);
    return { wrapper, label: labelElement, input };
}

export function readIdentityCredentialFields(authType, inputs) {
    const values = {};
    getIdentityCredentialFields(authType).forEach(field => {
        const input = inputs[field.name];
        if (!input) {
            throw new Error('Required identity fields are unavailable.');
        }
        values[field.name] = field.name === 'username' ? input.value.trim() : input.value;
    });
    return values;
}

export function wipeIdentityCredentialFields(container) {
    container?.querySelectorAll('[data-private-credential]').forEach(input => {
        input.value = '';
        input.removeAttribute('value');
    });
}
