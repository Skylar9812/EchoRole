const assert = require('node:assert/strict');
const { execFileSync } = require('node:child_process');
const { join } = require('node:path');

module.exports = async ({ browser, origin, root, env, text, idle, alice }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await page.goto(origin);
    await page.getByLabel('Display name', {exact:true}).fill('Retired identity');
    await page.getByRole('button', {name:'Create profile',exact:true}).click();
    await text(page,'Profile: Retired identity');
    const old = await (await context.request.get(origin+'/api/echorole/me')).json();
    await page.evaluate(id => {
      sessionStorage.setItem('echorole-room','999');
      sessionStorage.setItem(`echorole:${id}:chat:999`, JSON.stringify({content:'obsolete private retry'}));
    }, old.user_id);
    execFileSync(join(root,'backend/.venv/Scripts/python.exe'), ['-c',
      "import os,sqlite3,sys; c=sqlite3.connect(os.environ['ECHOROLE_DB_PATH']); c.execute('DELETE FROM user_profiles WHERE user_id=?',(sys.argv[1],)); c.commit()", old.user_id], {env,windowsHide:true});
    const rejected = await context.request.get(origin+'/api/echorole/me');
    assert.equal(rejected.status(),401);
    assert.equal((await rejected.json()).code,'stale_identity');
    await page.reload();
    await page.getByRole('button',{name:'Start with a new profile',exact:true}).click();
    await idle(page);
    assert(!(await context.cookies()).some(c=>['echorole_identity','echorole_enrollment'].includes(c.name)));
    assert.equal(await page.evaluate(()=>Object.keys(sessionStorage).filter(k=>k.startsWith('echorole')).length),0);
    await page.getByLabel('Display name',{exact:true}).fill('Fresh perspective');
    await page.getByRole('button',{name:'Create profile',exact:true}).click();
    await text(page,'Profile: Fresh perspective');
    const fresh = await (await context.request.get(origin+'/api/echorole/me')).json();
    assert.notEqual(fresh.user_id,old.user_id);
    await page.getByRole('button',{name:'Create room',exact:true}).click();
    await text(page,'Waiting for another participant');
    await page.reload(); await text(page,'Fresh perspective');
    assert.equal((await alice.request.get(origin+'/api/echorole/me')).status(),200);
    console.log('PASS: deleted-profile credential → explicit server cookie reset → cleared tab state → distinct new profile → room/reload; valid identity unaffected.');
  } finally { await context.close(); }
};
