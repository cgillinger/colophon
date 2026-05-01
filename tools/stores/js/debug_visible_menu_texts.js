() => {
    const selectors = [
        'a',
        'button',
        '[role="button"]',
        '[role="menuitem"]',
        '[role="option"]',
        '[aria-label]',
        'li',
        'span',
        'div'
    ];

    const elements = Array.from(document.querySelectorAll(selectors.join(',')));
    const out = [];

    for (const el of elements) {
        const rect = el.getBoundingClientRect();

        if (!rect || rect.width < 5 || rect.height < 5) {
            continue;
        }

        const style = window.getComputedStyle(el);

        if (style.visibility === 'hidden' || style.display === 'none' || Number(style.opacity) === 0) {
            continue;
        }

        const text = (el.innerText || '').replace(/\s+/g, ' ').trim();
        const aria = (el.getAttribute('aria-label') || '').replace(/\s+/g, ' ').trim();
        const title = (el.getAttribute('title') || '').replace(/\s+/g, ' ').trim();
        const href = (el.getAttribute('href') || '').replace(/\s+/g, ' ').trim();

        const combined = [text, aria, title, href].filter(Boolean).join(' | ');

        if (!combined) {
            continue;
        }

        if (combined.length > 180) {
            continue;
        }

        out.push(combined);
    }

    return Array.from(new Set(out)).slice(0, 40);
}
