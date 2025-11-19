// agent_modal_stepper.js
// Multi-step modal functionality for agent creation
import { showToast } from "./chat/chat-toast.js";
import * as agentsCommon from "./agents_common.js";

export class AgentModalStepper {
  constructor(isAdmin = false) {
    this.currentStep = 1;
    this.maxSteps = 6;
    this.isEditMode = false;
    this.isAdmin = isAdmin; // Track if this is admin context
    this.originalAgent = null;  // Track original state for change detection
    this.actionsToSelect = null; // Store actions to select when they're loaded
    this.updateStepIndicatorTimeout = null; // For debouncing step indicator updates
    
    this.bindEvents();
  }

  bindEvents() {
    // Step navigation buttons
    const nextBtn = document.getElementById('agent-modal-next');
    const prevBtn = document.getElementById('agent-modal-prev');
    const saveBtn = document.getElementById('agent-modal-save-btn');
    const skipBtn = document.getElementById('agent-modal-skip');
    const powerUserToggle = document.getElementById('agent-power-user-toggle');
    
    if (nextBtn) {
      nextBtn.addEventListener('click', () => this.nextStep());
    }
    if (prevBtn) {
      prevBtn.addEventListener('click', () => this.prevStep());
    }
    if (saveBtn) {
      saveBtn.addEventListener('click', () => this.saveAgent());
    }
    if (skipBtn) {
      skipBtn.addEventListener('click', () => this.skipToEnd());
    }
    if (powerUserToggle) {
      powerUserToggle.addEventListener('change', (e) => this.togglePowerUserMode(e.target.checked));
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

  togglePowerUserMode(isEnabled) {
    console.log('Toggling power user mode:', isEnabled);
    const powerUserSection = document.getElementById('agent-power-user-settings');
    if (powerUserSection) {
      powerUserSection.classList.toggle('d-none', !isEnabled);
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
    
    // Store original state for change detection
    this.originalAgent = agent ? JSON.parse(JSON.stringify(agent)) : null;
    
    // Reset modal state
    this.currentStep = 1;
    
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
      this.actionsToSelect = null; // Clear any stored actions for new agent
      this.clearFields();
    }
    
    // Ensure generated name is populated for both new and existing agents
    this.updateGeneratedName();
    
    // Load models for the modal
    this.loadModelsForModal();
    
    // Show the Bootstrap modal
    const modalEl = document.getElementById('agentModal');
    if (modalEl) {
      const modal = bootstrap.Modal.getOrCreateInstance(modalEl);
      modal.show();
      
      // Use a more robust approach - wait for modal to be visible and DOM ready
      const initializeSteps = () => {
        if (modalEl.classList.contains('show')) {
          console.log('Modal is visible, initializing step indicators');
          this.currentStep = 1; // Ensure we're on step 1
          this.updateStepIndicator();
          this.showStep(1);
          this.updateNavigationButtons();
          console.log('Step indicators initialized');
        } else {
          // Modal not ready yet, try again
          setTimeout(initializeSteps, 50);
        }
      };
      
      // Start checking after a short delay
      setTimeout(initializeSteps, 100);
      
    } else {
      console.error('Agent modal element not found');
    }
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
    const instructions = document.getElementById('agent-instructions');
    const modelSelect = document.getElementById('agent-global-model-select');
    const customConnection = document.getElementById('agent-custom-connection');
    
    if (displayName) displayName.value = '';
    if (generatedName) generatedName.value = '';
    if (description) description.value = '';
    if (instructions) instructions.value = '';
    if (modelSelect) modelSelect.selectedIndex = 0;
    if (customConnection) customConnection.checked = false;
    
    // Clear any selected actions
    this.clearSelectedActions();
  }

  clearSelectedActions() {
    const actionCards = document.querySelectorAll('.action-card.border-primary');
    actionCards.forEach(card => {
      card.classList.remove('border-primary', 'bg-primary-subtle');
    });
  }

  async loadModelsForModal() {
    try {
      const endpoint = '/api/user/agent/settings';
      const { models, selectedModel } = await agentsCommon.fetchAndGetAvailableModels(endpoint, this.currentAgent);
      const globalModelSelect = document.getElementById('agent-global-model-select');
      
      if (globalModelSelect) {
        agentsCommon.populateGlobalModelDropdown(globalModelSelect, models, selectedModel);
      }
    } catch (error) {
      console.error('Failed to load models for agent modal:', error);
      // Show fallback message if models fail to load
      const globalModelSelect = document.getElementById('agent-global-model-select');
      if (globalModelSelect) {
        globalModelSelect.innerHTML = '<option value="">Error loading models</option>';
      }
    }
  }

  populateFields(agent) {
    // Use shared logic to determine if custom connection should be enabled
    const customConnection = document.getElementById('agent-custom-connection');
    if (customConnection) {
      // Use agentsCommon.shouldEnableCustomConnection to set toggle
      customConnection.checked = agentsCommon.shouldEnableCustomConnection(agent);
    }

    // Use shared function to populate all fields
    if (agentsCommon && typeof agentsCommon.setAgentModalFields === 'function') {
      agentsCommon.setAgentModalFields(agent);
    }

    // any agent advanced settings
    if (this.currentAgent 
        && this.currentAgent.max_completion_tokens != -1) {
      const powerUserToggle = document.getElementById('agent-power-user-toggle');
      if (powerUserToggle) {
        powerUserToggle.checked = true; // true/false from your agent data
        const agentPowerUserSettings = document.getElementById('agent-power-user-settings');
        if (agentPowerUserSettings) {
          agentPowerUserSettings.classList.remove('d-none');
        }
      }
    }

    // Show/hide custom connection fields as needed
    if (customConnection) {
      // Find the custom fields and global model group containers
      const customFields = document.getElementById('agent-custom-connection-fields');
      const globalModelGroup = document.getElementById('agent-global-model-group');
      // Use shared UI toggle logic if available
      if (agentsCommon && typeof agentsCommon.toggleCustomConnectionUI === 'function') {
        agentsCommon.toggleCustomConnectionUI(customConnection.checked, {
          customFields,
          globalModelGroup
        });
      } else if (customFields && globalModelGroup) {
        // Fallback: show/hide manually
        if (customConnection.checked) {
          customFields.classList.remove('d-none');
          globalModelGroup.classList.add('d-none');
        } else {
          customFields.classList.add('d-none');
          globalModelGroup.classList.remove('d-none');
        }
      }
    }

    // Store selected actions to be set when actions are loaded
    if (agent.actions_to_load && Array.isArray(agent.actions_to_load)) {
      this.actionsToSelect = agent.actions_to_load;
    }
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

  async skipToEnd() {
    // Skip to the summary step (step 6)
    //if (this.actionsToSelect != null && this.actionsToSelect.length > 0) {
    //  this.setSelectedActions(this.actionsToSelect);
    //}
    const skipBtn = document.getElementById('agent-modal-skip');
    const originalText = skipBtn.innerHTML;
    if (skipBtn) {
      skipBtn.disabled = true;
      skipBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Skipping...`;
    }
    try {
      await this.loadAvailableActions();
      this.goToStep(this.maxSteps);
    } catch (error) {
      console.error('Error loading actions:', error);
      if (skipBtn) {
        skipBtn.disabled = false;
        skipBtn.innerHTML = originalText;
      }
    } finally {
      if (skipBtn) {
        skipBtn.disabled = false;
        skipBtn.innerHTML = originalText;
      }
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

    if (stepNumber === 2) {
      if (!this.isAdmin) {
        const customConnectionToggle = document.getElementById('agent-custom-connection-toggle');
        if (customConnectionToggle) {
          const allowUserCustom = appSettings?.allow_user_custom_agent_endpoints;
          if (!allowUserCustom) {
            customConnectionToggle.classList.add('d-none');
          } else {
            customConnectionToggle.classList.remove('d-none');
          }
        }
      }
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
    // Clear any pending updates to prevent rapid successive calls
    if (this.updateStepIndicatorTimeout) {
      clearTimeout(this.updateStepIndicatorTimeout);
    }
    
    // Debounce the actual update
    this.updateStepIndicatorTimeout = setTimeout(() => {
      this._doUpdateStepIndicator();
    }, 10); // Small delay to allow for batching
  }
  
  _doUpdateStepIndicator() {
    // Be very specific about which step indicators we're targeting - only those in the agent modal
    const agentModal = document.getElementById('agentModal');
    if (!agentModal) {
      console.warn('Agent modal not found');
      return;
    }
    
    const indicators = agentModal.querySelectorAll('.step-indicator');
    console.log(`Updating agent modal step indicator - Current step: ${this.currentStep}, Found ${indicators.length} indicators`);
    
    if (indicators.length === 0) {
      console.warn('No step indicators found in agent modal');
      return;
    }
    
    indicators.forEach((indicator, index) => {
      const stepNum = index + 1;
      const circle = indicator.querySelector('.step-circle');
      
      if (!circle) {
        console.warn(`No step-circle found for indicator ${stepNum}`);
        return;
      }
      
      // Reset classes
      indicator.classList.remove('active', 'completed');
      circle.classList.remove('active', 'completed');
      
      if (stepNum < this.currentStep) {
        indicator.classList.add('completed');
        circle.classList.add('completed');
        console.log(`Agent modal step ${stepNum}: marked as completed`);
      } else if (stepNum === this.currentStep) {
        indicator.classList.add('active');
        circle.classList.add('active');
        console.log(`Agent modal step ${stepNum}: marked as active`);
      } else {
        console.log(`Agent modal step ${stepNum}: unmarked (future step)`);
      }
    });
  }

  updateNavigationButtons() {
    const nextBtn = document.getElementById('agent-modal-next');
    const prevBtn = document.getElementById('agent-modal-prev');
    const saveBtn = document.getElementById('agent-modal-save-btn');
    const skipBtn = document.getElementById('agent-modal-skip');
    
    // Previous button
    if (prevBtn) {
      if (this.currentStep === 1) {
        prevBtn.classList.add('d-none');
      } else {
        prevBtn.classList.remove('d-none');
      }
    }
    
    // Skip button - show on steps 2-5, hide on first and last step
    if (skipBtn) {
      if (this.currentStep === 1 || this.currentStep === this.maxSteps) {
        skipBtn.classList.add('d-none');
      } else {
        skipBtn.classList.remove('d-none');
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
      
      // Use appropriate endpoint based on context
      const endpoint = this.isAdmin ? '/api/admin/plugins' : '/api/user/plugins';
      const response = await fetch(endpoint);
      if (!response.ok) {
        throw new Error(`HTTP ${response.status}: ${response.statusText}`);
      }
      
      const data = await response.json();
      const actions = data.actions || data || [];
      
      // Filter to only show global actions in admin context
      const filteredActions = this.isAdmin 
        ? actions.filter(action => action.is_global !== false) // Only global actions
        : actions; // All actions (personal + global when merged)
      
      // Sort actions alphabetically by display name
      filteredActions.sort((a, b) => {
        const nameA = (a.display_name || a.name || '').toLowerCase();
        const nameB = (b.display_name || b.name || '').toLowerCase();
        return nameA.localeCompare(nameB);
      });
      
      // Clear container
      container.innerHTML = '';
      
      if (filteredActions.length === 0) {
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
      filteredActions.forEach(action => {
        const actionCard = this.createActionCard(action);
        container.appendChild(actionCard);
      });
      
      // Initialize search and filter functionality
      this.initializeActionSearch(actions);
      
      // Pre-select actions if editing an existing agent
      if (this.actionsToSelect && Array.isArray(this.actionsToSelect)) {
        this.setSelectedActions(this.actionsToSelect);
        this.actionsToSelect = null; // Clear after use
      }
      
    } catch (error) {
      console.error('Error loading actions:', error);
      container.innerHTML = '<div class="col-12"><div class="alert alert-warning">Unable to load actions. Please try again.</div></div>';
    }
  }

  getFormModelName() {
    const customConnection = document.getElementById('agent-custom-connection')?.checked || false;
    let modelName = '-';
    if (customConnection) {
      const apimToggle = document.getElementById('agent-enable-apim');
      if (apimToggle && apimToggle.checked) {
        const apimDeployment = document.getElementById('agent-apim-deployment');
        modelName = apimDeployment?.value?.trim() || '-';
      } else {
        const gptDeployment = document.getElementById('agent-gpt-deployment');
        modelName = gptDeployment?.value?.trim() || '-';
      }
    } else {
      const modelSelect = document.getElementById('agent-global-model-select');
      modelName = modelSelect?.options[modelSelect.selectedIndex]?.text || '-';
    }
    return modelName;
  }

  populateSummary() {
    // Basic Information
    const displayName = document.getElementById('agent-display-name')?.value || '-';
    const generatedName = document.getElementById('agent-name')?.value || '-';
    const description = document.getElementById('agent-description')?.value || '-';
    
    // Model & Connection
    const customConnection = document.getElementById('agent-custom-connection')?.checked ? 'Yes' : 'No';
    const modelName = this.getFormModelName();
    
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
        actionTitle.className = 'action-title d-flex align-items-center justify-content-between';
        
        const titleText = document.createElement('span');
        titleText.textContent = action.display_name || action.name || 'Unknown Action';
        actionTitle.appendChild(titleText);
        
        // Add global tag if this is a global action
        if (action.is_global) {
          const globalTag = document.createElement('span');
          globalTag.className = 'badge bg-info text-dark ms-2';
          globalTag.style.fontSize = '0.65rem';
          globalTag.textContent = 'global';
          actionTitle.appendChild(globalTag);
        }
        
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
    
    // Populate changes summary
    this.populateChangesSummary();
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
    card.setAttribute('data-action-is-global', action.is_global ? 'true' : 'false');
    
    const cardBody = document.createElement('div');
    cardBody.className = 'card-body d-flex flex-column';
    
    const title = document.createElement('h6');
    title.className = 'card-title mb-2 d-flex align-items-center justify-content-between';
    
    const titleText = document.createElement('span');
    titleText.textContent = action.display_name || action.name || 'Untitled Action';
    title.appendChild(titleText);
    
    // Add global tag if this is a global action
    if (action.is_global) {
      const globalTag = document.createElement('span');
      globalTag.className = 'badge bg-info text-dark ms-2';
      globalTag.style.fontSize = '0.65rem';
      globalTag.textContent = 'global';
      title.appendChild(globalTag);
    }
    
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
          const isGlobal = card.getAttribute('data-action-is-global') === 'true';
          
          const badge = document.createElement('span');
          badge.className = 'badge bg-primary me-1 mb-1';
          
          // Create badge content with global tag if needed
          if (isGlobal) {
            badge.innerHTML = `${actionName} <small class="badge bg-info text-dark ms-1" style="font-size: 0.6em;">global</small>`;
          } else {
            badge.textContent = actionName;
          }
          
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
    
    console.log('setSelectedActions called with:', actionIds);
    
    const allCards = document.querySelectorAll('.action-card');
    console.log('Found action cards:', allCards.length);
    
    allCards.forEach(card => {
      const actionId = card.getAttribute('data-action-id');
      const actionName = card.getAttribute('data-action-name');
      
      console.log('Checking card - ID:', actionId, 'Name:', actionName);
      
      // Check if either the UUID (actionId) or name (actionName) matches
      const isMatch = actionIds.includes(actionId) || actionIds.includes(actionName);
      
      if (isMatch) {
        console.log('Matching action found, selecting:', { actionId, actionName });
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

  detectChanges() {
    if (!this.originalAgent) {
      return null; // No original to compare against
    }

    try {
      const changes = {};
      
      // Get current values
      const currentDisplayName = document.getElementById('agent-display-name')?.value || '';
      const currentName = document.getElementById('agent-name')?.value || '';
      const currentDescription = document.getElementById('agent-description')?.value || '';
      const currentInstructions = document.getElementById('agent-instructions')?.value || '';
      
      // Custom connection
      const currentCustomConnection = document.getElementById('agent-custom-connection')?.checked || false;

      // Model selection
      const currentModel = this.getFormModelName();
      
      // Selected actions
      const currentActions = this.getSelectedActionIds();
      const originalActions = this.originalAgent.actions_to_load || [];
      
      // Compare fields
      if (currentDisplayName !== (this.originalAgent.display_name || '')) {
        changes.displayName = {
          before: this.originalAgent.display_name || '',
          after: currentDisplayName
        };
      }
      
      if (currentName !== (this.originalAgent.name || '')) {
        changes.name = {
          before: this.originalAgent.name || '',
          after: currentName
        };
      }
      
      if (currentDescription !== (this.originalAgent.description || '')) {
        changes.description = {
          before: this.originalAgent.description || '',
          after: currentDescription
        };
      }
      
      if (currentInstructions !== (this.originalAgent.instructions || '')) {
        changes.instructions = {
          before: this.originalAgent.instructions || '',
          after: currentInstructions
        };
      }
      
      if (currentModel !== (this.originalAgent.model || '')) {
        changes.model = {
          before: this.originalAgent.model || '',
          after: currentModel
        };
      }
      
      if (currentCustomConnection !== (this.originalAgent.custom_connection || false)) {
        changes.customConnection = {
          before: this.originalAgent.custom_connection ? 'Yes' : 'No',
          after: currentCustomConnection ? 'Yes' : 'No'
        };
      }
      
      // Compare actions (check if arrays are different)
      const actionsChanged = JSON.stringify(currentActions.sort()) !== JSON.stringify(originalActions.sort());
      if (actionsChanged) {
        changes.actions = {
          before: originalActions.join(', ') || '(none)',
          after: currentActions.join(', ') || '(none)'
        };
      }
      
      return Object.keys(changes).length > 0 ? changes : null;
    } catch (error) {
      console.error('Error detecting changes:', error);
      return null;
    }
  }

  populateChangesSummary() {
    const changesSection = document.getElementById('summary-changes-section');
    const changesContent = document.getElementById('summary-changes-content');
    
    // Detect changes
    const changes = this.detectChanges();
    
    if (changes && Object.keys(changes).length > 0) {
      // Show changes section
      changesSection.style.display = '';
      
      // Build changes HTML
      let changesHtml = '';
      
      for (const [field, change] of Object.entries(changes)) {
        const fieldLabel = this.getFieldLabel(field);
        changesHtml += `
          <div class="mb-3">
            <div class="fw-medium text-primary mb-1">${this.escapeHtml(fieldLabel)}</div>
            <div class="row g-2">
              <div class="col-md-6">
                <div class="small text-muted mb-1">Before:</div>
                <div class="border rounded p-2 bg-light">
                  <code class="small">${this.escapeHtml(change.before || '(empty)')}</code>
                </div>
              </div>
              <div class="col-md-6">
                <div class="small text-muted mb-1">After:</div>
                <div class="border rounded p-2 bg-success-subtle">
                  <code class="small">${this.escapeHtml(change.after || '(empty)')}</code>
                </div>
              </div>
            </div>
          </div>
        `;
      }
      
      changesContent.innerHTML = changesHtml;
    } else {
      // Hide changes section if no changes
      changesSection.style.display = 'none';
    }
  }

  getFieldLabel(field) {
    const labels = {
      displayName: 'Display Name',
      name: 'Generated Name',
      description: 'Description',
      instructions: 'Instructions',
      model: 'Model',
      customConnection: 'Custom Connection',
      actions: 'Selected Actions'
    };
    return labels[field] || field;
  }

  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  async saveAgent() {
    const errorDiv = document.getElementById('agent-modal-error');
    
    try {
      // Get agent data from form
      const agentData = this.getAgentFormData();
      agentData.agent_type = (this.originalAgent?.agent_type) || agentData.agent_type || 'local';
      
      // Validate required fields
      if (!agentData.display_name || !agentData.name) {
        throw new Error('Display name and generated name are required');
      }
      
      // If editing, preserve the original ID
      if (this.isEditMode && this.originalAgent && this.originalAgent.id) {
        agentData.id = this.originalAgent.id;
      }
      else {
        // Generate ID if needed for new agents
        if (!agentData.id) {
          if (this.isAdmin) {
            try {
              const guidResp = await fetch('/api/agents/generate_id');
              if (guidResp.ok) {
                const guidData = await guidResp.json();
                agentData.id = guidData.id;
              } else {
                agentData.id = crypto.randomUUID();
              }
            } catch (guidErr) {
              agentData.id = crypto.randomUUID();
            }
          }
          else {
            agentData.id = `${current_user_id}_${agentData.name}`;
          }
        }
      }
      
      // Add selected actions
      agentData.actions_to_load = this.getSelectedActionIds();
      agentData.is_global = this.isAdmin; // Set based on admin context
      
      // Ensure required schema fields are present
      if (!agentData.other_settings) {
        agentData.other_settings = {};
      }
      else {
        agentData.other_settings = JSON.parse(agentData.other_settings) || {};
      }
      
      // Clean up form-specific fields that shouldn't be sent to backend
      const formOnlyFields = ['custom_connection', 'model'];
      formOnlyFields.forEach(field => {
        if (agentData.hasOwnProperty(field)) {
          delete agentData[field];
        }
      });
      
      // Use appropriate endpoint and save method based on context
      let saveBtn = document.getElementById('agent-modal-save-btn');
      const originalText = saveBtn.innerHTML;
      saveBtn.innerHTML = `<span class="spinner-border spinner-border-sm me-2" role="status" aria-hidden="true"></span>Saving...`;
      saveBtn.disabled = true;
      try {
        if (this.isAdmin) {
          // Admin context - save to global agents
          await this.saveGlobalAgent(agentData);
        } else {
          // User context - save to personal agents
          await this.savePersonalAgent(agentData);
        }
      //No catch to allow outer catch to handle errors
      } finally {
        saveBtn.innerHTML = originalText;
        saveBtn.disabled = false;
      }
      
    } catch (error) {
      console.error('Error saving agent:', error);
      if (errorDiv) {
        errorDiv.textContent = error.message;
        errorDiv.classList.remove('d-none');
      }
      if (window.showToast) {
        window.showToast(error.message, 'error');
      }
    }
  }

  getAgentFormData() {
    const formData = {
      display_name: document.getElementById('agent-display-name')?.value || '',
      name: document.getElementById('agent-name')?.value || '',
      description: document.getElementById('agent-description')?.value || '',
      instructions: document.getElementById('agent-instructions')?.value || '',
      model: document.getElementById('agent-global-model-select')?.value || '',
      custom_connection: document.getElementById('agent-custom-connection')?.checked || false,
      other_settings: document.getElementById('agent-additional-settings')?.value || '{}',
      max_completion_tokens: parseInt(document.getElementById('agent-max-completion-tokens')?.value.trim()) || null,
      agent_type: 'local'
    };
    
    // Handle model and deployment configuration
    if (formData.custom_connection) {
      // Custom connection - get values from custom fields
      const enableApim = document.getElementById('agent-enable-apim')?.checked || false;
      
      if (enableApim) {
        // APIM deployment fields - only include if they have values
        const apimEndpoint = document.getElementById('agent-apim-endpoint')?.value || '';
        const apimKey = document.getElementById('agent-apim-subscription-key')?.value || '';
        const apimDeployment = document.getElementById('agent-apim-deployment')?.value || '';
        const apimApiVersion = document.getElementById('agent-apim-api-version')?.value || '';
        
        if (apimEndpoint) formData.azure_agent_apim_gpt_endpoint = apimEndpoint;
        if (apimKey) formData.azure_agent_apim_gpt_subscription_key = apimKey;
        if (apimDeployment) formData.azure_agent_apim_gpt_deployment = apimDeployment;
        if (apimApiVersion) formData.azure_agent_apim_gpt_api_version = apimApiVersion;
        formData.enable_agent_gpt_apim = true;
      } else {
        // Non-APIM deployment fields - only include if they have values
        const gptEndpoint = document.getElementById('agent-gpt-endpoint')?.value || '';
        const gptKey = document.getElementById('agent-gpt-key')?.value || '';
        const gptDeployment = document.getElementById('agent-gpt-deployment')?.value || '';
        const gptApiVersion = document.getElementById('agent-gpt-api-version')?.value || '';
        
        if (gptEndpoint) formData.azure_openai_gpt_endpoint = gptEndpoint;
        if (gptKey) formData.azure_openai_gpt_key = gptKey;
        if (gptDeployment) formData.azure_openai_gpt_deployment = gptDeployment;
        if (gptApiVersion) formData.azure_openai_gpt_api_version = gptApiVersion;
        formData.enable_agent_gpt_apim = false;
      }
    } else {
      // Using global model - need to set at least one deployment field
      // We'll use the selected model as the deployment name for now
      if (formData.model) {
        formData.azure_openai_gpt_deployment = formData.model;
      }
    }
    
    return formData;
  }

  async saveGlobalAgent(agentData) {
    // For global agents, use the admin API endpoints
    if (this.isEditMode && this.originalAgent?.name) {
      // Update existing global agent
      const saveRes = await fetch(`/api/admin/agents/${encodeURIComponent(this.originalAgent.name)}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentData)
      });
      
      if (!saveRes.ok) {
        let errorMessage = 'Failed to save agent';
        try {
          const errorData = await saveRes.json();
          if (errorData.error) {
            errorMessage = errorData.error;
          }
        } catch (e) {
          // Fall back to status text if JSON parsing fails
          errorMessage = `Failed to save agent: ${saveRes.status} ${saveRes.statusText}`;
        }
        throw new Error(errorMessage);
      }
    } else {
      // Create new global agent
      const saveRes = await fetch('/api/admin/agents', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(agentData)
      });
      
      if (!saveRes.ok) {
        let errorMessage = 'Failed to save agent';
        try {
          const errorData = await saveRes.json();
          if (errorData.error) {
            errorMessage = errorData.error;
          }
        } catch (e) {
          // Fall back to status text if JSON parsing fails
          errorMessage = `Failed to save agent: ${saveRes.status} ${saveRes.statusText}`;
        }
        throw new Error(errorMessage);
      }
    }

