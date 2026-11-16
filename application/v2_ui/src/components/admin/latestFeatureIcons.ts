// latestFeatureIcons.ts
// Resolve the Bootstrap icon names in the Latest Features catalogues to local Lucide icons.
//
// The catalogues in `support_menu_config.py` name an icon per announcement and per
// shortcut, as the classic page draws them. Names the admin navigation already uses are
// read from that table, so the two cannot translate one name two ways; the rest are
// listed here. An unknown name draws a neutral sparkle rather than nothing, because a new
// catalogue entry should never render a gap.

import {
    BookMarked,
    Book,
    Boxes,
    Building2,
    Calculator,
    ChartColumn,
    ChartColumnIncreasing,
    CircleArrowDown,
    CircleArrowRight,
    CircleStop,
    ClipboardList,
    CloudUpload,
    Contact,
    DatabaseBackup,
    FileAudio,
    FileDown,
    FileJson,
    FileText,
    Filter,
    FolderOpen,
    Gauge,
    Grid3x3,
    LayoutGrid,
    Library,
    LogIn,
    MessageCircleMore,
    MessageSquareQuote,
    MessageSquareText,
    Network,
    PanelLeft,
    Plug,
    RadioTower,
    SearchCheck,
    Server,
    ServerCog,
    Settings,
    Sparkles,
    SquareUser,
    Trash2,
    Type,
    VenetianMask,
    Wifi,
    type LucideIcon,
} from 'lucide-react';
import { ADMIN_NAV_ICONS } from './adminSectionIcons';

/** Catalogue icon names the admin navigation does not use. */
const LATEST_FEATURE_ICONS: Readonly<Record<string, LucideIcon>> = {
    'bi-arrow-down-circle': CircleArrowDown,
    'bi-arrow-right-circle': CircleArrowRight,
    'bi-bar-chart': ChartColumn,
    'bi-bar-chart-line': ChartColumnIncreasing,
    'bi-book': Book,
    'bi-box-arrow-in-right': LogIn,
    'bi-boxes': Boxes,
    'bi-broadcast': RadioTower,
    'bi-building': Building2,
    'bi-calculator': Calculator,
    'bi-card-list': ClipboardList,
    'bi-chat-dots': MessageCircleMore,
    'bi-chat-left-text': MessageSquareText,
    'bi-chat-quote': MessageSquareQuote,
    'bi-cloud-upload': CloudUpload,
    'bi-database-check': DatabaseBackup,
    'bi-database-gear': ServerCog,
    'bi-diagram-2': Network,
    'bi-file-earmark-arrow-down': FileDown,
    'bi-file-earmark-music': FileAudio,
    'bi-file-richtext': FileText,
    'bi-filetype-json': FileJson,
    'bi-folder2-open': FolderOpen,
    'bi-fonts': Type,
    'bi-funnel': Filter,
    'bi-gear': Settings,
    'bi-grid': LayoutGrid,
    'bi-grid-3x3-gap': Grid3x3,
    'bi-hdd-rack': Server,
    'bi-journal-bookmark': BookMarked,
    'bi-journals': Library,
    'bi-layout-text-sidebar': PanelLeft,
    'bi-mask': VenetianMask,
    'bi-person-lines-fill': Contact,
    'bi-person-square': SquareUser,
    'bi-plug': Plug,
    'bi-search-heart': SearchCheck,
    'bi-speedometer': Gauge,
    'bi-stop-circle': CircleStop,
    'bi-trash3': Trash2,
    'bi-wifi': Wifi,
    'bi-window-sidebar': PanelLeft,
};

/** Drawn for an announcement or shortcut whose icon name is not translated. */
export const FALLBACK_LATEST_FEATURE_ICON: LucideIcon = Sparkles;

export function resolveLatestFeatureIcon(name: string | undefined): LucideIcon {
    if (!name) {
        return FALLBACK_LATEST_FEATURE_ICON;
    }
    return ADMIN_NAV_ICONS[name] ?? LATEST_FEATURE_ICONS[name] ?? FALLBACK_LATEST_FEATURE_ICON;
}
