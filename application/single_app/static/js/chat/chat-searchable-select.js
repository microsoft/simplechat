// chat-searchable-select.js

const SEARCH_ROLE_ACTION = 'action';
const SEARCH_SEPARATOR_PATTERN = /[_\-.]+/g;
const SEARCH_WHITESPACE_PATTERN = /\s+/g;

export function normalizeSearchText(value) {
    return String(value ?? '')
        .toLowerCase()
        .replace(SEARCH_SEPARATOR_PATTERN, ' ')
        .replace(SEARCH_WHITESPACE_PATTERN, ' ')
        .trim();
}

export function matchesSearchTokens(searchText, searchTerm) {
    const normalizedTerm = normalizeSearchText(searchTerm);

    if (!normalizedTerm) {
        return true;
    }

    const normalizedText = normalizeSearchText(searchText);
    return normalizedTerm.split(' ').every(token => normalizedText.includes(token));
}

function createNoMatchesElement(message) {
    const noMatchesEl = document.createElement('div');
    noMatchesEl.className = 'no-matches text-center text-muted py-2';
    noMatchesEl.textContent = message;
    return noMatchesEl;
}

function removeNoMatchesElement(itemsContainerEl) {
    const noMatchesEl = itemsContainerEl.querySelector('.no-matches');
    if (noMatchesEl) {
        noMatchesEl.remove();
    }
}

function isHiddenElement(el) {
    return Boolean(el && el.classList.contains('d-none'));
}

function isDividerElement(el) {
    return Boolean(el && el.classList.contains('dropdown-divider'));
}

function isHeaderElement(el) {
    return Boolean(el && el.classList.contains('dropdown-header'));
}

function isVisibleItem(el) {
    return Boolean(el && !isHiddenElement(el) && !isDividerElement(el));
}

// Section content is what a divider is allowed to separate. Always-visible action rows
// are excluded so an orphaned divider cannot anchor itself to the "Select All" row.
function isVisibleSectionContent(el) {
    if (!el || isHiddenElement(el) || isDividerElement(el)) {
        return false;
    }

    if (isHeaderElement(el)) {
        return true;
    }

    return el.classList.contains('dropdown-item')
        && el.getAttribute('data-search-role') !== SEARCH_ROLE_ACTION;
}

// A divider is "bound" when it introduces a section header, so its visibility follows
// that header instead of whatever unrelated row happens to still be visible above it.
function findDividerBoundHeader(children, dividerIndex) {
    for (let index = dividerIndex + 1; index < children.length; index += 1) {
        const candidate = children[index];

        if (isDividerElement(candidate)) {
            continue;
        }

        return isHeaderElement(candidate) ? candidate : null;
    }

    return null;
}

function collapseRedundantDividers(children) {
    let sawVisibleContent = false;

    children.forEach(child => {
        if (isDividerElement(child)) {
            if (isHiddenElement(child)) {
                return;
            }

            if (!sawVisibleContent) {
                child.classList.add('d-none');
                return;
            }

            sawVisibleContent = false;
            return;
        }

        if (!isHiddenElement(child)) {
            sawVisibleContent = true;
        }
    });

    for (let index = children.length - 1; index >= 0; index -= 1) {
        const child = children[index];

        if (isHiddenElement(child)) {
            continue;
        }

        if (!isDividerElement(child)) {
            break;
        }

        child.classList.add('d-none');
    }
}

