const subjectPicker = document.querySelector("[data-subject-picker]");
if (subjectPicker) {
    subjectPicker.querySelector("[data-subject-submit]").hidden = true;
    subjectPicker.elements.subject.addEventListener("change", () => subjectPicker.requestSubmit());
}

const editor = document.querySelector("[data-question-editor]");
if (editor) {
    const countField = editor.elements.answer_count;
    const correctField = editor.elements.correct;
    const answerFields = editor.querySelectorAll("[data-answer-field]");

    function updateAnswerFields() {
        const count = Number(countField.value);
        for (const field of answerFields) {
            const enabled = Number(field.dataset.answerField) <= count;
            field.hidden = !enabled;
            const input = field.querySelector("textarea");
            input.disabled = !enabled;
            input.required = enabled;
        }
        if (Number(correctField.value) > count) {
            correctField.value = "";
        }
        for (const option of correctField.options) {
            option.disabled = Number(option.value) > count;
            option.hidden = option.disabled;
        }
    }

    countField.addEventListener("change", updateAnswerFields);
    updateAnswerFields();
}

for (const form of document.querySelectorAll("[data-question-delete]")) {
    form.addEventListener("submit", (event) => {
        if (!window.confirm("Delete this question?")) event.preventDefault();
    });
}

const timer = document.querySelector("[data-quiz-timer]");
if (timer) {
    const deadline = Date.now() + Number(timer.dataset.quizTimer) * 1000;
    const interval = window.setInterval(updateTimer, 250);

    function updateTimer() {
        const seconds = Math.max(0, Math.ceil((deadline - Date.now()) / 1000));
        const minutes = Math.floor(seconds / 60);
        timer.textContent = `${minutes}:${String(seconds % 60).padStart(2, "0")}`;
        timer.classList.toggle("urgent", seconds <= 60);
        if (seconds === 0) {
            window.clearInterval(interval);
            document.querySelectorAll("[data-quiz-answer] button, [data-quiz-answer] input")
                .forEach((control) => control.disabled = true);
            window.location.replace(window.location.pathname);
        }
    }

    updateTimer();
    document.addEventListener("visibilitychange", updateTimer);
}
