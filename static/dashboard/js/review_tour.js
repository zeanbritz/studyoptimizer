(function () {
    "use strict";

    const tour = document.getElementById("review-tour");
    if (!tour) return;

    const app = document.querySelector(".app");
    const backdrop = document.getElementById("review-tour-backdrop");
    const spotlight = document.getElementById("review-tour-spotlight");
    const next = document.getElementById("review-tour-next");
    const done = document.getElementById("review-tour-done");
    const title = document.getElementById("review-tour-title");
    const copy = document.getElementById("review-tour-copy");
    const stepLabel = document.getElementById("review-tour-step");
    const status = document.getElementById("review-tour-status");
    const modePreview = document.getElementById("review-tour-mode-preview");
    const csrf = document.querySelector("#review-tour-csrf input[name='csrfmiddlewaretoken']");
    const reviewTarget = (
        document.querySelector("[data-review-card]")
        || document.querySelector(".empty-state")
        || document.querySelector("main")
    );
    const modeTarget = document.querySelector(".mode-switch");

    if (!app || !backdrop || !spotlight || !next || !done || !reviewTarget || !csrf) return;

    let step = 1;
    const wasInert = app.inert;
    app.inert = true;

    function activeTarget() {
        return step === 1 ? reviewTarget : (modeTarget || reviewTarget);
    }

    function copyTargetIntoSpotlight(target) {
        const copy = target.cloneNode(true);
        copy.classList.add("review-tour-spotlight__copy");
        copy.removeAttribute("href");
        copy.setAttribute("aria-hidden", "true");
        copy.querySelectorAll("[id]").forEach(function (element) {
            element.removeAttribute("id");
        });
        copy.querySelectorAll("a, button, input, select, textarea").forEach(function (element) {
            element.setAttribute("tabindex", "-1");
            element.removeAttribute("autofocus");
        });
        spotlight.replaceChildren(copy);
        spotlight.style.background = window.getComputedStyle(target).backgroundColor;
    }

    function position() {
        const target = activeTarget();
        const rect = target.getBoundingClientRect();
        const padding = 5;
        spotlight.style.left = Math.max(4, rect.left - padding) + "px";
        spotlight.style.top = Math.max(4, rect.top - padding) + "px";
        spotlight.style.width = Math.min(window.innerWidth - 8, rect.width + (padding * 2)) + "px";
        spotlight.style.height = Math.min(window.innerHeight - 8, rect.height + (padding * 2)) + "px";
        copyTargetIntoSpotlight(target);

        if (window.innerWidth <= 640) return;
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
        title.textContent = "Switch to Test";
        if (modeTarget) {
            copy.textContent = "Use the Review and Test switch to move from reading your saved items to testing what you remember.";
        } else {
            copy.textContent = "Definitions, formulas, lists, steps and comparisons have a Review and Test switch. Notes stay reading-only.";
        }
        modePreview.hidden = false;
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
            const response = await fetch(tour.dataset.completeUrl, {
                method: "POST",
                headers: {
                    "X-CSRFToken": csrf.value,
                    "X-Requested-With": "XMLHttpRequest",
                },
            });
            if (!response.ok || !(await response.json()).success) {
                throw new Error("Could not save review guide completion");
            }
            tour.remove();
            backdrop.remove();
            spotlight.remove();
            app.inert = wasInert;
            activeTarget().focus({ preventScroll: true });
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
