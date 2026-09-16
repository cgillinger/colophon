"""Generate book-like covers for the fictional sample library (Pillow only)."""
import math, os, random, sys
from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageChops, ImageOps

W, H = 900, 1350
OUT = os.path.join(os.path.dirname(__file__), "covers")
os.makedirs(OUT, exist_ok=True)

F = "/usr/share/fonts/truetype"
FONTS = {
    "serif": f"{F}/liberation/LiberationSerif-Regular.ttf",
    "serif_b": f"{F}/liberation/LiberationSerif-Bold.ttf",
    "serif_i": f"{F}/liberation/LiberationSerif-Italic.ttf",
    "serif_bi": f"{F}/liberation/LiberationSerif-BoldItalic.ttf",
    "fserif_b": f"{F}/freefont/FreeSerifBold.ttf",
    "fserif_bi": f"{F}/freefont/FreeSerifBoldItalic.ttf",
    "fserif_i": f"{F}/freefont/FreeSerifItalic.ttf",
    "sans": f"{F}/liberation/LiberationSans-Regular.ttf",
    "sans_b": f"{F}/liberation/LiberationSans-Bold.ttf",
    "dsans": f"{F}/dejavu/DejaVuSans.ttf",
    "dsans_b": f"{F}/dejavu/DejaVuSans-Bold.ttf",
    "dserif_b": f"{F}/dejavu/DejaVuSerif-Bold.ttf",
    "dserif": f"{F}/dejavu/DejaVuSerif.ttf",
    "mono": f"{F}/dejavu/DejaVuSansMono.ttf",
    "mono_b": f"{F}/dejavu/DejaVuSansMono-Bold.ttf",
}

def font(name, size):
    return ImageFont.truetype(FONTS[name], size)

def hexc(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i+2], 16) for i in (0, 2, 4))

def lerp(a, b, t):
    return tuple(int(a[i] + (b[i] - a[i]) * t) for i in range(3))

def vgrad(c1, c2, w=W, h=H):
    img = Image.new("RGB", (w, h))
    d = ImageDraw.Draw(img)
    for y in range(h):
        d.line([(0, y), (w, y)], fill=lerp(c1, c2, y / (h - 1)))
    return img

def rgrad(c_in, c_out, center=(0.5, 0.45), radius=0.9, w=W, h=H):
    small = Image.new("RGB", (90, 135))
    d = ImageDraw.Draw(small)
    cx, cy = center[0] * 90, center[1] * 135
    R = radius * 135
    for y in range(135):
        for x in range(90):
            t = min(1.0, math.hypot(x - cx, y - cy) / R)
            d.point((x, y), fill=lerp(c_in, c_out, t))
    return small.resize((w, h), Image.BICUBIC)

