// agent_modal_stepper.js
// Multi-step modal functionality for agent creation
import { showToast } from "./chat/chat-toast.js";

export class AgentModalStepper {
  constructor() {
    this.currentStep = 1;
    this.maxSteps = 6;
    this.isEditMode = false;
    
    this.bindEvents();
  }

  bindEvents() {
    // Step navigation buttons
    const nextBtn = document.getElementById('agent-modal-next');
    const prevBtn = document.getElementById('agent-modal-prev');
    
    if (nextBtn) {
      nextBtn.addEventListener('click', () => this.nextStep());
    }
    if (prevBtn) {
      prevBtn.addEventListener('click', () => this.prevStep());
    }
    
    // Set up display name to generated name conversion
    this.setupNameGeneration();
  }

  setupNameGeneration() {
    const displayNameInput = document.getElementById('agent-display-name');
    const generatedNameInput = document.getElementById('agent-name');
    
    if (displayNameInput && generatedNameInput) {
      displayNameInput.addEventListener('input', () => {
        const displayName = displayNameInput.value.trim();
        const generatedName = this.generateAgentName(displayName);
        generatedNameInput.value = generatedName;
      });
    }
  }

  generateAgentName(displayName) {
    if (!displayName) return '';
    
    // Convert to lowercase, replace spaces with underscores, remove invalid characters
    return displayName
      .toLowerCase()
      .replace(/\s+/g, '_')           // Replace spaces with underscores
      .replace(/[^a-z0-9_-]/g, '')    // Remove invalid characters (keep only letters, numbers, underscores, hyphens)
      .replace(/_{2,}/g, '_')         // Replace multiple underscores with single
      .replace(/^_+|_+$/g, '');       // Remove leading/trailing underscores
  }

  showModal(agent = null) {
    this.isEditMode = !!agent;
    
    // Reset modal state
    this.currentStep = 1;
    this.updateStepIndicator();
    this.showStep(1);
    this.updateNavigationButtons();
    
    // Set modal title
    const title = this.isEditMode ? 'Edit Agent' : 'Add Agent';
    const titleElement = document.getElementById('agentModalLabel');
    if (titleElement) {
      titleElement.textContent = title;
    }
    
    // Clear error messages
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
      errorDiv.classList.add('d-none');
    }
    
    // If editing an existing agent, populate fields and generate name if missing
    if (agent) {
      this.currentAgent = agent;
      this.populateFields(agent);
    } else {
      this.currentAgent = null;
      this.clearFields();
    }
    
