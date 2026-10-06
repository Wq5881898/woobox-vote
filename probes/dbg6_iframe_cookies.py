"""Does the in-page (iframe) vote still work when the browser partitions or
blocks cookie storage for embedded frames, the way Safari/ITP, Firefox ETP and
WeChat's built-in browser do?

Chromium's --test-third-party-cookie-phase-out emulates the partitioning that
those browsers apply by default. A real vote is cast; the /vote response body is
printed so the outcome is auditable.
"""
import sys, threading, re, http.server, socketserver, os
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
from playwright.sync_api import sync_playwright

SITE = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'site'))


class Q(http.server.SimpleHTTPRequestHandler):
    def __init__(s, *a, **k):
        super().__init__(*a, directory=SITE, **k)

    def log_message(s, *a):
        pass


srv = socketserver.TCPServer(('127.0.0.1', 0), Q)
port = srv.server_address[1]
threading.Thread(target=srv.serve_forever, daemon=True).start()

for name, args in [('default chromium', []),
                   ('3P cookies partitioned/blocked', ['--test-third-party-cookie-phase-out',
                                                       '--block-third-party-cookies'])]:
    with sync_playwright() as p:
        b = p.chromium.launch(args=args)
        pg = b.new_context(viewport={'width': 390, 'height': 844}).new_page()
        box = {}

        def on_resp(r):
            if r.url.rstrip('/').endswith('/vote'):        # not our own votes.json
                try:
                    box['status'] = r.status
                    box['body'] = r.text()[:200]
                except Exception as e:
                    box['body'] = 'unreadable: %s' % e

        pg.on('response', on_resp)
        def stub(route):
            req = route.request
            box.update(url=req.url, method=req.method,
                       same_origin=req.url.split('/')[2] == 'woobox.com',
                       cookie_header=bool(req.headers.get('cookie')),
                       referer=(req.headers.get('referer') or '')[:48],
                       body_fields=sorted(__import__('json').loads(req.post_data or '{}').keys()))
            route.fulfill(status=200, content_type='application/json',
                          body='{"success":true,"votes":9999}')

        # stub the real POST so this probe costs the contest no votes, while still
        # proving what the embedded page actually sends (same-origin, cookie, _csrf)
        pg.route(re.compile(r'/site_api/[^/]+/vote'), stub)
        pg.goto('http://127.0.0.1:%d/v/xpgroevp.html' % port, wait_until='load', timeout=60000)
        pg.wait_for_timeout(1500)
        pg.evaluate("() => document.getElementById('inline').click()")
        try:
            pg.wait_for_function("() => {for (const f of document.querySelectorAll('iframe')) "
                                 "if (f.contentDocument && f.contentDocument.querySelector('.btn-vote')) return true; return false;}",
                                 timeout=30000)
        except Exception:
            pass
        fr = [f for f in pg.frames if '4rq96i/gallery/' in (f.url or '')]
        out = {'frame': bool(fr)}
        if fr:
            f = fr[0]
            try:
                f.wait_for_selector('.btn-vote', timeout=30000)
            except Exception:
                pass
            out['cookies_visible_in_frame'] = f.evaluate("() => document.cookie.length")
            r = f.evaluate("""async () => {
                // an already-voted button has NO click handler in app.js, so clicking
                // one proves nothing: pick a card this visitor has not voted for.
                const cards=[...document.querySelectorAll('.gallery-card')];
                const c=cards.find(c=>{const b=c.querySelector('.btn-vote');
                    return b && !b.classList.contains('voted') && !b.disabled;});
                if(!c) return {error:'every visible card is already voted by this visitor'};
                const b=c.querySelector('.btn-vote');
                const cap=(c.querySelector('.gallery-caption')||{}).textContent||'?';
                const before={txt:b.textContent.trim(),disabled:b.disabled,count:(c.querySelector('.vote-count')||{}).textContent};
                b.click(); await new Promise(r=>setTimeout(r,2500));
                return {entry:cap.trim(), before:before,
                        after:{txt:b.textContent.trim(),disabled:b.disabled,
                              count:(c.querySelector('.vote-count')||{}).textContent}};}""")
            out['click'] = r
        out['the_post_only_woobox_itself_can_make'] = box
        print('%-34s %s' % (name, out))
        b.close()
srv.shutdown()
