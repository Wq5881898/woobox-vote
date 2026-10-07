"""Smoke-test the DEPLOYED site at its real public URL.

  python verify_live.py [--url https://wq5881898.github.io/woobox-vote/]

Checks the things that can only break in production: absolute share/canonical
URLs, the Pages 404 page masquerading as content, the cron schedule being
registered, and that a visitor's flow (find -> open -> vote) works from the
public URL rather than localhost.
"""
import sys, os, re, json, argparse, datetime, urllib.request
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import requests
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("--url", default=os.environ.get("SHELL_URL", "https://wq5881898.github.io/woobox-vote/"))
ap.add_argument("--id", default="xpgroevp")
a = ap.parse_args()
BASE = a.url if a.url.endswith("/") else a.url + "/"
sh = requests.Session()
sh.headers["User-Agent"] = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"

res = []
def chk(n, c, d=""):
    res.append((("PASS" if c else "FAIL"), n, d))
    print("%-4s %s%s" % ("PASS" if c else "FAIL", n, ("  -- " + str(d)) if d else ""))

# ── 1. the deployment itself ────────────────────────────────────────────────
r = sh.get(BASE + "votes.json", timeout=60)
chk("live: votes.json reachable and fresh", r.status_code == 200 and "votes" in r.json(),
    "http=%d built_at=%s rows=%d" % (r.status_code, r.json().get("built_at"), len(r.json().get("votes", {}))))
age = None
built = datetime.datetime.strptime(r.json()["built_at"], "%Y-%m-%d %H:%M UTC")
age = (datetime.datetime.now(datetime.timezone.utc) - built.replace(tzinfo=datetime.timezone.utc)).total_seconds() / 60
chk("live: snapshot is younger than the 10-minute rebuild + Pages lag", age < 45, "%.1f min old" % age)

votes = r.json()["votes"]
r = sh.get(BASE + "v/%s.html" % a.id, timeout=60)
page = r.text
chk("live: item page serves real content (not the 404 page)",
    r.status_code == 200 and "<!DOCTYPE" in page and "There isn" not in page, "http=%d %dB" % (r.status_code, len(page)))
chk("live: canonical + copy-link are absolute URLs on this host",
    ('rel="canonical" href="%sv/%s.html"' % (BASE, a.id)) in page and ('SHARE = "%sv/%s.html"' % (BASE, a.id)) in page,
    str(re.findall(r'SHARE = "[^"]+"', page))[:100])
chk("live: item page still hands the vote to woobox.com",
    ("https://woobox.com/4rq96i/gallery/%s#gallery-section" % a.id) in page)
chk("live: vote count baked into the page equals the published snapshot",
    int(re.search(r'id="v">(\d+)<', page).group(1)) == int(votes.get(a.id, -1)),
    "page=%s snapshot=%s" % (re.search(r'id="v">(\d+)<', page).group(1), votes.get(a.id)))

r = sh.get(BASE, timeout=60)
chk("live: index at the site root", r.status_code == 200 and "var DATA" in r.text,
    "http=%d %dB" % (r.status_code, len(r.text)))
chk("live: index item links are absolute (share-stable)",
    ('BASE="%s"' % BASE) in r.text, str(re.findall(r'BASE="[^"]*"', r.text))[:80])

for f in ("bookmarklet.txt", "woobox-item-fix.user.js", "items.json"):
    q = sh.head(BASE + f, timeout=60, allow_redirects=True)
    chk("live: %s downloadable" % f, q.status_code == 200, "http=%d" % q.status_code)

# ── 2. the scheduled rebuild is actually registered ─────────────────────────
api = os.environ.get("GH_REPO", "Wq5881898/woobox-vote")
try:
    j = sh.get("https://api.github.com/repos/%s/actions/workflows" % api,
               headers={"User-Agent": "check", "Accept": "application/vnd.github+json"}, timeout=60).json()
    wf = [w for w in j.get("workflows", []) if w.get("path", "").endswith("deploy.yml")]
    chk("live: rebuild workflow exists and is active (10-min cron)",
        bool(wf) and wf[0]["state"] in ("active", "enabled"), str([(w["state"], w["name"]) for w in wf]))
except Exception as e:
    print("SKIP workflow state check: %s" % str(e)[:80])

