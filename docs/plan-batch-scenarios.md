# Genomförandeplan: scenario-batch i stället för generisk wizard

Status: plan, 2026-09-16. Bakgrund i samtalet som ledde hit: den generiska
batchwizarden (markera N blandade böcker, välj fält, kör) lönar sig inte,
eftersom N böcker utan delat faktum är N oberoende granskningar. Scenarier
med ett delat faktum (en serie, ett författarskap, ett fält som kan avgöras
deterministiskt) lönar sig. Planen ersätter wizarden med fem sådana.

Skriven för en Opus 5-session som huvudagent. Läs avsnitt 1–3 innan du rör
kod. Varje steg är en egen session; avsluta sessionen när steget är klart.

---

## 1. Arbetssätt

### 1.1 Tokeneffektivitet

- **Läs inte hela filer.** `batch.js` är 2 200 rader, `metadata.py` 2 400.
  Varje steg nedan anger exakta rad- eller funktionsintervall. Läs dem, inte
  filen. Använd `grep -n` för att hitta, `sed -n a,bp` för att läsa.
- **Delegera all läsning som bara ska sammanfattas** (avsnitt 1.3). En
  Explore-agent som läser 800 rader och svarar med 20 kostar en bråkdel av
  att läsa dem själv i huvudkontexten.
- **Skriv koden, inte förklaringen.** Inga sammanfattningar av vad du tänker
  göra innan du gör det. Rapportera resultat, inte process.
- **Kör inte hela testsviten efter varje ändring.** Kör den fil som täcker
  steget. Hela sviten en gång per steg, innan commit.
- **Kända röda tester:** en ren körning är *639 passed, 10 failed*
  (`test_quality.py` 6, `test_scoring.py` 3, `test_scanner.py` 1, se
  `CLAUDE.md`). "Samma 10" är grönt. Försök inte laga dem.

### 1.2 Vad du är bra på och vad du ska akta dig för

Styrkor att använda:

- Att hålla en invariant över flera filer i huvudet. Varje steg har ett
  avsnitt "Invarianter", och det är där du behövs. Gör det arbetet själv.
- Att läsa en diff adversariellt. Gör det på allt en underagent lämnar, innan
  du kör tester. Frågan är alltid: *vad skulle få detta att skriva till fil
  utan att användaren tryckt Tillämpa?*
- Att skriva en spec som en enklare modell kan följa utan att gissa.

Begränsningar att kompensera för:

- **Du breddar scope.** När du ser ett angränsande problem vill du lösa det.
  Skriv det i `docs/TODO.md` i stället. Varje steg har en "Inte i det här
  steget"-lista. Den är bindande.
- **Du tappar detaljer i långa sessioner.** Därför ett steg per session och
  ett rent commit i slutet. Om kontexten blir lång mitt i ett steg: committa
  det som är grönt, skriv en rad i planens statusfält (avsnitt 6) och
  avsluta.
- **Du litar på egen kod utan att köra den.** Definition of done i varje steg
  kräver ett grönt test som skrevs *innan* koden, och att du verifierat att
  det var rött först.
- **Du skriver för mycket text i UI.** Colophon har en knapp UI-ton
  (jämför "Ordna serien", "Saknar omslag"). Rubriker på två ord, hjälptexter
  på en mening.

### 1.3 Delegering

Använd `Agent`-verktyget. Modellval per uppgiftstyp:

| Uppgift | Modell | Varför |
|---|---|---|
| Hitta var något finns, sammanfatta ett kodavsnitt, lista anropsställen | `haiku`, subagent `Explore` | Ren läsning, svaret är kort |
| Mekaniska ändringar: i18n-nycklar in i `bulk_metadata.html` + `messages.po`, `pybabel`-körning, CSS-klasser efter given spec, `.po`-översättning | `haiku` | Ingen bedömning, tydlig spec |
| Implementera en funktion/route/JS-modul mot en spec med givna tester | `sonnet` | Väl avgränsat, testerna avgör |
| Skriva testfall mot en given specifikation av beteende | `sonnet` | Bra på att täcka fall, du granskar att rätt invariant testas |
| Design av spec, invarianter, granskning av underagenters diff, allt som rör filskrivning och `content_updated_at` | du själv | Här sitter risken |

