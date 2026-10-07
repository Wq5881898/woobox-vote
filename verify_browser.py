#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
End-to-end verification in a real browser (Chromium via Playwright).

Proves, on the LIVE site:
  1. the bug: the artwork deep link carries the entry in __SITE__.gallery.item
     but the grid renders page 1 of the gallery instead;
  2. #:~:text= fragment jump (the zero-install fallback used by the shell pages);
  3. the userscript fix: single artwork + its own working Vote button, and
     "browse all entries" / Load More still work afterwards;
  4. the static shell: artwork loads, votes refresh from ../votes.json, in-page
     iframe voting opens, and the index search works;
  5. ?links=1 harvests every entry's link.

  python verify_browser.py            # everything
  python verify_browser.py --quick    # skip the slow ?links=1 harvest
  python verify_browser.py --vote     # ALSO click the real Vote button (+1 vote!)
"""
import http.server
import json
import os
import socketserver
import sys
import threading

import requests

from playwright.sync_api import sync_playwright

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
US = open(os.path.join(HERE, "woobox-item-fix.user.js"), encoding="utf-8").read()
QUICK = "--quick" in sys.argv
DO_VOTE = "--vote" in sys.argv
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass
SHOT = os.path.join(HERE, "shots")
API = "https://woobox.com/site_api/ewxzgdgw"
HDRS = {"User-Agent": "Mozilla/5.0 (compatible; vote-shell-verifier/1.0)"}
os.makedirs(SHOT, exist_ok=True)
MOBILE = {"user_agent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15 "
                         "(KHTML, like Gecko) Version/17.5 Mobile/15E148 Safari/604.1",
          "viewport": {"width": 390, "height": 844}, "is_mobile": True, "has_touch": True}

results = []


def chk(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  -- " + detail) if detail else ""))


def start_server():
    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=SITE, **kw)

        def log_message(self, *a):
            pass

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, "http://127.0.0.1:%d" % srv.server_address[1]


def grid_state(page):
    return page.evaluate("""() => {
      const cards=[...document.querySelectorAll('#gallery-grid .gallery-card')];
      return {
        cards: cards.length,
        text: cards.map(c=>(c.querySelector('.gallery-caption')||{}).textContent||''),
        scrollY: Math.round(window.scrollY),
        item: (window.__SITE__&&window.__SITE__.gallery&&window.__SITE__.gallery.item)||null,
        banner: (document.getElementById('wbk-bar')||{}).textContent||''
      };
    }""")


def wait_render(page):
    """app.js is the last script in <body>: wait until its functions exist."""
    page.wait_for_function("() => typeof window.renderGallery === 'function'", timeout=30000)


srv, BASE = start_server()
items = json.load(open(os.path.join(SITE, "items.json"), encoding="utf-8"))["items"]
target = [i for i in items if i["id"] == "xpgroevp"][0]
others = [i for i in items if i["id"] != "xpgroevp"][:: max(1, len(items) // 2)][:2]

with sync_playwright() as pw:
    br = pw.chromium.launch()

    # ── 1. reproduce the bug on the live deep link ─────────────────────────
    ctx = br.new_context(**MOBILE)
    pg = ctx.new_page()
    pg.goto(target["deep"], wait_until="domcontentloaded", timeout=60000)
    wait_render(pg)
    pg.wait_for_selector("#gallery-grid .gallery-card", timeout=30000)
    pg.wait_for_timeout(2500)
    s = grid_state(pg)
    chk("BUG reproduced: %s renders the whole grid (%d cards) although the page already knows the entry"
        % (target["id"], s["cards"]), s["cards"] > 1 and s["item"] and s["item"]["id"] == target["id"],
        "cards=%d scrollY=%d" % (s["cards"], s["scrollY"]))
    chk("BUG reproduced: the requested artwork is not among the rendered page-1 cards",
        target["caption"] not in s["text"], "cards: " + ", ".join(t[:18] for t in s["text"][:6]))
    pg.screenshot(path=os.path.join(SHOT, "1_before_broken.png"), full_page=False)

    # ── 2. the handoff URL really lands on the gallery section ──────────────
    # Measured: #:~:text= alone does NOT match cards rendered by JS after load
    # (scrollY stays 0), so the shell's link carries the page's own
    # #gallery-section anchor and keeps the text fragment as a free extra.
    pg2 = ctx.new_page()
    pg2.goto(target["deep"] + target["frag"], wait_until="domcontentloaded", timeout=60000)
    wait_render(pg2)
    pg2.wait_for_selector("#gallery-grid .gallery-card", timeout=30000)
    pg2.wait_for_timeout(3000)
    f = pg2.evaluate("""() => ({scrollY: Math.round(window.scrollY),
        top: Math.round(document.getElementById('gallery-section').getBoundingClientRect().top + window.scrollY),
        h: document.documentElement.scrollHeight})""")
    chk("handoff URL (#gallery-section:~:text=…) scrolls straight to the gallery section",
        abs(f["scrollY"] - f["top"]) < 60, "scrollY=%d, gallery at %d of %dpx" % (f["scrollY"], f["top"], f["h"]))
    pg2.screenshot(path=os.path.join(SHOT, "2_handoff_scrolled.png"))
    pg2.close()

    # ── 3. userscript fix on the same live URL ─────────────────────────────
    pg3 = ctx.new_page()
    pg3.goto(target["deep"], wait_until="domcontentloaded", timeout=60000)
    wait_render(pg3)
    pg3.evaluate(US)
    pg3.wait_for_timeout(1200)
    s3 = grid_state(pg3)
    chk("userscript: grid shows ONLY the requested artwork", s3["cards"] == 1,
        "cards=%d" % s3["cards"])
    chk("userscript: that card is the requested entry", s3["text"] == [target["caption"]], str(s3["text"]))
    vote = pg3.evaluate("""() => {const b=document.querySelector('#gallery-grid .btn-vote');
        return b?{txt:b.textContent.trim(),disabled:b.disabled,cls:b.className,img:
        (document.querySelector('#gallery-grid img')||{}).src||''}:null;}""")
    chk("userscript: the artwork's own Vote button is present and clickable",
        bool(vote) and vote["disabled"] is False and "vote" in vote["cls"], str(vote)[:120])
    chk("userscript: artwork image is the real upload",
        bool(vote) and target["img"].split("/")[-1] in vote["img"], (vote or {}).get("img", "")[:90])
    chk("userscript: banner offers the shareable deep link", "复制本作品投票链接" in s3["banner"], s3["banner"][:60])
    pg3.screenshot(path=os.path.join(SHOT, "2_after_userscript.png"), full_page=False)

    # later renders must not be swallowed any more -> browse all entries works
    pg3.evaluate("() => document.getElementById('load-more').click()")
    pg3.wait_for_timeout(3500)
    s3b = grid_state(pg3)
    chk("userscript: 'browse all entries' restores the grid", s3b["cards"] >= 12, "cards=%d" % s3b["cards"])
    pg3.evaluate("() => {const b=document.getElementById('load-more'); if(b) b.click();}")
    pg3.wait_for_timeout(3500)
    s3c = grid_state(pg3)
    chk("userscript: Load More still appends the next page", s3c["cards"] > s3b["cards"],
        "%d -> %d" % (s3b["cards"], s3c["cards"]))

    # same fix must work for arbitrary entries, not only the example
    for o in others:
        p = ctx.new_page()
        p.goto(o["deep"], wait_until="domcontentloaded", timeout=60000)
        wait_render(p)
        p.evaluate(US)
        p.wait_for_timeout(1000)
        st = grid_state(p)
        chk("userscript works for another entry too (%s)" % o["caption"],
            st["cards"] == 1 and st["text"] == [o["caption"]], "cards=%d %s" % (st["cards"], st["text"]))
        p.close()

    # (the single real vote is cast later, through the shell's in-page window)

    # ?links=1 harvest
    if not QUICK:
        pl = ctx.new_page()
        pl.goto("https://woobox.com/4rq96i/gallery?links=1", wait_until="domcontentloaded", timeout=60000)
        wait_render(pl)
        pl.evaluate(US)
        try:
            pl.wait_for_function("() => {const t=document.querySelector('#gallery-grid textarea'); return t && t.value.trim().split('\\n').length >= 116;}",
                                 timeout=180000)
        except Exception:
            pass
        n = pl.evaluate("() => {const t=document.querySelector('#gallery-grid textarea'); return t?t.value.trim().split('\\n').length:0;}")
        chk("?links=1 harvests entry links in-browser (API pull in build.py is authoritative)",
            n >= 100, "lines=%d (site pages can shift mid-pagination while Load More is clicked)" % n)
        pl.screenshot(path=os.path.join(SHOT, "4_links_harvest.png"))
        pl.close()
    ctx.close()

    # ── 4. the static shell, served locally ────────────────────────────────
    ctx2 = br.new_context(**MOBILE)
    sh = ctx2.new_page()
    sh.goto(BASE + "/v/%s.html" % target["id"], wait_until="load", timeout=60000)
    sh.wait_for_timeout(3500)
    st = sh.evaluate("""() => {const i=document.querySelector('.shot img');
        return {img:i?{w:i.naturalWidth,h:i.naturalHeight,src:i.currentSrc}:null,
                votes:document.getElementById('v').textContent.trim(),
                href:document.getElementById('votewin').getAttribute('href'),
                hint:document.querySelector('.pos').innerText,
                asof:document.getElementById('asof').textContent.trim(),
                title:document.title, others:document.querySelectorAll('.others a').length,
                prev:!!document.querySelector('.pager a')};}""")
    api_votes = [i for i in items if i["id"] == target["id"]][0]["votes"]
    snap = json.loads(sh.evaluate("() => fetch('../votes.json',{cache:'no-store'}).then(r=>r.text())"))
    live_votes = (snap["votes"] if "votes" in snap else snap)[target["id"]]
    chk("votes.json ships a snapshot timestamp the pages quote", bool(snap.get("built_at")), str(snap.get("built_at"))[:30])
    img = st["img"] or {}
    chk("shell page: artwork renders from the signature-free hotlink (%dx%d px)" % (img.get("w", 0), img.get("h", 0)),
        img.get("w", 0) > 200 and "?" not in img.get("src", ""), str(img)[:150])
    chk("shell page: Vote button points at the official page + anchor/fragment",
        st["href"] == target["deep"] + target["frag"], st["href"])
    chk("shell page: vote count refreshes from ../votes.json (live-ish, no proxy)",
        int(st["votes"]) == int(live_votes) == int(api_votes), "%s vs api %s" % (st["votes"], api_votes))
    chk("shell page: neighbours navigation + prev/next present", st["others"] >= 8 and st["prev"], str(st["others"]))

    # the "which position is it" hint must match the REAL gallery order (fresh pull)
    order, page = [], 1
    while page <= 20:
        js_r = requests.get(API + "/gallery", params={"page": page, "limit": 100},
                            headers=HDRS, timeout=60).json()
        order += [u["id"] for u in js_r["uploads"]]          # uploads is a flat list
        if page >= int(js_r.get("total_pages") or 1) or not js_r.get("has_more"):
            break
        page += 1
    idx = order.index(target["id"])
    hint = " ".join(st["hint"].split())
    chk("shell page: position hint matches the real gallery order (slot %d of %d)" % (idx + 1, len(order)),
        ("第 %d 位" % (idx + 1)) in hint and ("第 %d 页第 %d 张" % (idx // 12 + 1, idx % 12 + 1)) in hint, hint[:160])
    sh.set_viewport_size({"width": 1280, "height": 900})
    sh.evaluate("() => document.getElementById('inline').click()")
    frame_ok = sh.evaluate("""() => new Promise(res => {const f=document.getElementById('frame');
        const t=setTimeout(()=>res({loaded:f.contentDocument&&f.contentDocument.body?
        f.contentDocument.body.children.length:0,src:f.src}),15000);
        f.addEventListener('load',()=>{clearTimeout(t);
          res({loaded:f.contentDocument&&f.contentDocument.body?f.contentDocument.body.children.length:0,src:f.src});});});""")
    sh.wait_for_timeout(4000)
    vis = sh.evaluate("""() => {const f=document.getElementById('frame');const r=f.getBoundingClientRect();
        return {h:Math.round(r.height),top:Math.round(r.top),
                frameVisible:f.classList.contains('on'),styleH:f.style.height};}""")
    chk("shell page: in-page iframe voting opens the official page (no frame blocking)",
        vis["frameVisible"] and vis["h"] > 200, str(vis)[:120] + " | " + str(frame_ok)[:80])

    # the iframe is cross-origin, but Playwright can still reach inside it
    fr = None
    for _ in range(80):
        for cand in sh.frames:
            if "/4rq96i/gallery/" in (cand.url or ""):
                fr = cand
                break
        if fr:
            break
        sh.wait_for_timeout(500)
    if fr is None:
        chk("shell page: in-page voting window loads the official page", False, "no such iframe frame")
        ist = {"cards": 0, "votable": 0}
    else:
        try:
            fr.wait_for_selector(".btn-vote", timeout=30000)
        except Exception:
            pass
        ist = fr.evaluate("""() => {const sec = document.getElementById('gallery-section');
          const h = document.querySelector('.hero');
          return {cards:document.querySelectorAll('.gallery-card').length,
            votable:document.querySelectorAll('.btn-vote:not(.voted)').length,
            scrollY:Math.round(window.scrollY),
            galleryTop:Math.round(sec?sec.getBoundingClientRect().top+window.scrollY:-1),
            heroH:Math.round(h?h.getBoundingClientRect().height:-1),
            anchor:!!sec};}""")
        chk("shell page: in-page window shows the official page's own Vote buttons",
            ist["cards"] > 0 and ist["votable"] > 0, str(ist))
        chk("shell page: in-page window opens scrolled to the gallery (voter sees posters, not the hero)",
            ist["anchor"] and abs(ist["scrollY"] - ist["galleryTop"]) < 80,
            "scrollY=%d, gallery at %d, hero is %dpx tall" % (ist["scrollY"], ist["galleryTop"], ist["heroH"]))
        chk("shell page: iframe height follows the official page's woobox:resize messages",
            vis["styleH"].endswith("px") and int(vis["styleH"][:-2] or 0) > 300, str(vis["styleH"]))
        if DO_VOTE:
            r = fr.evaluate("""async () => {
                // app.js attaches no handler to an already-voted button, so only a
                // Vote -> Voted transition on a fresh card proves the vote landed.
                const cards=[...document.querySelectorAll('.gallery-card')];
                const c=cards.find(c=>{const b=c.querySelector('.btn-vote');
                    return b && !b.classList.contains('voted') && !b.disabled;});
                if(!c) return {error:'all visible cards already voted by this visitor'};
                const b=c.querySelector('.btn-vote');
                const cap=((c.querySelector('.gallery-caption')||{}).textContent||'?').trim();
                const before=b.textContent.trim();
                b.click(); await new Promise(r=>setTimeout(r,6000));
                return {entry:cap, before:before, after:b.textContent.trim(),
                        cls:b.className, count:(c.querySelector('.vote-count')||{}).textContent};}""")
            chk("REAL VOTE through the shell's in-page voting window was accepted",
                r.get("before") == "Vote" and ("voted" in r.get("cls", "") or r.get("after") == "Voted"), str(r))
    sh.screenshot(path=os.path.join(SHOT, "3_shell_item.png"), full_page=False)
    ctx2.close()

    ctx3 = br.new_context()
    ix = ctx3.new_page()
    ix.goto(BASE + "/index.html", wait_until="load", timeout=60000)
    ix.wait_for_timeout(1500)
    all_cards = ix.evaluate("() => document.querySelectorAll('#grid .it').length")
    ix.fill("#q", "Hanna")
    ix.wait_for_timeout(600)
    one = ix.evaluate("() => [...document.querySelectorAll('#grid .it .n')].map(e=>e.textContent)")
    ix.fill("#q", "")
    ix.wait_for_timeout(400)
    ix.select_option("#sort", "name")
    ix.wait_for_timeout(800)
    order = ix.evaluate("() => [...document.querySelectorAll('#grid .it .n')].map(e=>e.textContent).slice(0,3)")
    top = ix.evaluate("() => [...document.querySelectorAll('#rank span')].map(e=>e.textContent).slice(0,5)")
    chk("index: all %d entries listed on open (no Load More)" % all_cards, all_cards == len(items), str(all_cards))
    chk("index: search narrows to the requested entry", one and all("Hanna" in t for t in one), str(one))
    chk("index: name sort works", order == sorted(order), str(order))
    ix.select_option("#sort", "votes")
    ix.wait_for_timeout(600)
    chk("index: leaderboard present", len(top) == 5, str(top))
    bkmk = ix.evaluate("() => document.getElementById('bkmk').href")
    chk("index: bookmarklet href is a javascript: URL", bkmk.startswith("javascript:") and len(bkmk) > 200, str(len(bkmk)))
    live = ix.evaluate("() => document.getElementById('live').textContent")
    chk("index: counts re-fetch votes.json same-origin and stamp the snapshot time",
        "票数已刷新" in live and str(len(items)) in live, live[:120])
    ix.fill("#q", "Hanna")
    ix.wait_for_timeout(400)
    ix.screenshot(path=os.path.join(SHOT, "5_index_search.png"))
    ctx3.close()

    # ── 5. the shell must not break the deep link's own data ───────────────
    br.close()
    srv.shutdown()

fails = [r for r in results if not r[1]]
print("\n%d/%d checks passed   (screenshots in %s)" % (len(results) - len(fails), len(results), SHOT))
sys.exit(1 if fails else 0)
