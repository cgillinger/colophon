import json
import re
import shutil
import subprocess
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup


BROWSER_USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)

TIMEOUT = 18


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


def extract_first_url(value):
    value = str(value or "")
    match = re.search(r"https?://[^\s<>'\"]+", value)

    if not match:
        return ""

    url = match.group(0).strip()
    return url.rstrip(".,);]}")


def remove_urls(value):
    value = str(value or "")
    value = re.sub(r"https?://[^\s<>'\"]+", " ", value)
    return clean_text(value)


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
            return None, response.url

        content_type = response.headers.get("Content-Type", "").lower()

        if "text/html" not in content_type and "application/xhtml" not in content_type:
            return None, response.url

        return response.text, response.url

    except Exception:
        return None, url


def fetch_with_curl(url):
    if not shutil.which("curl"):
        return None, url

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
            return None, url

        html = result.stdout

        if not html or "<html" not in html.lower():
            return None, url

        return html, url

    except Exception:
        return None, url


def safe_get_html(url):
    html, final_url = fetch_with_requests(url)

    if html and looks_like_real_page(html):
        return html, final_url

    html, final_url = fetch_with_curl(url)

    if html and looks_like_real_page(html):
        return html, final_url

    return None, final_url


def looks_like_real_page(html):
    if not html:
        return False

    lower = html.lower()

    bad_markers = [
        "access denied",
        "captcha",
        "robot check",
        "just a moment",
        "enable javascript and cookies",
        "vercel security checkpoint",
        "security checkpoint",
        "there was an error while loading",
    ]

    for marker in bad_markers:
        if marker in lower:
            return False

    return "<html" in lower or "<body" in lower or "<h1" in lower


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


def value_from_meta(soup, *names):
    for name in names:
        tag = soup.find("meta", attrs={"property": name})

        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

        tag = soup.find("meta", attrs={"name": name})

        if tag and tag.get("content"):
            return clean_text(tag.get("content"))

    return ""


def remove_store_suffix(title):
    title = clean_text(title)

    suffixes = [
        " | Bokus",
        " - Bokus",
        " | Adlibris",
        " - Adlibris",
        " | Bokon",
        " - Bokon",
    ]

    for suffix in suffixes:
        if title.endswith(suffix):
            title = title[: -len(suffix)].strip()

    return title


def force_list(value):
    if value is None:
        return []

    if isinstance(value, list):
        return value

    return [value]


def parse_json_ld_scripts(soup):
    objects = []

    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        raw = script.string or script.get_text()

        if not raw:
            continue

        try:
            data = json.loads(raw.strip())
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
        return " ".join([str(v) for v in value]).lower()

    return str(value).lower()


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

        return ", ".join(names)

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
            candidate = candidate.get("value") or candidate.get("@id") or candidate.get("name")

        if isinstance(candidate, list):
            for row in candidate:
                isbn = extract_isbn_from_jsonld({"identifier": row})

                if isbn:
                    return isbn

        isbn = normalize_isbn(candidate)

        if isbn:
            return isbn

    return ""


def extract_book_from_jsonld(soup):
    json_objects = parse_json_ld_scripts(soup)

    best = {}

    for obj in json_objects:
        type_text = object_type_text(obj)

        if (
            "book" not in type_text
            and "product" not in type_text
            and "creativework" not in type_text
        ):
            continue

        title = remove_store_suffix(
            obj.get("name")
            or obj.get("headline")
            or obj.get("title")
            or ""
        )

        author = extract_name(obj.get("author") or obj.get("creator") or obj.get("contributor"))
        description = clean_text(obj.get("description") or obj.get("abstract") or "")
        image = extract_image(obj.get("image") or obj.get("thumbnailUrl"))
        isbn = extract_isbn_from_jsonld(obj)
        publisher = extract_name(obj.get("publisher"))
        language = extract_name(obj.get("inLanguage") or obj.get("language"))

        score = 0

        if title:
            score += 10

        if author:
            score += 5

        if description:
            score += 5

        if image:
            score += 5

        if isbn:
            score += 5

        candidate = {
            "title": title,
            "author": author,
            "description": description,
            "isbn": isbn,
            "publisher": publisher,
            "language": language,
            "cover_url": image,
            "_score": score,
        }

        if not best or candidate["_score"] > best.get("_score", 0):
            best = candidate

    if best:
        best.pop("_score", None)

    return best


