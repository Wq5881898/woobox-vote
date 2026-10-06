# Suggested upstream fix for `app.js` (site `4rq96i`)

Two independent bugs on the artwork deep link
`https://woobox.com/4rq96i/gallery/<upload_id>`. Both are client-side; the server
already sends everything needed. Reproducible on a fresh profile, all browsers.

## Bug 1 — the deep link ignores the entry it was given

`window.__SITE__.gallery.item` is rendered into the page by your server:

```json
{"id":"xpgroevp","caption":"Hanna - Elementary","type":"photo",
 "gallery_url":"https://woobox.com/4rq96i/gallery/xpgroevp",
 "uploaded_by":"Miss.","votes":32,
 "photo_url":"https://offertabs.s3.amazonaws.com/offer/4rq96i/uploads/6ab2995204d659.07573676.jpg?AWSAccessKeyId=…&Expires=1793921267&Signature=…"}
```

but `init()` (`app.js:25`) always calls `loadGallery(1)`, and nothing else reads
`gallery.item` (there is no `URLSearchParams`/`location.hash` handling anywhere in
`app.js`). Measured on the live page after the grid finished rendering:
`cards=12`, the requested entry **absent** (it is entry 108 of 116, page 9),
so a voter who follows a shared link sees 12 strangers and must click *Load More*
9 times.

`app.js` already has every ingredient — `renderGallery(uploads)` takes any array:

```js
if (site.gallery && site.gallery.enabled) {
    const loadMoreBtn = document.getElementById('load-more');
    const item = site.gallery.item;                       // ← added
    const browseAll = new URLSearchParams(location.search).has('all');

    if (item && !browseAll) {                             // ← added: deep-link view
        renderGallery([item]);
        if (loadMoreBtn) {
            loadMoreBtn.className = 'btn btn-secondary';
            loadMoreBtn.textContent = 'Browse all entries';
            loadMoreBtn.disabled = false;
            loadMoreBtn.classList.remove('hidden');
            loadMoreBtn.addEventListener('click', function showAll() {
                loadMoreBtn.removeEventListener('click', showAll);
                loadMoreBtn.className = 'btn btn-primary';
                loadMoreBtn.textContent = 'Load More Entries';
                galleryPage = 1;
                loadGallery(1);                           // page 1 clears the grid itself
                loadMoreBtn.addEventListener('click', function () { loadGallery(++galleryPage); });
            });
        }
        document.getElementById('gallery-section')?.scrollIntoView();
        return;                                           // ← do not load page 1
    }

    loadGallery(1);
    /* existing Load More wiring */
}
```

Notes: `loadGallery(1)` wipes `#gallery-grid` before appending, so the deep-link
view must simply *not* call it (a wrapper around `renderGallery` alone gets
erased). `loadMoreBtn`'s handler must be added/removed with named functions,
because `init()` wires it with `addEventListener`. Passing `gallery.item`
straight to `renderGallery` is enough: it already carries `votes` and
`photo_url`, and the caption needs no `formatCaption()` pass (it arrives as
plain text; `formatCaption` only trims it to “first name - category”).

`gallery_url` is already an absolute per-entry URL, so the “share this artwork”
button can be built from the same object with no extra request.

## Bug 2 — other visitors' votes disable the Vote button

`renderGallery()` decides the button state from

```js
const votedIds = site.result_votes || [];      // app.js:308
…
if (votedIds.includes(upload.id)) { voteBtn.classList.add('voted'); voteBtn.disabled = true; }
```

On a brand-new browser profile (no cookies, no prior vote) `result_votes` already
contains 5 entry ids, and 2 of the 12 visible cards come up **`Voted` + disabled**.
Those ids are not this visitor's votes — e.g. `arvbdljq` (22 votes),
`xpgroevp` (32), `xpgapxbx` (11), which are neither the top entries (883/452/340/…)
nor anything a new visitor could have voted for; the shape looks like a global
*recently voted* list. Result: a voter cannot vote for an entry that somebody else
just voted for, and reloading moves the list so the same entry becomes votable
again ~1 minute later.

Fix options: send the *current visitor's* voted ids (server knows them from the
session / fingerprint + IP already used by `/vote`) in a separate field, or drop
the client-side `disabled` and let the `/vote` response be the single source of
truth — its failure body can say `already_voted`.

## Acceptance checks

1. `…/gallery/xpgroevp` on a fresh profile shows exactly 1 card = `Hanna - Elementary`,
   `Vote` enabled; clicking it shows `Voted` and `votes` increments by 1.
2. *Browse all entries* → 12 cards, *Load More* then appends 12 more each click
   (12 → 24 → 36 …), no duplicate or lost pages.
3. A fresh profile can vote for an entry that currently appears in `result_votes`.
4. Sharing the page's own URL (or `navigator.share`) reproduces check 1 for the
   next visitor.

## Interim workarounds shipped here

* `woobox-item-fix.user.js` — same behaviour as Bug 1's patch, injected after
  `document-idle`, plus a `MutationObserver` that re-pins the card when the
  in-flight `loadGallery(1)` wipes the grid, and re-enabling of a falsely
  `Voted` button (letting `/vote` decide, with its error surfaced to the voter).
* `bookmarklet.txt` — the same thing as one paste-able `javascript:` URL, for
  voters who will not install anything.
* `site/v/<id>.html` — a static shell that needs nothing from the voter: it shows
  the artwork from the public S3 object (signature stripped, so it never expires)
  and hosts the official page in an `<iframe>` for the vote, because `/vote`
  accepts only a same-origin, `_csrf`-bearing POST.
