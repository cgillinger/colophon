import os
import posixpath
import zipfile
from bs4 import BeautifulSoup


KNOWN_NON_READING_FILES = [
    "container.xml",
    "content.opf",
    "package.opf",
    "toc.ncx",
    "nav.xhtml",
    "nav.html",
    "toc.xhtml",
    "toc.html",
    "encryption.xml",
    "rights.xml",
]


def clean_text(text):
    if not text:
        return ""

    return " ".join(str(text).split()).strip()


def safe_decode(raw_content):
    if isinstance(raw_content, str):
        return raw_content

    encodings = [
        "utf-8",
        "utf-8-sig",
        "cp1252",
        "latin-1",
    ]

    for encoding in encodings:
        try:
            return raw_content.decode(encoding)
        except Exception:
            continue

    return raw_content.decode("utf-8", errors="replace")


def local_name(tag):
    if not tag or not getattr(tag, "name", None):
        return ""

    return tag.name.split(":")[-1].lower()


def find_first_tag(soup, wanted_name):
    wanted_name = wanted_name.lower()

    return soup.find(lambda tag: local_name(tag) == wanted_name)


def find_all_tags(soup, wanted_name):
    wanted_name = wanted_name.lower()

    return soup.find_all(lambda tag: local_name(tag) == wanted_name)


def is_probably_non_reading_file(name):
    lower_name = name.lower()

    for bad_name in KNOWN_NON_READING_FILES:
        if lower_name.endswith(bad_name):
            return True

    if "/css/" in lower_name:
        return True

    if "/style/" in lower_name:
        return True

    return False


def has_drm_markers(zip_file):
    names = {name.lower() for name in zip_file.namelist()}

    if "meta-inf/rights.xml" in names:
        return True

    if "meta-inf/encryption.xml" in names:
        try:
            encryption_data = safe_decode(zip_file.read("META-INF/encryption.xml")).lower()

            drm_words = [
                "adobe",
                "adept",
                "encrypteddata",
                "cipherdata",
                "encryptionmethod",
            ]

            for word in drm_words:
                if word in encryption_data:
                    return True

        except Exception:
            return True

    return False


def get_rootfile_path(zip_file):
    try:
        container_data = safe_decode(zip_file.read("META-INF/container.xml"))
        soup = BeautifulSoup(container_data, "xml")

        rootfile = find_first_tag(soup, "rootfile")

        if rootfile and rootfile.get("full-path"):
            return rootfile.get("full-path")

    except Exception:
        return None

    return None


def normalize_epub_path(base_dir, href):
    return posixpath.normpath(posixpath.join(base_dir, href))


def get_spine_html_files(zip_file):
    rootfile_path = get_rootfile_path(zip_file)

    if not rootfile_path:
        return []

    try:
        opf_data = safe_decode(zip_file.read(rootfile_path))
        soup = BeautifulSoup(opf_data, "xml")

        base_dir = posixpath.dirname(rootfile_path)

        manifest_items = {}

        for item in find_all_tags(soup, "item"):
            item_id = item.get("id")
            href = item.get("href")
            media_type = item.get("media-type", "")

            if not item_id or not href:
                continue

            href_lower = href.lower()

            looks_like_text = (
                "xhtml" in media_type
                or "html" in media_type
                or href_lower.endswith((".xhtml", ".html", ".htm", ".xht", ".xml"))
            )

            if not looks_like_text:
                continue

            full_path = normalize_epub_path(base_dir, href)

            manifest_items[item_id] = full_path

        ordered_files = []

        spine = find_first_tag(soup, "spine")

        if not spine:
            return []

        for itemref in find_all_tags(spine, "itemref"):
            idref = itemref.get("idref")

            if not idref:
                continue

            full_path = manifest_items.get(idref)

            if not full_path:
                continue

            if full_path in zip_file.namelist():
                if not is_probably_non_reading_file(full_path):
                    ordered_files.append(full_path)

        return ordered_files

    except Exception:
        return []


def detect_possible_text_files(zip_file):
    possible_files = []

    for name in zip_file.namelist():
        lower_name = name.lower()

        if is_probably_non_reading_file(name):
            continue

        if lower_name.endswith((".xhtml", ".html", ".htm", ".xht", ".xml")):
            possible_files.append(name)

    possible_files.sort()

    return possible_files


