wantedLabels => {
    const wanted = wantedLabels.map(x => String(x || "").toLowerCase().trim());
    const selectors = [
        "a",
        "button",
        "[role='button']",
        "[role='menuitem']",
        "[role='option']",
        "li",
        "span",
        "div"
    ];

    const elements = Array.from(document.querySelectorAll(selectors.join(",")));
    const out = [];
    let counter = 0;

    function visible(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);

        return (
            rect &&
            rect.width >= 5 &&
            rect.height >= 5 &&
            style.visibility !== "hidden" &&
            style.display !== "none" &&
            Number(style.opacity) !== 0
        );
    }

    function clean(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    for (const el of elements) {
        if (!visible(el)) {
            continue;
        }

        const text = clean(el.innerText);
        const aria = clean(el.getAttribute("aria-label"));
        const title = clean(el.getAttribute("title"));
        const href = clean(el.getAttribute("href"));

        const values = [text, aria, title].map(x => x.toLowerCase().trim());

        const exactHit = values.some(v => wanted.includes(v));

        if (!exactHit) {
            continue;
        }

        const clickable =
            el.closest("a, button, [role='button'], [role='menuitem'], [role='option']") ||
            el;

        clickable.setAttribute("data-bookstation-exact-menu-candidate", String(counter));

        out.push({
            index: counter,
            text: text,
            aria: aria,
            title: title,
            href: href,
            combined: [text, aria, title, href].filter(Boolean).join(" | ")
        });

        counter += 1;
    }

    return out.slice(0, 30);
}
