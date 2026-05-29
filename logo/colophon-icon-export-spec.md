# Colophon — ikon-/logotypexport

Master-filer (vektor, oändligt skalbara):

| Fil | Användning |
|-----|-----------|
| `colophon-logo.svg` | Full lockup (symbol + ordmärke) med mjuk skugga — header, om-sida, social |
| `colophon-logo-flat.svg` | Full lockup utan skugga |
| `colophon-mark.svg` | Endast symbol, med skugga — större ikoner |
| `colophon-mark-flat.svg` | Endast symbol, platt — **favicon/app-ikon** (skugga försvinner ändå i småskala) |

Ordmärket är redan konverterat till banor (ingen typsnittsberoende rendering).

## Storlekar att generera

Favicon / app-ikon — använd `colophon-mark-flat.svg`:
- `favicon-16.png` 16×16
- `favicon-32.png` 32×32
- `favicon-48.png` 48×48
- `apple-touch-icon.png` 180×180
- `icon-192.png` 192×192 (PWA)
- `icon-512.png` 512×512 (PWA)
- `favicon.ico` (paketera 16/32/48)

Header-logga — använd `colophon-logo.svg` (eller `-flat`):
- `logo.svg` (lägg in SVG:n direkt — skarp på alla skärmar)
- `logo@1x.png`, `logo@2x.png`, `logo@3x.png` om PNG krävs

## Exportkommandon (välj det som finns)

rsvg-convert:
```
rsvg-convert -w 32  colophon-mark-flat.svg -o favicon-32.png
rsvg-convert -w 180 colophon-mark-flat.svg -o apple-touch-icon.png
rsvg-convert -w 512 colophon-mark-flat.svg -o icon-512.png
```

ImageMagick (density för skarphet):
```
magick -background none -density 600 colophon-mark-flat.svg -resize 32x32 favicon-32.png
```

Node/sharp:
```
sharp(fs.readFileSync('colophon-mark-flat.svg')).resize(512).png().toFile('icon-512.png')
```

favicon.ico:
```
magick favicon-16.png favicon-32.png favicon-48.png favicon.ico
```

Viktigt: rasterisera alltid direkt från SVG till varje målstorlek — skala aldrig upp en liten PNG. Behåll transparent bakgrund (`-background none`).
