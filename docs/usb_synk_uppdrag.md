# Uppdrag — USB-synk med kanalmedvetenhet (porta Bookstations USB-stack)

**Till:** den Claude-instans som arbetar i Colophon.
**Från:** Bookstation-sidan. Colophon har idag ENBART trådlös Kobo-synk
(`kobo_sync.py`/`kobo_auth.py`/`kobo_conf.py`) — ingen enhetsdetektering,
ingen USB-överföring, ingen läsning av `KoboReader.sqlite`. Bookstation har
byggt hela USB-stacken, kört den i produktion (Fredriks Kobo), lärt sig de
dyra läxorna och löst slutproblemet: **USB och WiFi utan dubbletter**. Det
här uppdraget är kartan för att porta alltihop åt andra hållet.

> ## Referensimplementationen finns på disk
>
> Bookstation ligger som systermapp: `../bookstation`
> (absolut: `/home/christian/Dokument/Github/bookstation`).
>
> - **Referens-commits** (kronologisk ordning — evolutionen är läroboken):
>   - `7de2d96` → `9e913af` → `a944aad` — enhetspanelen växer fram
>     (sidofältspanel → höger-drawer → topbar-badge med rolldown +
>     `KoboReader.sqlite`-jämförelse). Porta SLUTLÄGET, inte resan.
>   - `f4446ab` — USB-statistikimport: lässtatistik skördas direkt ur
>     `KoboReader.sqlite` när Kobon är USB-ansluten.
>   - `045ecfc` — **läxa 1**: läs ALDRIG `KoboReader.sqlite` på plats.
>     `immutable=1` mot en het WAL ger falsk "malformed" — kopiera DB +
>     sidofiler till temp och läs kopian.
>   - `0864879` — **läxa 2**: äkta korrupta databaser finns i verkligheten
>     (trasiga sidor, inte het WAL). Recover-fallback i ren Python:
>     rowid-intervall-halvering, till sist rad-för-rad, så raderna på
>     friska sidor överlever. (sqlite3-CLI:ts `.recover` finns INTE i
>     Ubuntus build — därav ren Python.)
>   - `a17e24c` (tag `v0.19.0`) — **kronjuvelen**: kanalmedveten synk.
>     `git -C ../bookstation show a17e24c --stat` listar allt.
> - **Kärnfiler**: `app/services/device_monitor.py` (mount-övervakning +
>   SSE), `app/routes/devices.py` (panel-API: compare/send/import/adopt/
>   remove-sideload), `app/static/js/device_panel.js` (topbar-badge +
>   drawer med fyra flikar), `app/services/kobo_usb_sync.py`
>   (statistikimport inkl. båda läxorna ovan),
>   `app/services/device_transfers.py` (kanalbokföringen),
>   `app/services/database.py` (`ensure_device_transfers_table`).
> - **Testerna är specen**: `../bookstation/tests/test_device_transfers.py`
>   (11 fall — conf-token/serial-parsning, idempotent bokföring,
>   token↔serial-bryggan, WiFi-synkens exkludering, SerialNumber-fångst,
>   adopt, remove-sideload med path-skydd) och
>   `tests/test_kobo_usb_sync.py` (temp-kopia + korrupt-DB-recover).
>   Porta dem först och låt dem driva implementationen.
>
> Läs Bookstations kod som **referens, inte facit** — repona har drivit
> isär. Verifiera varje ankare mot er egen kod.

---

## Designbesluten (det här är det viktiga att porta rätt)

1. **Bygg USB-importen och kanalbokföringen SAMTIDIGT — aldrig den ena
   utan den andra.** Kobons firmware kan inte dedupa en sidladdad fil
   (ContentID = sökväg) mot ett moln-entitlement (ContentID = UUID). En
   USB-funktion utan bokföring ger garanterat dubbletter så fort samma
   bok också WiFi-synkas (verklighetsfallet: ~1900 böcker dubblerade på
   en platta). Regeln är **"en kanal per bok och enhet"**, upprätthållen
   server-side: tabellen `device_transfers` bokför varje USB-överföring
   appen själv gör, och WiFi-synkens entitlement-bygge exkluderar de
   böckerna för just den enheten.

