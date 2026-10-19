(function () {
    const dialog = document.getElementById("completion-dialog");
    if (!dialog) return;

    const eventInput = dialog.querySelector('[name="event_id"]');
    const label = dialog.querySelector("[data-completion-label]");
    const noButton = dialog.querySelector("[data-completion-no]");

    document.addEventListener("click", (event) => {
        const button = event.target.closest("[data-complete-event-id]");
        if (!button) return;
        eventInput.value = button.dataset.completeEventId;
        label.textContent = button.dataset.completeLabel;
        if (typeof dialog.showModal === "function") dialog.showModal();
        else if (window.confirm(`Mark ${label.textContent} as completed?`)) dialog.querySelector("form").submit();
    });

    noButton.addEventListener("click", () => dialog.close());
}());
