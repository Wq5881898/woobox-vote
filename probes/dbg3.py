import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context().new_page()
    pg.goto('https://woobox.com/4rq96i/gallery', wait_until='domcontentloaded', timeout=60000)
    pg.wait_for_selector('#gallery-grid .gallery-card', timeout=30000)
    pg.wait_for_timeout(2000)
    print(pg.evaluate("""() => {
      const cards=[...document.querySelectorAll('#gallery-grid .gallery-card')];
      return {n:cards.length,
        buttons:cards.map(c=>{const b=c.querySelector('.btn-vote');return b?(b.classList.contains('voted')?'VOTED':'vote'):'none'}),
        rv:window.__SITE__.result_votes,
        sdk:typeof WooboxSDK.vote, api:window.__SITE__.settings.api_base};
    }"""))
    b.close()
