# Uppdrag — läsarfunktioner att hämta från Bookstation (sök, zoom, mörk PDF, sidinput)

**Till:** den Claude-instans som arbetar i Colophon.
**Från:** Bookstation-sidan. Vi jämförde de två läsarna (2026-07-29) inför
att Bookstation portade ERT dragreglage + snapback till sin PDF-läsare
(Bookstation v0.20.0). Jämförelsen gick åt båda hållen: Colophons läsare
saknar fyra saker Bookstation har byggt och användartestat. Det här är
kartan för att hämta hem dem.

> ## Referensimplementationen finns på disk
>
> Bookstation ligger som systermapp: `../bookstation`
> (absolut: `/home/christian/Dokument/Github/bookstation`).
>
> - **Referens-commits**: `0cb0312` ("In-book search for EPUB and PDF
>   readers" — hela sökfunktionen), `c80f4e5` (den fristående PDF.js-
>   läsaren med zoom/fit), tag `v0.20.0` (reglage+snapback-porten åt vårt
>   håll — bra att läsa för att se hur vi anpassade ER kod, plus
>   wasm-URL-fallgropen nedan).
> - **Kärnfiler**: `app/static/js/reader_common.js` (`SearchUI` —
>   delad sökpanel med träffutdrag), `app/static/js/reader_pdf.js`
>   (PDF-sök via sidvis textextraktion, zoomlägen, mörk canvas-
>   invertering, sidinput), `app/static/js/reader_epub.js` (foliate-
>   sökintegrationen), `app/templates/reader_pdf.html` +
>   `reader_base.html` (kontrollradens markup).
>
> Läs Bookstations kod som **referens, inte facit** — och OBS den stora
> arkitekturskillnaden: Bookstation har en FRISTÅENDE PDF.js-läsare,
> medan ni renderar PDF genom foliate. Allt PDF-specifikt nedan måste
> anpassas in i er enhetliga läsare, inte kopieras rakt av.

---

## De fyra funktionerna

1. **Sökning i boken (störst värde — ni har ingen alls).** Bookstations
   `SearchUI` (reader_common.js) är en delad panel: sökfält, träfflista
   med utdrag (kontext före/efter, träffen markerad), klick hoppar till
   träffen. Två backends bakom samma UI:
   - EPUB: foliates inbyggda sök-API (ni har redan motorn — bara UI:t
     saknas).
   - PDF: sidvis textextraktion via pdf.js `getTextContent()`, med
     träfftak (200) och utdragsradie (±50 tecken). Er foliate-PDF-adapter
     sitter ovanpå samma pdf.js — verifiera vad den exponerar innan ni
     väljer väg.

2. **Zoomkontroller för PDF/fixed-layout.** In/ut i 1.25×-steg (0.25–5×)
   plus en fit-toggle (anpassa bredd ↔ anpassa hel sida). I Bookstation
   räknas skalan om mot containerns mått och renderas med
   devicePixelRatio-medvetenhet (skarpt på hidpi). I er foliate-värld är
   motsvarigheten sannolikt en transform/viewport-skalning på
   fixed-layout-vyn — utred foliates API först.

3. **Mörkt läge som inverterar själva PDF-sidan.** Er temaforcering gäller
   flödande text — en vit PDF-sida förblir vit och bländande i mörkt
   tema. Bookstations lösning är ett CSS-filter på render-ytan:
   `invert(0.88) hue-rotate(180deg)` (hue-rotate:en gör att färger inte
   blir negativ-psykedeliska). Trivialt att applicera på er PDF-yta;
   koppla till samma temaväxlare som texten.

4. **Direkt sidinput.** Ett litet nummerfält ("247" + Enter) bredvid ert
   reglage — reglaget är bäst för "ungefär där", inputen när man VET
   sidan (referenser, index, "fortsätt på s. 312"). Billigast av allt:
   ett `<input type=number>` + goTo.

## Fallgrop vi hittade — särskilt relevant för er

**pdf.js `wasmUrl` måste vara ett katalogprefix som slutar på `/` — och
får ALDRIG få query-string.** Bookstation lade (0.16.0) cache-busting
(`?v=<version>`) på alla statiska URL:er; suffixet hamnade även på
wasm-katalogen och pdf.js vägrade då öppna NÅGRA dokument alls ("Invalid
factory url: … must include trailing slash"). Buggen låg obemärkt i fyra
versioner. Ni vendrade samma wasm-upplägg (er v1.31.1) — om ni någonsin
inför cache-busting eller andra URL-transformer på static: undanta
wasm-katalogen, eller strippa query-delen innan den når `getDocument`.

## Bytesbalansen (för sammanhang)

Åt andra hållet portade Bookstation just ert scrub-reglage + snapback
(v0.20.0) med era tre designbeslut bevarade: navigera först vid släpp
(PDF-sidor ska inte renderas om per pixel), riktiga sidnummer i
etiketten för fixed-layout, snapback-chip som städar sig själv när man
är tillbaka vid utgångspunkten. En avvikelse värd att känna till: för
flödande EPUB behöll Bookstation live-seek under draget (er
släpp-navigering är en PDF-kostnadsoptimering; flödande text tål seek)
— snapback-utgångspunkten fångas därför vid dragets START, inte släpp.

## Leveranskriterium

(1) Sök i en flödande EPUB → träfflista med utdrag, klick hoppar och
markerar; (2) sök i en PDF → samma UI, träffar per sida; (3) zoom in/ut +
fit-toggle på en PDF utan att skärpan försämras på hidpi; (4) mörkt tema
→ PDF-sidan inverteras behagligt (testa en PDF med färgbilder);
(5) sidinput hoppar direkt och reglaget/etiketten följer med;
(6) regression: era befintliga scrub/snapback/restart-flöden opåverkade.