def split_clean_lines(text):
    lines = []

    for line in str(text or "").splitlines():
        line = clean_text(line)

        if line:
            lines.append(line)

    return lines


def extract_heading_text(soup):
    h1 = soup.find("h1")

    if h1:
        return remove_store_suffix(h1.get_text(" ", strip=True))

    return ""


def find_line_after(lines, marker):
    marker_lower = marker.lower()

    for index, line in enumerate(lines):
        if line.lower() == marker_lower:
            for next_line in lines[index + 1:]:
                if next_line:
                    return next_line

    return ""


def text_between_line_markers(lines, start_marker, end_markers):
    start_index = None

    for index, line in enumerate(lines):
        if line.lower() == start_marker.lower():
            start_index = index + 1
            break

    if start_index is None:
        return ""

    end_index = len(lines)

    for index in range(start_index, len(lines)):
        line_lower = lines[index].lower()

        for marker in end_markers:
            if line_lower == marker.lower() or line_lower.startswith(marker.lower()):
                end_index = index
                break

        if end_index != len(lines):
            break

    return clean_text(" ".join(lines[start_index:end_index]))


def extract_value_after_label_from_lines(lines, label):
    label_lower = label.lower()

    for index, line in enumerate(lines):
        lower_line = line.lower()

        if lower_line.startswith(label_lower + ":"):
            return clean_text(line.split(":", 1)[1])

        if lower_line == label_lower:
            if index + 1 < len(lines):
                return clean_text(lines[index + 1])

    return ""


def normalize_text_for_image(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-zåäö0-9]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split())


def find_best_image_from_page(soup, page_url, title=""):
    candidates = []

    meta_image = value_from_meta(soup, "og:image", "twitter:image", "twitter:image:src")

    if meta_image:
        candidates.append(meta_image)

    title_norm = normalize_text_for_image(title)

    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-original") or ""
        alt = clean_text(img.get("alt", ""))

        if not src:
            continue

        score = 0

        if title_norm and title_norm in normalize_text_for_image(alt):
            score += 10

        if "bokus" in src.lower():
            score += 2

        if "image" in src.lower() or "images" in src.lower():
            score += 2

        if score > 0:
            candidates.append(src)

    for candidate in candidates:
        candidate = clean_text(candidate)

        if not candidate:
            continue

        return urljoin(page_url, candidate)

    return ""


def guess_author_from_page(soup, page_text):
    lines = split_clean_lines(page_text)

    author_after_av = find_line_after(lines, "Av")

    if author_after_av:
        return author_after_av

    text = clean_text(page_text)

    match = re.search(
        r"\bAv\s+([A-ZÅÄÖa-zåäöÉéÜüÁáÓóÍíÈèÀàÇç'´`\- ]{3,90})",
        text,
    )

    if match:
        author = clean_text(match.group(1))
        author = re.split(
            r"\s+(Pocket|Inbunden|E-bok|Ljudbok|Häftad|Kartonnage|Svenska|Engelska|Danska|Norska)\b",
            author,
        )[0]
        author = clean_text(author)

        if author:
            return author

    rel_author = soup.find("a", attrs={"rel": "author"})

    if rel_author:
        return clean_text(rel_author.get_text(" ", strip=True))

    return ""


def guess_publisher_from_page(page_text):
    lines = split_clean_lines(page_text)
    value = extract_value_after_label_from_lines(lines, "Förlag")

    if value:
        return value

    return ""


def guess_language_from_page(page_text):
    lines = split_clean_lines(page_text)
    value = extract_value_after_label_from_lines(lines, "Språk")

    if value:
        return value

    for line in lines:
        if "," in line and ("Svenska" in line or "Engelska" in line):
            parts = [clean_text(part) for part in line.split(",")]

            for part in parts:
                if part.lower() in ["svenska", "engelska", "norska", "danska", "finska"]:
                    return part

    return ""


