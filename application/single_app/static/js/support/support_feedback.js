import { showToast } from "../chat/chat-toast.js";


document.addEventListener('DOMContentLoaded', () => {
    const feedbackForms = document.querySelectorAll('.support-send-feedback-form');
    feedbackForms.forEach(form => {
        const submitButton = form.querySelector('.support-send-feedback-submit');
        if (!submitButton) {
            return;
        }

        submitButton.addEventListener('click', event => {
            event.preventDefault();
            submitSupportFeedbackForm(form);
        });
    });
});


async function submitSupportFeedbackForm(form) {
    const feedbackType = form.dataset.feedbackType;
    const feedbackLabel = form.dataset.feedbackLabel || 'Feedback';
    const inputs = form.querySelectorAll('input[type="text"], input[type="email"], textarea');
    const nameInput = inputs[0];
    const emailInput = inputs[1];
    const organizationInput = inputs[2];
    const detailsInput = inputs[3];
    const statusAlert = form.querySelector('.support-send-feedback-status');
    const submitButton = form.querySelector('.support-send-feedback-submit');

    const reporterName = nameInput?.value.trim() || '';
    const reporterEmail = emailInput?.value.trim() || '';
    const organization = organizationInput?.value.trim() || '';
    const details = detailsInput?.value.trim() || '';

    if (!reporterName || !reporterEmail || !organization || !details) {
        setStatusAlert(statusAlert, 'Please complete name, email, organization, and details before opening the email draft.', 'danger');
        showToast('Please complete the Send Feedback form first.', 'warning');
        return;
    }

    if (!reporterEmail.includes('@')) {
        setStatusAlert(statusAlert, 'Please enter a valid email address.', 'danger');
        showToast('Please enter a valid email address.', 'warning');
        return;
    }

    submitButton.disabled = true;

    try {
        const response = await fetch('/api/support/send_feedback_email', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            credentials: 'same-origin',
            body: JSON.stringify({
                feedbackType,
                reporterName,
                reporterEmail,
                organization,
                details
            })
        });

        const result = await response.json();
        if (!response.ok) {
            throw new Error(result.error || 'Unable to prepare the feedback email draft.');
        }

        const mailtoUrl = buildSupportFeedbackMailtoUrl({
            recipientEmail: result.recipientEmail,
            subjectLine: result.subjectLine,
            feedbackLabel,
            reporterName,
            reporterEmail,
            organization,
            details
        });

        setStatusAlert(
            statusAlert,
            'Email draft prepared. Your local email client should open next.',
            'success'
        );
        showToast(`${feedbackLabel} email draft prepared.`, 'success');
        window.location.href = mailtoUrl;
    } catch (error) {
        setStatusAlert(statusAlert, error.message || 'Unable to prepare the feedback email draft.', 'danger');
        showToast(error.message || 'Unable to prepare the feedback email draft.', 'danger');
    } finally {
        submitButton.disabled = false;
    }
}


function buildSupportFeedbackMailtoUrl({
    recipientEmail,
    subjectLine,
    feedbackLabel,
    reporterName,
    reporterEmail,
    organization,
    details
}) {
    const sendFeedbackPane = document.getElementById('support-send-feedback-pane');
    const appVersion = sendFeedbackPane?.dataset.appVersion || '';
    const bodyLines = [
        `Feedback Type: ${feedbackLabel}`,
        `Name: ${reporterName}`,
        `Email: ${reporterEmail}`,
        `Organization: ${organization}`,
        `App Version: ${appVersion || 'Unknown'}`,
        ''
    ];

    bodyLines.push('Details:');
    bodyLines.push(details);

    return `mailto:${recipientEmail}?subject=${encodeURIComponent(subjectLine)}&body=${encodeURIComponent(bodyLines.join('\n'))}`;
}


function setStatusAlert(statusAlert, message, variant) {
    if (!statusAlert) {
        return;
    }

    statusAlert.className = `alert alert-${variant} support-send-feedback-status`;
    statusAlert.textContent = message;
    statusAlert.classList.remove('d-none');
}