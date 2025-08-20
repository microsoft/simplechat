// plugin_modal_stepper.js
// Multi-step modal functionality for action/plugin creation
import { showToast } from "./chat/chat-toast.js";

export class PluginModalStepper {
  constructor() {
    this.currentStep = 1;
    this.maxSteps = 4;
    this.selectedType = null;
    this.availableTypes = [];
    this.isEditMode = false;
    this.currentPage = 1;
    this.itemsPerPage = 12;
    this.filteredTypes = [];
    
    this.bindEvents();
  }

  bindEvents() {
    // Step navigation buttons
    document.getElementById('plugin-modal-next').addEventListener('click', () => this.nextStep());
    document.getElementById('plugin-modal-prev').addEventListener('click', () => this.prevStep());
    document.getElementById('plugin-modal-skip').addEventListener('click', () => this.skipToEnd());
    
    // Search functionality
    document.getElementById('action-type-search').addEventListener('input', (e) => this.filterActionTypes(e.target.value));
    
    // Auth type change handlers for both sections
    document.getElementById('plugin-auth-type').addEventListener('change', () => this.toggleOpenApiAuthFields());
    document.getElementById('plugin-auth-type-generic').addEventListener('change', () => this.toggleGenericAuthFields());
    
    // OpenAPI source selection handlers
    document.querySelectorAll('input[name="openapi-source"]').forEach(radio => {
      radio.addEventListener('change', () => this.toggleOpenApiSourceSections());
    });
    
    // File upload handler
    document.getElementById('plugin-openapi-file').addEventListener('change', (e) => this.handleFileUpload(e));
    
    // URL validation handler
    document.getElementById('validate-openapi-url').addEventListener('click', () => this.validateOpenApiUrl());
    
    // SQL Plugin event handlers
    document.querySelectorAll('input[name="sql-database-type"]').forEach(radio => {
      radio.addEventListener('change', () => this.handleSqlDatabaseTypeChange());
    });
    
    document.querySelectorAll('input[name="sql-plugin-type"]').forEach(radio => {
      radio.addEventListener('change', () => this.handleSqlPluginTypeChange());
    });
    
    document.querySelectorAll('input[name="sql-connection-method"]').forEach(radio => {
      radio.addEventListener('change', () => this.handleSqlConnectionMethodChange());
    });
    
    document.getElementById('sql-auth-type').addEventListener('change', () => this.handleSqlAuthTypeChange());
    
    // Auto-generate action name when display name changes
    document.getElementById('plugin-display-name').addEventListener('input', (e) => {
      const displayName = e.target.value.trim();
      if (displayName) {
        const actionName = this.generateActionName(displayName);
        document.getElementById('plugin-name').value = actionName;
      }
    });
  }

  async showModal(plugin = null) {
    this.isEditMode = !!plugin;
    this.selectedType = plugin?.type || null;
    
    // Reset modal state
    this.currentStep = 1;
    this.updateStepIndicator();
    this.showStep(1);
    this.updateNavigationButtons();
    
    // Set modal title
    const title = this.isEditMode ? 'Edit Action' : 'Add Action';
    document.getElementById('plugin-modal-title').textContent = title;
    
    // Clear error messages
    document.getElementById('plugin-modal-error').classList.add('d-none');
    
    // Load available types and populate
    await this.loadAvailableTypes();
    
    if (this.isEditMode) {
      this.populateFormFromPlugin(plugin);
      // Skip to step 2 for editing
      this.goToStep(2);
    } else {
      this.populateActionTypeCards();
    }
    
    // Show the modal
    const modal = new bootstrap.Modal(document.getElementById('plugin-modal'));
    modal.show();
    
    return modal;
  }

  async loadAvailableTypes() {
    try {
      // Determine the endpoint based on context (admin vs user)
      const endpoint = window.location.pathname.includes('admin') ? 
        '/api/admin/plugins/types' : '/api/user/plugins/types';
      
      const res = await fetch(endpoint);
      if (!res.ok) throw new Error('Failed to load action types');
      
      this.availableTypes = await res.json();
      this.filteredTypes = [...this.availableTypes]; // Initialize filtered types
    } catch (error) {
      console.error('Error loading action types:', error);
      showToast('Failed to load action types', 'danger');
      this.availableTypes = [];
      this.filteredTypes = [];
    }
  }

  populateActionTypeCards() {
    const container = document.getElementById('action-types-container');
    container.innerHTML = '';
    
    if (this.availableTypes.length === 0) {
      container.innerHTML = '<div class="col-12"><p class="text-muted">No action types available.</p></div>';
      return;
    }
    
    // Calculate pagination
    const startIndex = (this.currentPage - 1) * this.itemsPerPage;
    const endIndex = startIndex + this.itemsPerPage;
    const paginatedTypes = this.filteredTypes.slice(startIndex, endIndex);
    
    // Create cards for current page
    paginatedTypes.forEach(type => {
      const card = this.createActionTypeCard(type);
      container.appendChild(card);
    });
    
    // Add pagination controls
    this.addPaginationControls(container);
  }

