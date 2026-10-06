// ==UserScript==
// @name         Woobox 作品直达修复 (ERA Kids Poster Contest)
// @namespace    https://github.com/yourname/woobox-vote
// @version      1.0.0
// @description  Fixes /gallery/<id>: renders the already-loaded window.__SITE__.gallery.item (artwork + working Vote button) instead of page 1 of the gallery. Adds ?all=1 (full gallery, auto Load More) and ?links=1 (harvest every entry's link).
// @author       you
// @match        https://woobox.com/*/gallery/*
// @match        https://woobox.com/*/gallery*
// @match        https://www.woobox.com/*/gallery*
// @run-at       document-idle
// @noframes
// @grant        none
// ==/UserScript==
/*
  Root cause (verified on https://woobox.com/4rq96i/site/v18/app.js):
    init()  ->  if (site.gallery && site.gallery.enabled) { loadGallery(1); ... }
    The server already put the requested entry into __SITE__.gallery.item
    (id / caption / votes / photo_url / gallery_url) but app.js never reads it,
    so every per-artwork URL renders the same page-1 grid.

  This script reuses the site's OWN renderGallery() + WooboxSDK.vote(), so the
  Vote button keeps the CSRF token, fingerprint and cookies of the real page.
  Nothing is proxied; the vote is still submitted by woobox.com itself.

  URL switches:
    https://woobox.com/4rq96i/gallery/xpgroevp          -> only "Hanna - Elementary"
    https://woobox.com/4rq96i/gallery/xpgroevp?all=1    -> normal grid + auto Load More
    https://woobox.com/4rq96i/gallery?links=1           -> dump "name <TAB> link" for all entries
*/
(function () {
  'use strict';

  var site = window.__SITE__ || {};
  var grid = document.getElementById('gallery-grid');
  var loadMore = document.getElementById('load-more');
  var params = new URLSearchParams(location.search);
  var item = (site.gallery && site.gallery.item) || null;

  if (!grid || typeof window.renderGallery !== 'function') return;

  var origRender = window.renderGallery;
  var seen = Object.create(null);        // id -> upload object (for ?links=1)
  var drop = false;                      // when true, swallow the grid renders

  // record every entry we ever render, and stamp its id on the card
  function record(list) {
    var before = grid.children.length;
    if (list && list.length) {
      for (var i = 0; i < list.length; i++) if (list[i] && list[i].id) seen[list[i].id] = list[i];
    }
    origRender.call(window, list);
    try {
      for (var k = before; k < grid.children.length; k++) {
        var up = list[k - before];
        if (up && up.id) grid.children[k].setAttribute('data-item-id', up.id);
      }
    } catch (e) {}
  }

  window.renderGallery = function (list) {
    if (drop) return;                    // the in-flight loadGallery(1) result
    record(list);
  };

  function banner(html) {
    var el = document.getElementById('wbk-bar');
    if (!el) {
      el = document.createElement('div');
      el.id = 'wbk-bar';
      el.style.cssText = 'position:sticky;top:0;z-index:999;background:#12261f;color:#fff;' +
        'padding:9px 14px;font:600 13px/1.5 -apple-system,"Segoe UI",Arial,sans-serif;' +
        'display:flex;gap:10px;align-items:center;flex-wrap:wrap';
      document.body.insertBefore(el, document.body.firstChild);
    }
    el.innerHTML = html;
    return el;
  }

  function toast(t) {
    var el = banner('<span>' + t + '</span>');
    el.style.background = '#1f7a4d';
    setTimeout(function () { el.style.background = '#12261f'; }, 1500);
  }

  function copy(text, cb) {
    var done = function () { cb && cb(); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
      navigator.clipboard.writeText(text).then(done, function () { fallback(); });
    } else fallback();
    function fallback() {
      var i = document.createElement('textarea');
      i.value = text; i.style.position = 'fixed'; i.style.left = '-9999px';
      document.body.appendChild(i); i.select();
      try { document.execCommand('copy'); } catch (e) {}
      i.remove(); done();
    }
  }

  function button(label, fn, color) {
    var b = document.createElement('button');
    b.textContent = label;
    b.style.cssText = 'background:' + (color || '#2f9e63') + ';color:#fff;border:0;border-radius:8px;' +
      'padding:6px 11px;font:700 12.5px/1.3 inherit;cursor:pointer';
    b.onclick = fn;
    return b;
  }

  function scrollToGallery() {
    var s = document.getElementById('gallery-section');
    if (s) setTimeout(function () { s.scrollIntoView({ behavior: 'smooth', block: 'start' }); }, 60);
  }

  // ── mode 1: artwork deep link -> show that entry only ────────────────────
  if (item && !params.get('all')) {
    var cardEl = null, pinned = true, mo = null;

    drop = true;                                   // swallow the page-1 grid render
    grid.innerHTML = '';
    origRender.call(window, [item]);               // the artwork + its Vote button
    cardEl = grid.firstElementChild;

    // loadGallery(1) wipes the grid itself (grid.innerHTML='') *before* it calls
    // renderGallery, so wrapping renderGallery is not enough: put the card back.
    if (cardEl) {
      mo = new MutationObserver(function () {
        if (pinned && !grid.contains(cardEl)) { grid.innerHTML = ''; grid.appendChild(cardEl); }
      });
      mo.observe(grid, { childList: true });
    }

    // The card's "Voted" flag comes from __SITE__.result_votes, which is a
    // GLOBAL list of recently voted entries (a brand-new visitor sees 1-2 of the
    // 12 visible cards already marked Voted). That silently blocks voting for a
    // perfectly good entry, so re-enable it and let woobox.com decide.
    var vb = grid.querySelector('.btn-vote');
    var cnt = grid.querySelector('.vote-count');
    var revived = false;
    if (vb && vb.classList.contains('voted')) {
      revived = true;
      vb.classList.remove('voted');
      vb.disabled = false;
      vb.textContent = 'Vote';
      vb.onclick = function () {
        vb.disabled = true;
        vb.textContent = 'Voting…';
        WooboxSDK.vote({ upload_id: item.id }).then(function (r) {
          if (r && r.success) {
            vb.classList.add('voted');
            vb.textContent = 'Voted ✓';
            if (cnt && r.votes !== undefined) cnt.textContent = r.votes + ' votes';
            toast('投票成功，谢谢你的支持！');
          } else {
            vb.disabled = false;
            vb.textContent = 'Vote';
            toast('未计入：' + ((r && (r.error || r.code)) || '服务器拒绝') +
                  '（若你已给这张作品投过票，这是正常提示）');
          }
        });
      };
    }

    if (loadMore) {
      var b = loadMore.cloneNode(false);             // drops init()'s click listener too
      loadMore.parentNode.replaceChild(b, loadMore);
      loadMore = b;
      b.className = 'btn btn-secondary';
      b.textContent = '查看全部作品 / Browse all entries';
      b.disabled = false;
      b.style.display = 'block';
      b.onclick = function () {
        pinned = false;
        if (mo) mo.disconnect();
        drop = false;
        b.textContent = 'Load More Entries';
        try { galleryPage = 1; } catch (e) {}
        loadGallery(1);                            // page===1 refills the grid
        b.onclick = function () { galleryPage++; loadGallery(galleryPage); };
      };
    }

    var bar = banner('');
    var sp = document.createElement('span');
    sp.textContent = '直达作品：' + (item.caption || '') + ' · ' + (item.votes || 0) + ' 票';
    bar.appendChild(sp);
    bar.appendChild(button('📋 复制本作品投票链接', function () {
      copy(location.href.split('?')[0], function () { toast('链接已复制，发给亲友即可直达本作品'); });
    }));
    if (vb) bar.appendChild(button(revived ? '↓ 投票（已恢复可点）' : '↓ 投票按钮', function () {
      vb.scrollIntoView({ behavior: 'smooth', block: 'center' });
    }, '#c47f16'));
    if (revived) {
      var w = document.createElement('span');
      w.style.cssText = 'font-weight:400;opacity:.85';
      w.textContent = '该作品本被标成 Voted（站方用全局最近投票列表判断，常为误标），已恢复成可投票。';
      bar.appendChild(w);
    }
    scrollToGallery();
    return;
  }

  // ── mode 2: plain gallery -> auto Load More + optional link dump ─────────
  var dumping = params.get('links') === '1';
  var busy = false, finished = false;

  function tick() {
    if (finished || !loadMore) return;
    if (loadMore.classList.contains('hidden') || !loadMore.parentElement) { finished = true; dump(); return; }
    if (busy || loadMore.disabled) return;
    busy = true;
    var n = Object.keys(seen).length;
    loadMore.click();
    setTimeout(function () {
      busy = false;
      if (Object.keys(seen).length === n) { finished = true; dump(); }
    }, 2600);
  }

  function dump() {
    var list = Object.keys(seen).map(function (k) { return seen[k]; });
    if (!list.length) return;
    list.sort(function (a, b) { return (b.votes || 0) - (a.votes || 0); });

    if (!dumping) {                                // plain gallery: just report, no tooling noise
      var pb = banner('');
      var ps = document.createElement('span');
      ps.textContent = '已自动展开全部 ' + list.length + ' 件作品（无需再点 Load More）'
        + ' · 找名字用 Ctrl/Cmd+F · 要导出直达链接清单请在网址后加 ?links=1';
      pb.appendChild(ps);
      if (loadMore) loadMore.classList.add('hidden');
      return;
    }
    var text = list.map(function (u) {
      return (u.caption || u.id) + '\t' + (u.votes || 0) + '\t' + (u.gallery_url || '');
    }).join('\n');
    var bar = banner('');
    var sp = document.createElement('span');
    sp.textContent = '已抓取 ' + list.length + ' 件作品的直达链接（名字 ⇥ 票数 ⇥ 链接）';
    bar.appendChild(sp);
    bar.appendChild(button('复制全部', function () { copy(text, function () { toast('已复制 ' + list.length + ' 行'); }); }));
    bar.appendChild(button('下载 CSV', function () {
      var csv = list.map(function (u) {
        return ['"' + String(u.caption || u.id).replace(/"/g, '""') + '"', u.votes || 0,
                '"' + (u.gallery_url || '') + '"'].join(',');
      }).join('\n');
      var a = document.createElement('a');
      a.href = URL.createObjectURL(new Blob([csv], { type: 'text/csv' }));
      a.download = 'woobox-links.csv'; a.click();
    }, '#2b6cb0'));
    if (dumping) {
      var ta = document.createElement('textarea');
      ta.value = text;
      ta.style.cssText = 'width:100%;height:60vh;font:12px/1.5 ui-monospace,Consolas,monospace;' +
        'box-sizing:border-box;padding:10px;border:1px solid #ccc;border-radius:10px';
      grid.innerHTML = '';
      grid.appendChild(ta);
      scrollToGallery();
    }
  }

  if (loadMore) {
    setInterval(tick, 900);                       // auto-expand the grid (no more Load More clicking)
    banner(dumping ? '<span>正在抓取全部作品链接…（自动点 Load More，请稍候）</span>'
                   : '<span>正在自动加载全部作品…</span>');
  }
})();