Regler:

- Ge underagenten **filväg + radintervall + spec + testfilens namn**. Aldrig
  "läs koden och lista ut det".
- Underagenten committar aldrig. Du granskar diffen, kör tester, committar.
- Skicka aldrig en underagent på något som skriver till ebook-filer eller
  rör Kobo-stämplingen utan att specen citerar invarianten ordagrant.
- Kör oberoende underagenter parallellt i samma tur (t.ex. i18n-jobbet och
  testskrivningen).

### 1.4 Git

Branch enligt sessionens instruktion. Ett commit per steg, med versionsbump
i samma commit (`app/version.py`, `README.md`, `CLAUDE.md`, se
"Versioning" i `CLAUDE.md`). Tagga. Ingen PR om inte användaren ber om det.

---

## 2. Invarianter som gäller alla steg

1. **Ingen fil skrivs förrän användaren tryckt Tillämpa.** Förhandsvisning är
   ren läsning. Inget steg får en `write_to_file=True` i en kodväg som
   användaren inte explicit utlöst från granskningsvyn.
2. **DB först, fil som separat, synligt val.** Granskningsvyn har en kryssruta
   "Skriv även till filerna (N böcker laddas om på Kobo)", **avkryssad** som
   default utom i språksteget (avsnitt 3.3 förklarar varför).
3. **`content_updated_at` stämplas av filskrivning, inte av DB-ändring.** Se
   `models.py:355–416`. Om ett steg ändrar DB utan fil ska Kobo *inte* ladda
   om. Verifiera med test, inte med resonemang.

   **Rättelse (steg 3, v1.52.0):** detta gäller inte fält i
   `models._DEVICE_CONTENT_COLUMNS`. De stämplar på DB-ändringen ensam,
   utan filskrivning. `language` ligger där — och ska göra det, Kobon
   väljer ordbok och avstavning därifrån. **`series` och `series_index`
   ligger där också, så steg 4 och 5 möter samma sak:** att ordna en serie
   får synkade läsplattor att ladda om böckerna även om ingen fil rörs.
   Räkna med det i UI-texten i stället för att försöka undvika det, och
   skriv inte om `_DEVICE_CONTENT_COLUMNS` — den är bärande för
   Kobo-synken. Se `tests/test_language_check.py`
   ::test_language_only_db_change_still_stamps_content.
4. **Smal diff.** Ett scenario rör högst två fält. Aldrig titel, författare,
   ISBN, synopsis i batch.
5. **JS-strängar går via `window.__colophonConfig.i18n`** i
   `bulk_metadata.html` (`i18n: {`), aldrig i `.js`. Lägg **inte** till
   `[javascript: …]` i `babel.cfg` (se varningen i `CLAUDE.md`).
6. **Ny logik i `app/static/js/*.js` och `app/services/*.py`**, inte i
   mallen och inte i routen. Routes är tunna.
7. **`apply_metadata_to_item` skriver aldrig `language` implicit.** Behåll.
8. **Blueprint-namn:** bara `metadata.*`, `authors.*`, `scan.*`, `settings.*`,
   `kobo.*`, `reader.*`.

---

## 3. Stegen

Ordning: 1 → 2 → 3 → 4 → 5 → (6). Steg 2 och 3 är oberoende av varandra
men båda före 4. Steg 5 återanvänder steg 4:s komponent.

### Steg 1: Stäng hålet i wizarden (PATCH)

**Mål.** Ingen kodväg i batch skriver före granskning. Den generiska
ingången försvinner ur UI; motorn finns kvar för steg 4–6.

