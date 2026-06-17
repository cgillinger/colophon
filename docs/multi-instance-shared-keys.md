# Fleranvändare: separata bibliotek med delade API-nycklar

**Status:** Inte byggt — diskuterat 2026-06-17. Ingen kod skriven. Den
rekommenderade vägen kräver heller *ingen* kod, bara compose/env-uppställning.
Den här filen finns för att kunna ta upp tråden framför rätt dator.

**Bakgrund:** användarens fru vill ha ett eget bibliotek. Frågan var hur svårt
det vore att göra Colophon till ett fleranvändarsystem med separata bibliotek,
och om man kan dela API-nycklar mellan dem.

## Kort svar

Colophon är medvetet single-user: **ingen autentisering, ingen `users`-tabell,
globala tabeller, ett `/books` + ett `/data` per instans.** Det finns ~64
`LibraryItem.query`-anrop spridda över 15 filer som alla saknar
användarfiltrering.

Tre vägar, i stigande svårighetsgrad:

| Väg | Vad | Arbete |
|-----|-----|--------|
| **A** | Två separata containrar, helt isolerade | ~30 min, noll kod |
| **A+** (vald) | Väg A men med delade API-nycklar via gemensam env-fil | ~30 min, noll kod |
| **B** | Äkta fleranvändare i en instans (auth + `user_id` överallt) | Flera dagar, ändrad säkerhetsmodell |

Beslut: **gå på A+.** Den ger frun ett komplett eget bibliotek utan kodrisk på
det riktiga biblioteket, men med en enda plats för API-nycklarna.

## Varför A+ fungerar utan kodändring

`app/services/app_settings.py:get_setting()` läser i ordning:

1. DB-värde (om raden finns och inte är tom)
2. `COLOPHON_<KEY>` miljövariabel
3. legacy-env (`COLOPHON_MISTRAL_*`)
4. default

Lägger man nycklarna som **miljövariabler** delar båda instanserna samma nycklar
utan att de ligger i någon DB. Allt annat (DB, bibliotek, omslag, Kobo-enheter,
lässtatus) förblir separat per instans eftersom det är env-styrt i `config.py`
(`COLOPHON_DATA_DIR`, `COLOPHON_LIBRARY_DIR`, `COLOPHON_COVER_DIR`).

## Uppställning

```yaml
# docker-compose.yml
services:
  colophon:                       # du
    image: colophon
    ports: ["5055:5055"]
    env_file: [shared-keys.env]   # delade nycklar
    volumes:
      - /mnt/böcker:/books
      - /mnt/data:/data

  colophon-fru:                   # frun
    image: colophon
    ports: ["5056:5055"]
    env_file: [shared-keys.env]   # SAMMA fil
    volumes:
      - /mnt/böcker-fru:/books
      - /mnt/data-fru:/data
```

```bash
# shared-keys.env  (en enda fil, båda läser den)
COLOPHON_AI_API_KEY=...
COLOPHON_AI_API_URL=...
COLOPHON_AI_MODEL=...
COLOPHON_GOOGLE_BOOKS_KEY=...
COLOPHON_HARDCOVER_API_TOKEN=...
```

Byt en nyckel → ändra i `shared-keys.env`, starta om båda. Klart.

### Nycklar som är värda att dela (env-namn)

Härledda ur `_API_KEY_KEYS` + `_API_TEXT_KEYS` i `app/routes/settings.py` och
`get_setting`-anropen i tjänstelagret:

- `COLOPHON_AI_API_KEY`  (hemlig; legacy: `COLOPHON_MISTRAL_API_KEY`)
- `COLOPHON_AI_API_URL`
- `COLOPHON_AI_MODEL`    (legacy: `COLOPHON_MISTRAL_MODEL`)
- `COLOPHON_GOOGLE_BOOKS_KEY`  (hemlig)
- `COLOPHON_HARDCOVER_API_TOKEN`  (hemlig)

Källtoggles (`COLOPHON_COVER_*_ENABLED`, `COLOPHON_METADATA_SOURCE_*_ENABLED`,
`COLOPHON_METADATA_FETCH_MODE`) *kan* också läggas i env om man vill ha dem
identiska, men det är preferenser snarare än hemligheter — antagligen bättre att
låta var och en styra själv.

## Tre fallgropar

1. **Skriv inte in nycklar i Inställningar-UI:t.** Sparar någon ett värde under
   `/settings/api` skrivs det till *den* instansens DB och vinner då över
   env-filen (bara för den instansen).
   - De hemliga nyckelfälten (`_API_KEY_KEYS`) är säkra: tomt fält vid spara
     behåller env-värdet (`# Empty submit = keep existing value`).
   - Men `AI_API_URL` och `AI_MODEL` (`_API_TEXT_KEYS`) skrivs *alltid* vid
     spara, så de "fryses" in i DB:n med vad som råkade visas. Ofarligt
     funktionellt — samma värde — men då slutar de följa env-filen.
   - Tumregel: hantera nycklarna i filen, rör dem inte i webbgränssnittet.
     UI:t visar dem ändå som ifyllda eftersom det läser via samma `get_setting`.

2. **Delad API-kvot.** Samma nyckel = samma rate limit / kvotpott. För ett
   hushåll med två personer är det inget problem i praktiken.

3. **Två URL:er, två PWA-installationer.** `:5055` resp. `:5056`. Ingen delad
   vy och inga delade böcker — det är hela poängen med isoleringen.

## Om vi senare vill ha Väg B (äkta fleranvändare)

Sparat för fullständighet — inte planerat. Skulle kräva:

1. Autentiseringslager från noll (login, lösenordshashning/sessioner, eller
   reverse-proxy-auth). Finns inget idag.
2. `users`-tabell + `user_id`-FK på `library_items` (troligen även `authors`,
   `kobo_devices`, `app_settings`).
3. Filtrera samtliga ~64 query-anrop på inloggad användare — varje missad query
   läcker böcker mellan användarna.
4. Per-användare biblioteksmappar på disk (`/books/<user>/…`) → omarbeta
   scanner, upload, upstream-synk och filsökvägar (`file_path` har `unique=True`).
5. Beslut om delat kontra privat: API-nycklar/AI-kvot, författarregistret
   (authority control).
6. Migrering av befintlig data in i "användare 1" + testning mot riktigt
   bibliotek.

Det är en MINOR/MAJOR-feature och ändrar säkerhetsmodellen (då *behövs* riktig
auth). A+ kan alltid migreras till B senare.