def extract_book_from_html(html, page_url):
    soup = BeautifulSoup(html, "html.parser")
    jsonld = extract_book_from_jsonld(soup)

    title = jsonld.get("title", "")
    author = jsonld.get("author", "")
    description = jsonld.get("description", "")
    isbn = jsonld.get("isbn", "")
    publisher = jsonld.get("publisher", "")
    language = jsonld.get("language", "")
    cover_url = jsonld.get("cover_url", "")

    page_text = soup.get_text("\n", strip=True)
    lines = split_clean_lines(page_text)

    if not title:
        title = remove_store_suffix(
            value_from_meta(soup, "og:title", "twitter:title")
            or extract_heading_text(soup)
            or (soup.title.get_text(" ", strip=True) if soup.title else "")
        )

    if not description:
        description = clean_text(
            value_from_meta(soup, "og:description", "description", "twitter:description")
        )

    if not cover_url:
        cover_url = clean_text(
            value_from_meta(soup, "og:image", "twitter:image", "twitter:image:src")
        )

    if not cover_url:
        cover_url = find_best_image_from_page(soup, page_url, title)

    if cover_url:
        cover_url = urljoin(page_url, cover_url)

    if not isbn:
        isbn_from_label = extract_value_after_label_from_lines(lines, "ISBN")
        isbn = normalize_isbn(isbn_from_label) or find_isbn_in_text(page_text)

    if not author:
        author = guess_author_from_page(soup, page_text)

    if not publisher:
        publisher = guess_publisher_from_page(page_text)

    if not language:
        language = guess_language_from_page(page_text)

    return {
        "title": title,
        "author": author,
        "description": description,
        "isbn": isbn,
        "publisher": publisher,
        "language": language,
        "cover_url": cover_url,
    }


def extract_bokus_specific_fields(soup, page_url, data):
    page_text = soup.get_text("\n", strip=True)
    lines = split_clean_lines(page_text)

    title = extract_heading_text(soup)

    if title:
        data["title"] = title

    author = guess_author_from_page(soup, page_text)

    if author:
        data["author"] = author

    description = text_between_line_markers(
        lines,
        "Beskrivning",
        [
            "Produktinformation",
            "Utforska kategorier",
            "Betyg & recensioner",
            "Mer från samma författare",
        ],
    )

    if description:
        data["description"] = description

    publisher = extract_value_after_label_from_lines(lines, "Förlag")

    if publisher:
        data["publisher"] = publisher

    language = extract_value_after_label_from_lines(lines, "Språk")

    if language:
        data["language"] = language

    isbn = extract_value_after_label_from_lines(lines, "ISBN")

    if isbn:
        data["isbn"] = normalize_isbn(isbn)

    if not data.get("isbn"):
        data["isbn"] = find_isbn_in_text(page_text)

    if not data.get("cover_url"):
        data["cover_url"] = find_best_image_from_page(
            soup=soup,
            page_url=page_url,
            title=data.get("title", ""),
        )

    return data


def make_result(source, data, page_url):
    title = clean_text(data.get("title", ""))

    blocked_titles = {
        "",
        "| bokon",
        "bokon",
        "barnböcker",
        "barnbocker",
        "biografier & memoarer",
        "deckare",
        "fackböcker",
        "fackbocker",
        "skönlitteratur",
        "skonlitteratur",
        "romantik",
        "fantasy",
        "topplistan",
        "vercel security checkpoint",
        "security checkpoint",
        "access denied",
        "just a moment",
    }

    if title.lower() in blocked_titles:
        return None

    cover_url = clean_text(data.get("cover_url", ""))

    # Butikslogotyp är inte bokomslag.
    if "logo_facebook.png" in cover_url.lower() or "/logo/" in cover_url.lower():
        cover_url = ""

    return {
        "source": source,
        "title": title,
        "author": clean_text(data.get("author", "")),
        "description": clean_text(data.get("description", "")),
        "isbn": normalize_isbn(data.get("isbn", "")),
        "publisher": clean_text(data.get("publisher", "")),
        "language": clean_text(data.get("language", "")),
        "series": "",
        "series_index": "",
        "cover_url": cover_url,
        "_source_url": page_url,
    }


