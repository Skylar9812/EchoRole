const assert = require('node:assert/strict');

module.exports = async page => {
  const scroll = await page.evaluate(()=>({x:scrollX,y:scrollY}));
  for (const img of await page.locator('img').all()) {
    if (!(await img.isVisible())) continue;
    const before = await img.boundingBox();
    await img.scrollIntoViewIfNeeded();
    await img.evaluate(async el => { if (!el.complete) await new Promise((resolve,reject)=>{el.addEventListener('load',resolve,{once:true});el.addEventListener('error',reject,{once:true});}); await el.decode(); });
    const info = await img.evaluate(el=>({width:el.naturalWidth,height:el.naturalHeight,alt:el.getAttribute('alt'),hidden:el.getAttribute('aria-hidden'),fit:getComputedStyle(el).objectFit,final:el.src.includes('illustrations')}));
    assert(info.width>0 && info.height>0,'Image must decode');
    if (info.final) {
      assert.equal(info.alt,''); assert.equal(info.hidden,'true');
      assert.equal(info.fit,'contain');
      const after=await img.boundingBox();
      assert.equal(after.width,before.width,'Image width must be reserved before decode');
      assert.equal(after.height,before.height,'Image height must be reserved before decode');
    }
  }
  assert(await page.evaluate(()=>{
    const img=document.querySelector('[data-illustration-slot="hero"] img');
    const copy=document.querySelector('#landing-title')?.parentElement;
    if(!img||!copy)return true;
    const art=img.getBoundingClientRect(), walker=document.createTreeWalker(copy,NodeFilter.SHOW_TEXT);
    for(let node=walker.nextNode();node;node=walker.nextNode()) {
      if(!node.textContent.trim())continue;
      const range=document.createRange();range.selectNodeContents(node);
      for(const r of range.getClientRects()) if(r.width&&r.height&&r.right>art.left+1&&r.left<art.right-1&&r.bottom>art.top+1&&r.top<art.bottom-1)return false;
    }
    return true;
  }),'Hero artwork must not overlap narrative text');
  await page.evaluate(p=>scrollTo(p.x,p.y),scroll);
};
