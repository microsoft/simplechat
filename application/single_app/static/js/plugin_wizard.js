// plugin_wizard.js
// Multi-step wizard for plugin creation and editing

export class PluginWizard {
    constructor() {
        this.currentStep = 1;
        this.maxSteps = 5; // Updated to 5 steps
        this.pluginTypes = [];
        this.filteredTypes = [];
        this.currentPage = 1;
        this.itemsPerPage = 12;
        this.selectedPluginType = null;
        this.editingPlugin = null;
        this.stepValidationState = {
            1: false, 2: false, 3: false, 4: true, 5: false // Step 4 (advanced) is optional
        };
        
        this.initializeElements();
        this.bindEvents();
    }

    initializeElements() {
        // Modal elements
        this.modal = document.getElementById('plugin-modal');
        this.modalTitle = document.getElementById('plugin-modal-title');
        this.stepProgressContainer = document.querySelector('.step-progress-container');
        this.errorDiv = document.getElementById('plugin-modal-error');

        // Step content elements
        this.stepContents = {
            1: document.getElementById('step-1'),
            2: document.getElementById('step-2'), 
            3: document.getElementById('step-3'),
            4: document.getElementById('step-4'),
            5: document.getElementById('step-5')
        };

        // Step indicators
        this.stepItems = document.querySelectorAll('.step-item');

        // Step 1 elements
        this.typeSearch = document.getElementById('plugin-type-search');
        this.typesContainer = document.getElementById('plugin-types-container');
        this.typesPagination = document.getElementById('plugin-types-pagination');

        // Step 2 elements
        this.displayNameField = document.getElementById('plugin-display-name');
        this.nameField = document.getElementById('plugin-name');
        this.descriptionField = document.getElementById('plugin-description');

        // Step 3 elements
        this.selectedTypeSpan = document.getElementById('selected-plugin-type');
        this.configFieldsContainer = document.getElementById('plugin-config-fields');
        this.typeSelect = document.getElementById('plugin-type'); // Hidden select for compatibility

        // Step 4 elements
        this.metadataField = document.getElementById('plugin-metadata');
        this.additionalFieldsField = document.getElementById('plugin-additional-fields');

        // Step 5 elements (Summary)
        this.summaryDisplayName = document.getElementById('summary-display-name');
        this.summaryInternalName = document.getElementById('summary-internal-name');
        this.summaryType = document.getElementById('summary-type');
        this.summaryDescription = document.getElementById('summary-description');
        this.summaryConfiguration = document.getElementById('summary-configuration');
        this.summaryAdvanced = document.getElementById('summary-advanced');
        this.summaryAdvancedCard = document.getElementById('summary-advanced-card');

        // Navigation buttons
        this.nextBtn = document.getElementById('next-step-btn');
        this.prevBtn = document.getElementById('prev-step-btn');
        this.saveBtn = document.getElementById('save-plugin-btn');
        this.skipBtn = document.getElementById('skip-to-end-btn');

        // Step indicators
        this.stepIndicators = document.querySelectorAll('.step-indicator');
    }

    bindEvents() {
        // Navigation buttons
        this.nextBtn.addEventListener('click', () => this.nextStep());
        this.prevBtn.addEventListener('click', () => this.prevStep());
        this.skipBtn.addEventListener('click', () => this.skipToEnd());

        // Search functionality
        this.typeSearch.addEventListener('input', (e) => this.filterPluginTypes(e.target.value));

        // Auto-generate internal name from display name
        this.displayNameField.addEventListener('input', (e) => this.generateInternalName(e.target.value));

        // Form validation on input
        this.displayNameField.addEventListener('input', () => this.validateCurrentStep());
        this.nameField.addEventListener('input', () => this.validateCurrentStep());
    }

    async show(plugin = null) {
        this.editingPlugin = plugin;
        this.reset();
        
        // Update modal title
        this.modalTitle.textContent = plugin ? 'Edit Plugin' : 'Add Plugin';
        
        // Load plugin types for step 1
        await this.loadPluginTypes();
        
        if (plugin) {
            // Pre-populate fields for editing
            await this.populateForEdit(plugin);
        }
        
        // Show the modal
        const modalInstance = new bootstrap.Modal(this.modal);
        modalInstance.show();
        
        return modalInstance;
    }

    reset() {
        this.currentStep = 1;
        this.selectedPluginType = null;
        this.clearError();
        
        // Reset validation state
        this.stepValidationState = {
            1: false, 2: false, 3: false, 4: true, 5: false
        };
        
        // Reset all form fields
        this.displayNameField.value = '';
        this.nameField.value = '';
        this.descriptionField.value = '';
        this.metadataField.value = '{}';
        this.additionalFieldsField.value = '{}';
        
        // Reset UI state
        this.updateStepDisplay();
        this.updateStepIndicators();
        this.updateNavigation();
    }

