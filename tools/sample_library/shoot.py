"""Set reading state on the sample library and take the README screenshots."""
import os, sqlite3, sys, time
from datetime import datetime, timedelta
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(__file__)
DATA = os.path.join(HERE, "data")
OUT = os.path.join(HERE, "png")
os.makedirs(OUT, exist_ok=True)
BASE = "http://127.0.0.1:5056"

def set_states():
    con = sqlite3.connect(os.path.join(DATA, "colophon.db"))
    cur = con.cursor()
    now = datetime.utcnow()
    def ts(d): return d.strftime("%Y-%m-%d %H:%M:%S.%f")
    def item(slug):
        r = cur.execute("SELECT id FROM library_items WHERE file_path LIKE ?", (f"%{slug}.epub",)).fetchone()
        return r[0]
    reading = [
        ("the-clockwork-cartographer", 12.0, now - timedelta(hours=5), now - timedelta(days=3)),
    ]
    for slug, prog, mod, started in reading:
        cur.execute("UPDATE library_items SET read_status='Reading', read_progress=?, read_last_modified=?, read_started_at=? WHERE id=?",
                    (prog, ts(mod), ts(started), item(slug)))
    for slug in ("iron-orchids", "a-theory-of-small-disasters", "letters-to-a-drowning-city", "signal-in-the-static", "the-winter-orchard"):
        cur.execute("UPDATE library_items SET read_status='Finished', read_progress=100, read_last_modified=?, read_started_at=? WHERE id=?",
                    (ts(now - timedelta(days=20)), ts(now - timedelta(days=30)), item(slug)))
    ratings = {"the-clockwork-cartographer": 5, "iron-orchids": 4, "a-theory-of-small-disasters": 4,
               "letters-to-a-drowning-city": 3, "signal-in-the-static": 4, "gardens-of-rust-and-salt": 5,
               "quiet-engines": 3, "maps-of-the-unbuilt": 4, "constellations-for-the-sleepless": 4,
               "the-cartographers-daughter": 5, "what-the-river-kept": 4, "hollow-engines-bright-sparks": 3}
    for slug, r in ratings.items():
        cur.execute("UPDATE library_items SET user_rating=? WHERE id=?", (r, item(slug)))
    # Make "New" badge appear on two recent books, the rest older.
    cur.execute("UPDATE library_items SET created_at=?", (ts(now - timedelta(days=90)),))
    for slug in ("a-clockwork-tide", "the-last-honest-map", "the-glass-arithmetic", "the-orchard-of-lost-keys", "the-salt-cathedral", "what-the-river-kept"):
        cur.execute("UPDATE library_items SET created_at=? WHERE id=?", (ts(now - timedelta(days=2)), item(slug)))
    con.commit()
    cid = item("the-clockwork-cartographer")
    con.close()
    return cid

def shoot(cid):
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, device_scale_factor=1)
        ctx.add_cookies([{"name": "colophon_lang", "value": "en", "url": BASE}])
        page = ctx.new_page()

        page.set_viewport_size({"width": 1440, "height": 1040})
        page.goto(f"{BASE}/metadata/bulk?view=shelf", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(OUT, "library-shelf.png"))
        page.set_viewport_size({"width": 1440, "height": 900})

        page.goto(f"{BASE}/metadata/bulk?view=table", wait_until="networkidle")
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(OUT, "library-table.png"))

        page.goto(f"{BASE}/metadata/bulk?view=shelf", wait_until="networkidle")
        page.wait_for_timeout(800)
        page.locator(f'.grid-card[data-item-id="{cid}"] .grid-card-cover').first.click()
        page.wait_for_timeout(1500)
        page.screenshot(path=os.path.join(OUT, "book-detail.png"))

        page.goto(f"{BASE}/reader/{cid}", wait_until="networkidle")
        page.wait_for_timeout(4000)
        page.screenshot(path=os.path.join(OUT, "reader.png"))
        browser.close()

if __name__ == "__main__":
    cid = set_states()
    print("clockwork id", cid)
    shoot(cid)
    print("done")