    // Ensure generated name is populated for both new and existing agents
    this.updateGeneratedName();
  }

  updateGeneratedName() {
    const displayNameInput = document.getElementById('agent-display-name');
    const generatedNameInput = document.getElementById('agent-name');
    
    if (displayNameInput && generatedNameInput) {
      const displayName = displayNameInput.value.trim();
      if (displayName && !generatedNameInput.value) {
        const generatedName = this.generateAgentName(displayName);
        generatedNameInput.value = generatedName;
      }
    }
  }

  clearFields() {
    // Clear all form fields
    const displayName = document.getElementById('agent-display-name');
    const generatedName = document.getElementById('agent-name');
    const description = document.getElementById('agent-description');
    
    if (displayName) displayName.value = '';
    if (generatedName) generatedName.value = '';
    if (description) description.value = '';
  }

  populateFields(agent) {
    // Populate form fields with agent data
    const displayName = document.getElementById('agent-display-name');
    const generatedName = document.getElementById('agent-name');
    const description = document.getElementById('agent-description');
    
    if (displayName) displayName.value = agent.display_name || '';
    if (generatedName) generatedName.value = agent.name || '';
    if (description) description.value = agent.description || '';
  }

  nextStep() {
    if (!this.validateCurrentStep()) {
      return;
    }
    
    if (this.currentStep < this.maxSteps) {
      this.goToStep(this.currentStep + 1);
    }
  }

  prevStep() {
    if (this.currentStep > 1) {
      this.goToStep(this.currentStep - 1);
    }
  }

  goToStep(stepNumber) {
    if (stepNumber < 1 || stepNumber > this.maxSteps) return;
    
    this.currentStep = stepNumber;
    this.showStep(stepNumber);
    this.updateStepIndicator();
    this.updateNavigationButtons();
  }

  showStep(stepNumber) {
    // Hide all steps
    for (let i = 1; i <= this.maxSteps; i++) {
      const step = document.getElementById(`agent-step-${i}`);
      if (step) {
        step.classList.add('d-none');
      }
    }
    
    // Show current step
    const currentStep = document.getElementById(`agent-step-${stepNumber}`);
    if (currentStep) {
      currentStep.classList.remove('d-none');
    }
    
    // Load actions when reaching step 4
    if (stepNumber === 4) {
      this.loadAvailableActions();
    }
    
    // Populate summary when reaching step 6
    if (stepNumber === 6) {
      this.populateSummary();
    }
  }

  updateStepIndicator() {
    document.querySelectorAll('.step-indicator').forEach((indicator, index) => {
      const stepNum = index + 1;
      const circle = indicator.querySelector('.step-circle');
      
      // Reset classes
      indicator.classList.remove('active', 'completed');
      circle.classList.remove('active', 'completed');
      
      if (stepNum < this.currentStep) {
        indicator.classList.add('completed');
        circle.classList.add('completed');
      } else if (stepNum === this.currentStep) {
        indicator.classList.add('active');
        circle.classList.add('active');
      }
    });
  }

  updateNavigationButtons() {
    const nextBtn = document.getElementById('agent-modal-next');
    const prevBtn = document.getElementById('agent-modal-prev');
    const saveBtn = document.getElementById('agent-modal-save-btn');
    
    // Previous button
    if (prevBtn) {
      if (this.currentStep === 1) {
        prevBtn.classList.add('d-none');
      } else {
        prevBtn.classList.remove('d-none');
      }
    }
    
    // Next/Save button
    if (this.currentStep === this.maxSteps) {
      if (nextBtn) nextBtn.classList.add('d-none');
      if (saveBtn) saveBtn.classList.remove('d-none');
    } else {
      if (nextBtn) nextBtn.classList.remove('d-none');
      if (saveBtn) saveBtn.classList.add('d-none');
    }
  }

  validateCurrentStep() {
    switch (this.currentStep) {
      case 1: // Basic Info
        const displayName = document.getElementById('agent-display-name');
        const description = document.getElementById('agent-description');
        
        if (!displayName || !displayName.value.trim()) {
          this.showError('Please enter a display name for the agent.');
          if (displayName) displayName.focus();
          return false;
        }
        
        if (!description || !description.value.trim()) {
          this.showError('Please enter a description for the agent.');
          if (description) description.focus();
          return false;
        }
        break;
        
      case 2: // Model & Connection
        // Model validation would go here
        break;
        
      case 3: // Instructions
        const instructions = document.getElementById('agent-instructions');
        if (!instructions || !instructions.value.trim()) {
          this.showError('Please provide instructions for the agent.');
          if (instructions) instructions.focus();
          return false;
        }
        break;
        
      case 4: // Actions
        // Actions validation would go here if needed
        break;
        
      case 5: // Advanced
        // Advanced settings validation would go here if needed
        break;
        
      case 6: // Summary
        // Final validation would go here
        break;
    }
    
    this.hideError();
    return true;
  }

  showError(message) {
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
      errorDiv.textContent = message;
      errorDiv.classList.remove('d-none');
      errorDiv.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  }

  hideError() {
    const errorDiv = document.getElementById('agent-modal-error');
    if (errorDiv) {
      errorDiv.classList.add('d-none');
    }
  }

  async loadAvailableActions() {
    const container = document.getElementById('agent-actions-container');
    const noActionsMsg = document.getElementById('agent-no-actions-message');
    
    if (!container) return;
    
    try {
      // Show loading state
      container.innerHTML = '<div class="col-12 text-center"><div class="spinner-border" role="status"><span class="visually-hidden">Loading...</span></div><p class="mt-2">Loading available actions...</p></div>';
      
      // Fetch available actions from the API
      const response = await fetch('/api/user/plugins');
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      const actions = data.actions || data || [];
      
      // Sort actions alphabetically by display name
      actions.sort((a, b) => {
        const nameA = (a.display_name || a.name || '').toLowerCase();
        const nameB = (b.display_name || b.name || '').toLowerCase();
        return nameA.localeCompare(nameB);
      });
      
      // Clear container
      container.innerHTML = '';
      
      if (actions.length === 0) {
        // Show no actions message
        container.style.display = 'none';
        if (noActionsMsg) {
          noActionsMsg.classList.remove('d-none');
        }
        return;
      }
      
      // Hide no actions message
      container.style.display = '';
      if (noActionsMsg) {
        noActionsMsg.classList.add('d-none');
      }
      
      // Populate action cards
      actions.forEach(action => {
        const actionCard = this.createActionCard(action);
        container.appendChild(actionCard);
      });
      
      // Initialize search and filter functionality
      this.initializeActionSearch(actions);
      
      // Pre-select actions if editing an existing agent
      if (this.currentAgent && this.currentAgent.actions_to_load) {
        this.setSelectedActions(this.currentAgent.actions_to_load);
      }
      
    } catch (error) {
      console.error('Error loading actions:', error);
      container.innerHTML = '<div class="col-12"><div class="alert alert-warning">Unable to load actions. Please try again.</div></div>';
    }
  }

  populateSummary() {
    // Basic Information
    const displayName = document.getElementById('agent-display-name')?.value || '-';
    const generatedName = document.getElementById('agent-name')?.value || '-';
    const description = document.getElementById('agent-description')?.value || '-';
    
    // Model & Connection
    const modelSelect = document.getElementById('agent-global-model-select');
    const modelName = modelSelect?.options[modelSelect.selectedIndex]?.text || '-';
    
    const customConnection = document.getElementById('agent-custom-connection')?.checked ? 'Yes' : 'No';
    
    // Instructions
    const instructions = document.getElementById('agent-instructions')?.value || '-';
    
    // Selected Actions
    const selectedActions = this.getSelectedActions();
    const actionsCount = selectedActions.length;
    
    // Update basic information
    document.getElementById('summary-display-name').textContent = displayName;
    document.getElementById('summary-name').textContent = generatedName;
    document.getElementById('summary-description').textContent = description;
    
    // Update configuration
    document.getElementById('summary-model').textContent = modelName;
    document.getElementById('summary-custom-connection').textContent = customConnection;
    
    // Update instructions
    document.getElementById('summary-instructions').textContent = instructions;
    
    // Update actions count badge
    const countBadge = document.getElementById('summary-actions-count-badge');
    if (countBadge) {
      countBadge.textContent = actionsCount;
    }
    
    // Update actions list
    const actionsListContainer = document.getElementById('summary-actions-list');
    const actionsEmptyContainer = document.getElementById('summary-actions-empty');
    
    if (actionsCount > 0) {
      // Show actions list, hide empty message
      actionsListContainer.style.display = 'block';
      actionsEmptyContainer.style.display = 'none';
      
      // Clear existing content
      actionsListContainer.innerHTML = '';
      
      // Create action cards
      selectedActions.forEach(action => {
        const col = document.createElement('div');
        col.className = 'col-md-6 col-lg-4';
        
        const actionCard = document.createElement('div');
        actionCard.className = 'summary-action-card';
        
        const actionTitle = document.createElement('div');
        actionTitle.className = 'action-title';
        actionTitle.textContent = action.display_name || action.name || 'Unknown Action';
        
        const actionDescription = document.createElement('div');
        actionDescription.className = 'action-description';
        const desc = action.description || 'No description available';
        actionDescription.textContent = desc.length > 80 ? desc.substring(0, 80) + '...' : desc;
        
        actionCard.appendChild(actionTitle);
        actionCard.appendChild(actionDescription);
        col.appendChild(actionCard);
        actionsListContainer.appendChild(col);
      });
    } else {
      // Hide actions list, show empty message
      actionsListContainer.style.display = 'none';
      actionsEmptyContainer.style.display = 'block';
    }
    
    // Update creation date
    const createdDate = document.getElementById('summary-created-date');
    if (createdDate) {
      const now = new Date();
      createdDate.textContent = now.toLocaleDateString() + ' at ' + now.toLocaleTimeString();
    }
  }

  createActionCard(action) {
    const col = document.createElement('div');
    col.className = 'col-md-6 col-lg-4';
    
    const card = document.createElement('div');
    card.className = 'card h-100 action-card';
    card.style.cursor = 'pointer';
    card.setAttribute('data-action-id', action.id || action.name);
    card.setAttribute('data-action-type', action.type || 'custom');
    card.setAttribute('data-action-name', action.name || action.display_name || '');
    card.setAttribute('data-action-description', action.description || '');
    
    const cardBody = document.createElement('div');
    cardBody.className = 'card-body d-flex flex-column';
    
    const title = document.createElement('h6');
    title.className = 'card-title mb-2';
    title.textContent = action.display_name || action.name || 'Untitled Action';
    
    const type = document.createElement('span');
    type.className = 'badge bg-secondary mb-2';
    type.textContent = action.type || 'Custom';
    
    // Create description with truncation functionality
    const descriptionContainer = document.createElement('div');
    descriptionContainer.className = 'card-text-container flex-grow-1';
    
    const description = document.createElement('p');
    description.className = 'card-text small text-muted mb-0';
    
    const fullDescription = action.description || 'No description available';
    const maxLength = 120; // Character limit for truncation
    
    if (fullDescription.length > maxLength) {
      const truncatedText = fullDescription.substring(0, maxLength) + '...';
      
      // Create truncated and full text spans
      const truncatedSpan = document.createElement('span');
      truncatedSpan.className = 'description-truncated';
      truncatedSpan.textContent = truncatedText;
      
      const fullSpan = document.createElement('span');
      fullSpan.className = 'description-full d-none';
      fullSpan.textContent = fullDescription;
      
      // Create toggle button
      const toggleBtn = document.createElement('button');
      toggleBtn.className = 'btn btn-link btn-sm p-0 ms-1 text-decoration-none';
      toggleBtn.style.fontSize = '0.75rem';
      toggleBtn.style.verticalAlign = 'baseline';
      toggleBtn.textContent = 'more';
      
      // Add click handler for toggle (prevent card selection)
      toggleBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        const isExpanded = !fullSpan.classList.contains('d-none');
        
        if (isExpanded) {
          // Show truncated
          truncatedSpan.classList.remove('d-none');
          fullSpan.classList.add('d-none');
          toggleBtn.textContent = 'more';
        } else {
          // Show full
          truncatedSpan.classList.add('d-none');
          fullSpan.classList.remove('d-none');
          toggleBtn.textContent = 'less';
        }
      });
      
      description.appendChild(truncatedSpan);
      description.appendChild(fullSpan);
      description.appendChild(toggleBtn);
    } else {
      description.textContent = fullDescription;
    }
    
    descriptionContainer.appendChild(description);
    
    const checkIcon = document.createElement('div');
    checkIcon.className = 'action-check-icon d-none';
    checkIcon.innerHTML = '<i class="bi bi-check-circle-fill text-primary"></i>';
    
    cardBody.appendChild(title);
    cardBody.appendChild(type);
    cardBody.appendChild(descriptionContainer);
    cardBody.appendChild(checkIcon);
    
    card.appendChild(cardBody);
    col.appendChild(card);
    
    // Add click handler
    card.addEventListener('click', () => {
      this.toggleActionSelection(card);
    });
    
    return col;
  }

  toggleActionSelection(card) {
    const checkIcon = card.querySelector('.action-check-icon');
    const isSelected = !card.classList.contains('border-primary');
    
    if (isSelected) {
      card.classList.add('border-primary', 'bg-light');
      checkIcon.classList.remove('d-none');
    } else {
      card.classList.remove('border-primary', 'bg-light');
      checkIcon.classList.add('d-none');
    }
    
    this.updateSelectedActionsDisplay();
  }

  updateSelectedActionsDisplay() {
    const selectedCards = document.querySelectorAll('.action-card.border-primary');
    const summaryDiv = document.getElementById('agent-selected-actions-summary');
    const listDiv = document.getElementById('agent-selected-actions-list');
    
    if (selectedCards.length > 0) {
      if (summaryDiv) summaryDiv.classList.remove('d-none');
      if (listDiv) {
        listDiv.innerHTML = '';
        selectedCards.forEach(card => {
          const actionName = card.getAttribute('data-action-name');
          const badge = document.createElement('span');
          badge.className = 'badge bg-primary';
          badge.textContent = actionName;
          listDiv.appendChild(badge);
        });
      }
    } else {
      if (summaryDiv) summaryDiv.classList.add('d-none');
    }
  }

  initializeActionSearch(actions) {
    const searchInput = document.getElementById('agent-action-search');
    const typeFilter = document.getElementById('agent-action-type-filter');
    const clearBtn = document.getElementById('agent-action-clear-search');
    const selectAllBtn = document.getElementById('agent-select-all-visible');
    const deselectAllBtn = document.getElementById('agent-deselect-all');
    const showSelectedBtn = document.getElementById('agent-toggle-selected-only');
    
    // Populate type filter
    if (typeFilter) {
      const types = [...new Set(actions.map(a => a.type || 'custom'))];
      typeFilter.innerHTML = '<option value="">All Types</option>';
      types.forEach(type => {
        const option = document.createElement('option');
        option.value = type;
        option.textContent = type.charAt(0).toUpperCase() + type.slice(1);
        typeFilter.appendChild(option);
      });
    }
    
    // Search and filter functionality
    const performFilter = () => {
      const searchTerm = searchInput ? searchInput.value.toLowerCase() : '';
      const selectedType = typeFilter ? typeFilter.value : '';
      const cards = document.querySelectorAll('.action-card');
      let visibleCount = 0;
      
      cards.forEach(card => {
        const name = card.getAttribute('data-action-name').toLowerCase();
        const description = card.getAttribute('data-action-description').toLowerCase();
        const type = card.getAttribute('data-action-type');
        
        const matchesSearch = searchTerm === '' || name.includes(searchTerm) || description.includes(searchTerm);
        const matchesType = selectedType === '' || type === selectedType;
        
        if (matchesSearch && matchesType) {
          card.parentElement.style.display = '';
          visibleCount++;
        } else {
          card.parentElement.style.display = 'none';
        }
      });
      
      // Update results count
      const resultsSpan = document.getElementById('agent-action-results-count');
      if (resultsSpan) {
        resultsSpan.textContent = `${visibleCount} action${visibleCount !== 1 ? 's' : ''} found`;
      }
    };
    
    if (searchInput) {
      searchInput.addEventListener('input', performFilter);
    }
    if (typeFilter) {
      typeFilter.addEventListener('change', performFilter);
    }
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        if (searchInput) searchInput.value = '';
        if (typeFilter) typeFilter.value = '';
        performFilter();
      });
    }
    
    // Button handlers
    if (selectAllBtn) {
      selectAllBtn.addEventListener('click', () => {
        const visibleCards = document.querySelectorAll('.action-card[style=""], .action-card:not([style*="display: none"])');
        visibleCards.forEach(card => {
          if (!card.classList.contains('border-primary')) {
            this.toggleActionSelection(card);
          }
        });
      });
    }
    
    if (deselectAllBtn) {
      deselectAllBtn.addEventListener('click', () => {
        const selectedCards = document.querySelectorAll('.action-card.border-primary');
        selectedCards.forEach(card => {
          this.toggleActionSelection(card);
        });
      });
    }
    
    // Initial filter
    performFilter();
  }

  getSelectedActions() {
    const selectedCards = document.querySelectorAll('.action-card.border-primary');
    return Array.from(selectedCards).map(card => {
      const actionId = card.getAttribute('data-action-id');
      const actionName = card.getAttribute('data-action-name');
      const actionDescription = card.getAttribute('data-action-description');
      
      return {
        id: actionId,
        name: actionName,
        display_name: actionName,
        description: actionDescription
      };
    });
  }

  getSelectedActionIds() {
    const selectedCards = document.querySelectorAll('.action-card.border-primary');
    return Array.from(selectedCards).map(card => card.getAttribute('data-action-id'));
  }

  setSelectedActions(actionIds) {
    if (!Array.isArray(actionIds)) return;
    
    const allCards = document.querySelectorAll('.action-card');
    allCards.forEach(card => {
      const actionId = card.getAttribute('data-action-id');
      if (actionIds.includes(actionId)) {
        if (!card.classList.contains('border-primary')) {
          this.toggleActionSelection(card);
        }
      } else {
        if (card.classList.contains('border-primary')) {
          this.toggleActionSelection(card);
        }
      }
    });
  }
}

// Create a global instance
window.agentModalStepper = new AgentModalStepper();
