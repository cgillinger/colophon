# Colophon — Handbok

*English version: [handbook-en.md](handbook-en.md)*

Den här handboken förklarar allt Colophon kan göra, i den ordning du oftast
stöter på det. Läs den från början första gången, eller använd indexet nedan för
att slå upp en sak — *Hur delar jag en bok? Varför synkar inte min Kobo? Vad är
en "preliminär" författare?*

> Colophon är en självhostad webbapp som förvandlar en mapp med e-boksfiler till
> ett städat, bläddringsbart bibliotek, fyller på metadata, och synkar hela
> alltihop till en Kobo-läsplatta över WiFi. Ett bibliotek, flera sätt att se
> det på.

## Index

1. [Första anblicken: skärmen](#1-första-anblicken-skärmen)
2. [De tre biblioteksvyerna](#2-de-tre-biblioteksvyerna)
3. [Hitta böcker: sök, filter, sortering](#3-hitta-böcker-sök-filter-sortering)
4. [Lägga till böcker](#4-lägga-till-böcker)
5. [Öppna och redigera en bok](#5-öppna-och-redigera-en-bok)
6. [Få bra metadata](#6-få-bra-metadata)
7. [AI-funktioner](#7-ai-funktioner)
8. [Omslag](#8-omslag)
9. [Många böcker på en gång: batchåtgärder](#9-många-böcker-på-en-gång-batchåtgärder)
10. [Hantera författare](#10-hantera-författare)
11. [Hitta och rensa dubbletter](#11-hitta-och-rensa-dubbletter)
12. [Läsa i webbläsaren](#12-läsa-i-webbläsaren)
13. [Lässtatus och läsläge](#13-lässtatus-och-läsläge)
14. [Dela en bok (ge bort den)](#14-dela-en-bok-ge-bort-den)
15. [Trådlös Kobo-synk](#15-trådlös-kobo-synk)
16. [Synka till ett uppströmsbibliotek](#16-synka-till-ett-uppströmsbibliotek)
17. [Inställningar](#17-inställningar)
18. [Installera som app (PWA)](#18-installera-som-app-pwa)
19. [Språk och tema](#19-språk-och-tema)
20. [Ordlista](#20-ordlista)

---

## 1. Första anblicken: skärmen

När du öppnar Colophon landar du i ditt **bibliotek**. Skärmen har två bestående
delar:

- **Sidomenyn** (till vänster på dator; **☰-knappen** uppe till höger på
  mobil/platta). Den är grupperad i:
  - **Vyer** — hur det aktuella biblioteket visas (Tabell / Hyllvy / Serie).
  - **Verktyg** — *Ladda upp böcker*, *Sök nya böcker*, *Hitta dubbletter*,
    *Författare*, *Kobo-synk*, *API-inställningar*, *AI-inställningar*, och
    *Synka till bibliotek* (visas bara när du har lokala ändringar att skicka
    uppströms).
  - **Läsning** — filtrerade vyer av samma bibliotek: *Alla*, *Oläst*, *Läser*,
    *Läst*, var och en med en live-räknare.
- **Topbaren** — språk (EN/SV), ljus/mörk-tema, och på små skärmar menyknappen.

Allt är *ett* bibliotek; sidomenyn ändrar bara vad du tittar på eller vad du gör
med det.

## 2. De tre biblioteksvyerna

Växla mellan dessa under **Vyer**. De visar samma böcker, ordnade för olika
ändamål.

- **Tabell** — ett sorterbart, filtrerbart kalkylark över din metadata. Bäst för
  kurering: du ser titel, författare, serie, språk och lässtatus på en gång, och
  det är här *Läser nu*-korten dyker upp (se §13).
- **Hyllvy** — en vägg av omslag, som en bokhylla. Bäst för att bläddra och för
  att läsa: omslagsbrickor visar läsprogress, och en nyss tillagd bok bär en
  **Nytillagt**-bricka ett par veckor. Tryck på ett omslag för detaljer — och det
  är härifrån **Läs**-knappen (webbläsarläsaren) nås.
- **Serie** — böcker grupperade per serie, i läsordning. Bäst för att se vad du
  har och vad som saknas i en serie.

Vald vy, sökning och filter sparas i sidans adress, så webbläsarens
**Bakåt**-knapp och bokmärken fungerar som du förväntar dig.

## 3. Hitta böcker: sök, filter, sortering

- **Sök** — sökrutan matchar titel, författare och serie medan du skriver.
- **Filter** — smalna av listan på språk, lässtatus med mera. **Läsning**-gruppen
  i sidomenyn (*Alla / Oläst / Läser / Läst*) är snabbaste sättet att filtrera på
  hur långt du kommit.
- **Sortering** — ordna på titel, författare, tillagd-datum (*Senast tillagt*
  lyfter dina nyaste böcker) och andra fält.
- **Sidindelning** — långa bibliotek delas i sidor; omslag laddas allteftersom du
  skrollar så att första skärmen är snabb även på en platta över WiFi.

## 4. Lägga till böcker

Det finns två sätt att få in böcker i Colophon.

- **Ladda upp böcker** (Verktyg → *Ladda upp böcker*) — välj filer, eller bara
  **dra och släpp** dem var som helst i fönstret. De laddas rakt in i ditt
  bibliotek; ingen omskanning behövs. Bra för att lägga till en handfull böcker
  från enheten du sitter vid.
- **Sök nya böcker** (Verktyg → *Sök nya böcker*) — skannar bokmappen på servern
  efter nytt eller ändrat och läser dess inbäddade metadata. Använd detta när du
  kopierat in filer i mappen på annat sätt. Förloppet strömmar live medan det
  kör.

Format som stöds: **EPUB, MOBI, AZW3, KEPUB, PDF, CBZ, CBR**.

**Formatgruppering.** Har du samma bok i flera format (säg EPUB + MOBI) grupperar
Colophon dem som **en** bibliotekspost, så hyllan inte fylls med dubbletter av
samma titel. Metadata-åtgärder gäller hela gruppen.

Nyss tillagda böcker bär en **Nytillagt**-bricka ett tag (14 dagar som standard)
så du ser vad som precis kommit in.

## 5. Öppna och redigera en bok

Klicka på en bok (en rad i Tabell, ett omslag i Hyllvy) för att öppna dess
**detaljer**. Härifrån kan du:

- **Redigera fälten** — titel, författare, serie och position, beskrivning,
  förlag, språk, ISBN, genrer, utgivningsdatum. Klicka **Spara** för att skriva
  ändringarna. Att spara skriver också metadatan **tillbaka in i e-boksfilen**,
  så andra verktyg (Komga, Kavita, din Kobo) ser samma data.
- **Ditt betyg** — ge boken ditt eget betyg 1–5. Detta är *ditt* betyg, hämtas
  aldrig någonstans ifrån.
- **Läsläge** — se och sätt hur långt du läst (se §13). *Markera som läst* sätter
  den klar för hand; *Återställ läsläge* nollställer.
- **Radera** — papperskorgen tar bort boken. Radering kan även ta bort filen från
  disk, så den frågar först. Betrakta det som permanent.

**Skydda dina ändringar.** När du kurerat en bok för hand respekterar Colophon
det: automatisk berikning skriver inte tyst över din text, och ett omslag kan
**låsas** så det aldrig byts. Ditt handarbete vinner.

## 6. Få bra metadata

Colophon kan fylla i saknade uppgifter från flera onlinekällor och slå ihop dem
smart.

- **Hämta metadata** (i en boks detaljer) slår upp boken, poängsätter
  kandidaterna, och antingen tillämpar en säker träff eller visar en
  **förhandsgranskning** att godkänna. Sammanslagningen sker **fält för fält** —
  bästa värdet per fält vinner, och Colophon minns var varje värde kom ifrån.
- **Källor** (alla kan slås av/på i *API-inställningar*):

  | Källa | Bra för |
  |---|---|
  | Inbäddad fil | Titel/författare/serie redan i filen — högt förtroende först |
  | Google Books | Titel, författare, beskrivning, ISBN, kategorier |
  | Hardcover | Serie, genrer, synopsis, betyg — stark för populära engelska titlar |
  | Open Library | Ämnen, synopsis, ISBN — stark för äldre/obskyra titlar |
  | Wikidata | Strukturerad serie **och position i serien**, genre, datum |
  | Wikipedia | Snabb beskrivning och ett reservomslag (miniatyr) |
  | LIBRIS (KB) | Sveriges nationalbibliografi — auktoritativ svensk data |
  | Calibre | "Djup"-nivå via Calibres egna plugins (Goodreads m.fl.) |

- **Sökdjup.** När du hämtar (särskilt i batch) kan du välja hur hårt det ska
  leta — en snabb svep över de snabba källorna, eller en djupare sökning som tar
  med de långsammare.

## 7. AI-funktioner

AI är valfritt och körs bara när du ber om det. Konfigurera en leverantör i
**AI-inställningar** först (Mistral, OpenAI, DeepSeek, eller en lokal Ollama — se
§17).

- **Fråga AI** (i en boks detaljer) — när de vanliga källorna inte kan fastställa
  en boks **serie** och position kan AI lista ut det. Den föreslår; du granskar
  och godkänner.
- **AI-författarkoll** (på Författare-sidan) — för två namn som ser ut att vara
  samma person kan AI råda om de verkligen är det. Endast rådgivande — du
  bestämmer.
- **Användningsstatistik** — *AI-inställningar* visar hur många tokens du
  förbrukat, så inga överraskningar på en mätt plan.

## 8. Omslag

- **Hitta ett omslag** — öppna en bok och slå upp omslagsbilder. Colophon söker i
  **Open Library, Google Books, Hardcover, Wikidata/Commons** och **DuckDuckGo**
  och visar kandidaterna att välja bland.
- **Låsa ett omslag** — när du är nöjd med ett omslag, lås det så att berikning
  och omskanningar aldrig byter det.
- Omslag sparas från filen och cachas i visningsstorlek, så katalogvyerna hålls
  snabba.

## 9. Många böcker på en gång: batchåtgärder

Markera flera böcker (kryssa dem i Tabell, eller flervalsmarkera) och öppna
**Batchåtgärder** för att berika dem alla i en körning.

1. **Välj vad som ska fyllas** — t.ex. *Grundinfo*, *Beskrivning* och andra
   fältgrupper. Kryssa bara det du vill röra.
2. **Välj sökdjup** och om befintliga värden ska **skrivas över**, samt ett
   **maxantal** böcker för körningen.
3. **Kör** — förloppet strömmar medan det jobbar; når det ditt max stannar det
   och säger åt dig att köra igen för nästa omgång.
4. **Granska sammanfattningen** — en prydlig rapport över vad som sparades och
   eventuella filer det inte kunde skriva tillbaka till.

Samma guide kan köra omslagssökning och AI över ett urval. Batchåtgärder ändrar
många böcker samtidigt, så de bekräftar alltid innan de skriver.

## 10. Hantera författare

Colophon håller **en kanonisk post per författare**, så varje bok av samma person
märks likadant — även när filerna stavar namnet olika ("J.R.R. Tolkien" /
"Tolkien, J.R.R." / "JRR Tolkien" blir alla en författare).

- **Författarfältet** i en boks detaljer är kopplat till registret: börja skriva
  så föreslår det befintliga författare, så att du återanvänder en post i stället
  för att skapa en nästan-dubblett.
- **Författare-sidan** (Verktyg → *Författare*) är där du kurerar registret:
  - **Bekräfta** preliminära poster — filtrera till obekräftade, kryssa flera,
    bekräfta dem i ett svep. Snabbaste sättet att städa efter en skanning.
  - **Byt namn** eller **Slå ihop** — båda kaskaderar och märker om varje länkad
    bok i ett svep.
  - **Verifiera** mot Wikidata för att förankra en författare med auktoritets-id
    (QID, VIAF, LIBRIS).
  - För troliga dubblettpar, slå ihop med ett klick, eller **Fråga AI** om de är
    samma person.

Varje författare har en **status** som styr om namnet skrivs in i dina filer:

| Status | Betyder | Skrivs till filer? |
|---|---|---|
| Preliminär | Auto-skapad från filmetadata vid skanning/uppladdning | Nej — bara databas |
| Bekräftad | Du bekräftade stavningen | Ja |
| Auktoritetslänkad | Verifierad mot Wikidata | Ja |

Preliminära poster skrivs aldrig in i filer förrän du bekräftar dem, så en
auto-gissad stavning kan inte tyst skriva om ditt bibliotek.

## 11. Hitta och rensa dubbletter

**Hitta dubbletter** (Verktyg) söker efter böcker som ser ut att vara samma titel
(luddig matchning, så den fångar nästan-träffar) och visar kandidatparen för dig
att granska och städa. Inget raderas utan ditt godkännande.

## 12. Läsa i webbläsaren

Colophon har en inbyggd EPUB-läsare — ingen app behövs.

- **Öppna den** från en boks detaljer i **Hyllvy**: tryck **Läs** (endast EPUB).
- **Bläddra** genom att trycka på vänster/höger kant, eller med piltangenterna.
- **Läsinställningar** (**Aa**-knappen) låter dig justera:
  - **Tema** — Ljus, Sepia, Mörk.
  - **Textstorlek**, **Typsnitt** (förlagets eget, Serif, Sans, eller ett
    **dyslexivänligt**), **Radavstånd**, **Marginaler**.
  - **Läsläge** — Bläddra (tryck för att vända) eller Rulla.
  Dessa kommer ihåg mellan böcker.
- **Spara offline** (nedladdningsikonen) cachar boken så att du kan läsa utan
  uppkoppling; din progress sparas lokalt och synkas igen när du är online. *Kräver
  en säker (HTTPS) anslutning* — se §15 om att servera via Tailscale.

Din läsposition sparas automatiskt och **synkar med din Kobo** (se §13).

## 13. Lässtatus och läsläge

Lässtatusen är en enda gemensam sanning, oavsett om du läser på Kobon eller i
webbläsaren. Varje bok är *Oläst* (Redo att läsa), *Läser*, eller *Läst*, plus en
procentuell progress.

- **Var du ser det:** **Läsning**-filtren i sidomenyn (med räknare),
  omslagsbrickorna i **Hyllvy**, **Läsläge**-rutan i en boks detaljer, och
  korten **Läser nu** / **Återuppta?** högst upp i **Tabell**-vyn — *Läser nu*
  tar vid där du nyligen slutade; *Återuppta?* påminner om böcker du börjat men
  glidit ifrån (var och en kan avfärdas).
- **Hur det synkar:** läsning på Kobon uppdaterar Colophon vid nästa synk, och
  läsning i webbläsaren rider samma kanal tillbaka till Kobon. Progress rör sig
  bara **framåt** — en snabb "titt" på en enhet kan inte radera hur långt du
  faktiskt läst på en annan. Status rör sig bara framåt också (en läst bok förblir
  läst); för att läsa om, använd *Återställ läsläge*.
- **Obs:** exakt sidsynk fungerar mellan Kobo-läsningar av samma bok;
  webbläsarläsaren återupptar på **procent**, eftersom en webbläsare och en Kobo
  beskriver positioner på olika sätt. De tekniska detaljerna (och felsökning)
  finns i [`kobo-reading-state-sync.md`](kobo-reading-state-sync.md).

## 14. Dela en bok (ge bort den)

Du kan räcka över en DRM-fri EPUB till någon på plats — *"du kan få den av mig"* —
direkt från läsaren.

- **Var:** öppna boken i läsaren (Hyllvy → **Läs**); i läsarens topbar sitter
  **dela**-ikonen (mellan offline-nedladdningen och **Aa**).
- **Vad som händer:** Colophon räcker EPUB:en till telefonens vanliga dela-meny —
  **AirDrop, Snabbdelning, Meddelanden, mejl** — och din vän får filen direkt.
  Inga konton, inget exponerat mot internet.
- **När det inte går** förklarar knappen varför i stället för att tyst misslyckas:
  - **DRM** — en kopieringsskyddad bok kan inte delas (mottagaren skulle ändå
    inte kunna öppna den).
  - **Inte en säker anslutning** — delning kräver HTTPS; öppna Colophon via din
    Tailscale-`https://…`-adress i stället för den vanliga `http://`-LAN-adressen.
  - **Webbläsare utan fildelning** (t.ex. desktop-Firefox) — den faller tillbaka
    till en vanlig nedladdning så att du kan skicka filen själv.

## 15. Trådlös Kobo-synk

Detta pekar en Kobo-läsplatta mot Colophon som om det vore Kobos egen butik: ditt
bibliotek, omslag och titlar dyker upp på enheten, du trycker för att ladda ner,
och läsprogress synkar åt båda håll över WiFi. Engångsinställning, sen är det
automatiskt.

**Inställningen** är ett kort engångsjobb — steg-för-steg (redigera Kobons
`.conf`, generera en enhets-URL) finns i projektets README under *Setting up Kobo
sync*. I Colophon hanterar du enheter under **Kobo-synk** (Verktyg): lägg till en
enhet, kopiera dess URL (visas en gång), eller återkalla en.

**Bra att veta:**

- Första nedladdningen av varje bok konverterar EPUB → KEPUB i farten (ett par
  sekunder); senare öppningar är direkta.
- **Bara böcker som levererats till Kobon av Colophon synkar sin lässtatus.** En
  bok du sidladdat på Kobon via USB, eller köpt i Kobo-butiken, är ett annat
  exemplar för enheten — dess progress kan inte synka.
- Läsprogress är lokal på enheten tills Kobon faktiskt synkar, så en bok du läser
  offline syns i Colophon först efter nästa synk.

**Felsökning** (mer i README): om inget dyker upp efter en synk är URL:en i
Kobons `.conf` oftast fel; om böcker dyker upp men inte omslag är det
`image_host`/`image_url_template`-raderna (de måste innehålla porten).

## 16. Synka till ett uppströmsbibliotek

Om du har ett "master"-bibliotek någon annanstans — till exempel en Komga-utdelning
— kan Colophon skicka upp de filer det ändrat dit.

- När du redigerat böcker (så att deras filer skiljer sig från uppströms) dyker en
  **Synka till bibliotek**-post upp i sidomenyn med en räknare över väntande filer.
- Att klicka på den visar en **förhandsgranskning** av vad som ska skickas; du
  bekräftar, och det synkar (med rsync under huven). Inget lämnar förrän du
  bekräftar.

Det här håller servern du faktiskt serverar från (Komga/Kavita) i takt med den
metadata och de omslag du kurerat i Colophon.

## 17. Inställningar

Alla inställningar finns i sidomenyn. API-nycklar satta i gränssnittet **vinner**
över miljövariabler.

- **API-inställningar** — nycklar för Google Books, Hardcover m.fl., och reglage
  för att slå av/på enskilda metadata- och omslags**källor**.
- **AI-inställningar** — välj AI-leverantör och modell, klistra in nyckeln, och se
  token-**användning**. Leverantörer: **Mistral** (rekommenderas, generös gratisnivå),
  **OpenAI**, **DeepSeek** (mycket billig), eller **Ollama** (lokal, gratis, ingen
  nyckel).
- **Kobo-synk** — dina registrerade enheter, varje enhets synk-URL, `.conf`-snutten
  att klistra in, och återkalla-kontrollen.
- **Biblioteksägar-etikett** — ett valfritt namn under loggan, så att en
  per-person-instans identifierar sig (sätts via miljövariabeln
  `COLOPHON_LIBRARY_OWNER`).

## 18. Installera som app (PWA)

Colophon är en installerbar webbapp. På mobil eller platta, använd webbläsarens
**Lägg till på hemskärmen**; på dator, **installera**-ikonen i adressfältet. Den
öppnas sen i helskärm som en native-app. (Att installera gör också offline-läsningens
lagring varaktig på iOS.) När en ny version driftsätts visas en liten **Ny version
tillgänglig → Ladda om**-prompt — den avbryter dig aldrig mitt i en redigering.

## 19. Språk och tema

- **Språk** — växla **EN / SV** i topbaren när du vill. (Att lägga till ett tredje
  språk är bara en översättningsfil — se README.)
- **Tema** — sol/måne-knappen växlar **ljus / mörk**. Ditt val sparas på enheten.

## 20. Ordlista

- **Bibliotekspost / grupp** — en bok i ditt bibliotek. Har du flera *format* av
  samma titel är de en post (en "grupp").
- **Inbäddad metadata** — titel/författare/etc. som ligger *inuti* e-boksfilen.
  Colophon läser den först och skriver dina ändringar tillbaka in i den.
- **Berikning** — att fylla i eller förbättra metadata från onlinekällor.
- **Manuell metadata / låst omslag** — en bok du redigerat för hand, eller ett
  omslag du låst, så att automatisk berikning lämnar den ifred.
- **Preliminär / Bekräftad / Auktoritetslänkad författare** — en författares status
  (se §10); bara bekräftade och auktoritetslänkade namn skrivs in i filer.
- **Lässtatus / läsläge** — *Oläst / Läser / Läst* plus en procentuell progress,
  delad mellan webbläsarläsaren och Kobon.
- **KEPUB** — Kobos förbättrade EPUB-format; Colophon konverterar till det i farten
  när en Kobo laddar ner en bok.
- **Uppströmsbibliotek** — ett separat "master"-arkiv (t.ex. Komga) som Colophon
  kan skicka kurerade filer till.
- **PWA** — Progressiv webbapp; en webbplats du kan installera som en app.

---

*Hittade du något inaktuellt, eller en funktion handboken missar? Det är ett
levande dokument — öppna en issue eller en PR.*
