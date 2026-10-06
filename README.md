# woobox-vote — 作品直达投票套壳站（无逆向代理）

Fix + shell for the Woobox voting site **ERA Kids Poster Contest**
(`https://woobox.com/4rq96i/gallery`).

## 1. The bug being worked around

`https://woobox.com/4rq96i/gallery/<id>` is the site's own "artwork deep link". The
server already puts that artwork into the page as `window.__SITE__.gallery.item`
(`id / caption / votes / photo_url / gallery_url`), but `app.js` never reads it:

```js
// app.js:25  init()
if (site.gallery && site.gallery.enabled) {
    loadGallery(1);              // ← always page 1 of the whole gallery
```

So opening a deep link renders 12 unrelated cards and the voter has to click
**Load More** up to 9 times hoping to find the entry (verified: `xpgroevp` sits at
position **108 of 116**, i.e. page 9 slot 12, and is not on page 1 at all).
Measured on the live page: `cards=12, scrollY=0`, requested entry absent.
Upstream fix: [`PATCH_FOR_WOOBOX.md`](PATCH_FOR_WOOBOX.md).

## 2. Constraints that decide the design (all measured, see `verify.py`)

| fact | consequence |
|---|---|
| `POST /site_api/ewxzgdgw/vote` needs the page's `_csrf` **and** its session cookie; a cross-origin POST gets `403 csrf_invalid`, and the preflight `OPTIONS` returns `405` | **the vote itself cannot be forwarded from another origin** — no shell can vote on woobox's behalf, proxy or not |
| the real POST (captured in `probes/dbg6_iframe_cookies.py`) is `POST https://woobox.com/site_api/ewxzgdgw/vote` from referer `…/4rq96i/gallery/<id>`, with a cookie header (`document.cookie` is empty inside the frame → HttpOnly session) and body fields `_csrf, upload_id, _interaction, _scfp, _scp, _ts_start, _ts_submit` (SDK-injected fingerprint/timing) | replaying a vote from a shell would mean forging the fingerprint too; embedding the page costs nothing and stays honest |
| gallery API sends no `Access-Control-Allow-Origin` | a shell cannot even *read* the gallery at runtime → snapshot at build time |
| no `X-Frame-Options`, CSP is `Content-Security-Policy-Report-Only` | embedding `woobox.com` in an `<iframe>` from any host is legal → the shell can host the official Vote button in-page |
| `offertabs.s3.amazonaws.com` objects are public-read and readable **without** the query signature (296/296 URLs returned 200) | the shell can hotlink every artwork forever, no expiring signed URLs, no image proxy |
| `app.js` contains no `URLSearchParams` / `location.hash` handling; `#:~:text=` does not match cards rendered by JS after load (`scrollY` stays 0) | no URL trick alone can position a voter on an entry → the shell must supply the position itself |
| `__SITE__.result_votes` is a **global** recent-votes list, not "your votes" | the site marks other people's entries `Voted` + `disabled` for a brand-new visitor (2 of 12 visible cards on a fresh profile), which silently blocks a valid vote |

## 3. What this repo produces

```
site/                     ← deploy this folder as a static site (GitHub Pages etc.)
  index.html              all 116 entries on one page: search / sort / leaderboard /
                          copy-deeplink / CSV export / install section, no Load More
  v/<id>.html             one page per artwork: big image, vote count, position hint,
                          and the official voting page embedded in an iframe
  items.json votes.json   data + per-item vote counts (votes.json is re-fetched by the
                          pages themselves, so counts refresh without a redeploy)
  bookmarklet.txt         the same fix as one paste-able javascript: URL
  woobox-item-fix.user.js Tampermonkey/Violentmonkey script
build.py                  pulls the gallery API, regenerates site/*, self-checks the JS
.github/workflows/deploy.yml  cron(10 min) rebuild + Pages deploy
```

Three ways to reach one artwork, in order of how little they ask of the voter:

1. **Shell page** `…/v/<id>.html` — zero install, works in WeChat/in-app browsers.
   Big artwork, current vote count, "就在这里投票" opens the *official* page in an
   iframe already scrolled to the gallery, so the voter presses woobox's own
   `Vote` button (the vote is counted by woobox, on woobox, first-party).
2. **Bookmarklet** (`bookmarklet.txt`, one line) — paste in the address bar on
   mobile, or drag to the bookmarks bar on desktop: makes the *official* deep link
   render only that artwork, with its own working Vote button.
3. **Userscript** `woobox-item-fix.user.js` — auto-activates on every deep link,
   plus `?all=1` (full gallery, auto Load More) and `?links=1` (dump every
   entry's `name ⇥ votes ⇥ link`, or export CSV) for the organiser.

## 4. Deploy

```bash
pip install requests playwright && playwright install chromium
python build.py                     # writes ./site  (SITE_BASE_URL=… for canonical URLs)
python verify.py                    # 20 network/protocol checks against woobox.com
python verify_browser.py            # 27 headless-Chromium end-to-end checks + shots/
python verify_browser.py --vote     # + casts ONE real vote through the shell iframe (28)
# both scripts take --quick to skip the slow ?links=1 harvest
```

GitHub: push this folder to a repo → *Settings → Pages → Source: GitHub Actions* →
the bundled workflow rebuilds every 10 minutes and publishes `site/`. If the
upstream API changes shape, `build.py` exits non-zero and the last good build
stays live. `build.py` also refuses to write the site if any inline script has a
syntax error or declares a global that collides with `window` (e.g. `top`).

Point people at `…/v/<id>.html`; the page tells them the entry's position in the
official gallery ("第 108 位，再点 8 次 Load More，第 9 页第 12 张") in case they
prefer to vote on woobox.com directly.

## 5. Notes / honest limits

* Vote counts are a **snapshot** (≤ ~10 min old with the cron). Live counts are
  only ever known by woobox.
* **Cookie storage in iframes.** Inside the in-page voting window the POST is still
  `woobox.com → woobox.com`, and `probes/dbg6_iframe_cookies.py` shows it keeps
  working with Chromium's third-party-cookie phase-out on (cookie is issued to the
  embedded frame anyway). Safari/ITP, Firefox ETP and WeChat's built-in browser are
  stricter than that emulation, so if a voter reports that the vote does not stick,
  send them the secondary *“在新标签打开官方投票页”* link instead — a top-level,
  first-party load, which is the path the vote was always designed for.
* One vote per entry per visitor is enforced by woobox (fingerprint + IP), not by
  us; our pages only display what woobox reports.
* `items.json` is not needed in production (data is inlined into the HTML) — it is
  there for `verify_browser.py` and for whoever wants the raw list.
* Captions are **not unique** (12 duplicated names in 116 entries), so anything
  that locates an entry by name alone can hit the wrong one: everything here keys
  on the entry `id`.
* `verify_browser.py` writes screenshots to `shots/`; `probes/dbg*.py` are the
  one-off investigations behind the numbers quoted above.
