// completeness.js
// Render model-assisted outcome metadata as inert text in classic workflow surfaces.

export function appendWorkflowCompleteness(parent, tasks) {
    if (!parent || !Array.isArray(tasks)) {
        return;
    }
    for (const task of tasks) {
        const report = task?.workflow_result?.task_completeness;
        if (report?.version !== 1) {
            continue;
        }
        const labels = {
            complete: Number(report.corrections) > 0 ? "Corrected and complete" : "Complete",
            incomplete: "Incomplete",
            verification_unavailable: "Verification unavailable",
            checking: "Checking answer",
            correcting: "Correcting answer",
        };
        if (!Object.hasOwn(labels, report.status)) {
            continue;
        }
        const details = document.createElement("details");
        details.className = "small mt-2";
        details.dataset.testid = "task-completeness";
        const summary = document.createElement("summary");
        summary.textContent = `${task.task_name || "Task"}: ${labels[report.status]} (${Number(report.corrections) || 0} corrections)`;
        details.appendChild(summary);
        const note = document.createElement("p");
        note.textContent = "Model-assisted answer completeness, separate from format validation.";
        details.appendChild(note);
        for (const item of Array.isArray(report.requirements) ? report.requirements : []) {
            const requirement = document.createElement("p");
            requirement.textContent = `${item.requirement || ""} — ${item.status || ""}. ${item.reason || ""}`;
            details.appendChild(requirement);
        }
        parent.appendChild(details);
    }
}
