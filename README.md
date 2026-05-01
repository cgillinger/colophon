# Bookstation

Självhostat digitalt bibliotek för e-böcker och ljudböcker. Hanterar din samling, läser EPUB-filer i webbläsaren, hämtar metadata och omslag automatiskt, och laddar ner böcker från svenska och internationella bokhandlar.

---

## Funktioner

- **Bibliotek** — bläddra, sök och organisera e-böcker och ljudböcker
- **Inbyggd EPUB-läsare** — läs direkt i webbläsaren med sidnavigering
- **Ljudboksspelare** — spela upp MP3/M4A/M4B i webbläsaren
- **Metadata** — hämta titel, författare, serie, ISBN, förlag, beskrivning och omslag från Google Books och Calibre-plugins (Goodreads, Fantastic Fiction, FictionDB)
- **Bokhandelsintegration** — ladda ner köpta böcker från Adlibris, Bokus, Bokon, Kobo och Google Play Böcker med Playwright-automation
- **DRM/ACSM** — öppna ACSM-filer i Adobe Digital Editions och importera avkrypterade EPUB/PDF till biblioteket
- **Serier och vill-läsa-lista** — organisera böcker i serier och markera titlar för framtida läsning
- **AI-metadata** — fråga Mistral AI om serietillhörighet och andra metadataförbättringar, med manuell granskning av varje förslag

---

## Teknik

| Komponent | Bibliotek |
|---|---|
| Webb-ramverk | Flask 3 |
| Databas | SQLite via Flask-SQLAlchemy |
| EPUB-hantering | EbookLib |
| Browser-automation | Playwright (Chromium) |
| HTML-parsning | BeautifulSoup4 |
| Ljudfilsmetadata | Mutagen |
| Miljövariabler | python-dotenv |
| Metadata-API-anrop | requests |

---

## Installation

### Krav

- Python 3.10 eller senare
- Chromium (installeras automatiskt av Playwright)

### Steg

```bash
# 1. Klona repot
git clone <repo-url>
cd Bookstation

# 2. Skapa och aktivera virtuell miljö
python3 -m venv venv
source venv/bin/activate

# 3. Installera Python-beroenden
pip install -r requirements.txt

# 4. Installera Playwright-webbläsaren
playwright install chromium

# Valfritt: installera extra metadata-plugins för bättre sökresultat
# Goodreads, Fantastic Fiction och FictionDb ger bättre metadata för serier, serieordning och genrer.
bash tools/install_calibre_plugins.sh

# 5. Konfigurera miljövariabler
cp .env.example .env
# Redigera .env och sätt åtminstone BOOKSTATION_SECRET_KEY
```

---

## Konfiguration

Kopiera `.env.example` till `.env` och fyll i dina värden:

| Variabel | Beskrivning | Obligatorisk |
|---|---|---|
| `BOOKSTATION_SECRET_KEY` | Hemlig nyckel för Flask-sessioner | Ja |
| `BOOKSTATION_LOG_LEVEL` | Loggningsnivå (`DEBUG`, `INFO`, `WARNING`) | Nej (standard: `INFO`) |
| `BOOKSTATION_GOOGLE_BOOKS_KEY` | Google Books API-nyckel | Nej |
| `BOOKSTATION_ADE_CMD` | Sökväg till Adobe Digital Editions | Nej |
| `BOOKSTATION_MISTRAL_API_KEY` | API-nyckel för Mistral AI (metadata-förslag) | Nej |
| `BOOKSTATION_MISTRAL_MODEL` | AI-modell (standard: `mistral-small-latest`) | Nej |

Generera ett säkert värde för `BOOKSTATION_SECRET_KEY`:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

---

## AI-metadata (valfritt)

Bookstation kan fråga en AI-tjänst — Mistral — om vilken **serie** en bok tillhör och vilken **del** i serien det är. AI:n kan också föreslå förbättringar av språk, ämnen och beskrivning. Alla förslag visas för dig innan något sparas — inget ändras automatiskt.

Funktionen är helt valfri. Bookstation fungerar precis som vanligt utan den. Den aktiveras bara om du lägger in en API-nyckel (en slags lösenord som ger Bookstation tillgång till AI-tjänsten).

### Skaffa en API-nyckel

1. Gå till https://console.mistral.ai/ och skapa ett konto. E-postadress räcker — inget kreditkort krävs för gratisplanen.
2. Klicka på **API Keys** i menyn till vänster.
3. Klicka **Create new key** och kopiera nyckeln som visas. Den visas bara en gång, så kopiera den direkt.
4. Öppna `.env`-filen i Bookstations mapp och lägg till raden:
   ```
   BOOKSTATION_MISTRAL_API_KEY=din-nyckel-här
   ```
