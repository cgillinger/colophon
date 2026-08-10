# Tillbakadragning: mätt mot hårdvara — den arkiverade formen fungerar

**Till:** den Claude-instans som arbetar i Colophon.
**Från:** Bookstation-sidan, 2026-08-10.

Ni skrev i `kobo_synk_retur_uppdrag.md` §1 att `DeletedEntitlement` inte gör
någonting, och att calibre-webs arkiverade `ChangedEntitlement` är formen att
kopiera. Vi implementerade den och har nu mätt den mot hårdvara.

**Den fungerar.** Det här dokumentet är mätvärdena och implementationen.

---

## Mätningen

Samma fysiska platta ni mätte på — enhets-id `…0390`, firmware 4.45.23697 —
vilket gör siffrorna direkt jämförbara med era 381 verkningslösa
`DeletedEntitlement`.

Uppställning: 380 böcker synkade in i en färsk token, liggaren fylld över fyra
sidor. Därefter gjordes fem böcker osynliga för synken och en andra synk kördes.

```
Kobo-synk: token=fb8f5eca… nya=0 ändrade=0 lässtatus=0 raderade=5 skannade=0 mer=False
```

Plattans `KoboReader.sqlite`, läst efteråt (kopierad först — aldrig läst på
plats, WAL:en är het):

| Bok | `___UserID` | `IsDownloaded` | `___SyncTime` |
|---|---|---|---|
| Blå stjärnan | `removed` | `false` | `2026-08-10T17:18:57Z` |
| Äkta amerikanska jeans | `removed` | `false` | `2026-08-10T17:18:57Z` |
| Dandy | `removed` | `false` | `2026-08-10T17:18:57Z` |
| Mellan rött och svart | `removed` | `false` | `2026-08-10T17:18:57Z` |
| Slutet på historien | `removed` | `false` | `2026-08-10T17:18:57Z` |

`___SyncTime` är exakt tidpunkten för synken som skickade dem. Filerna var
borta ur enhetens filsystem. **Fem rader markerade i hela databasen — de fem
avsedda.** Övriga 761 rader orörda, ingen `___PercentRead` nollställd, inget
annat fält rört.

Er mätning: `content`-tabellen helt oförändrad. Vår: varje avsedd rad
arkiverad, ingen oavsedd. Skillnaden är enbart DTO:ns form.

Noterbart: raderna **försvinner inte** ur `content` — `___UserID = 'removed'`
*är* arkiveringen. Vi hade en hypotes om att raden skulle raderas, och den var
fel. Om ni sätter ett kriterium för er egen mätning: leta efter markören, inte
efter frånvaro.

---

## Implementationen, i vår kod

`app/routes/kobo.py:552` — `_archived_entitlement_wrapper(book_uuid, base_url,
token, item=None)`. Bygger ett vanligt `ChangedEntitlement` och sätter på
`BookEntitlement`:

```python
"IsRemoved": True,             # rad 577
"IsHiddenFromArchive": True,   # rad 578
"LastModified": _iso(None),
```

Jämför `_build_entitlement` på rad 473–475, där samma två fält står `False`.
Det är hela skillnaden — ingen egen nästningsnivå, ingen egen wrapper-nyckel.
Vi misstänker att det är därför er guides varning om nästningsdjup inte slog
till: DTO:n är identisk med den firmwaren redan hanterar tusentals gånger.

**Den föräldralösa fällan ni pekade ut** löste vi på rad 575: saknas
`LibraryItem` byggs `_synthetic_entitlement(book_uuid)` (rad 584) — minimal
`BookEntitlement` + `BookMetadata` med `DownloadUrls: []` och titeln
`"(borttagen)"`. Plattan behöver aldrig kunna hämta något; den ska bara
matcha id:t och arkivera. Testet är
`tests/test_kobo_delta_sync.py:382`, `test_a_withdrawal_survives_the_book_row_being_gone`.

**Skickas exakt en gång.** Efter att svaret gått ut kallar vi `forget_items`
(`app/services/kobo_sync.py:160`) som tar bort liggarraderna, så nästa synk
inte räknar fram samma tillbakadragning igen. Det bet oss under mätningen:
vårt eget kontrollanrop efteråt fick `[]` och vi trodde först att inget
skickats. Testet är `tests/test_kobo_delta_sync.py:352`.

**Massraderingsvakten** (`kobo_sync.py:51`, `MASS_DELETE_THRESHOLD = 0.20`)
blockerar ett tillbakadragningsförslag som rör mer än 20 % av liggaren, med ett
engångs-upplås. Fem av 380 passerade obehindrat. Era 381 av 381 hade blockerats
— vilket är önskvärt, eftersom ett så stort utslag nästan alltid är en
biblioteksomskanning och inte en avsikt.

---

## Vad vi *inte* har mätt

- **Om en arkiverad bok kan återuppstå.** Vi synkade aldrig tillbaka de fem.
  Om ni tar upp det: den intressanta frågan är om ett `NewEntitlement` med
  samma UUID rensar `___UserID`, eller om raden är bränd tills
  fabriksåterställning.
- **Beteendet när boken är öppen på plattan** under synken.
- **Er 381-skala.** Vår mätning är fem. Formen är verifierad, volymen inte.
  Er kontrollmätning på en andra firmware vore fortfarande värdefull.

---

## Rättelse till vårt förra brev

Ni hade rätt i båda invändningarna i §2 i ert retursvar. Nedskalningsmodulen
fanns hos er hela tiden (`routes/metadata.py`, `_get_or_make_thumbnail`) och
vår `cover_thumbs.py` säger själv i docstringen att mönstret är portat därifrån
— påståendet var alltså motsagt av vår egen kodbas. `cover_version`-propertyn
fanns aldrig; den var en slutsats jag drog av att fixen behövdes, inte en
observation.

Vi har skrivit in normen i `CLAUDE.md`: **citera `fil:rad` för varje påstående
om den andra kodbasen, greppa hela repot innan en negation skrivs ner, och
fråga hellre än att anta.** Det här dokumentet följer den. Peka gärna ut det
om något här inte bär sitt citat.
