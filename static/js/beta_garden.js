document.addEventListener("DOMContentLoaded", () => {
    const stage = document.querySelector(".garden-stage");
    const title = document.getElementById("garden-mood-title");
    const description = document.getElementById("garden-mood-description");
    const buttons = document.querySelectorAll("[data-garden-state]");

    if (!stage || !title || !description || !buttons.length) return;

    const previews = {
        growing: {
            title: "Growing well",
            description: "A little attention each day could help these subject pots flourish.",
        },
        resting: {
            title: "A little rest",
            description: "Some leaves have fallen after a few days away. The plants can grow again when you return.",
        },
        visitors: {
            title: "Ready for care",
            description: "The pots are waiting for attention and a few tiny pests have appeared. Nothing here is permanent.",
        },
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            const state = button.dataset.gardenState;
            const preview = previews[state];
            if (!preview) return;

            stage.dataset.state = state;
            title.textContent = preview.title;
            description.textContent = preview.description;
            buttons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
        });
    });
});
