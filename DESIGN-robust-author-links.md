# Design — robusta författarlänkar (länken överlever metadatarättningar)

> Status: **DESIGN, ej byggt.** Skriven 2026-07-27 utifrån ett verkligt haveri i prod
> (fallet "Mary Doria Russel", se nedan). Bygger ovanpå det shippade författarregistret
> (`docs/author-authority-design.md`, v1.18–1.21) och ändrar **inte** dess grundprinciper —
> den täpper till ett hål i dem.

## Invarianten vi ska uppfylla

> **En bok som länkats till en författarpost förblir länkad tills (a) boken raderas
> eller (b) användaren själv byter författare på boken.** En metadatarättning av
> *stavningen* på samma person får aldrig kapa länken.

Idag gäller i stället: *varje* ändring av `item.author` — oavsett avsändare — nollar
länken och låter en minneslös omresolvering avgöra. Det är därför länkar "försvinner"
utan att någon bok raderats.

## Beviskedjan — fallet "Mary Doria Russel" (prod, 2026-06-12)

Rekonstruerad ur DB + fil, allt inom 7 minuter:

1. **17:04** Registret såddes. Bokens (`library_items.id=387`, *The Sparrow*) inbäddade
   `dc:creator` var felstavat **"Mary Doria Russel"** (ett l) → tentativ post
   `authors.id=162` skapades, boken länkades, `author_status='new'`.
2. **17:11** Berikningen valde rättstavade **"Mary Doria Russell"** och skrev den till
   både DB och filen (`file_modified_by_colophon` stämplad — filen är idag korrekt).
3. `_reset_author_resolution` (`app/models.py:248`) såg att `author` ändrats →
   nollade `author_id` + `author_status`.
4. Nästa pending-pass (`resolve_pending_authors`): "Russell" matchar inte "Russel"
   exakt; signaturen skiljer också (tokenmängderna {mary, doria, russel} ≠
   {mary, doria, russell}); fuzzy ≥ 0.85 → **järnregeln**: föreslå, länka aldrig →
   `author_status='review'`, `author_id=NULL`.
5. Slutresultat: boken evigt i granskningskön, posten föräldralös (0 böcker),
   och stavfelet "Russel" ligger kvar som kanoniskt namn. ("Timescape" är samma
   mekanism med annan orsak: titeln låg i författarfältet vid sådden.)

**Kärnfelet:** steg 3–4 är *minneslösa*. Omresolveringen vet inte att boken nyss var
länkad till post 162, så järnregeln (rätt för kalla matchningar mellan *okända* namn)
appliceras på ett fall där vi har stark kontext: *samma bok, samma fält, en
stavningsvariant från en mer pålitlig källa*.

## Designen: omresolvering med minne ("sticky links")

### 1. Reset-lyssnaren bevarar länken som kontext

`_reset_author_resolution` slutar nolla `author_id`. I stället:

```
author_status = 'stale'        # nytt värde: "länkad, men strängen har ändrats"
author_id     = <orörd>        # minnet — förra länken
```

Allt som idag räknar "länkad" (`author_status == 'linked'`) fortsätter fungera;
`'stale'` plockas upp av pending-passet precis som `NULL` gör idag
(`resolve_pending_authors`, `app/services/author_resolver.py:147`). Undantagen i
lyssnaren (combobox sätter båda fälten; `keep_author_links()` för kaskader) behålls
oförändrade.

### 2. Resolvern får en prioriterad regel för `stale`-poster

I `resolve_and_link()` (`author_resolver.py:112`), **före** dagens lager, när
`author_status='stale'` och `author_id` finns:

1. **Exakt/signatur-träff mot någon registerpost** (lager 1–2, som idag) → länka den.
   Är det en *annan* post än minnet pekar på är det en äkta författarkorrigering —
   godta den, och GC:a den gamla posten om den blivit föräldralös (se §4).
2. **Fuzzy-träff (≥ 0.85) mot just den post minnet pekar på** → **behåll länken**:
   `author_status='linked'`, registrera nya stavningen som alias
   (`_record_alias`). Detta bryter inte järnregeln — den skyddar mot att slå ihop
   *två olika personer* vid kall matchning; här dömer vi *samma boks* fält mot
   *bokens egen tidigare post*, med ny stavning från berikning/användare. Risken är
   en annan, och priset för dagens beteende (evig granskningskö + föräldralösa
   poster) är bevisat högre.
