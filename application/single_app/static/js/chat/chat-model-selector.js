// chat-model-selector.js

import { createSearchableSingleSelect } from './chat-searchable-select.js';

const modelSelect = document.getElementById('model-select');
const modelDropdown = document.getElementById('model-dropdown');
const modelDropdownButton = document.getElementById('model-dropdown-button');
const modelDropdownMenu = document.getElementById('model-dropdown-menu');
const modelDropdownText = modelDropdownButton
	? modelDropdownButton.querySelector('.chat-searchable-select-text')
	: null;
const modelSearchInput = document.getElementById('model-search-input');
const modelDropdownItems = document.getElementById('model-dropdown-items');

let modelSelectorController = null;

export function initializeModelSelector() {
	if (modelSelectorController || !modelSelect) {
		return modelSelectorController;
	}

	modelSelectorController = createSearchableSingleSelect({
		selectEl: modelSelect,
		dropdownEl: modelDropdown,
		buttonEl: modelDropdownButton,
		buttonTextEl: modelDropdownText,
		menuEl: modelDropdownMenu,
		searchInputEl: modelSearchInput,
		itemsContainerEl: modelDropdownItems,
		placeholderText: 'Select a Model',
		emptyMessage: 'No models available',
		emptySearchMessage: 'No matching models found',
	});

	return modelSelectorController;
}

export function refreshModelSelector() {
	if (!modelSelectorController) {
		initializeModelSelector();
	}

	modelSelectorController?.refresh();
}
