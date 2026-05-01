import json
import re
import shutil
import subprocess
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

TIMEOUT = 18


SUPPORTED_DOMAINS = {
    "adlibris.com": "Adlibris",
    "www.adlibris.com": "Adlibris",
    "bokus.com": "Bokus",
    "www.bokus.com": "Bokus",
    "bokon.se": "Bokon",
    "www.bokon.se": "Bokon",
    "bokborsen.se": "Bokbörsen",
    "www.bokborsen.se": "Bokbörsen",
}


def clean_text(value):
    if not value:
        return ""

    value = str(value)

    if "<" in value and ">" in value:
        soup = BeautifulSoup(value, "html.parser")
        value = soup.get_text(" ", strip=True)

    value = " ".join(value.split()).strip()
    return value


def normalize_isbn(value):
    if not value:
        return ""

    return re.sub(r"[^0-9Xx]", "", str(value)).upper()


def find_isbn_in_text(value):
    value = str(value or "")

    candidates = re.findall(
        r"(?:97[89][\-\s]?)?(?:[0-9][\-\s]?){9,12}[0-9Xx]",
        value,
    )

    best = ""

    for candidate in candidates:
        isbn = normalize_isbn(candidate)

        if len(isbn) == 13:
            return isbn

        if len(isbn) == 10 and not best:
            best = isbn

    return best


def get_source_name(url):
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return ""

    hostname = hostname.lower()
    return SUPPORTED_DOMAINS.get(hostname, "")


def is_supported_url(url):
    return bool(get_source_name(url))


def looks_blocked(html):
    lower = (html or "").lower()

    blocked_markers = [
        "vercel security checkpoint",
        "security checkpoint",
        "access denied",
        "captcha",
        "robot check",
        "just a moment",
        "enable javascript and cookies",
        "cloudflare",
    ]

    return any(marker in lower for marker in blocked_markers)


def fetch_with_requests(url):
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "sv-SE,sv;q=0.9,en;q=0.7",
                "Accept-Encoding": "gzip, deflate",
                "Connection": "keep-alive",
            },
            timeout=TIMEOUT,
            allow_redirects=True,
        )

        if response.status_code != 200:
            return None, response.url, f"HTTP {response.status_code}"

        content_type = response.headers.get("Content-Type", "").lower()

        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return None, response.url, "Sidan verkar inte vara HTML."

        return response.text, response.url, ""

    except Exception as error:
        return None, url, str(error)


def fetch_with_curl(url):
    if not shutil.which("curl"):
        return None, url, "curl saknas"

    try:
        command = [
            "curl",
            "-L",
            "--compressed",
            "--max-time",
            str(TIMEOUT),
            "-A",
            BROWSER_USER_AGENT,
            "-H",
            "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "-H",
            "Accept-Language: sv-SE,sv;q=0.9,en;q=0.7",
            url,
        ]

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=TIMEOUT + 5,
        )

        if result.returncode != 0:
            return None, url, result.stderr.strip() or "curl kunde inte hämta sidan"

        html = result.stdout

        if not html:
            return None, url, "Tomt svar från sidan"

        return html, url, ""

    except Exception as error:
        return None, url, str(error)


def fetch_html(url):
    html, final_url, error = fetch_with_requests(url)

    if html and not looks_blocked(html):
        return html, final_url, ""

    html2, final_url2, error2 = fetch_with_curl(url)

    if html2 and not looks_blocked(html2):
        return html2, final_url2, ""

    if html and looks_blocked(html):
        return None, final_url, "Sidan blockerar automatisk hämtning."

    if html2 and looks_blocked(html2):
        return None, final_url2, "Sidan blockerar automatisk hämtning."

    return None, final_url2 or final_url or url, error2 or error or "Kunde inte hämta sidan."


def value_from_meta(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"property": name})

        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

        tag = soup.find("meta", attrs={"name": name})

        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

    return ""


def force_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def extract_name(value):
    if not value:
        return ""

    if isinstance(value, str):
        return clean_text(value)

    if isinstance(value, dict):
        return clean_text(value.get("name") or value.get("title") or "")

    if isinstance(value, list):
        names = []

        for row in value:
            name = extract_name(row)

            if name:
                names.append(name)

        return ", ".join(dict.fromkeys(names))

    return clean_text(value)


