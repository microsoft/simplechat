// content-screening-policy.js
(function () {
    "use strict";

    const screening = window.ContentScreening;
    const { element, button, hasAction, showMessage, clearMessage, errorMessage } = screening;
    const editors = new WeakMap();
    let fieldSequence = 0;

    function field(container, labelText, type = "text", value = "", options = []) {
        const wrapper = element("div", "mb-3");
        const id = `screening-policy-field-${++fieldSequence}`;
        const label = element("label", "form-label", labelText);
        label.htmlFor = id;
        let input;
        if (type === "select") {
            input = element("select", "form-select");
            options.forEach(option => {
                const node = element("option", "", option.label);
                node.value = option.value;
                input.appendChild(node);
            });
        } else if (type === "textarea") {
            input = element("textarea", "form-control");
            input.rows = 3;
        } else {
            input = element("input", type === "checkbox" ? "form-check-input me-2" : "form-control");
            input.type = type;
        }
        input.id = id;
        input.autocomplete = "off";
        if (type === "checkbox") {
            input.checked = value === true;
            wrapper.className = "form-check mb-3";
            label.className = "form-check-label";
            wrapper.append(input, label);
        } else {
            input.value = value ?? "";
            wrapper.append(label, input);
        }
        container.appendChild(wrapper);
        return input;
    }

    function enumOptions(values) {
        return values.map(value => ({ value, label: value.replace(/_/g, " ") }));
    }

    function modelReference(model) {
        return { endpoint_id: model.endpoint_id, model_id: model.model_id };
    }

    function sameModel(left, right) {
        return left?.endpoint_id === right?.endpoint_id && left?.model_id === right?.model_id;
    }

    class PolicyEditor {
        constructor(root, scope) {
            this.root = root;
            this.scope = scope;
            this.sequence = 0;
            this.stale = false;
            this.dirty = false;
            this.message = element("div", "alert d-none");
            this.message.setAttribute("role", "alert");
            this.panel = element("div");
            this.root.replaceChildren(this.message, this.panel);
        }

        async load(scope = this.scope) {
            const sequence = ++this.sequence;
            this.scope = scope;
            this.panel.replaceChildren(element("p", "text-body-secondary", "Loading policy and prerequisites…"));
            clearMessage(this.message);
            try {
                const [data, templates, models] = await Promise.all([
                    screening.api.getPolicy(scope),
                    screening.api.getTemplates(scope),
                    screening.api.getModels(scope)
                ]);
                if (sequence !== this.sequence) return;
                this.data = data;
                this.templates = templates;
                this.models = models;
                this.stale = false;
                this.dirty = false;
                this.render();
                this.root.dispatchEvent(new CustomEvent("screening:policy-loaded", { bubbles: true, detail: { scope, data } }));
            } catch (error) {
                if (sequence !== this.sequence) return;
                this.panel.replaceChildren(button("Retry loading policy", "btn btn-outline-secondary", () => this.load()));
                showMessage(this.message, errorMessage(error));
            }
        }

        renderBaseline(baseline) {
            const region = element("section", "screening-policy-baseline");
            region.append(
                element("h3", "h6", "Required administrator baseline"),
                element("p", "small", "Workspace additions cannot remove, disable, or weaken required administrator checks. When the administrator baseline is disabled, additions are inactive.")
            );
            const rules = element("ul", "mb-2");
            (baseline?.rules || []).filter(rule => rule.enabled).forEach(rule => {
                rules.appendChild(element("li", "", `${rule.name} · ${rule.severity} · ${rule.category}`));
            });
            if (!rules.childElementCount) rules.appendChild(element("li", "", "Administrator-required checks are retained by the server. Their private rule values are not exposed here."));
            region.appendChild(rules);
            if (Number.isInteger(baseline?.rule_count)) {
                region.appendChild(element("p", "small mb-2", `${baseline.rule_count} mandatory deterministic rule${baseline.rule_count === 1 ? "" : "s"}.`));
            }
            if (baseline?.ai_check_count > 0) {
                region.appendChild(element("p", "small mb-0", "Required model criteria are included in every effective scan."));
            }
            this.panel.appendChild(region);
        }

        render() {
            this.panel.replaceChildren();
            this.ruleEditors = [];
            this.allowedModelInputs = [];
            this.limitInputs = new Map();
            const global = this.scope.scopeType === "global";
            const policy = this.data.policy;
            const canEdit = hasAction(this.data.allowed_actions, "edit_policy");
            const prerequisitesReady = this.data.prerequisites?.ready === true;
            const storageValidated = this.data.prerequisites?.storage_validated === true;
            const dependency = element("div", `alert ${prerequisitesReady && storageValidated ? "alert-success" : "alert-warning"}`);
            dependency.setAttribute("role", "status");
            dependency.textContent = prerequisitesReady
                ? (storageValidated ? "Enhanced Citations and screening storage prerequisites are ready."
                    : "Enhanced Citations is enabled. The server validates its private storage when Content Screening is enabled.")
                : "New scanning cannot be enabled until Enhanced Citations and its private storage are configured and validated.";
            this.panel.appendChild(dependency);
            const capability = document.getElementById("enable_content_screening");
            if (global && capability) {
                capability.checked = this.data.configuration.enabled === true;
                capability.disabled = !canEdit || (!prerequisitesReady && !capability.checked);
                if (!capability.dataset.screeningBound) {
                    capability.dataset.screeningBound = "true";
                    capability.addEventListener("change", () => this.configure(capability));
                    const citations = document.getElementById("enable_enhanced_citations");
                    citations?.addEventListener("change", () => {
                        if (capability.checked && !citations.checked) {
                            citations.checked = true;
                            showMessage(this.message, "Enhanced Citations is required while new Content Screening is enabled. Existing reviews also depend on its retained storage.", "warning");
                        }
                    });
                }
            }
            if (!global) this.renderBaseline(this.data.baseline);
            this.panel.append(
                element("h3", "h5", global ? "Mandatory screening policy" : "Workspace additions"),
                element("p", "small text-body-secondary", "Policies are saved separately from application settings. Pattern checks are indicators, not a guarantee that all PII or instruction manipulation will be detected.")
            );
            const summary = element("div", "alert alert-secondary");
            summary.setAttribute("role", "status");
            summary.setAttribute("aria-label", "Configured screening checks");
            this.summaryLabel = element("p", "fw-semibold mb-1");
            this.summaryDetail = element("p", "small mb-1");
            summary.append(
                this.summaryLabel, this.summaryDetail,
                element("p", "small mb-0", "This summarizes the current draft. Save the policy to apply it; new scans must also be enabled separately.")
            );
            this.panel.appendChild(summary);
            const controls = element("fieldset");
            controls.disabled = !canEdit;
            this.controls = controls;
            this.panel.appendChild(controls);
            this.enabledInput = field(controls, global ? "Baseline policy enabled" : "Workspace additions enabled", "checkbox", policy.enabled);
            controls.append(
                element("h4", "h6", "Deterministic checks"),
                element("p", "small text-body-secondary", "PII patterns, regular expressions, and literal values are checked in code. They do not call an AI model.")
            );
            const starterBar = element("div", "row g-3 align-items-end");
            const starterColumn = element("div", "col-md-8");
            this.packInput = field(starterColumn, "Starter rule pack", "select", "", [
                { value: "", label: "Choose a starter pack" },
                ...this.templates.starter_packs.map(pack => ({ value: pack.id, label: pack.name || pack.id.replace(/_/g, " ") }))
            ]);
            const starterAction = element("div", "col-md-4 mb-3");
            starterAction.appendChild(button("Add starter pack", "btn btn-outline-secondary", () => this.addStarterPack()));
            starterBar.append(starterColumn, starterAction);
            controls.appendChild(starterBar);
            this.rulesContainer = element("div");
            controls.appendChild(this.rulesContainer);
            (policy.rules || []).forEach(rule => this.addRule(rule));
            const addButtons = element("div", "d-flex flex-wrap gap-2 mb-3");
            addButtons.append(
                button("Add literal rule", "btn btn-outline-secondary", () => this.addRule({ type: "literal" })),
                button("Add regex rule", "btn btn-outline-secondary", () => this.addRule({ type: "regex" })),
                button("Add PII rule", "btn btn-outline-secondary", () => this.addRule({ type: "pii" }))
            );
            controls.appendChild(addButtons);
            this.renderModels(controls, policy, global);
            const limits = element("details", "mb-3");
            limits.appendChild(element("summary", "", "Execution limits"));
            limits.appendChild(element("p", "small text-body-secondary mt-2", global
                ? "A limit being reached means incomplete coverage, not a clean scan."
                : "Workspace limits can only tighten administrator limits. Reaching a limit keeps coverage incomplete."));
            Object.entries(policy.limits || {}).forEach(([key, value]) => {
                const input = field(limits, key.replace(/_/g, " "), "number", value);
                input.step = key.endsWith("_seconds") ? "any" : "1";
                this.limitInputs.set(key, input);
            });
            controls.appendChild(limits);
            const actions = element("div", "d-flex flex-wrap gap-2 mb-3");
            this.saveButton = button("Save screening policy", "btn btn-primary", () => this.save());
            this.reloadButton = button("Reload saved policy", "btn btn-outline-secondary", async () => {
                if (this.dirty && !await screening.confirmAction("Discard policy edits?", "Reloading replaces your unsaved policy edits with the saved version.", "Reload policy")) return;
                this.load();
            });
            actions.append(this.saveButton, this.reloadButton);
            this.panel.appendChild(actions);
            this.saveButton.disabled = !canEdit;
            controls.addEventListener("input", () => { this.dirty = true; this.updateSummary(); });
            controls.addEventListener("change", () => { this.dirty = true; this.updateSummary(); });
            this.renderSample(controls);
            this.updateSummary();
            if (!canEdit) showMessage(this.message, "This policy is read-only. The server has not granted policy editing for this workspace.", "info");
        }

        addStarterPack() {
            const pack = this.templates.starter_packs.find(item => item.id === this.packInput.value);
            if (!pack) return;
            pack.rules.forEach(rule => {
                if (!this.ruleEditors.some(editor => editor.id === rule.id)) this.addRule(rule);
            });
            this.packInput.value = "";
            this.dirty = true;
            this.updateSummary();
        }

        updateSummary() {
            if (!this.summaryLabel || !this.enabledInput) return;
            const global = this.scope.scopeType === "global";
            const inherited = this.data.baseline;
            if (!global && !inherited) {
                this.summaryLabel.textContent = "Required baseline unavailable";
                this.summaryDetail.textContent = "Reload the policy before interpreting its effective checks.";
                return;
            }
            if (!(global ? this.enabledInput.checked : inherited.enabled)) {
                this.summaryLabel.textContent = global ? "Policy disabled" : "Administrator baseline disabled";
                this.summaryDetail.textContent = "Saved rules and model selections are inactive until the required baseline is enabled.";
                return;
            }
            const requiredRules = global ? 0 : inherited.rule_count;
            const requiredAi = global ? 0 : inherited.ai_check_count;
            const rules = requiredRules + (this.enabledInput.checked ? this.ruleEditors.filter(rule => rule.enabled.checked).length : 0);
            const ai = requiredAi + (this.enabledInput.checked && this.aiEnabled?.checked ? 1 : 0);
            this.summaryLabel.textContent = `${rules} deterministic check${rules === 1 ? "" : "s"} | ${ai ? `${ai} AI check${ai === 1 ? "" : "s"}` : "AI screening off"}`;
            this.summaryDetail.textContent = requiredAi
                ? `Includes ${requiredAi} required administrator AI check${requiredAi === 1 ? "" : "s"}. Disabling workspace AI additions does not disable required checks.`
                : "Deterministic checks do not call a model. Model permission selections do not run checks.";
        }

        addRule(rule) {
            const defaults = this.templates.rule_defaults?.[rule.type] || {};
            const value = { ...defaults, ...rule };
            const container = element("section", "screening-rule");
            const heading = element("div", "d-flex flex-wrap justify-content-between gap-2");
            heading.appendChild(element("h4", "h6", `${value.type.toUpperCase()} rule`));
            const editor = { id: value.id || `rule-${screening.newRequestId()}`, type: value.type, container };
            heading.appendChild(button("Remove rule", "btn btn-sm btn-outline-danger", () => {
                this.ruleEditors = this.ruleEditors.filter(item => item !== editor);
                container.remove();
                this.dirty = true;
                this.updateSummary();
            }));
            container.appendChild(heading);
            editor.name = field(container, "Rule name", "text", value.name || "");
            editor.enabled = field(container, "Rule enabled", "checkbox", value.enabled !== false);
            const row = element("div", "row");
            const severityColumn = element("div", "col-md-6");
            const categoryColumn = element("div", "col-md-6");
            editor.severity = field(severityColumn, "Severity", "select", value.severity || "", enumOptions(this.templates.severities));
            editor.category = field(categoryColumn, "Category", "text", value.category || "");
            row.append(severityColumn, categoryColumn);
            container.appendChild(row);
            if (value.type === "pii") {
                editor.piiType = field(container, "Built-in PII detector", "select", value.pii_type || "", [
                    { value: "", label: "Choose a detector" }, ...this.templates.pii_choices
                ]);
            } else if (value.type === "regex") {
                editor.pattern = field(container, "Regular expression", "textarea", value.pattern || "");
            } else {
                editor.values = field(container, "Literal values or phrases", "textarea", (value.values || []).join("\n"));
            }
            if (value.type !== "pii") {
                editor.caseSensitive = field(container, "Case sensitive", "checkbox", value.case_sensitive);
                editor.wholeWord = field(container, "Whole words only", "checkbox", value.whole_word);
            }
            this.rulesContainer.appendChild(container);
            this.ruleEditors.push(editor);
            this.updateSummary();
        }

        renderModels(container, policy, global) {
            const section = element("section", "border-top pt-3 mt-3");
            section.append(
                element("h4", "h6", "AI checks (optional)"),
                element("p", "small text-body-secondary", "Send content to one selected model for this policy's additional criteria. AI findings cannot override deterministic findings.")
            );
            this.aiEnabled = field(section, "Enable AI checks", "checkbox", policy.ai.enabled);
            this.aiDisabledNotice = element("p", "small text-body-secondary", "AI checks for this policy are off. Saved model settings are retained but are not used. Required administrator AI checks still apply to workspace additions.");
            section.appendChild(this.aiDisabledNotice);
            const configuration = element("fieldset");
            configuration.appendChild(element("legend", "visually-hidden", "AI check configuration"));
            this.aiConfiguration = configuration;
            const modelOptions = [{ value: "", label: "Choose an approved configured model" }];
            this.models.choices.forEach((model, index) => modelOptions.push({
                value: String(index), label: [model.connection_name, model.label || model.model_id].filter(Boolean).join(" / ")
            }));
            const selectedIndex = this.models.choices.findIndex(model => sameModel(model, policy.ai.model_selection));
            const unavailable = selectedIndex < 0 && Boolean(policy.ai.model_selection?.model_id);
            if (unavailable) modelOptions.push({ value: "unavailable", label: "Saved model unavailable" });
            this.aiModel = field(configuration, "Scanner model", "select",
                unavailable ? "unavailable" : selectedIndex < 0 ? "" : String(selectedIndex), modelOptions);
            if (unavailable) {
                section.appendChild(element("p", "text-danger small", "The saved scanner model is unavailable. Choose an approved replacement; no fallback model is selected."));
            }
            const aiStarter = field(configuration, "AI starter criteria", "select", "", [
                { value: "", label: "Keep current criteria" },
                ...this.templates.ai_starters.map(starter => ({ value: starter.id, label: starter.name || starter.id.replace(/_/g, " ") }))
            ]);
            configuration.appendChild(button("Use criteria", "btn btn-sm btn-outline-secondary mb-3", async () => {
                const starter = this.templates.ai_starters.find(item => item.id === aiStarter.value);
                if (!starter) return;
                if (this.aiInstructions.value && !await screening.confirmAction("Replace model criteria?", "The selected starter will replace the current model criteria in this draft.", "Use criteria")) return;
                this.aiInstructions.value = starter.instructions;
                this.dirty = true;
            }));
            this.aiInstructions = field(configuration, "Model instructions", "textarea", policy.ai.instructions);
            this.aiSeverity = field(configuration, "Model finding severity", "select", policy.ai.severity, enumOptions(this.templates.severities));
            this.aiCategory = field(configuration, "Model finding category", "text", policy.ai.category);
            this.aiWindow = field(configuration, "Scan window unit", "select", policy.ai.window_unit, enumOptions(["pages", "chunks"]));
            this.aiSize = field(configuration, "Pages or chunks per window", "number", policy.ai.window_size);
            this.aiCharacters = field(configuration, "Maximum characters per window", "number", policy.ai.max_characters);
            this.aiOverlap = field(configuration, "Boundary overlap characters", "number", policy.ai.overlap_characters);
            [this.aiSize, this.aiCharacters, this.aiOverlap].forEach(input => { input.step = "1"; });
            section.appendChild(configuration);
            container.appendChild(section);
            if (global) {
                const permissions = element("details", "border rounded p-3 my-3");
                permissions.append(
                    element("summary", "fw-semibold", "Models workspaces may use"),
                    element("p", "small text-body-secondary mt-2", "This is a permission list, not a list of models to run. It can be configured while this policy's AI checks are off. A workspace must enable its own AI check to use one of these models. The saved baseline scanner is also permitted automatically.")
                );
                const allowed = element("fieldset", "screening-model-list");
                allowed.appendChild(element("legend", "visually-hidden", "Workspace model permissions"));
                this.models.choices.forEach(model => {
                    const explicit = (policy.allowed_models || []).some(item => sameModel(item, model));
                    const input = field(allowed, [model.connection_name, model.label || model.model_id].filter(Boolean).join(" / "), "checkbox", explicit);
                    const note = element("span", "small ms-1 d-none", "(included by baseline scanner selection)");
                    input.parentElement.querySelector("label").appendChild(note);
                    const permission = { input, model, explicit, note };
                    input.addEventListener("change", () => { permission.explicit = input.checked; });
                    this.allowedModelInputs.push(permission);
                });
                permissions.appendChild(allowed);
                container.appendChild(permissions);
            }
            this.aiEnabled.addEventListener("change", () => this.updateModelControls());
            this.aiModel.addEventListener("change", () => this.updateModelControls());
            this.updateModelControls();
        }

        updateModelControls() {
            this.aiConfiguration.disabled = !this.aiEnabled.checked;
            this.aiConfiguration.classList.toggle("opacity-50", !this.aiEnabled.checked);
            this.aiDisabledNotice.classList.toggle("d-none", this.aiEnabled.checked);
            const selected = this.aiModel.value === "" ? null : this.models.choices[Number(this.aiModel.value)];
            this.allowedModelInputs.forEach(permission => {
                const implicit = Boolean(selected && sameModel(permission.model, selected));
                permission.input.checked = permission.explicit || implicit;
                permission.input.disabled = implicit;
                permission.note.classList.toggle("d-none", !implicit);
            });
            this.updateSummary();
        }

        readPolicy() {
            const rules = this.ruleEditors.map(editor => {
                const rule = {
                    id: editor.id, name: editor.name.value.trim(), type: editor.type,
                    enabled: editor.enabled.checked, severity: editor.severity.value,
                    category: editor.category.value.trim()
                };
                if (editor.type === "pii") rule.pii_type = editor.piiType.value;
                else {
                    rule.case_sensitive = editor.caseSensitive.checked;
                    rule.whole_word = editor.wholeWord.checked;
                    if (editor.type === "regex") rule.pattern = editor.pattern.value;
                    else rule.values = editor.values.value.split(/\r?\n/).filter(value => value.length > 0);
                }
                if (!rule.name || !rule.category || !rule.severity
                    || (rule.type === "pii" && !rule.pii_type)
                    || (rule.type === "regex" && !rule.pattern)
                    || (rule.type === "literal" && !rule.values.length)) {
                    throw new screening.ScreeningError(422);
                }
                return rule;
            });
            const selection = this.aiModel.value === "" ? null : this.models.choices[Number(this.aiModel.value)];
            if (this.aiEnabled.checked && !selection) throw new screening.ScreeningError(422);
            return {
                schema_version: this.data.policy.schema_version,
                enabled: this.enabledInput.checked,
                rules,
                ai: {
                    enabled: this.aiEnabled.checked,
                    model_selection: selection ? modelReference(selection)
                        : this.aiModel.value === "unavailable" ? modelReference(this.data.policy.ai.model_selection)
                        : { endpoint_id: "", model_id: "" },
                    instructions: this.aiInstructions.value,
                    severity: this.aiSeverity.value,
                    category: this.aiCategory.value,
                    window_unit: this.aiWindow.value,
                    window_size: Number(this.aiSize.value),
                    max_characters: Number(this.aiCharacters.value),
                    overlap_characters: Number(this.aiOverlap.value)
                },
                allowed_models: this.scope.scopeType === "global"
                    ? this.allowedModelInputs.filter(item => item.explicit).map(item => modelReference(item.model)) : [],
                limits: Object.fromEntries(Array.from(this.limitInputs, ([key, input]) => [key, Number(input.value)]))
            };
        }

        renderSample(container) {
            const section = element("section", "border-top pt-3");
            section.append(
                element("h4", "h6", "Test a policy without publishing"),
                element("p", "small text-body-secondary", "Use synthetic sample text. Testing does not create document evidence or publish knowledge. Enabled model criteria send the sample to the selected model.")
            );
            this.sampleText = field(section, "Synthetic sample text", "textarea", "");
            this.sampleResult = element("div", "mt-2");
            this.sampleResult.setAttribute("aria-live", "polite");
            this.testButton = button("Test policy draft", "btn btn-outline-primary", () => this.test());
            this.testButton.disabled = !hasAction(this.data.allowed_actions, "test_policy");
            section.append(this.testButton, this.sampleResult);
            container.appendChild(section);
        }

        freezeOnConflict(error) {
            if (![403, 409, 412, 428].includes(error.status)) return;
            this.stale = true;
            this.controls.disabled = true;
            this.saveButton.disabled = true;
            const capability = document.getElementById("enable_content_screening");
            if (this.scope.scopeType === "global" && capability) capability.disabled = true;
        }

        async configure(capability) {
            const enabled = capability.checked;
            if (enabled && !this.data.policy.enabled) {
                capability.checked = false;
                showMessage(this.message, "Save an enabled mandatory policy with at least one active check before enabling new scans.", "warning");
                return;
            }
            capability.disabled = true;
            clearMessage(this.message);
            try {
                await screening.api.configure(enabled);
                await this.load();
                showMessage(this.message, enabled
                    ? "New Content Screening is enabled. Required checks run before enrolled knowledge is published."
                    : "New scans are disabled. Existing holds, review evidence, and approved-with-flags warnings remain in effect.", "success");
            } catch (error) {
                capability.checked = !enabled;
                this.freezeOnConflict(error);
                showMessage(this.message, [400, 409, 503].includes(error.status)
                    ? "Content Screening could not be changed. Verify the mandatory policy, Enhanced Citations, and its private storage. Existing holds are unchanged."
                    : errorMessage(error));
            } finally {
                capability.disabled = this.stale || (!this.data.prerequisites?.ready && !capability.checked);
            }
        }

        async save() {
            if (this.stale || !hasAction(this.data.allowed_actions, "edit_policy")) return;
            this.saveButton.disabled = true;
            clearMessage(this.message);
            try {
                const policy = this.readPolicy();
                await screening.api.savePolicy(this.scope, policy, this.data);
                await this.load();
                showMessage(this.message, "Screening policy saved. Existing holds still require explicit review.", "success");
            } catch (error) {
                this.freezeOnConflict(error);
                showMessage(this.message, errorMessage(error));
            } finally {
                this.saveButton.disabled = this.stale || !hasAction(this.data.allowed_actions, "edit_policy");
            }
        }

        async test() {
            if (this.stale || !hasAction(this.data.allowed_actions, "test_policy") || !this.sampleText.value.trim()) return;
            this.testButton.disabled = true;
            clearMessage(this.message);
            this.sampleResult.replaceChildren(element("p", "text-body-secondary", "Testing required checks…"));
            try {
                const result = await screening.api.testPolicy(this.scope, this.readPolicy(), this.sampleText.value);
                this.sampleResult.replaceChildren(element("p", "", `Result: ${result.status} · ${result.findings?.length || 0} findings`));
                (result.findings || []).forEach(finding => {
                    const entry = element("div", "border rounded p-2 mb-2");
                    entry.append(
                        element("strong", "", `${finding.category || "Finding"} · ${finding.severity || ""}`),
                        element("pre", "screening-source mb-0 mt-1", finding.evidence || "")
                    );
                    this.sampleResult.appendChild(entry);
                });
            } catch (error) {
                this.sampleResult.replaceChildren();
                this.freezeOnConflict(error);
                showMessage(this.message, errorMessage(error));
            } finally {
                this.testButton.disabled = this.stale || !hasAction(this.data.allowed_actions, "test_policy");
            }
        }
    }

    function mountPolicy(root, scope) {
        if (!root) return null;
        let editor = editors.get(root);
        if (!editor) {
            editor = new PolicyEditor(root, scope);
            editors.set(root, editor);
        }
        editor.load(scope);
        return editor;
    }

    screening.mountPolicy = mountPolicy;
    document.addEventListener("DOMContentLoaded", () => {
        document.querySelectorAll('[data-content-screening-policy][data-scope-type="global"]').forEach(root => {
            mountPolicy(root, { scopeType: "global", scopeId: "" });
        });
    });
}());
