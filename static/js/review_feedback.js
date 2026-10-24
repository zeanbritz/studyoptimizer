(function () {
    "use strict";

    // Existing pages use this flag to yield to the shared feedback player.
    window.STUDIGARDEN_SHARED_FEEDBACK = true;

    const checkButton = document.querySelector(".review-check-answer");
    if (checkButton && checkButton.form) {
        checkButton.form.addEventListener("submit", function () {
            try {
                sessionStorage.setItem("studyGardenReviewFeedbackPending", "1");
            } catch (error) {
                // Feedback remains optional when storage is unavailable.
            }
        });
    }

    const correctIndicator = document.querySelector(
        ".result.correct, .result--correct, .result-icon.correct, .feedback-box.correct"
    );
    const incorrectIndicator = document.querySelector(
        ".result.incorrect, .result--incorrect, .result-icon.incorrect, .feedback-box.incorrect"
    );
    const resultKind = correctIndicator ? "correct" : (incorrectIndicator ? "incorrect" : null);
    const indicator = correctIndicator || incorrectIndicator;

    if (!resultKind || !indicator) return;

    const feedbackTarget = (
        indicator.closest(".result-panel")
        || indicator.closest(".feedback-box")
        || indicator.closest(".result")
        || indicator
    );
    feedbackTarget.classList.add(
        resultKind === "correct" ? "review-feedback-correct" : "review-feedback-incorrect"
    );

    let pending = null;
    try {
        pending = sessionStorage.getItem("studyGardenReviewFeedbackPending");
        sessionStorage.removeItem("studyGardenReviewFeedbackPending");
    } catch (error) {
        pending = null;
    }

    const navigationEntry = window.performance
        && typeof window.performance.getEntriesByType === "function"
        ? window.performance.getEntriesByType("navigation")[0]
        : null;
    if (pending !== "1" && navigationEntry && navigationEntry.type === "reload") return;

    let feedbackPlayed = false;
    let attemptInFlight = false;

    function playFeedbackSound() {
        if (feedbackPlayed || attemptInFlight) return;

        const AudioContextClass = window.AudioContext || window.webkitAudioContext;
        if (!AudioContextClass) return;

        attemptInFlight = true;
        const audioContext = new AudioContextClass({ latencyHint: "interactive" });

        function scheduleNotes() {
            if (feedbackPlayed) {
                audioContext.close();
                return;
            }

            feedbackPlayed = true;
            attemptInFlight = false;
            const notes = resultKind === "correct"
                ? [
                    { frequency: 523.25, offset: 0, duration: 0.12 },
                    { frequency: 659.25, offset: 0.09, duration: 0.16 },
                ]
                : [
                    { frequency: 196, offset: 0, duration: 0.15 },
                    { frequency: 146.83, offset: 0.11, duration: 0.2 },
                ];
            const baseTime = audioContext.currentTime + 0.005;

            notes.forEach(function (note) {
                const oscillator = audioContext.createOscillator();
                const gain = audioContext.createGain();
                const startTime = baseTime + note.offset;
                const endTime = startTime + note.duration;

                oscillator.type = resultKind === "correct" ? "sine" : "triangle";
                oscillator.frequency.setValueAtTime(note.frequency, startTime);
                gain.gain.setValueAtTime(0.0001, startTime);
                gain.gain.exponentialRampToValueAtTime(
                    resultKind === "correct" ? 0.18 : 0.13,
                    startTime + 0.008
                );
                gain.gain.exponentialRampToValueAtTime(0.0001, endTime);
                oscillator.connect(gain);
                gain.connect(audioContext.destination);
                oscillator.start(startTime);
                oscillator.stop(endTime + 0.01);
            });

            window.setTimeout(function () {
                audioContext.close();
            }, 450);
        }

        if (audioContext.state === "suspended") {
            audioContext.resume().then(scheduleNotes).catch(function () {
                attemptInFlight = false;
                audioContext.close();
            });
        } else {
            scheduleNotes();
        }
    }

    // Run immediately instead of waiting for DOMContentLoaded. If a browser
    // blocks automatic audio, the first interaction retries without replaying.
    playFeedbackSound();
    document.addEventListener("pointerdown", playFeedbackSound, { once: true });
    document.addEventListener("keydown", playFeedbackSound, { once: true });
}());