5. Starta om Bookstation.
6. Nu syns knappen **🤖 Fråga AI om metadata** på varje boks metadatasida.

### Kostnad och gratisnivå

Mistral erbjuder en gratis "Experiment"-plan som räcker mer än väl för ett litet privatbibliotek. Planen har ett tak på antal tokens per månad — men ett enskilt anrop (en bok) förbrukar en mycket liten mängd, och taket rymmer tusentals bokanrop. För de allra flesta räcker gratisplanen utan problem. Om du vill ha mer kapacitet kan du uppgradera till betalplan, men det behöver du troligtvis inte.

Bookstation skickar bara kort metadata (titel, författare, ISBN och en kort beskrivning) till Mistral — aldrig bokfiler eller annat privat material.

### Byta AI-modell

Standardvalet är `mistral-small-latest`, vilket fungerar bra för metadata. Om du vill prova en annan modell kan du lägga till:

```
BOOKSTATION_MISTRAL_MODEL=modellnamn
```

i `.env`. De flesta behöver inte ändra detta.

---

## Starta applikationen

```bash
source venv/bin/activate
python run.py
```

Öppna `http://127.0.0.1:5050` i webbläsaren.

---

## Produktion (valfritt)

För personligt bruk fungerar Flasks inbyggda dev-server fint. Vill du däremot exponera Bookstation på ditt lokala nätverk rekommenderas Gunicorn som WSGI-server:

```bash
gunicorn wsgi:app --bind 0.0.0.0:5050
```

---

## Biblioteket

Bookstation skannar mappen `bibliotek/` efter stödda filformat:

| Typ | Format |
|---|---|
| E-böcker | `.epub`, `.pdf`, `.txt`, `.cbz`, `.cbr` |
| Ljudböcker | `.mp3`, `.m4a`, `.m4b`, `.zip` |

Lägg filer i `bibliotek/` och klicka på **Skanna bibliotek** i gränssnittet.

---

## Nedladdning från bokhandlar

Bookstation stöder nedladdning från fem butiker med hjälp av Playwright (Chromium med persistent session):

| Butik | Metod |
|---|---|
| Adlibris | Direktlänkar via `/produkt/download`-API |
| Bokus | Omslagsklick → popup med EPUB/PDF/ACSM |
| Bokon | Omslagsklick → nedladdningsval |
| Kobo | Menyknapp → "Ladda ner" → bekräftelsepopup |
| Google Play Böcker | Menyknapp → "Exportera" → EPUB/PDF-val |

### Arbetsflöde

**1. Logga in (en gång per butik)**

```bash
python tools/bookstore_web_worker.py login --store bokus
```

Logga in i det Chromium-fönster som öppnas. Sessionen sparas i `browser_profiles/<butik>/`.

**2. Ladda ner böcker**

```bash
# Automatisk nedladdning (upp till 20 böcker)
python tools/bookstore_web_worker.py generic-download --store bokus

# Förhandsgranska utan att ladda ner
python tools/bookstore_web_worker.py generic-download --store bokus --dry-run

# Headless (utan synligt webbläsarfönster)
python tools/bookstore_web_worker.py generic-download --store bokus --headless

# Adlibris (specialiserad extraktionsmetod)
python tools/bookstore_web_worker.py download-adlibris
```

Nedladdade filer sparas i `downloads/bookstores/<butik>/`.

**3. Övervaka manuellt**

Om automatiken inte fungerar kan du klicka själv medan Bookstation sparar alla nedladdningar:

```bash
python tools/bookstore_web_worker.py watch --store kobo
```

### bookstore_downloader.py — alternativt CLI

Ett enklare CLI med interaktivt läge:

```bash
# Visa stödda butiker
python tools/bookstore_downloader.py list

# Logga in
python tools/bookstore_downloader.py login --store adlibris

# Övervaka nedladdningar
python tools/bookstore_downloader.py watch --store bokus

# Automatisk skanning
python tools/bookstore_downloader.py auto --store bokus --dry-run

# Adlibris med manuell navigering
python tools/bookstore_downloader.py adlibris-downloads --interactive
```

---

## DRM och ACSM

Vissa butiker levererar DRM-skyddade böcker som `.acsm`-filer. Bookstation kan öppna dessa i Adobe Digital Editions (ADE) och sedan importera den avkrypterade EPUB/PDF.

**Krav:** Adobe Digital Editions installerat (inbyggt på Windows/macOS, eller via Wine på Linux).

**Arbetsflöde i gränssnittet:**

1. Gå till **DRM** i navigeringen
2. Klicka **Bearbeta väntande ACSM-filer** — ADE öppnas och avkrypterar filerna
3. Klicka **Importera från ADE** — de avkrypterade filerna kopieras till biblioteket

