(function () {
    const moveForm = document.getElementById("move-event-form");
    const eventChips = document.querySelectorAll(".day-event[data-event-id]");
    const days = document.querySelectorAll(".day[data-drop-date]");
    let draggingId = null;
    let suppressClickUntil = 0;
    let touchDrag = null;

    function clearTargets() {
        days.forEach((day) => day.classList.remove("drop-target"));
    }

    function moveEvent(eventId, date) {
        if (!moveForm || !eventId || !date) return;
        moveForm.querySelector('[name="event_id"]').value = eventId;
        moveForm.querySelector('[name="date"]').value = date;
        moveForm.submit();
    }

    days.forEach((day) => {
        day.addEventListener("click", (event) => {
            if (Date.now() < suppressClickUntil || event.target.closest("a, button")) return;
            window.location.href = `?date=${day.dataset.dropDate}`;
        });

        day.addEventListener("dragover", (event) => {
            if (!draggingId) return;
            event.preventDefault();
            event.dataTransfer.dropEffect = "move";
            day.classList.add("drop-target");
        });

        day.addEventListener("dragleave", (event) => {
            if (!day.contains(event.relatedTarget)) day.classList.remove("drop-target");
        });

        day.addEventListener("drop", (event) => {
            if (!draggingId) return;
            event.preventDefault();
            suppressClickUntil = Date.now() + 500;
            clearTargets();
            moveEvent(event.dataTransfer.getData("text/plain") || draggingId, day.dataset.dropDate);
        });
    });

    eventChips.forEach((chip) => {
        chip.addEventListener("click", (event) => {
            if (Date.now() < suppressClickUntil) event.preventDefault();
        });

        chip.addEventListener("dragstart", (event) => {
            draggingId = chip.dataset.eventId;
            event.dataTransfer.effectAllowed = "move";
            event.dataTransfer.setData("text/plain", draggingId);
            chip.classList.add("dragging");
        });

        chip.addEventListener("dragend", () => {
            draggingId = null;
            suppressClickUntil = Date.now() + 500;
            chip.classList.remove("dragging");
            clearTargets();
        });

        // Native HTML drag-and-drop is not supported on many touch browsers.
        chip.addEventListener("pointerdown", (event) => {
            if (event.pointerType !== "touch") return;
            touchDrag = {
                id: chip.dataset.eventId,
                pointerId: event.pointerId,
                startX: event.clientX,
                startY: event.clientY,
                active: false,
            };
        });
    });

    document.addEventListener("pointermove", (event) => {
        if (!touchDrag || event.pointerId !== touchDrag.pointerId) return;
        if (!touchDrag.active && Math.hypot(
            event.clientX - touchDrag.startX,
            event.clientY - touchDrag.startY
        ) < 12) return;
        touchDrag.active = true;
        event.preventDefault();
        clearTargets();
        document.elementFromPoint(event.clientX, event.clientY)?.closest(".day[data-drop-date]")?.classList.add("drop-target");
    }, { passive: false });

    document.addEventListener("pointerup", (event) => {
        if (!touchDrag || event.pointerId !== touchDrag.pointerId) return;
        const target = document.elementFromPoint(event.clientX, event.clientY)?.closest(".day[data-drop-date]");
        if (touchDrag.active) {
            event.preventDefault();
            suppressClickUntil = Date.now() + 500;
            if (target) moveEvent(touchDrag.id, target.dataset.dropDate);
        }
        clearTargets();
        touchDrag = null;
    });

    document.addEventListener("pointercancel", () => {
        touchDrag = null;
        clearTargets();
    });
}());
