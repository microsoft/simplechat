// sidebarMenuState.ts
// The expanded/collapsed state of the rail's named menus, shared with the classic interface.
//
// Both interfaces store this in one per-user setting, `sidebarMenuState`, so a group
// collapsed in one is collapsed in the other. That sharing imposes two constraints this
// module exists to enforce.
//
// The first is that `update_user_settings()` merges only the *top* level of the settings
// document (`doc['settings'].update(...)`), so posting a single key inside this object
// replaces the whole object. Writing `{ externalLinks: false }` on its own would silently
// discard the classic interface's `workspaces`, `support`, `conversations` and admin
// entries. Every write therefore has to carry the full state, which is what
// `withSidebarMenuExpanded` produces.
//
// The second is that the classic normaliser in static/js/sidebar.js drops any key outside
// its own whitelist each time it writes. A key invented here would survive exactly until
// the next toggle made in the other interface, so the whitelist below is quoted from it
// rather than extended.
//
// Kept free of store and React imports so the runtime test can import it directly under
// Node's TypeScript type-stripping.

/**
 * Keys the classic interface recognises, quoted from `sidebarMenuStateKeys` in
 * static/js/sidebar.js. Anything else is dropped on write by whichever interface writes
 * next, so it cannot be relied on.
 */
export const SIDEBAR_MENU_STATE_KEYS = [
    'workspaces',
    'support',
    'externalLinks',
    'customPages',
    'adminSettings',
    'controlCenter',
    'conversations',
] as const;

export type SidebarMenuKey = (typeof SIDEBAR_MENU_STATE_KEYS)[number];

export type SidebarMenuState = Partial<Record<SidebarMenuKey, boolean>>;

const KNOWN_KEYS: ReadonlySet<string> = new Set(SIDEBAR_MENU_STATE_KEYS);

/**
 * Coerce a stored value into the shape both interfaces agree on.
 *
 * Mirrors `normalizeSidebarMenuState` in the classic interface, including its tolerance of
 * `"true"` / `"false"` strings: the setting has been written by more than one code path over
 * time and a document in the wild may hold either form. An unrecognised key or value type is
 * dropped rather than passed through, so a malformed document cannot make a group
 * permanently disagree between the two interfaces.
 */
export function normalizeSidebarMenuState(value: unknown): SidebarMenuState {
    if (!value || typeof value !== 'object' || Array.isArray(value)) {
        return {};
    }

    const normalized: SidebarMenuState = {};

    for (const [key, rawValue] of Object.entries(value as Record<string, unknown>)) {
        if (!KNOWN_KEYS.has(key)) {
            continue;
        }

        if (typeof rawValue === 'boolean') {
            normalized[key as SidebarMenuKey] = rawValue;
            continue;
        }

        if (typeof rawValue === 'string') {
            const flag = rawValue.trim().toLowerCase();
            if (flag === 'true' || flag === 'false') {
                normalized[key as SidebarMenuKey] = flag === 'true';
            }
        }
    }

    return normalized;
}

/**
 * Whether a menu should be drawn open.
 *
 * Absent means open, matching the classic templates' `sidebar_menu_state.get(key, true)`.
 * A user who has never touched a group sees its links rather than having to discover that a
 * heading is a button.
 */
export function readSidebarMenuExpanded(value: unknown, key: SidebarMenuKey): boolean {
    const state = normalizeSidebarMenuState(value);
    return state[key] !== false;
}

/**
 * The complete state to post after toggling one menu.
 *
 * The existing state is carried through untouched, which is what keeps a change made here
 * from resetting the classic interface's own menus.
 */
export function withSidebarMenuExpanded(
    value: unknown,
    key: SidebarMenuKey,
    expanded: boolean,
): SidebarMenuState {
    return { ...normalizeSidebarMenuState(value), [key]: Boolean(expanded) };
}
