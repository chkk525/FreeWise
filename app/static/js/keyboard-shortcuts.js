(function () {
    if (window.__freewiseKeyboardShortcutsLoaded) return;
    window.__freewiseKeyboardShortcutsLoaded = true;

    const NAV_TARGETS = {
        d: '/dashboard/ui',
        l: '/library/ui',
        r: '/highlights/ui/review',
        f: '/highlights/ui/favorites',
        x: '/highlights/ui/discarded',
        m: '/highlights/ui/mastered',
        a: '/highlights/ui/ask',
        u: '/highlights/ui/duplicates',
        i: '/import/ui',
        s: '/settings/ui',
        t: '/import/api-token',
        v: '/highlights/ui/activity',
    };

    let gPrefixActive = false;
    let gTimer = null;
    let listIndex = -1;
    let listResetPending = false;

    function isTextInput(target) {
        if (!target) return false;
        const tag = target.tagName || '';
        if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return true;
        if (target.isContentEditable) return true;
        return Boolean(target.closest && target.closest('[contenteditable="true"]'));
    }

    function clickIfPresent(id) {
        const el = document.getElementById(id);
        if (!el || el.disabled) return false;
        el.click();
        return true;
    }

    function clearGPrefix() {
        gPrefixActive = false;
        if (gTimer) {
            clearTimeout(gTimer);
            gTimer = null;
        }
    }

    function focusOrOpenSearch() {
        const search = document.getElementById('global-search-input');
        if (search && search.offsetParent !== null) {
            search.focus();
            search.select();
            return;
        }
        window.location.href = '/highlights/ui/search';
    }

    function findCurrentCardIndex() {
        const cards = Array.from(document.querySelectorAll('[id^="highlight-"]'));
        if (cards.length === 0) return { cards, idx: -1 };
        const cutoff = 80;
        let idx = -1;
        for (let i = 0; i < cards.length; i += 1) {
            if (cards[i].getBoundingClientRect().top <= cutoff) idx = i;
            else break;
        }
        if (idx === -1) idx = 0;
        return { cards, idx };
    }

    function listStep(delta) {
        if (listIndex < 0 || listResetPending) {
            const current = findCurrentCardIndex();
            if (current.idx < 0) return false;
            listIndex = current.idx;
            listResetPending = false;
        }
        const cards = Array.from(document.querySelectorAll('[id^="highlight-"]'));
        if (cards.length === 0) return false;
        const next = Math.max(0, Math.min(cards.length - 1, listIndex + delta));
        listIndex = next;
        const target = cards[next];
        if (!target) return false;
        target.scrollIntoView({ behavior: 'smooth', block: 'start' });
        target.classList.add('ring-2', 'ring-primary-400');
        setTimeout(function () {
            target.classList.remove('ring-2', 'ring-primary-400');
        }, 700);
        return true;
    }

    function clickPagination(direction) {
        const selector = direction === 'next' ? '[data-pagination-next]' : '[data-pagination-prev]';
        const link = document.querySelector(selector);
        if (link && link.getAttribute('href')) {
            window.location.href = link.getAttribute('href');
            return true;
        }
        return false;
    }

    window.addEventListener('wheel', function () { listResetPending = true; }, { passive: true });
    window.addEventListener('touchmove', function () { listResetPending = true; }, { passive: true });

    document.addEventListener('keydown', function (e) {
        if (e.defaultPrevented) return;
        if (e.isComposing || e.keyCode === 229) return;
        if (isTextInput(e.target)) return;

        if ((e.metaKey || e.ctrlKey) && (e.key === 'k' || e.key === 'K')) {
            e.preventDefault();
            focusOrOpenSearch();
            return;
        }
        if (e.metaKey || e.ctrlKey || e.altKey) return;

        const help = document.getElementById('kbd-help-modal');
        const key = e.key.length === 1 ? e.key.toLowerCase() : e.key;

        if (e.key === 'Escape') {
            if (help && !help.classList.contains('hidden')) {
                help.classList.add('hidden');
                e.preventDefault();
            }
            clearGPrefix();
            return;
        }

        if (e.key === '?' || (e.shiftKey && e.key === '/')) {
            if (help) help.classList.toggle('hidden');
            e.preventDefault();
            return;
        }

        if (e.key === '/' && !gPrefixActive) {
            focusOrOpenSearch();
            e.preventDefault();
            return;
        }

        if (gPrefixActive) {
            const dest = NAV_TARGETS[key];
            clearGPrefix();
            if (dest) {
                window.location.href = dest;
                e.preventDefault();
            }
            return;
        }

        if (key === 'g') {
            gPrefixActive = true;
            gTimer = setTimeout(clearGPrefix, 1500);
            e.preventDefault();
            return;
        }

        switch (key) {
            case 'e':
            case ' ':
                if (clickIfPresent('review-done-btn')) {
                    e.preventDefault();
                    return;
                }
                break;
            case 's':
            case 'f':
                if (clickIfPresent('review-fav-btn')) {
                    e.preventDefault();
                    return;
                }
                break;
            case 'x':
            case 'd':
            case '#':
                if (clickIfPresent('review-discard-btn')) {
                    e.preventDefault();
                    return;
                }
                break;
            case 'Enter':
                if (clickIfPresent('review-edit-btn')) {
                    e.preventDefault();
                    return;
                }
                break;
        }

        if (key === 'j') {
            if (clickIfPresent('review-done-btn')) {
                e.preventDefault();
                return;
            }
            if (listStep(1)) e.preventDefault();
            return;
        }
        if (key === 'k') {
            if (listStep(-1)) e.preventDefault();
            return;
        }
        if (key === 'n') {
            if (clickPagination('next')) e.preventDefault();
            return;
        }
        if (key === 'p') {
            if (clickPagination('prev')) e.preventDefault();
            return;
        }
        if (key === 'r') {
            window.location.href = '/highlights/ui/random/go';
            e.preventDefault();
        }
    });
}());
