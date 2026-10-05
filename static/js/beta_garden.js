document.addEventListener("DOMContentLoaded", () => {
    const stage = document.querySelector(".garden-stage");
    const title = document.getElementById("garden-mood-title");
    const description = document.getElementById("garden-mood-description");
    const buttons = document.querySelectorAll("[data-garden-state]");

    if (!stage || !title || !description || !buttons.length) return;

    const phases = {
        growing: {
            title: "Growing well",
            description: "Your subject plants are looking healthy.",
        },
        resting: {
            title: "A little thirsty",
            description: "A few leaves have fallen, but the plants still have room to recover.",
        },
        visitors: {
            title: "Ready for care",
            description: "The plants have lost some colour and tiny garden visitors have arrived.",
        },
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            const state = button.dataset.gardenState;
            const phase = phases[state];
            if (!phase) return;

            stage.dataset.state = state;
            title.textContent = phase.title;
            description.textContent = phase.description;
            buttons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
        });
    });
});
