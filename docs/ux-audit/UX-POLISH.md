# UX-polish — bulk_metadata-vyn

Audit utförd 2026-05-24 mot produktionsservern via Playwright MCP.
Fynden är sorterade efter typ och prioriterade per område. Fokus är
polering — befintliga funktioner som kan kännas vassare, inte ny
funktionalitet.

Prioriteringsnotation:
- **P1** — bugg eller tydligt fel som syns för användaren
- **P2** — friktion/förvirring som inte är akut, men borde fixas
- **P3** — kosmetiskt eller nice-to-have

---

## 1. Pluralisering ("boker" / "1 böcker")

### 1.1 [P1] "boker" istället för "böcker" — felaktig svensk pluralbildning

Sju ställen i JS bygger plural med strängkonkatenering:

```javascript
bookCount + ' bok' + (bookCount !== 1 ? 'er' : '') + ' valda'
// → 1 → "1 bok valda"   (bör vara "1 bok vald")
// → 2 → "2 boker valda" (bör vara "2 böcker valda")
```

Svensk plural av *bok* är *böcker* (ö-omljud), inte *boker*. Visas i
batch-wizardens header ("3 boker valda"), batch-bar, samt
raderings-bekräftelser.

Filer/rader:
- `app/static/js/selection.js:97` — batch-bar count
- `app/static/js/selection.js:247` — bulk-delete completion toast
- `app/static/js/batch.js:114, 145, 1385, 1909, 1974, 2011` — batch wizard header, group counts, delete confirm, completion msg

Lösningsförslag: använd de befintliga i18n-nycklarna `bookSingular`
("bok") och `bookPlural` ("böcker") från `window.__colophonConfig.i18n`,
samt rätt particip ("vald" / "valda").

### 1.2 [P2] Serievyn säger alltid "böcker" — även för 1-boks-serier

`series-view.js:160, 263` använder `_i18n.seriesBooks` ("böcker") utan
plural-agreement. Resultat: kort som säger "1 böcker" (376 träffar via
Playwright). Bör vara "1 bok" för enstaka.

Lösning: `count === 1 ? bookSingular : bookPlural`.

### 1.3 [P2] Hard-codade "0" i i18n-strängar

```
dupConfirmDeleteMany: "Radera 0 filer? Detta kan inte ångras."
dupCouldNotDelete:     "Kunde inte radera 0 fil(er)."
```

Bör vara `{count}`-placeholder. Visas troligen i bekräftelse-dialoger
för dubblettsraderingar.

---

## 2. Topbar och toolbar

### 2.1 [P3] Logon har vit ram i mörkt tema

Colophon-logon ligger i en vit kvadrat med ljusgrå ram och sticker ut
hårt mot mörkgrå bakgrund i dark mode. Övriga komponenter har anpassat
sig. Förslag: gör logo-bilden transparent, alt. tona ramen i ett
mörktema-värde.

### 2.2 [P2] Ikon-knappar saknar `aria-label`

Fyra synliga ikon-only knappar (`#groupToggle`, `#filterToggle`,
`#actionsMenuBtn`, theme-toggle) har bara `title` — `title` läses inte
upp som primärt knappnamn av skärmläsare. Lägg till
`aria-label="Åtgärder"` etc.

### 2.3 [P3] Topbar har tre ikon-only knappar i klunga

`Gruppera format` + `Filter` + `Åtgärder` ligger direkt efter varandra
utan visuell separation, alla med samma stil. Svårt att skanna för en
ny användare. Förslag: gruppera Filter och Åtgärder visuellt eller ge
dem mikrokopia bredvid ikonen i bredare vy.

### 2.4 [P2] EN/SV-länkar har `href="#"`

Språkbytet är semantiskt fel som länkar med `#`-href — knappar är mer
korrekt eftersom de inte navigerar. Skapar också utilskräp i historiken
vid klick.

---

## 3. Tabellvyn

### 3.1 [P1] "PUBLICERAT"-kolumnens header trunkeras

`scrollWidth=97 > clientWidth=90` → header blir "PUBLICERA". Visas
omedelbart i grundvyn. Fix: öka kolumnens min-width, eller använd
ellipsis med tooltip.