function updateDropdownStructure(itemsContainerEl) {
    if (!itemsContainerEl) {
        return;
    }

    const children = Array.from(itemsContainerEl.children).filter(child => !child.classList.contains('no-matches'));

    children.forEach(child => {
        if (!isHeaderElement(child)) {
            return;
        }

        let hasVisibleItem = false;
        let next = child.nextElementSibling;

        while (next && !isHeaderElement(next)) {
            if (next.classList.contains('dropdown-item') && isVisibleItem(next)) {
                hasVisibleItem = true;
                break;
            }
            next = next.nextElementSibling;
        }

        child.classList.toggle('d-none', !hasVisibleItem);
    });

    children.forEach((child, index) => {
        if (!isDividerElement(child)) {
            return;
        }

        const boundHeader = findDividerBoundHeader(children, index);
        const hasSectionContentBefore = children.slice(0, index).some(sibling => isVisibleSectionContent(sibling));
        let keepDivider;

        if (boundHeader) {
            keepDivider = !isHiddenElement(boundHeader) && hasSectionContentBefore;
        } else {
            const hasVisibleContentBefore = children.slice(0, index).some(sibling => isVisibleItem(sibling));
            const hasSectionContentAfter = children.slice(index + 1).some(sibling => isVisibleSectionContent(sibling));
            keepDivider = hasVisibleContentBefore && hasSectionContentAfter;
        }

        child.classList.toggle('d-none', !keepDivider);
    });

    collapseRedundantDividers(children);
}

function createDropdownHeader(label) {
    const header = document.createElement('div');
    header.classList.add('dropdown-header', 'small', 'text-muted', 'px-2', 'pt-2', 'pb-1');
    header.textContent = label;
    return header;
}

function createDropdownDivider() {
    const divider = document.createElement('div');
    divider.classList.add('dropdown-divider');
    return divider;
}

export function createFloatingSearchableSelectDropdownConfig({
    viewportPadding = 12,
    maxWidth = 360,
} = {}) {
    const matchReferenceWidthModifier = {
        name: 'matchReferenceWidth',
        enabled: true,
        phase: 'beforeWrite',
        requires: ['computeStyles'],
        fn({ state }) {
            const referenceWidth = Math.ceil(state.rects.reference.width || 0);
            const viewportWidth = Math.max(0, window.innerWidth - (viewportPadding * 2));
            const maxMenuWidth = Math.max(0, Math.min(maxWidth, viewportWidth));
            const menuMinWidth = Math.min(referenceWidth, maxMenuWidth);

            state.styles.popper.minWidth = `${menuMinWidth}px`;
            state.styles.popper.maxWidth = `${maxMenuWidth}px`;
        },
    };

    return {
        boundary: 'viewport',
        reference: 'toggle',
        autoClose: 'outside',
        popperConfig: defaultConfig => {
            const baseModifiers = Array.isArray(defaultConfig.modifiers)
                ? defaultConfig.modifiers.filter(modifier => !['preventOverflow', 'matchReferenceWidth'].includes(modifier.name))
                : [];

            return {
                ...defaultConfig,
                strategy: 'fixed',
                modifiers: [
                    ...baseModifiers,
                    matchReferenceWidthModifier,
                    {
                        name: 'preventOverflow',
                        options: {
                            boundary: 'viewport',
                            padding: viewportPadding,
                            rootBoundary: 'viewport',
                        },
                    },
                ],
            };
        },
    };
}

