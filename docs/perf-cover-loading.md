# Prestanda: omslagsladdning / bibliotekets starttid

Anteckningar från uppsnabbningen av kataloagens starttid (juni 2026), sparade
ifall vi behöver återkomma. Status efter `v1.25.0`: **användaren bedömde
starttiden som tillräckligt snabb på iPad.** Lager A + B gjorda; Lager C
medvetet inte gjord.

## Problemet

`bulk_metadata.html` renderar hela biblioteket på en gång (en `<tr>` per bok).
Starten var trög, särskilt på iPad/Safari över WiFi. Tre staplande orsaker:

1. **Antal** — alla omslags-`<img>` begärdes direkt om `loading="lazy"` saknades.
2. **Storlek** — `cover_item` serverade originalomslag i full upplösning trots
   att de visas på 80–320 px.
3. **Samtidighet** — Gunicorn kör 2 *sync*-workers; I/O-bundna fil-requests
   betas av två i taget, resten köar.

## Baslinje (uppmätt före åtgärd, 2026-06-21)

| Mått | Värde |
|---|---|
| Omslag på disk (`/data/covers`) | 1059 filer, 166 MB |
| Storleksspridning | 24 st >1 MB (max **2,7 MB**), 44 st 512 KB–1 MB, 512 st 100–512 KB, 479 st <100 KB |
| Visad payload (379 katalogomslag) | **79,3 MB** vid kall start |
| Workers | 2× **sync** (`Dockerfile` CMD: `--workers 2`, inga trådar) |
| Pillow | saknades i `requirements.txt` före v1.25.0 |

## Verktygsgräns (viktigt vid framtida mätning)

**Playwrights headless-Chromium hedrar inte `loading="lazy"`** — den laddar alla
bilder direkt oavsett viewport (ingen riktig måla-viewport att grinda mot).
Mät därför **inte** omslags-deferral (antal requests vid load) via Playwright;
det ger falskt negativt och säger inget om iPad/Safari. Verifierat både i normal
och 390×700 viewport — båda hämtade alla 379.

Mät i stället tillförlitligt från terminalen:
- **Filstorlek per omslag** på disk (`ls -lh /data/covers`, `du -sh`).
- **Body-storlek över HTTP** med `curl -s -o /dev/null -w '%{size_download}'`.
- **Worker-setup** ur `Dockerfile` CMD.

Playwright duger till *funktionell* verifiering (vyer renderar, inga trasiga
omslag), inte till att bevisa deferral eller payload-gating.

Den slutgiltiga domen om upplevd starttid kommer från användarens iPad, inte
från en headless-mätning.

## Lager A — Lazy-load (antal) — `v1.24.2`→`v1.24.3`

En rad i `bulk_metadata.html`: tabellradens omslags-`<img>` fick
`loading="lazy" decoding="async"`. Bara synliga omslag hämtas; dolda
tabellbilder i hyllvyn hämtas inte alls. Övriga vyer hade redan lazy.
Verifierat: 379/379 imgs har attributet.

## Lager B — Nedskalade thumbnails (storlek) — `v1.25.0`

`cover_item` (`app/routes/metadata.py`) tar nu `?w=` och serverar en cachad,
nedskalad JPEG (Pillow, q82, progressive) i stället för originalet.

- **Bredder**: allowlist `(160, 320, 640)`, "snap-up" till minsta ≥ begärd.
  Tabell + reading-now begär `w=320` (täcker hyllvyns `--cover-width:160px` @2x
  och är skarpt för 80 px-cellen). Bokmodal/omslagsväljare/enrichment-preview
  behåller **full upplösning** (inget `?w=`).
- **Vyer ärver gratis**: `shelf-view.js` och `series-view.js` läser `coverSrc`
  från tabellradens `.cover img`, så `?w=320` propagerar dit utan extra ändring.
- **Cache**: `/data/covers/thumbs/` (additivt, originalen orörda).
- **Invalidering** (det knepiga): cachenyckeln = `sha1(realpath + mtime_ns +
  size + width)`. Byts ett omslag ändras källfilens identitet → ny nyckel → ny
  thumb genereras automatiskt. **Inga av de 9+ skrivställena för `cover_path`
  behöver röras.** Gamla thumbs blir ofarliga orphans (kan städas vid behov).
- **Felsäkerhet**: Pillow saknas / avkodning misslyckas / ogiltig `w` → faller
  tillbaka på `send_file(original)`. `os.replace` ger atomisk publicering (säkert
  med 2 workers).
- **Cache-headers**: thumbnails `max_age=3600` (kort, eftersom URL:en är stabil
  över omslagsbyten; ETag/Last-Modified fångar byte vid revalidering).

### Resultat (uppmätt efter, HTTP body-storlek)

| | Original | Thumb @320 |
|---|---|---|
| Tyngsta omslaget (item 61) | 2 734 KB | **33 KB** (−99 %) |
| Hela katalogen (379 omslag) | **79,3 MB** | **13 MB** (−84 %, ~35 KB/st) |

Kantfall verifierade: full upplösning utan `?w=` (2,8 MB, 200); `w=300→320`,
`w=500→640`; `w=abc` och `w=-5` → säker fallback till original.

## Lager C — Worker-samtidighet — INTE GJORD (nästa steg om det behövs)

Sekundärt. Gör bara om kön mot Gunicorn fortfarande är flaskhalsen efter A+B.
Efter v1.25.0 är omslagstrafiken nedkapad ~99 %/bild och gatead till synliga
omslag, så 2-worker-kön bedömdes inte längre vara flaskhalsen — och iPad-testet
bekräftade att det räcker.

**Om vi återkommer:** byt sync-workern mot `gthread` eller lägg till `--threads`
i `Dockerfile` CMD så I/O-bundna `send_file`-requests kan köras parallellt.

⚠️ **Verifiera uttryckligen efteråt** (CLAUDE.md varnar: subprocess-tunga
Calibre-operationer och SSE-strömmar trivs inte alltid med trådade workers):
- En **scan** fungerar utan timeout eller worker-krasch.
- En **bulk-metadata-körning (SSE)** strömmar som förut.
- **Avbryt** (`_abort_event`) fungerar fortfarande.

Blir något instabilt under `gthread` — **backa** worker-ändringen och notera det.

## Möjliga framtida förbättringar (ej gjorda)

- **WebP/AVIF** i stället för JPEG för thumbs (mindre, men kräver `Accept`-koll).
- **Cache-warming** efter deploy (loopa `/cover/<id>?w=320`) så första
  användaren slipper genereringskostnaden. Genereringen är annars lat per omslag.
- **Orphan-städning** av `/data/covers/thumbs/` (gamla nycklar efter omslagsbyten).
- **Pagineriong / virtualisering** av tabellen om bibliotekat växer kraftigt
  (i dag renderas alla rader; lazy-load gör det acceptabelt, men DOM-storleken
  växer linjärt).

## Relevanta filer

- `app/routes/metadata.py` — `cover_item`, `_resolve_cover_source`,
  `_get_or_make_thumbnail`, `_THUMB_WIDTHS`.
- `app/templates/bulk_metadata.html` — tabellradens omslags-`<img>` (`w=320`).
- `app/static/js/shelf-view.js`, `series-view.js` — ärver `coverSrc` från raden.
- `requirements.txt` — `Pillow>=10.0`.
- `Dockerfile` — Gunicorn CMD (för ev. Lager C).