def extract_image(value):
    if not value:
        return ""

    if isinstance(value, str):
        return clean_text(value)

    if isinstance(value, dict):
        return clean_text(
            value.get("url")
            or value.get("contentUrl")
            or value.get("image")
            or ""
        )

    if isinstance(value, list):
        for row in value:
            image = extract_image(row)

            if image:
                return image

    return ""


def extract_isbn_from_jsonld(obj):
    candidates = [
        obj.get("isbn"),
        obj.get("ISBN"),
        obj.get("gtin13"),
        obj.get("sku"),
        obj.get("productID"),
        obj.get("identifier"),
    ]

    for candidate in candidates:
        if isinstance(candidate, dict):
            candidate = (
                candidate.get("value")
                or candidate.get("@id")
                or candidate.get("name")
            )

        if isinstance(candidate, list):
            for row in candidate:
                isbn = extract_isbn_from_jsonld({"identifier": row})

                if isbn:
                    return isbn

        isbn = normalize_isbn(candidate)

        if isbn:
            return isbn

    return ""


def parse_json_ld(soup):
    objects = []

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()

        if not raw:
            continue

        raw = raw.strip()

        try:
            data = json.loads(raw)
        except Exception:
            continue

        stack = force_list(data)

        while stack:
            item = stack.pop(0)

            if isinstance(item, list):
                stack.extend(item)
                continue

            if not isinstance(item, dict):
                continue

            objects.append(item)

            graph = item.get("@graph")

            if isinstance(graph, list):
                stack.extend(graph)

    return objects


def object_type_text(obj):
    value = obj.get("@type", "")

    if isinstance(value, list):
        return " ".join([str(row) for row in value]).lower()

    return str(value).lower()


def extract_from_json_ld(soup):
    best = {}

    for obj in parse_json_ld(soup):
        type_text = object_type_text(obj)

        if (
            "book" not in type_text
            and "product" not in type_text
            and "creativework" not in type_text
        ):
            continue

        title = clean_title(
            obj.get("name")
            or obj.get("headline")
            or obj.get("title")
            or ""
        )

        author = extract_name(
            obj.get("author")
            or obj.get("creator")
            or obj.get("contributor")
        )

        description = clean_text(
            obj.get("description")
            or obj.get("abstract")
            or ""
        )

        isbn = extract_isbn_from_jsonld(obj)
        publisher = extract_name(obj.get("publisher"))
        language = extract_name(obj.get("inLanguage") or obj.get("language"))
        cover_url = extract_image(obj.get("image") or obj.get("thumbnailUrl"))

        score = 0

        if title:
            score += 10

        if author:
            score += 5

        if description:
            score += 5

        if isbn:
            score += 5

        if cover_url:
            score += 5

        candidate = {
            "title": title,
            "author": author,
            "description": description,
            "isbn": isbn,
            "publisher": publisher,
            "language": language,
            "cover_url": cover_url,
            "_score": score,
        }

        if not best or candidate["_score"] > best.get("_score", 0):
            best = candidate

    if best:
        best.pop("_score", None)

    return best


def clean_title(title):
    title = clean_text(title)

    suffixes = [
        " | Adlibris",
        " - Adlibris",
        " | Bokus",
        " - Bokus",
        " | Bokon",
        " - Bokon",
        " | Bokbörsen",
        " - Bokbörsen",
    ]

    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()

    blocked_titles = [
        "Vercel Security Checkpoint",
        "Security Checkpoint",
        "Access Denied",
        "Just a moment",
    ]

    for blocked in blocked_titles:
        if title.lower() == blocked.lower():
            return ""

    return title


def split_clean_lines(text):
    lines = []

    for line in str(text or "").splitlines():
        line = clean_text(line)

        if line:
            lines.append(line)

    return lines


def label_from_lines(lines, labels):
    wanted = [label.lower() for label in labels]

    for index, line in enumerate(lines):
        lower = line.lower()

        for label in wanted:
            if lower.startswith(label + ":"):
                return clean_text(line.split(":", 1)[1])

            if lower == label:
                if index + 1 < len(lines):
                    return clean_text(lines[index + 1])

    return ""


def h1_text(soup):
    h1 = soup.find("h1")

    if h1:
        return clean_title(h1.get_text(" ", strip=True))

    return ""


