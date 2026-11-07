// content-screening-api.js
(function () {
    "use strict";

    const screening = window.ContentScreening;
    const base = "/api/content-screening";
    const policyRequests = new Map();
    let configurationRequest = null;

    function resolveScope(scope) {
        if (scope.scopeType === "global") return { scopeType: "global", scopeId: "global" };
        const scopeId = scope.scopeId || (scope.scopeType === "personal"
            ? document.querySelector('meta[name="screening-user-id"]')?.content || window.current_user_id : "");
        if (!["personal", "group", "public"].includes(scope.scopeType) || !scopeId) throw new screening.ScreeningError(400);
        return { scopeType: scope.scopeType, scopeId: String(scopeId) };
    }

    function policyPath(scope) {
        const resolved = resolveScope(scope);
        return `${base}/policies/${resolved.scopeType}/${encodeURIComponent(resolved.scopeId)}`;
    }

    function reviewPath(reviewId, suffix = "") {
        if (!reviewId) throw new screening.ScreeningError(400);
        return `${base}/reviews/${encodeURIComponent(reviewId)}${suffix}`;
    }

    function getConfiguration() {
        if (!configurationRequest) {
            configurationRequest = screening.request(`${base}/configuration`)
                .finally(() => { configurationRequest = null; });
        }
        return configurationRequest;
    }

    function rawPolicy(scope) {
        const path = policyPath(scope);
        if (!policyRequests.has(path)) {
            policyRequests.set(path, screening.request(path).finally(() => policyRequests.delete(path)));
        }
        return policyRequests.get(path);
    }

    function normalizeTemplates(templates = {}) {
        const rules = templates.rules || {};
        const ruleList = Object.values(rules);
        const packs = Object.entries(templates.packs || {}).map(([id, pack]) => ({
            id,
            name: pack.name || id.replace(/_/g, " "),
            rules: (Array.isArray(pack) ? pack : pack.rules || [])
                .map(rule => typeof rule === "string" ? rules[rule] : rule).filter(Boolean)
        }));
        return {
            starter_packs: packs,
            ai_starters: Object.entries(templates.ai || {}).map(([id, instructions]) => ({
                id, instructions: typeof instructions === "string" ? instructions : instructions.instructions,
                name: typeof instructions === "object" ? instructions.name : id.replace(/_/g, " ")
            })),
            pii_types: [...new Set(ruleList.filter(rule => rule.type === "pii").map(rule => rule.pii_type))],
            pii_choices: ruleList.filter(rule => rule.type === "pii").map(rule => ({
                value: rule.pii_type, label: rule.name
            })),
            severities: ["low", "medium", "high", "critical"],
            rule_defaults: Object.fromEntries(["pii", "regex", "literal"].map(type => {
                const rule = ruleList.find(item => item.type === type);
                return [type, rule ? { severity: rule.severity, category: rule.category, enabled: rule.enabled } : {}];
            }))
        };
    }

    function scopedActions(scope, configuration, policy) {
        if (policy.allowed_actions) return policy.allowed_actions;
        // Policy GET and PUT share the same object-level manager contract.
        if (scope.scopeType === "global") {
            return configuration.can_manage_global
                ? ["edit_policy", "test_policy", ...(configuration.can_scan_all ? ["scan_global"] : [])] : [];
        }
        return ["edit_policy", "test_policy", "scan"];
    }

    async function getPolicy(scope) {
        const [policy, configuration] = await Promise.all([rawPolicy(scope), getConfiguration()]);
        return {
            ...policy,
            allowed_actions: scopedActions(scope, configuration, policy),
            new_scans_enabled: configuration.enabled === true,
            prerequisites: {
                ready: configuration.enhanced_citations_enabled === true && configuration.storage_ready !== false,
                storage_validated: configuration.storage_ready === true
            },
            baseline: policy.inherited_summary,
            configuration
        };
    }

    async function getModels(scope) {
        const [policy, configuration] = await Promise.all([rawPolicy(scope), getConfiguration()]);
        const approved = scope.scopeType === "global" ? null : policy.allowed_models || [];
        if (scope.scopeType !== "global") {
            return {
                choices: approved.filter(model => model.endpoint_id && model.model_id).map(model => ({
                    endpoint_id: model.endpoint_id, model_id: model.model_id, label: model.model_id
                }))
            };
        }
        if (!configuration.can_manage_global) return { choices: [] };
        const response = await fetch("/api/v2/admin/capability-models/chat", {
            credentials: "same-origin", cache: "no-store", redirect: "manual", headers: { Accept: "application/json" }
        });
        if (response.redirected || response.type === "opaqueredirect") throw new screening.ScreeningError(401);
        if (!response.ok) throw new screening.ScreeningError(response.status);
        if (!response.headers.get("Content-Type")?.includes("application/json")) throw new screening.ScreeningError();
        const data = await response.json();
        return {
            choices: (data.choices || []).map(model => ({
                endpoint_id: model.endpoint_id, model_id: model.model_id,
                label: model.label, connection_name: model.connection_name
            }))
        };
    }

    function mutationOptions(method, payload, snapshot = {}) {
        const headers = {};
        if (snapshot.idempotency_key) headers["Idempotency-Key"] = snapshot.idempotency_key;
        return { method, body: JSON.stringify(payload), headers };
    }

    function etagOf(snapshot) {
        if (snapshot.etag !== undefined) return snapshot.etag;
        if (snapshot.responseEtag) return snapshot.responseEtag;
        throw new screening.ScreeningError(428);
    }

    function pageQuery(scope, cursor = "") {
        const query = screening.scopeQuery(resolveScope(scope));
        query.set("page_size", "100");
        if (cursor) query.set("continuation", cursor);
        return query;
    }

    async function getEvidence(reviewId, kind, cursor = "") {
        const query = new URLSearchParams({ page_size: "100" });
        if (cursor) query.set("continuation", cursor);
        return screening.request(`${reviewPath(reviewId, `/${kind}`)}?${query}`);
    }

    function approvedDownload(review, kind) {
        const download = review.downloads?.[kind];
        const reviewId = review.scan_id || review.id;
        if (!["original", "clean"].includes(kind) || !reviewId
            || !screening.hasAction(review.allowed_actions, `download_${kind}`)
            || download?.url !== reviewPath(reviewId, `/downloads/${kind}`)
            || ["deleting", "deleted"].includes(review.state)
            || kind === "clean" && !["cleared", "approved_with_flags"].includes(review.state)
            || typeof download.file_name !== "string" || !download.file_name) return null;
        return { url: download.url, file_name: download.file_name };
    }

    function normalizeReview(raw, units = [], findings = []) {
        const state = raw.content_screening?.state || raw.state || "pending_review";
        const summary = raw.content_screening || {
            state,
            available: raw.available === true,
            finding_count: raw.finding_count,
            scan_id: raw.scan_id || raw.id,
            review_id: raw.scan_id || raw.id
        };
        const coverage = raw.coverage || {};
        return {
            ...raw,
            id: raw.scan_id || raw.id,
            file_name: raw.file_name || (raw.subject?.document_id ? `Document ${raw.subject.document_id}` : "Workspace document"),
            content_screening: summary,
            allowed_actions: raw.allowed_actions || [],
            coverage: {
                complete: coverage.complete === true,
                units_total: coverage.units_total,
                status: coverage.status || raw.outcome
            },
            coverage_mode: raw.coverage_mode || raw.source_coverage,
            downloads: { original: approvedDownload(raw, "original"), clean: approvedDownload(raw, "clean") },
            units,
            findings: findings.map(finding => ({ ...finding, explanation: finding.reason || finding.explanation || "" }))
        };
    }

    function normalizeJob(raw) {
        const counts = raw.counters || {};
        return {
            ...raw,
            id: raw.job_id || raw.id,
            status: raw.state,
            counts,
            allowed_actions: raw.allowed_actions || []
        };
    }

    function wireEdits(edits, detail) {
        const result = [];
        const removedUnits = new Set();
        edits.forEach(edit => {
            if (edit.action === "remove_page") {
                if (!detail.units_complete || !Number.isInteger(edit.locator.page_number)) throw new screening.ScreeningError(422);
                detail.units.filter(unit => unit.locator?.page_number === edit.locator.page_number).forEach(unit => {
                    if (removedUnits.has(unit.unit_id)) return;
                    result.push({ action: "remove_unit", unit_id: unit.unit_id, content_hash: unit.content_hash });
                    removedUnits.add(unit.unit_id);
                });
                return;
            }
            const unitEdit = { action: edit.action, unit_id: edit.unit_id, content_hash: edit.content_hash };
            if (edit.action === "remove_span") Object.assign(unitEdit, { start: edit.start, end: edit.end });
            if (edit.action === "replace_cell" || edit.action === "clear_cell") {
                unitEdit.action = "replace_cell";
                unitEdit.text = edit.action === "clear_cell" ? "" : edit.value;
            }
            result.push(unitEdit);
        });
        return result;
    }

    function previewDiff(preview, detail) {
        const before = new Map();
        detail.units.forEach(unit => {
            if (!before.has(unit.unit_id)) before.set(unit.unit_id, { ...unit, text: "" });
            before.get(unit.unit_id).text += unit.text;
        });
        const after = new Map((preview.units || []).map(unit => [unit.unit_id, unit]));
        const removed = new Set(preview.removed_unit_ids || []);
        const diff = [];
        before.forEach((unit, id) => {
            if (removed.has(id)) diff.push({ locator: unit.locator, before: unit.text, after: "[Source unit removed]" });
            else if (after.has(id) && after.get(id).text !== unit.text) {
                diff.push({ locator: unit.locator, before: unit.text, after: after.get(id).text });
            }
        });
        return diff;
    }

    screening.api = {
        getConfiguration,
        getPolicy,
        getModels,
        getTemplates: async () => normalizeTemplates((await getConfiguration()).templates),
        configure: (enabled, workspaceUploadsEnabled) => screening.request(`${base}/configuration`, mutationOptions("PUT", {
            enabled,
            ...(typeof workspaceUploadsEnabled === "boolean" ? { workspace_uploads_enabled: workspaceUploadsEnabled } : {})
        })),
        savePolicy: (scope, policy, snapshot) => screening.request(policyPath(scope), mutationOptions("PUT", { policy, etag: etagOf(snapshot) }, snapshot)),
        testPolicy: (scope, policy, sampleText) => screening.request(`${policyPath(scope)}/test`, mutationOptions("POST", { policy, sample_text: sampleText })),
        getStatus: (scope, documentId) => {
            const query = screening.scopeQuery(resolveScope(scope));
            query.set("document_id", documentId);
            return screening.request(`${base}/status?${query}`);
        },
        listReviews: async (scope, state, cursor) => {
            const query = pageQuery(scope, cursor);
            query.set("state", state);
            const result = await screening.request(`${base}/reviews?${query}`);
            return {
                items: (result.items || []).map(review => normalizeReview(review)),
                continuation_token: result.continuation
            };
        },
        getReview: async (scope, reviewId) => {
            const raw = await screening.request(reviewPath(reviewId));
            let evidenceUnavailable = false;
            const readEvidence = async kind => {
                if (raw.evidence?.[`${kind}_available`] !== true) {
                    return { items: [], continuation: null, unavailable: true };
                }
                try {
                    return await getEvidence(reviewId, kind);
                } catch (error) {
                    if ([401, 403].includes(error.status)
                        || error.status === 404 && error.code !== "screening_evidence_unavailable") throw error;
                    evidenceUnavailable = true;
                    return { items: [], continuation: null, unavailable: true };
                }
            };
            const [units, findings] = await Promise.all([
                readEvidence("units"), readEvidence("findings")
            ]);
            return {
                ...normalizeReview(raw, units.items || [], findings.items || []),
                evidence_unavailable: evidenceUnavailable,
                units_complete: !units.unavailable && !units.continuation,
                findings_complete: !findings.unavailable && !findings.continuation,
                units_continuation: units.continuation || "",
                findings_continuation: findings.continuation || ""
            };
        },
        getEvidence,
        preview: async (scope, reviewId, edits, detail) => {
            const body = { etag: etagOf(detail), edits: wireEdits(edits, detail) };
            const preview = await screening.request(reviewPath(reviewId, "/preview"), mutationOptions("POST", body, detail));
            return { ...preview, diff: previewDiff(preview, detail), submitted_edits: body.edits, review_etag: body.etag };
        },
        submitCandidate: async (scope, reviewId, preview, detail) => {
            if (preview.review_etag !== etagOf(detail)) throw new screening.ScreeningError(409);
            const result = await screening.request(reviewPath(reviewId, "/remediate"), mutationOptions("POST", {
                etag: preview.review_etag, edits: preview.submitted_edits
            }, preview.idempotency_key ? preview : detail));
            if (preview.content_fingerprint && result.content_fingerprint
                && preview.content_fingerprint !== result.content_fingerprint) throw new screening.ScreeningError(409);
            return normalizeReview(result);
        },
        decide: async (scope, reviewId, action, decision, detail) => normalizeReview(await screening.request(
            reviewPath(reviewId, "/decision"), mutationOptions("POST", {
                etag: etagOf(detail), action,
                reason: action === "retry_publication" ? detail.decision?.reason : decision.reason,
                ...(action === "approve_with_flags" ? { acknowledge_flags: decision.acknowledged === true } : {})
            }, detail)
        )),
        reviewDownload: (scope, reviewId, kind, detail) => {
            const download = approvedDownload(detail, kind);
            if (detail.id !== reviewId || !download) throw new screening.ScreeningError(403);
            return download;
        },
        listJobs: async (scope, cursor) => {
            const query = scope.scopeType === "global" ? new URLSearchParams({ page_size: "100" }) : pageQuery(scope, cursor);
            if (cursor) query.set("continuation", cursor);
            const result = await screening.request(`${base}/scans?${query}`);
            return { items: (result.items || []).map(normalizeJob), continuation_token: result.continuation };
        },
        getJob: async (scope, jobId) => normalizeJob(await screening.request(`${base}/scans/${encodeURIComponent(jobId)}`)),
        startScan: async (scope, documentIds) => {
            const resolved = resolveScope(scope);
            const body = resolved.scopeType === "global" ? { all_workspaces: true }
                : { scope_type: resolved.scopeType, scope_id: resolved.scopeId, ...(documentIds ? { document_ids: documentIds } : {}) };
            return normalizeJob(await screening.request(`${base}/scans`, mutationOptions("POST", body)));
        },
        updateJob: (scope, job, action) => screening.request(`${base}/scans/${encodeURIComponent(job.id)}/actions`, mutationOptions("POST", { action }, job))
    };
}());
