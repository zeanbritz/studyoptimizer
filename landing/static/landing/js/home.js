(() => {
    const tabs = Array.from(document.querySelectorAll('[data-demo-tab]'));
    const panels = Array.from(document.querySelectorAll('[data-demo-panel]'));

    function selectTab(tab, moveFocus = false) {
        const selected = tab.dataset.demoTab;

        for (const item of tabs) {
            const active = item === tab;
            item.classList.toggle('is-active', active);
            item.setAttribute('aria-selected', String(active));
            item.tabIndex = active ? 0 : -1;
        }

        for (const panel of panels) {
            panel.hidden = panel.dataset.demoPanel !== selected;
        }

        if (moveFocus) tab.focus();
    }

    for (const [index, tab] of tabs.entries()) {
        tab.addEventListener('click', () => selectTab(tab));
        tab.addEventListener('keydown', (event) => {
            let nextIndex;
            if (event.key === 'ArrowRight' || event.key === 'ArrowDown') nextIndex = (index + 1) % tabs.length;
            else if (event.key === 'ArrowLeft' || event.key === 'ArrowUp') nextIndex = (index - 1 + tabs.length) % tabs.length;
            else if (event.key === 'Home') nextIndex = 0;
            else if (event.key === 'End') nextIndex = tabs.length - 1;
            else return;

            event.preventDefault();
            selectTab(tabs[nextIndex], true);
        });
    }

    const reducedMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (!reducedMotion && 'IntersectionObserver' in window) {
        const observer = new IntersectionObserver((entries) => {
            for (const entry of entries) {
                if (!entry.isIntersecting) continue;
                entry.target.classList.add('is-visible');
                observer.unobserve(entry.target);
            }
        }, { threshold: 0.12 });

        document.querySelectorAll('.reveal').forEach((element) => observer.observe(element));
    }
})();