def guess_author_from_title(raw_title):
    raw_title = clean_text(raw_title)

    parts = [clean_text(part) for part in raw_title.split(" - ") if clean_text(part)]

    if len(parts) >= 2:
        possible_author = parts[1]

        bad_words = [
            "bok",
            "pocket",
            "inbunden",
            "e-bok",
            "ljudbok",
            "adlibris",
            "bokus",
            "bokbörsen",
        ]

        if not any(word in possible_author.lower() for word in bad_words):
            return possible_author

    return ""


def find_best_image(soup, page_url, title=""):
    candidates = []

    meta_image = value_from_meta(
        soup,
        "og:image",
        "twitter:image",
        "twitter:image:src",
    )

    if meta_image:
        candidates.append(meta_image)

    title_norm = normalize_match_text(title)

    for img in soup.find_all("img"):
        src = (
            img.get("src")
            or img.get("data-src")
            or img.get("data-original")
            or img.get("data-lazy-src")
            or ""
        )

        alt = clean_text(img.get("alt", ""))

        if not src:
            continue

        score = 0

        if title_norm and title_norm in normalize_match_text(alt):
            score += 10

        lower_src = src.lower()

        if "cover" in lower_src or "product" in lower_src or "media" in lower_src:
            score += 3

        if score > 0:
            candidates.append(src)

    for candidate in candidates:
        candidate = clean_text(candidate)

        if not candidate:
            continue

        return urljoin(page_url, candidate)

    return ""


def normalize_match_text(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-zåäö0-9]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split()).strip()


def parse_page(url, html, final_url):
    source_name = get_source_name(final_url) or get_source_name(url) or "Länk"
    soup = BeautifulSoup(html, "html.parser")
    page_text = soup.get_text("\n", strip=True)
    lines = split_clean_lines(page_text)

    json_data = extract_from_json_ld(soup)

    raw_meta_title = (
        value_from_meta(soup, "og:title", "twitter:title")
        or (soup.title.get_text(" ", strip=True) if soup.title else "")
    )

    title = (
        json_data.get("title")
        or h1_text(soup)
        or clean_title(raw_meta_title)
    )

    author = (
        json_data.get("author")
        or label_from_lines(lines, ["Författare", "Av", "Author"])
        or guess_author_from_title(raw_meta_title)
    )

    description = (
        json_data.get("description")
        or value_from_meta(
            soup,
            "og:description",
            "description",
            "twitter:description",
        )
    )

    isbn = (
        json_data.get("isbn")
        or label_from_lines(lines, ["ISBN", "ISBN13", "ISBN-13"])
        or find_isbn_in_text(final_url)
        or find_isbn_in_text(page_text)
    )

    publisher = (
        json_data.get("publisher")
        or label_from_lines(lines, ["Förlag", "Publisher"])
    )

    language = (
        json_data.get("language")
        or label_from_lines(lines, ["Språk", "Language"])
    )

    cover_url = (
        json_data.get("cover_url")
        or find_best_image(soup, final_url, title)
    )

    if cover_url:
        cover_url = urljoin(final_url, cover_url)

    if "logo" in cover_url.lower() and not title:
        cover_url = ""

    title = clean_title(title)

    if not title:
        return {
            "ok": False,
            "error": "Kunde inte hitta en riktig titel på sidan.",
            "result": None,
        }

    result = {
        "source": f"Import från {source_name}-länk",
        "title": title,
        "author": clean_text(author),
        "description": clean_text(description),
        "isbn": normalize_isbn(isbn),
        "publisher": clean_text(publisher),
        "language": clean_text(language),
        "series": "",
        "series_index": "",
        "cover_url": clean_text(cover_url),
        "_source_url": final_url,
    }

    return {
        "ok": True,
        "error": "",
        "result": result,
    }


def import_metadata_from_url(url):
    url = clean_text(url)

    if not url:
        return {
            "ok": False,
            "error": "Du måste klistra in en länk.",
            "result": None,
        }

    if not url.startswith(("http://", "https://")):
        return {
            "ok": False,
            "error": "Länken måste börja med http:// eller https://",
            "result": None,
        }

    if not is_supported_url(url):
        supported = ", ".join(sorted(set(SUPPORTED_DOMAINS.values())))
        return {
            "ok": False,
            "error": f"Den här domänen stöds inte ännu. Stödda källor: {supported}.",
            "result": None,
        }

    html, final_url, error = fetch_html(url)

    if not html:
        return {
            "ok": False,
            "error": error or "Kunde inte läsa sidan.",
            "result": None,
        }

    return parse_page(url, html, final_url)