### 3.2 [P2] Inkonsekvent klickyta per rad

Cells 1–5 (omslag, titel, författare, genre, publicerat) har
`cursor: pointer` och öppnar modalen. **Cells 6 (status) och 7 (filtyp)
har `cursor: auto` och gör inget när man klickar**. Klickar man på
"EPUB" eller status-badgen får man ingen feedback. Antingen gör hela
raden klickbar eller markera de icke-klickbara cellerna visuellt.

### 3.3 [P2] "Sparad" + "Har metadata" — två identiska gröna badges

Båda har `background: rgb(209,250,229); color: rgb(6,95,70)` och samma
storlek. Av 376 rader har 138 båda, 221 bara "Har metadata", 8 bara
"Saknar metadata + Sparad", 9 bara "Saknar metadata". Statusarna är
semantiskt oberoende men ser identiska ut. Föreslagen polering:
- "Sparad" som mindre disk-ikon (💾) eller ren visuell prick
- olika nyans / olika fyllning
- eller kombinera till ett tillstånd: "Sparad ✓ · Komplett ✓" i kompakt
  layout

### 3.4 [P3] Genre-cell wrappar till många rader

Långa genre-listor (t.ex. boken *1968* med 7 genrer) gör radhöjden
oförutsägbar. Övervägning: trunkera till första 3 genrer + "+4 till" om
det finns fler, med tooltip för fullständig lista.

### 3.5 [P3] "Filtyp"-kolumnen är överdimensionerad

Cellinnehållet är alltid en 3-bokstavs förkortning (EPUB/PDF/MOBI),
men kolumnen får 200+px bredd. Smal chip + center-justering räcker.

### 3.6 [P3] `\n`-whitespace i cellinnehåll

`textContent` i cell 3 innehåller `"12|21|12\n                  "` —
visuellt påverkar det inte mycket men adresserar
accessibility-snapshot-renderingar och CSV-export framöver. Trim i
templaten.

---

## 4. Hyllvyn

### 4.1 [P2] Inga lässtatus-indikatorer på hyllvy-kort

`data-read-status` finns på kortet (`ReadyToRead`, `Reading`,
`Finished`) men ingen visuell markör visas. Användaren kan inte se i
hyllvyn vilka böcker som är utlästa. Föreslagen polering: liten kant
eller hörn-badge i en av färgerna (oläst/läser/utläst).

### 4.2 [P1] Cover-bilder har tom alt-text i hyllvy

375 cover-bilder, alla med `alt=""`. Skärmläsare hoppar över dem
helt. Bör vara `alt="Omslag: {title} av {author}"`. (Tabellvyn har alt
korrekt.)

### 4.3 [P3] Inget tomt-tillstånd om filter ger 0 träffar

Vid sökning som inte matchar något — visas inget. `noBooksMatch` finns
i i18n men kopplingen är osäker. Behöver verifieras manuellt.

---

## 5. Serievyn

### 5.1 [P2] Density-toggle (Kompakt/Luftig) syns i serievyn men är `pointer-events: none`

Knapparna har `opacity: 1`, ser fullt klickbara ut, men reagerar inte
vid klick. Bör antingen döljas eller fadas (opacity 0.4).

### 5.2 [P3] Serie-cover använder bara första bokens omslag

Visuellt bra default, men om bok #1 saknar omslag visas placeholder
även om #3 har omslag. Möjlig polering: använd första tillgängliga
omslag i serien.

### 5.3 [P3] Inga lässtatus-indikatorer i serie-modalens boklista

Varje bok visar bara titel + författare + status-badge. Inget
visuellt avstånd mellan utlästa och olästa. Kan kombineras med 4.1.

---

## 6. Bokmodalen

### 6.1 [P1] Modalen visar ingen titel i headern

Bokens titel är endast i fält-inputen — modal-headern har bara
delete-ikon och × i hörnen. Användaren ser inte vilken bok som är
öppen utan att skrolla in i formuläret. Lägg en `<h2>` med boktiteln
överst i modalen (nuvarande `<h1>` finns redan men är inte visuellt
placerad där).

### 6.2 [P1] "Spara" är `outline`-stylad — sekundär — istället för primary

