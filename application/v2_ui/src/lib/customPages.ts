// customPages.ts
// Types and helpers for the static custom page designer.
//
// The shape mirrors `normalize_custom_page_metadata` in `functions_custom_pages.py`, which
// is what the CRUD API returns and expects. Validation here is a local mirror of
// `validate_custom_page_metadata`: it exists to catch mistakes while typing, not to replace
// the server check, which stays authoritative.

export type CustomPageEntryType = 'static' | 'python';
export type CustomPageAccessLevel = 'app_user' | 'authenticated';

export interface CustomPage {
    id?: string;
    slug: string;
    title: string;
    description: string;
    enabled: boolean;
    entry_type: CustomPageEntryType;
    access_level: CustomPageAccessLevel;
    nav_label: string;
    nav_icon: string;
    nav_order: number;
    roles: string[];
    show_in_nav: boolean;
    open_in_new_tab: boolean;
    html_file: string;
    css_files: string[];
    js_files: string[];
    asset_files: string[];
    json_files: string[];
    /** 'cosmos' for pages created here; 'python' for code-registered pages. */
    source?: string;
}

export const ACCESS_LEVEL_LABELS: Record<CustomPageAccessLevel, string> = {
    app_user: 'App users only',
    authenticated: 'Any signed-in user',
};

/** File extensions each folder accepts. Mirrors `ASSET_FOLDERS`. */
export const ASSET_FOLDER_EXTENSIONS: Record<string, string[]> = {
    css_files: ['.css'],
    js_files: ['.js'],
    json_files: ['.json'],
    asset_files: ['.png', '.jpg', '.jpeg', '.gif', '.svg', '.webp', '.ico', '.woff', '.woff2'],
};

export const SLUG_PATTERN = /^[a-z0-9][a-z0-9_-]*$/;

export function emptyCustomPage(): CustomPage {
    return {
        slug: '',
        title: '',
        description: '',
        enabled: true,
        entry_type: 'static',
        access_level: 'app_user',
        nav_label: '',
        nav_icon: '',
        nav_order: 100,
        roles: [],
        show_in_nav: true,
        open_in_new_tab: false,
        html_file: '',
        css_files: [],
        js_files: [],
        asset_files: [],
        json_files: [],
    };
}

function asStringList(value: unknown): string[] {
    return Array.isArray(value)
        ? value.filter((item): item is string => typeof item === 'string')
        : [];
}

/** Read an API page defensively into the editor's shape. */
export function toCustomPage(raw: unknown): CustomPage {
    const page = (raw ?? {}) as Record<string, unknown>;
    const base = emptyCustomPage();
    return {
        ...base,
        id: typeof page.id === 'string' ? page.id : undefined,
        slug: typeof page.slug === 'string' ? page.slug : '',
        title: typeof page.title === 'string' ? page.title : '',
        description: typeof page.description === 'string' ? page.description : '',
        enabled: page.enabled !== false,
        entry_type: page.entry_type === 'python' ? 'python' : 'static',
        access_level: page.access_level === 'authenticated' ? 'authenticated' : 'app_user',
        nav_label: typeof page.nav_label === 'string' ? page.nav_label : '',
        nav_icon: typeof page.nav_icon === 'string' ? page.nav_icon : '',
        nav_order: typeof page.nav_order === 'number' ? page.nav_order : 100,
        roles: asStringList(page.roles),
        show_in_nav: page.show_in_nav !== false,
        open_in_new_tab: page.open_in_new_tab === true,
        html_file: typeof page.html_file === 'string' ? page.html_file : '',
        css_files: asStringList(page.css_files),
        js_files: asStringList(page.js_files),
        asset_files: asStringList(page.asset_files),
        json_files: asStringList(page.json_files),
        source: typeof page.source === 'string' ? page.source : undefined,
    };
}

/** Pages registered in Python are defined in code and cannot be edited here. */
export function isReadOnly(page: CustomPage): boolean {
    return page.source === 'python' || page.entry_type === 'python';
}

export function validateCustomPage(page: CustomPage): Record<string, string> {
    const errors: Record<string, string> = {};

    if (!SLUG_PATTERN.test(page.slug)) {
        errors.slug =
            'Start with a lowercase letter or number, then lowercase letters, numbers, hyphens or underscores.';
    }
    if (!page.title.trim()) {
        errors.title = 'Title is required.';
    }
    if (!page.html_file.trim()) {
        errors.html_file = 'Static pages need an HTML file.';
    } else if (!page.html_file.trim().toLowerCase().endsWith('.html')) {
        errors.html_file = 'The entry file must be a .html file.';
    }

    for (const [key, extensions] of Object.entries(ASSET_FOLDER_EXTENSIONS)) {
        const files = page[key as keyof CustomPage] as string[];
        const bad = files.filter(
            (file) => !extensions.some((ext) => file.toLowerCase().endsWith(ext)),
        );
        if (bad.length) {
            errors[key] = `Unsupported extension: ${bad.join(', ')}. Expected ${extensions.join(', ')}.`;
        }
    }

    const unsafe = [page.html_file, ...page.css_files, ...page.js_files, ...page.asset_files, ...page.json_files]
        .filter((file) => file)
        .filter((file) => file.startsWith('/') || file.replace(/\\/g, '/').split('/').includes('..'));
    if (unsafe.length) {
        errors.html_file = `Unsafe file path: ${unsafe.join(', ')}.`;
    }

    return errors;
}

/** Roles are edited as a comma-separated string, which is how V1 presents them. */
export function parseRoles(value: string): string[] {
    return value
        .split(',')
        .map((role) => role.trim())
        .filter(Boolean);
}
