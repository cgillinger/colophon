# Design — författarundermappar för uppladdade böcker + uppströmsstädning

> Status: **BYGGT i v1.38.0 (2026-07-28).** Implementation: `app/services/author_folders.py`,
> städning i `app/services/upstream_sync.py`, tester i `tests/test_author_folders.py`.
> De fyra öppna besluten avgjordes: (1) ingen bulk-flytt (per bok räcker — 8 rot-filer),
> (2) städning av som default (`UPSTREAM_CLEANUP_ORPHANS`, checkbox i inställningarna),
> (3) massomdöpning uppskjuten, (4) flytt + städning byggdes ihop. Mappnamnet tas numera
> från huvudförfattarens (position 0) kanoniska registernamn — flerförfattarstödet i
> v1.36.0 gjorde `authorKey`-strängtolkningen till enbart fallback/systermappsmatchning.
> Konverterad från diskussion 2026-06-10.
> Bygger ovanpå den shippade uppladdningsfunktionen i v1.17.0 (`app/routes/scan.py` `/upload`,
> `app/static/js/upload.js`).

## Problemet vi löser
Uppladdning lägger idag alla filer **platt i `LIBRARY_DIR`-roten**. Användaren vill ha
**författarundermappar** (`LIBRARY_DIR/<Författare>/<fil>`), à la Calibre — men utan att
Colophon blir en automatisk filhanterare.

## Vald modell: "root + flytta-på-begäran" (INTE mappval vid uppladdning)
Ladda alltid upp platt i roten. Mappläggningen blir en **medveten användarhandling** i
edit-modalen, gjord *när metadatan är bra* (författare känd/rättad), inte vid intaget när den
är som sämst. Detta dödar drift-problemet (Colophon flyttar aldrig filer i tysthet) och är i
linje med filosofin "vi rör inte dina filer utan att du ber om det".

## Beslutade designval
- **Saknad författare** → boken **stannar i roten**. Knappen "Flytta till författarmapp" visas
  för rot-böcker i edit-modalen och **aktiveras när författare finns**. Visar målsökväg.
- **Flera författare** → använd **första** författaren (jfr Calibres author_sort).
- **Namnkonsolidering** via ett `authorKey()`-mönster som speglar befintliga
  `seriesKey()` / `seriesBetterName()` (i `core.js`):
  1. Räkna `authorKey` (lowercase, punkt/understreck→mellanslag, kollapsa whitespace, trimma).
  2. Finns en **systermapp vars nyckel matchar** → återanvänd den (så "arthur_c_clarke" hamnar
     i befintliga "Arthur C. Clarke", inte i en ny mapp).
  3. Annars skapa mappen med **rensad visningsstavning**.
  - Hanterar **kosmetisk** variation (versaler/whitespace/punkt/understreck), INTE **semantisk**
    ("Arthur C. Clarke" vs "A. C. Clarke") — den senare rättar användaren i författarfältet och
    flyttar om. Massomdöpning av befintliga mappar = senare/utanför scope.
- **Explicit knapp, inte automatisk flytt** vid varje författar-edit (tyst filflytt vid varje
  tangenttryck bryter mot hela poängen).

## Flytt-semantik (viktigt — Colophon flyttar aldrig filer idag)
- `file_path` är `unique=True` och är nyckeln scannern matchar mot. Flytt = **flytta på disk
  OCH uppdatera `file_path` i samma operation** (atomiskt). Annars ser en mellanliggande
  skanning en "ny" + "borttagen" fil → raden återskapas, **`id` byts**, lässtatus/Kobo tappas.
- **Bevara `id`** → läsförlopp, betyg och Kobo-entitlement (som hänger på `LibraryItem.id`,
  inte sökvägen) följer med. Flytta raden, radera/återskapa aldrig.
- **Flytta hela formatgruppen** (`group_key`) tillsammans, annars splittras EPUB+MOBI på två
  platser. `group_key` (titel+författare-hash) är sökvägsoberoende → grupperingen klarar sig.
- Omskanning blir idempotent (rekursiv `rglob` hittar filen på nya sökvägen).