    // Show success message and refresh
    this.handleSaveSuccess();
    
    // Refresh admin agents list if available
    if (window.loadAllAdminAgentData) {
      await window.loadAllAdminAgentData();
    }
  }

  async savePersonalAgent(agentData) {
    // For personal agents, use the user API endpoints
    const res = await fetch('/api/user/agents');
    let agents = [];
    if (res.ok) {
      agents = await res.json();
    }
    
    // If editing, replace; else, add
    const idx = this.isEditMode && this.originalAgent ? 
      agents.findIndex(a => a.id === this.originalAgent.id) : -1;
    
    if (idx >= 0) {
      agents[idx] = agentData;
    } else {
      agents.push(agentData);
    }
    
    const saveRes = await fetch('/api/user/agents', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(agents)
    });
    
    if (!saveRes.ok) {
      let errorMessage = 'Failed to save agent';
      try {
        const errorData = await saveRes.json();
        if (errorData.error) {
          errorMessage = errorData.error;
        }
      } catch (e) {
        // Fall back to status text if JSON parsing fails
        errorMessage = `Failed to save agent: ${saveRes.status} ${saveRes.statusText}`;
      }
      throw new Error(errorMessage);
    }

    // Show success message and refresh
    this.handleSaveSuccess();
    
    // Refresh workspace agents list if available
    if (window.fetchAgents) {
      await window.fetchAgents();
    }
  }

  handleSaveSuccess() {
    // Hide modal
    const modal = bootstrap.Modal.getInstance(document.getElementById('agentModal'));
    if (modal) {
      modal.hide();
    }
    
    // Show success message
    if (window.showToast) {
      window.showToast(`Agent ${this.isEditMode ? 'updated' : 'created'} successfully!`, 'success');
    }
  }
}

// Global instance will be created contextually by the calling code
// Do not create a default instance here to avoid conflicts between admin and user contexts