def is_supported_store_url(url):
    try:
        host = urlparse(url).hostname or ""
    except Exception:
        return False

    host = host.lower()

    return (
        host == "bokus.com"
        or host.endswith(".bokus.com")
        or host == "adlibris.com"
        or host.endswith(".adlibris.com")
        or host == "bokon.se"
        or host.endswith(".bokon.se")
    )


def valid_domain(url, domains):
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return False

    hostname = hostname.lower()

    for domain in domains:
        if hostname == domain or hostname.endswith("." + domain):
            return True

    return False


def clean_link(url):
    parsed = urlparse(url)

    if not parsed.scheme.startswith("http"):
        return ""

    return parsed._replace(fragment="").geturl()


def is_bokus_book_page(url):
    return "/bok/" in urlparse(url).path.lower()


def is_adlibris_book_page(url):
    path = urlparse(url).path.lower()
    return "/bok/" in path or "/book/" in path


def is_bokon_book_page(url):
    path = urlparse(url).path.lower().strip("/")

    if not path:
        return False

    parts = [part for part in path.split("/") if part]

    if len(parts) < 2:
        return False

    blocked_first_parts = {
        "forfattare",
        "kategori",
        "topplistan",
        "kampanj",
        "sok",
        "kundservice",
        "om-bokon",
        "varukorg",
        "konto",
        "login",
        "registrera",
    }

    if parts[0] in blocked_first_parts:
        return False

    # Stoppa rena kategori/list-sidor.
    generic_slugs = {
        "barnbocker",
        "barnböcker",
        "biografier-memoarer",
        "biografier",
        "memoarer",
        "deckare",
        "fackbocker",
        "fackböcker",
        "skonlitteratur",
        "skönlitteratur",
        "romantik",
        "fantasy",
        "thriller",
        "feelgood",
        "historia",
        "halsa",
        "hälsa",
        "mat-dryck",
        "resor",
        "barn-ungdom",
        "alla",
        "nyheter",
        "topplistan",
    }

    if parts[-1] in generic_slugs:
        return False

    # Bokon-produkter brukar vara t.ex:
    # /ebocker/other/kvinna-saknad_mary-kubica-2/
    # Därför kräver vi minst 3 delar för /ebocker/ och /ljudbocker/.
    if parts[0] in {"ebocker", "ljudbocker"}:
        if len(parts) < 3:
            return False

        slug = parts[-1]

        if "-" in slug or "_" in slug:
            return True

        return False

    # Äldre möjliga produktsidor.
    if parts[0] in {"ebok", "ljudbok", "bok"}:
        return len(parts) >= 2

    return False


def collect_links_from_search_page(html, base_url, domains, page_filter, max_links=8):
    soup = BeautifulSoup(html, "html.parser")
    links = []

    for link in soup.find_all("a", href=True):
        href = link.get("href", "").strip()

        if not href:
            continue

        full_url = clean_link(urljoin(base_url, href))

        if not full_url:
            continue

        if not valid_domain(full_url, domains):
            continue

        if not page_filter(full_url):
            continue

        if full_url in links:
            continue

        links.append(full_url)

        if len(links) >= max_links:
            break

    return links


def parse_direct_store_page(source_name, page_url):
    html, final_url = safe_get_html(page_url)

    if not html:
        return []

    data = extract_book_from_html(html, final_url)
    soup = BeautifulSoup(html, "html.parser")

    if "bokus" in source_name.lower():
        data = extract_bokus_specific_fields(soup, final_url, data)

    result = make_result(source_name, data, final_url)

    if not result:
        return []

    return [result]


