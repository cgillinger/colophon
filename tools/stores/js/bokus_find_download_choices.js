() => {
    const selectors = [
        "a[href]",
        "button",
        "input[type='button']",
        "input[type='submit']",
        "[role='button']",
        "[role='menuitem']",
        "[aria-label]",
        "[title]",
        "td",
        "span",
        "div"
    ];

    const goodMarkers = [
        "ladda ner",
        "ladda ned",
        "ladda hem",
        "nedladdning",
        "nerladdning",
        "hämta",
        "hamta",
        "download",
        "epub",
        "pdf",
        "acsm",
        "e-bok",
        "ebok",
        "adobe digital editions",
        "digital editions"
    ];

    const badMarkers = [
        "avbryt",
        "cancel",
        "stäng",
        "stang",
        "close",
        "logga ut",
        "logga in",
        "kundservice",
        "villkor",
        "integritet",
        "privacy",
        "köp",
        "kop",
        "kundvagn",
        "varukorg",
        "cart",
        "ta bort",
        "radera",
        "delete",
        "remove",
        "recension",
        "review",
        "sök",
        "sok"
    ];

    function clean(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

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

    function hrefLooksDownload(href) {
        const lower = href.toLowerCase();
        return (
            lower.includes("download") ||
            lower.includes("ladda") ||
            lower.includes("hamta") ||
            lower.includes("hämta") ||
            lower.includes("epub") ||
            lower.includes("pdf") ||
            lower.includes("acsm") ||
            lower.includes("ebook") ||
            lower.includes("drm") ||
            lower.endsWith(".epub") ||
            lower.endsWith(".pdf") ||
            lower.endsWith(".acsm") ||
            lower.includes(".epub?") ||
            lower.includes(".pdf?") ||
            lower.includes(".acsm?")
        );
    }

    const elements = Array.from(document.querySelectorAll(selectors.join(",")));
    const seen = new Set();
    const result = [];
    let counter = 0;

    for (const el of elements) {
        const clickable = el.closest("a, button, [role='button'], [role='menuitem'], input[type='button'], input[type='submit']") || el;

        if (!visible(clickable)) {
            continue;
        }

        const text = clean(clickable.innerText || el.innerText || clickable.value || el.value);
        const aria = clean(clickable.getAttribute("aria-label") || el.getAttribute("aria-label"));
        const title = clean(clickable.getAttribute("title") || el.getAttribute("title"));
        const href = clean(clickable.getAttribute("href") || el.getAttribute("href"));
        const onclick = clean(clickable.getAttribute("onclick") || el.getAttribute("onclick"));
        const combined = clean([text, aria, title, href, onclick].filter(Boolean).join(" | "));
        const lower = combined.toLowerCase();

        if (!combined) {
            continue;
        }

        if (combined.length > 320 && !hrefLooksDownload(href)) {
            continue;
        }

        if (badMarkers.some(marker => lower.includes(marker)) && !hrefLooksDownload(href)) {
            continue;
        }

        let score = 0;

        for (const marker of goodMarkers) {
            if (lower.includes(marker)) {
                score += 10;
            }
        }

        if (hrefLooksDownload(href)) {
            score += 50;
        }

        if (lower.includes("acsm")) {
            score += 35;
        }

        if (lower.includes("epub")) {
            score += 30;
        }

        if (lower.includes("pdf")) {
            score += 20;
        }

        if (lower.includes("adobe digital editions") || lower.includes("digital editions")) {
            score += 25;
        }

        if (lower.includes("ladda") || lower.includes("download") || lower.includes("hämta") || lower.includes("hamta")) {
            score += 20;
        }

        if (score <= 0) {
            continue;
        }

        const key = [text, aria, title, href, onclick].join("|");

        if (seen.has(key)) {
            continue;
        }

        seen.add(key);
        clickable.setAttribute("data-bookstation-bokus-download-choice", String(counter));
        result.push({index: counter, text: combined, href: href, score: score});
        counter += 1;
    }

    result.sort((a, b) => b.score - a.score);
    return result.slice(0, 30);
}
