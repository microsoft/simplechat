// Sidebar.tsx
// The single navigation surface. SimpleChat V2 has no top bar by design: brand, primary
// navigation, workspace scopes, theme control and the user menu all live in this rail,
// which collapses to an icon strip.
//
// The user menu deliberately offers one destination for personal settings. It used to offer
// two — Settings here and Profile in the classic interface — which was a choice nobody had
// the information to make, since the classic profile page is where the settings *and* the
// activity stats were. The stats now live on the Settings page's Stats tab, so the second
// entry has nothing left to lead to.

import { useState } from 'react';
import { NavLink, useLocation } from 'react-router-dom';
import { clsx } from 'clsx';
import {
    ChevronDown,
    ChevronLeft,
    ChevronRight,
    FolderOpen,
    Globe2,
    LogOut,
    MessageSquarePlus,
    MessagesSquare,
    Moon,
    Settings,
    SlidersHorizontal,
    Sparkles,
    Sun,
    Users,
} from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { classicChatHref } from '../../lib/conversationUrl';
import { ConversationRail } from '../chat/ConversationRail';
import { NavExtras } from './NavExtras';

interface NavItem {
    to: string;
    label: string;
    icon: typeof MessagesSquare;
    /** Hover text. Two entries are easily confused without it, so both say what they are. */
    hint?: string;
    adminOnly?: boolean;
}

// Home is deliberately absent. The brand mark above this list is the link to it, which is
// where a reader looks for it anyway; a nav row saying the same thing spent a slot on a
// destination the logo already implies.
const NAV_ITEMS: NavItem[] = [
    { to: '/chat', label: 'Chats', icon: MessagesSquare },
    {
        to: '/agents',
        label: 'Agents',
        icon: Sparkles,
        // Distinct from My Workspace > Agents, which is where you build your own. This is
        // the catalogue of every agent you are allowed to use, wherever it came from.
        hint: 'Browse every agent you can use',
    },
    {
        to: '/workspace',
        label: 'My Workspace',
        icon: FolderOpen,
        hint: 'Your documents, prompts, agents and automation',
    },
    { to: '/groups', label: 'Group Workspaces', icon: Users },
    { to: '/public', label: 'Public Workspaces', icon: Globe2 },
    { to: '/admin', label: 'Admin Settings', icon: Settings, adminOnly: true },
];

function BrandMark({ collapsed }: { collapsed: boolean }) {
    const branding = useBootstrapStore((state) => state.data?.branding);
    const theme = useUiStore((state) => state.theme);

    const themedLogoUrl = theme === 'dark' ? branding?.logo_dark_url : branding?.logo_url;
    const title = branding?.app_title || 'SimpleChat';

    // A logo counts only when one is stored *and* switched on.
    const logoUrl = branding?.show_logo ? themedLogoUrl : null;
    const showTitle = !collapsed && !branding?.hide_app_title;
    // The letter square stands in for a mark there is either no configuration or no room
    // for, so it is drawn only where the title itself is not: in the collapsed rail, or
    // when the title is hidden. Beside the title it was the same word twice.
    const showInitial = !logoUrl && !showTitle;

    return (
        // The brand is the way back to the landing page -- there is no separate Home nav
        // item, because this is where a reader looks for one. `end` matters: without it
        // "/" prefixes every route and this would claim aria-current on all of them.
        //
        // The accessible name carries the title rather than reading only "Home", so the
        // visible label stays inside the accessible name (WCAG 2.5.3) and the link is
        // still named when the rail is collapsed to the logo or the letter alone.
        <NavLink
            to="/"
            end
            aria-label={`${title} home`}
            className={clsx(
                '-mx-1.5 flex min-w-0 items-center gap-2.5 rounded-xl px-1.5 py-1.5',
                'transition-colors hover:bg-surface-2',
                collapsed && 'justify-center',
            )}
        >
            {logoUrl && (
                // Height-constrained with a free width, matching the classic navigation.
                // Forcing a square would letterbox or crop the wordmark most deployments
                // upload. The collapsed rail is only 68px wide, so the cap tightens there.
                //
                // Decorative: the link names itself, so alt text would announce twice.
                <img
                    src={logoUrl}
                    alt=""
                    className={clsx(
                        'h-8 w-auto shrink-0 object-contain',
                        collapsed ? 'max-w-[44px]' : 'max-w-[150px]',
                    )}
                />
            )}
            {showInitial && (
                <span
                    aria-hidden="true"
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-sm font-bold text-on-accent"
                >
                    {title.slice(0, 1).toUpperCase()}
                </span>
            )}
            {showTitle && (
                <span className="truncate text-[15px] font-semibold text-text-1" title={title}>
                    {title}
                </span>
            )}
        </NavLink>
    );
}

