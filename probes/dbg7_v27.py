"""Woobox shipped v27 of app.js, which contains:
      if (site.gallery.item) { openLightbox(site.gallery.item); }
so the official deep link may now work on its own. Re-measure what a visitor
actually sees on https://woobox.com/4rq96i/gallery/<id>, because that changes
what the shell page is for.

  python probes/dbg7_v27.py
"""
import sys, re, html
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests
from playwright.sync_api import sync_playwright

ID = "xpgroevp"
URL = "https://woobox.com/4rq96i/gallery/%s" % ID
h = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
page = requests.get(URL, headers=h, timeout=60).text
m = re.search(r'src="([^"]*app\.js[^"]*)"', page)
app_url = html.unescape(m.group(1))
app_url = "https://woobox.com" + app_url if app_url.startswith("/") else app_url
src = requests.get(app_url, headers=h, timeout=60).text
print("bundle:", app_url)
for probe in ("if (site.gallery.item)", "openLightbox(site.gallery.item)", "loadGallery(1)",
              "grid.innerHTML", "galleryLimit"):
    print("  %-34s in bundle: %s" % (probe, probe in src))
i = src.find("site.gallery.item")
print("  context:\n    " + "\n    ".join(src[i - 200:i + 260].splitlines()))

with sync_playwright() as p:
    br = p.chromium.launch()
    pg = br.new_context(viewport={"width": 1280, "height": 900}).new_page()
    pg.goto(URL, wait_until="load", timeout=90000)
    pg.wait_for_timeout(6000)
    st = pg.evaluate("""() => {
      const lb=[...document.querySelectorAll('.lightbox,#lightbox,[class*=lightbox],[class*=modal]')]
        .filter(e=>e.offsetParent!==null);
      const cards=[...document.querySelectorAll('.gallery-card')];
      const cap=cards.find(c=>((c.querySelector('.gallery-caption')||{}).textContent||'').trim().startsWith('Hanna'));
      return {scrollY:Math.round(scrollY), cards:cards.length,
        cardsTotalVotes:cards.length,
        targetCardVisible:!!(cap&&cap.offsetParent!==null),
        lightboxesOpen:lb.map(e=>({cls:e.className,txt:(e.innerText||'').replace(/\\s+/g,' ').slice(0,80)})),
        voteBtns:document.querySelectorAll('.btn-vote').length,
        lightboxImg:lb.length? [...lb[0].querySelectorAll('img')].map(i=>i.src.slice(0,70)) : [],
        title:document.title};}""")
    print("\nwhat a visitor sees on the official deep link:")
    for k, v in st.items():
        print("  %-20s %s" % (k, v))
    pg.screenshot(path="probes/shots/v27_deeplink.png", full_page=False)
    # does the lightbox carry a working Vote button?
    lb_vote = pg.evaluate("""() => {const lb=[...document.querySelectorAll('[class*=lightbox],[class*=modal]')]
        .filter(e=>e.offsetParent!==null);
      if(!lb.length) return {none:true};
      const b=[...lb[0].querySelectorAll('button,a')].map(x=>({t:x.textContent.trim().slice(0,20),cls:x.className}));
      return {buttons:b.slice(0,6)};}""")
    print("  lightbox controls:", lb_vote)
    br.close()
