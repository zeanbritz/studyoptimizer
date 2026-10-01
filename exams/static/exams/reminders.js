(function () {
    const dialog = document.getElementById("completion-dialog");
    if (!dialog) return;

    const eventInput = dialog.querySelector('[name="event_id"]');
    const label = dialog.querySelector("[data-completion-label]");
    const noButton = dialog.querySelector("[data-completion-no]");

    document.querySelectorAll("[data-complete-event-id]").forEach((button) => {
        button.addEventListener("click", () => {
            eventInput.value = button.dataset.completeEventId;
            label.textContent = button.dataset.completeLabel;
            if (typeof dialog.showModal === "function") dialog.showModal();
            else if (window.confirm(`Mark ${label.textContent} as completed?`)) dialog.querySelector("form").submit();
        });
    });

    noButton.addEventListener("click", () => dialog.close());
}());
