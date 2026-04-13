// latest-release.js

function setupLatestFeatureImageModal() {
    const modalElement = document.getElementById('latestFeatureImageModal');
    const modalImage = document.getElementById('latestFeatureImageModalImage');
    const modalTitle = document.getElementById('latestFeatureImageModalLabel');
    const modalCaption = document.getElementById('latestFeatureImageModalCaption');
    const imageTriggers = document.querySelectorAll('[data-latest-feature-image-src]');

    if (!modalElement || !modalImage || !modalTitle || !modalCaption || imageTriggers.length === 0) {
        return;
    }

    const imageModal = bootstrap.Modal.getOrCreateInstance(modalElement);

    imageTriggers.forEach((trigger) => {
        trigger.addEventListener('click', (event) => {
            event.preventDefault();

            const imageSrc = trigger.dataset.latestFeatureImageSrc;
            const imageTitle = trigger.dataset.latestFeatureImageTitle || 'Latest Feature Preview';
            const imageCaption = trigger.dataset.latestFeatureImageCaption || 'Click outside the popup to close it.';
            const imageAlt = trigger.querySelector('img')?.getAttribute('alt') || imageTitle;

            if (!imageSrc) {
                return;
            }

            modalImage.src = imageSrc;
            modalImage.alt = imageAlt;
            modalTitle.textContent = imageTitle;
            modalCaption.textContent = imageCaption;
            imageModal.show();
        });
    });

    modalElement.addEventListener('hidden.bs.modal', () => {
        modalImage.src = '';
        modalImage.alt = 'Latest feature preview';
    });
}

document.addEventListener('DOMContentLoaded', () => {
    setupLatestFeatureImageModal();
});