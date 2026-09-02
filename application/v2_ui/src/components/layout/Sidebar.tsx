// Sidebar.tsx
// The single navigation surface. SimpleChat V2 has no top bar by design: brand, primary
// navigation, workspace scopes, theme control and the user menu all live in this rail,
// which collapses to an icon strip.

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
    User,
    Users,
} from 'lucide-react';
import { useUiStore } from '../../stores/uiStore';
import { useBootstrapStore } from '../../stores/bootstrapStore';
import { useChatStore } from '../../stores/chatStore';
import { ConversationRail } from '../chat/ConversationRail';

interface NavItem {
    to: string;
    label: string;
    icon: typeof MessagesSquare;
    adminOnly?: boolean;
}

const NAV_ITEMS: NavItem[] = [
    { to: '/chat', label: 'Chats', icon: MessagesSquare },
    { to: '/agents', label: 'Agents', icon: Sparkles },
    { to: '/workspace', label: 'My Workspace', icon: FolderOpen },
    { to: '/groups', label: 'Group Workspaces', icon: Users },
    { to: '/public', label: 'Public Workspaces', icon: Globe2 },
    { to: '/admin', label: 'Admin Settings', icon: Settings, adminOnly: true },
];

function BrandMark({ collapsed }: { collapsed: boolean }) {
    const branding = useBootstrapStore((state) => state.data?.branding);
    const theme = useUiStore((state) => state.theme);

    const logoUrl = theme === 'dark' ? branding?.logo_dark_url : branding?.logo_url;
    const title = branding?.app_title || 'SimpleChat';

    return (
        <div className="flex min-w-0 items-center gap-2.5">
            {branding?.show_logo && logoUrl ? (
                <img
                    src={logoUrl}
                    alt=""
                    className="h-8 w-8 shrink-0 rounded-lg object-contain"
                />
            ) : (
                <span
                    aria-hidden="true"
                    className="flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-accent text-sm font-bold text-on-accent"
                >
                    {title.slice(0, 1).toUpperCase()}
                </span>
            )}
            {!collapsed && !branding?.hide_app_title && (
                <span className="truncate text-[15px] font-semibold text-text-1" title={title}>
                    {title}
                </span>
            )}
        </div>
    );
}

function UserMenu({ collapsed }: { collapsed: boolean }) {
    const user = useBootstrapStore((state) => state.data?.user);
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
                    <a
                        href="/profile"
                        className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-text-1 hover:bg-surface-2"
                    >
                        <User size={15} /> Profile
                    </a>
                    <a
                        href="/chats"
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

            <ul className="mt-3 space-y-0.5 px-3">
                {NAV_ITEMS.filter((item) => !item.adminOnly || isAdmin).map((item) => (
                    <li key={item.to}>
                        <NavLink
                            to={item.to}
                            title={collapsed ? item.label : undefined}
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
