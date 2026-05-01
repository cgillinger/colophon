storeName => {
    const markersByStore = {
        kobo: ["ladda ner", "download"],
        google: ["exportera fil", "exportera", "export file", "export", "download", "ladda ner", "ladda ned"]
    };

    const markers = markersByStore[storeName] || ["ladda ner", "download", "exportera", "export"];
    const badMarkers = ["köp", "buy", "delete", "ta bort", "remove", "logga ut", "logout", "konto"];

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
        const combined = clean([text, aria, title, href].filter(Boolean).join(" "));
        const lower = combined.toLowerCase();

        if (!combined) {
            continue;
        }

        if (!markers.some(marker => lower.includes(marker))) {
            continue;
        }

        // För Kobo får en stor menyrad innehålla recension/arkiv,
        // men vi vill helst klicka exakt "Ladda ner".
        const exactText = text.toLowerCase();

        let score = 1;

        if (storeName === "kobo") {
            if (exactText === "ladda ner" || exactText === "download") {
                score += 20;
            } else if (lower.includes("ladda ner")) {
                score += 8;
            }
        }

        if (storeName === "google") {
            if (exactText === "exportera fil" || exactText === "export file") {
                score += 20;
            } else if (lower.includes("exportera") || lower.includes("export")) {
                score += 10;
            }
        }

        if (badMarkers.some(marker => lower.includes(marker)) && score < 10) {
            continue;
        }

        if (combined.length > 220 && score < 10) {
            continue;
        }

        const clickable =
            el.closest("a, button, [role='button'], [role='menuitem'], [role='option']") ||
            el;

        clickable.setAttribute("data-bookstation-download-candidate", String(counter));

        out.push({
            index: counter,
            text: text,
            aria: aria,
            title: title,
            href: href,
            combined: combined,
            score: score
        });

        counter += 1;
    }

    out.sort((a, b) => b.score - a.score);
    return out.slice(0, 30);
}
