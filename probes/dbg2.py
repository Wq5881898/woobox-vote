import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

JS = r"""() => {
  const it = window.__SITE__.gallery.item, g = document.getElementById('gallery-grid');
  g.innerHTML = '';
  let err = null;
  try { window.renderGallery([it]); } catch (e) { err = e.name + ': ' + e.message + ' @ ' + (e.stack || '').split('\n')[1]; }
  return {err: err, cards: g.children.length, keys: Object.keys(it),
          html: g.innerHTML.slice(0, 160),
          voted: (window.__SITE__.result_votes || []).indexOf(it.id) !== -1};
}"""

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context().new_page()
    pg.on('pageerror', lambda e: print('PAGEERROR', str(e)[:200]))
    pg.goto('https://woobox.com/4rq96i/gallery/xpgroevp', wait_until='domcontentloaded', timeout=60000)
    pg.wait_for_function("() => typeof window.renderGallery === 'function'", timeout=30000)
    print(pg.evaluate(JS))
    b.close()