  createActionTypeCard(type) {
    const col = document.createElement('div');
    col.className = 'col-md-6 col-lg-4';
    
    // Use backend-provided display and description
    const displayName = type.display || type.displayName || type.type || type.name;
    const description = type.description || `${displayName} action type`;
    
    // Truncate description if too long
    const maxLength = 120;
    const truncatedDescription = description.length > maxLength ? 
      description.substring(0, maxLength) + '...' : description;
    const needsTruncation = description.length > maxLength;
    
    col.innerHTML = `
      <div class="card action-type-card h-100" data-type="${type.type || type.name}">
        <div class="card-body">
          <h6 class="card-title">${this.escapeHtml(displayName)}</h6>
          <p class="card-text">
            <span class="description-short">${this.escapeHtml(truncatedDescription)}</span>
            ${needsTruncation ? `
              <span class="description-full d-none">${this.escapeHtml(description)}</span>
              <button type="button" class="btn btn-link btn-sm p-0 text-decoration-none view-more-btn">
                <small>View More</small>
              </button>
            ` : ''}
          </p>
        </div>
      </div>
    `;
    
    // Add click handler for card selection
    col.querySelector('.action-type-card').addEventListener('click', (e) => {
      // Don't trigger selection if clicking the "View More" button
      if (!e.target.classList.contains('view-more-btn')) {
        this.selectActionType(type.type || type.name);
      }
    });
    
    // Add view more/less functionality
    if (needsTruncation) {
      const viewMoreBtn = col.querySelector('.view-more-btn');
      viewMoreBtn.addEventListener('click', (e) => {
        e.stopPropagation();
        this.toggleDescription(col);
      });
    }
    
    return col;
  }

  selectActionType(typeName) {
    // Remove previous selection
    document.querySelectorAll('.action-type-card').forEach(card => {
      card.classList.remove('selected');
    });
    
    // Select new type
    const selectedCard = document.querySelector(`[data-type="${typeName}"]`);
    if (selectedCard) {
      selectedCard.classList.add('selected');
      this.selectedType = typeName;
      
      // Update hidden field
      document.getElementById('plugin-type').value = typeName;
      
      // Auto-populate description from type if available
      const typeData = this.availableTypes.find(t => (t.type || t.name) === typeName);
      if (typeData && typeData.description) {
        document.getElementById('plugin-description').value = typeData.description;
      }
      
      // Pre-configure for step 3 if needed
      this.showConfigSectionForType();
    }
  }

  filterActionTypes(searchTerm) {
    searchTerm = searchTerm.toLowerCase();
    
    // Filter types based on search term
    this.filteredTypes = this.availableTypes.filter(type => {
      const displayName = (type.display || type.displayName || type.type || type.name).toLowerCase();
      const description = (type.description || '').toLowerCase();
      return displayName.includes(searchTerm) || description.includes(searchTerm);
    });
    
    // Reset to first page when filtering
    this.currentPage = 1;
    
    // Repopulate cards with filtered results
    this.populateActionTypeCards();
  }

  toggleDescription(cardElement) {
    const shortDesc = cardElement.querySelector('.description-short');
    const fullDesc = cardElement.querySelector('.description-full');
    const btn = cardElement.querySelector('.view-more-btn');
    
    if (fullDesc.classList.contains('d-none')) {
      shortDesc.classList.add('d-none');
      fullDesc.classList.remove('d-none');
      btn.innerHTML = '<small>View Less</small>';
    } else {
      shortDesc.classList.remove('d-none');
      fullDesc.classList.add('d-none');
      btn.innerHTML = '<small>View More</small>';
    }
  }

