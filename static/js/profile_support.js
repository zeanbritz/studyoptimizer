(() => {
    const launcher = document.getElementById("profile-support-launcher");
    const panel = document.getElementById("profile-support-panel");
    const closeButton = document.getElementById("profile-support-close");
    const form = document.getElementById("profile-support-form");
    const status = document.getElementById("profile-support-status");

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
                headers: {"Accept": "application/json"}
            });
            if (response.redirected) {
                throw new Error("Please sign in again, then retry.");
            }

            const result = await response.json().catch(() => ({}));
            if (!response.ok || !result.ok) {
                throw new Error(result.error || "Could not send your request. Please try again.");
            }

            form.reset();
            status.textContent = result.message;
            status.dataset.state = "success";
        } catch (error) {
            status.textContent = error.message;
            status.dataset.state = "error";
        } finally {
            submitButton.disabled = false;
            submitButton.textContent = "Send support request";
        }
    });
})();
