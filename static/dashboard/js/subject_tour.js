(function () {
    "use strict";

    const tour = document.getElementById("subject-tour");
    if (!tour) return;

    const editButton = document.getElementById("subject-edit-button");
    const expandButton = document.getElementById("subject-minimize-button");
    const app = document.querySelector(".app");
    const backdrop = document.getElementById("subject-tour-backdrop");
    const spotlight = document.getElementById("subject-tour-spotlight");
    const spotlightIcon = document.getElementById("subject-tour-spotlight-icon");
    const next = document.getElementById("subject-tour-next");
    const done = document.getElementById("subject-tour-done");
    const title = document.getElementById("subject-tour-title");
    const copy = document.getElementById("subject-tour-copy");
    const stepLabel = document.getElementById("subject-tour-step");
    const status = document.getElementById("subject-tour-status");
    if (!editButton || !expandButton || !app || !backdrop || !spotlight || !spotlightIcon) return;

    let step = 1;
    const wasInert = app.inert;
    app.inert = true;

    function activeTarget() { return step === 1 ? editButton : expandButton; }

    function position() {
        const rect = activeTarget().getBoundingClientRect();
        spotlight.style.left = rect.left + "px";
        spotlight.style.top = rect.top + "px";
        spotlight.style.width = rect.width + "px";
        spotlight.style.height = rect.height + "px";
        spotlightIcon.textContent = activeTarget().textContent.trim();
        spotlightIcon.style.fontSize = window.getComputedStyle(activeTarget()).fontSize;
        const width = tour.offsetWidth;
        const height = tour.offsetHeight;
        const left = Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16));
        let top = rect.bottom + 16;
        if (top + height > window.innerHeight - 16) top = rect.top - height - 16;
        tour.style.left = left + "px";
        tour.style.top = Math.max(16, top) + "px";
    }

    function highlight() {
        activeTarget().scrollIntoView({ block: "center", behavior: "auto" });
        window.requestAnimationFrame(position);
    }

    next.addEventListener("click", function () {
        step = 2;
        stepLabel.textContent = "Step 2 of 2";
        title.textContent = "Open the full subject workspace";
        copy.textContent = "The expand button opens textbooks, revision days and more subject tools. You can use it after this guide.";
        next.hidden = true;
        done.hidden = false;
        highlight();
        done.focus();
    });

    tour.addEventListener("keydown", function (event) {
        if (event.key !== "Tab") return;
        event.preventDefault();
        (step === 1 ? next : done).focus();
    });

    done.addEventListener("click", async function () {
        done.disabled = true;
        status.textContent = "Saving...";
        try {
            const token = document.querySelector('#subject-edit-form input[name="csrfmiddlewaretoken"]').value;
            const body = new FormData();
            body.set("action", "complete_subject_tour");
            const response = await fetch(tour.dataset.completeUrl, {
                method: "POST",
                headers: { "X-CSRFToken": token, "X-Requested-With": "XMLHttpRequest" },
                body,
            });
            if (!response.ok || !(await response.json()).success) throw new Error("Could not save tour completion");
            tour.remove();
            backdrop.remove();
            spotlight.remove();
            app.inert = wasInert;
            expandButton.focus();
        } catch (error) {
            status.textContent = "Could not finish the guide. Please try again.";
            done.disabled = false;
        }
    });

    window.addEventListener("resize", position);
    window.addEventListener("scroll", position, { passive: true });
    highlight();
    next.focus();
}());
