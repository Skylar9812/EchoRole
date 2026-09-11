const { chromium } = require(process.env.ECHOROLE_PLAYWRIGHT || 'C:/Users/skyla/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const { spawn, execFileSync } = require('node:child_process');
const { mkdtempSync, rmSync, mkdirSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
const assert = require('node:assert/strict');
const root = resolve(__dirname, '../..');
const temp = mkdtempSync(join(tmpdir(), 'echorole-ui-'));
const origin = 'http://127.0.0.1:3317';
const env = {...process.env, ECHOROLE_DB_PATH: join(temp, 'ui.db'), ECHOROLE_API_URL: 'http://127.0.0.1:8317', ECHOROLE_WEB_ORIGIN: origin, ECHOROLE_COOKIE_SECURE: 'false', ECHOROLE_AI_PROVIDER: 'local', NEXT_TELEMETRY_DISABLED: '1'};
const procs = []; let browser;
async function waitFor(fn, message) { for (let i=0;i<100;i++) { if (await fn()) return; await new Promise(r=>setTimeout(r,250)); } throw Error(message); }
async function text(page, value) { await page.getByText(value, {exact:false}).first().waitFor({timeout:25000}); }
async function idle(page) { await page.waitForTimeout(100); await waitFor(async()=> !(await page.getByRole('status').filter({hasText:'Request in progress'}).count()), 'UI busy'); }
(async()=>{ try {
  for (const [cmd,args,cwd] of [[join(root,'backend/.venv/Scripts/python.exe'),['-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8317'],root], [process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3317'],join(root,'frontend')]]) {
    const proc=spawn(cmd,args,{cwd,env,windowsHide:true,stdio:'pipe'}); procs.push(proc); proc.stderr.on('data',b=> { if(b.toString().includes('Error')) process.stderr.write(b); });
  }
  await waitFor(async()=>{try{return (await fetch(origin)).ok && (await fetch(env.ECHOROLE_API_URL+'/api/v1/health')).ok;}catch{return false;}},'startup');
  browser=await chromium.launch({headless:true, executablePath: process.env.ECHOROLE_CHROMIUM});
  const a=await browser.newContext({viewport:{width:1440,height:1000}}), b=await browser.newContext();
  const alice=await a.newPage(), bob=await b.newPage(); const errors=[];
  for (const p of [alice,bob]) p.on('pageerror', e=>errors.push(e.message));
  async function capture(name, fullPage=true) { if(process.env.ECHOROLE_SCREENSHOTS) { mkdirSync(process.env.ECHOROLE_SCREENSHOTS,{recursive:true}); await alice.evaluate(()=>scrollTo(0,0)); await alice.screenshot({path:join(process.env.ECHOROLE_SCREENSHOTS,name+'.png'),fullPage}); } }
  let originalIdentity;
  await alice.route('**/api/echorole/profiles', async route => {
    const response = await route.fetch(); originalIdentity = (await response.json()).user_id;
    await route.abort('failed');
  });
  await alice.goto(origin);
  await waitFor(async()=>await alice.getByRole('button',{name:'Create profile',exact:true}).isEnabled(),'Landing profile ready');
  for (const width of [375, 768, 1024, 1440]) {
    await alice.setViewportSize({width,height:1000});
    assert(await alice.evaluate(()=>document.documentElement.scrollWidth <= innerWidth), `Landing overflow at ${width}px`);
    if (process.env.ECHOROLE_SCREENSHOTS) {
      mkdirSync(process.env.ECHOROLE_SCREENSHOTS,{recursive:true});
      await alice.screenshot({path:join(process.env.ECHOROLE_SCREENSHOTS,`landing-${width}.png`),fullPage:true});
    }
  }
  await require('./polish_checks.cjs')(alice,'landing');
  await alice.getByLabel('Display name').fill('Alice UI');
  await alice.getByLabel('MBTI (optional)',{exact:true}).fill('INFJ');
  await alice.getByLabel('Communication / value priorities',{exact:true}).fill('Listening and trust');
  await alice.getByRole('button',{name:'Create profile',exact:true}).click(); await idle(alice);
  assert(originalIdentity);
  // route.fetch can process Set-Cookie itself. Remove only that cookie to model
  // loss before the initial identity response arrives, retaining prepared enrollment.
  await a.clearCookies({name:'echorole_identity'});
  assert((await a.cookies()).some(c=>c.name==='echorole_enrollment' && c.httpOnly && c.sameSite==='Strict'));
  await alice.unroute('**/api/echorole/profiles'); await alice.reload();
  await alice.getByLabel('Display name').fill('Edited retry must not overwrite Alice');
  await alice.getByRole('button',{name:'Create profile',exact:true}).click(); await text(alice,'Profile: Alice UI');
  const restored = await (await a.request.get(origin+'/api/echorole/me')).json(); assert.equal(restored.user_id,originalIdentity);
  assert.equal(restored.mbti,'INFJ'); assert.equal(restored.priorities,'Listening and trust');
  await alice.getByLabel('MBTI (optional)',{exact:true}).fill('ENFP');
  await alice.getByLabel('Communication / value priorities',{exact:true}).fill('Empathy and clear boundaries');
  await alice.getByRole('button',{name:'Save profile',exact:true}).click(); await idle(alice);
  await alice.reload(); await text(alice,'Profile: Alice UI');
  assert.equal(await alice.getByLabel('MBTI (optional)',{exact:true}).inputValue(),'ENFP');
  assert.equal(await alice.getByLabel('Communication / value priorities',{exact:true}).inputValue(),'Empathy and clear boundaries');
  assert(!(await alice.evaluate(()=>document.cookie)).includes('echorole_enrollment'));
  await bob.goto(origin); await bob.getByLabel('Display name').fill('Bob UI');
  await bob.getByRole('button',{name:'Create profile',exact:true}).click(); await text(bob,'Create or join a room');
  const count = execFileSync(join(root,'backend/.venv/Scripts/python.exe'),['-c',"import os,sqlite3; c=sqlite3.connect(os.environ['ECHOROLE_DB_PATH']); print(c.execute('SELECT COUNT(*) FROM user_profiles').fetchone()[0])"],{env,windowsHide:true}).toString().trim();
  assert.equal(count,'2');

  await alice.getByRole('button',{name:'Create room',exact:true}).click(); await text(alice,'Waiting for another participant');
  const code=await alice.locator('strong').filter({hasText:/^[A-F0-9]{24}$/}).innerText();
  await bob.getByLabel('Invite code',{exact:true}).fill(code); await bob.getByRole('button',{name:'Join room',exact:true}).click(); await text(bob,'Alice UI'); await text(alice,'Bob UI');

  await require('./lobby_checks.cjs')({alice,bob,origin,idle,text,waitFor,code});

  await require('./polish_checks.cjs')(alice,'lobby');
  const options=await alice.locator('select').nth(1).locator('option').evaluateAll(xs=>xs.map(x=>x.value));
  await alice.locator('select').nth(1).selectOption(options[1]); await alice.getByRole('button',{name:'Start session',exact:true}).click();
  await text(alice,'PRIVATE · ROLE A'); await text(bob,'PRIVATE · ROLE B');
  await require('./polish_checks.cjs')(alice,'active');
  await a.setOffline(true); await text(alice,'You’re offline.'); await a.setOffline(false);
  await waitFor(async()=>await alice.getByText('You’re offline.',{exact:false}).count()===0,'Online status restored');
  for (const width of [1440,1024,768,375]) {
    await alice.setViewportSize({width,height:1000});
    assert(await alice.evaluate(()=>document.documentElement.scrollWidth<=innerWidth), `Session overflow at ${width}px`);
    await capture(`active-session-${width}`);
    await capture(`active-session-${width}-viewport`,false);
  }
  await alice.setViewportSize({width:1440,height:1000});
  await alice.getByLabel('Message your Coach').fill('ALICE_PRIVATE_ONLY'); await alice.getByRole('button',{name:'Send reflection',exact:true}).click(); await idle(alice); await text(alice,'ALICE_PRIVATE_ONLY');
  assert(!(await bob.locator('body').innerText()).includes('ALICE_PRIVATE_ONLY'));
  const privateA = await (await alice.request.get(origin+'/api/echorole/rooms/'+(await alice.evaluate(()=>sessionStorage.getItem('echorole-room')))+'/session')).json();
  const briefA = await (await alice.request.get(origin+'/api/echorole/sessions/'+privateA.id+'/private')).json();
  const briefB = await (await bob.request.get(origin+'/api/echorole/sessions/'+privateA.id+'/private')).json();
  assert.equal(briefA.role_name,'role_a'); assert.equal(briefB.role_name,'role_b');
  assert(!(await alice.locator('body').innerText()).includes(briefB.brief));
  assert(!(await bob.locator('body').innerText()).includes(briefA.brief));
  if(process.env.ECHOROLE_SCREENSHOTS) await alice.getByRole('heading',{name:'AI Coach — private',exact:true}).locator('..').screenshot({path:join(process.env.ECHOROLE_SCREENSHOTS,'active-session-coach.png')});
  // Simulate loss of a successful shared-message response, then reload and retry original ID.
  let lost=false;
  await alice.route('**/api/echorole/rooms/*/messages', async route=>{ if(route.request().method()==='POST' && !lost) {lost=true; await route.fetch(); await route.abort('failed');} else await route.continue(); });
  await alice.getByLabel('Shared message',{exact:true}).fill('RETRY_SHARED_ONCE'); await alice.getByRole('button',{name:'Send message',exact:true}).click(); await idle(alice);
  await alice.reload(); await text(alice,'Unconfirmed requests'); await alice.getByRole('button',{name:'Retry original request',exact:true}).click(); await idle(alice);
  await text(bob,'RETRY_SHARED_ONCE'); assert.equal(await bob.getByText('RETRY_SHARED_ONCE',{exact:true}).count(),1);
  await alice.getByLabel('Your action for turn 1').fill('ALICE_ACTION_PRIVATE I ask my colleague to explain the blockers and propose a realistic deadline together.'); await alice.getByRole('button',{name:'Submit action',exact:true}).click(); await idle(alice); await text(alice,'Action submitted. Waiting');
  assert(!(await bob.locator('body').innerText()).includes('ALICE_ACTION_PRIVATE'));
  await capture('active-session-waiting');
  await bob.getByLabel('Your action for turn 1').fill('I explain my priorities and ask for a practical compromise.'); await bob.getByRole('button',{name:'Submit action',exact:true}).click(); await idle(bob);
  await text(alice,'— Turn 2'); await text(bob,'— Turn 2'); await text(alice,'Progression history — shared');
  await alice.reload(); await text(alice,'PRIVATE · ROLE A'); await text(alice,'— Turn 2');
  await alice.getByText('Turn 1',{exact:true}).filter({has:alice.locator('xpath=self::summary')}).click();
  await capture('active-session-progression');
  // Presentation fixture: the local provider completes too quickly to capture reliably.
  await alice.route('**/api/echorole/sessions/*/turn', async route => { const r=await route.fetch(); const body=await r.json(); await route.fulfill({json:{...body,state:'generating',submitted:true,other_submitted:true}}); });
  await alice.getByRole('button',{name:'Refresh status',exact:true}).click();
  await text(alice,'Generating the next scene. Your action is saved');
  assert.equal(await alice.getByRole('button',{name:'Submit action',exact:true}).count(),0);
  await capture('active-session-generating');
  await alice.unroute('**/api/echorole/sessions/*/turn');
  // UI fixture only: durable recovery semantics are covered by backend tests.
  let recovered = null;
  await alice.route('**/api/echorole/sessions/*/turn', async route => { const r=await route.fetch(); const body=await r.json(); await route.fulfill({json:{...body,state:'uncertain',attempt_id:'ui-attempt'}}); });
  await alice.route('**/api/echorole/sessions/*/turn/recover', async route => { recovered=route.request().postDataJSON(); await route.fulfill({json:{}}); });
  await alice.getByRole('button',{name:'Refresh status',exact:true}).click();
  const recovery = alice.getByRole('button',{name:'Recover generation',exact:true}); await recovery.waitFor(); assert(await recovery.isDisabled());
  assert.equal(await alice.getByRole('button',{name:'Submit action',exact:true}).count(),0);
  await capture('active-session-recovery');
  if(process.env.ECHOROLE_SCREENSHOTS) await recovery.locator('xpath=ancestor::section[1]').screenshot({path:join(process.env.ECHOROLE_SCREENSHOTS,'active-session-recovery-panel.png')});
  await alice.getByRole('checkbox').check(); await recovery.click(); await idle(alice);
  assert.deepEqual(recovered,{turn_index:2,attempt_id:'ui-attempt',acknowledge_uncertain:true});
  await alice.unroute('**/api/echorole/sessions/*/turn'); await alice.unroute('**/api/echorole/sessions/*/turn/recover');
  await alice.getByRole('button',{name:'Refresh status',exact:true}).click();
  await text(alice,'Peer feedback becomes available from turn 3.');
  for (const p of [alice,bob]) {
    await p.getByLabel('Your action for turn 2').fill('I listen carefully to the other perspective and suggest a practical next step together.');
    await p.getByRole('button',{name:'Submit action',exact:true}).click(); await idle(p);
  }
  await text(alice,'— Turn 3'); await text(bob,'— Turn 3');
  let feedbackLost = false;
  await alice.route('**/api/echorole/sessions/*/peer-feedback', async route => {
    if (route.request().method()==='POST' && !feedbackLost) {feedbackLost=true; await route.fetch(); await route.abort('failed');}
    else await route.continue();
  });
  await alice.getByRole('combobox', {name: /^Peer rating/}).selectOption('4.5');
  await alice.getByLabel('Private comment',{exact:true}).fill('FEEDBACK_AUTHOR_ONLY');
  await alice.getByRole('button',{name:'Submit feedback',exact:true}).click(); await idle(alice);
  await alice.reload(); await text(alice,'Unconfirmed requests');
  await alice.getByRole('button',{name:'Retry original request',exact:true}).click(); await idle(alice);
  await text(alice,'Feedback submitted: 4.5 stars — 45 points'); await text(bob,'Peer score: 45 points');
  assert(!(await bob.locator('body').innerText()).includes('FEEDBACK_AUTHOR_ONLY'));
  await bob.getByRole('combobox', {name: /^Peer rating/}).selectOption('5');
  await bob.getByRole('button',{name:'Submit feedback',exact:true}).click(); await idle(bob);
  await text(alice,'Peer score: 50 points');
  await bob.getByRole('button',{name:'Leave room',exact:true}).click(); await text(bob,'Create or join a room'); await text(alice,'Waiting for another participant');
  await require('./stale_identity.cjs')({browser,origin,root,env,text,idle,alice});
  assert.equal(errors.length,0, errors.join('\n'));
  console.log('PASS: landing at 375/768/1024/1440px without overflow, profile fields/edit/reload, Create/Join Room; enrollment response loss restores identical identity with exactly two profiles; turn-3 peer feedback, private comments, score polling and exactly-once feedback retry; two isolated Chromium contexts: profiles, invite join, lobby polling, scenario, role isolation, private Coach, lost-response retry after reload (one shared row), shared chat, private pending action, waiting, joint advancement, history, refresh restoration, leave/member polling; mocked uncertain UI requires acknowledgement and sends fenced attempt; no browser exceptions.');
} finally { if(browser) await browser.close(); for(const p of procs) p.kill(); await new Promise(r=>setTimeout(r,800)); rmSync(temp,{recursive:true,force:true}); } })().catch(e=>{ console.error(e.message?.split('Call log:')[0] || 'UI smoke failed'); process.exitCode=1; });
