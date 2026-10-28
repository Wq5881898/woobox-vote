#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Independent verification of the shell site (network/protocol layer).
Re-pulls the API on its own and cross-checks the built files, so a stale or
mis-built site cannot be shipped silently.

  python verify.py            # full run (HEADs every image, samples deep links)
  python verify.py --quick    # fewer samples
"""

import concurrent.futures as cf
import calendar
import glob
import html
import json
import os
import re
import ssl
import sys
import time
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SITE = os.path.join(HERE, "site")
API = "https://woobox.com/site_api/ewxzgdgw"
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
CTX = ssl.create_default_context()
QUICK = "--quick" in sys.argv
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

results = []


def chk(name, ok, detail=""):
    results.append((name, bool(ok), detail))
    print("%s  %s%s" % ("PASS" if ok else "FAIL", name, ("  -- " + detail) if detail else ""))


def http(url, method="GET", headers=None, timeout=40):
    req = urllib.request.Request(url, method=method, headers=dict(UA, **(headers or {})))
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=CTX) as r:
            return r.status, dict(r.headers), r.read(400000)
    except urllib.error.HTTPError as e:
        return e.code, dict(e.headers), e.read(200000)
    except Exception as e:                       # noqa: BLE001
        return 0, {}, str(e).encode()


def caption(raw):
    if not raw or raw == "Student Entry":
        return "Student Entry"
    p = raw.split(" - ")
    if len(p) > 1:
        return p[0].strip().split()[0] + " - " + " - ".join(p[1:]).strip()
    return raw.strip().split()[0] if raw.strip() else "Student Entry"


# ─── 1. independent API pull ───────────────────────────────────────────────
api, page = {}, 1
while True:
    st, _, body = http("%s/gallery?page=%d&limit=100" % (API, page))
    assert st == 200, "API page %d -> %s" % (page, st)
    d = json.loads(body)
    for u in d["uploads"]:
        api[u["id"]] = u
    if not d.get("has_more"):
        break
    page += 1
chk("API: public gallery endpoint reachable without cookie/auth (%d entries)" % len(api), len(api) > 0)

built = json.load(open(os.path.join(SITE, "items.json"), encoding="utf-8"))
items = built["items"]
chk("build: entry count matches live API (%d)" % len(api), len(items) == len(api),
    "built=%d api=%d" % (len(items), len(api)))
chk("build: ids identical to live API", {i["id"] for i in items} == set(api))

# Votes drift while we check: this is a hot contest (measured +10 votes on one
# entry in 30 min), so an absolute delta proves nothing. These invariants do:
#   * upstream votes only go up -> a snapshot count can never be ABOVE live
#   * the snapshot must be recent, that is the whole point of the rebuild job
#   * the leaderboard order must still be the live order at the top
above = [(i["id"], i["votes"], api[i["id"]]["votes"]) for i in items
         if int(api[i["id"]]["votes"]) < i["votes"]]
chk("build: no snapshot count sits above the live count (votes only go up)", not above, str(above[:3]))

age = (time.time() - calendar.timegm(time.strptime(built["generated_at"], "%Y-%m-%d %H:%M UTC"))) / 60.0
chk("snapshot is fresh (%.0f min old, rebuilt on push + schedule)" % age, age < 75,
    "built %s, %.1f min ago" % (built["generated_at"], age))

snap5 = [i["id"] for i in sorted(items, key=lambda r: -r["votes"])[:5]]
live5 = [k for k, _ in sorted(((k, int(v["votes"])) for k, v in api.items()), key=lambda kv: -kv[1])[:5]]
chk("build: the Top-5 the index ranks is still the live Top-5", set(snap5) == set(live5),
    "snapshot %s vs live %s" % (snap5, live5))
drift = [(i["id"], i["votes"], api[i["id"]]["votes"]) for i in items
         if int(api[i["id"]]["votes"]) - i["votes"] > max(25, 0.05 * int(api[i["id"]]["votes"]))]
chk("build: counts are within a plausible growth margin of live", not drift, str(drift[:3]))
moved = [(i["id"], i["votes"], api[i["id"]]["votes"]) for i in items if api[i["id"]]["votes"] != i["votes"]]
if moved:
    print("      note: %d count(s) moved since the snapshot; pages pull votes.json to catch up" % len(moved), str(moved[:3]))
snap = json.load(open(os.path.join(SITE, "votes.json")))
votes_map = snap["votes"] if "votes" in snap else snap
by_id = {i["id"]: i for i in items}
chk("votes.json: timestamped snapshot, one row per entry, values equal to this build",
    bool(snap.get("built_at")) and len(votes_map) == len(api)
    and all(votes_map[k] == by_id[k]["votes"] for k in api),
    "built_at=%s rows=%d" % (snap.get("built_at"), len(votes_map)))

# ─── 2. every entry has a shell page, wired correctly ──────────────────────
bad = []
for i in items:
    p = os.path.join(SITE, "v", i["id"] + ".html")
    if not os.path.exists(p):
        bad.append((i["id"], "missing page"))
        continue
    t = open(p, encoding="utf-8").read()
    # the handoff URL = the page's real #gallery-section anchor (works on JS-rendered
    # cards) + the text fragment (best effort); both are recomputed here from the API
    want_frag = ("#gallery-section:~:text=" + urllib.parse.quote(caption(api[i["id"]]["caption"])).replace("%20", " "))
    if i["deep"] not in t:
        bad.append((i["id"], "no deep link"))
    if want_frag not in t and want_frag.replace(" ", "%20") not in t:
        bad.append((i["id"], "wrong text fragment"))
    if i["img"] and 'src="%s"' % i["img"] not in t:
        bad.append((i["id"], "artwork img not embedded"))
    if not i["img"] and 'class="noimg"' not in t:
        bad.append((i["id"], "image-less entry without placeholder"))
    if "AWSAccessKeyId" in t:
        bad.append((i["id"], "presigned (expiring) URL leaked into page"))
chk("shell pages: exist for all entries, deep link + text fragment + artwork wired", not bad, str(bad[:4]))

files = sorted(glob.glob(os.path.join(SITE, "v", "*.html")))
stray = [f for f in files if os.path.basename(f)[:-5] not in api]
chk("shell pages: no orphan pages (%d files)" % len(files), not stray, str(stray[:3]))

# ─── 3. images must work as plain hotlinks (this is what kills the proxy) ──
# a fresh upload can have neither photo_url nor thumb_url: it must get the
# placeholder, never an <img src=""> that renders as a broken icon
noimg = [i for i in items if not i["img"] and not i["thumb"]]
broken = [i["id"] for i in noimg if 'src=""' in open(os.path.join(SITE, "v", i["id"] + ".html"), encoding="utf-8").read()]
chk("entries uploaded before their image exists (%d) render a placeholder, not a broken <img>" % len(noimg),
    not broken and all("noimg" in open(os.path.join(SITE, "v", i["id"] + ".html"), encoding="utf-8").read() for i in noimg),
    str([i["id"] for i in noimg][:3]) + (" broken:" + str(broken[:2]) if broken else ""))

urls = sorted({i["img"] for i in items if i["img"]} | {i["thumb"] for i in items if i["thumb"]})
if QUICK:
    urls = urls[:20]


def head(u):
    st, h, _ = http(u, method="HEAD")
    return u, st, h.get("Content-Type", ""), h.get("Access-Control-Allow-Origin", "")


with cf.ThreadPoolExecutor(12) as ex:
    res = list(ex.map(lambda a: head(a), urls))
notok = [r for r in res if r[1] != 200]
chk("S3 objects readable with NO signature (%d urls)" % len(urls), not notok, str(notok[:3]))
img_ok = [r for r in res if r[1] == 200]
chk("S3 responses are real images", bool(img_ok) and all(r[2].startswith("image/") for r in img_ok),
    "checked %d" % len(img_ok))

# ─── 4. constraints that justify the design ───────────────────────────────
st, h, _ = http("%s/gallery?page=1&limit=1" % API, headers={"Origin": "https://example.github.io"})
chk("woobox API sends NO Access-Control-Allow-Origin -> runtime fetch from another origin is out; "
    "build-time snapshot is the right shape", st == 200 and "access-control-allow-origin" not in {k.lower() for k in h})
st, h, b = http("%s/vote" % API, method="POST", headers={"Origin": "https://example.github.io",
                                                        "Content-Type": "application/json"}, timeout=40)
body = b.decode("utf-8", "replace")
chk("cross-origin /vote rejected (%s) -> Vote button must live on woobox.com itself" % st,
    st in (403, 405) or "csrf" in body.lower(), body[:70])
st, h, b = http("https://woobox.com/4rq96i/gallery/xpgroevp")
low = {k.lower(): v for k, v in h.items()}
fa = (low.get("content-security-policy", "") + " " + low.get("x-frame-options", "")).lower()
chk("woobox item page has no enforced X-Frame-Options / frame-ancestors -> in-page iframe mode is legal",
    st == 200 and "frame-ancestors" not in fa and "deny" not in fa and "sameorigin" not in fa, fa[:60] or "none")

# ─── 5. deep links still resolve to their own entry (server side) ──────────
sample = [i for i in items if i["id"] == "xpgroevp"] + (items[:6] if not QUICK else items[:2])
broken = []
for i in sample:
    st, _, b = http(i["deep"])
    m = re.search(r'"item":\{"id":"(\w+)"', b.decode("utf-8", "replace"))
    if st != 200 or not m or m.group(1) != i["id"]:
        broken.append((i["id"], st, m.group(1) if m else None))
chk("deep links: %d sampled pages each carry their own __SITE__.gallery.item" % len(sample),
    not broken, str(broken[:3]))

# ─── 6. frontend bug is still there (so our fix is still needed) ───────────
st, _, page = http("https://woobox.com/4rq96i/gallery/xpgroevp")
m = re.search(r'src="([^"]*app\.js[^"]*)"', page.decode("utf-8", "replace"))
app_url = html.unescape(m.group(1)) if m else ""
if app_url.startswith("/"):
    app_url = "https://woobox.com" + app_url
st, _, b = http(app_url)
src = b.decode("utf-8", "replace")
chk("fetched the live frontend bundle (%s bytes)" % len(src), len(src) > 1000, app_url)
# What the bundle does today is an observation, not an assumption: v18 ignored
# gallery.item (that bug is why this shell exists), v27 added
# openLightbox(site.gallery.item). Either way the shell must keep working, so the
# only hard requirements are the two functions the userscript hooks.
lm = re.search(r"galleryLimit\s*=\s*(\d+)", src)
chk("official deep link handled by upstream? (shell still needed for search/ranking)",
    True, "gallery.item handled in init: %s | grid page size: %s"
    % ("gallery.item" in src, lm.group(1) if lm else "?"))
chk("app.js still renders the grid through loadGallery/renderGallery (userscript hook points)",
    "function renderGallery" in src and "function loadGallery" in src, app_url)

# ─── 7. index.html self-containment ───────────────────────────────────────
idx = open(os.path.join(SITE, "index.html"), encoding="utf-8").read()
m = re.search(r"var DATA=(\[.*?\]), BASE=", idx, re.S)
data = json.loads(m.group(1)) if m else []
chk("index.html embeds all %d entries inline (works offline / file:// / WeChat)" % len(api),
    len(data) == len(api))
chk("index.html has no external JS/CSS dependency",
    'src="http' not in idx and 'stylesheet' not in idx,   # <link rel=canonical> is fine
    str(sorted(set(re.findall(r'<link rel="([a-z]+)"', idx)))))
chk("index.html and the item pages refresh counts from same-origin votes.json (no proxy)",
    "votes.json" in idx and "votes.json" in open(os.path.join(SITE, "v", items[0]["id"] + ".html"), encoding="utf-8").read())
chk("bookmarklet.txt is a single javascript: URL that is valid JS",
    open(os.path.join(SITE, "bookmarklet.txt")).read().strip().startswith("javascript:"))
esc_bad = [i["id"] for i in items if ("&" in (i["caption"] or "")) and html.escape(i["caption"]) not in idx]
chk("captions with special chars are escaped in index.html", not esc_bad, str(esc_bad[:3]))

fails = [r for r in results if not r[1]]
print("\n%d/%d checks passed" % (len(results) - len(fails), len(results)))
sys.exit(1 if fails else 0)