# ============================================================
# BOOKSTATION OVERRIDE:
# Import från inklistrad sidtext / HTML.
# Används när webbsidan blockerar automatisk hämtning.
# ============================================================

def title_from_url_slug(url):
    try:
        path = urlparse(url).path.strip("/")
    except Exception:
        return ""

    if not path:
        return ""

    slug = path.split("/")[-1]
    slug = re.sub(r"\.[a-zA-Z0-9]+$", "", slug)

    # Ta bort ISBN i slutet, t.ex. kvinna-saknad-9789189829619
    slug = re.sub(r"[-_]?97[89][0-9]{10}$", "", slug)
    slug = re.sub(r"[-_][0-9]+$", "", slug)

    slug = slug.replace("-", " ").replace("_", " ")
    slug = clean_text(slug)

    if not slug:
        return ""

    small_words = {
        "och", "i", "på", "av", "en", "ett", "den", "det",
        "the", "and", "of", "a", "an",
    }

    words = []

    for word in slug.split():
        if word.lower() in small_words:
            words.append(word.lower())
        else:
            words.append(word[:1].upper() + word[1:])

    return clean_text(" ".join(words))


def text_between_markers(text, start_markers, end_markers):
    lines = split_clean_lines(text)

    start_index = None

    for index, line in enumerate(lines):
        lower = line.lower()

        for marker in start_markers:
            if lower == marker.lower() or lower.startswith(marker.lower()):
                start_index = index + 1
                break

        if start_index is not None:
            break

    if start_index is None:
        return ""

    end_index = len(lines)

    for index in range(start_index, len(lines)):
        lower = lines[index].lower()

        for marker in end_markers:
            if lower == marker.lower() or lower.startswith(marker.lower()):
                end_index = index
                break

        if end_index != len(lines):
            break

    return clean_text(" ".join(lines[start_index:end_index]))


def guess_author_from_text(text):
    lines = split_clean_lines(text)

    author = label_from_lines(
        lines,
        [
            "Författare",
            "Av",
            "Author",
            "Authors",
        ],
    )

    if author:
        return author

    flat = clean_text(text)

    patterns = [
        r"Författare\s*[:\-]?\s*([A-ZÅÄÖ][A-ZÅÄÖa-zåäöÉéÜüÁáÓóÍíÈèÀàÇç'´`\- ]{2,90})",
        r"\bAv\s+([A-ZÅÄÖ][A-ZÅÄÖa-zåäöÉéÜüÁáÓóÍíÈèÀàÇç'´`\- ]{2,90})",
        r"Author\s*[:\-]?\s*([A-Z][A-Za-z'´`\- ]{2,90})",
    ]

    for pattern in patterns:
        match = re.search(pattern, flat)

        if match:
            value = clean_text(match.group(1))
            value = re.split(
                r"\s+(Pocket|Inbunden|E-bok|Ljudbok|Häftad|Kartonnage|Svenska|Engelska|ISBN|Förlag|Språk)\b",
                value,
            )[0]
            value = clean_text(value)

            if value:
                return value

    return ""