# ── 3. the visitor's whole flow, in a browser, from the public URL ──────────
with sync_playwright() as p:
    br = p.chromium.launch()
    ctx = br.new_context(viewport={"width": 390, "height": 844})
    pg = ctx.new_page()
    pg.goto(BASE, wait_until="load", timeout=90000)
    pg.wait_for_timeout(3500)
    pg.evaluate("() => document.getElementById('live') && scrollTo(0,document.body.scrollHeight)")
    pg.wait_for_timeout(4000)          # give loading="lazy" thumbnails a chance
    pg.evaluate("() => scrollTo(0,0)")
    pg.wait_for_timeout(500)
    st = pg.evaluate("""() => ({rows:document.querySelectorAll('#grid .it').length,
        live:(document.getElementById('live')||{}).textContent||'',
        rank:[...document.querySelectorAll('#rank span')].map(e=>e.textContent).slice(0,3),
        imgs:[...document.querySelectorAll('#grid img')].map(i=>({ok:i.complete&&i.naturalWidth>50,src:i.src}))})""")
    bad = [i for i in st["imgs"] if not i["ok"]]
    chk("live: index lists every entry with pictures loaded (S3 hotlinks)",
        st["rows"] >= 100 and not bad, "%d rows, %d not loaded, e.g. %s" % (st["rows"], len(bad), bad[:1]))
    chk("live: index shows the snapshot stamp (counts self-refresh, no proxy)",
        "票数已刷新" in st["live"], st["live"][:100])
    chk("live: top-3 leaderboard rendered", len(st["rank"]) == 3, str(st["rank"]))

    pg.fill("#q", "Hanna")
    pg.wait_for_timeout(500)
    names = pg.evaluate("() => [...document.querySelectorAll('#grid .it .n')].map(e=>e.textContent)")
    chk("live: a parent can find the entry by typing a name", names and all("Hanna" in n for n in names), str(names))
    pg.click("#grid .it a")
    pg.wait_for_timeout(2000)
    d = pg.evaluate("""() => ({url:location.href, title:(document.querySelector('.t')||{}).textContent,
        votes:(document.getElementById('v')||{}).textContent, asof:document.getElementById('asof').textContent,
        pos:(document.querySelector('.pos')||{}).innerText||'',
        main:(document.getElementById('votewin')||{}).href, copy:!!document.getElementById('copy')})""")
    chk("live: search -> entry page navigation works", d["url"].endswith("v/%s.html" % a.id), d["url"])
    chk("live: entry page states the position in the official gallery",
        "第" in d["pos"] and "Load More" in d["pos"], d["pos"].replace("\n", " ")[:120])
    chk("live: main CTA goes to woobox.com already scrolled to the artwork",
        d["main"].startswith("https://woobox.com/4rq96i/gallery/%s#gallery-section" % a.id), d["main"][:110])

    # in-page voting window, opened from the public URL
    pg.evaluate("() => document.getElementById('inline').click()")
    why = "no iframe appeared"
    fr = None
    for _ in range(60):
        pg.wait_for_timeout(1000)
        cand = [f for f in pg.frames if "4rq96i/gallery/" in (f.url or "")]
        if cand:
            fr = cand[0]
            try:
                n = fr.evaluate("() => document.querySelectorAll('.btn-vote').length")
            except Exception as e:
                n, why = 0, "frame not inspectable: %s" % str(e)[:60]
                continue
            if n:
                why = "%d Vote buttons" % n
                break
            why = "frame loaded but rendered 0 Vote buttons (woobox JS did not run?)"
        else:
            why = "iframe element exists, no woobox frame: " + str(
                pg.evaluate("() => [...document.querySelectorAll('iframe')].map(f=>f.src.slice(0,40))"))[:90]
    st2 = fr.evaluate("""() => ({cards:document.querySelectorAll('.gallery-card').length,
        votable:[...document.querySelectorAll('.btn-vote')].filter(b=>!b.classList.contains('voted')&&!b.disabled).length,
        scrollY:Math.round(scrollY),anchor:!!document.getElementById('gallery-section')})""") if fr else {}
    chk("live: in-page voting window shows the official page with usable Vote buttons",
        bool(fr) and st2.get("cards", 0) >= 1 and st2.get("votable", 0) >= 1, "%s | %s" % (why, str(st2)[:140]))
    chk("live: in-page voting window opens already scrolled to the gallery",
        st2.get("scrollY", 0) > 300, "scrollY=%s" % st2.get("scrollY"))
    pg.screenshot(path=os.path.join(os.path.dirname(__file__) or ".", "shots_live.png"))
    br.close()

bad = [x for x in res if x[0] == "FAIL"]
print("\n%d/%d checks passed" % (len(res) - len(bad), len(res)))
sys.exit(1 if bad else 0)
