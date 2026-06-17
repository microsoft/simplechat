// example-static.js
const staticExampleRoot = document.querySelector("[data-static-example]");

if (staticExampleRoot) {
    const counterButton = staticExampleRoot.querySelector("[data-static-counter-button]");
    const counterValue = staticExampleRoot.querySelector("[data-static-counter-value]");
    const timeButton = staticExampleRoot.querySelector("[data-static-time-button]");
    const timeValue = staticExampleRoot.querySelector("[data-static-time]");
    const statusValue = staticExampleRoot.querySelector("[data-static-status]");
    let clickCount = 0;

    if (counterButton && counterValue) {
        counterButton.addEventListener("click", () => {
            clickCount += 1;
            counterValue.textContent = String(clickCount);
            if (statusValue) {
                statusValue.textContent = "Interactive";
            }
        });
    }

    if (timeButton && timeValue) {
        timeButton.addEventListener("click", () => {
            timeValue.textContent = new Date().toLocaleTimeString();
            if (statusValue) {
                statusValue.textContent = "Updated";
            }
        });
    }
}