def parse_pasted_text_fallback(source_url, pasted_content):
    source_name = get_source_name(source_url) or "klistrad sida"
    text = clean_text(pasted_content)
    lines = split_clean_lines(pasted_content)

    title = (
        label_from_lines(lines, ["Titel", "Title"])
        or h1_text(BeautifulSoup(pasted_content, "html.parser"))
        or title_from_url_slug(source_url)
    )

    # Om title_from_url_slug gav konstigt resultat, försök hitta första vettiga rad.
    if not title:
        for line in lines[:40]:
            low = line.lower()

            if len(line) < 3:
                continue

            if any(bad in low for bad in ["kundvagn", "cookie", "logga in", "meny", "sök", "adlibris", "bokus"]):
                continue

            if find_isbn_in_text(line):
                continue

            title = clean_title(line)
            break

    author = guess_author_from_text(pasted_content)

    description = text_between_markers(
        pasted_content,
        [
            "Beskrivning",
            "Produktbeskrivning",
            "Bokbeskrivning",
            "Om boken",
            "Description",
        ],
        [
            "Produktinformation",
            "Detaljer",
            "Specifikationer",
            "ISBN",
            "Författare",
            "Förlag",
            "Språk",
            "Kundrecensioner",
            "Recensioner",
            "Liknande böcker",
            "Andra köpte också",
        ],
    )

    isbn = (
        label_from_lines(lines, ["ISBN", "ISBN13", "ISBN-13"])
        or find_isbn_in_text(source_url)
        or find_isbn_in_text(pasted_content)
    )

    publisher = label_from_lines(
        lines,
        [
            "Förlag",
            "Utgivare",
            "Publisher",
        ],
    )

    language = label_from_lines(
        lines,
        [
            "Språk",
            "Language",
        ],
    )

    # Försök även plocka bild från HTML om användaren klistrat in sidkälla.
    soup = BeautifulSoup(pasted_content, "html.parser")
    cover_url = find_best_image(soup, source_url or "", title)

    if cover_url and source_url:
        cover_url = urljoin(source_url, cover_url)

    title = clean_title(title)

    if not title:
        return {
            "ok": False,
            "error": "Kunde inte hitta titel i det inklistrade innehållet.",
            "result": None,
        }

    result = {
        "source": f"Import från {source_name} via inklistrad sida",
        "title": title,
        "author": clean_text(author),
        "description": clean_text(description),
        "isbn": normalize_isbn(isbn),
        "publisher": clean_text(publisher),
        "language": clean_text(language),
        "series": "",
        "series_index": "",
        "cover_url": clean_text(cover_url),
        "_source_url": source_url,
    }

    return {
        "ok": True,
        "error": "",
        "result": result,
    }


def import_metadata_from_pasted_content(source_url="", pasted_content=""):
    source_url = clean_text(source_url)
    pasted_content = str(pasted_content or "").strip()

    if not pasted_content:
        return {
            "ok": False,
            "error": "Du måste klistra in sidtext eller HTML.",
            "result": None,
        }

    # Om det är HTML försöker vi först använda vanliga parsern.
    if "<html" in pasted_content.lower() or "<body" in pasted_content.lower() or "<script" in pasted_content.lower():
        final_url = source_url or "https://bookstation.local/pasted"
        parsed = parse_page(final_url, pasted_content, final_url)

        if parsed.get("ok"):
            return parsed

    # Om det bara är kopierad synlig text använder vi text-fallback.
    return parse_pasted_text_fallback(source_url, pasted_content)


# ============================================================
# BOOKSTATION OVERRIDE:
# Import från Google Books-länk via Google Books API.
# Exempel:
# https://www.google.se/books/edition/Familjereceptet/RYeRDwAAQBAJ?hl=sv&gbpv=0
# https://books.google.com/books?id=RYeRDwAAQBAJ
# ============================================================

def is_google_books_url(url):
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
    except Exception:
        return False

    return (
        host in ["books.google.com", "www.books.google.com"]
        or host.endswith(".google.com")
        or host.endswith(".google.se")
        or host.endswith(".google.fr")
    ) and "/books" in (urlparse(url).path.lower() or "")


def extract_google_books_volume_id(url):
    try:
        parsed = urlparse(url)
    except Exception:
        return ""

    # Variant 1:
    # https://books.google.com/books?id=RYeRDwAAQBAJ
    query = parsed.query or ""

    for part in query.split("&"):
        if part.startswith("id="):
            value = part.split("=", 1)[1].strip()
            if value:
                return value

    # Variant 2:
    # https://www.google.se/books/edition/Familjereceptet/RYeRDwAAQBAJ
    parts = [part for part in parsed.path.split("/") if part]

    if "edition" in parts:
        index = parts.index("edition")

        if len(parts) > index + 2:
            return parts[index + 2].strip()

    # Fallback: sista path-delen om den ser ut som Google Books volume-id
    if parts:
        candidate = parts[-1].strip()

        if candidate and re.match(r"^[A-Za-z0-9_-]{6,}$", candidate):
            return candidate

    return ""


def pick_google_isbn(industry_identifiers):
    if not isinstance(industry_identifiers, list):
        return ""

    isbn_13 = ""
    isbn_10 = ""

    for row in industry_identifiers:
        if not isinstance(row, dict):
            continue

        ident_type = clean_text(row.get("type", ""))
        ident_value = normalize_isbn(row.get("identifier", ""))

        if ident_type == "ISBN_13" and ident_value:
            isbn_13 = ident_value

        if ident_type == "ISBN_10" and ident_value:
            isbn_10 = ident_value

    return isbn_13 or isbn_10


