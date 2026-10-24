(() => {
    const openButton = document.getElementById("delete-account-open");
    const closeButton = document.getElementById("delete-account-close");
    const dialog = document.getElementById("delete-account-dialog");

    if (!openButton || !closeButton || !dialog) {
        return;
    }

    openButton.addEventListener("click", () => {
        if (typeof dialog.showModal === "function") {
            dialog.showModal();
        } else {
            dialog.setAttribute("open", "");
        }
    });

    function closeDialog() {
        if (typeof dialog.close === "function") {
            dialog.close();
        } else {
            dialog.removeAttribute("open");
        }
    }

    closeButton.addEventListener("click", closeDialog);
    dialog.addEventListener("click", (event) => {
        if (event.target === dialog) {
            closeDialog();
        }
    });
})();