export function initializeFilterableDropdownSearch({
    dropdownEl,
    buttonEl,
    menuEl,
    searchInputEl,
    itemsContainerEl,
    emptyMessage,
    getItemSearchText,
    isAlwaysVisibleItem,
    itemSelector = '.dropdown-item',
    clearSearchOnHide = true,
    onFilterApplied,
}) {
    if (!menuEl || !searchInputEl || !itemsContainerEl) {
        return null;
    }

    const readSearchText = getItemSearchText || (item => item.dataset.searchLabel || item.textContent || '');
    const isAlwaysVisible = isAlwaysVisibleItem || (() => false);

    const applyFilter = (rawSearchTerm = '') => {
        const searchTerm = normalizeSearchText(rawSearchTerm);
        const items = Array.from(itemsContainerEl.querySelectorAll(itemSelector));
        let visibleMatchCount = 0;

        items.forEach(item => {
            const keepVisible = isAlwaysVisible(item);
            const matches = keepVisible || matchesSearchTokens(readSearchText(item), searchTerm);

            item.classList.toggle('d-none', !matches);

            if (matches && !keepVisible) {
                visibleMatchCount += 1;
            }
        });

        removeNoMatchesElement(itemsContainerEl);
        updateDropdownStructure(itemsContainerEl);

        if (searchTerm && visibleMatchCount === 0) {
            itemsContainerEl.appendChild(createNoMatchesElement(emptyMessage));
        }

        onFilterApplied?.({ searchTerm, visibleMatchCount });
    };

    const resetFilter = () => {
        searchInputEl.value = '';
        applyFilter('');
    };

    menuEl.addEventListener('click', event => {
        event.stopPropagation();
    });

    menuEl.addEventListener('keydown', event => {
        event.stopPropagation();
    });

    searchInputEl.addEventListener('click', event => {
        event.stopPropagation();
    });

    searchInputEl.addEventListener('keydown', event => {
        event.stopPropagation();
    });

    searchInputEl.addEventListener('input', () => {
        applyFilter(searchInputEl.value);
    });

    if (dropdownEl) {
        dropdownEl.addEventListener('shown.bs.dropdown', () => {
            searchInputEl.focus();
            searchInputEl.select();
        });

        if (clearSearchOnHide) {
            dropdownEl.addEventListener('hidden.bs.dropdown', () => {
                resetFilter();
            });
        }
    }

    if (buttonEl) {
        try {
            bootstrap.Dropdown.getOrCreateInstance(buttonEl, {
                autoClose: 'outside'
            });
        } catch (error) {
            console.error('Error initializing dropdown search helper:', error);
        }
    }

    applyFilter('');

    return {
        applyFilter,
        resetFilter,
    };
}

