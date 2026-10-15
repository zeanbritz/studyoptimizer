"use strict";

(function () {
    if (window.studiGardenSidebarReady) return;

    const sidebar = document.getElementById("sidebar");
    const openButton = document.querySelector(".mobile-menu-toggle");
    const closeButton = document.querySelector(".mobile-sidebar-close");
    const backdrop = document.querySelector(".mobile-sidebar-backdrop");
    if (!sidebar || !openButton || !closeButton || !backdrop) return;

    window.studiGardenSidebarReady = true;
    const mobile = window.matchMedia("(max-width: 800px)");
    let previousFocus = null;

    function closeMenu(restoreFocus) {
        sidebar.classList.remove("is-open");
        sidebar.inert = mobile.matches;
        backdrop.hidden = true;
        openButton.setAttribute("aria-expanded", "false");
        document.body.classList.remove("mobile-sidebar-open");
        if (restoreFocus && previousFocus) previousFocus.focus();
        previousFocus = null;
    }

    function openMenu() {
        if (!mobile.matches) return;
        previousFocus = document.activeElement;
        sidebar.inert = false;
        sidebar.classList.add("is-open");
        backdrop.hidden = false;
        openButton.setAttribute("aria-expanded", "true");
        document.body.classList.add("mobile-sidebar-open");
        closeButton.focus();
    }

    openButton.addEventListener("click", openMenu);
    closeButton.addEventListener("click", function () { closeMenu(true); });
    backdrop.addEventListener("click", function () { closeMenu(true); });

    document.addEventListener("keydown", function (event) {
        if (!sidebar.classList.contains("is-open")) return;
        if (event.key === "Escape") {
            event.preventDefault();
            closeMenu(true);
            return;
        }
        if (event.key !== "Tab") return;

        const focusable = Array.from(sidebar.querySelectorAll("a[href], button:not([disabled])"));
        if (!focusable.length) return;
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first.focus();
        }
    });

    function syncScreenSize() { closeMenu(false); }
    if (mobile.addEventListener) mobile.addEventListener("change", syncScreenSize);
    else mobile.addListener(syncScreenSize);
    syncScreenSize();
}());