def search_web_source(source_name, search_urls, domains, page_filter, max_pages=5):
    results = []
    candidate_links = []

    for search_url in search_urls:
        html, final_url = safe_get_html(search_url)

        if not html:
            continue

        links = collect_links_from_search_page(
            html=html,
            base_url=final_url,
            domains=domains,
            page_filter=page_filter,
            max_links=8,
        )

        for link in links:
            if link not in candidate_links:
                candidate_links.append(link)

        if len(candidate_links) >= max_pages:
            break

    for page_url in candidate_links[:max_pages]:
        results.extend(parse_direct_store_page(source_name, page_url))

    return results


def build_query(query_text, title="", author="", isbn=""):
    url = extract_first_url(query_text)

    if url:
        return {
            "url": url,
            "isbn": normalize_isbn(url) or normalize_isbn(query_text),
            "query": remove_urls(query_text),
        }

    isbn_value = normalize_isbn(isbn) or normalize_isbn(query_text)

    query = remove_urls(query_text) or " ".join(
        [part for part in [title, author] if part]
    ).strip()

    return {
        "url": "",
        "isbn": isbn_value,
        "query": query,
    }


def bokus_search(query_text, title="", author="", isbn=""):
    query_data = build_query(query_text, title, author, isbn)

    if query_data["url"] and is_supported_store_url(query_data["url"]):
        if "bokus." in query_data["url"]:
            results = parse_direct_store_page("Bokus (webbkälla)", query_data["url"])

            if results:
                return deduplicate_results(results)

    isbn_value = query_data["isbn"]
    query = isbn_value or query_data["query"]

    if not query:
        return []

    encoded = quote_plus(query)

    if isbn_value:
        direct_url = f"https://www.bokus.com/bok/{isbn_value}/"
        results = parse_direct_store_page("Bokus (webbkälla)", direct_url)

        if results:
            return deduplicate_results(results)

    search_urls = [
        f"https://www.bokus.com/cgi-bin/product_search.cgi?search_word={encoded}",
        f"https://www.bokus.com/cgi-bin/product_search.cgi?ac_used=no&search_word={encoded}",
    ]

    return deduplicate_results(
        search_web_source(
            source_name="Bokus (webbkälla)",
            search_urls=search_urls,
            domains=["bokus.com", "www.bokus.com"],
            page_filter=is_bokus_book_page,
            max_pages=5,
        )
    )


def adlibris_search(query_text, title="", author="", isbn=""):
    query_data = build_query(query_text, title, author, isbn)

    if query_data["url"] and is_supported_store_url(query_data["url"]):
        if "adlibris." in query_data["url"]:
            results = parse_direct_store_page("Adlibris (webbkälla)", query_data["url"])

            if results:
                return deduplicate_results(results)

    query = query_data["isbn"] or query_data["query"]

    if not query:
        return []

    encoded = quote_plus(query)

    search_urls = [
        f"https://www.adlibris.com/se/sok?q={encoded}",
        f"https://www.adlibris.com/sv/sok?q={encoded}",
        f"https://www.adlibris.com/sv/searchresult.aspx?search={encoded}",
    ]

    return deduplicate_results(
        search_web_source(
            source_name="Adlibris (webbkälla)",
            search_urls=search_urls,
            domains=["adlibris.com", "www.adlibris.com"],
            page_filter=is_adlibris_book_page,
            max_pages=5,
        )
    )


def deduplicate_results(results):
    unique = []
    seen = set()

    for result in results:
        key = (
            result.get("source", "").lower(),
            result.get("title", "").lower(),
            result.get("author", "").lower(),
            result.get("isbn", "").lower(),
            result.get("cover_url", "").lower(),
        )

        if key in seen:
            continue

        seen.add(key)
        unique.append(result)

    return unique