3. **Ingen träff alls** (< 0.85 även mot minnet) → äkta författarbyte: släpp minnet
   och kör dagens flöde (nytt tentativt / review / missing). GC:a gammal post per §4.

### 3. Tentativa poster följer med rättningen

I regel 2, om den mindes posten är `source='tentative'` **och** boken är dess enda
länkade bok: **döp om postens `canonical_name` till den nya stavningen** (via
`keep_author_links()`-kaskaden så lyssnaren inte triggas). Motivering: posten
skapades automatiskt ur exakt den här bokens dåliga filmetadata — boken *är* postens
enda evidens. När evidensen rättas ska posten följa med, inte fossilisera stavfelet.

Har posten fler böcker: behåll namnet, lägg bara alias (de andra böckerna kan
fortfarande ha gamla stavningen), och låt dublettvyn/AI-domaren föreslå ev. rename.
Bekräftade/auktoritetslänkade poster byter aldrig namn automatiskt — bara alias.

### 4. Livscykel för föräldralösa tentativa poster (GC)

När en omresolvering (regel 1 eller 3) *lämnar* en post: om posten är
`source='tentative'` och nu har 0 länkade böcker → **radera den + dess alias**
(samma logik som delete-endpointens guard, `app/routes/authors.py:268`, fast
automatiskt). Tentativa poster är DB-only och autoskapade — de har inget
bevarandevärde utan böcker. Bekräftade poster raderas aldrig automatiskt; de får
"Inga böcker"-badgen (v1.33.1) och användaren avgör.

Engångsbackfill vid uppstart (mönstret i `app/services/database.py`): GC:a
befintliga tentativa 0-boksposter ("Timescape" försvinner då av sig själv).

### 5. Skannervakt mot flip-flop via alias

`upsert_library_item` (`app/services/scanner.py:509`) skriver idag alltid över
`author` från filens `dc:creator`. Det är rätt när filen är sanningen — men om
filskrivningen är gate:ad (tentativ kanonisk skrivs aldrig till fil) kan filen ligga
kvar med en äldre stavning och varje omscan då återinföra den → lyssnaren triggas →
churn. Vakt: **om inkommande författarsträngs `variant_key` är ett känt alias för
bokens länkade post → hoppa över överskrivningen** (DB:ns kanoniska form vinner;
filen hinner ikapp vid nästa metadata-skrivning). Okända strängar skrivs över som
idag.

## Vad som INTE ändras

- Järnregeln för **kalla** matchningar står kvar orörd: fuzzy föreslår, länkar aldrig,
  vid sådd/upload/nyresolvering utan minne.
- Filen förblir sanningskällan; gate:n "tentativ skrivs inte till fil" står kvar.
- Combobox-/manage-flödena (assign/rename/merge/confirm) oförändrade.
- `group_key`, Kobo-synk, läsarstate — orörda.

## Implementationsordning

1. **Resolvertest först** (`tests/test_author_resolver.py`): stale-reglerna 1–3 som
   rena enhetstester, inkl. Russell-kedjan som regressionstest.
2. `models.py`-lyssnaren (`'stale'` i stället för NULL) + resolverregeln.
3. Tentativ-rename (§3) + GC (§4) + backfill.
4. Skannervakten (§5) — separat commit, den rör en het kodväg.
5. MINOR-bump (beteendeförändring + backfill).

## Öppna beslut (Christians)

1. **Tröskeln för "samma person" i regel 2** — återanvända 0.85 (dagens
   `_FUZZY_THRESHOLD`) eller sätta en egen, t.ex. 0.80, eftersom kontexten
   (samma boks fält) motiverar generösare gräns?
2. **Auto-rename av tentativ post (§3)** — ok att kanoniska namnet byts utan
   bekräftelse när boken är postens enda evidens, eller ska det bli ett
   "föreslagen rename"-kort i /authors i stället?
3. **GC-backfillen (§4)** — radera befintliga tentativa 0-boksposter tyst vid
   deploy, eller lista dem en gång i loggen/UI:t innan?
4. **Skannervakten (§5)** — räcker alias-matchning, eller ska även
   signatur-matchning (lager 2) mot länkad post blockera överskrivning?
