#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Static shell ("套壳") builder for the Woobox gallery deep-link problem.

Reads the PUBLIC gallery API of the Woobox site, then writes a fully static
site that can be hosted anywhere (GitHub Pages / Cloudflare Pages / Netlify /
any bucket) -- no reverse proxy, no server, no cookies of our own.

Why this works without a proxy
------------------------------
* The gallery API is public (GET, no auth/cookie needed).
* The artwork objects on S3 are public-read, so the signature query string can
  be dropped -> permanent, expiring-free hotlinks.
* Voting itself CANNOT be done from another origin (the /vote endpoint needs a
  per-page _csrf token + session cookie and sends no CORS headers, and OPTIONS
  preflight returns 405). So every "Vote" control in this shell is a link to
  the real woobox.com page; we just make the landing + finding instant.

Usage:  python build.py            # regenerate ./site
Env:    SITE_BASE_URL  absolute base of the deployed shell, e.g.
        https://era.github.io/poster-vote   (used for canonical/og:url)
"""

import io
import json
import os
import ssl
import sys
import time
import urllib.parse
import urllib.request

# ─── site config ────────────────────────────────────────────────────────────
API_ROOT = "https://woobox.com"
API_BASE = "/site_api/ewxzgdgw"          # from __SITE__.settings.api_base
SHARD = "4rq96i"                          # from __SITE__.settings.shard
CONTEST_NAME = "ERA Kids Poster Contest"
PAGE_LIMIT = 100                          # server caps at 100
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "site")
SITE_BASE_URL = (os.environ.get("SITE_BASE_URL") or "").rstrip("/")

# Install-free fix: paste into the address bar (mobile) or drag to the bookmarks
# bar (desktop). Mirrors mode 1 of woobox-item-fix.user.js:
#   * renders __SITE__.gallery.item with the site's own renderGallery()
#   * re-pins that card when loadGallery(1) wipes the grid
#   * revotes the button when the page falsely flags it "Voted" (the site decides)
BOOKMARKLET_LINES = [
 "(function(){",
 "var s=window.__SITE__,g=document.getElementById('gallery-grid');",
 "if(!g||typeof renderGallery!=='function'){alert('请在作品页面(/gallery/编号)里点此书签');return;}",
 "var it=s&&s.gallery&&s.gallery.item;",
 "if(!it){alert('此页面无作品数据，请打开 /gallery/编号 直达链接');return;}",
 "var o=window.renderGallery,drop=true,pinned=true,card=null,mo=null;",
 "window.renderGallery=function(u){if(drop){return;}return o.call(window,u);};",
 "g.innerHTML='';o.call(window,[it]);card=g.firstElementChild;",
 "if(card){mo=new MutationObserver(function(){if(pinned&&!g.contains(card)){g.innerHTML='';g.appendChild(card);}});mo.observe(g,{childList:true});}",
 "var vb=g.querySelector('.btn-vote'),cnt=g.querySelector('.vote-count');",
 "if(vb&&vb.classList.contains('voted')){vb.classList.remove('voted');vb.disabled=false;vb.textContent='Vote';",
 "vb.onclick=function(){vb.disabled=true;vb.textContent='Voting...';",
 "WooboxSDK.vote({upload_id:it.id}).then(function(r){",
 "if(r&&r.success){vb.classList.add('voted');vb.textContent='Voted';",
 "if(cnt&&r.votes!==undefined){cnt.textContent=r.votes+' votes';}}",
 "else{vb.disabled=false;vb.textContent='Vote';alert('未计入：'+((r&&(r.error||r.code))||'服务器拒绝'));}});};}",
 "var l=document.getElementById('load-more');",
 "if(l){var n=l.cloneNode(false);n.className='btn btn-secondary';n.textContent='查看全部作品';n.style.display='block';",
 "n.onclick=function(){pinned=false;if(mo){mo.disconnect();}drop=false;n.textContent='Load More Entries';",
 "try{galleryPage=1;}catch(e){}loadGallery(1);",
 "n.onclick=function(){galleryPage++;loadGallery(galleryPage);};};",
 "l.parentNode.replaceChild(n,l);n.classList.remove('hidden');}",
 "var bar=document.createElement('div');",
 "bar.style.cssText='position:sticky;top:0;z-index:999;background:#12261f;color:#fff;padding:9px 14px;font:600 13px/1.5 -apple-system,Segoe UI,Arial,sans-serif';",
 "bar.textContent='直达作品：'+(it.caption||'')+' · '+(it.votes||0)+' 票';",
 "document.body.insertBefore(bar,document.body.firstChild);",
 "var sec=document.getElementById('gallery-section');if(sec){sec.scrollIntoView();}",
 "})();void(0)",
]
BOOKMARKLET_JS = " ".join(BOOKMARKLET_LINES)

UA = {"User-Agent": "Mozilla/5.0 (compatible; vote-shell-builder/1.0)"}
CTX = ssl.create_default_context()


def fetch_json(path, retries=4):
    url = API_ROOT + API_BASE + path
    last = None
    for i in range(retries):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=45, context=CTX) as r:
                return json.load(r)
        except Exception as e:                      # noqa: BLE001
            last = e
            time.sleep(1.5 * (i + 1))
    raise SystemExit("API fetch failed: %s (%s)" % (url, last))


def strip_sig(url):
    """offertabs.s3.amazonaws.com objects are public-read -> drop the presigner."""
    return (url or "").split("?")[0]


def format_caption(raw):
    """Byte-for-byte port of app.js formatCaption() so the text fragment we
    generate matches the text the site actually renders in the card."""
    if not raw or raw == "Student Entry":
        return "Student Entry"
    parts = raw.split(" - ")
    if len(parts) > 1:
        return parts[0].strip().split()[0] + " - " + " - ".join(parts[1:]).strip()
    return (raw.strip().split()[0] if raw.strip() else "Student Entry")


def load_all():
    items, page = [], 1
    while True:
        d = fetch_json("/gallery?page=%d&limit=%d" % (page, PAGE_LIMIT))
        ups = d.get("uploads") or []
        items.extend(ups)
        if not d.get("has_more") or page > 40:
            break
        page += 1
    return items, d


GALLERY_LIMIT = 12        # app.js: const galleryLimit = 12 (page size of the real grid)


def build_records(raw_items):
    """raw_items arrive in the order the real grid renders them (sort=newest)."""
    recs = []
    for n, u in enumerate(raw_items):
        img = strip_sig(u.get("large_url") or u.get("photo_url"))
        recs.append({
            "id": u["id"],
            "caption": format_caption(u.get("caption")),
            "raw_caption": u.get("caption"),
            "uploaded_by": u.get("uploaded_by") or "",
            "votes": int(u.get("votes") or 0),
            "type": u.get("type") or "photo",
            "img": img,
            "thumb": strip_sig(u.get("thumb_url")) or img,
            "deep": u.get("gallery_url") or "%s/%s/gallery/%s" % (API_ROOT, SHARD, u["id"]),
            # #:~:text= makes Chrome/Edge/Android/Safari scroll the caption (and
            # therefore its Vote button) into view even without the userscript.
            # Verified in Chromium: #:~:text= alone does NOT match cards that
            # are rendered by JS after load (scrollY stays 0), while the page's
            # own #gallery-section anchor scrolls reliably. Use the anchor and
            # keep the text fragment as a best-effort extra.
            "frag": "#gallery-section:~:text=" + urllib.parse.quote(format_caption(u.get("caption"))),
            "pos": n + 1,
            "grid_page": n // GALLERY_LIMIT + 1,
            "grid_slot": n % GALLERY_LIMIT + 1,
            "load_more_clicks": n // GALLERY_LIMIT,
            "page": "v/%s.html" % u["id"],
        })
    recs.sort(key=lambda r: (-r["votes"], r["caption"]))
    return recs


# ─── templates ──────────────────────────────────────────────────────────────
CSS = """
:root{--ink:#12261f;--sub:#5b6f66;--line:#e3e9e5;--brand:#1f7a4d;--bg:#f6f8f7}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","PingFang SC","Hiragino Sans GB","Microsoft YaHei",sans-serif}
.wrap{max-width:760px;margin:0 auto;padding:18px 16px 60px}
.card{background:#fff;border:1px solid var(--line);border-radius:16px;overflow:hidden;
 box-shadow:0 4px 18px rgba(18,38,31,.06)}
.hero{padding:16px 16px 0;font-size:13px;color:var(--sub)}
.hero a{color:var(--brand);text-decoration:none;font-weight:600}
h1{font-size:21px;margin:10px 16px 4px;line-height:1.3}
.meta{margin:0 16px 14px;font-size:13px;color:var(--sub)}
.shot{display:block;width:100%;height:auto;background:#fff}
.shot video,.shot img{display:block;width:100%;height:auto}
.row{display:flex;gap:10px;flex-wrap:wrap;padding:0 16px 16px}
.btn{flex:1 1 180px;text-align:center;padding:14px 16px;border-radius:12px;font-size:16px;
 font-weight:700;text-decoration:none;border:0;cursor:pointer;display:block}
.btn-p{background:var(--brand);color:#fff;box-shadow:0 6px 16px rgba(31,122,77,.25)}
.btn-p:active{transform:translateY(1px)}
.btn-s{background:#fff;color:var(--brand);border:1.5px solid var(--brand);font-size:14px;padding:11px}
.note{margin:0 16px 18px;font-size:12.5px;color:var(--sub);line-height:1.65;
 background:#fff;border:1px dashed var(--line);border-radius:12px;padding:12px 14px}
.pos{margin:0 16px 14px;font-size:13px;color:#31513f;line-height:1.6;
 background:#eef7f1;border-left:3px solid var(--brand);border-radius:0 10px 10px 0;padding:10px 12px}
.count{display:inline-flex;align-items:center;gap:6px;background:#eef7f1;color:#155e3c;
 border-radius:999px;padding:5px 12px;font-size:13px;font-weight:700}
.others{display:grid;grid-template-columns:repeat(auto-fill,minmax(104px,1fr));gap:10px;padding:0 16px 8px}
.others a{display:block;text-decoration:none;color:inherit;font-size:12px;line-height:1.35}
.others img{width:100%;aspect-ratio:1/1;object-fit:cover;border-radius:10px;border:1px solid var(--line)}
.others span{display:block;color:var(--sub);margin-top:4px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sec{margin:26px 0 8px;font-size:14px;font-weight:700;padding:0 16px}
#frame{width:100%;height:78vh;border:1px solid var(--line);border-radius:12px;background:#fff;display:none}
#frame.on{display:block}
.toast{position:fixed;left:50%;bottom:26px;transform:translateX(-50%);background:#12261f;color:#fff;
 padding:10px 16px;border-radius:999px;font-size:13px;opacity:0;transition:.25s;pointer-events:none}
.toast.on{opacity:1}
.pager{display:flex;justify-content:space-between;gap:10px;padding:0 16px 10px;font-size:14px}
.pager a{color:var(--brand);text-decoration:none;font-weight:600}
"""

ITEM_TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>Vote @@TITLE@@ · @@CONTEST@@</title>
<meta name="description" content="@@DESC@@">
<meta property="og:type" content="article">
<meta property="og:title" content="Vote for @@TITLE@@ · @@CONTEST@@">
<meta property="og:description" content="@@DESC@@">
<meta property="og:image" content="@@IMG@@">
<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="Vote for @@TITLE@@">
<meta name="twitter:image" content="@@IMG@@">
@@CANON@@<style>@@CSS@@</style>
</head><body>
<div class="wrap">
 <div class="hero"><a href="@@BACK@@">← 全部作品 / All entries</a></div>
 <div class="card">
  <h1>@@TITLE@@</h1>
  <div class="meta"><span class="count"><span id="v">@@VOTES@@</span> votes</span>
   <span id="asof">· snapshot @@ASOF@@</span><br>Entry uploaded by @@UPLOADED_BY@@</div>
  <div class="shot">@@SHOT@@</div>
  <div class="row">
   <a class="btn btn-p" id="votewin" href="@@DEEP@@@@FRAG@@" target="_blank" rel="noopener">🗳️ 给这个作品投票 / Vote</a>
  </div>
  <div class="row">
   <button class="btn btn-s" id="inline">▾ 不跳走，在本页内投票</button>
   <button class="btn btn-s" id="copy">🔗 复制本页链接发给亲友</button>
  </div>
  <div class="pos">📍 官方页面里这张作品位于<b>按最新排序的第 @@POS@@ 位</b>：
   打开后页面会自动滚到作品区；若还没看到，再点 <b>@@CLICKS@@ 次 Load More</b>
   （第 @@GPAGE@@ 页第 @@SLOT@@ 张）。找不到就用浏览器搜索 <b>@@TITLE@@</b>。</div>
  <iframe id="frame" data-src="@@DEEP@@@@FRAG@@" src="about:blank" title="official voting page"></iframe>
  <div class="note">
   <b>为什么票要回官方页面投：</b>投票接口 <code>@@API@@/vote</code> 只认页面自带的
   <code>_csrf</code> + 会话 Cookie，跨域 POST 一律 403、预检 OPTIONS 直接 405，
   所以上面的投票区是直接把官方页面套进来（同域，无响应头限制，无反向代理），
   你点的仍是 woobox.com 自己的 Vote 按钮。每人对同一作品限投一票，投过显示 <i>Voted</i>。<br>
   <b>想少点几下：</b>装书签/油猴脚本后，官方链接 <code>@@DEEP@@</code>
   本身就只显示这张作品（<a href="@@BACK@@#tools-fix">安装说明</a>）；票数每次构建刷新。
  </div>
 </div>
<div class="pager"><span>@@PREV@@</span><span>NEXT@@NEXTL@@</span></div>
 <div class="sec">其它作品 / Other entries</div>
 <div class="others">@@OTHERS@@</div>
</div>
<div class="toast" id="toast">已复制</div>
<script>
var DEEP = "@@DEEP@@", FRAG = "@@FRAG@@", SHARE = "@@SHAREURL@@";
var OFF = document.getElementById('inline').textContent, ON = '▴ 收起投票页';
(function(){
  var f=document.getElementById('frame'), b=document.getElementById('inline');
  function openFrame(){
    if(f.classList.contains('on')){ f.classList.remove('on'); f.src='about:blank';
      b.textContent=OFF; return; }
    if(!f.src||f.src==='about:blank') f.src=f.getAttribute('data-src');
    f.classList.add('on'); b.textContent=ON;
    f.scrollIntoView({behavior:'smooth',block:'center'});
  }
  b.onclick=openFrame;
  // woobox SDK posts {type:'woobox:resize',height} while embedded -> perfect height
  addEventListener('message',function(e){
    var d=e.data; if(d&&d.type==='woobox:resize'&&d.height) f.style.height=Math.min(d.height+40,window.innerHeight)+'px';
  });
  function toast(t){var el=document.getElementById('toast');el.textContent=t;el.classList.add('on');setTimeout(function(){el.classList.remove('on')},1600);}
  document.getElementById('copy').onclick=function(){
    var url=SHARE;
    (navigator.clipboard?navigator.clipboard.writeText(url):Promise.reject()).then(function(){toast('已复制直达链接')},
      function(){var i=document.createElement('textarea');i.value=url;document.body.appendChild(i);i.select();document.execCommand('copy');i.remove();toast('已复制直达链接');});
  };
  // same-origin snapshot refresh (plain static file, no proxy involved)
  if(location.protocol.indexOf('http')===0){
    var id=location.pathname.split('/').pop().replace('.html','');
    fetch('../votes.json',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
      var m=j.votes||j;                       // {id:n} or {built_at,votes:{id:n}}
      if(m[id]!==undefined){
        document.getElementById('v').textContent=m[id];
        document.getElementById('asof').textContent='· 票数已刷新'+(j.built_at?('（快照建于 '+j.built_at.replace('T',' ')+')'):'');
      }
    }).catch(function(){});
  }
})();
</script>
</body></html>
"""

INDEX_TPL = """<!DOCTYPE html>
<html lang="zh-CN"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<title>@@CONTEST@@ · 作品投票直达 / Direct voting links</title>
<meta name="description" content="按名字找到作品，一个链接直达它的投票按钮，不用翻 Load More。">
<style>@@CSS@@
header{padding:22px 16px 6px}h1{font-size:22px;margin:0 0 6px}
p.lead{margin:0;font-size:14px;color:var(--sub);line-height:1.6}
.tools{position:sticky;top:0;z-index:5;background:var(--bg);padding:12px 16px;border-bottom:1px solid var(--line)}
#q{width:100%;padding:13px 14px;font-size:16px;border:1.5px solid var(--line);border-radius:12px;background:#fff}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(150px,1fr));gap:12px;padding:14px 0 0}
.it{background:#fff;border:1px solid var(--line);border-radius:14px;overflow:hidden;font-size:13px}
.it img{width:100%;aspect-ratio:1/1;object-fit:cover;display:block;background:#fff}
.it .b{padding:8px 10px 10px}
.it .n{font-weight:700;font-size:13.5px;line-height:1.3;margin-bottom:4px}
.it .v{color:var(--sub);font-size:12px;margin-bottom:7px}
.it a,.it button{display:block;width:100%;text-align:center;font-size:13px;padding:8px;border-radius:9px;
 text-decoration:none;font-weight:700;border:0;cursor:pointer;margin-top:5px}
.it a{background:var(--brand);color:#fff}
.it button{background:#eef2ef;color:#31513f}
.rank{display:flex;flex-wrap:wrap;gap:7px;padding:10px 16px 0;font-size:12.5px}
.rank span{background:#fff;border:1px solid var(--line);border-radius:999px;padding:5px 10px}
#tools{padding:18px 16px;font-size:14px;line-height:1.75}
#tools code{background:#eef2ef;padding:1px 5px;border-radius:5px;font-size:12.5px;word-break:break-all}
#tools h2{font-size:16px;margin:18px 0 6px}
.bkmk{display:inline-block;background:var(--brand);color:#fff;padding:9px 14px;border-radius:10px;
 text-decoration:none;font-weight:700;font-size:14px}
pre{background:#12261f;color:#dfe9e3;padding:12px 14px;border-radius:12px;overflow:auto;font-size:12px;line-height:1.6}
label{font-size:13px;color:var(--sub)}
select{padding:8px;border-radius:8px;border:1px solid var(--line);font-size:13px}
</style></head><body>
<header>
 <h1>@@CONTEST@@</h1>
 <p class="lead"><b>@@TOTAL@@</b> 件作品。输入孩子/班级名字，直接打开该作品的投票页链接（不用点 Load More 一页页翻）。
 链接发给亲友，对方点一下就落在它的 <i>Vote</i> 按钮上。</p>
</header>
<div class="tools">
 <input id="q" placeholder="搜索名字 / Search a name, e.g. Hanna" autocomplete="off" inputmode="search">
 <div class="rank" id="rank"></div>
 <div id="live" style="margin-top:8px;font-size:12.5px;color:#7d8b85"></div>
</div>
<div class="wrap" style="padding-top:0">
 <div class="grid" id="grid"></div>
 <div class="note" id="empty" style="display:none;margin:16px 0">没有匹配的作品。</div>
 <div id="tools">
  <h2 id="t-links">批量导出链接</h2>
  <button class="btn btn-s" id="csv" style="max-width:260px">⬇ 导出 CSV（名字 + 直达链接）</button>
  <label style="margin-left:8px">排序 <select id="sort"><option value="votes">票数</option><option value="name">名字</option></select></label>
  <h2 id="tools-fix">让官方链接本身就能直达（可选，装一次）</h2>
  <p>官方页面把作品数据写在了 <code>window.__SITE__.gallery.item</code>，但前端 <code>init()</code>
  却调 <code>loadGallery(1)</code> 渲染整页画廊，所以 <code>/4rq96i/gallery/&lt;id&gt;</code> 不会显示那张作品。
  装下面任一工具即可修正（投票仍在 woobox.com 上完成，不涉及反向代理）：</p>
  <p>① <b>书签脚本（免安装）</b>：把
   <a class="bkmk" id="bkmk" href="@@BK@@">🗳️ 直达作品</a> 拖到书签栏；在官方作品页点一下即可。
   手机可把 <a href="bookmarklet.txt">bookmarklet.txt</a> 里的 <code>javascript:</code> 代码粘贴到地址栏执行。</p>
  <p>② <b>油猴脚本</b>：<a href="woobox-item-fix.user.js">woobox-item-fix.user.js</a>
   （Tampermonkey / Violentmonkey，自动生效；还支持 <code>?all=1</code> 看回整页画廊）。</p>
  <p>③ 给 Woobox 提需求：在 <code>app.js</code> 的 <code>init()</code> 里用
   <code>site.gallery.item</code> 渲染一次即可（约 4 行），见 <code>PATCH_FOR_WOOBOX.md</code>。</p>
 </div>
</div>
<div class="toast" id="toast"></div>
<script>
var DATA=@@DATA@@, BASE="@@BASE@@";
function esc(s){return String(s).replace(/[&<>"]/g,function(c){return{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]})}
function shellUrl(r){return BASE||(location.origin+location.pathname.replace(/[^/]*$/,''))+r.page}
function render(){
 var q=document.getElementById('q').value.trim().toLowerCase();
 var mode=document.getElementById('sort').value;
 var list=DATA.filter(function(r){return !q||r.caption.toLowerCase().indexOf(q)>=0||String(r.uploaded_by).toLowerCase().indexOf(q)>=0});
 list.sort(mode==='name'?function(a,b){return a.caption.localeCompare(b.caption)}:function(a,b){return b.votes-a.votes});
 document.getElementById('grid').innerHTML=list.map(function(r){
  return '<div class="it"><a href="'+r.page+'"><img loading="lazy" src="'+r.thumb+'" alt="'+esc(r.caption)+'"></a>'+
   '<div class="b"><div class="n">'+esc(r.caption)+'</div><div class="v">'+r.votes+' votes · by '+esc(r.uploaded_by)+'</div>'+
   '<a href="'+r.page+'">投票页 / Vote</a><button data-i="'+r.id+'">复制直达链接</button></div></div>'}).join('');
 document.getElementById('empty').style.display=list.length?'none':'block';
}
function leaderboard(){   // NOT named "top": a global function called top collides
                         // with window.top and SyntaxErrors the whole script
 var t=DATA.slice().sort(function(a,b){return b.votes-a.votes}).slice(0,10);
 document.getElementById('rank').innerHTML=t.map(function(r,i){return '<span>'+(i+1)+'. '+esc(r.caption)+' · '+r.votes+'</span>'}).join('');
}
function toast(t){var e=document.getElementById('toast');e.textContent=t;e.classList.add('on');setTimeout(function(){e.classList.remove('on')},1600)}
// vote counts come from votes.json, which GitHub Actions rebuilds every ~10 min;
// if the fetch fails we simply keep the numbers baked into this file
function refreshVotes(){
  if(location.protocol.indexOf('http')!==0)return;
  fetch('votes.json',{cache:'no-store'}).then(function(r){return r.json()}).then(function(j){
    var m=j.votes||j,n=0;
    for(var i=0;i<DATA.length;i++){if(m[DATA[i].id]!==undefined&&m[DATA[i].id]!==DATA[i].votes){DATA[i].votes=m[DATA[i].id];n++}}
    render();leaderboard();
    var s=document.getElementById('live');
    if(s)s.textContent='票数已刷新（'+(n?('变动 '+n+' 件'):'与快照一致')+' · 快照建于 '+(j.built_at?j.built_at.replace('T',' '):'本次构建')+'）· 共 '+DATA.length+' 件作品';
  }).catch(function(){});
}
document.getElementById('q').addEventListener('input',render);
document.getElementById('sort').addEventListener('change',render);
document.getElementById('grid').addEventListener('click',function(e){
 var b=e.target.closest('button[data-i]'); if(!b)return;
 var r=DATA.filter(function(x){return x.id===b.getAttribute('data-i')})[0]; if(!r)return;
 var url=shellUrl(r), d=DEEPL(r);
 (navigator.clipboard?navigator.clipboard.writeText(url):Promise.reject()).then(function(){toast('已复制：'+r.caption+' → '+url)},
  function(){var i=document.createElement('textarea');i.value=url;document.body.appendChild(i);i.select();document.execCommand('copy');i.remove();toast('已复制')});
 e.preventDefault();
});
function DEEPL(r){return r.deep}
document.getElementById('csv').onclick=function(){
 var rows=[['caption','votes','uploader','shell_page','woobox_deeplink']].concat(DATA.map(function(r){
  return [r.caption,r.votes,r.uploaded_by,location.origin+location.pathname.replace(/[^/]*$/,'')+r.page,r.deep]}));
 var csv=rows.map(function(r){return r.map(function(c){return '"'+String(c).replace(/"/g,'""')+'"'}).join(',')}).join('\\n');
 var a=document.createElement('a');a.href=URL.createObjectURL(new Blob([csv],{type:'text/csv'}));a.download='vote-links.csv';a.click();
};
render();leaderboard();refreshVotes();
</script>
</body></html>
"""


def render_item(rec, all_recs, generated, rank_of):
    idx = rank_of[rec["id"]]
    prev = all_recs[idx - 1] if idx > 0 else None           # list is votes-desc
    nxt = all_recs[idx + 1] if idx + 1 < len(all_recs) else None
    others = [r for r in all_recs if r["id"] != rec["id"]][:12]
    shot = ('<img src="%s" alt="%s">' % (rec["img"], rec["caption"].replace('"', "&quot;"))
            if rec["type"] == "photo"
            else '<a href="%s"><img src="%s" alt="%s"></a><div class="note">该作品为 %s，请在官方页面查看。</div>'
                 % (rec["deep"], rec["thumb"], rec["caption"], rec["type"]))
    share = (SITE_BASE_URL + "/" + rec["page"]) if SITE_BASE_URL else rec["page"]
    canon = ('<link rel="canonical" href="%s">\n' % (SITE_BASE_URL + "/" + rec["page"])) if SITE_BASE_URL else ""
    html = (ITEM_TPL
            .replace("@@CONTEST@@", CONTEST_NAME)
            .replace("@@CSS@@", CSS)
            .replace("@@CANON@@", canon)
            .replace("@@BACK@@", "../index.html")
            .replace("@@TITLE@@", rec["caption"])
            .replace("@@DESC@@", "Vote for %s in %s (%d votes so far)." % (rec["caption"], CONTEST_NAME, rec["votes"]))
            .replace("@@IMG@@", rec["img"])
            .replace("@@VOTES@@", str(rec["votes"]))
            .replace("@@ASOF@@", generated)
            .replace("@@UPLOADED_BY@@", rec["uploaded_by"] or "—")
            .replace("@@POS@@", str(rec["pos"]))
            .replace("@@CLICKS@@", str(rec["load_more_clicks"]))
            .replace("@@GPAGE@@", str(rec["grid_page"]))
            .replace("@@SLOT@@", str(rec["grid_slot"]))
            .replace("@@API@@", API_ROOT + API_BASE)
            .replace("@@SHOT@@", shot)
            .replace("@@DEEP@@", rec["deep"])
            .replace("@@FRAG@@", rec["frag"])
            .replace("@@SHAREURL@@", share)
            .replace("@@PREV@@", ('<a href="%s">← %s</a>' % (prev["page"], prev["caption"])) if prev else "")
            .replace("@@NEXTL@@", (' <a href="%s">%s →</a>' % (nxt["page"], nxt["caption"])) if nxt else "")
            .replace("@@OTHERS@@", "".join(
                '<a href="%s"><img loading="lazy" src="%s" alt="%s"><span>%s</span></a>'
                % (r["page"], r["thumb"], r["caption"].replace('"', "&quot;"), r["caption"]) for r in others)))
    return html


def js_selfcheck():
    """An inline script that dies on a SyntaxError fails *silently* in the
    browser (page looks fine, shows nothing), so fail the build instead.
    Also catches declaring a global name that already exists on `window`
    (top, name, length, status, ...): a SyntaxError in a classic script,
    which a plain syntax check on a wrapped copy would happily accept."""
    import re as _re
    import subprocess
    import tempfile

    COLLIDERS = ("top", "name", "length", "status", "origin", "location", "history",
                 "close", "open", "focus", "blur", "print", "screen", "frameElement")
    pat = _re.compile(r"^\s*(?:function|var|let|const)\s+(%s)\b" % "|".join(COLLIDERS), _re.M)
    try:
        node = subprocess.run(["node", "--version"], capture_output=True, timeout=20).returncode == 0
    except Exception:
        node = False

    problems, checked = [], 0
    vdir = os.path.join(OUT, "v")
    names = sorted(os.listdir(vdir))
    files = [os.path.join(OUT, "index.html"), os.path.join(OUT, "woobox-item-fix.user.js")]
    files += [os.path.join(vdir, f) for f in names[:12]] + [os.path.join(vdir, f) for f in names[-4:]]
    files = [f for f in files if os.path.exists(f)]
    tmp = os.path.join(tempfile.gettempdir(), "wooboxjscheck.js")
    for path in files:
        text = io.open(path, encoding="utf-8").read()
        blocks = _re.findall(r"<script>(.*?)</script>", text, _re.S) if path.endswith(".html") else [text]
        for n, js in enumerate(blocks):
            checked += 1
            hit = pat.search(js)
            if hit:
                problems.append("%s [%d]: global '%s' collides with window.%s"
                                % (os.path.basename(path), n, hit.group(1), hit.group(1)))
            elif node:
                io.open(tmp, "w", encoding="utf-8").write(js)
                r = subprocess.run(["node", "--check", tmp], capture_output=True, timeout=60)
                if r.returncode:
                    problems.append("%s [%d]: %s" % (os.path.basename(path), n,
                                                     r.stderr.decode("utf-8", "replace")[:300]))
    print("js self-check: %d script blocks (%s) -> %s"
          % (checked, "node --check + name scan" if node else "name scan only",
             "OK" if not problems else "PROBLEMS"))
    for p in problems:
        print("  !!", p)
    if problems:
        sys.exit(2)


def main():
    raw, meta = load_all()
    recs = build_records(raw)
    total = meta.get("total")
    if total and len(recs) < total:
        print("WARN: fetched %d of %d entries" % (len(recs), total))

    generated = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime())
    vd = os.path.join(OUT, "v")
    os.makedirs(vd, exist_ok=True)
    rank_of = {r["id"]: i for i, r in enumerate(recs)}
    for r in recs:
        with open(os.path.join(vd, r["id"] + ".html"), "w", encoding="utf-8") as f:
            f.write(render_item(r, recs, generated, rank_of))

    with open(os.path.join(OUT, "items.json"), "w", encoding="utf-8") as f:
        json.dump({"generated_at": generated, "total": len(recs), "items": recs}, f, ensure_ascii=False, indent=1)
    with open(os.path.join(OUT, "votes.json"), "w", encoding="utf-8") as f:
        # compact: {"built_at":..., "votes":{id:n}} - pages read either shape
        json.dump({"built_at": generated, "votes": {r["id"]: r["votes"] for r in recs}},
                  f, separators=(",", ":"))

    KEYS = ("id", "caption", "votes", "uploaded_by", "thumb", "page", "deep", "type", "frag",
            "pos", "grid_page", "grid_slot", "load_more_clicks")
    data = json.dumps([{k: r[k] for k in KEYS}
                       for r in recs], ensure_ascii=False, separators=(",", ":"))
    bk_href = "javascript:" + urllib.parse.quote(BOOKMARKLET_JS, safe="")
    with open(os.path.join(OUT, "bookmarklet.txt"), "w", encoding="utf-8") as f:
        f.write(bk_href + chr(10))

    # GitHub Pages runs Jekyll only on the classic branch deploy; an empty
    # .nojekyll keeps that path working too (entry ids are plain names here, but
    # it also stops Jekyll from rewriting anything).
    with open(os.path.join(OUT, ".nojekyll"), "w") as f:
        f.write("")

    idx_html = (INDEX_TPL.replace("@@CONTEST@@", CONTEST_NAME).replace("@@CSS@@", CSS)
                .replace("@@TOTAL@@", str(len(recs))).replace("@@DATA@@", data)
                .replace("@@BK@@", bk_href.replace("&", "&amp;"))
                .replace("@@BASE@@", (SITE_BASE_URL + "/") if SITE_BASE_URL else ""))
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(idx_html)

    us = os.path.join(os.path.dirname(os.path.abspath(__file__)), "woobox-item-fix.user.js")
    if os.path.exists(us):
        with open(us, encoding="utf-8") as f:
            body = f.read()
        with open(os.path.join(OUT, "woobox-item-fix.user.js"), "w", encoding="utf-8") as f:
            f.write(body)

    print("built %d item pages + index.html (%s entries, total=%s)" % (len(recs), len(recs), total))
    print("top:", ", ".join("%s=%d" % (r["caption"], r["votes"]) for r in recs[:5]))
    js_selfcheck()


if __name__ == "__main__":
    main()
