const subjectPicker = document.querySelector("[data-subject-picker]");
if (subjectPicker) {
    subjectPicker.querySelector("[data-subject-submit]").hidden = true;
    subjectPicker.elements.subject.addEventListener("change", () => subjectPicker.requestSubmit());
}

function prepareAnswerRows(container, requireAnswers) {
    const countField = container.querySelector('[name$="answer_count"]');
    const answerRows = Array.from(container.querySelectorAll("[data-answer-field]"), (field) => ({
        field,
        input: field.querySelector("textarea"),
        correct: field.querySelector(".questions-correct-choice input"),
    }));

    function updateAnswerFields() {
        const count = Number(countField.value);
        for (const [index, { field, input, correct }] of answerRows.entries()) {
            const enabled = index < count;
            field.hidden = !enabled;
            input.disabled = !enabled;
            input.required = requireAnswers && enabled;
            correct.disabled = !enabled;
            if (!enabled) correct.checked = false;
        }
    }

    countField.addEventListener("change", updateAnswerFields);
    updateAnswerFields();

    for (const { input, correct } of answerRows) {
        input.addEventListener("dblclick", () => { correct.checked = true; });
    }
    return { countField, answerRows, updateAnswerFields };
}

for (const draft of document.querySelectorAll("[data-bulk-draft]")) {
    const fields = draft.querySelector("[data-draft-fields]");
    const removal = draft.querySelector('[name$="-DELETE"]');
    const { updateAnswerFields } = prepareAnswerRows(fields, false);
    function updateRemoval() {
        fields.hidden = removal.checked;
        for (const control of fields.querySelectorAll("input, textarea, select")) {
            control.disabled = removal.checked;
        }
        if (!removal.checked) updateAnswerFields();
    }
    removal.addEventListener("change", updateRemoval);
    updateRemoval();
}

const editor = document.querySelector("[data-question-editor]");
if (editor) {
    const { countField, answerRows, updateAnswerFields } = prepareAnswerRows(editor, true);

    const dialog = document.querySelector("[data-question-upload]");
    if (dialog && typeof dialog.showModal === "function") {
        const openButton = document.querySelector("[data-question-upload-open]");
        const uploadForm = dialog.querySelector("[data-question-upload-form]");
        const pasteField = dialog.querySelector("#question-upload-text");
        const fileField = dialog.querySelector("#question-upload-file");
        const limits = {
            source: pasteField.maxLength,
            prompt: editor.elements.prompt.maxLength,
            answer: answerRows[0].input.maxLength,
        };
        const sourceLimitError = "Use up to " + limits.source.toLocaleString() + " characters for the pasted text.";
        const error = dialog.querySelector("[data-question-upload-error]");
        const showError = (message) => {
            error.textContent = message;
            error.hidden = !message;
        };

        openButton.hidden = false;
        openButton.addEventListener("click", () => {
            showError("");
            dialog.showModal();
        });
        dialog.querySelector("[data-question-upload-cancel]")
            .addEventListener("click", () => dialog.close());
        dialog.addEventListener("close", () => { fileField.value = ""; });
        pasteField.addEventListener("input", () => {
            fileField.value = "";
            showError("");
        });

        fileField.addEventListener("change", async () => {
            const file = fileField.files[0];
            if (!file) return;
            showError("");
            if (!/\.txt$/i.test(file.name)) {
                showError("Choose a text (.txt) file with one question and its answers.");
                return;
            }
            if (file.size > limits.source * 4) {
                showError(sourceLimitError);
                return;
            }
            try {
                const text = await file.text();
                if (!dialog.open || fileField.files[0] !== file) return;
                if (text.length > limits.source) {
                    showError(sourceLimitError);
                } else {
                    pasteField.value = text;
                }
            } catch {
                if (dialog.open && fileField.files[0] === file) {
                    showError("Could not read that file. Try pasting the text instead.");
                }
            }
        });

        uploadForm.addEventListener("submit", (event) => {
            event.preventDefault();
            let draft;
            try {
                draft = parseQuestionText(pasteField.value, limits);
            } catch (failure) {
                showError(failure.message);
                return;
            }
            editor.elements.prompt.value = draft.prompt;
            countField.value = String(draft.choices.length);
            answerRows.forEach(({ input, correct }, index) => {
                input.value = draft.choices[index] || "";
                correct.checked = false;
            });
            updateAnswerFields();
            pasteField.value = "";
            dialog.close();
            answerRows[0].correct.focus();
        });
    }
}