    async loadPluginTypes() {
        try {
            // Determine endpoint based on current context (admin vs user)
            const endpoint = document.getElementById('plugins-tab') ? 
                '/api/admin/plugins/types' : '/api/user/plugins/types';
            
            const response = await fetch(endpoint);
            if (!response.ok) throw new Error('Failed to load plugin types');
            
            this.pluginTypes = await response.json();
            this.filteredTypes = [...this.pluginTypes];
            
            // Populate hidden select for backward compatibility
            this.populateTypeSelect();
            
            // Render plugin type cards
            this.renderPluginTypeCards();
            
        } catch (error) {
            console.error('Error loading plugin types:', error);
            this.showError('Failed to load plugin types. Please try again.');
        }
    }

    populateTypeSelect() {
        this.typeSelect.innerHTML = '<option value="">Select type...</option>';
        this.pluginTypes.forEach(type => {
            const option = document.createElement('option');
            option.value = type.type;
            option.textContent = type.display || type.type;
            this.typeSelect.appendChild(option);
        });
    }

    filterPluginTypes(searchTerm) {
        const term = searchTerm.toLowerCase();
        this.filteredTypes = this.pluginTypes.filter(type => 
            (type.type || '').toLowerCase().includes(term) ||
            (type.display || '').toLowerCase().includes(term) ||
            (type.description || '').toLowerCase().includes(term)
        );
        
        this.currentPage = 1;
        this.renderPluginTypeCards();
    }

    renderPluginTypeCards() {
        const startIndex = (this.currentPage - 1) * this.itemsPerPage;
        const endIndex = startIndex + this.itemsPerPage;
        const pageTypes = this.filteredTypes.slice(startIndex, endIndex);

        if (pageTypes.length === 0) {
            this.typesContainer.innerHTML = `
                <div class="col-12 text-center text-muted">
                    <i class="bi bi-search fs-1 mb-2"></i>
                    <div>No plugin types found</div>
                </div>
            `;
        } else {
            this.typesContainer.innerHTML = pageTypes.map(type => `
                <div class="col-md-4">
                    <div class="card plugin-type-card ${this.selectedPluginType?.type === type.type ? 'border-primary bg-primary bg-opacity-10' : ''}" 
                         data-type="${type.type}" 
                         style="cursor: pointer; min-height: 120px;">
                        <div class="card-body d-flex flex-column">
                            <h6 class="card-title">${this.escapeHtml(type.display || type.type)}</h6>
                            <p class="card-text flex-grow-1 small text-muted">
                                ${this.escapeHtml(type.description || 'No description available')}
                            </p>
                            ${this.selectedPluginType?.type === type.type ? 
                                '<i class="bi bi-check-circle-fill text-primary position-absolute top-0 end-0 m-2"></i>' : 
                                ''
                            }
                        </div>
                    </div>
                </div>
            `).join('');

            // Add click event listeners to cards
            this.typesContainer.querySelectorAll('.plugin-type-card').forEach(card => {
                card.addEventListener('click', () => this.selectPluginType(card.dataset.type));
            });
        }

        this.renderPagination();
    }

