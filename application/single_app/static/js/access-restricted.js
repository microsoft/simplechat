// access-restricted.js
// Shows a suspension's restore time in the reader's own locale and time zone. The page
// already renders it in UTC, so the text only improves when this runs.

(function () {
    function formatLocalDateTime(value) {
        const parsed = new Date(value);
        if (Number.isNaN(parsed.getTime())) {
            return '';
        }
        try {
            return parsed.toLocaleString(undefined, { dateStyle: 'full', timeStyle: 'short' });
        } catch (error) {
            return parsed.toLocaleString();
        }
    }

    function localizeRestoreTimes() {
        document.querySelectorAll('time[data-local-datetime]').forEach(function (element) {
            const formatted = formatLocalDateTime(element.dataset.localDatetime || '');
            if (formatted) {
                element.textContent = formatted;
            }
        });
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', localizeRestoreTimes);
    } else {
        localizeRestoreTimes();
    }
}());
