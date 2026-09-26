const realAI=process.env.ECHOROLE_REAL_AI_TEST==='1';
const { chromium } = require(process.env.ECHOROLE_PLAYWRIGHT || 'C:/Users/skyla/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright');
const { spawn, execFileSync } = require('node:child_process');
const { mkdtempSync, rmSync, mkdirSync } = require('node:fs');
const { tmpdir } = require('node:os');
const { resolve, join } = require('node:path');
const assert = require('node:assert/strict');
const root = resolve(__dirname, '../..');
const temp = mkdtempSync(join(tmpdir(), 'echorole-ui-'));
const origin = 'http://127.0.0.1:3419';
const env = {...process.env, ECHOROLE_DB_PATH: join(temp, 'ui.db'), ECHOROLE_API_URL: 'http://127.0.0.1:8419', ECHOROLE_WEB_ORIGIN: origin, ECHOROLE_COOKIE_SECURE: 'false', ECHOROLE_AI_PROVIDER: realAI?'llm':'local', ECHOROLE_TEST_REAL_COACH:realAI?'1':'0', NEXT_TELEMETRY_DISABLED: '1'};
const procs = []; let browser;
async function waitFor(fn, message) { for (let i=0;i<100;i++) { if (await fn()) return; await new Promise(r=>setTimeout(r,250)); } throw Error(message); }
async function text(page, value) { await page.getByText(value, {exact:false}).first().waitFor({timeout:25000}); }
async function idle(page) { await page.waitForTimeout(100); await waitFor(async()=> !(await page.getByRole('status').filter({hasText:'Request in progress'}).count()), 'UI busy'); }
(async()=>{ try {
  for (const [cmd,args,cwd] of [[join(root,'backend/.venv/Scripts/python.exe'),['-m','uvicorn','backend.main:app','--host','127.0.0.1','--port','8419'],root], [process.execPath,['node_modules/next/dist/bin/next','start','--hostname','127.0.0.1','--port','3419'],join(root,'frontend')]]) {
    const proc=spawn(cmd,args,{cwd,env,windowsHide:true,stdio:'pipe'}); procs.push(proc); proc.stdout.resume(); proc.stderr.on('data',b=> { if(b.toString().includes('Error')) process.stderr.write(b); });
  }
  await waitFor(async()=>{try{return (await fetch(origin)).ok && (await fetch(env.ECHOROLE_API_URL+'/api/v1/health')).ok;}catch{return false;}},'startup');
  browser=await chromium.launch({headless:true, executablePath: process.env.ECHOROLE_CHROMIUM});
  await require('./localization_checks.cjs')({browser,origin,root,env});
} finally { if(browser)await browser.close();for(const p of procs)p.kill();await new Promise(r=>setTimeout(r,800));rmSync(temp,{recursive:true,force:true}); } })().catch(e=>{ console.error(e.stack||'Real language smoke failed');process.exitCode=1;});
