(function () {
    "use strict";

    const modal = document.getElementById("subject-setup-modal");
    const form = document.getElementById("subject-setup-form");
    if (!modal || !form) return;

    const links = Array.from(document.querySelectorAll("[data-setup-subject-index]"));
    let returnFocus = null;

    function open(link) {
        returnFocus = link;
        form.reset();
        form.action = link.href;
        modal.hidden = false;
        document.body.style.overflow = "hidden";
        document.getElementById("setup-subject-name").focus();
    }

    function close() {
        modal.hidden = true;
        document.body.style.overflow = "";
        if (returnFocus) returnFocus.focus();
    }

    links.forEach(function (link) {
        link.addEventListener("click", function (event) {
            event.preventDefault();
            open(link);
        });
    });

    modal.querySelectorAll("[data-close-subject-setup]").forEach(function (button) {
        button.addEventListener("click", close);
    });

    document.addEventListener("keydown", function (event) {
        if (!modal.hidden && event.key === "Escape") close();
    });

    const params = new URLSearchParams(window.location.search);
    const newIndex = params.get("setup");
    const newLink = links.find(function (link) {
        return link.dataset.setupSubjectIndex === newIndex;
    });
    if (newLink) {
        window.history.replaceState({}, "", window.location.pathname);
        open(newLink);
    }
}());