## Säkerhet
- **Sökvägssäkerhet (det riktiga hotet).** Författarsträng kan ha `/ \ .. NUL`, kontrolltecken,
  släng-punkter/mellanslag, Windows-reserverade namn, absurd längd. Sanera mappnamnet med
  **samma sanitizer som filnamn** (`sanitize_upload_filename`-mönstret, basename-only). Lägg
  till bälte-och-hängslen: efter `join`, resolva och **verifiera att sökvägen ligger under
  `LIBRARY_DIR`**.
- **Ingen SQL-escaping.** SQLAlchemy-ORM använder parametriserade queries → författarnamn binds
  som värde, byggs aldrig in i SQL-sträng. Att escapa för "db-inject" vore fel verktyg (skulle
  förvanska t.ex. "O'Brien"). XSS hanteras redan av Jinja-autoescape + `_esc` i JS.
  **Sanera för filsystemet, inte för databasen.**

## Uppströmsstädning (rsync-orphan efter flytt)
Problem: rsync-push (utan `--delete`, medvetet) kopierar nya sökvägen uppströms men lämnar kvar
den gamla → **dubblett uppströms**. Lösning = **kirurgisk, spårad, uppskjuten radering** kopplad
till push-flödet. ALDRIG `rsync --delete`.

Principer:
1. **Radera bara det Colophon själv pushat och kan verifiera** (`upstream_synced_at` finns).
   Filer som lagts uppströms för hand / av annat verktyg rörs aldrig — säkerhetsgränsen.
2. **Nytt före gammalt:** pusha ny sökväg → verifiera att den finns uppströms → radera gammal.
   Aldrig radera gammal innan ny finns.
3. **Uppskjutet, inte vid flyttillfället:** lagra en "pending upstream-städning" på boken (den
   relativa sökväg som *faktiskt* ligger uppströms = senast pushade). Nästa push städar och
   nollar fältet. Överlever omstarter.

Kräver:
- Modelltillägg via `ensure_*`-migrationsmönstret: spara *senast pushade relativa sökväg* +
  `pending_upstream_cleanup`-fält.
- Radering = direkt `os.remove(UPSTREAM_DIR/gammal_sökväg)` (upstream är monterad sökväg i
  containern). Ev. tom författarmapp uppströms rensas — bara om tom, försiktigt.
- Hantera **flera flyttar före en push** → fältet pekar på det som faktiskt ligger uppströms,
  inte mellansteg.
- Rapportera i push-sammanfattningen ("städade N föräldralösa filer uppströms") + logga varje
  radering.
- **Begränsning:** kan bara städa filer Colophon själv pushat. By design.

## ÖPPNA BESLUT (ta tag i imorgon)
1. **Bulk-variant?** Bara knapp i rot-böckers modal, eller även "flytta alla rot-böcker med
   känd författare på en gång"?
2. **Uppströmsstädning default på eller av?** Flagga `COLOPHON_UPSTREAM_CLEANUP_ORPHANS` —
   på = smidigast (raderar uppströms automatiskt vid push), av = användaren slår på medvetet.
3. **Massomdöpning av befintlig mapp** vid ändrad stavning — bygga nu eller skjuta upp?
4. Bygga flytt + uppströmsstädning i **ett svep** eller flytt först, städning som uppföljning?

## Ärliga hakar att minnas
- Upstream-orphan kan bara städas för Colophon-pushade filer.
- Normalisering = kosmetisk, inte semantisk.
- Flytt är en engångshandling per bok; inga befintliga rot-böcker rör sig förrän du ber om det
  (bra — icke-destruktivt, opt-in per bok).

## Berörda filer (preliminärt)
- `app/routes/metadata.py` — ny POST-route, t.ex. `/metadata/<id>/move-to-author-folder`.
- `app/routes/scan.py` — `sanitize_upload_filename` återanvänds för författarmapp.
- `app/services/scanner.py` / ny helper — `author_key` + flytt-logik (move + uppdatera file_path).
- `app/services/upstream_sync.py` — orphan-städning i push-flödet.
- `app/services/database.py` — `ensure_*` för nya kolumner.
- `app/static/js/book-modal.js` — knapp + målsökväg + enable-on-author.
- `app/models.py` — nya fält (senast pushad sökväg, pending cleanup).
- Versionsbump: ny MINOR (1.18.0).