  addPaginationControls(container) {
    const totalPages = Math.ceil(this.filteredTypes.length / this.itemsPerPage);
    
    if (totalPages <= 1) return; // No pagination needed
    
    const paginationRow = document.createElement('div');
    paginationRow.className = 'col-12 mt-3';
    
    paginationRow.innerHTML = `
      <nav aria-label="Action types pagination">
        <ul class="pagination justify-content-center mb-0">
          <li class="page-item ${this.currentPage === 1 ? 'disabled' : ''}">
            <a class="page-link" href="#" id="prev-page" aria-label="Previous">
              <span aria-hidden="true">&laquo;</span>
            </a>
          </li>
          <li class="page-item active">
            <span class="page-link">
              Page ${this.currentPage} of ${totalPages}
            </span>
          </li>
          <li class="page-item ${this.currentPage === totalPages ? 'disabled' : ''}">
            <a class="page-link" href="#" id="next-page" aria-label="Next">
              <span aria-hidden="true">&raquo;</span>
            </a>
          </li>
        </ul>
      </nav>
    `;
    
    container.appendChild(paginationRow);
    
    // Add event listeners for pagination
    const prevBtn = paginationRow.querySelector('#prev-page');
    const nextBtn = paginationRow.querySelector('#next-page');
    
    prevBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (this.currentPage > 1) {
        this.currentPage--;
        this.populateActionTypeCards();
      }
    });
    
    nextBtn.addEventListener('click', (e) => {
      e.preventDefault();
      if (this.currentPage < totalPages) {
        this.currentPage++;
        this.populateActionTypeCards();
      }
    });
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

  skipToEnd() {
    // Skip to the last step (configuration)
    this.goToStep(this.maxSteps);
  }

  goToStep(stepNumber) {
    if (stepNumber < 1 || stepNumber > this.maxSteps) return;
    
    this.currentStep = stepNumber;
    this.showStep(stepNumber);
    this.updateStepIndicator();
    this.updateNavigationButtons();
    
    // Handle step-specific logic
    if (stepNumber === 3) {
      this.showConfigSectionForType();
      this.toggleOpenApiAuthFields();
      this.toggleGenericAuthFields();
    }
  }

  showConfigSectionForType() {
    const openApiSection = document.getElementById('openapi-config-section');
    const genericSection = document.getElementById('generic-config-section');
    const sqlSection = document.getElementById('sql-config-section');
    
    // Determine plugin type
    const isOpenApiType = this.selectedType && this.selectedType.toLowerCase().includes('openapi');
    const isSqlType = this.selectedType && (
      this.selectedType.toLowerCase().includes('sql') || 
      this.selectedType.toLowerCase() === 'sql_schema' ||
      this.selectedType.toLowerCase() === 'sql_query'
    );
    
    if (isOpenApiType) {
      openApiSection.classList.remove('d-none');
      genericSection.classList.add('d-none');
      sqlSection.classList.add('d-none');
      // Initialize the source sections for OpenAPI
      this.toggleOpenApiSourceSections();
    } else if (isSqlType) {
      openApiSection.classList.add('d-none');
      genericSection.classList.add('d-none');
      sqlSection.classList.remove('d-none');
      // Initialize SQL plugin configuration
      this.initializeSqlConfiguration();
    } else {
      openApiSection.classList.add('d-none');
      genericSection.classList.remove('d-none');
      sqlSection.classList.add('d-none');
    }
  }

  showStep(stepNumber) {
    // Hide all steps
    document.querySelectorAll('.plugin-step').forEach(step => {
      step.classList.add('d-none');
    });
    
    // Show current step
    const currentStepEl = document.getElementById(`plugin-step-${stepNumber}`);
    if (currentStepEl) {
      currentStepEl.classList.remove('d-none');
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
    const nextBtn = document.getElementById('plugin-modal-next');
    const prevBtn = document.getElementById('plugin-modal-prev');
    const skipBtn = document.getElementById('plugin-modal-skip');
    const saveBtn = document.getElementById('save-plugin-btn');
    
    // Previous button
    if (this.currentStep === 1) {
      prevBtn.classList.add('d-none');
    } else {
      prevBtn.classList.remove('d-none');
    }
    
    // Next/Save button
    if (this.currentStep === this.maxSteps) {
      nextBtn.classList.add('d-none');
      saveBtn.classList.remove('d-none');
    } else {
      nextBtn.classList.remove('d-none');
      saveBtn.classList.add('d-none');
    }
    
    // Skip button (show on steps 2 and 3, hide on 1 and 4)
    if (this.currentStep === 2 || this.currentStep === 3) {
      skipBtn.classList.remove('d-none');
    } else {
      skipBtn.classList.add('d-none');
    }
  }

  validateCurrentStep() {
    const errorDiv = document.getElementById('plugin-modal-error');
    errorDiv.classList.add('d-none');
    
    switch (this.currentStep) {
      case 1:
        if (!this.selectedType) {
          this.showError('Please select an action type.');
          return false;
        }
        break;
        
      case 2:
        const displayName = document.getElementById('plugin-display-name').value.trim();
        if (!displayName) {
          this.showError('Display name is required.');
          return false;
        }
        
        // Auto-generate action name from display name
        const actionName = this.generateActionName(displayName);
        document.getElementById('plugin-name').value = actionName;
        
        if (!/^[^\s]+$/.test(actionName)) {
          this.showError('Generated action name cannot contain spaces. Please use a simpler display name.');
          return false;
        }
        break;
        
      case 3:
        // Validate based on which config section is visible
        const openApiSection = document.getElementById('openapi-config-section');
        const sqlSection = document.getElementById('sql-config-section');
        const isOpenApiVisible = !openApiSection.classList.contains('d-none');
        const isSqlVisible = !sqlSection.classList.contains('d-none');
        
        if (isOpenApiVisible) {
          // Validate OpenAPI fields based on source type
          const selectedSource = document.querySelector('input[name="openapi-source"]:checked').value;
          const endpoint = document.getElementById('plugin-endpoint').value.trim();
          
          // Validate source-specific fields
          if (selectedSource === 'file') {
            const fileInput = document.getElementById('plugin-openapi-file');
            if (!fileInput.files || fileInput.files.length === 0) {
              this.showError('OpenAPI specification file is required.');
              return false;
            }
          } else if (selectedSource === 'url') {
            const url = document.getElementById('plugin-openapi-url').value.trim();
            if (!url) {
              this.showError('OpenAPI specification URL is required.');
              return false;
            }
          }
          
          if (!endpoint) {
            this.showError('Base URL is required.');
            return false;
          }
          
          // Validate auth fields for OpenAPI
          const authType = document.getElementById('plugin-auth-type').value;
          if (authType === 'api_key') {
            const keyName = document.getElementById('plugin-auth-api-key-name').value.trim();
            const keyValue = document.getElementById('plugin-auth-api-key-value').value.trim();
            if (!keyName || !keyValue) {
              this.showError('API key name and value are required.');
              return false;
            }
          } else if (authType === 'bearer') {
            const token = document.getElementById('plugin-auth-bearer-token').value.trim();
            if (!token) {
              this.showError('Bearer token is required.');
              return false;
            }
          } else if (authType === 'basic') {
            const username = document.getElementById('plugin-auth-basic-username').value.trim();
            const password = document.getElementById('plugin-auth-basic-password').value.trim();
            if (!username || !password) {
              this.showError('Username and password are required for basic auth.');
              return false;
            }
          } else if (authType === 'oauth2') {
            const token = document.getElementById('plugin-auth-oauth2-token').value.trim();
            if (!token) {
              this.showError('OAuth2 access token is required.');
              return false;
            }
          }
        } else if (isSqlVisible) {
          // Validate SQL configuration
          const selectedDbType = document.querySelector('input[name="sql-database-type"]:checked');
          if (!selectedDbType) {
            this.showError('Database type is required.');
            return false;
          }
          
          const selectedPluginType = document.querySelector('input[name="sql-plugin-type"]:checked');
          if (!selectedPluginType) {
            this.showError('Plugin type is required.');
            return false;
          }
          
          const selectedConnectionMethod = document.querySelector('input[name="sql-connection-method"]:checked');
          if (!selectedConnectionMethod) {
            this.showError('Connection method is required.');
            return false;
          }
          
          // Validate connection method specific fields
          if (selectedConnectionMethod.value === 'connection-string') {
            // No additional validation needed for connection string method
          } else if (selectedConnectionMethod.value === 'individual-parameters') {
            const server = document.getElementById('sql-server').value.trim();
            const database = document.getElementById('sql-database').value.trim();
            
            if (!server) {
              this.showError('Server is required.');
              return false;
            }
            
            if (!database) {
              this.showError('Database is required.');
              return false;
            }
            
            // Validate authentication for individual parameters
            const sqlAuthType = document.getElementById('sql-auth-type').value;
            if (sqlAuthType === 'username-password') {
              const username = document.getElementById('sql-username').value.trim();
              const password = document.getElementById('sql-password').value.trim();
              
              if (!username) {
                this.showError('Username is required.');
                return false;
              }
              
              if (!password) {
                this.showError('Password is required.');
                return false;
              }
            }
          }
        } else {
          // Validate generic endpoint field
          const endpoint = document.getElementById('plugin-endpoint-generic').value.trim();
          if (!endpoint) {
            this.showError('Endpoint is required.');
            return false;
          }
        }
        break;
        
      case 4:
        // Validate JSON fields
        if (!this.validateJSONField('plugin-metadata', 'Metadata')) return false;
        if (!this.validateJSONField('plugin-additional-fields', 'Additional Fields')) return false;
        break;
    }
    
    return true;
  }

  validateJSONField(fieldId, fieldName) {
    const field = document.getElementById(fieldId);
    const value = field.value.trim();
    
    if (value && value !== '{}') {
      try {
        const parsed = JSON.parse(value);
        if (typeof parsed !== 'object' || Array.isArray(parsed)) {
          throw new Error(`${fieldName} must be a JSON object`);
        }
      } catch (e) {
        this.showError(`${fieldName}: ${e.message}`);
        return false;
      }
    }
    
    return true;
  }

  showError(message) {
    const errorDiv = document.getElementById('plugin-modal-error');
    errorDiv.textContent = message;
    errorDiv.classList.remove('d-none');
  }

  toggleOpenApiAuthFields() {
    const authType = document.getElementById('plugin-auth-type').value;
    const groups = {
      apiKeyLocation: document.getElementById('auth-api-key-location-group'),
      apiKeyName: document.getElementById('auth-api-key-name-group'),
      apiKeyValue: document.getElementById('auth-api-key-value-group'),
      bearer: document.getElementById('auth-bearer-group'),
      basicUsername: document.getElementById('auth-basic-username-group'),
      basicPassword: document.getElementById('auth-basic-password-group'),
      oauth2: document.getElementById('auth-oauth2-group')
    };
    
    // Hide all groups first
    Object.values(groups).forEach(group => {
      if (group) group.style.display = 'none';
    });
    
    // Show relevant groups based on auth type
    switch (authType) {
      case 'api_key':
        if (groups.apiKeyLocation) groups.apiKeyLocation.style.display = 'flex';
        if (groups.apiKeyName) groups.apiKeyName.style.display = 'flex';
        if (groups.apiKeyValue) groups.apiKeyValue.style.display = 'flex';
        break;
      case 'bearer':
        if (groups.bearer) groups.bearer.style.display = 'flex';
        break;
      case 'basic':
        if (groups.basicUsername) groups.basicUsername.style.display = 'flex';
        if (groups.basicPassword) groups.basicPassword.style.display = 'flex';
        break;
      case 'oauth2':
        if (groups.oauth2) groups.oauth2.style.display = 'flex';
        break;
      case 'none':
        // No additional fields needed
        break;
    }
  }

  toggleOpenApiSourceSections() {
    const selectedSource = document.querySelector('input[name="openapi-source"]:checked').value;
    const fileSection = document.getElementById('openapi-file-section');
    const urlSection = document.getElementById('openapi-url-section');

    // Hide all sections first
    fileSection.classList.add('d-none');
    urlSection.classList.add('d-none');

    // Show the selected section
    switch (selectedSource) {
      case 'file':
        fileSection.classList.remove('d-none');
        break;
      case 'url':
        urlSection.classList.remove('d-none');
        break;
    }
  }

  async handleFileUpload(event) {
    const file = event.target.files[0];
    const statusDiv = document.getElementById('openapi-file-status');
    
    if (!file) {
      statusDiv.innerHTML = '';
      return;
    }

    // Clear previous status
    statusDiv.innerHTML = '<div class="spinner-border spinner-border-sm me-2" role="status"></div>Uploading and validating...';
    statusDiv.className = 'mt-2 text-info';

    // Create FormData for upload
    const formData = new FormData();
    formData.append('file', file);

    try {
      const response = await fetch('/api/openapi/upload', {
        method: 'POST',
        body: formData
      });

      const result = await response.json();

      if (response.ok) {
        statusDiv.innerHTML = `
          <i class="fas fa-check-circle me-2"></i>
          File uploaded and validated successfully!
          <br><small class="text-muted">File ID: ${result.file_id}</small>
        `;
        statusDiv.className = 'mt-2 text-success';

        // Store the file ID for later use
        document.getElementById('plugin-openapi-file').dataset.fileId = result.file_id;

        // Display API info if available
        if (result.api_info) {
          this.displayOpenApiInfo(result.api_info);
        }
      } else {
        statusDiv.innerHTML = `<i class="fas fa-exclamation-triangle me-2"></i>${result.error || 'Upload failed'}`;
        statusDiv.className = 'mt-2 text-danger';
      }
    } catch (error) {
      console.error('Upload error:', error);
      statusDiv.innerHTML = `<i class="fas fa-exclamation-triangle me-2"></i>Upload failed: ${error.message}`;
      statusDiv.className = 'mt-2 text-danger';
    }
  }

  async validateOpenApiUrl() {
    const urlInput = document.getElementById('plugin-openapi-url');
    const statusDiv = document.getElementById('openapi-url-status');
    const validateBtn = document.getElementById('validate-openapi-url');
    
    const url = urlInput.value.trim();
    if (!url) {
      statusDiv.innerHTML = '<i class="fas fa-exclamation-triangle me-2"></i>Please enter a URL';
      statusDiv.className = 'mt-2 text-warning';
      return;
    }

    // Disable button and show loading
    validateBtn.disabled = true;
    validateBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span>Validating...';
    
    statusDiv.innerHTML = '<div class="spinner-border spinner-border-sm me-2" role="status"></div>Downloading and validating...';
    statusDiv.className = 'mt-2 text-info';

    try {
      const response = await fetch('/api/openapi/validate-url', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({ url: url })
      });

      const result = await response.json();

      if (response.ok) {
        statusDiv.innerHTML = `
          <i class="fas fa-check-circle me-2"></i>
          URL validated successfully!
          <br><small class="text-muted">File ID: ${result.file_id}</small>
        `;
        statusDiv.className = 'mt-2 text-success';

        // Store the file ID for later use
        urlInput.dataset.fileId = result.file_id;

        // Display API info if available
        if (result.api_info) {
          this.displayOpenApiInfo(result.api_info);
        }
      } else {
        statusDiv.innerHTML = `<i class="fas fa-exclamation-triangle me-2"></i>${result.error || 'Validation failed'}`;
        statusDiv.className = 'mt-2 text-danger';
      }
    } catch (error) {
      console.error('Validation error:', error);
      statusDiv.innerHTML = `<i class="fas fa-exclamation-triangle me-2"></i>Validation failed: ${error.message}`;
      statusDiv.className = 'mt-2 text-danger';
    } finally {
      // Re-enable button
      validateBtn.disabled = false;
      validateBtn.innerHTML = '<i class="fas fa-check me-1"></i>Validate';
    }
  }

  displayOpenApiInfo(apiInfo) {
    const infoDisplay = document.getElementById('openapi-info-display');
    const infoContent = document.getElementById('openapi-info-content');
    
    let infoHtml = '';
    if (apiInfo.title) {
      infoHtml += `<strong>Title:</strong> ${this.escapeHtml(apiInfo.title)}<br>`;
    }
    if (apiInfo.version) {
      infoHtml += `<strong>Version:</strong> ${this.escapeHtml(apiInfo.version)}<br>`;
    }
    if (apiInfo.description) {
      infoHtml += `<strong>Description:</strong> ${this.escapeHtml(apiInfo.description)}<br>`;
    }
    if (apiInfo.servers && apiInfo.servers.length > 0) {
      infoHtml += `<strong>Servers:</strong><br>`;
      apiInfo.servers.forEach(server => {
        infoHtml += `&nbsp;&nbsp;• ${this.escapeHtml(server.url)}`;
        if (server.description) {
          infoHtml += ` - ${this.escapeHtml(server.description)}`;
        }
        infoHtml += '<br>';
      });
    }
    if (apiInfo.endpoints_count) {
      infoHtml += `<strong>Endpoints:</strong> ${apiInfo.endpoints_count}<br>`;
    }

    infoContent.innerHTML = infoHtml;
    infoDisplay.classList.remove('d-none');
  }

  toggleAuthFields() {
    this.toggleGenericAuthFields();
  }

  toggleGenericAuthFields() {
    const authType = document.getElementById('plugin-auth-type-generic').value;
    const identityGroup = document.getElementById('auth-identity-group');
    const keyGroup = document.getElementById('auth-key-group');
    const tenantIdGroup = document.getElementById('auth-tenantid-group');
    
    // Hide all groups first
    [identityGroup, keyGroup, tenantIdGroup].forEach(group => {
      if (group) group.style.display = 'none';
    });
    
    // Show relevant groups based on auth type
    switch (authType) {
      case 'key':
        if (keyGroup) keyGroup.style.display = 'flex';
        break;
      case 'identity':
        if (identityGroup) identityGroup.style.display = 'flex';
        break;
      case 'servicePrincipal':
        if (identityGroup) identityGroup.style.display = 'flex';
        if (keyGroup) keyGroup.style.display = 'flex';
        if (tenantIdGroup) tenantIdGroup.style.display = 'flex';
        break;
      case 'user':
        // No additional fields needed
        break;
    }
  }

  // SQL Plugin Configuration Methods
  initializeSqlConfiguration() {
    // Set default values
    document.getElementById('sql-read-only').value = 'true';
    document.getElementById('sql-max-rows').value = '1000';
    document.getElementById('sql-timeout').value = '30';
    document.getElementById('sql-include-system-tables').value = 'false';
    
    // Initialize connection examples
    this.updateSqlConnectionExamples();
    
    // Initialize auth info
    this.updateSqlAuthInfo();
    
    // Show/hide relevant sections
    this.handleSqlPluginTypeChange();
    this.handleSqlDatabaseTypeChange();
    this.handleSqlConnectionMethodChange();
    this.handleSqlAuthTypeChange();
  }

  handleSqlDatabaseTypeChange() {
    const selectedType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
    
    if (!selectedType) return;
    
    // Update connection examples
    this.updateSqlConnectionExamples();
    
    // Show/hide fields based on database type
    const serverField = document.getElementById('sql-server-field');
    const portField = document.getElementById('sql-port-field');
    const driverField = document.getElementById('sql-driver-field');
    const databaseField = document.getElementById('sql-database-field');
    const authTypeSelect = document.getElementById('sql-auth-type');
    
    if (selectedType === 'sqlite') {
      serverField.style.display = 'none';
      portField.style.display = 'none';
      driverField.style.display = 'none';
      databaseField.querySelector('label').textContent = 'Database File Path';
      databaseField.querySelector('input').placeholder = '/path/to/database.db';
      databaseField.querySelector('.form-text').textContent = 'Full path to the SQLite database file';
      
      // Limit auth options for SQLite
      authTypeSelect.innerHTML = `
        <option value="connection_string_only">File Path Only</option>
      `;
    } else {
      serverField.style.display = 'block';
      portField.style.display = 'block';
      databaseField.querySelector('label').textContent = 'Database';
      databaseField.querySelector('input').placeholder = 'database_name';
      databaseField.querySelector('.form-text').textContent = 'Database name';
      
      // Show/hide driver field for SQL Server
      if (selectedType === 'sqlserver' || selectedType === 'azure_sql') {
        driverField.style.display = 'block';
      } else {
        driverField.style.display = 'none';
      }
      
      // Set auth options based on database type
      if (selectedType === 'azure_sql') {
        authTypeSelect.innerHTML = `
          <option value="managed_identity">Managed Identity (Recommended)</option>
          <option value="username_password">Username & Password</option>
          <option value="service_principal">Service Principal</option>
          <option value="connection_string_only">Connection String Only</option>
        `;
      } else {
        authTypeSelect.innerHTML = `
          <option value="username_password">Username & Password</option>
          <option value="integrated">Integrated Authentication</option>
          <option value="connection_string_only">Connection String Only</option>
        `;
      }
    }
    
    // Update port placeholder
    this.updatePortPlaceholder(selectedType);
    
    // Trigger auth type change to update fields
    this.handleSqlAuthTypeChange();
  }

  handleSqlPluginTypeChange() {
    const selectedType = document.querySelector('input[name="sql-plugin-type"]:checked')?.value;
    
    const querySettings = document.getElementById('sql-query-settings');
    const schemaSettings = document.getElementById('sql-schema-settings');
    
    if (selectedType === 'query') {
      querySettings.classList.remove('d-none');
      schemaSettings.classList.add('d-none');
    } else if (selectedType === 'schema') {
      querySettings.classList.add('d-none');
      schemaSettings.classList.remove('d-none');
    } else {
      querySettings.classList.add('d-none');
      schemaSettings.classList.add('d-none');
    }
  }

  handleSqlConnectionMethodChange() {
    const selectedMethod = document.querySelector('input[name="sql-connection-method"]:checked')?.value;
    
    const stringSection = document.getElementById('sql-connection-string-section');
    const paramsSection = document.getElementById('sql-connection-params-section');
    
    if (selectedMethod === 'connection_string') {
      stringSection.classList.remove('d-none');
      paramsSection.classList.add('d-none');
    } else {
      stringSection.classList.add('d-none');
      paramsSection.classList.remove('d-none');
    }
  }

  handleSqlAuthTypeChange() {
    const authType = document.getElementById('sql-auth-type').value;
    const credentialsDiv = document.getElementById('sql-auth-credentials');
    const servicePrincipalDiv = document.getElementById('sql-auth-service-principal');
    
    // Hide all auth sections first
    credentialsDiv.style.display = 'none';
    servicePrincipalDiv.style.display = 'none';
    
    // Show relevant sections
    switch (authType) {
      case 'username_password':
        credentialsDiv.style.display = 'block';
        break;
      case 'service_principal':
        servicePrincipalDiv.style.display = 'block';
        break;
      case 'integrated':
      case 'managed_identity':
      case 'connection_string_only':
        // No additional fields needed
        break;
    }
    
    // Update auth info
    this.updateSqlAuthInfo();
  }

  updateSqlConnectionExamples() {
    const selectedType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
    const examplesDiv = document.getElementById('sql-connection-examples');
    
    if (!selectedType || !examplesDiv) return;
    
    const examples = this.getSqlConnectionExamples(selectedType);
    examplesDiv.innerHTML = examples;
  }

  getSqlConnectionExamples(dbType) {
    const examples = {
      sqlserver: `
        <div class="example"><strong>SQL Server:</strong> DRIVER={ODBC Driver 17 for SQL Server};SERVER=server.com;DATABASE=mydb;UID=user;PWD=pass</div>
        <div class="example"><strong>Integrated Auth:</strong> DRIVER={ODBC Driver 17 for SQL Server};SERVER=server.com;DATABASE=mydb;Trusted_Connection=yes</div>
      `,
      azure_sql: `
        <div class="example"><strong>Managed Identity:</strong> DRIVER={ODBC Driver 17 for SQL Server};SERVER=server.database.windows.net;DATABASE=mydb;Authentication=ActiveDirectoryMsi</div>
        <div class="example"><strong>Username/Password:</strong> DRIVER={ODBC Driver 17 for SQL Server};SERVER=server.database.windows.net;DATABASE=mydb;UID=user;PWD=pass</div>
      `,
      postgresql: `
        <div class="example"><strong>PostgreSQL:</strong> host=localhost dbname=mydb user=username password=password port=5432</div>
        <div class="example"><strong>With SSL:</strong> host=server.com dbname=mydb user=username password=password sslmode=require</div>
      `,
      mysql: `
        <div class="example"><strong>MySQL:</strong> mysql://username:password@localhost:3306/database_name</div>
        <div class="example"><strong>With SSL:</strong> mysql://username:password@server.com:3306/database_name?ssl=true</div>
      `,
      sqlite: `
        <div class="example"><strong>SQLite:</strong> /path/to/your/database.db</div>
        <div class="example"><strong>Relative path:</strong> ./data/database.db</div>
      `
    };
    
    return examples[dbType] || '';
  }

  updatePortPlaceholder(dbType) {
    const portInput = document.getElementById('sql-port');
    if (!portInput) return;
    
    const defaultPorts = {
      sqlserver: '1433',
      azure_sql: '1433',
      postgresql: '5432',
      mysql: '3306'
    };
    
    portInput.placeholder = defaultPorts[dbType] || 'Auto-detect';
  }

  updateSqlAuthInfo() {
    const authType = document.getElementById('sql-auth-type').value;
    const dbType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
    const infoDiv = document.getElementById('sql-auth-info');
    const infoText = document.getElementById('sql-auth-info-text');
    
    if (!infoDiv || !infoText) return;
    
    let message = '';
    
    switch (authType) {
      case 'managed_identity':
        message = 'Managed Identity uses Azure AD authentication without storing credentials. Ensure your application has the appropriate database permissions assigned.';
        break;
      case 'service_principal':
        message = 'Service Principal authentication uses Azure AD application credentials. Store client secrets securely and rotate them regularly.';
        break;
      case 'integrated':
        message = 'Integrated Authentication uses Windows credentials of the running application. Ensure the application service account has database access.';
        break;
      case 'username_password':
        message = 'Username and password authentication stores credentials in the configuration. Consider using more secure authentication methods for production.';
        break;
      case 'connection_string_only':
        message = 'Connection string contains all authentication details. Ensure the string is properly secured and not logged in plain text.';
        break;
    }
    
    if (message) {
      infoText.textContent = message;
      infoDiv.classList.remove('d-none');
    } else {
      infoDiv.classList.add('d-none');
    }
  }

  populateFormFromPlugin(plugin) {
    // Step 2 fields
    document.getElementById('plugin-name').value = plugin.name || '';
    document.getElementById('plugin-display-name').value = plugin.displayName || '';
    document.getElementById('plugin-description').value = plugin.description || '';
    document.getElementById('plugin-type').value = plugin.type || '';
    
    // Step 3 fields - populate based on plugin type
    const isOpenApiType = plugin.type && plugin.type.toLowerCase().includes('openapi');
    
    if (isOpenApiType) {
      // Populate OpenAPI fields
      const additionalFields = plugin.additionalFields || {};
      document.getElementById('plugin-endpoint').value = plugin.endpoint || additionalFields.base_url || '';
      
      const auth = plugin.auth || {};
      let authType = 'none';
      
      // Map from our OpenAPI auth format to modal format
      if (auth.type === 'api_key') {
        authType = 'api_key';
        document.getElementById('plugin-auth-api-key-location').value = auth.location || 'header';
        document.getElementById('plugin-auth-api-key-name').value = auth.name || '';
        document.getElementById('plugin-auth-api-key-value').value = auth.value || '';
      } else if (auth.type === 'bearer') {
        authType = 'bearer';
        document.getElementById('plugin-auth-bearer-token').value = auth.token || '';
      } else if (auth.type === 'basic') {
        authType = 'basic';
        document.getElementById('plugin-auth-basic-username').value = auth.username || '';
        document.getElementById('plugin-auth-basic-password').value = auth.password || '';
      } else if (auth.type === 'oauth2') {
        authType = 'oauth2';
        document.getElementById('plugin-auth-oauth2-token').value = auth.access_token || '';
      }
      
      document.getElementById('plugin-auth-type').value = authType;
    } else {
      // Populate generic fields
      document.getElementById('plugin-endpoint-generic').value = plugin.endpoint || '';
      
      const auth = plugin.auth || {};
      let authType = auth.type || 'key';
      if (authType === 'managedIdentity') authType = 'identity'; // Legacy support
      
      document.getElementById('plugin-auth-type-generic').value = authType;
      document.getElementById('plugin-auth-key').value = auth.key || '';
      document.getElementById('plugin-auth-identity').value = auth.identity || auth.managedIdentity || '';
      document.getElementById('plugin-auth-tenant-id').value = auth.tenantId || '';
    }
    
    // Step 4 fields
    const metadata = plugin.metadata && Object.keys(plugin.metadata).length > 0 ? 
      JSON.stringify(plugin.metadata, null, 2) : '{}';
    const additionalFields = plugin.additionalFields && Object.keys(plugin.additionalFields).length > 0 ? 
      JSON.stringify(plugin.additionalFields, null, 2) : '{}';
    
    document.getElementById('plugin-metadata').value = metadata;
    document.getElementById('plugin-additional-fields').value = additionalFields;
  }

  getFormData() {
    // Determine which configuration section is active
    const openApiSection = document.getElementById('openapi-config-section');
    const sqlSection = document.getElementById('sql-config-section');
    const isOpenApiVisible = !openApiSection.classList.contains('d-none');
    const isSqlVisible = !sqlSection.classList.contains('d-none');
    
    let auth = {};
    let endpoint = '';
    let additionalFields = {};
    
    if (isOpenApiVisible) {
      // Collect OpenAPI-specific data
      endpoint = document.getElementById('plugin-endpoint').value.trim();
      
      // Handle OpenAPI spec source
      const selectedSource = document.querySelector('input[name="openapi-source"]:checked').value;
      additionalFields.openapi_source_type = selectedSource;
      
      if (selectedSource === 'file') {
        const fileInput = document.getElementById('plugin-openapi-file');
        const fileId = fileInput.dataset.fileId;
        if (!fileId) {
          throw new Error('Please upload an OpenAPI specification file');
        }
        additionalFields.openapi_file_id = fileId;
      } else if (selectedSource === 'url') {
        const urlInput = document.getElementById('plugin-openapi-url');
        const url = urlInput.value.trim();
        const fileId = urlInput.dataset.fileId;
        if (!url) {
          throw new Error('Please enter an OpenAPI specification URL');
        }
        if (!fileId) {
          throw new Error('Please validate the OpenAPI specification URL');
        }
        additionalFields.openapi_url = url;
        additionalFields.openapi_file_id = fileId;
      }
      
      additionalFields.base_url = endpoint;
      
      const authType = document.getElementById('plugin-auth-type').value;
      auth.type = authType;
      
      if (authType === 'api_key') {
        auth.location = document.getElementById('plugin-auth-api-key-location').value;
        auth.name = document.getElementById('plugin-auth-api-key-name').value.trim();
        auth.value = document.getElementById('plugin-auth-api-key-value').value.trim();
      } else if (authType === 'bearer') {
        auth.token = document.getElementById('plugin-auth-bearer-token').value.trim();
      } else if (authType === 'basic') {
        auth.username = document.getElementById('plugin-auth-basic-username').value.trim();
        auth.password = document.getElementById('plugin-auth-basic-password').value.trim();
      } else if (authType === 'oauth2') {
        auth.access_token = document.getElementById('plugin-auth-oauth2-token').value.trim();
      } else if (authType === 'none') {
        auth = {}; // No auth needed
      }
    } else if (isSqlVisible) {
      // Collect SQL plugin data
      const databaseType = document.querySelector('input[name="sql-database-type"]:checked')?.value;
      const pluginType = document.querySelector('input[name="sql-plugin-type"]:checked')?.value;
      const connectionMethod = document.querySelector('input[name="sql-connection-method"]:checked')?.value;
      const authType = document.getElementById('sql-auth-type').value;
      
      if (!databaseType) {
        throw new Error('Please select a database type');
      }
      if (!pluginType) {
        throw new Error('Please select a plugin type (Schema or Query)');
      }
      
      // Set the actual plugin type based on selection
      this.selectedType = pluginType === 'schema' ? 'sql_schema' : 'sql_query';
      
      // Database configuration
      additionalFields.database_type = databaseType;
      
      if (connectionMethod === 'connection_string') {
        const connectionString = document.getElementById('sql-connection-string').value.trim();
        if (!connectionString) {
          throw new Error('Please enter a connection string');
        }
        additionalFields.connection_string = connectionString;
      } else {
        // Individual parameters
        if (databaseType !== 'sqlite') {
          const server = document.getElementById('sql-server').value.trim();
          if (!server) {
            throw new Error('Please enter the server name');
          }
          additionalFields.server = server;
          
          const port = document.getElementById('sql-port').value.trim();
          if (port) {
            additionalFields.port = parseInt(port);
          }
          
          if (databaseType === 'sqlserver' || databaseType === 'azure_sql') {
            additionalFields.driver = document.getElementById('sql-driver').value;
          }
        }
        
        const database = document.getElementById('sql-database').value.trim();
        if (!database) {
          throw new Error('Please enter the database name/path');
        }
        additionalFields.database = database;
      }
      
      // Authentication configuration
      auth.type = authType;
      
      switch (authType) {
        case 'username_password':
          const username = document.getElementById('sql-username').value.trim();
          const password = document.getElementById('sql-password').value.trim();
          if (!username || !password) {
            throw new Error('Please enter both username and password');
          }
          additionalFields.username = username;
          additionalFields.password = password;
          break;
          
        case 'service_principal':
          const clientId = document.getElementById('sql-client-id').value.trim();
          const clientSecret = document.getElementById('sql-client-secret').value.trim();
          const tenantId = document.getElementById('sql-tenant-id').value.trim();
          if (!clientId || !clientSecret || !tenantId) {
            throw new Error('Please enter client ID, client secret, and tenant ID');
          }
          auth.client_id = clientId;
          auth.client_secret = clientSecret;
          auth.tenant_id = tenantId;
          break;
          
        case 'integrated':
        case 'managed_identity':
        case 'connection_string_only':
          // No additional fields needed
          break;
      }
      
      // Plugin-specific settings
      if (pluginType === 'query') {
        additionalFields.read_only = document.getElementById('sql-read-only').value === 'true';
        additionalFields.max_rows = parseInt(document.getElementById('sql-max-rows').value) || 1000;
        additionalFields.timeout = parseInt(document.getElementById('sql-timeout').value) || 30;
      } else if (pluginType === 'schema') {
        additionalFields.include_system_tables = document.getElementById('sql-include-system-tables').value === 'true';
        const tableFilter = document.getElementById('sql-table-filter').value.trim();
        if (tableFilter) {
          additionalFields.table_filter = tableFilter;
        }
      }
      
      // For SQL plugins, endpoint is not applicable
      endpoint = '';
    } else {
      // Collect generic plugin data
      endpoint = document.getElementById('plugin-endpoint-generic').value.trim();
      
      const authType = document.getElementById('plugin-auth-type-generic').value;
      auth.type = authType;
      
      if (authType === 'key') {
        auth.key = document.getElementById('plugin-auth-key').value.trim();
      } else if (authType === 'identity') {
        auth.identity = document.getElementById('plugin-auth-identity').value.trim();
      } else if (authType === 'servicePrincipal') {
        auth.identity = document.getElementById('plugin-auth-identity').value.trim();
        auth.key = document.getElementById('plugin-auth-key').value.trim();
        auth.tenantId = document.getElementById('plugin-auth-tenant-id').value.trim();
      }
    }
    
    // Parse existing additional fields and merge
    try {
      const additionalFieldsValue = document.getElementById('plugin-additional-fields').value.trim();
      const existingAdditionalFields = additionalFieldsValue ? JSON.parse(additionalFieldsValue) : {};
      additionalFields = { ...existingAdditionalFields, ...additionalFields };
    } catch (e) {
      throw new Error('Invalid additional fields JSON');
    }
    
    let metadata = {};
    try {
      const metadataValue = document.getElementById('plugin-metadata').value.trim();
      metadata = metadataValue ? JSON.parse(metadataValue) : {};
    } catch (e) {
      throw new Error('Invalid metadata JSON');
    }
    
    return {
      name: document.getElementById('plugin-name').value.trim(),
      displayName: document.getElementById('plugin-display-name').value.trim(),
      type: this.selectedType,
      description: document.getElementById('plugin-description').value.trim(),
      endpoint,
      auth,
      metadata,
      additionalFields
    };
  }

  generateActionName(displayName) {
    // Convert display name to a valid action name
    return displayName
      .toLowerCase()                 // Convert to lowercase
      .replace(/[^a-z0-9\s]/g, '')  // Remove special characters except spaces
      .replace(/\s+/g, '_')         // Replace spaces with underscores
      .replace(/_+/g, '_')          // Replace multiple underscores with single
      .replace(/^_|_$/g, '');       // Remove leading and trailing underscores
  }

  escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }
}

// Create global instance
window.pluginModalStepper = new PluginModalStepper();