2. **USB↔WiFi-länken är definitiv, inte heuristisk.** Vid trådlös setup
   skriver appen själv `api_endpoint=<bas>/kobo/<token>` i enhetens
   `Kobo eReader.conf` — alltså kan tokenen läsas rakt ur den monterade
   enheten (regex på conf-filen). Serienumret är reservidentitet, fångat
   från två håll: `.kobo/version` (första CSV-fältet) vid montering, och
   `SerialNumber` i `/v1/auth/device`-payloaden WiFi-vägen (lagras på
   token-raden). Bokföringen matchar token först, serial som reserv, och
   en befintlig rad *kompletteras* med nyare kunskap i stället för att
   dubbleras. OBS: Colophons conf-patchning bor i `kobo_conf.py` — er
   endpoint-URL-form kan skilja sig från Bookstations; verifiera
   regexen mot vad NI faktiskt skriver.

3. **Läs ALDRIG `KoboReader.sqlite` på plats — och räkna med korruption.**
   Ordningen är: (a) kopiera DB + `-wal`/`-shm` till temp och läs kopian
   (het WAL ger annars falsk "malformed" med `immutable=1`); (b) vid
   äkta "database disk image is malformed": läs om i rowid-intervall med
   halvering och till sist rad för rad — raderna på friska sidor
   överlever. Flagga i kvittot att statistiken kommer ur en skadad
   databas och att rader kan saknas. Ren Python — förlita er inte på
   sqlite3-CLI:t.

4. **Kanalparitet: USB-skick kepubifieras precis som WiFi-nedladdningar.**
   Annars ger de två kanalerna olika läsupplevelse och olika rik
   lässtatistik. Rå EPUB som fallback när kepubify saknas — samma policy
   som er trådlösa väg. Filnamnet ska sluta på `.kepub.epub`. Touch:a
   `.kobo/bgdl_a_trigger` efter kopiering så Nickel omindexerar utan
   ur-och-i-koppling.

5. **Stoppa korskanal-dubbletter vid dörren, flagga resten — gissa
   aldrig.** Ett USB-skick av en bok som redan är WiFi-synkad till samma
   enhet stoppas med besked ("finns redan via WiFi"). Böcker som hamnat
   på enheten utanför appen kan inte förhindras — de *upptäcks* i
   jämför-vyn och flaggas i en egen ⚠-flik som bara visas när något
   behöver åtgärdas, med två fall och tre åtgärder:
   - **Dubblett (USB + WiFi)**: sidladdad fil + moln-entitlement för
     samma bok → åtgärd "Ta bort från enhet" (raderar den sidladdade
     filen; molnboken och all läsdata blir kvar).
   - **Ospårad (kopierad utanför appen)**: matchar en biblioteksbok men
     saknar bokföringsrad → åtgärd "Adoptera" (bokför i efterhand ⇒
     WiFi-synken hoppar över den; filen rörs inte).
   - **Finns bara på Kobon**: importera till biblioteket — och bokför
     importen direkt, annars dubbleras den nyimporterade boken vid
     nästa synk.

6. **Enhetsövervakningen får inte pinna workers.** `/proc/mounts`-polling
   i bakgrundstråd + SSE-ström till klienten — men SSE-anslutningen ska
   bara vara öppen medan panelen faktiskt är öppen; annars långsam
   polling som pausar när fliken är dold. (Bookstation lärde sig detta
   den hårda vägen med gunicorn-sync-workers; regeln är sund även under
   gthread.) Ladda ALDRIG panel-JS:et på reader-sidor.

