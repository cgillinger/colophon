# Assignment: fixa iOS-/hemskärmsikonen

Bakgrund: nuvarande `apple-touch-icon.png` (och PWA-ikonerna) genererades från den transparenta `colophon-mark-flat.svg`. iOS ignorerar transparens och svartfyller bakgrunden när man lägger sidan på hemskärmen via Safari → böckerna hamnar på en svart bricka och de nedre banden försvinner. Fix: generera dessa ikoner från en fyrkantig master med solid bakgrund.

Ny källfil ligger i `logo/colophon-icon-ios.svg` (fyrkantig, cremefärgad bakgrund). Lämna fyrkant orörd — iOS rundar hörnen själv. Sonnet räcker. Pusha direkt till `main`.

## Steg
1. Hitta var de befintliga ikonerna ligger (sannolikt `app/static/img/`) — där `apple-touch-icon.png` redan finns.

2. **Skriv över** följande, nu genererade från `logo/colophon-icon-ios.svg`:
   - `apple-touch-icon.png` 180×180
   - `icon-192.png` 192×192
   - `icon-512.png` 512×512
   ```
   rsvg-convert -w 180 logo/colophon-icon-ios.svg -o app/static/img/apple-touch-icon.png
   rsvg-convert -w 192 logo/colophon-icon-ios.svg -o app/static/img/icon-192.png
   rsvg-convert -w 512 logo/colophon-icon-ios.svg -o app/static/img/icon-512.png
   ```
   (Justera målsökväg till var ikonerna faktiskt ligger. ImageMagick funkar också: `magick -density 600 logo/colophon-icon-ios.svg -resize 180x180 .../apple-touch-icon.png`.)

3. **Rör INTE** `favicon-16/32/48.png` eller `favicon.ico` — transparent bakgrund är rätt för webbläsarflikar.

4. Bekräfta att bas-templaten har `<link rel="apple-touch-icon" sizes="180x180" href="{{ url_for('static', filename='img/apple-touch-icon.png') }}">` i `<head>`. Lägg till om det saknas.

## Verifiera
- De tre ikonerna har nu cremefärgad (ej transparent) bakgrund.
- Öppna en av dem och kontrollera att hela boksymbolen syns mot creme, centrerad.

---

Rebuild efteråt:
```
cd /mnt/docker/stacks/colophon/repo && git pull && cd .. && docker compose down && docker compose build --no-cache && docker compose up -d && docker logs colophon --tail 20
```
