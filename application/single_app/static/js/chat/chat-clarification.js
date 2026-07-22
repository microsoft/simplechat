// chat-clarification.js

const MAX_OPTIONS = 6;
const QUESTION_BY_CODE = Object.freeze({
    ambiguous_reference: 'What does the referenced item mean in this request?',
    document_targets_required: 'Which documents should I use?',
    jurisdiction_required: 'Which jurisdiction applies?',
    output_format_required: 'What output format do you want?',
    source_scope_required: 'Where should I look for this information?',
    target_entity_required: 'Which person, organization, or item should I use?',
    time_range_required: 'What time range should I use?',
});

function normalizeClarification(metadata) {
    const clarification = metadata?.chat_clarification;
    if (!clarification || typeof clarification !== 'object') {
        return null;
    }
    const code = String(clarification.code || '').trim().toLowerCase();
    const question = QUESTION_BY_CODE[code];
    const status = String(clarification.status || '').trim().toLowerCase();
    if (!question || !['pending', 'resolving', 'resolved', 'expired', 'failed'].includes(status)) {
        return null;
    }
    const options = Array.isArray(clarification.options)
        ? clarification.options
            .map(value => String(value || '').trim().slice(0, 120))
            .filter((value, index, values) => value && values.indexOf(value) === index)
            .slice(0, MAX_OPTIONS)
        : [];
    const expiresAt = String(clarification.expires_at || '').trim();
    const expiresAtMilliseconds = Date.parse(expiresAt);
    return {
        code,
        question,
        status,
        options,
        expired: Number.isFinite(expiresAtMilliseconds)
            && expiresAtMilliseconds <= Date.now(),
    };
}

function createElement(tagName, className = '', text = '') {
    const element = document.createElement(tagName);
    if (className) {
        element.className = className;
    }
    if (text) {
        element.textContent = text;
    }
    return element;
}

function setBusy(card, busy) {
    card.dataset.submitting = busy ? 'true' : 'false';
    card.querySelectorAll('button').forEach(button => {
        button.disabled = busy;
    });
}

function updateStatus(statusElement, text, tone = 'muted') {
    statusElement.className = `sc-chat-clarification-status text-${tone}`;
    statusElement.textContent = text;
}

export function hydrateChatClarification(
    messageElement,
    metadata,
    { onSubmit, onFocusInput } = {},
) {
    if (!messageElement) {
        return;
    }
    messageElement.querySelector('.sc-chat-clarification-card')?.remove();
    const clarification = normalizeClarification(metadata);
    if (!clarification) {
        return;
    }
    const messageText = messageElement.querySelector('.message-text');
    if (!messageText) {
        return;
    }

    const card = createElement('section', 'sc-chat-clarification-card');
    card.dataset.testid = 'chat-clarification-card';
    const title = createElement('h3', 'sc-chat-clarification-title', 'One detail needed');
    const statusElement = createElement(
        'div',
        'sc-chat-clarification-status text-muted',
    );
    const titleId = `chat-clarification-title-${clarification.code}`;
    const statusId = `chat-clarification-status-${clarification.code}`;
    title.id = titleId;
    statusElement.id = statusId;
    statusElement.setAttribute('role', 'status');
    statusElement.setAttribute('aria-live', 'polite');
    card.setAttribute('aria-labelledby', titleId);

    const header = createElement('div', 'sc-chat-clarification-header');
    const icon = createElement('i', 'bi bi-question-circle');
    icon.setAttribute('aria-hidden', 'true');
    header.appendChild(icon);
    header.appendChild(title);
    card.appendChild(header);
    card.appendChild(createElement(
        'p',
        'sc-chat-clarification-question',
        clarification.question,
    ));

    const isPending = clarification.status === 'pending' && !clarification.expired;
    if (isPending) {
        const actions = createElement('div', 'sc-chat-clarification-actions');
        clarification.options.forEach(option => {
            const optionButton = createElement(
                'button',
                'btn btn-outline-primary sc-chat-clarification-option',
                option,
            );
            optionButton.type = 'button';
            optionButton.dataset.testid = 'chat-clarification-option';
            optionButton.setAttribute('aria-describedby', statusId);
            optionButton.addEventListener('click', () => {
                if (card.dataset.submitting === 'true') {
                    return;
                }
                setBusy(card, true);
                updateStatus(statusElement, 'Sending your answer...', 'primary');
                const submitted = typeof onSubmit === 'function'
                    ? onSubmit(option)
                    : false;
                if (submitted === false) {
                    setBusy(card, false);
                    updateStatus(
                        statusElement,
                        'Your answer could not be sent. Type it in the message box.',
                        'danger',
                    );
                }
            });
            actions.appendChild(optionButton);
        });

        const freeTextButton = createElement(
            'button',
            'btn btn-link sc-chat-clarification-free-text',
            'Answer in the message box',
        );
        freeTextButton.type = 'button';
        freeTextButton.setAttribute('aria-describedby', statusId);
        freeTextButton.addEventListener('click', () => {
            if (typeof onFocusInput === 'function') {
                onFocusInput();
            }
        });
        actions.appendChild(freeTextButton);
        card.appendChild(actions);
        updateStatus(statusElement, 'Waiting for your answer.');
    } else if (clarification.status === 'resolved') {
        card.classList.add('is-resolved');
        updateStatus(statusElement, 'Answer saved.', 'success');
    } else if (clarification.status === 'resolving') {
        card.classList.add('is-resolving');
        updateStatus(statusElement, 'Your answer is being processed.', 'primary');
    } else {
        card.classList.add('is-expired');
        updateStatus(
            statusElement,
            'This clarification has expired. Send a new message to continue.',
            'muted',
        );
    }
    card.appendChild(statusElement);
    messageText.insertAdjacentElement('afterend', card);
}
