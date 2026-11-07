// CustomPageDesigner.tsx
// Create and edit static custom page metadata.
//
// Backed by the same `/api/admin/custom-pages` CRUD the server-rendered designer uses, so a
// page created in either interface is identical. The form only writes metadata: the HTML,
// CSS, JS and asset files themselves are deployed with the application, and this names
// which of them a page uses.

import { useState } from 'react';
import { clsx } from 'clsx';
import { AlertCircle, Loader2, Plus, X } from 'lucide-react';
import { AdminModal } from './AdminModal';
import { GlassButton } from '../ui/primitives';
import {
    ACCESS_LEVEL_LABELS,
    parseRoles,
    validateCustomPage,
    type CustomPage,
} from '../../lib/customPages';

const inputClass = clsx(
    'w-full rounded-lg border border-edge bg-surface-1 px-2.5 py-1.5',
    'text-sm text-text-1 placeholder:text-text-3',
    'focus:border-accent focus:outline-none',
);

const FILE_FIELDS: Array<{ key: 'css_files' | 'js_files' | 'asset_files' | 'json_files'; label: string; placeholder: string }> = [
    { key: 'css_files', label: 'CSS files', placeholder: 'my-page.css' },
    { key: 'js_files', label: 'JavaScript files', placeholder: 'my-page.js' },
    { key: 'asset_files', label: 'Asset files', placeholder: 'logo.png' },
    { key: 'json_files', label: 'JSON files', placeholder: 'config.json' },
];

function Field({
    label,
    error,
    help,
    children,
}: {
    label: string;
    error?: string;
    help?: string;
    children: React.ReactNode;
}) {
    return (
        <div>
            <label className="mb-1 block text-xs font-medium text-text-2">{label}</label>
            {children}
            {help ? <p className="mt-1 text-xs text-text-3">{help}</p> : null}
            {error ? (
                <p role="alert" className="mt-1 flex items-center gap-1 text-xs text-danger">
                    <AlertCircle size={12} className="shrink-0" />
                    {error}
                </p>
            ) : null}
        </div>
    );
}

/** A named list of deployed files, added one at a time. */
function FileListEditor({
    label,
    placeholder,
    files,
    error,
    onChange,
}: {
    label: string;
    placeholder: string;
    files: string[];
    error?: string;
    onChange: (next: string[]) => void;
}) {
    const [entry, setEntry] = useState('');

    const add = () => {
        const candidate = entry.trim();
        if (!candidate || files.includes(candidate)) {
            setEntry('');
            return;
        }
        onChange([...files, candidate]);
        setEntry('');
    };

    return (
        <Field label={label} error={error}>
            <div className="flex gap-1.5">
                <input
                    type="text"
                    className={clsx(inputClass, 'font-mono text-xs')}
                    placeholder={placeholder}
                    value={entry}
                    spellCheck={false}
                    aria-label={`Add a ${label.toLowerCase()} entry`}
                    onChange={(event) => setEntry(event.target.value)}
                    onKeyDown={(event) => {
                        if (event.key === 'Enter') {
                            event.preventDefault();
                            add();
                        }
                    }}
                />
                <GlassButton type="button" variant="subtle" size="sm" onClick={add}>
                    <Plus size={14} />
                </GlassButton>
            </div>

            {files.length ? (
                <ul className="mt-1.5 flex flex-wrap gap-1.5">
                    {files.map((file) => (
                        <li
                            key={file}
                            className="flex items-center gap-1 rounded-md border border-edge bg-surface-2 px-2 py-0.5 font-mono text-xs text-text-2"
                        >
                            {file}
                            <button
                                type="button"
                                aria-label={`Remove ${file}`}
                                className="text-text-3 transition-colors hover:text-danger"
                                onClick={() => onChange(files.filter((item) => item !== file))}
                            >
                                <X size={12} />
                            </button>
                        </li>
                    ))}
                </ul>
            ) : null}
        </Field>
    );
}

