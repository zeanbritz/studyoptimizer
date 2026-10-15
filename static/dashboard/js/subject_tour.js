(function () {
    "use strict";

    const tour = document.getElementById("subject-tour");
    if (!tour) return;

    const editButton = document.getElementById("subject-edit-button");
    const expandButton = document.getElementById("subject-minimize-button");
    const subjectCard = document.getElementById("subject-information");
    const next = document.getElementById("subject-tour-next");
    const done = document.getElementById("subject-tour-done");
    const title = document.getElementById("subject-tour-title");
    const copy = document.getElementById("subject-tour-copy");
    const stepLabel = document.getElementById("subject-tour-step");
    const status = document.getElementById("subject-tour-status");
    if (!editButton || !expandButton || !subjectCard) return;

    let step = 1;

    function activeTarget() { return step === 1 ? editButton : expandButton; }

    function position() {
        const rect = activeTarget().getBoundingClientRect();
        const width = tour.offsetWidth;
        const height = tour.offsetHeight;
        const left = Math.max(16, Math.min(rect.right - width, window.innerWidth - width - 16));
        let top = rect.bottom + 16;
        if (top + height > window.innerHeight - 16) top = rect.top - height - 16;
        tour.style.left = left + "px";
        tour.style.top = Math.max(16, top) + "px";
    }

    function highlight() {
        editButton.classList.toggle("subject-tour-target", step === 1);
        expandButton.classList.toggle("subject-tour-target", step === 2);
        editButton.removeAttribute("aria-describedby");
        expandButton.removeAttribute("aria-describedby");
        activeTarget().setAttribute("aria-describedby", "subject-tour-copy");
        activeTarget().scrollIntoView({ block: "center", behavior: "smooth" });
        window.requestAnimationFrame(position);
        window.setTimeout(position, 300);
    }

    next.addEventListener("click", function () {
        if (!subjectCard.classList.contains("minimized")) expandButton.click();
        step = 2;
        stepLabel.textContent = "Step 2 of 2";
        title.textContent = "Open the full subject workspace";
        copy.textContent = "Click the expand button to see textbooks, revision days and more subject tools.";
        next.hidden = true;
        done.hidden = true;
        highlight();
        expandButton.focus();
    });

    expandButton.addEventListener("click", function () {
        if (step !== 2 || subjectCard.classList.contains("minimized")) return;
        copy.textContent = "That's the full workspace. You're ready to start adding study material.";
        done.hidden = false;
        window.requestAnimationFrame(position);
        done.focus();
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
            editButton.classList.remove("subject-tour-target");
            expandButton.classList.remove("subject-tour-target");
            editButton.removeAttribute("aria-describedby");
            expandButton.removeAttribute("aria-describedby");
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
