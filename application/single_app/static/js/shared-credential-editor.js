// shared-credential-editor.js

const storedSecretMarkers = new Set([
    '***REDACTED***', 'Stored_In_KeyVault', '[REDACTED]', '********', '**********'
]);

export function isStoredCredentialValue(value) {
    return typeof value === 'string' && storedSecretMarkers.has(value);
}

function pointerParts(pointer) {
    if (typeof pointer !== 'string' || !pointer.startsWith('/') || /~(?![01])/.test(pointer)) {
        throw new Error('Stored credential fields are invalid. Reload this editor.');
    }
    const parts = pointer.slice(1).split('/').map(part => part.replace(/~1/g, '/').replace(/~0/g, '~'));
    if (parts.some(part => ['__proto__', 'prototype', 'constructor'].includes(part))) {
        throw new Error('Stored credential fields are invalid. Reload this editor.');
    }
    return parts;
}

function readPath(record, parts) {
    let value = record;
    for (const part of parts) {
        if (!value || typeof value !== 'object' || !Object.hasOwn(value, part)) return undefined;
        value = value[part];
    }
    return value;
}

function writePath(record, parts, value, remove = false) {
    let parent = record;
    for (const part of parts.slice(0, -1)) {
        if (!parent[part] || typeof parent[part] !== 'object') {
            if (remove) return;
            parent[part] = {};
        }
        parent = parent[part];
    }
    const leaf = parts[parts.length - 1];
    if (remove) delete parent[leaf];
    else parent[leaf] = value;
}

export class SharedCredentialEditor {
    constructor(record) {
        this.record = record;
        this.active = Boolean(record?.is_group && record.read_only === false && Array.isArray(record.secret_paths));
        this.paths = this.active ? record.secret_paths.map(pointer => ({ pointer, parts: pointerParts(pointer) })) : [];
        this.clears = new Set();
        const required = Array.isArray(record?.credential_reentry_required) ? record.credential_reentry_required : [];
        this.reentry = new Set(required.filter(field => typeof field?.path === 'string').map(field => field.path));
    }

    has(pointer) {
        return this.paths.some(field => field.pointer === pointer);
    }

    render(container) {
        container?.querySelector('[data-shared-credentials]')?.remove();
        if (!container || !this.active || !this.paths.length) return;
        const notice = document.createElement('div');
        notice.dataset.sharedCredentials = 'true';
        notice.className = 'alert alert-secondary mt-3';
        const title = document.createElement('strong');
        title.textContent = 'Stored credentials are write-only';
        const guidance = document.createElement('p');
        guidance.className = 'mb-2';
        guidance.textContent = 'Keep configured values unchanged, or enter replacements. Select a field below to clear it explicitly; change the authentication method if that field is required.';
        notice.append(title, guidance);
        for (const [index, field] of this.paths.entries()) {
            const row = document.createElement('div');
            row.className = 'form-check text-break';
            const checkbox = document.createElement('input');
            checkbox.type = 'checkbox';
            checkbox.className = 'form-check-input';
            checkbox.id = `${container.closest('.modal')?.id || 'shared'}-clear-credential-${index}`;
            checkbox.addEventListener('change', () => {
                if (checkbox.checked) this.clears.add(field.pointer);
                else this.clears.delete(field.pointer);
            });
            const label = document.createElement('label');
            label.className = 'form-check-label';
            label.htmlFor = checkbox.id;
            label.textContent = `Clear ${field.parts.join(' / ')}`;
            row.append(checkbox, label);
            notice.appendChild(row);
        }
        container.prepend(notice);
    }

    basicAuth(username, password) {
        if (this.has('/auth/key')) {
            if (isStoredCredentialValue(username) && isStoredCredentialValue(password)) {
                return this.record.auth.key;
            }
            if (isStoredCredentialValue(username) || isStoredCredentialValue(password)) {
                throw new Error('Re-enter both the username and password to replace stored Basic authentication.');
            }
        }
        return `${username}:${password}`;
    }

    apply(payload) {
        if (!this.active) return payload;
        if (typeof this.record.revision !== 'string' || !this.record.revision) {
            throw new Error('Reload this resource before saving; its revision is unavailable.');
        }
        for (const field of this.paths) {
            const value = readPath(payload, field.parts);
            if (this.clears.has(field.pointer)) {
                const requiredKey = field.pointer === '/auth/key' && payload.auth?.type === 'key';
                writePath(payload, field.parts, requiredKey ? '' : undefined, !requiredKey);
            } else if (this.reentry.has(field.pointer)) {
                if (isStoredCredentialValue(value)) writePath(payload, field.parts, undefined, true);
            } else if (value === '' || value === null) {
                writePath(payload, field.parts, readPath(this.record, field.parts));
            } else if (typeof value === 'string' && !isStoredCredentialValue(value)
                && [...storedSecretMarkers].some(marker => value.includes(marker))) {
                throw new Error('Re-enter the complete credential rather than combining it with a stored-value marker.');
            }
        }
        payload.expected_revision = this.record.revision;
        payload.clear_secret_paths = [...this.clears];
        return payload;
    }
}
