import sys, pathlib, re, threading, http.server, socketserver, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, 'site')


class Q(http.server.SimpleHTTPRequestHandler):
    def __init__(self, *a, **kw):
        super().__init__(*a, directory=SITE, **kw)

    def log_message(self, *a):
        pass


srv = socketserver.TCPServer(('127.0.0.1', 0), Q)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()
BASE = 'http://127.0.0.1:%d' % port

with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(viewport={'width': 1280, 'height': 900}).new_page()
    msgs = []
    pg.on('console', lambda m: msgs.append('[%s] %s' % (m.type, m.text[:200])))
    pg.on('pageerror', lambda e: msgs.append('PAGEERROR %s' % str(e)[:400]))
    for url in ('/index.html', '/v/xpgroevp.html'):
        msgs.clear()
        pg.goto(BASE + url, wait_until='load', timeout=60000)
        pg.wait_for_timeout(3000)
        print('=' * 25, url)
        for m in msgs:
            print('  ', m)
        print('   state:', pg.evaluate("""() => ({
            cards: document.querySelectorAll('#grid .it').length,
            hasDATA: typeof DATA!=='undefined' && (DATA.length||0),
            inline: !!document.getElementById('inline'),
            frame: !!document.getElementById('frame'),
            rank: document.querySelectorAll('#rank span').length,
            votewin: (document.getElementById('votewin')||{}).href})"""))
        if url.endswith('xpgroevp.html'):
            r = pg.evaluate("""() => {const b=document.getElementById('inline');
                let err=null; try{b.click()}catch(e){err=String(e)}
                const f=document.getElementById('frame');
                return {err:err, cls:f.className, src:f.src, js:b.textContent};}""")
            print('   inline click:', r)
            pg.wait_for_timeout(6000)
            print('   after wait:', pg.evaluate("""() => {const f=document.getElementById('frame');
                return {cls:f.className,src:f.src,h:Math.round(f.getBoundingClientRect().height),styleH:f.style.height,
                frames:window.frames.length};}"""))
            print('   page scripts:', pg.evaluate("() => [...document.scripts].map(s=>s.src||('inline:'+s.textContent.length))"))
    b.close()
    srv.shutdown()