function UserMenu({ collapsed }: { collapsed: boolean }) {
    const user = useBootstrapStore((state) => state.data?.user);
    const activeConversationId = useChatStore((state) => state.activeConversationId);
    const [open, setOpen] = useState(false);

    const initials =
        (user?.display_name || user?.email || '?')
            .split(/[\s@.]+/)
            .filter(Boolean)
            .slice(0, 2)
            .map((part) => part[0]?.toUpperCase())
            .join('') || '?';

    return (
        <div className="relative">
            {open && !collapsed && (
                <div className="glass-modal absolute bottom-full left-0 mb-2 w-full overflow-hidden rounded-2xl p-1.5">
                    <NavLink
                        to="/settings"
                        onClick={() => setOpen(false)}
                        className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-text-1 hover:bg-surface-2"
                    >
                        <SlidersHorizontal size={15} /> Settings
                    </NavLink>
                    {/* Carries the open conversation across, since both interfaces read the
                        same parameter. Crossing over otherwise lands on the conversation
                        list, leaving you to find your place again. */}
                    <a
                        href={classicChatHref(activeConversationId)}
                        className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-text-1 hover:bg-surface-2"
                    >
                        <ChevronLeft size={15} /> Back to classic UI
                    </a>
                    <a
                        href="/logout"
                        className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-danger hover:bg-danger-soft"
                    >
                        <LogOut size={15} /> Sign out
                    </a>
                </div>
            )}

            <button
                type="button"
                onClick={() => setOpen((isOpen) => !isOpen)}
                aria-expanded={open}
                title={collapsed ? user?.display_name || 'Account' : undefined}
                className={clsx(
                    'flex w-full items-center gap-2.5 rounded-xl p-2 transition-colors hover:bg-surface-2',
                    collapsed && 'justify-center',
                )}
            >
                <span className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
                    {initials}
                </span>
                {!collapsed && (
                    <>
                        <span className="min-w-0 flex-1 text-left">
                            <span className="block truncate text-sm font-medium text-text-1">
                                {user?.display_name || 'Signed in'}
                            </span>
                            {user?.is_admin && (
                                <span className="block text-[11px] text-text-3">Administrator</span>
                            )}
                        </span>
                        <ChevronDown
                            size={14}
                            className={clsx('shrink-0 text-text-3 transition-transform', open && 'rotate-180')}
                        />
                    </>
                )}
            </button>
        </div>
    );
}

