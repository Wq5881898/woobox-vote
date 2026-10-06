import io, re

p = 'build.py'
s = io.open(p, encoding='utf-8').read()

# ── 1. build_records: keep the API/gallery default order, add position hints ──
s = s.replace(
    '''def build_records(raw_items):
    recs = []
    for u in raw_items:''',
    '''GALLERY_LIMIT = 12        # app.js: const galleryLimit = 12 (page size of the real grid)


def build_records(raw_items):
    """raw_items arrive in the order the real grid renders them (sort=newest)."""
    recs = []
    for n, u in enumerate(raw_items):''')

s = s.replace(
    '''            "frag": "#:~:text=" + urllib.parse.quote(format_caption(u.get("caption"))),''',
    '''            # Verified in Chromium: #:~:text= alone does NOT match cards that
            # are rendered by JS after load (scrollY stays 0), while the page's
            # own #gallery-section anchor scrolls reliably. Use the anchor and
            # keep the text fragment as a best-effort extra.
            "frag": "#gallery-section:~:text=" + urllib.parse.quote(format_caption(u.get("caption"))),
            "pos": n + 1,
            "grid_page": n // GALLERY_LIMIT + 1,
            "grid_slot": n % GALLERY_LIMIT + 1,
            "load_more_clicks": n // GALLERY_LIMIT,''')

# ── 2. item template: one-click voting surface + position hint ──
old = s[s.index('''  <div class="shot">@@SHOT@@</div>'''):s.index('''<div class="pager">''')]
new = '''  <div class="shot">@@SHOT@@</div>
  <div class="row">
   <button class="btn btn-p" id="inline">🗳️ 就在这里投票 / Vote here</button>
  </div>
  <div class="row">
   <a class="btn btn-s" id="votewin" href="@@DEEP@@@@FRAG@@">↗ 在新标签打开官方投票页</a>
   <button class="btn btn-s" id="copy">🔗 复制本页链接发给亲友</button>
  </div>
  <div class="pos">📍 官方页面里这张作品位于<b>按最新排序的第 @@POS@@ 位</b>：
   作品区已自动展开；若还没出现，再点 <b>@@CLICKS@@ 次 Load More</b>
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
'''
s = s.replace(old, new)

# ── 3. iframe js: load data-src on click, keep resize handshake ──
s = s.replace("""  var f=document.getElementById('frame'), b=document.getElementById('inline');
  b.onclick=function(){
    var on=f.classList.toggle('on');
    if(on){ f.src=DEEP; b.textContent='▴ 收起投票页'; f.scrollIntoView({behavior:'smooth',block:'center'}); }
    else { f.src='about:blank'; b.textContent='▾ 在本页内投票（打开投票页）'; }
  };""",
"""  var f=document.getElementById('frame'), b=document.getElementById('inline');
  function openFrame(){
    if(f.classList.contains('on')){ f.classList.remove('on'); f.src='about:blank';
      b.textContent='🗳️ 就在这里投票 / Vote here'; return; }
    if(!f.src||f.src==='about:blank') f.src=f.getAttribute('data-src');
    f.classList.add('on'); b.textContent='▴ 收起投票页';
    f.scrollIntoView({behavior:'smooth',block:'center'});
  }
  b.onclick=openFrame;""")

# ── 4. .pos style ──
s = s.replace('''.count{display:inline-flex''',
              '''.pos{margin:0 16px 14px;font-size:13px;color:#31513f;line-height:1.6;
 background:#eef7f1;border-left:3px solid var(--brand);border-radius:0 10px 10px 0;padding:10px 12px}
.count{display:inline-flex''')

# ── 5. render_item substitutions for the new placeholders ──
s = s.replace('''            .replace("@@UPLOADED_BY@@", rec["uploaded_by"] or "—")''',
              '''            .replace("@@UPLOADED_BY@@", rec["uploaded_by"] or "—")
            .replace("@@POS@@", str(rec["pos"]))
            .replace("@@CLICKS@@", str(rec["load_more_clicks"]))
            .replace("@@GPAGE@@", str(rec["grid_page"]))
            .replace("@@SLOT@@", str(rec["grid_slot"]))
            .replace("@@API@@", API_ROOT + API_BASE)''')

# ── 6. DATA for index.html: carry the position hints too ──
s = s.replace('''    data = json.dumps([{k: r[k] for k in ("id", "caption", "votes", "uploaded_by", "thumb", "page", "deep", "type")}''',
              '''    KEYS = ("id", "caption", "votes", "uploaded_by", "thumb", "page", "deep", "type", "frag",
            "pos", "grid_page", "grid_slot", "load_more_clicks")
    data = json.dumps([{k: r[k] for k in KEYS}''')

io.open(p, 'w', encoding='utf-8').write(s)
print('build.py updated')
