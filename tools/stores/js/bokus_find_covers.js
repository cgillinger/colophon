() => {
    const badHrefParts = [
        "logout",
        "logoff",
        "login",
        "kundservice",
        "customer",
        "help",
        "search",
        "product_search",
        "kundvagn",
        "cart",
        "wishlist",
        "recommend",
        "#"
    ];

    const badTextParts = [
        "logga ut",
        "logga in",
        "kundservice",
        "kundvagn",
        "varukorg",
        "sök",
        "sok",
        "konto",
        "meny",
        "köp",
        "kop"
    ];

    const goodParts = [
        "ebook",
        "ebookshelf",
        "e-bok",
        "ebok",
        "digital",
        "bibl",
        "cover",
        "omslag",
        "image",
        "produkt",
        "product"
    ];

    function clean(value) {
        return String(value || "").replace(/\s+/g, " ").trim();
    }

    function visible(el) {
        const rect = el.getBoundingClientRect();
        const style = window.getComputedStyle(el);

        return (
            rect &&
            rect.width >= 35 &&
            rect.height >= 45 &&
            style.visibility !== "hidden" &&
            style.display !== "none" &&
            Number(style.opacity) !== 0
        );
    }

    const result = [];
    const seen = new Set();
    let counter = 0;
    const images = Array.from(document.querySelectorAll("img"));

    for (const img of images) {
        if (!visible(img)) {
            continue;
        }

        const rect = img.getBoundingClientRect();

        if (rect.height < rect.width * 1.05) {
            continue;
        }

        const src = clean(img.currentSrc || img.src || "");
        const alt = clean(img.alt || "");
        const title = clean(img.getAttribute("title") || "");
        const aria = clean(img.getAttribute("aria-label") || "");
        const anchor = img.closest("a");
        const button = img.closest("button, [role='button']");
        const href = clean(anchor ? (anchor.getAttribute("href") || "") : "");
        const card = img.closest("table, tr, td, article, li, .book, .product, .item, div") || img.parentElement;
        const cardText = clean(card ? (card.innerText || "") : "");
        const combined = clean([src, alt, title, aria, href, cardText].join(" "));
        const lower = combined.toLowerCase();
        const hrefLower = href.toLowerCase();

        if (!combined) {
            continue;
        }

        if (lower.includes("logo") || lower.includes("sprite") || lower.includes("icon") || lower.includes("banner")) {
            continue;
        }

        if (badHrefParts.some(part => hrefLower.includes(part))) {
            continue;
        }

        const hasGoodSignal = goodParts.some(part => lower.includes(part)) || hrefLower.includes("account_bibl");
        const hasUsefulText = cardText.length >= 5 || alt.length >= 3 || title.length >= 3;

        if (!hasGoodSignal && !hasUsefulText) {
            continue;
        }

        if (badTextParts.some(part => lower.includes(part)) && !hasGoodSignal) {
            continue;
        }

        const key = [
            Math.round(rect.x),
            Math.round(rect.y),
            Math.round(rect.width),
            Math.round(rect.height),
            src.slice(0, 100),
            href.slice(0, 100),
            alt.slice(0, 80)
        ].join("|");

        if (seen.has(key)) {
            continue;
        }

        seen.add(key);
        img.setAttribute("data-bookstation-bokus-cover", String(counter));

        if (anchor) {
            anchor.setAttribute("data-bookstation-bokus-cover-link", String(counter));
        }

        if (button) {
            button.setAttribute("data-bookstation-bokus-cover-button", String(counter));
        }

        let label = cardText || alt || title || href || src;
        label = clean(label);

        if (label.length > 220) {
            label = label.slice(0, 220);
        }

        result.push({
            index: counter,
            label: label || `Bokus-omslag ${counter + 1}`,
            href: href,
            src: src,
            width: Math.round(rect.width),
            height: Math.round(rect.height)
        });

        counter += 1;
    }

    return result;
}