export function Sidebar() {
    const { railCollapsed, toggleRail, theme, toggleTheme } = useUiStore();
    const isAdmin = useBootstrapStore((state) => Boolean(state.data?.user?.is_admin));
    const startNewConversation = useChatStore((state) => state.startNewConversation);
    const location = useLocation();

    const onChatPage = location.pathname.startsWith('/chat');
    const collapsed = railCollapsed;

    /**
     * Arriving at the chat page from elsewhere starts a fresh chat.
     *
     * The store is not reset by navigation — it is plain in-memory state that outlives a
     * route change — so without this, returning to the chat page silently re-opens the
     * conversation last read and puts it back in the address bar. Since `New chat` is only
     * offered on the chat page, this is what makes a new chat reachable from anywhere else.
     *
     * Two things are deliberately left alone. Clicking `Chats` while already on the chat
     * page does nothing, so a stray click on the highlighted nav item cannot throw away
     * whatever is being read. And a conversation still streaming a reply is returned to
     * rather than reset, because the reset stops the stream and the reply would be lost.
     *
     * `streaming` is read from the store rather than subscribed to: it changes with every
     * token, and subscribing would re-render this rail — conversation list included —
     * throughout a response.
     */
    const startNewChatOnArrival = () => {
        if (onChatPage || useChatStore.getState().streaming) {
            return;
        }
        startNewConversation();
    };

    return (
        <nav
            aria-label="Primary"
            className={clsx(
                'glass glass-edge flex h-full flex-col rounded-none border-y-0 border-l-0 transition-[width] duration-200',
                collapsed ? 'w-[68px]' : 'w-[280px]',
            )}
        >
            <div
                className={clsx(
                    'flex h-14 shrink-0 items-center gap-2 px-3',
                    collapsed && 'justify-center',
                )}
            >
                <BrandMark collapsed={collapsed} />
                {!collapsed && (
                    <button
                        type="button"
                        onClick={toggleRail}
                        aria-label="Collapse navigation"
                        className="ml-auto rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                    >
                        <ChevronLeft size={17} />
                    </button>
                )}
            </div>

            {collapsed && (
                <button
                    type="button"
                    onClick={toggleRail}
                    aria-label="Expand navigation"
                    className="mx-auto mb-2 rounded-lg p-1.5 text-text-3 transition-colors hover:bg-surface-2 hover:text-text-1"
                >
                    <ChevronRight size={17} />
                </button>
            )}

            {/* Only offered where it has somewhere to act. On any other page it reset chat
                state that was not on screen and left the reader where they were, which
                looked like a button that did nothing. `Chats` covers that case instead. */}
            {onChatPage && (
                <div className="px-3">
                    <button
                        type="button"
                        onClick={startNewConversation}
                        title="Start a new chat"
                        className={clsx(
                            'flex w-full items-center gap-2 rounded-xl bg-accent px-3 py-2.5',
                            'text-sm font-medium text-on-accent transition-colors hover:bg-accent-hover',
                            collapsed && 'justify-center px-0',
                        )}
                    >
                        <MessageSquarePlus size={17} className="shrink-0" />
                        {!collapsed && <span>New chat</span>}
                    </button>
                </div>
            )}

            <ul className={clsx('space-y-0.5 px-3', onChatPage && 'mt-3')}>
                {NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => (
                    <li key={item.to}>
                        <NavLink
                            to={item.to}
                            onClick={item.to === '/chat' ? startNewChatOnArrival : undefined}
                            title={collapsed ? item.label : item.hint}
                            className={({ isActive }) =>
                                clsx(
                                    'flex items-center gap-2.5 rounded-xl px-3 py-2 text-sm transition-colors',
                                    collapsed && 'justify-center px-0',
                                    isActive
                                        ? 'bg-accent-soft font-medium text-accent'
                                        : 'text-text-2 hover:bg-surface-2 hover:text-text-1',
                                )
                            }
                        >
                            <item.icon size={17} className="shrink-0" />
                            {!collapsed && <span className="truncate">{item.label}</span>}
                        </NavLink>
                    </li>
                ))}
            </ul>

            {/* Custom pages and external links an administrator configured. Renders
                nothing when neither is enabled, which is the default. */}
            <NavExtras collapsed={collapsed} />

            {/* The conversation list only belongs in the rail while the chat page is open,
                so other pages get the full rail height for their own navigation. */}
            {onChatPage && !collapsed && (
                <div className="mt-4 min-h-0 flex-1 border-t border-edge pt-3">
                    <ConversationRail />
                </div>
            )}
            {(!onChatPage || collapsed) && <div className="flex-1" />}

            <div className="shrink-0 space-y-1 border-t border-edge p-3">
                <button
                    type="button"
                    onClick={toggleTheme}
                    title={collapsed ? 'Toggle theme' : undefined}
                    aria-label={`Switch to ${theme === 'dark' ? 'light' : 'dark'} theme`}
                    className={clsx(
                        'flex w-full items-center gap-2.5 rounded-xl px-3 py-2 text-sm',
                        'text-text-2 transition-colors hover:bg-surface-2 hover:text-text-1',
                        collapsed && 'justify-center px-0',
                    )}
                >
                    {theme === 'dark' ? (
                        <Sun size={17} className="shrink-0" />
                    ) : (
                        <Moon size={17} className="shrink-0" />
                    )}
                    {!collapsed && <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>}
                </button>

                <UserMenu collapsed={collapsed} />
            </div>
        </nav>
    );
}
