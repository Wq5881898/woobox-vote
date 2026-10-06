import io,sys
sys.stdout.reconfigure(encoding='utf-8',errors='replace')
from playwright.sync_api import sync_playwright
US=open('woobox-item-fix.user.js',encoding='utf-8').read()
with sync_playwright() as p:
    b=p.chromium.launch(); c=b.new_context(); pg=c.new_page()
    pg.on('console',lambda m:print('CONSOLE',m.type,m.text[:200]))
    pg.on('pageerror',lambda e:print('PAGEERROR',str(e)[:300]))
    pg.goto('https://woobox.com/4rq96i/gallery/xpgroevp',wait_until='domcontentloaded',timeout=60000)
    pg.wait_for_function("() => typeof window.renderGallery === 'function'",timeout=30000)
    print('before eval:',pg.evaluate("() => ({cards:document.querySelectorAll('#gallery-grid .gallery-card').length, kids:document.getElementById('gallery-grid').children.length})"))
    out=pg.evaluate("() => { window.__err=[]; addEventListener('error',e=>__err.push(String(e.message))); return 'armed'; }")
    r=pg.evaluate("("+US+"\n)")   # force expression evaluation of the IIFE
    pg.wait_for_timeout(1500)
    print('eval ret:',repr(r)[:80])
    print('after eval:',pg.evaluate("""() => ({cards:document.querySelectorAll('#gallery-grid .gallery-card').length,
        kids:document.getElementById('gallery-grid').children.length,
        html:document.getElementById('gallery-grid').innerHTML.slice(0,200),
        wrapper:(''+window.renderGallery).slice(0,60),
        err:window.__err, bar:(document.getElementById('wbk-bar')||{}).textContent||''})"""))
    pg.wait_for_timeout(4000)
    print('later:',pg.evaluate("() => ({cards:document.querySelectorAll('#gallery-grid .gallery-card').length, kids:document.getElementById('gallery-grid').children.length})"))
    b.close()
