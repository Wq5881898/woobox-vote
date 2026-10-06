import io

NEW = '''# Install-free fix: paste into the address bar (mobile) or drag to the bookmarks
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
'''

lines = io.open('build.py', encoding='utf-8').read().split('\n')
start = next(i for i, l in enumerate(lines) if l.startswith('BOOKMARKLET_JS = ('))
end = next(i for i, l in enumerate(lines) if i > start and l.rstrip().endswith('})();void(0)")'))
lines[start:end + 1] = NEW.rstrip('\n').split('\n')
io.open('build.py', 'w', encoding='utf-8').write('\n'.join(lines))
print('bookmarklet block replaced at lines %d-%d' % (start + 1, end + 1))
