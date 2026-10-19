"use strict";

(() => {
    if (window.studiGardenReviewNavigation) return;
    window.studiGardenReviewNavigation = true;
    const origins = new Set(["standard", "garden", "subject"]);
    const storageKey = (path, view) => `studigarden.review-scroll:${path}:${view}`;

    // The origin is a server-validated enum. Scroll state is optional, tab-local,
    // and never used to choose a navigation destination.
    document.addEventListener("click", event => {
        const link = event.target.closest("a[href]");
        if (!link || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
        const target = new URL(link.href, location.href);
        const origin = target.searchParams.get("review_origin");
        if (target.origin !== location.origin || !origins.has(origin)) return;
        const plan = document.getElementById("today-plan");
        const view = plan ? document.querySelector('[data-plan-view][aria-selected="true"]')?.dataset.planView : "subject";
        if (origin !== view) return;
        try {
            sessionStorage.setItem(storageKey(location.pathname, view), JSON.stringify({y: window.scrollY, saved: Date.now()}));
        } catch (_) { /* The validated back link still works without storage. */ }
    }, true);

    const url = new URL(location.href);
    if (url.searchParams.get("review_return") !== "1") return;
    let saved;
    try {
        saved = JSON.parse(sessionStorage.getItem(storageKey(url.pathname, url.searchParams.get("view") || "subject")));
    } catch (_) { /* Use the Today's Plan anchor when no position is available. */ }
    const restore = () => requestAnimationFrame(() => requestAnimationFrame(() => {
        if (saved && Number.isFinite(saved.y) && saved.y >= 0 && Date.now()-saved.saved < 86400000) {
            window.scrollTo({top: saved.y, behavior: "instant"});
        }
        url.searchParams.delete("review_return");
        history.replaceState(history.state, "", url.pathname + url.search + url.hash);
    }));
    // Wait for the inline garden layout and page assets before restoring height.
    if (document.readyState === "complete") restore();
    else window.addEventListener("load", restore, {once: true});
})();