def grain(img, amount=18, seed=1):
    noise = Image.effect_noise((W, H), 64).convert("L")
    noise = ImageOps.autocontrast(noise)
    noise = noise.point(lambda v: 128 + (v - 128) * amount // 100)
    noise = Image.merge("RGB", (noise, noise, noise))
    return ImageChops.overlay(img, noise)

def vignette(img, strength=0.35):
    mask = rgrad((255, 255, 255), (int(255 * (1 - strength)),) * 3, center=(0.5, 0.5), radius=0.95)
    return ImageChops.multiply(img, mask)

def wrap(draw, text, fnt, maxw):
    words = text.split()
    lines, cur = [], ""
    for w_ in words:
        t = (cur + " " + w_).strip()
        if draw.textlength(t, font=fnt) <= maxw:
            cur = t
        else:
            if cur:
                lines.append(cur)
            cur = w_
    if cur:
        lines.append(cur)
    return lines

def fit_title(draw, text, fname, maxw, maxh, start=130, minsize=60, spacing=1.05):
    size = start
    while size >= minsize:
        fnt = font(fname, size)
        lines = wrap(draw, text, fnt, maxw)
        lh = int(size * spacing)
        if len(lines) * lh <= maxh and all(draw.textlength(l, font=fnt) <= maxw for l in lines):
            return fnt, lines, lh
        size -= 6
    fnt = font(fname, minsize)
    return fnt, wrap(draw, text, fnt, maxw), int(minsize * spacing)

def draw_lines(draw, lines, fnt, lh, y, fill, align="center", x=None, tracking=0, shadow=None):
    for l in lines:
        tw = draw.textlength(l, font=fnt) + tracking * max(0, len(l) - 1)
        if align == "center":
            xx = (W - tw) / 2
        elif align == "left":
            xx = x
        else:
            xx = x - tw
        if tracking:
            cx = xx
            for ch in l:
                if shadow:
                    draw.text((cx + 3, y + 3), ch, font=fnt, fill=shadow)
                draw.text((cx, y), ch, font=fnt, fill=fill)
                cx += draw.textlength(ch, font=fnt) + tracking
        else:
            if shadow:
                draw.text((xx + 3, y + 3), l, font=fnt, fill=shadow)
            draw.text((xx, y), l, font=fnt, fill=fill)
        y += lh
    return y

def small_caps_line(draw, text, fnt, y, fill, tracking=6):
    tw = draw.textlength(text, font=fnt) + tracking * (len(text) - 1)
    x = (W - tw) / 2
    for ch in text:
        draw.text((x, y), ch, font=fnt, fill=fill)
        x += draw.textlength(ch, font=fnt) + tracking

def imprint(draw, name, y, fill, symbol=True):
    fnt = font("sans", 26)
    small_caps_line(draw, name.upper(), fnt, y, fill, tracking=7)
    if symbol:
        draw.rectangle([W / 2 - 9, y - 26, W / 2 + 9, y - 8], outline=fill, width=2)

def rule(draw, y, fill, width=1, inset=260):
    draw.line([(inset, y), (W - inset, y)], fill=fill, width=width)

# ----------------------------------------------------------------- art

def stars(draw, n, seed, color=(255, 255, 255), ymax=H, big=False):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.randint(0, W), rnd.randint(0, ymax)
        r = rnd.choice([1, 1, 1, 2, 2, 3]) if big else rnd.choice([1, 1, 1, 1, 2])
        a = rnd.randint(120, 255)
        c = tuple(int(v * a / 255) for v in color)
        draw.ellipse([x - r, y - r, x + r, y + r], fill=c)

def mountains(draw, layers, seed, base_y, colors, jag=0.5):
    rnd = random.Random(seed)
    for i, col in enumerate(colors):
        pts = [(0, H)]
        x = 0
        y = base_y + i * 70
        while x <= W + 60:
            pts.append((x, y + rnd.randint(-int(120 * jag), int(120 * jag)) - i * 10))
            x += rnd.randint(50, 110)
        pts.append((W, H))
        draw.polygon(pts, fill=col)

def waves(draw, y0, n, seed, colors, amp=18, wl=170):
    rnd = random.Random(seed)
    for i, col in enumerate(colors):
        pts = []
        ph = rnd.random() * 6
        for x in range(0, W + 1, 6):
            y = y0 + i * 42 + amp * math.sin(x / wl * 2 * math.pi + ph + i)
            pts.append((x, y))
        pts += [(W, H), (0, H)]
        draw.polygon(pts, fill=col)

def skyline(draw, y0, seed, col, win=None):
    rnd = random.Random(seed)
    x = 0
    while x < W:
        w_ = rnd.randint(40, 110)
        h_ = rnd.randint(120, 420)
        draw.rectangle([x, y0 - h_, x + w_, H], fill=col)
        if rnd.random() < 0.4:
            draw.rectangle([x + w_ // 2 - 4, y0 - h_ - rnd.randint(20, 90), x + w_ // 2 + 4, y0 - h_], fill=col)
        if win:
            for wy in range(y0 - h_ + 14, y0, 22):
                for wx in range(x + 8, x + w_ - 10, 18):
                    if rnd.random() < 0.35:
                        draw.rectangle([wx, wy, wx + 7, wy + 11], fill=win)
        x += w_ + rnd.randint(4, 18)

def trees(draw, seed, y_base, col, n=14, fog=None):
    rnd = random.Random(seed)
    for i in range(n):
        x = rnd.randint(-20, W + 20)
        w_ = rnd.randint(16, 40)
        draw.rectangle([x, y_base - rnd.randint(500, 900), x + w_, H], fill=col)
        for _ in range(rnd.randint(2, 5)):
            by = y_base - rnd.randint(300, 800)
            bl = rnd.randint(40, 120)
            dirn = rnd.choice([-1, 1])
            draw.line([(x + w_ / 2, by), (x + w_ / 2 + dirn * bl, by - bl * 0.5)], fill=col, width=rnd.randint(5, 10))

def leaf(draw, cx, cy, L, ang, col, outline=None):
    pts = []
    for t in range(0, 41):
        u = t / 40
        x = u * L
        y = math.sin(u * math.pi) * L * 0.22
        pts.append((x, y))
    for t in range(40, -1, -1):
        u = t / 40
        x = u * L
        y = -math.sin(u * math.pi) * L * 0.22
        pts.append((x, y))
    ca, sa = math.cos(ang), math.sin(ang)
    P = [(cx + x * ca - y * sa, cy + x * sa + y * ca) for x, y in pts]
    draw.polygon(P, fill=col, outline=outline)
    draw.line([(cx, cy), (cx + L * ca, cy + L * sa)], fill=outline or col, width=2)

def compass(draw, cx, cy, r, col, width=3):
    for k in range(8):
        a = k * math.pi / 4
        L = r if k % 2 == 0 else r * 0.6
        draw.line([(cx, cy), (cx + L * math.cos(a), cy + L * math.sin(a))], fill=col, width=width)
    draw.ellipse([cx - r * 0.12, cy - r * 0.12, cx + r * 0.12, cy + r * 0.12], outline=col, width=width)
    draw.ellipse([cx - r * 1.05, cy - r * 1.05, cx + r * 1.05, cy + r * 1.05], outline=col, width=width)

def gears(draw, cx, cy, r, teeth, col, width=6):
    pts = []
    for i in range(teeth * 2):
        a = i * math.pi / teeth
        rr = r if i % 2 == 0 else r * 0.82
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    draw.polygon(pts, outline=col, width=width)
    draw.ellipse([cx - r * 0.3, cy - r * 0.3, cx + r * 0.3, cy + r * 0.3], outline=col, width=width)

def constellation(draw, seed, n, col, region):
    rnd = random.Random(seed)
    x0, y0, x1, y1 = region
    pts = [(rnd.randint(x0, x1), rnd.randint(y0, y1)) for _ in range(n)]
    for i in range(n - 1):
        draw.line([pts[i], pts[i + 1]], fill=col, width=2)
    for x, y in pts:
        draw.ellipse([x - 6, y - 6, x + 6, y + 6], fill=col)
        draw.ellipse([x - 11, y - 11, x + 11, y + 11], outline=col, width=1)

def rain(draw, seed, col, n=400):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.randint(0, W), rnd.randint(0, H)
        L = rnd.randint(20, 60)
        draw.line([(x, y), (x - 6, y + L)], fill=col, width=1)

def sunburst(draw, cx, cy, n, col, r0, r1, width=3):
    for i in range(n):
        a = math.pi + i * math.pi / (n - 1)
        draw.line([(cx + r0 * math.cos(a), cy + r0 * math.sin(a)), (cx + r1 * math.cos(a), cy + r1 * math.sin(a))], fill=col, width=width)

def moon(draw, cx, cy, r, col, crescent=None):
    draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
    if crescent:
        draw.ellipse([cx - r + 40, cy - r - 25, cx + r + 40, cy + r - 25], fill=crescent)

def birds(draw, seed, col, n=9, region=(100, 200, 800, 600)):
    rnd = random.Random(seed)
    for _ in range(n):
        x, y = rnd.randint(region[0], region[2]), rnd.randint(region[1], region[3])
        s = rnd.randint(8, 18)
        draw.line([(x - s, y), (x, y + s * 0.5), (x + s, y)], fill=col, width=2)

# ----------------------------------------------------------------- designs

def finish(img, g=14, v=0.3):
    img = grain(img, g)
    return vignette(img, v)

def base_text(d, b, title_font, title_col, author_col, author_font="sans", author_size=44,
              title_y=None, title_maxw=720, title_maxh=520, start=128, tagline=None, tagline_col=None,
              tracking=0, author_tracking=4, shadow=None, author_y=None, series_y=None, series_col=None):
    fnt, lines, lh = fit_title(d, b["title"], title_font, title_maxw, title_maxh, start=start)
    if title_y is None:
        title_y = 170
    y = draw_lines(d, lines, fnt, lh, title_y, title_col, tracking=tracking, shadow=shadow)
    if tagline:
        small_caps_line(d, tagline.upper(), font("sans", 28), y + 28, tagline_col or author_col, tracking=6)
    ay = author_y if author_y is not None else H - 250
    small_caps_line(d, b["author"].upper(), font(author_font, author_size), ay, author_col, tracking=author_tracking)
    if b.get("series") and series_y is not None:
        small_caps_line(d, f"{b['series']} · book {b['series_index']}".upper(), font("sans", 26), series_y, series_col or author_col, tracking=5)
    return y

def design_mountains(b, pal):
    sky1, sky2, sun, m = [hexc(c) for c in pal[:4]]
    img = vgrad(sky1, sky2)
    d = ImageDraw.Draw(img)
    stars(d, 90, 3, ymax=600)
    moon(d, 690, 600, 85, sun)
    mountains(d, 4, 7, 760, [lerp(m, sky2, 0.55), lerp(m, sky2, 0.35), lerp(m, sky2, 0.15), m], jag=0.8)
    birds(d, 4, lerp(m, sky2, 0.1), n=6, region=(120, 250, 560, 500))
    img = finish(img)
    d = ImageDraw.Draw(img)
    base_text(d, b, "fserif_b", (250, 246, 236), (250, 246, 236), title_y=140, title_maxh=330, tagline="A novel", shadow=(0, 0, 0))
    imprint(d, b["publisher"], H - 110, (250, 246, 236))
    return img

def design_sea(b, pal):
    sky1, sky2, sea, fg = [hexc(c) for c in pal[:4]]
    img = vgrad(sky1, sky2)
    d = ImageDraw.Draw(img)
    stars(d, 50, 11, ymax=500)
    moon(d, 380, 600, 100, lerp(sky2, (255, 255, 255), 0.85))
    waves(d, 700, 6, 5, [lerp(sea, sky2, 0.6), lerp(sea, sky2, 0.45), lerp(sea, sky2, 0.3), lerp(sea, sky2, 0.15), sea, fg], amp=14)
    # lighthouse
    d.polygon([(760, 720), (800, 720), (812, 540), (748, 540)], fill=fg)
    d.rectangle([742, 520, 818, 545], fill=fg)
    d.rectangle([752, 480, 808, 522], fill=(255, 240, 180))
    d.polygon([(740, 480), (820, 480), (780, 445)], fill=fg)
    img = finish(img)
    d = ImageDraw.Draw(img)
    base_text(d, b, "serif_bi", (252, 250, 244), (252, 250, 244), title_y=130, start=118, title_maxh=330, tagline="A novel", shadow=(10, 10, 20))
    imprint(d, b["publisher"], H - 110, (252, 250, 244))
    return img

def design_city(b, pal):
    bg1, bg2, neon, build = [hexc(c) for c in pal[:4]]
    img = vgrad(bg1, bg2)
    d = ImageDraw.Draw(img)
    skyline(d, 1120, 21, lerp(build, bg2, 0.5))
    skyline(d, 1240, 22, build, win=lerp(neon, (255, 255, 255), 0.3))
    rain(d, 9, lerp(bg2, (255, 255, 255), 0.25), n=500)
    img = finish(img, g=20, v=0.4)
    d = ImageDraw.Draw(img)
    # neon title block
    fnt, lines, lh = fit_title(d, b["title"], "sans_b", 760, 520, start=140, spacing=0.98)
    y = 160
    for l in lines:
        tw = d.textlength(l, font=fnt)
        d.text(((W - tw) / 2 + 4, y + 4), l, font=fnt, fill=(0, 0, 0))
        d.text(((W - tw) / 2, y), l, font=fnt, fill=neon)
        y += lh
    small_caps_line(d, "A THRILLER", font("sans", 28), y + 26, (230, 230, 230), tracking=8)
    small_caps_line(d, b["author"].upper(), font("sans_b", 48), H - 250, (245, 245, 245), tracking=6)
    imprint(d, b["publisher"], H - 110, (200, 200, 200))
    return img

def design_constellation(b, pal):
    bg1, bg2, star, line = [hexc(c) for c in pal[:4]]
    img = rgrad(bg1, bg2, center=(0.5, 0.35), radius=1.0)
    d = ImageDraw.Draw(img)
    stars(d, 320, 17, color=star, big=True)
    constellation(d, 31, 9, line, (140, 560, 760, 1000))
    constellation(d, 32, 6, lerp(line, bg2, 0.4), (120, 900, 500, 1180))
    img = finish(img, g=10, v=0.2)
    d = ImageDraw.Draw(img)
    base_text(d, b, "serif", star, star, title_y=150, start=112, tagline="Poems", author_font="serif_i", author_size=46, author_tracking=3)
    rule(d, H - 170, lerp(star, bg2, 0.4))
    imprint(d, b["publisher"], H - 110, lerp(star, bg2, 0.2))
    return img

def design_botanical(b, pal):
    paper, ink, leafc, accent = [hexc(c) for c in pal[:4]]
    img = Image.new("RGB", (W, H), paper)
    d = ImageDraw.Draw(img)
    rnd = random.Random(41)
    for i in range(26):
        cx, cy = rnd.choice([rnd.randint(-40, 200), rnd.randint(700, 940)]), rnd.randint(-40, H + 40)
        ang = rnd.uniform(-math.pi, math.pi)
        L = rnd.randint(120, 260)
        col = lerp(leafc, paper, rnd.uniform(0, 0.35))
        leaf(d, cx, cy, L, ang, col, outline=lerp(leafc, ink, 0.3))
    for i in range(10):
        cx, cy = rnd.randint(200, 700), rnd.choice([rnd.randint(-60, 120), rnd.randint(1180, 1400)])
        leaf(d, cx, cy, rnd.randint(140, 240), rnd.uniform(-math.pi, math.pi), lerp(leafc, paper, 0.2), outline=lerp(leafc, ink, 0.3))
    d.rectangle([150, 380, 750, 900], fill=paper, outline=ink, width=3)
    d.rectangle([162, 392, 738, 888], outline=ink, width=1)
    img = finish(img, g=12, v=0.18)
    d = ImageDraw.Draw(img)
    fnt, lines, lh = fit_title(d, b["title"], "fserif_b", 520, 330, start=96, minsize=54)
    y = 640 - len(lines) * lh / 2 - 40
    y = draw_lines(d, lines, fnt, lh, y, ink)
    rule(d, y + 24, accent, width=2, inset=330)
    small_caps_line(d, b["author"].upper(), font("serif", 38), y + 48, ink, tracking=6)
    small_caps_line(d, "A NOVEL", font("sans", 24), 960, lerp(ink, paper, 0.3), tracking=8)
    imprint(d, b["publisher"], H - 90, ink)
    return img

def design_deco(b, pal):
    navy, gold, cream, deep = [hexc(c) for c in pal[:4]]
    img = vgrad(navy, deep)
    d = ImageDraw.Draw(img)
    sunburst(d, W / 2, 620, 33, lerp(gold, navy, 0.5), 150, 900, width=3)
    for r, wdt in ((140, 6), (170, 2), (200, 2)):
        d.ellipse([W / 2 - r, 620 - r, W / 2 + r, 620 + r], outline=gold, width=wdt)
    d.rectangle([60, 60, W - 60, H - 60], outline=gold, width=4)
    d.rectangle([76, 76, W - 76, H - 76], outline=gold, width=1)
    for y in (300, 1000):
        d.polygon([(W / 2 - 40, y), (W / 2, y - 18), (W / 2 + 40, y), (W / 2, y + 18)], fill=gold)
        d.line([(120, y), (W / 2 - 60, y)], fill=gold, width=2)
        d.line([(W / 2 + 60, y), (W - 120, y)], fill=gold, width=2)
    img = finish(img, g=10, v=0.25)
    d = ImageDraw.Draw(img)
    fnt, lines, lh = fit_title(d, b["title"], "fserif_b", 680, 300, start=110, minsize=56, spacing=1.0)
    draw_lines(d, lines, fnt, lh, 120, cream, tracking=3)
    small_caps_line(d, b["author"].upper(), font("sans", 44), 1040, gold, tracking=10)
    if b.get("series"):
        small_caps_line(d, f"{b['series']} · {b['series_index']}".upper(), font("sans", 24), 1110, lerp(gold, cream, 0.5), tracking=6)
    imprint(d, b["publisher"], H - 120, gold)
    return img

def design_minimal(b, pal):
    bg, ink, accent, obj = [hexc(c) for c in pal[:4]]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    # a door with light
    d.rectangle([330, 560, 570, 1010], fill=obj)
    d.rectangle([350, 580, 550, 1010], fill=lerp(obj, bg, 0.2))
    d.polygon([(350, 1010), (550, 1010), (760, 1150), (140, 1150)], fill=lerp(accent, bg, 0.6))
    d.ellipse([520, 790, 536, 806], fill=accent)
    img = finish(img, g=8, v=0.12)
    d = ImageDraw.Draw(img)
    fnt, lines, lh = fit_title(d, b["title"], "serif", 700, 380, start=120, minsize=64, spacing=1.02)
    draw_lines(d, lines, fnt, lh, 120, ink, align="left", x=100)
    d.line([(100, 120 + len(lines) * lh + 20), (260, 120 + len(lines) * lh + 20)], fill=accent, width=5)
    d.text((100, H - 190), b["author"], font=font("sans", 44), fill=ink)
    d.text((100, H - 130), "A NOVEL", font=font("sans", 24), fill=lerp(ink, bg, 0.4))
    imprint(d, b["publisher"], H - 70, lerp(ink, bg, 0.3), symbol=False)
    return img

def design_typo(b, pal):
    bg, ink, accent, _ = [hexc(c) for c in pal[:4]]
    img = Image.new("RGB", (W, H), bg)
    d = ImageDraw.Draw(img)
    fnt, lines, lh = fit_title(d, b["title"].upper(), "sans_b", 800, 760, start=210, minsize=110, spacing=0.9)
    y = 110
    for i, l in enumerate(lines):
        d.text((50, y), l, font=fnt, fill=accent if i == len(lines) - 1 else ink)
        y += lh
    d.rectangle([50, y + 30, W - 50, y + 36], fill=ink)
    d.text((50, y + 70), b["author"].upper(), font=font("sans_b", 56), fill=ink)
    d.text((50, y + 150), "THE INTERNATIONAL BESTSELLER", font=font("sans", 26), fill=lerp(ink, bg, 0.35))
    img = finish(img, g=8, v=0.1)
    d = ImageDraw.Draw(img)
    imprint(d, b["publisher"], H - 70, lerp(ink, bg, 0.3), symbol=False)
    return img

def design_planet(b, pal):
    bg1, bg2, planet, ring = [hexc(c) for c in pal[:4]]
    img = vgrad(bg1, bg2)
    d = ImageDraw.Draw(img)
    stars(d, 260, 23, big=True)
    cx, cy, r = 450, 1120, 520
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=planet)
    d.ellipse([cx - r + 40, cy - r + 40, cx + r - 200, cy + r - 200], fill=lerp(planet, (255, 255, 255), 0.12))
    for k in range(3):
        rr = r + 60 + k * 30
        d.ellipse([cx - rr, cy - rr * 0.28, cx + rr, cy + rr * 0.28], outline=ring, width=4 - k)
    img = finish(img, g=12, v=0.25)
    d = ImageDraw.Draw(img)
    base_text(d, b, "sans_b", (245, 247, 255), (245, 247, 255), title_y=120, start=124, author_y=560,
              series_y=620, series_col=lerp(ring, (255, 255, 255), 0.4), tracking=2)
    imprint(d, b["publisher"], H - 90, (220, 225, 240))
    return img

def design_forest(b, pal):
    fog1, fog2, tree, ink = [hexc(c) for c in pal[:4]]
    img = vgrad(fog1, fog2)
    d = ImageDraw.Draw(img)
    trees(d, 51, H, lerp(tree, fog2, 0.6), n=12)
    trees(d, 52, H, lerp(tree, fog2, 0.35), n=10)
    trees(d, 53, H, tree, n=7)
    img = img.filter(ImageFilter.GaussianBlur(0.6))
    img = finish(img, g=14, v=0.3)
    d = ImageDraw.Draw(img)
    base_text(d, b, "fserif_b", ink, ink, title_y=130, start=120, shadow=lerp(fog2, (0, 0, 0), 0.6), series_y=H - 190, author_y=H - 250)
    imprint(d, b["publisher"], H - 100, ink)
    return img

def design_gears(b, pal):
    bg1, bg2, brass, ink = [hexc(c) for c in pal[:4]]
    img = rgrad(bg1, bg2, center=(0.5, 0.6), radius=1.1)
    d = ImageDraw.Draw(img)
    gears(d, 640, 980, 260, 16, lerp(brass, bg2, 0.5), width=8)
    gears(d, 260, 1180, 180, 12, lerp(brass, bg2, 0.4), width=7)
    gears(d, 780, 560, 120, 10, lerp(brass, bg2, 0.55), width=6)
    compass(d, 240, 640, 130, brass, width=4)
    img = finish(img, g=16, v=0.3)
    d = ImageDraw.Draw(img)
    base_text(d, b, "fserif_b", ink, brass, title_y=140, start=118, tagline=f"{b['series']} · Book {b['series_index']}" if b.get("series") else "A novel", tagline_col=brass, shadow=(0, 0, 0))
    imprint(d, b["publisher"], H - 110, brass)
    return img

def design_map(b, pal):
    paper, ink, water, red = [hexc(c) for c in pal[:4]]
    img = Image.new("RGB", (W, H), paper)
    d = ImageDraw.Draw(img)
    rnd = random.Random(77)
    # contour lines
    for k in range(18):
        cx, cy = rnd.randint(0, W), rnd.randint(0, H)
        for r in range(40, 400, 34):
            d.ellipse([cx - r * 1.4, cy - r, cx + r * 1.4, cy + r], outline=lerp(ink, paper, 0.75), width=1)
    # grid
    for x in range(0, W, 90):
        d.line([(x, 0), (x, H)], fill=lerp(ink, paper, 0.85), width=1)
    for y in range(0, H, 90):
        d.line([(0, y), (W, y)], fill=lerp(ink, paper, 0.85), width=1)
    d.line([(120, 1180), (300, 1010), (420, 1080), (610, 860), (760, 900)], fill=red, width=4)
    for x, y in ((120, 1180), (610, 860), (760, 900)):
        d.ellipse([x - 8, y - 8, x + 8, y + 8], fill=red)
    compass(d, 720, 300, 90, ink, width=3)
    d.rectangle([90, 470, 810, 760], fill=paper, outline=ink, width=3)
    img = finish(img, g=14, v=0.2)
    d = ImageDraw.Draw(img)
    fnt, lines, lh = fit_title(d, b["title"], "fserif_b", 660, 240, start=100, minsize=54)
    y = 615 - len(lines) * lh / 2
    draw_lines(d, lines, fnt, lh, y, ink)
    small_caps_line(d, b["author"].upper(), font("serif", 40), 790, ink, tracking=6)
    small_caps_line(d, "AN EXPEDITION IN THREE PARTS", font("sans", 22), 850, lerp(ink, paper, 0.3), tracking=5)
    imprint(d, b["publisher"], H - 90, ink)
    return img

def design_letters(b, pal):
    bg, ink, accent, fade = [hexc(c) for c in pal[:4]]
    img = vgrad(bg, lerp(bg, (0, 0, 0), 0.25))
    d = ImageDraw.Draw(img)
    skyline(d, 1350, 61, lerp(fade, bg, 0.2))
    waves(d, 1040, 5, 62, [lerp(accent, bg, 0.5), lerp(accent, bg, 0.35), lerp(accent, bg, 0.2), accent, lerp(accent, (0, 0, 0), 0.2)], amp=10, wl=140)
    img = finish(img, g=14, v=0.3)
    d = ImageDraw.Draw(img)
    base_text(d, b, "serif_i", ink, ink, title_y=160, start=112, tagline="Poems", author_font="serif", author_size=42, author_y=H - 260, shadow=(0, 0, 0))
    imprint(d, b["publisher"], H - 110, ink)
    return img

DESIGNS = {
    "mountains": design_mountains, "sea": design_sea, "city": design_city,
    "constellation": design_constellation, "botanical": design_botanical, "deco": design_deco,
    "minimal": design_minimal, "typo": design_typo, "planet": design_planet, "forest": design_forest,
    "gears": design_gears, "map": design_map, "letters": design_letters,
}

def render(b):
    img = DESIGNS[b["design"]](b, b["pal"])
    # subtle spine shadow on the left edge
    d = ImageDraw.Draw(img, "RGBA")
    for i in range(28):
        d.line([(i, 0), (i, H)], fill=(0, 0, 0, int(60 * (1 - i / 28))))
    path = os.path.join(OUT, b["slug"] + ".jpg")
    img.save(path, quality=88)
    return path

if __name__ == "__main__":
    sys.path.insert(0, os.path.dirname(__file__))
    from books import BOOKS
    paths = [render(b) for b in BOOKS]
    # contact sheet
    cols = 6
    tw, th = 200, 300
    rows = math.ceil(len(paths) / cols)
    sheet = Image.new("RGB", (cols * (tw + 12) + 12, rows * (th + 12) + 12), (40, 40, 40))
    for i, p in enumerate(paths):
        im = Image.open(p).resize((tw, th), Image.LANCZOS)
        sheet.paste(im, (12 + (i % cols) * (tw + 12), 12 + (i // cols) * (th + 12)))
    sheet.save(os.path.join(os.path.dirname(__file__), "contact.png"))
    print("rendered", len(paths))
