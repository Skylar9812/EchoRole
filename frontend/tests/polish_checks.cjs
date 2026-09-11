const assert = require('node:assert/strict');
const { writeFileSync, mkdirSync } = require('node:fs');
const { join } = require('node:path');

module.exports = async function polish(page, name) {
  const result = await page.evaluate(() => {
    const visible = el => !!el.getClientRects().length && !el.closest('[aria-hidden=true]');
    const parse = text => (text.match(/[\d.]+/g)||[]).map(Number);
    const blend = (a,b) => { const alpha=a[3]??1; return a.slice(0,3).map((v,i)=>v*alpha+b[i]*(1-alpha)); };
    const background = el => { const ancestors=[]; for(let x=el;x;x=x.parentElement) ancestors.unshift(x); return ancestors.reduce((bg,x)=>blend(parse(getComputedStyle(x).backgroundColor),bg),[255,255,255]); };
    const lum = rgb => rgb.map(v=>v/255).map(v=>v<=.04045?v/12.92:((v+.055)/1.055)**2.4).reduce((v,x,i)=>v+x*[.2126,.7152,.0722][i],0);
    const issues=[];
    for(const el of document.querySelectorAll('p,div,em,span,small,strong,h1,h2,h3,label,summary,button,a')) {
      if(!visible(el)||el.closest(':disabled')||!Array.from(el.childNodes).some(n=>n.nodeType===3&&n.textContent.trim())) continue;
      const style=getComputedStyle(el), bg=background(el), fg=blend(parse(style.color),bg);
      const ratio=(Math.max(lum(bg),lum(fg))+.05)/(Math.min(lum(bg),lum(fg))+.05);
      const large=parseFloat(style.fontSize)>=24||(parseFloat(style.fontSize)>=18.66&&parseInt(style.fontWeight)>=700);
      if(ratio<(large?3:4.5)) issues.push({text:el.textContent.trim().slice(0,70),ratio:+ratio.toFixed(2),color:style.color,class:el.className});
    }
    const controls=Array.from(document.querySelectorAll('button,input:not([type=checkbox]),select,textarea,summary')).filter(visible);
    return {contrast:issues, unlabeled:controls.filter(el=>['INPUT','SELECT','TEXTAREA'].includes(el.tagName)&&!el.labels?.length&&!el.getAttribute('aria-label')).map(el=>el.outerHTML), smallTargets:controls.filter(el=>el.getBoundingClientRect().height<44).map(el=>({text:el.textContent.slice(0,40),height:el.getBoundingClientRect().height})), overflow:document.documentElement.scrollWidth>innerWidth};
  });
  if(process.env.ECHOROLE_SCREENSHOTS) { mkdirSync(process.env.ECHOROLE_SCREENSHOTS,{recursive:true}); writeFileSync(join(process.env.ECHOROLE_SCREENSHOTS,`${name}-accessibility.json`),JSON.stringify(result,null,2)); }
  assert.equal(result.unlabeled.length,0,`${name}: unlabelled controls`);
  assert.equal(result.smallTargets.length,0,`${name}: small targets ${JSON.stringify(result.smallTargets)}`);
  assert(!result.overflow,`${name}: overflow`);
  assert.equal(result.contrast.length,0,`${name}: contrast ${JSON.stringify(result.contrast)}`);
  assert(await page.locator('textarea').evaluateAll(xs=>xs.filter(x=>!x.value).every(x=>getComputedStyle(x).borderLeftColor!=='rgb(128, 84, 66)')),`${name}: cleared composer must not look invalid`);
  const skip=page.getByRole('link',{name:/^Skip to/});
  await skip.focus(); await page.keyboard.press('Tab');
  const ring=await page.evaluate(()=>getComputedStyle(document.activeElement).outlineStyle);
  assert.equal(ring,'solid',`${name}: keyboard focus ring`);
  await skip.focus(); await page.keyboard.press('Enter');
  assert(await page.evaluate(()=>['character','scenario-setup','current-scene'].includes(document.activeElement.id)),`${name}: skip destination focus`);
  await page.emulateMedia({reducedMotion:'reduce'});
  assert(await page.locator('[data-echorole]').evaluate(el=>Array.from(el.querySelectorAll('[data-reveal]')).every(x=>getComputedStyle(x).animationName==='none')),`${name}: reduced motion`);
  await page.emulateMedia({reducedMotion:'no-preference'});
  await page.context().setOffline(true);
  await page.getByText('You’re offline.',{exact:false}).waitFor();
  await page.context().setOffline(false);
  await page.getByText('You’re offline.',{exact:false}).waitFor({state:'hidden'});
  console.log(`PASS: ${name} contrast, labels, 44px controls, keyboard focus/skip, reduced motion and offline presentation.`);
};
