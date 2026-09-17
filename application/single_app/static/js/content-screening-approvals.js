// content-screening-approvals.js
(function () {
    "use strict";

    const screening = window.ContentScreening;

    function isScreeningApproval(approval) {
        return (approval.request_type || approval.action_type) === "content_screening_review";
    }

    function screeningApprovalLink(approval) {
        try {
            const url = new URL(approval.metadata?.review_url || "/content-review", window.location.origin);
            if (url.origin !== window.location.origin || url.pathname !== "/content-review" || url.username || url.password) return "/content-review";
            const query = new URLSearchParams();
            ["scope_type", "scope_id", "scan_id"].forEach(key => {
                if (url.searchParams.has(key)) query.set(key, url.searchParams.get(key));
            });
            return `/content-review${query.size ? `?${query}` : ""}`;
        } catch {
            return "/content-review";
        }
    }

    function reviewLink(approval) {
        const link = screening.element("a", "btn btn-sm btn-outline-primary", "Open content review");
        link.href = screeningApprovalLink(approval);
        return link;
    }

    function approvalDate(approval) {
        const date = new Date(approval.created_at);
        return Number.isNaN(date.getTime()) ? "Date unavailable" : date.toLocaleString();
    }

    function renderScreeningApprovalRow(approval) {
        const row = screening.element("tr");
        const type = screening.element("td");
        type.appendChild(screening.element("span", "badge text-bg-secondary", "Content Screening"));
        const target = screening.element("td", "", "Protected workspace knowledge");
        const requester = screening.element("td", "small", approval.requester_name || approval.requested_by || "Unknown");
        const created = screening.element("td", "small", approvalDate(approval));
        const status = screening.element("td");
        const pending = approval.status === "pending";
        status.appendChild(screening.element("span", pending ? "badge text-bg-warning" : "badge text-bg-secondary", pending ? "Pending review" : "Resolved"));
        const actions = screening.element("td");
        actions.appendChild(reviewLink(approval));
        row.append(type, target, requester, created, status, actions);
        return row;
    }

    function renderScreeningApprovalDetails(approval) {
        const modal = document.getElementById("approvalActionModal");
        modal.dataset.screeningReview = "true";
        modal.querySelector(".modal-title").textContent = "Content screening review";
        document.getElementById("approvalDetailType").textContent = "Content Screening";
        document.getElementById("approvalDetailGroup").textContent = "Protected workspace knowledge";
        document.getElementById("approvalDetailRequester").textContent = approval.requester_name || "Unknown";
        document.getElementById("approvalDetailDate").textContent = approvalDate(approval);
        document.getElementById("approvalDetailReason").replaceChildren(
            screening.element("p", "", "This request requires protected evidence and a revision-bound decision in Content review. Generic approval and denial cannot change a content hold."),
            reviewLink(approval)
        );
        ["approvalApproveBtn", "approvalDenyBtn", "approvalCommentRequired", "cannotApproveAlert"].forEach(id => {
            document.getElementById(id)?.classList.add("d-none");
        });
        const comment = document.getElementById("approvalActionComment");
        comment.value = "";
        comment.required = false;
        comment.closest(".mb-3").classList.add("d-none");
    }

    Object.assign(screening, { isScreeningApproval, screeningApprovalLink, renderScreeningApprovalRow, renderScreeningApprovalDetails });
}());