Sätt `BOOKSTATION_ADE_CMD` i `.env` om ADE inte hittas automatiskt.

---

## Projektstruktur

```
Bookstation/
├── app/
│   ├── __init__.py          # App-fabrik, loggningsinställning
│   ├── config.py            # Flask-konfiguration
│   ├── models.py            # LibraryItem-modell (SQLAlchemy)
│   ├── paths.py             # Centrala sökvägar för hela projektet
│   ├── routes/
│   │   ├── library.py       # Bibliotek, skanning, filhantering
│   │   ├── reader.py        # EPUB-läsare, ljudboksspelare
│   │   ├── metadata.py      # Metadatasökning och -redigering
│   │   ├── bookstores.py    # Bokhandelsintegration (bakgrundsjobb)
│   │   └── drm.py           # DRM/ACSM-hantering
│   └── services/            # Affärslogik och API-integrationer
├── tools/
│   ├── bookstore_web_worker.py   # CLI för Playwright-automation
│   ├── bookstore_downloader.py   # Alternativt nedladdnings-CLI
│   └── stores/
│       ├── common.py        # Delade Playwright-verktyg
│       ├── adlibris.py      # Adlibris-logik
│       ├── bokus.py         # Bokus-logik
│       ├── bokon.py         # Bokon-logik
│       ├── kobo.py          # Kobo-logik
│       ├── google.py        # Google Play Böcker-logik
│       ├── generic.py       # Generisk nedladdning
│       └── js/              # JavaScript för sidinspektion
├── bibliotek/               # Ditt bibliotek (lägg filer här)
├── downloads/bookstores/    # Nedladdade böcker från butiker
├── browser_profiles/        # Playwright-sessioner (en per butik)
├── data/                    # Databas, omslag, EPUB-cache
├── var/                     # Loggar, DRM-status, jobbfiler
├── .env.example             # Mall för miljövariabler
├── requirements.txt
└── run.py                   # Starta applikationen
```

---

## Loggar

Applikationsloggen sparas i `var/logs/bookstation.log` (roterande, max 1 MB, 5 backuper).

DRM-historik sparas i `var/bookstore_jobs/skipped_drm.jsonl`.

---

## Tredjepartsberoenden och licenser

### Python-paket

| Paket | Version | Licens | Källa |
|---|---|---|---|
| Flask | 3.0.3 | BSD-3-Clause | github.com/pallets/flask |
| Flask-SQLAlchemy | 3.1.1 | BSD-3-Clause | github.com/pallets-eco/flask-sqlalchemy |
| EbookLib | 0.18 | AGPL-3.0 | github.com/aerkalov/ebooklib |
| beautifulsoup4 | 4.12.3 | MIT | crummy.com/software/BeautifulSoup |
| mutagen | 1.47.0 | GPL-2.0-or-later | github.com/quodlibet/mutagen |
| python-dotenv | 1.0.1 | BSD-3-Clause | github.com/theskumar/python-dotenv |
| playwright | senaste | Apache-2.0 | github.com/microsoft/playwright-python |
| requests | senaste | Apache-2.0 | github.com/psf/requests |
| gunicorn | senaste | MIT | github.com/benoitc/gunicorn |

### JavaScript-bibliotek

| Bibliotek | Version | Licens | Källa |
|---|---|---|---|
| epub.js | 0.3.x | BSD-2-Clause | github.com/futurepress/epub.js |

epub.js levereras som en lokal minifierad fil (`app/static/js/epub.min.js`). Inga externa CDN-beroenden används.

### Systemverktyg (körtidsberoenden, ej bundlade)

| Verktyg | Licens | Källa |
|---|---|---|
| Calibre (`ebook-meta`, `fetch-ebook-metadata`) | GPL-3.0+ | calibre-ebook.com |
| Goodreads Calibre-plugin (valfritt) | GPL-3.0 | github.com/kiwidude68/calibre_plugins |
| Fantastic Fiction Calibre-plugin (valfritt) | GPL-3.0 | github.com/kiwidude68/calibre_plugins |
| FictionDB Calibre-plugin (valfritt) | GPL-3.0 | github.com/kiwidude68/calibre_plugins |

Calibre-plugins installeras separat via `bash tools/install_calibre_plugins.sh`.

### Externa API:er (kräver egna nycklar)

| Tjänst | Villkor | Källa |
|---|---|---|
| Google Books API | Gratis med API-nyckel · Google Terms of Service | developers.google.com/books |

En fullständig licensöversikt finns också under **Om**-sidan i applikationens gränssnitt (`/about`).