export function createSearchableSingleSelect({
    selectEl,
    dropdownEl,
    buttonEl,
    buttonTextEl,
    menuEl,
    searchInputEl,
    itemsContainerEl,
    placeholderText,
    emptyMessage,
    emptySearchMessage,
    getOptionLabel,
    getOptionSearchText,
    renderOptionContent,
    dropdownConfig,
}) {
    if (!selectEl || !dropdownEl || !buttonEl || !buttonTextEl || !menuEl || !searchInputEl || !itemsContainerEl) {
        return null;
    }

    const readOptionLabel = getOptionLabel || (option => option.textContent.trim());
    const readOptionSearchText = getOptionSearchText || (option => option.textContent.trim());
    const renderOption = typeof renderOptionContent === 'function' ? renderOptionContent : null;
    const resolvedDropdownConfig = dropdownConfig || {
        autoClose: 'outside',
    };

    const getTopLevelEntries = () => Array.from(selectEl.children).filter(child => {
        const tagName = child.tagName;
        return tagName === 'OPTION' || tagName === 'OPTGROUP';
    });

    const getSelectedOption = () => {
        if (selectEl.selectedIndex < 0) {
            return null;
        }

        return selectEl.options[selectEl.selectedIndex] || null;
    };

    const syncButtonText = () => {
        const selectedOption = getSelectedOption();
        const label = selectedOption ? readOptionLabel(selectedOption) : '';
        buttonTextEl.textContent = label || placeholderText;
    };

    const renderOptions = () => {
        const searchTerm = normalizeSearchText(searchInputEl.value);
        const options = Array.from(selectEl.options);
        const optionIndexMap = new Map(options.map((option, index) => [option, index]));
        const selectedIndex = selectEl.selectedIndex;
        const hasEnabledOption = options.some(option => !option.disabled);

        itemsContainerEl.innerHTML = '';

        if (!options.length) {
            buttonEl.disabled = true;
            searchInputEl.disabled = true;
            buttonTextEl.textContent = emptyMessage;
            itemsContainerEl.appendChild(createNoMatchesElement(emptyMessage));
            return;
        }

        let matchedCount = 0;

        const appendOptionItem = option => {
            const index = optionIndexMap.get(option);
            const optionLabel = readOptionLabel(option);
            const optionSearchText = String(readOptionSearchText(option) || optionLabel).toLowerCase();
            const matches = matchesSearchTokens(optionSearchText, searchTerm);

            const item = document.createElement('button');
            item.type = 'button';
            item.classList.add('dropdown-item', 'chat-searchable-select-item');
            item.dataset.optionIndex = String(index);
            item.dataset.optionValue = option.value;
            item.dataset.searchLabel = optionSearchText;
            item.title = optionLabel;

            if (!matches) {
                item.classList.add('d-none');
            } else {
                matchedCount += 1;
            }

            if (index === selectedIndex) {
                item.classList.add('active');
            }

            if (option.disabled) {
                item.classList.add('disabled');
                item.disabled = true;
            }

            if (renderOption) {
                const renderedContent = renderOption(option, optionLabel);
                if (renderedContent instanceof Node) {
                    item.appendChild(renderedContent);
                }
            }

            if (!item.childNodes.length) {
                const textEl = document.createElement('span');
                textEl.className = 'chat-searchable-select-item-text';
                textEl.textContent = optionLabel;
                item.appendChild(textEl);
            }

            itemsContainerEl.appendChild(item);
        };

        let renderedGroupCount = 0;
        getTopLevelEntries().forEach(entry => {
            if (entry.tagName === 'OPTGROUP') {
                const groupOptions = Array.from(entry.children).filter(child => child.tagName === 'OPTION');
                if (!groupOptions.length) {
                    return;
                }

                if (itemsContainerEl.children.length > 0) {
                    itemsContainerEl.appendChild(createDropdownDivider());
                }

                itemsContainerEl.appendChild(createDropdownHeader(entry.label || ''));
                groupOptions.forEach(option => {
                    appendOptionItem(option);
                });
                renderedGroupCount += 1;
                return;
            }

            appendOptionItem(entry);
        });

        buttonEl.disabled = !hasEnabledOption;
        searchInputEl.disabled = !hasEnabledOption;
        syncButtonText();

        if (renderedGroupCount > 0) {
            updateDropdownStructure(itemsContainerEl);
        }

        if (matchedCount === 0) {
            itemsContainerEl.appendChild(createNoMatchesElement(searchTerm ? emptySearchMessage : emptyMessage));
        }
    };

    const syncFromSelect = () => {
        renderOptions();
    };

    const selectOption = optionIndex => {
        const normalizedIndex = Number(optionIndex);
        const option = selectEl.options[normalizedIndex];

        if (!option || option.disabled) {
            return;
        }

        selectEl.selectedIndex = normalizedIndex;
        renderOptions();
        selectEl.dispatchEvent(new Event('change', { bubbles: true }));

        try {
            bootstrap.Dropdown.getOrCreateInstance(buttonEl, resolvedDropdownConfig).hide();
        } catch (error) {
            console.error('Error hiding dropdown after selection:', error);
        }
    };

    itemsContainerEl.addEventListener('click', event => {
        const item = event.target.closest('.chat-searchable-select-item[data-option-index]');
        if (!item) {
            return;
        }

        event.preventDefault();
        event.stopPropagation();
        selectOption(item.dataset.optionIndex);
    });

    menuEl.addEventListener('click', event => {
        event.stopPropagation();
    });

    menuEl.addEventListener('keydown', event => {
        event.stopPropagation();
    });

    searchInputEl.addEventListener('click', event => {
        event.stopPropagation();
    });

    searchInputEl.addEventListener('keydown', event => {
        event.stopPropagation();
    });

    searchInputEl.addEventListener('input', () => {
        renderOptions();
    });

    dropdownEl.addEventListener('show.bs.dropdown', () => {
        searchInputEl.value = '';
        renderOptions();
    });

    dropdownEl.addEventListener('shown.bs.dropdown', () => {
        searchInputEl.focus();
    });

    dropdownEl.addEventListener('hidden.bs.dropdown', () => {
        searchInputEl.value = '';
        renderOptions();
    });

    selectEl.addEventListener('change', syncFromSelect);

    const observer = new MutationObserver(() => {
        renderOptions();
    });
    observer.observe(selectEl, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['disabled', 'label', 'selected', 'value']
    });

    try {
        bootstrap.Dropdown.getOrCreateInstance(buttonEl, resolvedDropdownConfig);
    } catch (error) {
        console.error('Error initializing searchable select:', error);
    }

    renderOptions();

    return {
        refresh: renderOptions,
        syncFromSelect,
        destroy() {
            observer.disconnect();
        }
    };
}