def split_fallback_text(raw_text):
    parts = []

    for line in raw_text.splitlines():
        line = clean_text(line)

        if len(line) >= 2:
            parts.append(line)

    if not parts:
        one_line = clean_text(raw_text)

        if one_line:
            parts.append(one_line)

    return parts


def extract_blocks_from_html(raw_content):
    blocks = []

    html_content = safe_decode(raw_content)

    soup = BeautifulSoup(html_content, "html.parser")

    for tag in soup(["script", "style", "nav", "noscript", "svg"]):
        tag.decompose()

    html_blocks = soup.find_all(
        ["h1", "h2", "h3", "h4", "p", "li", "blockquote", "div", "section"]
    )

    for html_block in html_blocks:
        text = clean_text(html_block.get_text(" ", strip=True))

        if not text:
            continue

        if len(text) < 2:
            continue

        tag_name = html_block.name.lower()

        if tag_name in ["h1", "h2", "h3", "h4"]:
            block_type = "heading"
        elif tag_name == "blockquote":
            block_type = "quote"
        elif tag_name == "li":
            block_type = "list"
        else:
            block_type = "paragraph"

        blocks.append(
            {
                "type": block_type,
                "text": text,
            }
        )

    if blocks:
        return blocks

    body = soup.find("body")

    if body:
        raw_text = body.get_text("\n", strip=True)
    else:
        raw_text = soup.get_text("\n", strip=True)

    for text in split_fallback_text(raw_text):
        blocks.append(
            {
                "type": "paragraph",
                "text": text,
            }
        )

    return blocks


def extract_epub_blocks(file_path):
    blocks = []
    seen_texts = set()
    drm_detected = False
    tried_files = []

    if not os.path.exists(file_path):
        return [
            {
                "type": "paragraph",
                "text": "Bookstation hittar inte EPUB-filen på disken.",
            }
        ]

    try:
        with zipfile.ZipFile(file_path, "r") as zip_file:
            drm_detected = has_drm_markers(zip_file)

            html_files = get_spine_html_files(zip_file)

            if not html_files:
                html_files = detect_possible_text_files(zip_file)

            tried_files = html_files[:20]

            if not html_files:
                if drm_detected:
                    return [
                        {
                            "type": "paragraph",
                            "text": "Bookstation hittar ingen vanlig läsbar text i denna EPUB. Filen verkar innehålla DRM/låsning. Metadata och omslag kan ibland visas, men själva boktexten går inte att läsa direkt i Bookstation.",
                        }
                    ]

                return [
                    {
                        "type": "paragraph",
                        "text": "Bookstation hittade inga HTML/XHTML-sidor inuti EPUB-filen.",
                    }
                ]

            for html_file in html_files:
                try:
                    raw_content = zip_file.read(html_file)
                except Exception:
                    continue

                page_blocks = extract_blocks_from_html(raw_content)

                for block in page_blocks:
                    text = clean_text(block["text"])

                    if not text:
                        continue

                    if len(text) < 2:
                        continue

                    duplicate_key = text.lower()

                    if duplicate_key in seen_texts:
                        continue

                    seen_texts.add(duplicate_key)

                    blocks.append(
                        {
                            "type": block["type"],
                            "text": text,
                        }
                    )

    except zipfile.BadZipFile:
        return [
            {
                "type": "paragraph",
                "text": "Den här EPUB-filen verkar vara skadad eller inte en riktig EPUB-fil.",
            }
        ]

    except Exception as error:
        return [
            {
                "type": "paragraph",
                "text": f"Bookstation kunde inte läsa EPUB-filen. Fel: {error}",
            }
        ]

    if not blocks:
        if drm_detected:
            return [
                {
                    "type": "paragraph",
                    "text": "Bookstation hittade ingen läsbar boktext. EPUB-filen verkar vara DRM-skyddad/låst. Då kan Bookstation inte läsa själva texten, även om titel, omslag och annan metadata ibland kan hittas.",
                }
            ]

        file_list = ", ".join(tried_files[:8])

        if not file_list:
            file_list = "inga läsbara innehållsfiler hittades"

        return [
            {
                "type": "paragraph",
                "text": "Bookstation hittade ingen läsbar text i denna EPUB-fil.",
            },
            {
                "type": "paragraph",
                "text": f"Teknisk info: försökte läsa: {file_list}",
            },
        ]

    return blocks
