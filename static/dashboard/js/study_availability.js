(function () {
    "use strict";

    const root = document.querySelector("[data-study-availability]");
    if (!root) return;

    const form = root.closest("form");
    const days = Array.from(root.querySelectorAll("[data-day]"));
    const autosave = root.dataset.autosave === "true";
    const status = root.querySelector("#autosave-status");
    const error = root.querySelector("#availability-error");
    let saveTimer;
    let changeVersion = 0;
    let savedVersion = 0;
    let saving = false;

    function dayFields(button) {
        const day = button.dataset.day;
        return {
            button,
            hours: root.querySelector("#hours-" + day),
            minutes: root.querySelector("#minutes-" + day),
            enabled: root.querySelector("#enabled-" + day),
            time: root.querySelector("#time-" + day),
        };
    }

    function syncDay(fields) {
        const selected = fields.button.classList.contains("selected");
        fields.button.setAttribute("aria-pressed", selected ? "true" : "false");
        fields.enabled.value = selected ? "1" : "0";
        fields.hours.disabled = !selected;
        fields.minutes.disabled = !selected;
        if (!selected) {
            fields.time.value = "";
            return;
        }
        if (fields.hours.value === "24" && fields.minutes.value !== "0") {
            fields.minutes.value = "0";
        }
        fields.time.value = fields.hours.value !== "" && fields.minutes.value !== ""
            ? String(fields.hours.value).padStart(2, "0") + ":" + String(fields.minutes.value).padStart(2, "0")
            : "";
    }

    function isValid(showErrors) {
        let valid = true;
        days.forEach(function (button) {
            const fields = dayFields(button);
            const selected = button.classList.contains("selected");
            const hours = Number(fields.hours.value);
            const minutes = Number(fields.minutes.value);
            const dayValid = !selected || (
                fields.hours.value !== "" && fields.minutes.value !== ""
                && (hours * 60 + minutes) > 0
                && (hours < 24 || minutes === 0)
            );
            fields.hours.classList.toggle("invalid", showErrors && !dayValid);
            fields.minutes.classList.toggle("invalid", showErrors && !dayValid);
            valid = valid && dayValid;
        });
        error.hidden = valid || !showErrors;
        return valid;
    }

    function updateTotal() {
        let total = 0;
        days.forEach(function (button) {
            const fields = dayFields(button);
            if (button.classList.contains("selected") && fields.time.value) {
                total += Number(fields.hours.value) * 60 + Number(fields.minutes.value);
            }
        });
        root.querySelector("#weekly-study-total").textContent =
            Math.floor(total / 60) + "h " + String(total % 60).padStart(2, "0") + "m / week";
    }

    function setStatus(message, state) {
        if (!status) return;
        status.textContent = message;
        status.className = "autosave-status " + state;
    }

    async function saveLatest() {
        if (!autosave || saving || !isValid(true)) return;
        saving = true;
        while (savedVersion < changeVersion) {
            const version = changeVersion;
            const data = new FormData(form);
            data.set("action", "update_availability");
            setStatus("Saving...", "saving");
            try {
                const response = await fetch(window.location.href, {
                    method: "POST",
                    headers: {
                        "X-CSRFToken": form.querySelector('[name="csrfmiddlewaretoken"]').value,
                        "X-Requested-With": "XMLHttpRequest",
                    },
                    body: data,
                });
                if (!response.ok || !(await response.json()).success) {
                    throw new Error("Availability could not be saved");
                }
                savedVersion = version;
            } catch (saveError) {
                setStatus("Could not save. Try changing a time again.", "error");
                saving = false;
                return;
            }
        }
        saving = false;
        setStatus("Saved", "saved");
        window.setTimeout(function () {
            if (savedVersion === changeVersion && status && status.textContent === "Saved") {
                status.textContent = "";
            }
        }, 1800);
    }

    function changed() {
        days.forEach(function (button) { syncDay(dayFields(button)); });
        updateTotal();
        isValid(false);
        if (autosave) {
            changeVersion += 1;
            window.clearTimeout(saveTimer);
            saveTimer = window.setTimeout(saveLatest, 450);
        }
    }

    days.forEach(function (button) {
        const fields = dayFields(button);
        button.addEventListener("click", function () {
            const selected = !button.classList.contains("selected");
            button.classList.toggle("selected", selected);
            if (selected) {
                if (fields.hours.value === "") fields.hours.value = "1";
                if (fields.minutes.value === "") fields.minutes.value = "0";
                fields.hours.focus();
            }
            changed();
        });
        fields.hours.addEventListener("change", changed);
        fields.minutes.addEventListener("change", changed);
        syncDay(fields);
    });

    form.addEventListener("submit", function (event) {
        if (autosave) {
            event.preventDefault();
            saveLatest();
        } else if (!isValid(true)) {
            event.preventDefault();
        }
    });
    updateTotal();
}());
