import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.services.auto_link_importer import auto_import_metadata_from_link


def main():
    if len(sys.argv) < 2:
        print("Användning:")
        print("python tools/test_auto_link_import.py 'https://länk-till-bok'")
        raise SystemExit(1)

    url = sys.argv[1]

    result = auto_import_metadata_from_link(url)

    print("OK:", result.get("ok"))
    print("Metod:", result.get("method"))
    print("Fel:", result.get("error"))

    book = result.get("result")

    if not book:
        return

    print("Källa:", book.get("source"))
    print("Titel:", book.get("title"))
    print("Författare:", book.get("author"))
    print("ISBN:", book.get("isbn"))
    print("Förlag:", book.get("publisher"))
    print("Språk:", book.get("language"))
    print("Omslag:", book.get("cover_url"))
    print("Beskrivning:", book.get("description", "")[:500])


if __name__ == "__main__":
    main()
