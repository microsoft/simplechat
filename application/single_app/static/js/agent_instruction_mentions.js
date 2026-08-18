// agent_instruction_mentions.js
// Progressive "#" reference autocomplete for the agent modal Instructions step.
//
// Authors reference the actions and assigned knowledge chosen in the earlier
// steps by typing "#". The menu drills down through namespace -> item ->
// capability and inserts a literal token that is saved with the instructions:
//
//   #action:<ActionDisplayName>
//   #action:<ActionDisplayName>:<capability_key>
//   #knowledge:doc:<Document Title>
//   #knowledge:workspace:<Workspace Name>
//   #knowledge:tag:<tag>
//   #knowledge:web:<url>
//
// Values containing whitespace or a colon are wrapped in double quotes so the
// token stays unambiguous, e.g. #knowledge:doc:"Employee Handbook.pdf".
//
// The vendored SimpleMDE 1.11.2 bundle does not ship CodeMirror's show-hint
// addon, so the menu is rendered and positioned here instead.

const MENTION_NAMESPACES = Object.freeze([
    {
        key: 'action',
        label: 'action',
        description: 'Reference an action selected in the Actions step'
    },
    {
        key: 'knowledge',
        label: 'knowledge',
        description: 'Reference an assigned document, workspace, tag, or web source'
    }
]);

const MAX_VISIBLE_MENTION_ITEMS = 10;
// Characters that may sit immediately in front of a "#" for it to start a
// reference. Anything else (a letter, digit, etc.) means the "#" is mid-word.
const MENTION_BOUNDARY_CHARS = Object.freeze(new Set([' ', '\t', '\n', '\r', '(', '[', '{', '>', '"', "'", '`']));
// Cap how far back the trigger scan looks so typing in a long instruction stays
// cheap.
const MENTION_LOOKBEHIND_LIMIT = 500;
// Knowledge items are grouped by type (documents first, since they are the
// common case) and sorted alphabetically inside each group.
const KNOWLEDGE_TYPE_ORDER = Object.freeze(['document', 'workspace', 'tag', 'web']);
// Namespaces whose query may span unquoted spaces, because document titles and
// workspace names routinely contain them.
const SPACE_TOLERANT_NAMESPACES = Object.freeze(new Set(['action', 'knowledge']));

/**
 * Locate the "#" that starts the reference under the caret.
 *
 * This is a single linear reverse scan rather than a regular expression on
 * purpose: a pattern able to describe optional quoted runs is ambiguous, and
 * backtracking over ordinary instruction prose degrades exponentially. The scan
 * is O(n) over a bounded window and runs on every keystroke.
 *
 * @returns {{ body: string, hasUnquotedWhitespace: boolean } | null}
 */
export function locateMentionTrigger(textBeforeCursor) {
    // Keeping one extra character means a truncated window still exposes the
    // real character in front of a "#", so word-boundary checks stay honest.
    const window_ = String(textBeforeCursor ?? '').slice(-(MENTION_LOOKBEHIND_LIMIT + 1));

    for (let index = window_.length - 1; index >= 0; index -= 1) {
        const character = window_[index];

        // A reference never spans lines, so stop at the start of this one.
        if (character === '\n' || character === '\r') {
            return null;
        }

        if (character !== '#') {
            continue;
        }

        const precedingCharacter = index === 0 ? '' : window_[index - 1];
        if (index !== 0 && !MENTION_BOUNDARY_CHARS.has(precedingCharacter)) {
            // The nearest "#" is mid-word, so there is no reference here.
            return null;
        }

        const body = window_.slice(index + 1);
        return { body, hasUnquotedWhitespace: hasUnquotedWhitespace(body) };
    }

    return null;
}

function hasUnquotedWhitespace(text) {
    let inQuotes = false;
    for (const character of String(text ?? '')) {
        if (character === '"') {
            inQuotes = !inQuotes;
            continue;
        }
        if (!inQuotes && /\s/.test(character)) {
            return true;
        }
    }
    return false;
}