    renderPagination() {
        const totalPages = Math.ceil(this.filteredTypes.length / this.itemsPerPage);
        
        if (totalPages <= 1) {
            this.typesPagination.innerHTML = '';
            return;
        }

        let paginationHtml = '';
        
        // Previous button
        paginationHtml += `
            <li class="page-item ${this.currentPage === 1 ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${this.currentPage - 1}">Previous</a>
            </li>
        `;

        // Page numbers
        for (let i = 1; i <= totalPages; i++) {
            paginationHtml += `
                <li class="page-item ${i === this.currentPage ? 'active' : ''}">
                    <a class="page-link" href="#" data-page="${i}">${i}</a>
                </li>
            `;
        }

        // Next button
        paginationHtml += `
            <li class="page-item ${this.currentPage === totalPages ? 'disabled' : ''}">
                <a class="page-link" href="#" data-page="${this.currentPage + 1}">Next</a>
            </li>
        `;

        this.typesPagination.innerHTML = paginationHtml;

        // Add click event listeners
        this.typesPagination.querySelectorAll('.page-link').forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                const page = parseInt(e.target.dataset.page);
                if (page && page >= 1 && page <= totalPages) {
                    this.currentPage = page;
                    this.renderPluginTypeCards();
                }
            });
        });
    }

    selectPluginType(typeString) {
        this.selectedPluginType = this.pluginTypes.find(t => t.type === typeString);
        this.typeSelect.value = typeString;
        
        this.renderPluginTypeCards(); // Re-render to show selection
        this.validateCurrentStep();
    }

    generateInternalName(displayName) {
        // Generate a clean internal name from display name
        const internalName = displayName
            .toLowerCase()
            .replace(/[^a-z0-9]/g, '_')
            .replace(/_+/g, '_')
            .replace(/^_|_$/g, '');
        
        this.nameField.value = internalName;
    }

    async nextStep() {
        console.log(`🚀 nextStep() called from step ${this.currentStep}`);
        
        if (!this.validateCurrentStep()) {
            console.log('❌ Current step validation failed');
            return;
        }

        // Mark current step as valid when successfully moving to next step
        this.stepValidationState[this.currentStep] = true;
        console.log(`✅ Step ${this.currentStep} marked as valid`);

        if (this.currentStep === 2) {
            // Load configuration fields when moving TO step 3
            console.log('📋 Moving to configuration step, loading configuration fields...');
            await this.loadConfigurationFields();
        }

        if (this.currentStep === 4) {
            // Generate summary before moving to step 5
            console.log('📝 Moving to summary step, generating summary...');
            this.generateSummary();
        }

        this.currentStep++;
        console.log(`➡️ Advanced to step ${this.currentStep}`);
        
        this.updateStepDisplay();
        this.updateStepIndicators();
        this.updateNavigation();
    }

    prevStep() {
        this.currentStep--;
        this.updateStepDisplay();
        this.updateStepIndicators();
        this.updateNavigation();
    }

    skipToEnd() {
        this.generateSummary();
        this.currentStep = this.maxSteps;
        this.updateStepDisplay();
        this.updateStepIndicators();
        this.updateNavigation();
    }

    updateStepDisplay() {
        console.log(`🎭 updateStepDisplay() called for step ${this.currentStep}`);
        
        // Hide all step contents
        Object.entries(this.stepContents).forEach(([stepNum, step]) => {
            if (step) {
                step.classList.add('d-none');
                console.log(`👁️ Hiding step ${stepNum}`);
            }
        });

        // Show current step
        const currentStepContent = this.stepContents[this.currentStep];
        if (currentStepContent) {
            currentStepContent.classList.remove('d-none');
            console.log(`✅ Showing step ${this.currentStep}`);
        } else {
            console.error(`❌ Step ${this.currentStep} content not found!`);
        }
    }

    updateStepIndicators() {
        // Update step progress container class
        if (this.stepProgressContainer) {
            this.stepProgressContainer.className = `step-progress-container step-${this.currentStep}`;
        }

        // Update each step indicator
        this.stepItems.forEach((stepItem, index) => {
            const stepNumber = index + 1;
            stepItem.classList.remove('active', 'completed', 'error', 'pending');

            if (stepNumber < this.currentStep) {
                // Past steps - mark as completed or error based on validation
                if (this.stepValidationState[stepNumber]) {
                    stepItem.classList.add('completed');
                } else {
                    stepItem.classList.add('error');
                }
            } else if (stepNumber === this.currentStep) {
                // Current step
                stepItem.classList.add('active');
            } else {
                // Future steps
                stepItem.classList.add('pending');
            }
        });
    }

    async loadConfigurationFields() {
        console.log('🔧 loadConfigurationFields() called');
        
        if (!this.selectedPluginType) {
            console.error('❌ No selectedPluginType found!');
            return;
        }

        console.log('📋 Selected plugin type:', JSON.stringify(this.selectedPluginType, null, 2));
        this.selectedTypeSpan.textContent = this.selectedPluginType.display || this.selectedPluginType.type;

        const apiUrl = `/api/plugins/${this.selectedPluginType.type}/merge_settings`;
        console.log('🌐 Making API request to:', apiUrl);

        try {
            // Load merged settings to get default configuration
            console.log('📤 Sending POST request to merge_settings endpoint...');
            const response = await fetch(apiUrl, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({})
            });

            console.log('📡 Response status:', response.status, response.statusText);
            
            if (response.ok) {
                const mergedSettings = await response.json();
                console.log('✅ Received merged settings:', JSON.stringify(mergedSettings, null, 2));
                this.renderConfigurationFields(mergedSettings);
            } else {
                console.warn('⚠️ API response not ok, falling back to basic configuration');
                const errorText = await response.text();
                console.error('❌ API error response:', errorText);
                // Fallback to basic configuration fields
                this.renderBasicConfigurationFields();
            }
        } catch (error) {
            console.error('❌ Error loading configuration fields:', error);
            console.error('❌ Error stack:', error.stack);
            this.renderBasicConfigurationFields();
        }
    }

    renderConfigurationFields(mergedSettings) {
        console.log('🎨 renderConfigurationFields() called with:', JSON.stringify(this.maskSensitiveData(mergedSettings), null, 2));
        
        // This will render dynamic configuration fields based on the plugin type and schema
        let fieldsHtml = '';

        // First render the endpoint field (common to most plugins)
        console.log('🌐 Adding endpoint field...');
        fieldsHtml += `
            <div class="mb-3">
                <label for="plugin-endpoint" class="form-label">Endpoint</label>
                <input type="text" class="form-control" id="plugin-endpoint" 
                       placeholder="https://" 
                       value="${mergedSettings.endpoint || ''}" />
                <div class="form-text">The endpoint URL for this plugin.</div>
            </div>
        `;

        // Render additionalFields schema-driven fields
        if (mergedSettings.additionalFields) {
            console.log('🔧 Rendering additionalFields:', JSON.stringify(this.maskSensitiveData(mergedSettings.additionalFields), null, 2));
            fieldsHtml += this.renderSchemaFields(mergedSettings.additionalFields, 'additionalFields');
        } else {
            console.log('⚠️ No additionalFields found in mergedSettings');
        }

        // Always render auth configuration last
        console.log('🔐 Adding auth configuration...');
        fieldsHtml += this.renderAuthConfiguration();

        console.log('📝 Final fields HTML length:', fieldsHtml.length);
        console.log('📝 Final fields HTML preview:', fieldsHtml.substring(0, 200) + '...');
        
        if (!this.configFieldsContainer) {
            console.error('❌ configFieldsContainer not found!');
            return;
        }
        
        this.configFieldsContainer.innerHTML = fieldsHtml;
        console.log('✅ Configuration fields rendered successfully');

        // Add event listeners for auth type changes
        const authTypeSelect = document.getElementById('plugin-auth-type');
        if (authTypeSelect) {
            authTypeSelect.addEventListener('change', () => this.toggleAuthFields());
            this.toggleAuthFields(); // Initial toggle
        }
    }

    renderSchemaFields(fieldData, section) {
        if (!fieldData || typeof fieldData !== 'object') return '';
        
        let fieldsHtml = '';
        
        // Iterate through all properties in the schema-merged data
        Object.entries(fieldData).forEach(([key, value]) => {
            // Skip known fields that are handled elsewhere
            if (key === 'endpoint' || key === 'auth') return;
            
            fieldsHtml += this.renderSchemaField(key, value, section);
        });

        return fieldsHtml;
    }

    renderSchemaField(key, value, section) {
        const fieldId = `plugin-${section}-${key}`;
        const label = this.formatFieldLabel(key);
        
        // Check if this is a security field that should be masked
        const isSecurityField = this.isSecurityField(key);
        
        // Handle different value types based on the merged schema data
        if (typeof value === 'boolean') {
            return `
                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="${fieldId}" 
                               ${value ? 'checked' : ''} />
                        <label class="form-check-label" for="${fieldId}">
                            ${label}
                        </label>
                    </div>
                </div>
            `;
        } else if (typeof value === 'number') {
            return `
                <div class="mb-3">
                    <label for="${fieldId}" class="form-label">${label}</label>
                    <input type="number" class="form-control" id="${fieldId}" value="${value}" />
                </div>
            `;
        } else if (Array.isArray(value)) {
            // Handle arrays as JSON text area
            return `
                <div class="mb-3">
                    <label for="${fieldId}" class="form-label">${label}</label>
                    <textarea class="form-control" id="${fieldId}" rows="3" placeholder="[]">${JSON.stringify(value, null, 2)}</textarea>
                    <div class="form-text">JSON array format</div>
                </div>
            `;
        } else if (typeof value === 'object' && value !== null) {
            // Handle objects as JSON text area
            return `
                <div class="mb-3">
                    <label for="${fieldId}" class="form-label">${label}</label>
                    <textarea class="form-control" id="${fieldId}" rows="4" placeholder="{}">${JSON.stringify(value, null, 2)}</textarea>
                    <div class="form-text">JSON object format</div>
                </div>
            `;
        } else if (typeof value === 'string' && value.includes('|')) {
            // Handle enum values (merged as pipe-separated strings)
            const options = value.split('|');
            let optionsHtml = options.map(option => 
                `<option value="${option.trim()}">${option.trim()}</option>`
            ).join('');
            
            return `
                <div class="mb-3">
                    <label for="${fieldId}" class="form-label">${label}</label>
                    <select class="form-select" id="${fieldId}">
                        <option value="">Select ${label}</option>
                        ${optionsHtml}
                    </select>
                </div>
            `;
        } else if (isSecurityField) {
            // Security field with show/hide toggle
            const placeholder = `Enter ${label.toLowerCase()}`;
            return `
                <div class="mb-3">
                    <label for="${fieldId}" class="form-label">${label}</label>
                    <div class="input-group">
                        <input type="password" class="form-control" id="${fieldId}" 
                               value="${value || ''}" 
                               placeholder="${placeholder}" />
                        <button class="btn btn-outline-secondary" type="button" onclick="togglePasswordField('${fieldId}')">
                            <i class="bi bi-eye" id="${fieldId}-toggle-icon"></i>
                        </button>
                    </div>
                </div>
            `;
        } else {
            // Default to text input
            const placeholder = typeof value === 'string' && value.length > 50 ? 
                value.substring(0, 47) + '...' : 
                (value || `Enter ${label.toLowerCase()}`);
                
            return `
                <div class="mb-3">
                    <label for="${fieldId}" class="form-label">${label}</label>
                    <input type="text" class="form-control" id="${fieldId}" 
                           value="${value || ''}" 
                           placeholder="${placeholder}" />
                </div>
            `;
        }
    }

    isSecurityField(fieldName) {
        // Check if field name indicates it's a security field
        const securityKeywords = [
            'key', 'secret', 'password', 'token', 'credential', 'connectionstring',
            'connection_string', 'api_key', 'apikey', 'auth_key', 'authkey',
            'client_secret', 'clientsecret', 'private_key', 'privatekey'
        ];
        
        const lowerFieldName = fieldName.toLowerCase();
        return securityKeywords.some(keyword => lowerFieldName.includes(keyword));
    }

    maskSensitiveData(obj, maskKeys = true) {
        // Create a deep copy and mask sensitive data for logging
        if (obj === null || obj === undefined) return obj;
        if (typeof obj !== 'object') return obj;
        if (Array.isArray(obj)) return obj.map(item => this.maskSensitiveData(item, maskKeys));
        
        const masked = {};
        for (const [key, value] of Object.entries(obj)) {
            if (maskKeys && this.isSecurityField(key) && typeof value === 'string' && value.length > 0) {
                // Mask sensitive values but keep some info for debugging
                masked[key] = value.length > 4 ? `***${value.slice(-4)}` : '***';
            } else if (typeof value === 'object') {
                masked[key] = this.maskSensitiveData(value, maskKeys);
            } else {
                masked[key] = value;
            }
        }
        return masked;
    }

    renderBasicConfigurationFields() {
        // Fallback basic configuration
        this.configFieldsContainer.innerHTML = `
            <div class="mb-3">
                <label for="plugin-endpoint" class="form-label">Endpoint</label>
                <input type="text" class="form-control" id="plugin-endpoint" placeholder="https://" />
                <div class="form-text">The endpoint URL for this plugin.</div>
            </div>
            ${this.renderAuthConfiguration()}
        `;

        const authTypeSelect = document.getElementById('plugin-auth-type');
        if (authTypeSelect) {
            authTypeSelect.addEventListener('change', () => this.toggleAuthFields());
            this.toggleAuthFields();
        }
    }

    renderAuthConfiguration() {
        return `
            <div class="mb-3">
                <label class="form-label">Authentication</label>
                <div class="input-group mb-3">
                    <span class="input-group-text">Type</span>
                    <select class="form-select" id="plugin-auth-type">
                        <option value="key">Key</option>
                        <option value="identity">Managed Identity</option>
                        <option value="user">User</option>
                        <option value="servicePrincipal">Service Principal</option>
                    </select>
                </div>
                <div class="input-group mb-3" id="auth-identity-group" style="display:none;">
                    <span class="input-group-text" id="auth-identity-label">Identity</span>
                    <input type="text" class="form-control" id="plugin-auth-identity" />
                </div>
                <div id="auth-key-group" class="mb-3" style="display:none;">
                    <label class="form-label mb-2" id="auth-key-label">Key</label>
                    <div class="input-group">
                        <input type="password" class="form-control" id="plugin-auth-key" placeholder="Enter authentication key" />
                        <button class="btn btn-outline-secondary" type="button" onclick="togglePasswordField('plugin-auth-key')">
                            <i class="bi bi-eye" id="plugin-auth-key-toggle-icon"></i>
                        </button>
                    </div>
                </div>
                <div class="input-group mb-3" id="auth-tenantid-group" style="display:none;">
                    <span class="input-group-text" id="auth-tenantid-label">Tenant Id</span>
                    <input type="text" class="form-control" id="plugin-auth-tenant-id" />
                </div>
            </div>
        `;
    }

    renderDynamicField(key, value) {
        // Render dynamic fields based on type
        if (typeof value === 'boolean') {
            return `
                <div class="mb-3">
                    <div class="form-check">
                        <input class="form-check-input" type="checkbox" id="plugin-${key}" 
                               ${value ? 'checked' : ''} />
                        <label class="form-check-label" for="plugin-${key}">
                            ${this.formatFieldLabel(key)}
                        </label>
                    </div>
                </div>
            `;
        } else if (typeof value === 'number') {
            return `
                <div class="mb-3">
                    <label for="plugin-${key}" class="form-label">${this.formatFieldLabel(key)}</label>
                    <input type="number" class="form-control" id="plugin-${key}" value="${value}" />
                </div>
            `;
        } else {
            return `
                <div class="mb-3">
                    <label for="plugin-${key}" class="form-label">${this.formatFieldLabel(key)}</label>
                    <input type="text" class="form-control" id="plugin-${key}" value="${value || ''}" />
                </div>
            `;
        }
    }

    formatFieldLabel(key) {
        return key.replace(/([A-Z])/g, ' $1')
                 .replace(/^./, str => str.toUpperCase())
                 .replace(/_/g, ' ');
    }

    toggleAuthFields() {
        const authType = document.getElementById('plugin-auth-type')?.value;
        const keyGroup = document.getElementById('auth-key-group');
        const identityGroup = document.getElementById('auth-identity-group');
        const tenantIdGroup = document.getElementById('auth-tenantid-group');

        // Hide all groups first
        [keyGroup, identityGroup, tenantIdGroup].forEach(group => {
            if (group) group.style.display = 'none';
        });

        // Show relevant groups based on auth type
        if (authType === 'key' && keyGroup) {
            keyGroup.style.display = 'flex';
        } else if (authType === 'identity' && identityGroup) {
            identityGroup.style.display = 'flex';
        } else if (authType === 'servicePrincipal') {
            if (identityGroup) identityGroup.style.display = 'flex';
            if (keyGroup) keyGroup.style.display = 'flex';
            if (tenantIdGroup) tenantIdGroup.style.display = 'flex';
        }
    }

    validateCurrentStep() {
        this.clearError();
        
        switch (this.currentStep) {
            case 1:
                return this.validateStep1();
            case 2:
                return this.validateStep2();
            case 3:
                return this.validateStep3();
            case 4:
                return this.validateStep4();
            case 5:
                return this.validateStep5();
            default:
                return true;
        }
    }

    validateStep1() {
        const isValid = this.selectedPluginType !== null;
        this.nextBtn.disabled = !isValid;
        return isValid;
    }

    validateStep2() {
        const displayName = this.displayNameField.value.trim();
        const internalName = this.nameField.value.trim();
        
        const isValid = displayName.length > 0 && internalName.length > 0;
        this.nextBtn.disabled = !isValid;
        
        if (!isValid && displayName.length === 0) {
            this.showError('Display name is required.');
        }
        
        return isValid;
    }

    validateStep3() {
        // Basic validation for required configuration fields
        const endpoint = document.getElementById('plugin-endpoint');
        
        if (endpoint && endpoint.value.trim() && !endpoint.value.startsWith('https://')) {
            this.showError('Endpoint must start with https://');
            this.nextBtn.disabled = true;
            return false;
        }
        
        this.nextBtn.disabled = false;
        return true;
    }

    validateStep4() {
        // Validate JSON fields
        try {
            if (this.metadataField.value.trim()) {
                JSON.parse(this.metadataField.value);
            }
            if (this.additionalFieldsField.value.trim()) {
                JSON.parse(this.additionalFieldsField.value);
            }
        } catch (e) {
            this.showError('Invalid JSON in metadata or additional fields.');
            return false;
        }
        
        return true;
    }

    validateStep5() {
        console.log('✅ validateStep5() called - summary step is always valid');
        // Step 5 is always valid - it's just a summary
        // Clear any validation errors that might be lingering
        this.clearError();
        this.nextBtn.disabled = false;
        return true;
    }

    generateSummary() {
        console.log('📊 generateSummary() called');
        
        // Clear any existing validation errors when generating summary
        this.clearError();
        
        // Populate summary fields
        this.summaryDisplayName.textContent = this.displayNameField.value.trim() || '-';
        this.summaryInternalName.textContent = this.nameField.value.trim() || '-';
        this.summaryType.textContent = this.selectedPluginType?.display || this.selectedPluginType?.type || '-';
        this.summaryDescription.textContent = this.descriptionField.value.trim() || '-';

        // Generate configuration summary
        this.generateConfigurationSummary();
        
        // Generate advanced settings summary
        this.generateAdvancedSummary();
        
        console.log('✅ Summary generation completed');
    }

    generateConfigurationSummary() {
        let configHtml = '';
        
        // Endpoint
        const endpoint = document.getElementById('plugin-endpoint');
        if (endpoint && endpoint.value.trim()) {
            configHtml += `<div class="row mb-2">
                <div class="col-sm-4"><strong>Endpoint:</strong></div>
                <div class="col-sm-8"><code>${this.escapeHtml(endpoint.value)}</code></div>
            </div>`;
        }

        // Authentication
        const authType = document.getElementById('plugin-auth-type')?.value;
        if (authType) {
            configHtml += `<div class="row mb-2">
                <div class="col-sm-4"><strong>Auth Type:</strong></div>
                <div class="col-sm-8"><span class="badge bg-primary">${authType}</span></div>
            </div>`;

            if (authType === 'key') {
                const authKey = document.getElementById('plugin-auth-key')?.value;
                if (authKey) {
                    configHtml += `<div class="row mb-2">
                        <div class="col-sm-4"><strong>API Key:</strong></div>
                        <div class="col-sm-8"><code>***${authKey.slice(-4)}</code></div>
                    </div>`;
                }
            } else if (authType === 'identity') {
                const identity = document.getElementById('plugin-auth-identity')?.value;
                if (identity) {
                    configHtml += `<div class="row mb-2">
                        <div class="col-sm-4"><strong>Identity:</strong></div>
                        <div class="col-sm-8"><code>${this.escapeHtml(identity)}</code></div>
                    </div>`;
                }
            } else if (authType === 'servicePrincipal') {
                const identity = document.getElementById('plugin-auth-identity')?.value;
                const tenantId = document.getElementById('plugin-auth-tenant-id')?.value;
                if (identity) {
                    configHtml += `<div class="row mb-2">
                        <div class="col-sm-4"><strong>Client ID:</strong></div>
                        <div class="col-sm-8"><code>${this.escapeHtml(identity)}</code></div>
                    </div>`;
                }
                if (tenantId) {
                    configHtml += `<div class="row mb-2">
                        <div class="col-sm-4"><strong>Tenant ID:</strong></div>
                        <div class="col-sm-8"><code>${this.escapeHtml(tenantId)}</code></div>
                    </div>`;
                }
            }
        }

        // Other configuration fields from schema
        const configData = this.collectConfigurationData();
        console.log('📊 Config data for summary:', JSON.stringify(this.maskSensitiveData(configData), null, 2));
        
        Object.entries(configData).forEach(([key, value]) => {
            if (key !== 'endpoint' && value !== '' && value !== null && value !== undefined) {
                // Check if this is a security field
                const isSecurityField = this.isSecurityField(key);
                
                let displayValue;
                if (isSecurityField && typeof value === 'string' && value.length > 0) {
                    // Mask security values
                    displayValue = value.length > 4 ? `***${value.slice(-4)}` : '***';
                } else if (typeof value === 'object') {
                    displayValue = JSON.stringify(value, null, 2);
                } else {
                    displayValue = String(value);
                }
                    
                configHtml += `<div class="row mb-2">
                    <div class="col-sm-4"><strong>${this.formatFieldLabel(key)}:</strong></div>
                    <div class="col-sm-8"><code>${this.escapeHtml(displayValue)}</code></div>
                </div>`;
            }
        });

        if (!configHtml) {
            configHtml = '<em class="text-muted">No configuration set</em>';
        }

        this.summaryConfiguration.innerHTML = configHtml;
    }

    generateAdvancedSummary() {
        let advancedHtml = '';
        
        // Metadata
        const metadata = this.metadataField.value.trim();
        if (metadata) {
            try {
                const parsed = JSON.parse(metadata);
                const keys = Object.keys(parsed);
                advancedHtml += `<div class="row mb-2">
                    <div class="col-sm-4"><strong>Metadata:</strong></div>
                    <div class="col-sm-8">${keys.length} field(s) configured</div>
                </div>`;
            } catch (e) {
                advancedHtml += `<div class="row mb-2">
                    <div class="col-sm-4"><strong>Metadata:</strong></div>
                    <div class="col-sm-8"><span class="text-warning">Invalid JSON</span></div>
                </div>`;
            }
        }

        // Additional Fields
        const additionalFields = this.additionalFieldsField.value.trim();
        if (additionalFields) {
            try {
                const parsed = JSON.parse(additionalFields);
                const keys = Object.keys(parsed);
                advancedHtml += `<div class="row mb-2">
                    <div class="col-sm-4"><strong>Additional Fields:</strong></div>
                    <div class="col-sm-8">${keys.length} field(s) configured</div>
                </div>`;
            } catch (e) {
                advancedHtml += `<div class="row mb-2">
                    <div class="col-sm-4"><strong>Additional Fields:</strong></div>
                    <div class="col-sm-8"><span class="text-warning">Invalid JSON</span></div>
                </div>`;
            }
        }

        if (advancedHtml) {
            this.summaryAdvanced.innerHTML = advancedHtml;
            this.summaryAdvancedCard.style.display = 'block';
        } else {
            this.summaryAdvancedCard.style.display = 'none';
        }
    }

    updateNavigation() {
        // Show/hide navigation buttons based on current step
        this.prevBtn.style.display = this.currentStep > 1 ? 'inline-block' : 'none';
        this.nextBtn.style.display = this.currentStep < this.maxSteps ? 'inline-block' : 'none';
        this.saveBtn.style.display = this.currentStep === this.maxSteps ? 'inline-block' : 'none';
        this.skipBtn.style.display = this.currentStep < this.maxSteps - 1 ? 'inline-block' : 'none';
        
        // Validate current step
        this.validateCurrentStep();
    }

    async populateForEdit(plugin) {
        // Pre-populate fields when editing
        this.displayNameField.value = plugin.displayName || plugin.name || '';
        this.nameField.value = plugin.name || '';
        this.descriptionField.value = plugin.description || '';
        
        if (plugin.metadata) {
            this.metadataField.value = JSON.stringify(plugin.metadata, null, 2);
        }
        
        if (plugin.additionalFields) {
            this.additionalFieldsField.value = JSON.stringify(plugin.additionalFields, null, 2);
        }
        
        // Select the plugin type
        if (plugin.type) {
            this.selectPluginType(plugin.type);
        }
    }

    collectFormData() {
        // Collect all form data for saving
        console.log('🔍 Starting form data collection...');
        
        const auth = this.collectAuthData();
        console.log('🔐 Auth data collected:', JSON.stringify(this.maskSensitiveData(auth), null, 2));
        
        const configData = this.collectConfigurationData();
        console.log('⚙️ Configuration data collected:', JSON.stringify(this.maskSensitiveData(configData), null, 2));
        
        let metadata = {};
        let additionalFields = {};
        
        try {
            metadata = this.metadataField.value.trim() ? 
                JSON.parse(this.metadataField.value) : {};
            console.log('📊 Metadata parsed:', JSON.stringify(this.maskSensitiveData(metadata), null, 2));
        } catch (e) {
            console.error('❌ Invalid metadata JSON:', e);
        }
        
        try {
            additionalFields = this.additionalFieldsField.value.trim() ? 
                JSON.parse(this.additionalFieldsField.value) : {};
            console.log('🔧 Additional fields parsed:', JSON.stringify(this.maskSensitiveData(additionalFields), null, 2));
        } catch (e) {
            console.error('❌ Invalid additional fields JSON:', e);
        }

        // Merge configuration data into additionalFields, but extract endpoint to root level
        console.log('🔄 Processing configuration data...');
        
        // Extract endpoint from configData for root level
        const endpoint = configData.endpoint;
        delete configData.endpoint; // Remove from configData so it doesn't go into additionalFields
        
        // Merge remaining configuration data into additionalFields
        Object.assign(additionalFields, configData);
        console.log('🔧 Final additional fields:', JSON.stringify(this.maskSensitiveData(additionalFields), null, 2));

        const formData = {
            name: this.nameField.value.trim(),
            displayName: this.displayNameField.value.trim(), // ✅ Include displayName as schema now supports it
            type: this.selectedPluginType?.type,
            description: this.descriptionField.value.trim(),
            endpoint: endpoint || '', // ✅ Endpoint at root level as required by schema
            auth,
            metadata,
            additionalFields
        };
        
        console.log('📋 Final form data collected:', JSON.stringify(this.maskSensitiveData(formData), null, 2));
        return formData;
    }

    collectAuthData() {
        const authType = document.getElementById('plugin-auth-type')?.value;
        const auth = { type: authType };
        
        if (authType === 'key') {
            auth.key = document.getElementById('plugin-auth-key')?.value.trim() || '';
        } else if (authType === 'identity') {
            auth.identity = document.getElementById('plugin-auth-identity')?.value.trim() || '';
        } else if (authType === 'servicePrincipal') {
            auth.identity = document.getElementById('plugin-auth-identity')?.value.trim() || '';
            auth.key = document.getElementById('plugin-auth-key')?.value.trim() || '';
            auth.tenantId = document.getElementById('plugin-auth-tenant-id')?.value.trim() || '';
        }
        
        return auth;
    }

    collectConfigurationData() {
        const configData = {};
        console.log('⚙️ Starting configuration data collection...');
        
        // Collect endpoint
        const endpoint = document.getElementById('plugin-endpoint');
        if (endpoint && endpoint.value.trim()) {
            configData.endpoint = endpoint.value.trim();
            console.log('🌐 Endpoint found:', configData.endpoint);
        } else {
            console.log('🌐 No endpoint found or endpoint is empty');
        }
        
        // Collect schema-driven fields
        console.log('🔍 Looking for schema-driven fields in container...');
        this.configFieldsContainer.querySelectorAll('input, select, textarea').forEach(field => {
            if (field.id && field.id.startsWith('plugin-') && 
                !field.id.includes('auth') && field.id !== 'plugin-endpoint') {
                
                console.log(`🔧 Processing field: ${field.id}, type: ${field.type}, value: ${field.value}`);
                
                // Parse field ID: plugin-additionalFields-fieldName or plugin-fieldName
                let key = field.id.replace('plugin-', '');
                if (key.startsWith('additionalFields-')) {
                    key = key.replace('additionalFields-', '');
                }
                
                if (field.type === 'checkbox') {
                    configData[key] = field.checked;
                } else if (field.type === 'number') {
                    configData[key] = field.value ? parseFloat(field.value) : 0;
                } else if (field.tagName.toLowerCase() === 'textarea') {
                    // Try to parse JSON for textarea fields, fallback to string
                    try {
                        const trimmedValue = field.value.trim();
                        if (trimmedValue && (trimmedValue.startsWith('{') || trimmedValue.startsWith('['))) {
                            configData[key] = JSON.parse(trimmedValue);
                        } else {
                            configData[key] = trimmedValue;
                        }
                    } catch (e) {
                        configData[key] = field.value;
                    }
                } else {
                    configData[key] = field.value;
                }
                
                // Log field value (masked if sensitive)
                const isSecurityField = this.isSecurityField(key);
                const logValue = isSecurityField && typeof configData[key] === 'string' && configData[key].length > 0 ?
                    (configData[key].length > 4 ? `***${configData[key].slice(-4)}` : '***') :
                    configData[key];
                console.log(`✅ Field ${key} set to:`, logValue);
            }
        });
        
        console.log('⚙️ Final configuration data:', JSON.stringify(this.maskSensitiveData(configData), null, 2));
        return configData;
    }

    showError(message) {
        this.errorDiv.textContent = message;
        this.errorDiv.classList.remove('d-none');
    }

    clearError() {
        this.errorDiv.classList.add('d-none');
        this.errorDiv.textContent = '';
    }

    escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
}

// Global function for password field toggle (called from HTML)
window.togglePasswordField = function(fieldId) {
    const field = document.getElementById(fieldId);
    const icon = document.getElementById(fieldId + '-toggle-icon');
    
    if (!field || !icon) return;
    
    if (field.type === 'password') {
        field.type = 'text';
        icon.className = 'bi bi-eye-slash';
    } else {
        field.type = 'password';
        icon.className = 'bi bi-eye';
    }
};

// Export for use in other modules
export default PluginWizard;
