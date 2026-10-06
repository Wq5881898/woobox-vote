import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

BASE = 'https://woobox.com/4rq96i/gallery/xpgroevp'
CASES = {
    'plain': BASE,
    '#gallery-section': BASE + '#gallery-section',
    '#:~:text=(JS-rendered caption)': BASE + '#:~:text=Hanna%20-%20Elementary',
    '#gallery-section:~:text=(anchor+text)': BASE + '#gallery-section:~:text=Hanna%20-%20Elementary',
    '#:~:text=(text present at load)': BASE + '#:~:text=Reduce%2C%20Reuse%2C%20Recycle',
}

with sync_playwright() as p:
    b = p.chromium.launch()
    for name, url in CASES.items():
        pg = b.new_context(viewport={'width': 390, 'height': 844}).new_page()
        pg.goto(url, wait_until='domcontentloaded', timeout=60000)
        try:
            pg.wait_for_selector('#gallery-grid .gallery-card', timeout=20000)
        except Exception:
            pass
        pg.wait_for_timeout(2000)
        early = pg.evaluate('() => Math.round(window.scrollY)')
        pg.wait_for_timeout(8000)
        late = pg.evaluate('''() => ({y:Math.round(window.scrollY),
                            galleryTop: Math.round((document.getElementById('gallery-section')||{getBoundingClientRect:()=>({top:0})}).getBoundingClientRect().top+window.scrollY),
                            docH: document.documentElement.scrollHeight})''')
        print('%-42s early=%-6s late=%-6s gallerySectionAt=%-7s docH=%s' %
              (name, early, late['y'], late['galleryTop'], late['docH']))
        pg.close()
    b.close()
