// m365-approvals.js
(() => {
    'use strict';

    function isM365Approval(approval) {
        return Object.prototype.hasOwnProperty.call(window.SimpleChatM365Approvals.typeLabels, approval?.request_type);
    }

    function showListError(error) {
        let alert = document.getElementById('m365-approval-list-error');
        if (!alert) {
            alert = document.createElement('div');
            alert.id = 'm365-approval-list-error';
            alert.className = 'alert alert-danger';
            alert.setAttribute('role', 'alert');
            document.getElementById('approvalsTable')?.parentElement.before(alert);
        }
        alert.textContent = error.message || 'The Microsoft 365 approval could not be opened.';
    }

    function renderRow(approval, onUpdated) {
        const api = window.SimpleChatM365Approvals;
        const row = document.createElement('tr');
        row.dataset.m365ApprovalId = approval.id;
        [
            api.typeLabels[approval.request_type],
            approval.context?.workflow_id || approval.context?.conversation_id || 'Your Microsoft 365 data',
            approval.requester_name || approval.requester_id || 'Data user',
            approval.created_at ? new Date(approval.created_at).toLocaleString() : 'Not reported',
            api.describeStatus(approval)
        ].forEach(text => {
            const cell = document.createElement('td');
            cell.className = 'small text-break';
            cell.textContent = text;
            row.appendChild(cell);
        });
        const cell = document.createElement('td');
        const button = document.createElement('button');
        button.type = 'button';
        button.className = 'btn btn-sm btn-outline-primary';
        button.textContent = approval.status === 'pending' ? 'Review my data request' : 'View saved decision';
        button.addEventListener('click', async () => {
            button.disabled = true;
            try {
                await api.openApprovals({ approvals: [approval] });
                if (onUpdated) {
                    await onUpdated();
                }
            } catch (error) {
                showListError(error);
            } finally {
                button.disabled = false;
            }
        });
        cell.appendChild(button);
        row.appendChild(cell);
        return row;
    }

    window.SimpleChatM365ApprovalList = Object.freeze({ isM365Approval, renderRow });
    document.addEventListener('DOMContentLoaded', async () => {
        const id = new URLSearchParams(window.location.search).get('m365_approval');
        if (!id) {
            return;
        }
        try {
            await window.SimpleChatM365Approvals.openApprovals({ approvals: [{ id }] });
            window.ApprovalManager?.loadApprovals();
        } catch (error) {
            showListError(error);
        }
    }, { once: true });
})();
