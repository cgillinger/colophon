# Design v2 — obrytbara författarlänkar ("en bok är alltid länkad")

> Status: **DESIGN, ej byggt.** v1 skrevs 2026-07-27 efter Russell-haveriet (omresolvering
> med minne). v2 samma dag efter skärpt krav från användaren: länken ska inte kunna brytas
> av *någon* — inte av berikning, inte av scan, inte av användarens egna redigeringar —
> utan bara flyttas medvetet, och försvinna först när boken raderas. Systemet ska också
> hantera att en författares sista bok raderas. Bygger ovanpå det shippade registret
> (`docs/author-authority-design.md`) och behåller dess järnregel för *sammanslagningar*.

## Invarianten

> 1. **En bok med författarsträng är alltid länkad till exakt en registerpost**, från
>    första resolvering till att boken raderas. Ingen operation lämnar den i limbo.
> 2. Länken **flyttas** bara av: (a) deterministisk matchning när strängen ändras
>    (exakt/signatur/alias), (b) användarens medvetna val i comboboxen, (c) en
>    registersammanslagning. Den **försvinner** bara när boken raderas.
> 3. Osäkerhet uttrycks som **förslag ovanpå en intakt länk** — aldrig som avsaknad
>    av länk.
> 4. När en författares sista bok försvinner: tentativa poster städas bort automatiskt;
>    bekräftade/auktoritetslänkade består som kunskap (med "Inga böcker"-badgen,
>    v1.33.1) och återanvänds när en ny bok av personen dyker upp.

Dagens modell bryter mot allt detta: `review`/`NULL` är *olänkade* tillstånd, och
reset-lyssnaren (`app/models.py:248`) kastar boken dit vid varje strängändring.

## Beviskedjan (prod 2026-06-12, fullständig)

1. **17:06** Sådd. Filens `dc:creator` = **"Russel, Mary Doria"** (efternamn först,
   felstavad med ett l *i filen*; filnamnet har två — förlagsmetadata ≠ filnamn).
   Tentativ post 162 skapades, boken (*The Sparrow*, id 387) länkades.
2. Användaren **döpte om** posten i /authors till "Mary Doria Russel" (bara
   ordningsbyte, stavningen troget bevarad). Fungerade exakt som designat: kaskaden
   märkte om boken med länken intakt, båda stavningarna sparades som alias, posten
   flippades tentativ → `user_confirmed` (rename räknas som bekräftelse,
   `author_resolver.py:rename_author`).
3. **17:11** Berikningen valde rättstavade **"Mary Doria Russell"** (två l), skrev DB +
   fil. Reset-lyssnaren nollade länken. Omresolveringen: ingen exakt/signatur/alias-träff
   (registret kunde bara en-l-formerna), fuzzy ≥ 0.85 → järnregeln → `review`,
   `author_id=NULL`. Boken i limbo, posten föräldralös. Marginalen var **en bokstav**.

Lärdomar: (a) användarens åtgärder var aldrig problemet — kaskaderna fungerar;
(b) felet är att osäkerhet representeras som *bruten länk*; (c) omresolveringen
slänger sin säkraste information (den befintliga länken) och gissar om från den
svagaste (kall strängjämförelse).

## Grundmodellen: sträng och länk är alltid överens

Ny hård regel i datamodellen:

> `item.author` (strängen) är alltid lika med den länkade postens `canonical_name`
> **eller** ett registrerat alias till den.

Därmed kan resolvering aldrig "misslyckas" — värsta fallet är att strängen blir en
**ny tentativ post** (registret speglar då exakt vad som faktiskt står i böckerna),
och osäkerheten blir ett **sammanslagningsförslag mellan två registerposter** i
stället för en olänkad bok:

### Regler när `item.author` ändras (av vem som helst: scan, berikning, fritext)

Lyssnaren slutar nolla. Den markerar `author_status='stale'` och **behåller
`author_id` som minne**. Pending-passet (körs redan direkt efter modal-spar,
`metadata.py:2048`, samt vid scan/upload) avgör:

1. **Exakt/signatur/alias-träff mot någon post** → länka den (ev. samma som förut
   via alias). Deterministisk, som idag. Status `linked`.
2. **Ingen träff** → **skapa/återanvänd en tentativ post för den bokstavliga
   strängen och länka den.** Boken är aldrig olänkad. Sedan:
   - Fanns ett minne (förra länken) och nya strängen fuzzy-matchar (≥ tröskel) den
     mindes posten → registrera ett **högkonfidens-sammanslagningsförslag**
     (ny post ↔ mindes post) och sätt `author_status='review'` på boken.
     Russell-fallet: ny post "Mary Doria Russell" länkad, förslag
     "Russell (1 bok) ↔ Russel (0 böcker)" överst i /authors dublettpanel —
     ett klick, kaskaden slår ihop, aliasen konsolideras. Ignoreras förslaget
     är boken ändå fullt funktionell och rätt märkt.
   - Annars: kall fuzzy mot registret som idag → ev. vanligt dublettförslag.
     Inget minne, ingen träff → bara den nya posten, status `new`.
