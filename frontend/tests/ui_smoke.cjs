const { chromium } = require(process.env.ECHOROLE_PLAYWRIGHT || 'C:/Users/skyla/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const { spawn } = require('node:child_process');
const { mkdtempSync, rmSync } = require('node:fs');
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
async function idle(page) { await waitFor(async()=> !(await page.getByRole('status').filter({hasText:'Request in progress'}).count()), 'UI busy'); }
(async()=>{ try {
  for (const [cmd,args,cwd] of [[join(root,'backend/.venv/Scripts/python.exe'),['-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8317'],root], [process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3317'],join(root,'frontend')]]) {
    const proc=spawn(cmd,args,{cwd,env,windowsHide:true,stdio:'pipe'}); procs.push(proc); proc.stderr.on('data',b=> { if(b.toString().includes('Error')) process.stderr.write(b); });
  }
  await waitFor(async()=>{try{return (await fetch(origin)).ok && (await fetch(env.ECHOROLE_API_URL+'/api/v1/health')).ok;}catch{return false;}},'startup');
  browser=await chromium.launch({headless:true, executablePath: process.env.ECHOROLE_CHROMIUM});
  const a=await browser.newContext(), b=await browser.newContext();
  const alice=await a.newPage(), bob=await b.newPage(); const errors=[];
  for (const p of [alice,bob]) p.on('pageerror', e=>errors.push(e.message));
  for (const [p,name] of [[alice,'Alice UI'],[bob,'Bob UI']]) { await p.goto(origin); await p.getByLabel('Display name').fill(name); await p.getByRole('button',{name:'Create profile',exact:true}).click(); await text(p,'Create or join a room'); }
  await alice.getByRole('button',{name:'Create room',exact:true}).click(); await text(alice,'Waiting for another participant');
  const code=await alice.locator('strong').filter({hasText:/^[A-F0-9]{24}$/}).innerText();
  await bob.getByLabel('Invite code',{exact:true}).fill(code); await bob.getByRole('button',{name:'Join room',exact:true}).click(); await text(bob,'Alice UI'); await text(alice,'Bob UI');

  const options=await alice.locator('select').nth(1).locator('option').evaluateAll(xs=>xs.map(x=>x.value));
  await alice.locator('select').nth(1).selectOption(options[1]); await alice.getByRole('button',{name:'Start session',exact:true}).click();
  await text(alice,'Your role: role_a'); await text(bob,'Your role: role_b');
  await alice.getByLabel('Message your Coach').fill('ALICE_PRIVATE_ONLY'); await alice.getByRole('button',{name:'Send / retry Coach message',exact:true}).click(); await idle(alice); await text(alice,'ALICE_PRIVATE_ONLY');
  assert(!(await bob.locator('body').innerText()).includes('ALICE_PRIVATE_ONLY'));
  // Simulate loss of a successful shared-message response, then reload and retry original ID.
  let lost=false;
  await alice.route('**/api/echorole/rooms/*/messages', async route=>{ if(route.request().method()==='POST' && !lost) {lost=true; await route.fetch(); await route.abort('failed');} else await route.continue(); });
  await alice.getByLabel('Shared message',{exact:true}).fill('RETRY_SHARED_ONCE'); await alice.getByRole('button',{name:'Send / retry shared message',exact:true}).click(); await idle(alice);
  await alice.reload(); await text(alice,'Unconfirmed requests'); await alice.getByRole('button',{name:'Retry original request',exact:true}).click(); await idle(alice);
  await text(bob,'RETRY_SHARED_ONCE'); assert.equal(await bob.getByText('RETRY_SHARED_ONCE',{exact:true}).count(),1);
  await alice.getByLabel('Your action for turn 1').fill('ALICE_ACTION_PRIVATE I ask my colleague to explain the blockers and propose a realistic deadline together.'); await alice.getByRole('button',{name:'Submit / retry action',exact:true}).click(); await idle(alice); await text(alice,'Action submitted. Waiting');
  assert(!(await bob.locator('body').innerText()).includes('ALICE_ACTION_PRIVATE'));
  await bob.getByLabel('Your action for turn 1').fill('I explain my priorities and ask for a practical compromise.'); await bob.getByRole('button',{name:'Submit / retry action',exact:true}).click(); await idle(bob);
  await text(alice,'— Turn 2'); await text(bob,'— Turn 2'); await text(alice,'Progression history — shared');
  await alice.reload(); await text(alice,'Your role: role_a'); await text(alice,'— Turn 2');
  // UI fixture only: durable recovery semantics are covered by backend tests.
  let recovered = null;
  await alice.route('**/api/echorole/sessions/*/turn', async route => { const r=await route.fetch(); const body=await r.json(); await route.fulfill({json:{...body,state:'uncertain',attempt_id:'ui-attempt'}}); });
  await alice.route('**/api/echorole/sessions/*/turn/recover', async route => { recovered=route.request().postDataJSON(); await route.fulfill({json:{}}); });
  await alice.getByRole('button',{name:'Refresh status',exact:true}).click();
  const recovery = alice.getByRole('button',{name:'Recover generation',exact:true}); await recovery.waitFor(); assert(await recovery.isDisabled());
  await alice.getByRole('checkbox').check(); await recovery.click(); await idle(alice);
  assert.deepEqual(recovered,{turn_index:2,attempt_id:'ui-attempt',acknowledge_uncertain:true});
  await alice.unroute('**/api/echorole/sessions/*/turn'); await alice.unroute('**/api/echorole/sessions/*/turn/recover');
  await alice.getByRole('button',{name:'Refresh status',exact:true}).click();
  await bob.getByRole('button',{name:'Leave room',exact:true}).click(); await text(bob,'Create or join a room'); await text(alice,'Waiting for another participant');
  assert.equal(errors.length,0, errors.join('\n'));
  console.log('PASS: two isolated Chromium contexts: profiles, invite join, lobby polling, scenario, role isolation, private Coach, lost-response retry after reload (one shared row), shared chat, private pending action, waiting, joint advancement, history, refresh restoration, leave/member polling; mocked uncertain UI requires acknowledgement and sends fenced attempt; no browser exceptions.');
} finally { if(browser) await browser.close(); for(const p of procs) p.kill(); await new Promise(r=>setTimeout(r,800)); rmSync(temp,{recursive:true,force:true}); } })().catch(e=>{ console.error(e); process.exitCode=1; });
