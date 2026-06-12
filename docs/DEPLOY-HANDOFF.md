# Deploy handoff — v1.18.0 → v1.20.0 (author authority control)

> **Till Claude Code (eller Christian) på en dator med serveraccess.**
> Skrivet 2026-06-12 från en dator UTAN access till servern. Allt som
> behövs finns i fjärrepot — inget beror på den ursprungliga datorn.
> **Radera den här filen (och pekaren i CLAUDE.md) när deployen är
> verifierad.**

## Läget

Tre releaser ligger på `main`, taggade `v1.18.0`, `v1.19.0`, `v1.20.0`
(HEAD = `0b1c929`). De bygger tillsammans **author authority control** —
kanoniskt författarregister med UI. Servern (`colophon` på
http://192.168.50.8:5055) kör fortfarande **1.17.0** och har inte sett
någon av ändringarna. Designdokument: `docs/author-authority-design.md`.

## Steg 1 — rebuild (vanliga rutinen)

Från `/mnt/docker/stacks/colophon/repo`:

```bash
git pull && cd .. && docker compose down && docker compose build --no-cache && docker compose up -d && docker logs colophon --tail 20
```

`--no-cache` är obligatoriskt (se CLAUDE.md). Vid uppstart kör
migreringarna automatiskt: nya tabeller `authors` + `author_aliases`,
nya kolumner `library_items.author_id` + `author_status`. Ofarligt —
tomma tabeller och NULL-kolumner, inga befintliga data röre.

Kontrollera i loggen att Gunicorn startar utan traceback och att sidfoten
i UI:t visar **1.20.0**.

## Steg 2 — första scannen (back-upplöser biblioteket)

Kör **"Hitta nya böcker"** i UI:t (eller `curl http://192.168.50.8:5055/scan`).
Pending-passet upplöser då hela biblioteket mot registret: exakta träffar
och format-/ordningsvarianter ("Tolkien, J.R.R." = "J.R.R. Tolkien")
auto-länkas, fuzzy-nära namn flaggas för granskning, nya författare blir
preliminära poster. **DB-only — inga filer skrivs, ingen Kobo-omsynk.**

## Steg 3 — verifiera (gärna med Playwright MCP, läs-bara)

Säg "Använd Playwright MCP" i sessionens första prompt om UI-verifiering
önskas. Säkert att göra (inget muterar):

1. **Statusraden** i biblioteksvyn: en chip "N författare att granska"
   ska finnas (om biblioteket har olösta namn). Klick togglar filtret.
2. **Författarkolumnen**: små flaggor (⚠️/➕/❓) på flaggade rader.
3. **Sidomenyn → Författare** (`/authors`): registertabell med bokantal,
   statusbadges (Preliminär/Bekräftad/Auktoriserad), ev. panel "Troliga
   dubbletter".
4. **Bokmodalen**: författarfältet är en combobox — skriv några tecken
   och se typeahead-listan; granskningsflaggad bok visar "Menade du …?".
5. **Svenska**: alla nya strängar ska vara på svenska (kompileras i
   Docker-bygget, `Dockerfile` rad ~40).

Mutationsåtgärder (Bekräfta/Byt namn/Slå ihop/Verifiera/spara i modal)
kräver Christians uttryckliga ok per åtgärd — se produktionsreglerna i
CLAUDE.md.

## Om något går fel

- Rollback: `git checkout v1.17.0`-läget motsvaras av
  `git reset --hard 069c290` + rebuild. Migreringarna lämnar bara
  oanvända tomma tabeller/kolumner kvar — ofarligt.
- Kända icke-fel: lokala testkörningar utanför containern failar på
  test_kobo_sync (PermissionError `/data`), test_quality/test_scoring
  (okompilerade översättningar) och
  test_scanner::test_does_not_overwrite_manual_metadata (stale test
  sedan 2026-05-24). I containern är de irrelevanta.

## Efter verifierad deploy

1. Radera den här filen.
2. Ta bort "Pending deployment"-stycket i CLAUDE.md.
3. Committa: `chore: remove deploy handoff after v1.20.0 rollout`.
