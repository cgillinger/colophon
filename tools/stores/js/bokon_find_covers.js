() => {
    const badHrefParts = [
        "/ebocker",
        "/ljudbocker",
        "/presentkort",
        "/sok",
        "/kategori",
        "/kategorier",
        "/topplista",
        "/kampanj",
        "/forfattare",
        "/forlag",
        "/nyheter",
        "/kundservice",
        "/konto",
        "/login",
        "/logout",
        "#"
    ];

    const badTextParts = [
        "e-böcker",
        "eböcker",
        "ljudböcker",
        "presentkort",
        "kundservice",
        "logga in",
        "logga ut",
        "konto",
        "meny",
        "sök"
    ];

    const goodImageParts = [
        "bokon-cdn",
        "pubfront",
        "media/product",
        "elib",
        "product_",
        "cover"
    ];

    const result = [];
    const seen = new Set();

    const images = Array.from(document.querySelectorAll("img"));

    let counter = 0;

    for (const img of images) {
        const rect = img.getBoundingClientRect();

        if (!rect || rect.width < 65 || rect.height < 90) {
            continue;
        }

        // Bokomslag är nästan alltid högre än breda.
        if (rect.height < rect.width * 1.12) {
            continue;
        }

        const src = img.currentSrc || img.src || "";
        const alt = img.alt || "";
        const aria = img.getAttribute("aria-label") || "";
        const title = img.getAttribute("title") || "";

        const anchor = img.closest("a");
        const button = img.closest("button, [role='button']");

        const href = anchor ? (anchor.getAttribute("href") || "") : "";

        const card = img.closest("article, li, .book, .product, .library-item, .item, div") || img.parentElement;
        const cardText = card ? (card.innerText || "") : "";

        const combined = (src + " " + alt + " " + aria + " " + title + " " + href + " " + cardText).toLowerCase();

        if (combined.includes("logo") || combined.includes("sprite") || combined.includes("icon")) {
            continue;
        }

        if (combined.includes("app-store") || combined.includes("google-play")) {
            continue;
        }

        if (badHrefParts.some(part => href.toLowerCase().includes(part))) {
            continue;
        }

        if (badTextParts.some(part => combined.includes(part)) && !goodImageParts.some(part => combined.includes(part))) {
            continue;
        }

        // Kräver antingen riktig produktbildkälla eller rimlig korttext.
        const looksLikeProductImage = goodImageParts.some(part => combined.includes(part));
        const hasUsefulText = cardText.trim().length > 8 || alt.trim().length > 3;

        if (!looksLikeProductImage && !hasUsefulText) {
            continue;
        }

        const key = [
            Math.round(rect.x),
            Math.round(rect.y),
            Math.round(rect.width),
            Math.round(rect.height),
            src.slice(0, 80),
            alt.slice(0, 80)
        ].join("|");

        if (seen.has(key)) {
            continue;
        }

        seen.add(key);

        img.setAttribute("data-bookstation-bokon-cover", String(counter));

        if (anchor) {
            anchor.setAttribute("data-bookstation-bokon-cover-link", String(counter));
        }

        if (button) {
            button.setAttribute("data-bookstation-bokon-cover-button", String(counter));
        }

        let label = cardText || alt || title || href || src;
        label = label.replace(/\s+/g, " ").trim();

        result.push({
            index: counter,
            label: label,
            href: href,
            src: src,
            width: Math.round(rect.width),
            height: Math.round(rect.height)
        });

        counter += 1;
    }

    return result;
}