def _colophon_clean_bokon_title_and_author(result):
    title = clean_text(result.get("title", ""))
    author = clean_text(result.get("author", ""))

    match = re.match(
        r"^(.*?)\s+\((e-bok|ljudbok)\)\s+av\s+(.+)$",
        title,
        flags=re.IGNORECASE,
    )

    if match:
        title = clean_text(match.group(1))
        author = author or clean_text(match.group(3))

    title = re.sub(
        r"\s+\((e-bok|ljudbok)\)\s*$",
        "",
        title,
        flags=re.IGNORECASE,
    )

    result["title"] = clean_text(title)
    result["author"] = clean_text(author)

    return result


def _colophon_normalize_match_text(value):
    value = clean_text(value).lower()
    value = re.sub(r"[^a-zåäö0-9]+", " ", value, flags=re.IGNORECASE)
    return " ".join(value.split()).strip()


def _colophon_word_overlap_score(query, candidate):
    query = _colophon_normalize_match_text(query)
    candidate = _colophon_normalize_match_text(candidate)

    if not query or not candidate:
        return 0.0

    stop_words = {
        "och", "att", "det", "den", "en", "ett", "av", "i", "på",
        "the", "and", "of", "a", "an",
        "ebook", "ebok", "e", "bok", "ljudbok",
        "mary",  # förnamn får inte ensam ge träff
    }

    query_words = {
        word for word in query.split()
        if word not in stop_words and len(word) >= 2
    }

    candidate_words = {
        word for word in candidate.split()
        if word not in stop_words and len(word) >= 2
    }

    if not query_words:
        return 0.0

    hits = query_words.intersection(candidate_words)

    return len(hits) / len(query_words)


def _colophon_result_matches_query(result, query_text="", title="", author="", isbn=""):
    wanted_isbn = normalize_isbn(isbn) or normalize_isbn(query_text)
    found_isbn = normalize_isbn(result.get("isbn", ""))

    if wanted_isbn:
        return bool(found_isbn and found_isbn == wanted_isbn)

    query_without_urls = remove_urls(query_text)

    query = query_without_urls or " ".join(
        [part for part in [title, author] if part]
    ).strip()

    candidate = " ".join(
        [
            result.get("title", ""),
            result.get("author", ""),
            result.get("_source_url", ""),
        ]
    )

    score = _colophon_word_overlap_score(query, candidate)

    return score >= 0.50


def _colophon_filter_bokon_results(results, query_text="", title="", author="", isbn=""):
    filtered = []

    for result in results:
        result = _colophon_clean_bokon_title_and_author(result)

        if _colophon_result_matches_query(
            result=result,
            query_text=query_text,
            title=title,
            author=author,
            isbn=isbn,
        ):
            filtered.append(result)

    return deduplicate_results(filtered)


def bokon_search(query_text="", title="", author="", isbn=""):
    query_data = build_query(query_text, title, author, isbn)

    if query_data["url"] and is_supported_store_url(query_data["url"]):
        if "bokon." in query_data["url"]:
            raw_results = parse_direct_store_page("Bokon (webbkälla)", query_data["url"])

            return _colophon_filter_bokon_results(
                results=raw_results,
                query_text=query_text,
                title=title,
                author=author,
                isbn=isbn,
            )

    query = query_data["isbn"] or query_data["query"]

    if not query:
        return []

    encoded = quote_plus(query)

    search_urls = [
        f"https://bokon.se/sok/?q={encoded}",
        f"https://bokon.se/sok/?search={encoded}",
        f"https://bokon.se/?s={encoded}",
    ]

    raw_results = search_web_source(
        source_name="Bokon (webbkälla)",
        search_urls=search_urls,
        domains=["bokon.se", "www.bokon.se"],
        page_filter=is_bokon_book_page,
        max_pages=8,
    )

    return _colophon_filter_bokon_results(
        results=raw_results,
        query_text=query_text,
        title=title,
        author=author,
        isbn=isbn,
    )


def swedish_web_sources_search(query_text="", title="", author="", isbn=""):
    results = []

    for source_function in [
        bokus_search,
        bokon_search,
        adlibris_search,
    ]:
        try:
            results.extend(
                source_function(
                    query_text=query_text,
                    title=title,
                    author=author,
                    isbn=isbn,
                )
            )
        except Exception:
            continue

    return deduplicate_results(results)
