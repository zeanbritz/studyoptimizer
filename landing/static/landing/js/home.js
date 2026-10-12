(() => {
    const tabs = Array.from(document.querySelectorAll('[data-demo-tab]'));
    const panels = Array.from(document.querySelectorAll('[data-demo-panel]'));
    const activities = Array.from(document.querySelectorAll('[data-demo-activity]'));
    const workspace = document.querySelector('.product-demo__workspace');
    let activityOpener = null;

    function selectTab(tab, moveFocus = false) {
        const selected = tab.dataset.demoTab;
        tabs[0].setAttribute('aria-controls', 'demo-panel-today');

        for (const item of tabs) {
            const active = item === tab;
            item.classList.toggle('is-active', active);
            item.setAttribute('aria-selected', String(active));
            item.tabIndex = active ? 0 : -1;
        }

        for (const panel of panels) {
            panel.hidden = panel.dataset.demoPanel !== selected;
        }
        for (const activity of activities) activity.hidden = true;

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

    function showActivity(name) {
        const activity = activities.find((item) => item.dataset.demoActivity === name);
        if (!activity) return;
        const lesson = activity.querySelector('[data-demo-lesson]');
        const quiz = activity.querySelector('[data-demo-quiz]');
        lesson.hidden = false;
        quiz.hidden = true;
        quiz.reset();
        quiz.querySelectorAll('input').forEach((input) => { input.disabled = false; });
        quiz.querySelector('.demo-quiz__result').hidden = true;
        quiz.querySelector('[data-demo-retry]').hidden = true;
        quiz.querySelector('[type="submit"]').hidden = false;
        for (const panel of panels) panel.hidden = true;
        for (const item of activities) item.hidden = item !== activity;
        tabs[0].setAttribute('aria-controls', activity.id);
        activity.querySelector('[data-demo-back]').focus();
        workspace.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
    }

    document.querySelectorAll('[data-demo-open]').forEach((button) => {
        button.addEventListener('click', () => {
            activityOpener = button;
            showActivity(button.dataset.demoOpen);
        });
    });
    document.querySelectorAll('[data-demo-back]').forEach((button) => {
        button.addEventListener('click', () => {
            selectTab(tabs[0]);
            if (activityOpener) activityOpener.focus();
        });
    });
    document.querySelectorAll('[data-demo-start]').forEach((button) => {
        button.addEventListener('click', () => {
            const activity = button.closest('[data-demo-activity]');
            activity.querySelector('[data-demo-lesson]').hidden = true;
            const quiz = activity.querySelector('[data-demo-quiz]');
            quiz.hidden = false;
            quiz.querySelector('input').focus();
        });
    });
    document.querySelectorAll('[data-demo-quiz]').forEach((quiz) => {
        quiz.addEventListener('submit', (event) => {
            event.preventDefault();
            const selected = quiz.querySelector('input:checked');
            if (!selected) return;
            const correct = selected.value === quiz.dataset.answer;
            const result = quiz.querySelector('.demo-quiz__result');
            const answer = quiz.dataset.demoQuiz === 'formula'
                ? 'The answer is π: A = π × r².'
                : 'An atom is the smallest unit of an element that retains its chemical properties.';
            result.textContent = (correct ? 'That’s right! ' : 'Not quite. ') + answer;
            result.classList.toggle('is-correct', correct);
            result.hidden = false;
            quiz.querySelector('[data-demo-retry]').hidden = false;
            quiz.querySelectorAll('input').forEach((input) => { input.disabled = true; });
            quiz.querySelector('[type="submit"]').hidden = true;
        });
        quiz.querySelector('[data-demo-retry]').addEventListener('click', () => {
            quiz.reset();
            quiz.querySelectorAll('input').forEach((input) => { input.disabled = false; });
            quiz.querySelector('.demo-quiz__result').hidden = true;
            quiz.querySelector('[data-demo-retry]').hidden = true;
            quiz.querySelector('[type="submit"]').hidden = false;
            quiz.querySelector('input').focus();
        });
    });

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