3. **Tom sträng** → `missing` som idag (avsaknad av författare är inte en bruten
   länk).

**Järnregeln består oförändrad**: inget slås någonsin ihop automatiskt — fuzzy
*föreslår* sammanslagning, användaren klickar. Skillnaden mot idag är att boken
väntar *länkad till sin bokstavliga sträng* i stället för i limbo, och att minnet
gör förslaget träffsäkert (samma boks fält ⇒ nästan säkert samma person).

### Varför detta uppfyller det skärpta kravet

- **Fritext i modalen** kan inte bryta länken: texten blir i värsta fall en ny
  tentativ post som boken länkas till, plus ett förslag. Stavfel = en post till att
  slå ihop, aldrig en försvunnen koppling.
- **Berikning/scan** samma väg. Skannervakten (nedan) tar bort även churnen.
- **Comboboxen** förblir det enda stället där länken *byts medvetet* (sätter
  `author_id` explicit — lyssnarundantaget består).
- **Rename/merge** kaskaderar redan med länkar intakta (bevisat i steg 2 ovan).
- **Radera-knappen i /authors** är redan spärrad för poster med böcker
  (`authors.py:delete`, 409 vid `in_use`) — den enda vägen att bli av med en
  länkad post är att först flytta/radera böckerna. Behålls.

## När sista boken försvinner

Bokradering (UI:t eller scannerns städning av försvunna filer,
`scanner.py:613`) följs av en GC-krok på den övergivna posten:

- `source='tentative'` + 0 böcker → **radera post + alias automatiskt.**
  Autoskapade, DB-only, inget bevarandevärde utan böcker. (Backfill vid deploy
  städar befintliga — "Timescape" försvinner.)
- `user_confirmed`/`authority_linked` + 0 böcker → **behåll.** Posten är kuraterad
  kunskap (stavning, auktoritets-id:n, alias). "Inga böcker"-badgen visar läget,
  papperskorgen finns för användaren. Laddas en ny bok av personen upp länkar
  regel 1 den direkt mot den bevarade posten — registret fungerar som stående
  auktoritetsfil, inte bara som index över nuvarande bestånd.

## Schema

- `library_items.suggested_author_id` (nullable FK) — sammanslagningsförslagets
  motpart, satt av regel 2a; visas i granskningskön och rensas när förslaget
  avgörs (merge eller avvisa). Ersätter dagens "recompute suggestions on demand"
  som *primär* källa (recompute behålls som fallback i comboboxen).
- `author_status`-semantik efter bygget: `linked` (allt väl) · `new` (skapade en
  tentativ post; rensas vid confirm, v1.33.2) · `review` (länkad + öppet förslag) ·
  `missing` (ingen sträng) · `stale` (väntar på pending-pass, transient).
  **`NULL` med icke-tom sträng förekommer inte längre.**

## Skannervakt mot flip-flop

Oförändrad från v1: `upsert_library_item` hoppar över author-överskrivning när
inkommande strängs `variant_key` redan är alias till bokens länkade post (filen
bär en äldre stavning av samma person; DB:ns form vinner tills filen skrivs om
vid nästa metadata-skrivning). Okända strängar skrivs över som vanligt och går
genom reglerna ovan.

## Migration/backfill (idempotent, `database.py`-mönstret)

1. Böcker i limbo idag (`author_status IN ('review') OR (author_id IS NULL AND
   author != '')`): kör reglerna — skapa/länka bokstavlig post, sätt förslag om
   fuzzy-kandidat finns. (Prod: *The Sparrow* → ny post "Mary Doria Russell" +
   förslag mot "Russel"-posten; *ATLANTIS* motsvarande.)
2. GC tentativa 0-boksposter.
3. `suggested_author_id`-kolumnen via `ensure_database_columns()`.

## Implementationsordning

1. Resolvertester först, med hela Russell-kedjan som regressionstest
   (sådd → rename → berikning → **länken består**).
2. Lyssnaren (`stale`, behåll FK) + resolverreglerna + `suggested_author_id`.
3. GC-kroken vid bokradering + scannerstädning + backfill.
4. /authors: minnesförslag överst i dublettpanelen (infran finns —
   `duplicate_pairs` + merge-knapparna); granskningskön visar förslaget i
   comboboxen förvalt.
5. Skannervakten (separat commit, het kodväg).
6. MINOR-bump.

## Öppna beslut (färre än v1 — auto-rename-frågan försvann med modellen)

1. **Fuzzy-tröskel för minnesförslaget** — 0.85 som `_FUZZY_THRESHOLD`, eller
   generösare (0.80) givet kontexten samma boks fält? (Rekommendation: 0.85 —
   förslaget är ändå bara ett förslag.)
2. **GC-backfillen** — radera tentativa 0-boksposter tyst vid deploy eller logga
   listan först? (Rekommendation: logga till containerloggen, radera sedan.)
3. **Skannervaktens räckvidd** — bara alias-träff, eller även signatur-träff mot
   länkad post? (Rekommendation: börja med alias; signatur är nästan alltid
   redan alias via `_record_alias`.)