function parseQuestionText(text, limits) {
    if (text.length > limits.source) {
        throw new Error("Use up to " + limits.source.toLocaleString() + " characters for the pasted text.");
    }
    let lines = text.split(/\r\n?|\n|\u2028|\u2029/).map((line) => line.trim()).filter(Boolean);
    if (/^question(?:\s+\d+)?\s*:?\s*$/i.test(lines[0] || "")) lines.shift();
    const footer = lines.findIndex((line, index) => index > 0
        && /^(?:(?:correct\s+)?answer(?:\s+key)?|explanation)\s*:/i.test(line));
    if (footer !== -1) lines = lines.slice(0, footer);

    const heading = lines.findIndex((line, index) => index > 0
        && /^(?:(?:possible\s+)?answers|(?:answer\s+)?(?:options|choices))\s*:?\s*$/i.test(line));
    const firstOption = heading === -1 ? 1 : heading + 1;
    const markedStart = lines.findIndex((line, index) => {
        if (index < firstOption) return false;
        const option = readOption(line);
        return option && (option.style === "bullet" || option.number === 1);
    });
    const start = markedStart === -1 ? firstOption : markedStart;
    const promptEnd = heading === -1 ? start : heading;
    const prompt = lines.slice(0, promptEnd).join("\n")
        .replace(/^(?:question(?:\s+\d+)?\s*:\s*|\d+[.)][ \t]+)/i, "").trim();
    const choices = [];

    if (markedStart === -1) {
        choices.push(...lines.slice(start));
    } else {
        const style = readOption(lines[start]).style;
        for (const line of lines.slice(start)) {
            const option = readOption(line);
            if (option && option.style === style) {
                if (style !== "bullet" && option.number !== choices.length + 1) {
                    throw new Error("Use one question and put the answer labels in order.");
                }
                choices.push(option.text);
            } else {
                const last = choices.length - 1;
                choices[last] = (choices[last] + " " + line).trim();
            }
        }
    }

    if (!prompt || choices.length < 2 || choices.length > 6 || choices.some((choice) => !choice)) {
        throw new Error("Include one question and two to six answers, each on its own line.");
    }
    if (prompt.length > limits.prompt) {
        throw new Error("The question exceeds the " + limits.prompt.toLocaleString() + "-character limit.");
    }
    const longAnswer = choices.findIndex((choice) => choice.length > limits.answer);
    if (longAnswer !== -1) {
        throw new Error("Answer " + (longAnswer + 1) + " exceeds the " + limits.answer.toLocaleString() + "-character limit.");
    }
    if (new Set(choices.map((choice) => choice.replace(/\s+/g, " ").toLowerCase())).size !== choices.length) {
        throw new Error("Each answer choice needs to be different.");
    }
    return { prompt, choices };
}

function readOption(line) {
    const bullet = /^[-*•◦▪●]\s+(.*)$/.exec(line);
    if (bullet) return { style: "bullet", text: bullet[1].trim() };

    const marked = /^(?:\(([a-z]|\d{1,2})\)|([a-z]|\d{1,2})[.):])(?:\s+(.*)|$)/i.exec(line);
    if (!marked) return null;

    const label = marked[1] || marked[2];
    const letter = /^[a-z]$/i.test(label);
    return {
        style: letter ? "letter" : "number",
        number: letter ? label.toUpperCase().charCodeAt(0) - 64 : Number(label),
        text: (marked[3] || "").trim(),
    };
}

for (const panel of document.querySelectorAll("[data-question-image-editor]")) {
    const file = panel.querySelector('input[type="file"]');
    const preview = panel.querySelector("[data-question-image-preview]");
    const description = panel.querySelector('[name$="image_description"]');
    const remove = panel.querySelector('[name$="remove_image"]');
    const original = preview.getAttribute("src");
    let localUrl = null;

    function showPreview() {
        const source = remove?.checked ? null : localUrl || original;
        if (source) preview.src = source;
        else preview.removeAttribute("src");
        preview.hidden = !source;
    }

    file.addEventListener("change", () => {
        if (localUrl) URL.revokeObjectURL(localUrl);
        localUrl = file.files[0] ? URL.createObjectURL(file.files[0]) : null;
        if (localUrl && remove) remove.checked = false;
        showPreview();
    });
    description.addEventListener("input", () => {
        preview.alt = description.value.trim() || "Question image preview";
    });
    remove?.addEventListener("change", () => {
        if (remove.checked) {
            file.value = "";
            if (localUrl) URL.revokeObjectURL(localUrl);
            localUrl = null;
        }
        showPreview();
    });
    showPreview();
}

for (const form of document.querySelectorAll("[data-question-delete]")) {
    form.addEventListener("submit", (event) => {
        if (!window.confirm("Delete this question?")) event.preventDefault();
    });
}

const multipleAnswerForm = document.querySelector("[data-multiple-answers]");
if (multipleAnswerForm) {
    const choices = Array.from(multipleAnswerForm.querySelectorAll('input[name="answer"]'));
    const checkButton = multipleAnswerForm.querySelector('button[type="submit"]');
    const updateCheckButton = () => {
        checkButton.disabled = !choices.some((choice) => choice.checked && !choice.disabled);
    };
    multipleAnswerForm.addEventListener("change", updateCheckButton);
    updateCheckButton();
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
