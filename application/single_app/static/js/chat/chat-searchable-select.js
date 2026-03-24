// chat-searchable-select.js

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

function isVisibleItem(el) {
    return Boolean(
        el &&
        !el.classList.contains('d-none') &&
        !el.classList.contains('dropdown-divider')
    );
}

function updateDropdownStructure(itemsContainerEl) {
    if (!itemsContainerEl) {
        return;
    }

    const children = Array.from(itemsContainerEl.children).filter(child => !child.classList.contains('no-matches'));

    children.forEach(child => {
        if (!child.classList.contains('dropdown-header')) {
            return;
        }

        let hasVisibleItem = false;
        let next = child.nextElementSibling;

        while (next && !next.classList.contains('dropdown-header')) {
            if (next.classList.contains('dropdown-item') && isVisibleItem(next)) {
                hasVisibleItem = true;
                break;
            }
            next = next.nextElementSibling;
        }

        child.classList.toggle('d-none', !hasVisibleItem);
    });

    children.forEach(child => {
        if (!child.classList.contains('dropdown-divider')) {
            return;
        }

        let previousVisible = null;
        let previous = child.previousElementSibling;
        while (previous) {
            if (!previous.classList.contains('no-matches') && isVisibleItem(previous)) {
                previousVisible = previous;
                break;
            }
            previous = previous.previousElementSibling;
        }

        let nextVisible = null;
        let next = child.nextElementSibling;
        while (next) {
            if (!next.classList.contains('no-matches') && isVisibleItem(next)) {
                nextVisible = next;
                break;
            }
            next = next.nextElementSibling;
        }

        child.classList.toggle('d-none', !(previousVisible && nextVisible));
    });
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
}) {
    if (!menuEl || !searchInputEl || !itemsContainerEl) {
        return null;
    }

    const readSearchText = getItemSearchText || (item => item.dataset.searchLabel || item.textContent || '');
    const isAlwaysVisible = isAlwaysVisibleItem || (() => false);

    const applyFilter = (rawSearchTerm = '') => {
        const searchTerm = rawSearchTerm.toLowerCase().trim();
        const items = Array.from(itemsContainerEl.querySelectorAll(itemSelector));
        let visibleMatchCount = 0;

        items.forEach(item => {
            const keepVisible = isAlwaysVisible(item);
            const searchText = String(readSearchText(item) || '').toLowerCase();
            const matches = !searchTerm || keepVisible || searchText.includes(searchTerm);

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
}) {
    if (!selectEl || !dropdownEl || !buttonEl || !buttonTextEl || !menuEl || !searchInputEl || !itemsContainerEl) {
        return null;
    }

    const readOptionLabel = getOptionLabel || (option => option.textContent.trim());
    const readOptionSearchText = getOptionSearchText || (option => option.textContent.trim());

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
        const searchTerm = searchInputEl.value.toLowerCase().trim();
        const options = Array.from(selectEl.options);
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

        options.forEach((option, index) => {
            const optionLabel = readOptionLabel(option);
            const optionSearchText = String(readOptionSearchText(option) || optionLabel).toLowerCase();
            const matches = !searchTerm || optionSearchText.includes(searchTerm);

            if (!matches) {
                return;
            }

            matchedCount += 1;

            const item = document.createElement('button');
            item.type = 'button';
            item.classList.add('dropdown-item', 'chat-searchable-select-item');
            item.dataset.optionIndex = String(index);
            item.dataset.optionValue = option.value;
            item.title = optionLabel;

            if (index === selectedIndex) {
                item.classList.add('active');
            }

            if (option.disabled) {
                item.classList.add('disabled');
                item.disabled = true;
            }

            const textEl = document.createElement('span');
            textEl.className = 'chat-searchable-select-item-text';
            textEl.textContent = optionLabel;
            item.appendChild(textEl);

            itemsContainerEl.appendChild(item);
        });

        buttonEl.disabled = !hasEnabledOption;
        searchInputEl.disabled = !hasEnabledOption;
        syncButtonText();

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
            bootstrap.Dropdown.getOrCreateInstance(buttonEl, {
                autoClose: 'outside'
            }).hide();
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
        bootstrap.Dropdown.getOrCreateInstance(buttonEl, {
            autoClose: 'outside'
        });
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