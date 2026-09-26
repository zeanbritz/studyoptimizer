(() => {
    const launcher = document.getElementById("beta-feedback-launcher");
    const panel = document.getElementById("beta-feedback-panel");
    const closeButton = document.getElementById("beta-feedback-close");
    const form = document.getElementById("beta-feedback-form");
    const status = document.getElementById("beta-feedback-status");

    if (!launcher || !panel || !closeButton || !form || !status) {
        return;
    }

    const submitButton = form.querySelector('button[type="submit"]');
    const firstChoice = form.querySelector('input[name="category"]');

    function closePanel() {
        panel.hidden = true;
        launcher.setAttribute("aria-expanded", "false");
        launcher.focus();
    }

    launcher.addEventListener("click", () => {
        if (!panel.hidden) {
            closePanel();
            return;
        }

        panel.hidden = false;
        launcher.setAttribute("aria-expanded", "true");
        status.textContent = "";
        status.removeAttribute("data-state");
        firstChoice.focus();
    });

    closeButton.addEventListener("click", closePanel);

    document.addEventListener("keydown", (event) => {
        if (event.key === "Escape" && !panel.hidden) {
            closePanel();
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        if (!form.reportValidity()) {
            return;
        }

        submitButton.disabled = true;
        submitButton.textContent = "Sending…";
        status.textContent = "";
        status.removeAttribute("data-state");

        try {
            const response = await fetch(form.action, {
                method: "POST",
                body: new FormData(form),
                credentials: "same-origin",
                mode: "same-origin",
                headers: { "Accept": "application/json" }
            });

            if (response.redirected) {
                throw new Error("Please sign in again, then retry.");
            }

            const result = await response.json().catch(() => ({}));

            if (!response.ok || !result.ok) {
                throw new Error(
                    result.error || "Could not send feedback. Please try again."
                );
            }

            form.reset();
            status.textContent = "Thank you — your feedback was sent.";
            status.dataset.state = "success";
        } catch (error) {
            status.textContent = error.message;
            status.dataset.state = "error";
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = "Send feedback";
        }
    });
})();