def google_books_image_url(image_links):
    if not isinstance(image_links, dict):
        return ""

    cover_url = (
        image_links.get("extraLarge")
        or image_links.get("large")
        or image_links.get("medium")
        or image_links.get("small")
        or image_links.get("thumbnail")
        or image_links.get("smallThumbnail")
        or ""
    )

    cover_url = clean_text(cover_url)

    if cover_url.startswith("http://"):
        cover_url = "https://" + cover_url[len("http://"):]

    return cover_url


def import_google_books_volume_from_url(url):
    from dotenv import load_dotenv
    import os

    load_dotenv()

    volume_id = extract_google_books_volume_id(url)

    if not volume_id:
        return {
            "ok": False,
            "error": "Kunde inte hitta Google Books volume-id i länken.",
            "result": None,
        }

    params = {}

    google_key = os.environ.get("BOOKSTATION_GOOGLE_BOOKS_KEY", "").strip()

    if google_key:
        params["key"] = google_key

    try:
        response = requests.get(
            f"https://www.googleapis.com/books/v1/volumes/{volume_id}",
            params=params,
            headers={
                "User-Agent": BROWSER_USER_AGENT,
            },
            timeout=TIMEOUT,
        )

        if response.status_code != 200:
            return {
                "ok": False,
                "error": f"Google Books API svarade HTTP {response.status_code}.",
                "result": None,
            }

        data = response.json()

    except Exception as error:
        return {
            "ok": False,
            "error": f"Kunde inte hämta från Google Books API: {error}",
            "result": None,
        }

    info = data.get("volumeInfo", {})

    if not isinstance(info, dict):
        return {
            "ok": False,
            "error": "Google Books API saknade volumeInfo.",
            "result": None,
        }

    title = clean_text(info.get("title", ""))

    subtitle = clean_text(info.get("subtitle", ""))

    if subtitle and subtitle.lower() not in title.lower():
        title = clean_text(f"{title}: {subtitle}")

    authors = info.get("authors", [])

    if isinstance(authors, list):
        author = ", ".join([clean_text(row) for row in authors if clean_text(row)])
    else:
        author = clean_text(authors)

    description = clean_text(info.get("description", ""))
    isbn = pick_google_isbn(info.get("industryIdentifiers", []))
    publisher = clean_text(info.get("publisher", ""))
    language = clean_text(info.get("language", ""))
    cover_url = google_books_image_url(info.get("imageLinks", {}))

    if not title:
        return {
            "ok": False,
            "error": "Google Books API gav ingen titel.",
            "result": None,
        }

    result = {
        "source": "Import från Google Books API-länk",
        "title": title,
        "author": author,
        "description": description,
        "isbn": isbn,
        "publisher": publisher,
        "language": language,
        "series": "",
        "series_index": "",
        "cover_url": cover_url,
        "_source_url": url,
    }

    return {
        "ok": True,
        "error": "",
        "result": result,
    }


def get_source_name(url):
    if is_google_books_url(url):
        return "Google Books"

    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return ""

    hostname = hostname.lower()
    return SUPPORTED_DOMAINS.get(hostname, "")


def is_supported_url(url):
    if is_google_books_url(url):
        return True

    return bool(get_source_name(url))


def import_metadata_from_url(url):
    url = clean_text(url)

    if not url:
        return {
            "ok": False,
            "error": "Du måste klistra in en länk.",
            "result": None,
        }

    if not url.startswith(("http://", "https://")):
        return {
            "ok": False,
            "error": "Länken måste börja med http:// eller https://",
            "result": None,
        }

    if is_google_books_url(url):
        return import_google_books_volume_from_url(url)

    if not is_supported_url(url):
        supported = ", ".join(sorted(set(SUPPORTED_DOMAINS.values()) | {"Google Books"}))
        return {
            "ok": False,
            "error": f"Den här domänen stöds inte ännu. Stödda källor: {supported}.",
            "result": None,
        }

    html, final_url, error = fetch_html(url)

    if not html:
        return {
            "ok": False,
            "error": error or "Kunde inte läsa sidan.",
            "result": None,
        }

    return parse_page(url, html, final_url)