**Läs.** `app/routes/metadata.py` 1069–1470 (`bulk_stream`) och 672–830
(`bulk_metadata`, grenen `action == "ai"`). `app/static/js/batch.js`
1783–2085 (`startBatchSearch`, `startBatchAI`) och 1092–1180
(`_batchSaveTextFields`).

**Faktum att utgå från.** `bulk_stream` klassificerar `auto_apply` och kör
då `_apply(... write_to_file=True)` på varje gruppmedlem *innan* eventet
`book_done` skickas (rad ~1283–1300). Granskningssteget i wizarden sparar
sedan samma fält igen via `save-json`, som också skriver filen. AI-grenen i
`bulk_metadata` skriver alla `high`-fält direkt till fil utan någon
granskning alls, och `_AI_DISPLAY_ONLY` är tom så titel och författare ingår.

**Ändringar.**

1. `bulk_stream` får query-parametern `dry_run=1`. Med den sätts
   `classification = "auto_apply"` som idag men **ingen** `_apply` körs;
   `apply_details` blir `None`. Wizardens `startBatchSearch` skickar alltid
   `dry_run=1`. Behåll icke-dry-run-vägen orörd (ingen annan anropare idag,
   men steg 6 kan vilja ha den).
2. Ta bort `action == "ai"`-grenen i `bulk_metadata` och `startBatchAI` i
   `batch.js` plus dess knapp i mallen. Ta bort `_AI_DISPLAY_ONLY` om den
   blir oanvänd.
3. Knappen "Batchåtgärder" i verktygsraden döljs (inte raderas: `display:none`
   via en config-flagga `SHOW_LEGACY_BATCH`, default av). Steg 4–6 tar över
   motorn; när steg 6 är klart raderas resten.
4. Handboken (`docs/handbook-sv.md` avsnitt 9, `handbook-en.md` motsvarande):
   stryk påståendet "bekräftar alltid innan de skriver" tills det är sant,
   eller skriv om avsnittet till "under ombyggnad".

**Test först.** Ny fil `tests/test_batch_dry_run.py`. Mocka
`run_metadata_enrichment` så att den returnerar `classification="auto_apply"`
med ett `fetched_payload`. Anropa `/metadata/bulk/stream?...&dry_run=1`,
konsumera strömmen, assertera att `apply_metadata_to_item` **inte**
anropats (patcha den) och att raden i DB är oförändrad. Kör testet mot
nuvarande kod först: det ska vara rött.

**Delegering.** Testet: `sonnet`, med specen ovan ordagrant. Borttagningen av
AI-grenen: `haiku` (ren radering, du ger radintervallen). `dry_run`-ändringen:
gör själv, den är liten och det är den som bär risken.

**Inte i det här steget.** Ingen ny UI. Ingen ändring av `save-json`. Inga
nya scenarier.

**Klart när.** Testet grönt, hela sviten "samma 10", knappen borta i UI,
`docs/TODO.md` har en rad "radera batch.js-rester efter steg 6".

### Steg 2: Inventering (MINOR)

**Mål.** Användaren ser på ett ögonblick vilka böcker som saknar metadata och
klickar sig till dem i befintlig modal. Vyn läser bara.

**Läs.** `app/services/metadata_pipeline.py` 38–91 (`FIELD_WEIGHTS`,
`QUALITY_THRESHOLDS`, `completeness_score`). `app/templates/bulk_metadata.html`
185–215 (filter- och sorteringsmenyerna). `app/static/js/filters-sort-paging.js`
`applyFilters` och sorteringshanteraren (grep `filterMissingField` och
`sortSelect`).

**Faktum att utgå från.** `completeness_score` finns som kolumn (0 = komplett,
9 = tomt) men räknas idag **bara** om i `apply_metadata_to_item`
(`metadata_writer.py:218`). Skanning och `save-json` uppdaterar den inte, så
den är inaktuell på handredigerade och nyskannade rader. Vikterna täcker
cover 3, description 3, genres 1, published_date 1, publisher 1. Serie ingår
inte.

