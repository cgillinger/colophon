() => {
    const selectors = ["button", "a", "input", "[role='button']", "[role='menuitem']", "div", "span", "td"];
    const elements = Array.from(document.querySelectorAll(selectors.join(",")));
    const out = [];

    function clean(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function visible(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);
        return rect && rect.width >= 5 && rect.height >= 5 && style.visibility !== "hidden" && style.display !== "none" && Number(style.opacity) !== 0;
    }

    for (const el of elements) {
        if (!visible(el)) {
            continue;
        }

        const text = clean(el.innerText || el.value);
        const aria = clean(el.getAttribute("aria-label"));
        const title = clean(el.getAttribute("title"));
        const href = clean(el.getAttribute("href"));
        const onclick = clean(el.getAttribute("onclick"));
        const combined = [text, aria, title, href, onclick].filter(Boolean).join(" | ");

        if (combined && combined.length < 260) {
            out.push(combined);
        }
    }

    return Array.from(new Set(out)).slice(0, 100);
}
