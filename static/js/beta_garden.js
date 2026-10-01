document.addEventListener("DOMContentLoaded", () => {
    const stage = document.querySelector(".garden-stage");
    const title = document.getElementById("garden-mood-title");
    const description = document.getElementById("garden-mood-description");
    const buttons = document.querySelectorAll("[data-garden-state]");

    if (!stage || !title || !description || !buttons.length) return;

    const previews = {
        growing: {
            title: "Growing well",
            description: "A little attention each day is helping this garden flourish.",
            image: "A healthy garden with three green plants",
        },
        resting: {
            title: "A little rest",
            description: "Some leaves have fallen after a few days away. The garden can grow again when you return.",
            image: "A garden with gently drooping plants and fallen leaves",
        },
        visitors: {
            title: "Ready for care",
            description: "The plants are waiting for attention and a few tiny pests have appeared. Nothing here is permanent.",
            image: "A garden with drooping plants, fallen leaves and small pests",
        },
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            const state = button.dataset.gardenState;
            const preview = previews[state];
            if (!preview) return;

            stage.dataset.state = state;
            stage.setAttribute("aria-label", preview.image);
            title.textContent = preview.title;
            description.textContent = preview.description;
            buttons.forEach((item) => item.setAttribute("aria-pressed", String(item === button)));
        });
    });
});