export function CustomPageDesigner({
    page,
    isNew,
    existingSlugs,
    saving,
    serverError,
    onCancel,
    onSave,
}: {
    page: CustomPage;
    isNew: boolean;
    existingSlugs: string[];
    saving: boolean;
    serverError: string | null;
    onCancel: () => void;
    onSave: (page: CustomPage) => void;
}) {
    const [draft, setDraft] = useState<CustomPage>(page);
    const [rolesText, setRolesText] = useState(page.roles.join(', '));
    const [showErrors, setShowErrors] = useState(false);

    const errors = validateCustomPage(draft);
    if (isNew && existingSlugs.includes(draft.slug)) {
        errors.slug = 'A custom page with this slug already exists.';
    }
    const visibleErrors = showErrors ? errors : {};

    const patch = (changes: Partial<CustomPage>) =>
        setDraft((current) => ({ ...current, ...changes }));

    const submit = () => {
        setShowErrors(true);
        if (Object.keys(errors).length) {
            return;
        }
        onSave({ ...draft, roles: parseRoles(rolesText) });
    };

    return (
        <AdminModal
            title={isNew ? 'New static page' : `Edit ${page.slug}`}
            description="Metadata only. The files themselves are deployed with the application."
            size="lg"
            onClose={onCancel}
            footer={
                <>
                    <GlassButton type="button" variant="ghost" size="sm" onClick={onCancel}>
                        Cancel
                    </GlassButton>
                    <GlassButton
                        type="button"
                        variant="primary"
                        size="sm"
                        disabled={saving}
                        onClick={submit}
                    >
                        {saving ? <Loader2 size={14} className="animate-spin" /> : null}
                        Save page
                    </GlassButton>
                </>
            }
        >
            <div className="space-y-4">
                {serverError ? (
                    <p
                        role="alert"
                        className="flex items-start gap-2 rounded-lg border border-edge bg-danger-soft px-3 py-2 text-xs text-danger"
                    >
                        <AlertCircle size={14} className="mt-0.5 shrink-0" />
                        {serverError}
                    </p>
                ) : null}

                <div className="grid gap-3 sm:grid-cols-2">
                    <Field
                        label="Slug"
                        error={visibleErrors.slug}
                        help={draft.slug ? `Served at /custom/${draft.slug}` : 'Served at /custom/<slug>'}
                    >
                        <input
                            type="text"
                            className={clsx(inputClass, 'font-mono text-xs')}
                            placeholder="team-dashboard"
                            value={draft.slug}
                            spellCheck={false}
                            // Editing a slug would orphan the existing document, so it is
                            // fixed once the page exists. V1 behaves the same way.
                            disabled={!isNew}
                            onChange={(event) =>
                                patch({ slug: event.target.value.trim().toLowerCase() })
                            }
                        />
                    </Field>

                    <Field label="Title" error={visibleErrors.title}>
                        <input
                            type="text"
                            className={inputClass}
                            value={draft.title}
                            onChange={(event) => patch({ title: event.target.value })}
                        />
                    </Field>
                </div>

                <Field label="Description">
                    <textarea
                        className={clsx(inputClass, 'resize-y')}
                        rows={2}
                        value={draft.description}
                        onChange={(event) => patch({ description: event.target.value })}
                    />
                </Field>

                <Field label="HTML file" error={visibleErrors.html_file}>
                    <input
                        type="text"
                        className={clsx(inputClass, 'font-mono text-xs')}
                        placeholder="my-page.html"
                        value={draft.html_file}
                        spellCheck={false}
                        onChange={(event) => patch({ html_file: event.target.value })}
                    />
                </Field>

                <div className="grid gap-3 sm:grid-cols-3">
                    <Field label="Navigation label">
                        <input
                            type="text"
                            className={inputClass}
                            placeholder={draft.title || 'Navigation label'}
                            value={draft.nav_label}
                            onChange={(event) => patch({ nav_label: event.target.value })}
                        />
                    </Field>
                    <Field label="Bootstrap icon">
                        <input
                            type="text"
                            className={clsx(inputClass, 'font-mono text-xs')}
                            placeholder="bi-file-earmark-text"
                            value={draft.nav_icon}
                            spellCheck={false}
                            onChange={(event) => patch({ nav_icon: event.target.value })}
                        />
                    </Field>
                    <Field label="Order">
                        <input
                            type="number"
                            className={inputClass}
                            value={draft.nav_order}
                            onChange={(event) =>
                                patch({ nav_order: Number(event.target.value) || 0 })
                            }
                        />
                    </Field>
                </div>

                <div className="grid gap-3 sm:grid-cols-2">
                    <Field label="Access level">
                        <select
                            className={clsx(inputClass, 'appearance-none')}
                            value={draft.access_level}
                            onChange={(event) =>
                                patch({
                                    access_level: event.target
                                        .value as CustomPage['access_level'],
                                })
                            }
                        >
                            {Object.entries(ACCESS_LEVEL_LABELS).map(([value, label]) => (
                                <option key={value} value={value}>
                                    {label}
                                </option>
                            ))}
                        </select>
                    </Field>
                    <Field
                        label="Allowed roles"
                        help="Comma separated. Leave blank to allow all signed-in users."
                    >
                        <input
                            type="text"
                            className={inputClass}
                            placeholder="Admin, User"
                            value={rolesText}
                            onChange={(event) => setRolesText(event.target.value)}
                        />
                    </Field>
                </div>

                <div className="rounded-lg border border-edge p-3">
                    <h3 className="mb-3 text-xs font-semibold text-text-1">Deployed files</h3>
                    <div className="grid gap-3 sm:grid-cols-2">
                        {FILE_FIELDS.map((entry) => (
                            <FileListEditor
                                key={entry.key}
                                label={entry.label}
                                placeholder={entry.placeholder}
                                files={draft[entry.key]}
                                error={visibleErrors[entry.key]}
                                onChange={(next) => patch({ [entry.key]: next } as Partial<CustomPage>)}
                            />
                        ))}
                    </div>
                </div>

                <div className="rounded-lg border border-edge p-3">
                    <h3 className="mb-2 text-xs font-semibold text-text-1">Publishing</h3>
                    <div className="grid gap-2 sm:grid-cols-3">
                        {(
                            [
                                ['enabled', 'Enabled'],
                                ['show_in_nav', 'Show in navigation'],
                                ['open_in_new_tab', 'Open in new tab'],
                            ] as const
                        ).map(([key, label]) => (
                            <label
                                key={key}
                                className="flex cursor-pointer items-center gap-2 text-sm text-text-2"
                            >
                                <input
                                    type="checkbox"
                                    className="accent-[var(--accent)]"
                                    checked={draft[key]}
                                    onChange={(event) =>
                                        patch({ [key]: event.target.checked } as Partial<CustomPage>)
                                    }
                                />
                                {label}
                            </label>
                        ))}
                    </div>
                </div>
            </div>
        </AdminModal>
    );
}