**Ändringar.**

1. **Räkna om poängen överallt där raden ändras:** i `scanner.py`s upsert, i
   `save_metadata_json`, i `enrichment_apply`/`ai_apply`, i
   `cover/apply`. Lägg en hjälpare `refresh_completeness(item)` i
   `metadata_pipeline.py` och anropa den. Plus en engångsbackfill i
   `database.py` för rader där kolumnen är NULL (mönster: `backfill_*`).
2. **Beslut om vikter:** lägg till `series: 1`. Inte titel/författare (en bok
   utan dem är trasig på annat sätt och syns i författarkön). Max blir 10.
   Dokumentera i docstringen att poängen nu **är** användarvänd.
3. **Trafikljus.** Trösklar: grönt ≤ 1, gult 2–5, rött ≥ 6. En prick i
   tabellradens första cell och i hyllvyns kort (liten, `title`-attribut med
   vilka fält som saknas). CSS i `bulk_metadata.css`.
4. **Räknarrad** i tabellvyn ovanför tabellen: "🔴 12 · 🟡 87 · 🟢 540", varje
   del ett klickbart filter (`filterType === 'completeness'` i `applyFilters`,
   samma mönster som `missing_cover`). Räknas server-side i `bulk_metadata()`
   som de andra räknarna.
5. **Sortering** "Mest ofullständig först" i sorteringsmenyn.
6. **Översikt under Verktyg:** ett avsnitt (ingen ny sida) "Inventering":
   en rad per fält "Saknar synopsis: 41" som länkar till
   `/metadata/bulk?missing=<fält>` (URL-state finns i `url-state.js`,
   kontrollera att filtret redan speglas dit; annars lägg till).

**Test först.** `tests/test_completeness.py`: poängen räknas om vid
`save-json` (skriv titel + tom synopsis, assertera score); backfill sätter
NULL → värde; trösklarna mappar rätt. Röd först.

**Delegering.** Punkt 1 och 2: `sonnet` med testfilen. Punkt 3–5 (JS + CSS +
i18n-nycklar): `sonnet` för JS, `haiku` för i18n och CSS. Punkt 6: `haiku`.
Du: tröskelbeslutet, granskning, och att verifiera att omräkningen inte
missar någon skrivväg (grep `db.session.commit()` i `routes/metadata.py` och
gå igenom listan).

**Inte i det här steget.** Ingen "Hämta allt rött"-knapp. Aldrig. Ingen
AI. Ingen filskrivning.

**Klart när.** Räknarraden stämmer mot filtret (klicka rött → lika många
rader), poängen ändras direkt efter en modal-spara, sviten "samma 10".
Handbok: ett stycke under avsnitt 9 eller ett nytt kort avsnitt.

### Steg 3: Språkkontroll (MINOR)

**Mål.** En vy som läser text ur varje EPUB, jämför med lagrat `language`,
och visar bara saknade och avvikande. Användaren kryssar, trycker Tillämpa.

**Läs.** `app/services/language_detect.py` (hela, 100 rader).
`app/services/scanner.py` 396–407. `app/routes/scan.py` (SSE-mönstret med
bakgrundstråd + `queue.SimpleQueue`, kopiera det). `metadata_writer.py`
49–100 (`_should_write`, språkregeln).

**Ändringar.**

1. `language_detect.py`: ny `detect_language_confident(file_path)` som tar
   **två** sampel (vid 30 % och 60 % av spine-längden, inte början, för att
   undvika copyright och förord), kör `langdetect.detect_langs` på båda,
   returnerar `{"code", "prob", "agree": bool}` eller `None`. Behåll
   `detect_language_from_text` orörd (skannern använder den).
