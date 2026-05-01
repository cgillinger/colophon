() => {
    const selectors = [
        "button",
        "a",
        "[role='button']",
        "[role='menuitem']",
        "div[role='button']",
        "span"
    ];

    const elements = Array.from(document.querySelectorAll(selectors.join(",")));
    const result = [];
    const seen = new Set();

    function clean(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function visible(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);

        return (
            rect &&
            rect.width >= 8 &&
            rect.height >= 8 &&
            style.visibility !== "hidden" &&
            style.display !== "none" &&
            Number(style.opacity) !== 0
        );
    }

    let counter = 0;

    for (const el of elements) {
        if (!visible(el)) {
            continue;
        }

        const clickable =
            el.closest("button, a, [role='button'], [role='menuitem']") || el;

        if (!visible(clickable)) {
            continue;
        }

        if (seen.has(clickable)) {
            continue;
        }

        const text = clean(clickable.innerText || el.innerText);
        const aria = clean(clickable.getAttribute("aria-label") || el.getAttribute("aria-label"));
        const title = clean(clickable.getAttribute("title") || el.getAttribute("title"));
        const combined = clean([text, aria, title].filter(Boolean).join(" | "));
        const lower = combined.toLowerCase();

        if (!combined) {
            continue;
        }

        if (combined.length > 240) {
            continue;
        }

        if (
            lower.includes("avbryt") ||
            lower.includes("cancel") ||
            lower.includes("stäng") ||
            lower.includes("close") ||
            lower.includes("läs mer") ||
            lower.includes("learn more")
        ) {
            continue;
        }

        let score = 0;
        let format = "";

        if (lower.includes("epub")) {
            score += 1000;
            format = "EPUB";
        }

        if (lower.includes("pdf")) {
            score += 800;
            format = "PDF";
        }

        if (lower.includes("acsm")) {
            score += 200;
        }

        if (lower.includes("exportera som")) {
            score += 100;
        }

        if (lower.includes("export as")) {
            score += 100;
        }

        if (lower.includes("åtkomst")) {
            score += 50;
        }

        if (lower.includes("access")) {
            score += 50;
        }

        if (!format || score <= 0) {
            continue;
        }

        clickable.setAttribute("data-bookstation-google-format-choice", String(counter));
        seen.add(clickable);

        result.push({
            index: counter,
            text: combined,
            format: format,
            score: score
        });

        counter += 1;
    }

    result.sort((a, b) => b.score - a.score);
    return result;
}