`#modalSaveBtn` har `class="btn outline"`. `#modalFetchBtn` ("Hämta
metadata") är `class="btn primary"`. Spara borde vara den primära
konklusiva handlingen i en redigeringsmodal. Föreslagen rotation:
- **Spara** → primary
- Hämta metadata → secondary (action-button)
- Fråga AI → ai-ghost (samma)
- Stäng → ghost (samma)

### 6.3 [P2] Genre-display + genre-input duplicerar varandra

`#modalGenresDisplay` (chips) längst upp y=157, `#modalGenres` (input
med kommaseparerade strängar) längst ned y=648. Användaren ser samma
information två gånger. Polering: gör chips redigerbara (klick för att
ta bort, plus-knapp för att lägga till) och dölj input-fältet.

### 6.4 [P2] "Markera som utläst manuellt" är ovanligt lång knapp-text

Knappen är ~250px bred och tar mer plats än andra primary actions.
Förkortning: "Markera som utläst" (eller bara "Utläst"). "Manuellt"
kan flyttas till en mindre hjälp-text.

### 6.5 [P3] Hard-coded svenska i `_modalI18n` (noterat redan i REFACTOR.md §8)

Redan på todo. Inkluderar bl.a. fasta strängar för read-status. Bör
hämtas från config-bridge.

### 6.6 [P3] Engelsk text läcker i tooltip-attribut

- `#modalEditToggleBtn` har `title="Edit metadata"` (engelska)
- `#seriesModalTableBtn` har `title="View this series in the table"`
  (engelska, även när UI är på svenska)

---

## 7. Dubblettmodal

### 7.1 [P2] Filsökvägar visas tekniskt

Varje bok i ett dubblettpar visar full sökväg (`/books/Year's Best
SF/...epub`). Detta är användbart för debugging men distraherande för
det grundläggande flödet "är det här samma bok?". Förslag: dölj
sökvägen bakom en "visa detaljer"-toggle, eller visa bara mappnamn +
filnamn.

### 7.2 [P3] Inget jämförelse-läge för osäkra dubbletter

Vid 94% match-träff vore det användbart att se metadata sida-vid-sida
(titel, författare, ISBN, sidantal). Just nu får man bara
filinformation. Nice-to-have.

---

## 8. Batch-wizard

### 8.1 [P1] "3 boker valda" — samma plural-bugg som 1.1

Visas direkt i wizard-headern (`batch.js:114, 145`).

### 8.2 [P2] "Titel" och "Författare" är obockade som standard

Med "Hämta metadata" är det vanligtvis dessa två fält man vill
synkronisera. Defaulten gör det mindre upptäckbart vad wizarden gör.
Övervägning: bocka i alla *non-destructive* fält som standard.

### 8.3 [P3] Step 4 heter "Klart" — bör vara "Klar"

Subtilt — *klart* är neutrum (när något *är klart*), men det stega
processen heter konventionellt "Klar" på svenska (kort för "färdig
steg"). Inte fel språkligt men inkonsekvent med andra steg ("Välj
fält", "Sökning", "Granska") som är substantiv/imperativ.

---

## 9. Footer + paginering

### 9.1 [P3] Status-rad blandar olika datatyp utan tydlig separator

```
376 böcker · 17 ej kompletta · 372 EPUB, 4 PDF · 14 osynkade
```

Komma mellan EPUB och PDF men `·` mellan övriga grupper. Polera till
genomgående `·`. Filtyp-grupperna kan också chip-as.

### 9.2 [P3] "Visa: 20 per sida" — selectbox utan tooltip om vad "Alla" betyder

Vid 1000+ böcker kan "Alla" vara dyrt. Förslag: lägg till varning
eller tooltip ("Kan vara långsamt med många böcker").

### 9.3 [P3] Pageringen visar pagineringsknappar 1, 2, …, 19, › men ingen "Snabbhopp till sida"

Vid 19 sidor är detta okej. Nice-to-have framöver: input för
"gå till sida N" eller `Page Down`-tangentstöd.

---

## 10. Tema och tillgänglighet

### 10.1 [P1] 291 av 654 cover-bilder har tom alt-text

Cover-bilder utan `alt` är osynliga för skärmläsare. Tabellvyns
omslag har alt korrekt, men hyllvy/serievyn har tomt. Bör vara
`alt="{title}"` (titel räcker — *omslag* är underförstått av kontext).

### 10.2 [P1] Inga `:focus-visible`-stilar på knappar och tabellceller

`grep -c "focus" bulk_metadata.css` → endast 6 träffar, alla för
`<input>:focus`. Knapparna och klickbara `<td>`-celler har ingen
synlig fokusring vid tangentbordsnavigering. Behöver `:focus-visible`-
regler globalt.

### 10.3 [P2] Två `<h1>` samtidigt i DOM (när modaler är dolda men finns)

`#bookModal h1` ("1968") och `#seriesModal h1` ("Ascension Series")
existerar parallellt i DOM (bara en visas i taget). För
skärmläsar-stöd är detta ok men för dokumentstruktur saknar själva
sidan ett `<h1>` (titel "Colophon" är en `<a>`). Lägg till en visuellt
gömd `<h1>` ("Bibliotek") för sidan.

### 10.4 [P2] Tom `<h2>` i DOM

En av de fem rubrikerna har tom text. Verkar vara serie-modalens
placeholder innan en serie öppnas. Bör fyllas dynamiskt eller hållas
utanför DOM tills den behövs.

### 10.5 [P3] Statusbadges använder färg som enda signal

"Har metadata" (grön) vs "Saknar metadata" (röd/orange). Person med
färgblindhet ser inte skillnaden. Komplettera med ikon (✓ / ⚠).

---

## 11. Mikrokopia och i18n-konsekvens

### 11.1 [P3] "Lässtatus" som rubrik vs "Status" som kolumn

Bokmodalens panel heter "Lässtatus" men tabellens kolumn heter bara
"Status". Tabellkolumnen visar dock *metadata-status* (har/saknar),
inte lässtatus. Tvetydigt. Förslag: byt kolumnnamn till
"Metadata" eller "Komplett".

### 11.2 [P3] "Sök" som verb vs "Sök" som substantiv

Searchbox + `placeholder="Sök titel, …"` + `Sök`-knapp i batch-wizard
+ `Sök omslag`-knapp i bokmodal. Verb-användning är genomgående bra
men kollar gärna att tonen är konsekvent (imperativ "Sök X" eller
"Sök efter X").

### 11.3 [P3] "Hämta metadata" vs "Sök metadata"

Bokmodalen säger "Hämta metadata", batch-wizardens primary heter "Sök".
Båda gör mer eller mindre samma sak (sök externa källor). Föreslagen
harmonisering till "Hämta" överallt, eller "Sök & hämta metadata".

---

## 12. Sammanfattande prioriteringslista (för en framtida session)

| # | Område | Fix | Prio |
|---|--------|-----|------|
| 1.1 | "boker" → "böcker" i 7 JS-rader | använd `bookSingular`/`bookPlural` | P1 |
| 1.2 | Serievyn "1 böcker" | plural-agreement | P2 |
| 1.3 | i18n hard-coded "0 filer" | placeholders | P2 |
| 3.1 | "PUBLICERAT" trunkeras | öka min-width | P1 |
| 3.2 | Status-cell + filtyp-cell ej klickbar | konsekvent klickyta | P2 |
| 4.2 / 10.1 | 291 covers utan alt | dynamic alt från title | P1 |
| 5.1 | Density-toggle visuellt aktiv i serievyn | fade eller dölj | P2 |
| 6.1 | Bokmodal saknar titel i header | h2 med boktitel | P1 |
| 6.2 | "Spara" är secondary-styled | byt till primary | P1 |
| 6.6 | Engelska tooltip-strängar | översätt | P3 |
| 8.1 | Batch-wizard plural-bugg | se 1.1 | P1 |
| 10.2 | Inga `:focus-visible`-stilar | global fokusring | P1 |
| 2.1 | Logo med vit ram i dark mode | transparent | P3 |

---

## Skapat av

Playwright MCP audit 2026-05-24. Screenshots i samma mapp
(`docs/ux-audit/`): `ux-01-header.png` … `ux-10-mobile.png`. Säg till
om du vill att jag fixar specifika punkter i en följande session.
