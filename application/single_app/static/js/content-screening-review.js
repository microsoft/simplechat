// content-screening-review.js
(function () {
    "use strict";

    const screening = window.ContentScreening;
    const { element, button, showMessage, clearMessage, errorMessage, hasAction } = screening;
    const byId = id => document.getElementById(`screening-${id}`);

    class ContentReview {
        constructor(root) {
            this.root = root;
            this.message = byId("review-message");
            this.reviewId = "";
            this.detail = null;
            this.preview = null;
            this.edits = [];
            this.selectedRange = null;
            this.stale = false;
            this.busy = false;
            this.sequence = 0;
            this.scopeSequence = 0;
            const query = new URLSearchParams(window.location.search);
            const type = query.get("scope_type");
            this.scope = {
                scopeType: ["personal", "group", "public"].includes(type) ? type : "personal",
                scopeId: query.get("scope_id") || ""
            };
            this.reviewId = query.get("scan_id") || query.get("review_id") || "";
            byId("scope-type").value = this.scope.scopeType;
            byId("scope-id").value = this.scope.scopeId;
            this.syncScopeFields();
            this.bind();
            this.loadScope();
            if (["policy", "jobs"].includes(query.get("tab"))) {
                bootstrap.Tab.getOrCreateInstance(byId(`${query.get("tab")}-tab`)).show();
            }
        }

        bind() {
            byId("scope-type").addEventListener("change", () => this.syncScopeFields());
            byId("scope-form").addEventListener("submit", async event => {
                event.preventDefault();
                if (this.edits.length && !await screening.confirmAction("Leave candidate edits?", "Changing workspace discards the candidate edits shown here.", "Open workspace")) return;
                this.scope = {
                    scopeType: byId("scope-type").value,
                    scopeId: byId("scope-type").value === "personal" ? "" : byId("scope-id").value.trim()
                };
                if (this.scope.scopeType !== "personal" && !this.scope.scopeId) {
                    showMessage(this.message, "Choose a workspace ID, or open Content review from that workspace.", "warning");
                    return;
                }
                this.reviewId = "";
                window.history.replaceState(null, "", screening.reviewUrl(this.scope));
                this.loadScope();
            });
            byId("refresh").addEventListener("click", async () => {
                if (this.edits.length && !await screening.confirmAction("Reload the review?", "Refreshing discards local candidate edits and loads the current protected revision.", "Refresh review")) return;
                this.reviewId ? this.loadReview(this.reviewId) : this.loadReviews();
            });
            byId("load-reviews").addEventListener("click", () => this.loadReviews());
            byId("review-filter").addEventListener("change", () => this.loadReviews());
            byId("more-reviews").addEventListener("click", () => this.loadReviews(this.reviewCursor));
            byId("more-units").addEventListener("click", () => this.loadEvidence("units"));
            byId("more-findings").addEventListener("click", () => this.loadEvidence("findings"));
            byId("unit-select").addEventListener("change", () => this.renderUnit());
            byId("edit-kind").addEventListener("change", () => this.syncEditFields());
            byId("unit-text").addEventListener("mouseup", () => this.captureSelection());
            byId("unit-text").addEventListener("keyup", () => this.captureSelection());
            byId("use-selection").addEventListener("click", () => this.useSelection());
            byId("add-edit").addEventListener("click", () => this.addEdit());
            byId("reset-edits").addEventListener("click", () => this.resetEdits());
            byId("preview-edit").addEventListener("click", () => this.previewEdits());
            byId("submit-candidate").addEventListener("click", () => this.submitCandidate());
            byId("decision-reason").addEventListener("input", () => this.syncActions());
            byId("flags-acknowledged").addEventListener("change", () => this.syncActions());
            [
                ["approve-flags", "approve_with_flags"],
                ["approve-clean", "approve_clean"],
                ["reject", "reject"],
                ["retry-publication", "retry_publication"],
                ["delete", "delete"]
            ].forEach(([id, action]) => byId(id).addEventListener("click", () => this.decide(action)));
            byId("download-original").addEventListener("click", () => this.download("original"));
            byId("download-clean").addEventListener("click", () => this.download("clean"));
            window.addEventListener("pagehide", () => window.clearTimeout(this.pollTimer), { once: true });
        }

        syncScopeFields() {
            const personal = byId("scope-type").value === "personal";
            byId("scope-id-field").classList.toggle("d-none", personal);
            byId("scope-id").required = !personal;
        }

        loadScope() {
            this.sequence += 1;
            this.scopeSequence += 1;
            window.clearTimeout(this.pollTimer);
            this.detail = null;
            this.resetEdits();
            byId("review-detail").classList.add("d-none");
            screening.mountPolicy(byId("workspace-policy"), this.scope);
            screening.mountScanJobs(byId("review-scan-controls"), byId("job-list"), byId("more-jobs"), this.scope);
            this.loadReviews();
            if (this.reviewId) this.loadReview(this.reviewId);
        }

        async loadReviews(cursor = "") {
            const sequence = this.scopeSequence;
            const list = byId("review-list");
            if (!cursor) list.replaceChildren(element("p", "text-body-secondary", "Loading accessible reviews…"));
            try {
                const response = await screening.api.listReviews(this.scope, byId("review-filter").value, cursor);
                if (sequence !== this.scopeSequence) return;
                if (!cursor) list.replaceChildren();
                response.items.forEach(review => {
                    const row = element("div", "list-group-item d-flex flex-wrap align-items-center justify-content-between gap-2");
                    const description = element("div");
                    description.appendChild(element("strong", "text-break", review.file_name || "Workspace document"));
                    const status = screening.statusBadge({ content_screening: review.content_screening });
                    if (status) description.appendChild(element("div", "mt-1")).appendChild(status);
                    row.append(description, button("Open review", "btn btn-sm btn-outline-primary", () => this.openReview(review.id)));
                    list.appendChild(row);
                });
                if (!list.childElementCount) list.appendChild(element("p", "text-body-secondary", "No accessible reviews match this status."));
                this.reviewCursor = response.continuation_token || "";
                byId("more-reviews").classList.toggle("d-none", !this.reviewCursor);
            } catch (error) {
                if (sequence !== this.scopeSequence) return;
                list.replaceChildren();
                showMessage(this.message, errorMessage(error));
            }
        }

        async openReview(reviewId) {
            if (this.edits.length && !await screening.confirmAction("Leave candidate edits?", "Opening another review discards the local candidate edits.", "Open review")) return;
            window.history.replaceState(null, "", screening.reviewUrl(this.scope, reviewId));
            await this.loadReview(reviewId);
        }

        async loadReview(reviewId) {
            const sequence = ++this.sequence;
            window.clearTimeout(this.pollTimer);
            this.reviewId = reviewId;
            this.busy = true;
            this.syncActions();
            clearMessage(this.message);
            try {
                const detail = await screening.api.getReview(this.scope, reviewId);
                if (sequence !== this.sequence) return;
                this.detail = detail;
                this.stale = false;
                this.edits = [];
                this.preview = null;
                this.renderDetail();
                if (["pending_scan", "scanning", "remediating", "publishing"].includes(detail.content_screening?.state)) {
                    this.schedulePoll(reviewId, sequence);
                }
            } catch (error) {
                if (sequence !== this.sequence) return;
                this.stale = true;
                if ([401, 403, 404].includes(error.status)) this.clearProtectedContent();
                showMessage(this.message, errorMessage(error));
            } finally {
                if (sequence === this.sequence) {
                    this.busy = false;
                    this.syncActions();
                }
            }
        }

        schedulePoll(reviewId, sequence) {
            this.pollTimer = window.setTimeout(() => {
                if (sequence !== this.sequence) return;
                if (document.hidden || this.busy) this.schedulePoll(reviewId, sequence);
                else this.loadReview(reviewId);
            }, 4000);
        }

        clearProtectedContent() {
            window.clearTimeout(this.pollTimer);
            this.detail = null;
            this.edits = [];
            this.preview = null;
            ["unit-text", "findings", "diff", "edit-list", "document-title", "recorded-decision", "review-warning", "unit-select"].forEach(id => byId(id).replaceChildren());
            byId("decision-reason").value = "";
            byId("flags-acknowledged").checked = false;
            byId("review-detail").classList.add("d-none");
            this.syncActions();
        }

        renderDetail() {
            const detail = this.detail;
            byId("review-detail").classList.remove("d-none");
            byId("document-title").textContent = detail.file_name || "Workspace document";
            byId("document-state").replaceChildren();
            const badge = screening.statusBadge({ content_screening: detail.content_screening });
            if (badge) byId("document-state").appendChild(badge);
            const coverage = detail.coverage;
            const counts = Number.isInteger(coverage.units_total) ? ` ${coverage.units_total} source units.` : "";
            byId("review-coverage").textContent = coverage.complete
                ? `Required scan coverage complete.${counts}`
                : `Required scan coverage incomplete.${counts} Approval is unavailable.`;
            byId("review-origin").textContent = detail.coverage_mode === "indexed_snapshot"
                ? "Coverage: retained indexed knowledge only. Missing source bytes and original formatting were not inspected."
                : "Coverage applies to canonical extracted knowledge. Original appearance, font color, and hidden-layer formatting are not inspected.";
            const pending = ["pending_scan", "scanning", "remediating"].includes(detail.content_screening?.state);
            byId("candidate-pending").classList.toggle("d-none", !pending || !detail.candidate_of);
            byId("evidence-unavailable").classList.toggle("d-none",
                !detail.evidence_unavailable && detail.evidence?.units_available === true);
            byId("review-warning").textContent = detail.warning || "";
            byId("review-warning").classList.toggle("d-none", !detail.warning);
            byId("recorded-decision").textContent = detail.decision?.reason
                ? `Recorded decision: ${detail.decision.action.replace(/_/g, " ")}. ${detail.decision.reason}` : "";
            byId("recorded-decision").classList.toggle("d-none", !detail.decision?.reason);
            this.renderEvidence();
            byId("decision-reason").value = "";
            byId("flags-acknowledged").checked = false;
            this.renderUnit();
            this.renderEdits();
        }

        renderEvidence() {
            const selected = byId("unit-select").value;
            byId("unit-select").replaceChildren();
            this.detail.units.forEach((unit, index) => {
                const offset = unit.text_offset || 0;
                const length = screening.codePointLength(unit.text);
                const windowLabel = offset || unit.text_total > length ? ` · offsets ${offset}–${offset + length} of ${unit.text_total}` : "";
                const option = element("option", "", `${index + 1}. ${screening.formatLocator(unit.locator)}${windowLabel}`);
                option.value = String(index);
                byId("unit-select").appendChild(option);
            });
            if (selected) byId("unit-select").value = selected;
            byId("findings").replaceChildren();
            this.detail.findings.forEach((finding, index) => {
                const item = button("", "list-group-item list-group-item-action text-start", () => this.openFinding(finding));
                item.append(
                    element("strong", "d-block", `${index + 1}. ${finding.category || "Finding"} · ${finding.severity || ""}`),
                    element("span", "d-block small mt-1 text-break", finding.reason || finding.explanation || finding.message || ""),
                    element("span", "d-block small mt-1 text-break", finding.evidence || "")
                );
                byId("findings").appendChild(item);
            });
            if (!this.detail.findings.length) byId("findings").appendChild(element("p", "text-body-secondary",
                this.detail.evidence?.findings_available === true && !this.detail.evidence_unavailable
                    ? "No findings in this scan. Complete coverage and explicit approval are still required."
                    : "Findings are not available for this scan. Missing results are not a clean verdict."));
            byId("more-units").classList.toggle("d-none", !this.detail.units_continuation);
            byId("more-findings").classList.toggle("d-none", !this.detail.findings_continuation);
        }

        async loadEvidence(kind) {
            if (!this.detail || this.busy || this.stale) return;
            const cursor = this.detail[`${kind}_continuation`];
            if (!cursor) return;
            const sequence = this.sequence;
            const control = byId(`more-${kind}`);
            control.disabled = true;
            try {
                const page = await screening.api.getEvidence(this.reviewId, kind, cursor);
                if (sequence !== this.sequence) return;
                this.detail[kind].push(...(page.items || []));
                this.detail[`${kind}_continuation`] = page.continuation || "";
                this.detail[`${kind}_complete`] = !page.continuation;
                this.renderEvidence();
                this.renderUnit();
                this.syncActions();
            } catch (error) {
                if ([401, 403, 404].includes(error.status)) this.clearProtectedContent();
                showMessage(this.message, errorMessage(error));
            } finally {
                control.disabled = false;
            }
        }

        currentUnit() {
            return this.detail?.units[Number(byId("unit-select").value)] || null;
        }

        renderUnit(offsets = null) {
            const unit = this.currentUnit();
            this.selectedRange = null;
            if (!unit) {
                byId("unit-text").textContent = "Canonical units are not available for this revision.";
                byId("unit-location").textContent = "";
                byId("edit-kind").replaceChildren();
                return;
            }
            byId("unit-location").textContent = `${screening.formatLocator(unit.locator)} · normalization ${unit.normalization_version}`;
            const textOffset = unit.text_offset || 0;
            const localOffsets = offsets ? { start: offsets.start - textOffset, end: offsets.end - textOffset } : null;
            screening.renderSourceText(byId("unit-text"), unit.text, localOffsets);
            const options = [{ value: "remove_span", label: "Remove a text span" }];
            const hasSourcePage = Number.isInteger(unit.locator?.page_number) && unit.locator.page_number > 0;
            if (hasSourcePage) {
                if (this.detail.units_complete) {
                    options.push({ value: "remove_page", label: `Remove source page ${unit.locator.page_number} and linked units` });
                }
            } else {
                options.push({ value: "remove_unit", label: "Remove this source unit" });
            }
            if (["table_cell", "table_formula"].includes(unit.locator?.kind)) {
                options.push({ value: "replace_cell", label: "Replace this cell" }, { value: "clear_cell", label: "Clear this cell" });
            }
            byId("edit-kind").replaceChildren();
            options.forEach(value => {
                const option = element("option", "", value.label);
                option.value = value.value;
                byId("edit-kind").appendChild(option);
            });
            byId("span-start").value = offsets?.start ?? textOffset;
            byId("span-end").value = offsets?.end ?? textOffset;
            byId("span-start").min = textOffset;
            byId("span-end").min = textOffset;
            byId("span-start").max = textOffset + screening.codePointLength(unit.text);
            byId("span-end").max = textOffset + screening.codePointLength(unit.text);
            byId("cell-value").value = "";
            this.syncEditFields();
        }

        openFinding(finding) {
            const index = this.detail.units.findIndex(unit => unit.unit_id === finding.unit_id && (
                !Number.isInteger(finding.start) || (finding.start >= (unit.text_offset || 0)
                    && finding.end <= (unit.text_offset || 0) + screening.codePointLength(unit.text))
            ));
            if (index < 0) {
                showMessage(this.message, "This finding is outside the loaded text window or has no precise location. Load more source units or review the whole unit; no offset was inferred.", "warning");
                return;
            }
            byId("unit-select").value = String(index);
            const offsets = Number.isInteger(finding.start) && Number.isInteger(finding.end)
                ? { start: finding.start, end: finding.end } : null;
            this.renderUnit(offsets);
            byId("unit-text").focus();
        }

        captureSelection() {
            const range = screening.selectedCodePointRange(byId("unit-text"));
            const offset = this.currentUnit()?.text_offset || 0;
            this.selectedRange = range ? { start: range.start + offset, end: range.end + offset } : null;
        }

        useSelection() {
            const local = screening.selectedCodePointRange(byId("unit-text"));
            const offset = this.currentUnit()?.text_offset || 0;
            const selection = local ? { start: local.start + offset, end: local.end + offset } : this.selectedRange;
            if (!selection) {
                showMessage(this.message, "Select text within one canonical source unit first.", "warning");
                return;
            }
            byId("span-start").value = selection.start;
            byId("span-end").value = selection.end;
            clearMessage(this.message);
        }

        syncEditFields() {
            const action = byId("edit-kind").value;
            byId("span-fields").classList.toggle("d-none", action !== "remove_span");
            byId("cell-fields").classList.toggle("d-none", action !== "replace_cell");
        }

        addEdit() {
            const unit = this.currentUnit();
            if (!unit || this.stale || this.busy || !hasAction(this.detail.allowed_actions, "remediate")) return;
            const action = byId("edit-kind").value;
            const edit = {
                action, unit_id: unit.unit_id, content_hash: unit.content_hash,
                normalization_version: unit.normalization_version, locator: { ...unit.locator }
            };
            if (action === "remove_span") {
                edit.start = Number(byId("span-start").value);
                edit.end = Number(byId("span-end").value);
                const offset = unit.text_offset || 0;
                if (!Number.isInteger(edit.start) || !Number.isInteger(edit.end) || edit.start < offset
                    || edit.end <= edit.start || edit.end > offset + screening.codePointLength(unit.text)) {
                    showMessage(this.message, "Choose a non-empty span within this source unit using Unicode code-point offsets.", "warning");
                    return;
                }
            }
            if (action === "remove_page" && (!Number.isInteger(unit.locator?.page_number) || unit.locator.page_number < 1)) return;
            if (action === "replace_cell") edit.value = byId("cell-value").value;
            if (action === "clear_cell") edit.value = "";
            this.edits.push(edit);
            this.preview = null;
            clearMessage(this.message);
            this.renderEdits();
        }

        renderEdits() {
            byId("edit-list").replaceChildren();
            this.edits.forEach((edit, index) => {
                const row = element("li", "mb-2");
                let description = `${edit.action.replace(/_/g, " ")} · ${screening.formatLocator(edit.locator)}`;
                if (edit.action === "remove_span") description += ` · [${edit.start}, ${edit.end})`;
                row.append(
                    element("span", "me-2", description),
                    button("Remove edit", "btn btn-sm btn-outline-secondary", () => {
                        this.edits.splice(index, 1);
                        this.preview = null;
                        this.renderEdits();
                    })
                );
                byId("edit-list").appendChild(row);
            });
            if (!this.preview) {
                byId("preview").classList.add("d-none");
                byId("diff").replaceChildren();
            }
            this.syncActions();
        }

        resetEdits() {
            this.edits = [];
            this.preview = null;
            this.renderEdits();
        }

        completeCoverage() {
            const coverage = this.detail?.coverage;
            return coverage?.complete === true && this.detail.units.length > 0 && this.detail.units_complete && this.detail.findings_complete
                && !["error", "incomplete", "pending", "scanning"].includes(coverage.status)
                && !["pending_scan", "scanning", "scan_error", "incomplete", "remediating", "publishing"].includes(this.detail.content_screening?.state);
        }

        syncActions() {
            const actions = this.detail?.allowed_actions;
            const blocked = this.busy || this.stale || !this.detail;
            const complete = this.completeCoverage();
            const canEdit = !blocked && hasAction(actions, "remediate") && Boolean(this.detail?.units.length);
            const hasReason = Boolean(byId("decision-reason").value.trim());
            byId("edit-controls").disabled = !canEdit;
            byId("decisions").disabled = blocked;
            byId("preview-edit").disabled = !canEdit || !this.edits.length;
            byId("submit-candidate").disabled = !canEdit || !this.preview;
            byId("approval-blocked").classList.toggle("d-none", complete && !this.stale);
            byId("approval-blocked").textContent = this.stale
                ? "Refresh required. The previous revision or permission snapshot cannot authorize a decision."
                : this.detail?.evidence_unavailable || this.detail?.evidence?.units_available !== true
                    ? "Canonical evidence is unavailable. Approval requires verified source content; authorized Reject/Delete actions remain available."
                : this.detail?.coverage.complete && (!this.detail.units_complete || !this.detail.findings_complete)
                    ? "Load the remaining source units and findings before approving this revision."
                    : "Approval requires a completed scan of this exact revision. Missing, pending, or failed checks keep it held.";
            byId("approve-flags").disabled = blocked || !complete || this.edits.length > 0
                || !hasAction(actions, "approve_with_flags")
                || !byId("decision-reason").value.trim() || !byId("flags-acknowledged").checked;
            byId("approve-clean").disabled = blocked || !complete || this.edits.length > 0
                || !hasAction(actions, "approve_clean") || this.detail?.findings.length !== 0
                || this.detail?.content_screening?.finding_count !== 0 || !hasReason;
            byId("reject").disabled = blocked || !hasAction(actions, "reject") || !hasReason;
            byId("retry-publication").classList.toggle("d-none", !hasAction(actions, "retry_publication"));
            byId("retry-publication").disabled = blocked || !hasAction(actions, "retry_publication");
            byId("delete").disabled = blocked || !hasAction(actions, "delete") || !hasReason;
            byId("download-original").disabled = blocked || !hasAction(actions, "download_original") || !this.detail?.downloads?.original;
            byId("download-clean").disabled = blocked || !hasAction(actions, "download_clean") || !this.detail?.downloads?.clean;
        }

        async mutate(operation, successMessage, refresh = true) {
            if (this.busy || this.stale) return null;
            const sequence = this.sequence;
            this.busy = true;
            this.syncActions();
            clearMessage(this.message);
            try {
                const result = await operation();
                if (sequence !== this.sequence) return null;
                if (refresh) {
                    this.edits = [];
                    if (result?.id) this.reviewId = result.id;
                    window.history.replaceState(null, "", screening.reviewUrl(this.scope, this.reviewId));
                    await this.loadReview(this.reviewId);
                }
                if (!this.stale) showMessage(this.message, successMessage, "success");
                return result;
            } catch (error) {
                if (sequence !== this.sequence) return null;
                this.stale = ![400, 422, 429].includes(error.status);
                if ([401, 403, 404].includes(error.status)) this.clearProtectedContent();
                showMessage(this.message, errorMessage(error));
                return null;
            } finally {
                this.busy = false;
                this.syncActions();
            }
        }

        async previewEdits() {
            if (!this.edits.length || this.busy || this.stale) return;
            const edits = this.edits.slice();
            const result = await this.mutate(
                () => screening.api.preview(this.scope, this.reviewId, edits, this.detail),
                "Preview created. Nothing has been published.", false
            );
            if (!result) return;
            this.edits = edits;
            this.preview = result;
            byId("preview-warning").classList.toggle("d-none", result.preview_truncated !== true);
            byId("preview-warning").textContent = "This diff is a bounded preview, not a complete source display. The entire candidate will be rescanned and must be explicitly reviewed before publication.";
            byId("diff").replaceChildren();
            result.diff.forEach(change => {
                const section = element("section", "mb-3");
                section.appendChild(element("h4", "h6", screening.formatLocator(change.locator)));
                const row = element("div", "row g-2");
                [["Before", change.before, "screening-diff-before"], ["Candidate", change.after, "screening-diff-after"]].forEach(([label, text, className]) => {
                    const column = element("div", "col-md-6");
                    column.append(element("h5", "small fw-bold", label), element("pre", `screening-diff-text border rounded p-2 ${className}`, text));
                    row.appendChild(column);
                });
                section.appendChild(row);
                byId("diff").appendChild(section);
            });
            byId("preview").classList.remove("d-none");
            this.syncActions();
        }

        async submitCandidate() {
            if (!this.preview || byId("submit-candidate").disabled) return;
            const preview = this.preview;
            const snapshot = this.detail;
            const reviewId = this.reviewId;
            const scope = { ...this.scope };
            if (!await screening.confirmAction("Submit candidate for rescan?", "The candidate stays held. All required checks must complete, followed by an explicit review decision.", "Submit and rescan")) return;
            if (!this.confirmationStillCurrent(snapshot, reviewId) || this.preview !== preview) return;
            await this.mutate(
                () => screening.api.submitCandidate(scope, reviewId, preview, snapshot),
                "Candidate submitted for complete rescan. It has not been approved or published."
            );
        }

        confirmationStillCurrent(snapshot, reviewId) {
            if (this.detail && this.reviewId === reviewId && this.detail.etag === snapshot.etag) return true;
            this.stale = true;
            showMessage(this.message, "The review changed while confirmation was open. Refresh required; no action was submitted.");
            this.syncActions();
            return false;
        }

        async decide(action) {
            const buttonIds = { approve_with_flags: "approve-flags", approve_clean: "approve-clean", reject: "reject", delete: "delete", retry_publication: "retry-publication" };
            if (!buttonIds[action] || byId(buttonIds[action]).disabled) return;
            const snapshot = this.detail;
            const reviewId = this.reviewId;
            const scope = { ...this.scope };
            const decision = {
                reason: byId("decision-reason").value.trim(),
                acknowledged: byId("flags-acknowledged").checked
            };
            const descriptions = {
                approve_with_flags: "Authorize this exact scanned revision despite its findings? The warning and your reason are retained.",
                approve_clean: "Approve the fully scanned clean revision? Only the cleaned knowledge and its derivative may be published.",
                reject: "Keep this document unavailable to ordinary chat, search, tools, and downloads?",
                retry_publication: "Retry publication for the existing, exact approved decision? This does not approve a failed scan or a new revision.",
                delete: "Delete this document and its screened content? Availability is revoked before deletion; this cannot be undone here."
            };
            if (!await screening.confirmAction("Confirm content review decision", descriptions[action], byId(buttonIds[action]).textContent, action === "delete")) return;
            if (!this.confirmationStillCurrent(snapshot, reviewId)) return;
            const result = await this.mutate(
                () => screening.api.decide(scope, reviewId, action, decision, snapshot),
                action === "delete" ? "Document deletion accepted. It is not available for ordinary use." : "Decision accepted. Availability is determined by completed publication.",
                action !== "delete"
            );
            if (result && action === "delete") {
                this.clearProtectedContent();
                this.loadReviews();
            }
        }

        async download(kind) {
            if (this.busy || this.stale || byId(`download-${kind}`).disabled) return;
            clearMessage(this.message);
            try {
                const download = screening.api.reviewDownload(this.scope, this.reviewId, kind, this.detail);
                await screening.downloadAttachment(download.url, download.file_name);
            } catch (error) {
                if ([401, 403, 404].includes(error.status)) this.clearProtectedContent();
                showMessage(this.message, errorMessage(error));
            }
        }
    }

    document.addEventListener("DOMContentLoaded", () => {
        const root = document.getElementById("content-screening-review-app");
        if (root) new ContentReview(root);
    });
}());