2. Ny route `metadata_bp`: `GET /metadata/language-check/stream` (SSE, alla
   EPUB/KEPUB eller `item_ids`), skickar `{"item_id","stored","detected",
   "prob","agree"}` bara när `stored` saknas/`und` eller ≠ `detected`.
   `POST /metadata/language-check/apply` med `[{item_id, code}]` +
   `write_files: bool`. DB alltid; fil via `apply_metadata_to_item(...,
   selected_fields={"language"}, write_to_file=write_files)`.
3. Ny JS-modul `app/static/js/language-check.js`. Vy: tre kolumner (titel,
   lagrat, detekterat) + sannolikhet. Rader utan lagrat värde förkryssade.
   Avvikande synliga, okryssade, gulmarkerade om `agree` är falskt.
   Kryssrutan för filskrivning **förkryssad** i just detta scenario: språket
   är vad Kobo använder för ordbok och avstavning, så omladdningen är
   önskvärd. Texten ska ändå säga "N böcker laddas om på Kobo".
4. Ingång: Verktyg → Inventering → "Kontrollera språk". Ingen ny sida, en
   modal som återanvänder batchmodalens skal (`#batchModal`) om det är
   enklare än ett nytt; annars eget.

**Invarianter.** Inget skrivs i stream-routen. Endast `language` i
`selected_fields`. MOBI/AZW3 hoppas över och räknas i en fotnot ("N filer
kan inte läsas").

**Test först.** `tests/test_language.py` finns: lägg till fall för
`detect_language_confident` (två sampel oense → `agree=False`; för kort text
→ `None`). `tests/test_language_check_route.py`: stream skriver inte
(patcha `apply_metadata_to_item`, assertera ej anropad); apply med
`write_files=False` ändrar DB men inte `content_updated_at`
(**invariant 3, det här är testet som bevisar den**); apply med
`write_files=True` anropar writer med exakt `selected_fields={"language"}`.

**Delegering.** Punkt 1 + tester: `sonnet`. Punkt 2: `sonnet` med
`scan.py` som mall. Punkt 3: `sonnet`, i18n via `haiku`. Du: `content_updated_at`-
testet granskas rad för rad, och sampelpositionerna (30/60 %) verifieras
mot en riktig EPUB i `tests/fixtures` om en finns, annars mot en syntetisk.

**Inte i det här steget.** Ingen AI. Ingen ändring i skannerns detektion.

**Klart när.** Testerna gröna, en körning mot en lokal testmapp med minst en
felmärkt bok visar exakt den boken, sviten "samma 10".

### Steg 4: Ordna serien (MINOR)

**Mål.** Från ett seriekort: ett AI-anrop med hela gruppen, korsvalidering
mot Wikidata, granskning i en kolumn, Tillämpa skriver `series` +
`series_index`.

**Läs.** `app/services/ai_metadata.py` 79–232 (`build_library_context`,
`format_library_context`) och 558–611 (`adjudicate_author_names`, mönstret
för ett rådgivande anrop). `app/services/metadata_wikidata.py` (grep
`P179`, funktionen som slår upp serie + ordinal per verk).
`app/static/js/series-view.js` 160–200 (kortets markup).
`app/static/js/batch.js` 325–458 (granskningstabellen, mönstret att
återanvända, inte koden).

**Ändringar.**

1. `ai_metadata.py`: ny `propose_series_order(books, series_hint=None)` som
   tar `[{id, title, series, series_index, published_date, file_name}]` och
   returnerar `{"ok", "series_name", "books": [{"id", "index",
   "confidence", "reason"}], "not_in_series": [ids]}`. Egen prompt
   (`_SERIES_ORDER_PROMPT`), JSON-svar, samma felkoder som övriga anrop,
   `_log_usage`. Tak på 60 böcker per anrop; fler → felkod `too_many`.
2. Ny service `app/services/series_batch.py`: `build_series_proposal(
   group_items)` som (a) snappar `series_name` till bibliotekets befintliga
   stavning via samma casefold-nyckel som v1.51.0, (b) frågar Wikidata per
   bok (befintlig funktion; cacha per körning), (c) sätter status per rad:
   `confirmed` (AI + Wikidata eniga), `ai_only`, `conflict` (befintligt
   ifyllt värde ≠ förslag), `unchanged`, (d) räknar invarianter:
   dubblettindex, luckor. Ren funktion, ingen DB-skrivning, testbar utan
   nätverk (Wikidata och AI injiceras).
3. Routes: `POST /metadata/series/propose` (`item_ids`) → förslaget.
   `POST /metadata/series/apply` (`[{item_id, series, series_index}]`,
   `write_files`). Apply via `apply_metadata_to_item(...,
   selected_fields={"series","series_index"}, write_to_file=write_files)`
   på alla formatsyskon i gruppen.
4. Ny JS-modul `series-order.js` med granskningskomponenten. **Bygg den
   för två ingångar redan nu:** den tar en lista av grupper
   `[{series_name, rows:[...]}]`, steg 4 skickar en grupp, steg 5 flera.
   Radlayout: kryssruta · titel · nuvarande serie/nr · → · föreslaget ·
   statusfärg (grön/gul/röd) · skäl i `title`. Grupprubrik visar
   invarianterna ("2 dubblettindex", "lucka vid 5"). Rader med
   `unchanged` visas nedtonade, okryssade. `conflict` okryssade.
   `ai_only` kryssade bara om `confidence == "high"`.
5. Knapp "Ordna serien" på seriekortet (`series-view.js`, i
   `.series-card-body`). Öppnar modalen med gruppens `item_ids`.

**Invarianter.** Aldrig index på en bok i `not_in_series`. En föreslagen
serie med bara en bok utan Wikidata-bekräftelse: hela gruppen visas som
`ai_only` och okryssad. `series_name` byts bara om användaren kryssar
"Byt seriestavning på alla" (en kryssruta i grupprubriken, avkryssad).

**Test först.** `tests/test_series_batch.py` mot `build_series_proposal`
med injicerade AI- och Wikidata-svar: status per rad, snappning av
stavning, dubblett/lucka, singelbok utan bekräftelse → `ai_only`. Route-test:
propose skriver inte; apply med `write_files=False` lämnar
`content_updated_at`.

**Delegering.** Punkt 1: `sonnet` (prompten skriver du, koden runt den
delegeras). Punkt 2 + tester: `sonnet`; du granskar statuslogiken. Punkt 3:
`sonnet`. Punkt 4: `sonnet` med tydlig spec på datakontraktet; i18n `haiku`.
Punkt 5: `haiku`. Du: prompten, datakontraktet mellan 2 och 4 (skriv det som
ett JSON-exempel i specen till båda agenterna), granskning.

**Inte i det här steget.** Ingen författaringång. Ingen seriestädningsvy
över hela biblioteket (den i `docs/TODO.md`, som delar byggsten men är ett
eget steg senare). Ingen ändring av `group_key`.

**Klart när.** Testerna gröna, ett seriekort i lokal miljö ger ett förslag
och Tillämpa ändrar DB utan Kobo-stämpling, sviten "samma 10". Handbok:
nytt avsnitt "Ordna serien". `CLAUDE.md`: ett stycke under
Architecture decisions.

### Steg 5: Ordna författarens serier (MINOR)

**Mål.** Samma komponent som steg 4, men urvalet är alla en författares
formatgrupper och AI:n får hela listan för att gruppera i serier.

**Läs.** `app/routes/metadata.py` 672–700 (author-filtret via
`book_authors`). `app/routes/authors.py` 49–72 (`/authors`-vyn) och
`app/static/js/authors-manage.js` (radens knappar). Steg 4:s
`series_batch.py` och `series-order.js`.

**Ändringar.**

1. `ai_metadata.py`: `propose_author_series(books)` → `{"ok", "series":
   [{"name", "books":[{"id","index","confidence","reason"}]}],
   "standalone": [ids]}`. Samma tak (60), samma felkoder.
2. `series_batch.py`: `build_author_proposal(author_id)` som hämtar en
   representant per formatgrupp via `book_authors` (kopiera filtret från
   `bulk_metadata()`), kör punkt 1, och per föreslagen serie kör samma
   statuslogik som steg 4. Samförfattade böcker (fler än en rad i
   `book_authors`) markeras `co_authored` och visas med en not.
3. Route `POST /metadata/series/propose-author` (`author_id`). Apply
   återanvänds från steg 4.
4. Ingångar: knapp "Ordna serier" i `/authors`-radens åtgärder, och i
   rubriken på `/metadata/bulk?author=<id>` (mallen visar redan
   `author_filter`; lägg knappen där).

**Invarianter.** Utöver steg 4: en serie i förslaget som inte finns i
biblioteket och bara har en bok → `ai_only`, okryssad, oavsett confidence.
Fristående böcker får aldrig index.

**Test först.** Utöka `tests/test_series_batch.py`: gruppering, singelserie
utan bekräftelse, samförfattad markering, tak på 60.

**Delegering.** Som steg 4. Du skriver prompten och granskar.

**Inte i det här steget.** Ingen ändring av författarregistret. Inga
namnbyten. Inga fristående-markeringar sparas (det finns inget fält för
det; skriv i TODO om det saknas).

**Klart när.** En författare med minst tre böcker i två serier ger rätt
gruppering i lokal miljö, tester gröna, sviten "samma 10". Handbok +
`CLAUDE.md`.

### Steg 6: Hämta omslag för filtret (valfritt, MINOR)

**Mål.** När filtret "Saknar omslag" är aktivt visas "Hämta omslag för
dessa". Kör `bulk_stream` **utan** `dry_run` men med bara cover-fält,
granskning i befintlig `_batchRenderCoverReview` (`batch.js:1318`),
Tillämpa via `cover/apply`.

Det här är det enda scenariot som bär den gamla motorn vidare. Gör det
sist, och radera sedan resten av `batch.js` (fältväljaren, synopsis-
granskningen, wizard-stegen) och `SHOW_LEGACY_BATCH`. Skriv specen när
steg 1–5 är klara; den beror på hur mycket av `batch.js` som fortfarande
är levande då.

---

## 4. Definition of done per steg, gemensamt

- Testet som bevisar stegets invariant skrevs först och var rött.
- Hela sviten: "samma 10".
- `python -m pytest tests/<stegets fil> -q` grönt.
- Versionsbump i tre filer + tagg.
- Handbok (sv + en) uppdaterad om UI ändrats.
- `CLAUDE.md` uppdaterad om en arkitekturregel tillkommit.
- Commit-meddelande på svenska, imperativ, med versionsnummer i parentes
  (mönster: `git log --oneline -10`).
- Inga modellnamn i commit, kod eller docs.

## 5. Vad som uttryckligen skjuts upp

Skriv dessa i `docs/TODO.md` när du stöter på dem, gör dem inte:

- Seriestädningsvy över hela biblioteket (klustring av stavningar). Delar
  `series_batch.py` men är eget steg.
- Per-fält-lås (`docs/future-idea-per-field-locks.md`).
- Serieregister som egen tabell.
- "Fristående"-flagga på bok.
- Mappflytt eller omdöpning driven av något av scenarierna.
- De 10 kända röda testerna.

## 6. Status

Uppdatera raden när ett steg är klart, med version och commit.

| Steg | Status | Version | Commit |
|---|---|---|---|
| 1 Stäng hålet | klar | 1.51.1 | 5325b35 |
| 2 Inventering | klar | 1.52.0 | e16e9fc |
| 3 Språkkontroll | klar | 1.52.0 | e16e9fc |
| 4 Ordna serien | klar | 1.53.0 | v1.53.0 |
| 5 Författarens serier | ej påbörjat | | |
| 6 Omslag för filtret | ej påbörjat | | |