7. **Jämförelsen matchar på normaliserad titel/författare/filnamnsstam.**
   `KoboReader.sqlite` vet inget om era id:n eller hashar — trippeln
   räcker i praktiken. Sidladdade böcker identifieras på
   `ContentID`-sökväg; molnböcker på UUID. WiFi-enhetens "på enheten"-
   lista = lässtatus-rader för tokenen ∪ USB-bokförda böcker (annars
   listas USB-överförda som "saknade" för evigt).

8. **Migrationen är additiv + idempotent**: `CREATE TABLE IF NOT EXISTS
   device_transfers` (item_id FK CASCADE, kobo_token, device_serial,
   device_label, method, transferred_at) + index + `ALTER TABLE`-tillägg
   av serienummerkolumnen på token-tabellen med
   dubblettkolumn-tolerans.

## Fallgropar Bookstation hittade under bygget

- **Bulk-deletes går förbi ORM-kaskaden**: raderingsvägar som kör
  `query.delete()` måste städa `device_transfers` explicit (FK CASCADE
  i SQLite kräver `foreign_keys=ON` och hjälper ändå inte ORM-lösa
  vägar i alla lägen). Kolla ERA raderingsvägar.
- **Sökvägsvalidering på allt som pekar in i monteringen**: både import
  och fjärr-radering realpath-validerar att filen ligger under
  mount-punkten — en Kobo-montering är skrivbar för alla processer.
- **Radering av sidladdad fil ska också städa bokföringsraden** (skicka
  med item-id) — annars förblir boken exkluderad ur WiFi-synken fast
  den inte längre finns på enheten.
- **macOS-skuggfiler**: en `._KoboReader.sqlite` på 4 KB är INTE
  databasen. Ta första ordentliga filen, inte första globträffen.
- **Enhetsetiketter är opålitliga** — bygg identiteten på conf-token +
  serienummer, aldrig på volymnamn/label.

## Colophon-specifika anpassningar (kända skillnader)

- Colophon är single-user — inga `scoped_items`/`admin_required`-grindar
  att porta; hoppa över Bookstations multiuser-scoping.
- UI-språk via gettext (`_()` + sv-.po) — Bookstations svenska strängar
  är hårdkodade; era ska in i översättningsflödet.
- Er trådlösa Kobo-kod heter annorlunda (`kobo_sync.py`, `kobo_auth.py`,
  `kobo_conf.py` vs Bookstations `routes/kobo.py` + `kobo_conf_patch.py`)
  och er reading-state-modell skiljer sig — verifiera varje ankare
  (entitlement-byggare, state-tabell, conf-nycklar) mot er egen kod
  innan ni kopierar en rad.
- Panelens hemvist: Bookstation kör topbar-badge + rolldown-drawer med
  fyra flikar (→ Kobo / ✓ Synkade / ← Bibliotek / ⚠ Felöverförda).
  Anpassa till er chrome, men behåll flik-semantiken — särskilt att
  ⚠-fliken är dold tills den behövs.

## Användarlöftet (målet med alltihop)

När porten är klar ska Colophon kunna säga samma sak som Bookstation:
**"Använd alltid appen för överföring — USB eller WiFi, båda blir rätt.
Kopiera aldrig böcker till Kobon med en filhanterare; det upptäcks och
flaggas, men kan inte förhindras."**

## Leveranskriterium

Porta testsviterna (`test_device_transfers.py` + `test_kobo_usb_sync.py`)
och kör kedjan end-to-end: (1) skicka en bok via USB → bokförd, KEPUB på
enheten, nästa WiFi-synk hoppar över den, (2) försök USB-skicka en bok
som redan är WiFi-synkad → stoppas med besked, (3) kopiera en fil till
en fejkad montering utanför appen → flaggas som ospårad, Adoptera →
bokförd och exkluderad ur nästa synk, (4) fejka en dubblett (sidladdad +
lässtatus-rad) → flaggas, "Ta bort från enhet" raderar filen och städar
bokföringen, (5) statistikimport mot en het-WAL-kopia OCH mot en medvetet
korrupt databas → båda ger data, den korrupta med varningsflagga.
