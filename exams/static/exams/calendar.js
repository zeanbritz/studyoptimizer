(function () {
    const moveForm = document.getElementById("move-event-form");
    const eventChips = document.querySelectorAll(".day-event[data-event-id]");
    const days = document.querySelectorAll(".day[data-drop-date]");

    if (!moveForm || !eventChips.length) {
        return;
    }

    let draggingId = null;

    eventChips.forEach((chip) => {
        chip.addEventListener("dragstart", (event) => {
            draggingId = chip.dataset.eventId;
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", draggingId);
            chip.classList.add("dragging");
        });

        chip.addEventListener("dragend", () => {
            draggingId = null;
            chip.classList.remove("dragging");
            days.forEach((day) => day.classList.remove("drop-target"));
        });
    });

    days.forEach((day) => {
        day.addEventListener("dragover", (event) => {
            if (!draggingId) {
                return;
            }
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            day.classList.add("drop-target");
        });

        day.addEventListener("dragleave", (event) => {
            if (!day.contains(event.relatedTarget)) {
                day.classList.remove("drop-target");
            }
        });

        day.addEventListener("drop", (event) => {
            if (!draggingId) {
                return;
            }
            event.preventDefault();
            const eventId = event.dataTransfer.getData("text/plain") || draggingId;
            moveForm.querySelector('[name="event_id"]').value = eventId;
            moveForm.querySelector('[name="date"]').value = day.dataset.dropDate;
            moveForm.submit();
        });
    });
}());
