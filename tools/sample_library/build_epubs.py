"""Build the fictional EPUB library with embedded metadata and covers."""
import os, sys
from ebooklib import epub
sys.path.insert(0, os.path.dirname(__file__))
from books import BOOKS, CHAPTERS, GENERIC

HERE = os.path.dirname(__file__)
LIB = os.path.join(HERE, "library")
os.makedirs(LIB, exist_ok=True)

CSS = """
body { font-family: Georgia, serif; line-height: 1.5; margin: 1em; }
h1 { font-size: 1.6em; margin: 2em 0 1em; }
p { text-indent: 1.4em; margin: 0 0 0.7em; }
"""

def build(b, i):
    book = epub.EpubBook()
    isbn = f"978{1000000000 + i * 7919:010d}"
    book.set_identifier(f"urn:isbn:{isbn}")
    book.set_title(b["title"])
    book.set_language(b["lang"])
    book.add_author(b["author"])
    book.add_metadata("DC", "publisher", b["publisher"])
    book.add_metadata("DC", "date", f"{b['year']}-03-14")
    book.add_metadata("DC", "description", b["description"])
    for s in b["subjects"]:
        book.add_metadata("DC", "subject", s)
    if b.get("series"):
        book.add_metadata(None, "meta", "", {"name": "calibre:series", "content": b["series"]})
        book.add_metadata(None, "meta", "", {"name": "calibre:series_index", "content": str(b["series_index"])})
    with open(os.path.join(HERE, "covers", b["slug"] + ".jpg"), "rb") as fh:
        book.set_cover("cover.jpg", fh.read())
    style = epub.EpubItem(uid="style", file_name="style/main.css", media_type="text/css", content=CSS)
    book.add_item(style)
    chapters = CHAPTERS.get(b["slug"], GENERIC)
    items = []
    for n, (head, paras) in enumerate(chapters, 1):
        c = epub.EpubHtml(title=head, file_name=f"chap{n:02d}.xhtml", lang=b["lang"])
        body = "".join(f"<p>{p}</p>" for p in paras)
        c.content = f"<html><head><title>{head}</title></head><body><h1>{head}</h1>{body}</body></html>"
        c.add_item(style)
        book.add_item(c)
        items.append(c)
    book.toc = tuple(items)
    book.add_item(epub.EpubNcx())
    book.add_item(epub.EpubNav())
    book.spine = items
    path = os.path.join(LIB, f"{b['slug']}.epub")
    epub.write_epub(path, book, {})
    return path

if __name__ == "__main__":
    for i, b in enumerate(BOOKS):
        build(b, i)
    print("built", len(BOOKS), "epubs in", LIB)