/**
 * Split a token body on colons while treating quoted runs as opaque, so a
 * value such as "Q3: Results.pdf" stays in a single segment.
 */
export function splitTokenSegments(raw) {
    const segments = [];
    let current = '';
    let inQuotes = false;

    for (const character of String(raw ?? '')) {
        if (character === '"') {
            inQuotes = !inQuotes;
            current += character;
            continue;
        }
        if (character === ':' && !inQuotes) {
            segments.push(current);
            current = '';
            continue;
        }
        current += character;
    }

    segments.push(current);
    return segments;
}

/**
 * Quote a token value when it contains characters that would make the token
 * boundary ambiguous.
 */
export function formatMentionValue(value) {
    const text = String(value ?? '').trim();
    if (!text) {
        return '';
    }
    if (/[\s:"]/.test(text)) {
        return `"${text.replaceAll('"', "'")}"`;
    }
    return text;
}

export function buildActionToken(actionLabel, capabilityKey = '') {
    const action = formatMentionValue(actionLabel);
    if (!action) {
        return '';
    }
    const capability = formatMentionValue(capabilityKey);
    return capability ? `#action:${action}:${capability}` : `#action:${action}`;
}

export function buildKnowledgeToken(knowledgeType, value) {
    const type = String(knowledgeType || '').trim().toLowerCase();
    const formattedValue = formatMentionValue(value);
    if (!type || !formattedValue) {
        return '';
    }
    return `#knowledge:${type}:${formattedValue}`;
}

function matchesQuery(text, query) {
    const normalizedQuery = String(query ?? '').replaceAll('"', '');
    if (!normalizedQuery) {
        return true;
    }
    return String(text || '').toLowerCase().includes(normalizedQuery.toLowerCase());
}

function compareByLabel(first, second) {
    return String(first.label || '').localeCompare(String(second.label || ''), undefined, { sensitivity: 'base' });
}

/**
 * Thin adapter so the controller can drive a plain textarea and a CodeMirror
 * instance through the same interface.
 */
class TextareaAdapter {
    constructor(textarea) {
        this.textarea = textarea;
        this.mirror = null;
    }

    get element() {
        return this.textarea;
    }

    getTextBeforeCursor() {
        return this.textarea.value.slice(0, this.textarea.selectionStart);
    }

    replaceBeforeCursor(charactersToReplace, replacement) {
        const cursor = this.textarea.selectionStart;
        const start = Math.max(0, cursor - charactersToReplace);
        const value = this.textarea.value;
        this.textarea.value = `${value.slice(0, start)}${replacement}${value.slice(cursor)}`;
        const nextCursor = start + replacement.length;
        this.textarea.setSelectionRange(nextCursor, nextCursor);
        this.textarea.dispatchEvent(new Event('input', { bubbles: true }));
    }

    focus() {
        this.textarea.focus();
    }

    on(eventName, handler) {
        this.textarea.addEventListener(eventName, handler);
    }

    off(eventName, handler) {
        this.textarea.removeEventListener(eventName, handler);
    }

    /**
     * Measure the caret position by mirroring the textarea into a hidden div
     * that shares its typography and padding.
     */
    getCaretViewportCoords() {
        const rect = this.textarea.getBoundingClientRect();
        const computed = window.getComputedStyle(this.textarea);

        if (!this.mirror) {
            this.mirror = document.createElement('div');
            this.mirror.className = 'agent-mention-caret-mirror';
            document.body.appendChild(this.mirror);
        }

        const mirrorStyle = this.mirror.style;
        [
            'fontFamily', 'fontSize', 'fontWeight', 'fontStyle', 'letterSpacing',
            'lineHeight', 'textTransform', 'wordSpacing', 'paddingTop', 'paddingRight',
            'paddingBottom', 'paddingLeft', 'borderTopWidth', 'borderRightWidth',
            'borderBottomWidth', 'borderLeftWidth', 'boxSizing'
        ].forEach(property => {
            mirrorStyle[property] = computed[property];
        });
        mirrorStyle.width = `${this.textarea.clientWidth}px`;

        this.mirror.textContent = this.getTextBeforeCursor();
        const marker = document.createElement('span');
        marker.textContent = '\u200b';
        this.mirror.appendChild(marker);

        const markerRect = marker.getBoundingClientRect();
        const mirrorRect = this.mirror.getBoundingClientRect();

        return {
            left: rect.left + (markerRect.left - mirrorRect.left),
            top: rect.top + (markerRect.top - mirrorRect.top) - this.textarea.scrollTop,
            bottom: rect.top + (markerRect.bottom - mirrorRect.top) - this.textarea.scrollTop
        };
    }

    destroy() {
        if (this.mirror) {
            this.mirror.remove();
            this.mirror = null;
        }
    }

    releaseAttachmentFlag() {
        delete this.textarea.dataset.agentMentionsAttached;
    }
}

class CodeMirrorAdapter {
    constructor(codemirror) {
        this.codemirror = codemirror;
    }

    get element() {
        return this.codemirror.getWrapperElement();
    }

    getTextBeforeCursor() {
        const cursor = this.codemirror.getCursor();
        return this.codemirror.getRange({ line: 0, ch: 0 }, cursor);
    }

    replaceBeforeCursor(charactersToReplace, replacement) {
        const cursor = this.codemirror.getCursor();
        const from = { line: cursor.line, ch: Math.max(0, cursor.ch - charactersToReplace) };
        this.codemirror.replaceRange(replacement, from, cursor);
    }

    focus() {
        this.codemirror.focus();
    }

    on(eventName, handler) {
        this.codemirror.on(eventName, handler);
    }

    off(eventName, handler) {
        this.codemirror.off(eventName, handler);
    }

    getCaretViewportCoords() {
        const coords = this.codemirror.cursorCoords(true, 'window');
        return { left: coords.left, top: coords.top, bottom: coords.bottom };
    }

    destroy() {
        // CodeMirror owns its DOM; nothing extra to clean up here.
    }

    releaseAttachmentFlag() {
        delete this.codemirror.__agentMentionsAttached;
    }
}

export class AgentInstructionMentions {
    /**
     * @param {object} options
     * @param {() => Array} options.getActions Selected actions with capabilities.
     * @param {() => object} options.getKnowledge Assigned knowledge reference.
     * @param {() => void} [options.onBeforeOpen] Hook to refresh source data.
     */
    constructor(options = {}) {
        this.getActions = typeof options.getActions === 'function' ? options.getActions : () => [];
        this.getKnowledge = typeof options.getKnowledge === 'function' ? options.getKnowledge : () => ({});
        this.onBeforeOpen = typeof options.onBeforeOpen === 'function' ? options.onBeforeOpen : null;

        this.menu = null;
        this.listElement = null;
        this.emptyElement = null;
        this.items = [];
        this.activeIndex = 0;
        this.activeAdapter = null;
        this.triggerLength = 0;
        this.attachments = [];

        this.handleDocumentPointerDown = this.handleDocumentPointerDown.bind(this);
        this.handleWindowResize = this.handleWindowResize.bind(this);
    }

    attachTextarea(textarea) {
        if (!textarea || textarea.dataset.agentMentionsAttached === 'true') {
            return;
        }
        textarea.dataset.agentMentionsAttached = 'true';
        this.attachAdapter(new TextareaAdapter(textarea), 'keydown', [
            // Text actually changed, so a reference may be starting.
            { name: 'input', allowOpen: true },
            // Caret moved without editing: only re-evaluate an open menu.
            { name: 'keyup', allowOpen: false },
            { name: 'click', allowOpen: false }
        ]);
    }

    attachCodeMirror(codemirror) {
        if (!codemirror || codemirror.__agentMentionsAttached) {
            return;
        }
        codemirror.__agentMentionsAttached = true;
        this.attachAdapter(new CodeMirrorAdapter(codemirror), 'keydown', [
            // "changes" covers typing and deleting; "inputRead" alone would
            // miss backspacing through a reference.
            { name: 'changes', allowOpen: true },
            { name: 'cursorActivity', allowOpen: false }
        ]);
    }

    attachAdapter(adapter, keydownEvent, inputEvents) {
        const onKeydown = (first, second) => {
            // CodeMirror passes (instance, event); a textarea passes (event).
            const event = second || first;
            this.handleKeydown(adapter, event);
        };
        const onBlur = () => {
            window.setTimeout(() => {
                if (this.activeAdapter === adapter && !this.isPointerInsideMenu) {
                    this.close();
                }
            }, 150);
        };

        adapter.on(keydownEvent, onKeydown);
        adapter.on('blur', onBlur);

        const inputHandlers = inputEvents.map(({ name, allowOpen }) => {
            const handler = () => {
                window.setTimeout(() => this.handleInput(adapter, { allowOpen }), 0);
            };
            adapter.on(name, handler);
            return { name, handler };
        });

        this.attachments.push({ adapter, keydownEvent, onKeydown, onBlur, inputHandlers });
    }

    ensureMenu() {
        if (this.menu) {
            return this.menu;
        }

        const menu = document.createElement('div');
        menu.className = 'agent-mention-menu d-none';
        menu.setAttribute('role', 'listbox');
        menu.setAttribute('aria-label', 'Insert agent reference');

        const header = document.createElement('div');
        header.className = 'agent-mention-menu-header';
        header.id = 'agent-mention-menu-header';
        menu.appendChild(header);

        const list = document.createElement('div');
        list.className = 'agent-mention-menu-list';
        menu.appendChild(list);

        const empty = document.createElement('div');
        empty.className = 'agent-mention-menu-empty d-none';
        menu.appendChild(empty);

        menu.addEventListener('mouseenter', () => {
            this.isPointerInsideMenu = true;
        });
        menu.addEventListener('mouseleave', () => {
            this.isPointerInsideMenu = false;
        });
        menu.addEventListener('mousedown', event => {
            // Keep focus in the editor so the insertion point survives the click.
            event.preventDefault();
        });

        document.body.appendChild(menu);
        this.menu = menu;
        this.headerElement = header;
        this.listElement = list;
        this.emptyElement = empty;
        return menu;
    }

    get isOpen() {
        return Boolean(this.menu) && !this.menu.classList.contains('d-none');
    }

    /**
     * Parse the text immediately before the caret into a menu request.
     * Returns null when the caret is not inside a "#" reference.
     */
    parseTrigger(textBeforeCursor) {
        const located = locateMentionTrigger(textBeforeCursor);
        if (!located) {
            return null;
        }

        const segments = splitTokenSegments(located.body);

        if (located.hasUnquotedWhitespace) {
            // Only a typed namespace may span spaces, and such a match is only
            // trusted while it still resolves to at least one item.
            if (segments.length === 1) {
                return null;
            }
            if (!SPACE_TOLERANT_NAMESPACES.has(segments[0].trim().toLowerCase())) {
                return null;
            }
        }

        return this.parseTriggerBody(located.body, segments, located.hasUnquotedWhitespace);
    }

    parseTriggerBody(raw, segments, allowsSpaces) {
        const triggerLength = raw.length + 1;

        if (segments.length === 1) {
            return { level: 'namespace', query: raw, triggerLength, allowsSpaces };
        }

        const [namespace, ...rest] = segments;
        const normalizedNamespace = namespace.trim().toLowerCase();

        if (normalizedNamespace === 'knowledge') {
            // Only the first segment after the namespace is a filter; once a
            // type prefix is present the token is already complete.
            if (rest.length > 1) {
                return null;
            }
            return { level: 'knowledge', query: rest[0] || '', triggerLength, allowsSpaces };
        }

        if (normalizedNamespace === 'action') {
            if (rest.length === 1) {
                return { level: 'action', query: rest[0] || '', triggerLength, allowsSpaces };
            }
            if (rest.length === 2) {
                return {
                    level: 'capability',
                    actionLabel: rest[0] || '',
                    query: rest[1] || '',
                    triggerLength,
                    allowsSpaces
                };
            }
            return null;
        }

        return null;
    }

    buildNamespaceItems(query) {
        return MENTION_NAMESPACES
            .filter(namespace => matchesQuery(namespace.label, query))
            .map(namespace => ({
                label: namespace.label,
                detail: namespace.description,
                badge: '',
                token: `#${namespace.key}:`,
                keepOpen: true
            }));
    }

    buildActionItems(query) {
        return (this.getActions() || [])
            .map(action => {
                const label = String(action.display_name || action.name || '').trim();
                return {
                    label,
                    detail: String(action.description || '').trim(),
                    badge: String(action.type || '').trim(),
                    hasCapabilities: Array.isArray(action.capabilities) && action.capabilities.length > 0,
                    token: buildActionToken(label)
                };
            })
            .filter(item => item.label && matchesQuery(item.label, query))
            .sort(compareByLabel)
            .map(item => (item.hasCapabilities
                ? { ...item, token: `#action:${formatMentionValue(item.label)}:`, keepOpen: true }
                : item));
    }

    buildCapabilityItems(actionLabel, query) {
        const normalizedLabel = String(actionLabel || '').replaceAll('"', '').trim().toLowerCase();
        const action = (this.getActions() || []).find(candidate => {
            const label = String(candidate.display_name || candidate.name || '').trim().toLowerCase();
            return label === normalizedLabel;
        });

        if (!action) {
            return [];
        }

        return (action.capabilities || [])
            .filter(capability => matchesQuery(capability.key, query) || matchesQuery(capability.label, query))
            .map(capability => ({
                label: capability.key,
                detail: capability.label,
                badge: 'capability',
                token: buildActionToken(action.display_name || action.name, capability.key)
            }));
    }

    buildKnowledgeItems(query) {
        const knowledge = this.getKnowledge() || {};
        if (!knowledge.enabled) {
            return [];
        }

        const items = [];

        (knowledge.documents || []).forEach(document_ => {
            const label = String(document_.title || document_.file_name || '').trim();
            if (!label) {
                return;
            }
            items.push({
                label,
                detail: String(document_.source_name || '').trim(),
                badge: 'document',
                token: buildKnowledgeToken('doc', label)
            });
        });

        (knowledge.sources || []).forEach(source => {
            const label = String(source.name || '').trim();
            if (!label) {
                return;
            }
            items.push({
                label,
                detail: `${source.scope || ''} workspace`.trim(),
                badge: 'workspace',
                token: buildKnowledgeToken('workspace', label)
            });
        });

        (knowledge.tags || []).forEach(tag => {
            const label = String(tag || '').trim();
            if (!label) {
                return;
            }
            items.push({
                label,
                detail: 'Tag limit',
                badge: 'tag',
                token: buildKnowledgeToken('tag', label)
            });
        });

        (knowledge.web_sources || []).forEach(webSource => {
            const label = String(webSource.url || '').trim();
            if (!label) {
                return;
            }
            items.push({
                label,
                detail: String(webSource.mode_label || '').trim(),
                badge: 'web',
                token: buildKnowledgeToken('web', label)
            });
        });

        return items
            .filter(item => matchesQuery(item.label, query) || matchesQuery(item.badge, query))
            .sort((first, second) => {
                const typeDelta = KNOWLEDGE_TYPE_ORDER.indexOf(first.badge) - KNOWLEDGE_TYPE_ORDER.indexOf(second.badge);
                return typeDelta !== 0 ? typeDelta : compareByLabel(first, second);
            });
    }

    buildItems(trigger) {
        switch (trigger.level) {
            case 'namespace':
                return this.buildNamespaceItems(trigger.query);
            case 'action':
                return this.buildActionItems(trigger.query);
            case 'capability':
                return this.buildCapabilityItems(trigger.actionLabel, trigger.query);
            case 'knowledge':
                return this.buildKnowledgeItems(trigger.query);
            default:
                return [];
        }
    }

    getEmptyMessage(level) {
        switch (level) {
            case 'action':
                return 'No actions were selected in the Actions step.';
            case 'capability':
                return 'This action has no enabled capabilities.';
            case 'knowledge':
                return 'No assigned knowledge was selected in the Knowledge step.';
            default:
                return 'No matching references.';
        }
    }

    getHeaderText(level) {
        switch (level) {
            case 'action':
                return 'Selected actions';
            case 'capability':
                return 'Enabled capabilities';
            case 'knowledge':
                return 'Assigned knowledge';
            default:
                return 'Reference';
        }
    }

    handleInput(adapter, { allowOpen = true } = {}) {
        const isOpenForAdapter = this.isOpen && this.activeAdapter === adapter;
        // Caret-only events may re-evaluate or close an open menu, but must
        // never pop one open over text the author wrote earlier.
        if (!allowOpen && !isOpenForAdapter) {
            return;
        }

        const trigger = this.parseTrigger(adapter.getTextBeforeCursor());
        if (!trigger) {
            if (this.activeAdapter === adapter) {
                this.close();
            }
            return;
        }

        if (this.onBeforeOpen) {
            this.onBeforeOpen();
        }

        const items = this.buildItems(trigger);
        // A space-spanning query is only a reference for as long as it still
        // resolves; otherwise the author is just writing prose after a token.
        if (trigger.allowsSpaces && !items.length) {
            if (this.activeAdapter === adapter) {
                this.close();
            }
            return;
        }

        this.activeAdapter = adapter;
        this.triggerLength = trigger.triggerLength;
        this.render(trigger, items);
    }

    render(trigger, items) {
        const menu = this.ensureMenu();
        const visibleItems = items.slice(0, MAX_VISIBLE_MENTION_ITEMS);
        this.items = visibleItems;
        this.activeIndex = 0;

        this.headerElement.textContent = this.getHeaderText(trigger.level);
        this.listElement.textContent = '';

        if (!visibleItems.length) {
            this.emptyElement.textContent = this.getEmptyMessage(trigger.level);
            this.emptyElement.classList.remove('d-none');
        } else {
            this.emptyElement.classList.add('d-none');
            visibleItems.forEach((item, index) => {
                this.listElement.appendChild(this.createItemElement(item, index));
            });
            if (items.length > visibleItems.length) {
                const overflow = document.createElement('div');
                overflow.className = 'agent-mention-menu-overflow';
                overflow.textContent = `${items.length - visibleItems.length} more — keep typing to filter`;
                this.listElement.appendChild(overflow);
            }
        }

        menu.classList.remove('d-none');
        this.updateActiveItem();
        this.position();

        document.addEventListener('mousedown', this.handleDocumentPointerDown);
        window.addEventListener('resize', this.handleWindowResize);
    }

    createItemElement(item, index) {
        const row = document.createElement('div');
        row.className = 'agent-mention-menu-item';
        row.id = `agent-mention-option-${index}`;
        row.setAttribute('role', 'option');
        row.setAttribute('aria-selected', 'false');

        const main = document.createElement('div');
        main.className = 'agent-mention-menu-item-main';

        const label = document.createElement('span');
        label.className = 'agent-mention-menu-item-label';
        label.textContent = item.label;
        main.appendChild(label);

        if (item.badge) {
            const badge = document.createElement('span');
            badge.className = 'badge text-bg-secondary agent-mention-menu-item-badge';
            badge.textContent = item.badge;
            main.appendChild(badge);
        }

        if (item.keepOpen) {
            const chevron = document.createElement('i');
            chevron.className = 'bi bi-chevron-right agent-mention-menu-item-chevron';
            chevron.setAttribute('aria-hidden', 'true');
            main.appendChild(chevron);
        }

        row.appendChild(main);

        if (item.detail) {
            const detail = document.createElement('div');
            detail.className = 'agent-mention-menu-item-detail';
            detail.textContent = item.detail;
            row.appendChild(detail);
        }

        row.addEventListener('mousemove', () => {
            if (this.activeIndex !== index) {
                this.activeIndex = index;
                this.updateActiveItem();
            }
        });
        row.addEventListener('click', () => this.select(index));

        return row;
    }

    updateActiveItem() {
        const rows = Array.from(this.listElement.querySelectorAll('.agent-mention-menu-item'));
        rows.forEach((row, index) => {
            const isActive = index === this.activeIndex;
            row.classList.toggle('active', isActive);
            row.setAttribute('aria-selected', isActive ? 'true' : 'false');
            if (isActive) {
                this.menu.setAttribute('aria-activedescendant', row.id);
                row.scrollIntoView?.({ block: 'nearest' });
            }
        });
    }

    position() {
        if (!this.activeAdapter || !this.menu) {
            return;
        }

        const coords = this.activeAdapter.getCaretViewportCoords();
        const menuRect = this.menu.getBoundingClientRect();
        const margin = 8;

        let left = coords.left;
        if (left + menuRect.width + margin > window.innerWidth) {
            left = Math.max(margin, window.innerWidth - menuRect.width - margin);
        }

        let top = coords.bottom + 4;
        if (top + menuRect.height + margin > window.innerHeight) {
            const above = coords.top - menuRect.height - 4;
            top = above >= margin ? above : Math.max(margin, window.innerHeight - menuRect.height - margin);
        }

        this.menu.style.left = `${Math.max(margin, left)}px`;
        this.menu.style.top = `${top}px`;
    }

    select(index) {
        const item = this.items[index];
        if (!item || !this.activeAdapter || !item.token) {
            return;
        }

        const adapter = this.activeAdapter;
        const replacement = item.keepOpen ? item.token : `${item.token} `;
        adapter.replaceBeforeCursor(this.triggerLength, replacement);
        adapter.focus();

        if (item.keepOpen) {
            // Advance to the next level immediately so the menu does not blink
            // between the namespace, action, and capability lists.
            this.triggerLength = item.token.length;
            this.handleInput(adapter, { allowOpen: true });
            return;
        }

        this.close();
    }

    handleKeydown(adapter, event) {
        if (!this.isOpen || this.activeAdapter !== adapter || !event) {
            return;
        }

        switch (event.key) {
            case 'ArrowDown':
                event.preventDefault();
                if (this.items.length) {
                    this.activeIndex = (this.activeIndex + 1) % this.items.length;
                    this.updateActiveItem();
                }
                break;
            case 'ArrowUp':
                event.preventDefault();
                if (this.items.length) {
                    this.activeIndex = (this.activeIndex - 1 + this.items.length) % this.items.length;
                    this.updateActiveItem();
                }
                break;
            case 'Tab':
            case 'Enter':
                if (this.items.length) {
                    event.preventDefault();
                    if (typeof event.stopPropagation === 'function') {
                        event.stopPropagation();
                    }
                    this.select(this.activeIndex);
                }
                break;
            case 'Escape':
                event.preventDefault();
                this.close();
                break;
            default:
                break;
        }
    }

    handleDocumentPointerDown(event) {
        if (this.menu && !this.menu.contains(event.target)) {
            this.close();
        }
    }

    handleWindowResize() {
        if (this.isOpen) {
            this.position();
        }
    }

    close() {
        if (this.menu) {
            this.menu.classList.add('d-none');
            this.menu.removeAttribute('aria-activedescendant');
        }
        this.items = [];
        this.activeIndex = 0;
        this.activeAdapter = null;
        this.isPointerInsideMenu = false;
        document.removeEventListener('mousedown', this.handleDocumentPointerDown);
        window.removeEventListener('resize', this.handleWindowResize);
    }

    destroy() {
        this.close();
        this.attachments.forEach(({ adapter, keydownEvent, onKeydown, onBlur, inputHandlers }) => {
            adapter.off(keydownEvent, onKeydown);
            adapter.off('blur', onBlur);
            inputHandlers.forEach(({ name, handler }) => adapter.off(name, handler));
            adapter.releaseAttachmentFlag();
            adapter.destroy();
        });
        this.attachments = [];
        if (this.menu) {
            this.menu.remove();
            this.menu = null;
        }
    }
}

export const MENTION_MENU_MAX_VISIBLE_ITEMS = MAX_VISIBLE_MENTION_ITEMS;
export const AGENT_MENTION_NAMESPACES = MENTION_NAMESPACES;
