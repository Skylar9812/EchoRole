const assert = require('node:assert/strict');
const {mkdirSync} = require('node:fs');
const {join} = require('node:path');

module.exports = async function verifyLobby({alice, bob, origin, idle, text, waitFor, code}) {
  const capture = async name => {
    if (!process.env.ECHOROLE_SCREENSHOTS) return;
    mkdirSync(process.env.ECHOROLE_SCREENSHOTS, {recursive:true});
    await require('./illustration_checks.cjs')(alice);
    await alice.screenshot({path:join(process.env.ECHOROLE_SCREENSHOTS, name + '.png'),fullPage:true});
  };
  await capture('lobby-empty-desktop');
  const roomPattern = /\/api\/echorole\/rooms\/\d+$/;
  let release;
  const held = new Promise(resolve => { release = resolve; });
  await alice.route(roomPattern, async route => { await held; await route.continue(); });
  await alice.reload(); await text(alice, 'Loading room…');
  await capture('lobby-loading');
  release(); await text(alice, 'Bob UI'); await alice.unroute(roomPattern);

  await alice.getByRole('link', {name:'Edit profile: Alice UI',exact:true}).click();
  await alice.getByLabel('Display name',{exact:true}).fill('Alex Chen');
  await alice.getByLabel('MBTI (optional)',{exact:true}).fill('INFJ');
  await alice.getByLabel('Communication / value priorities',{exact:true}).fill('Listening, clarity, and room for another perspective.');
  await alice.getByRole('button',{name:'Save profile',exact:true}).click(); await idle(alice);
  await text(bob,'Alex Chen');
  const me = await (await alice.request.get(origin+'/api/echorole/me')).json();
  assert.equal(me.display_name,'Alex Chen'); assert.equal(me.mbti,'INFJ');
  await alice.getByText('Your profile',{exact:false}).filter({hasText:'Edit'}).first().click();

  await alice.getByLabel('Shared message',{exact:true}).fill('Shall we take a moment to read the scenario?');
  await alice.getByRole('button',{name:'Send message',exact:true}).click(); await idle(alice);
  await text(bob,'Shall we take a moment to read the scenario?');
  await bob.getByRole('button',{name:'Leave room',exact:true}).click(); await text(bob,'Create or join a room');
  await text(alice,'Waiting for another participant.');
  await bob.getByLabel('Invite code',{exact:true}).fill(code);
  await bob.getByRole('button',{name:'Join room',exact:true}).click(); await text(alice,'Bob UI');

  const catalog = await (await alice.request.get(origin+'/api/echorole/scenarios')).json();
  for (const category of [...new Set(catalog.map(item=>item.category))]) {
    await alice.getByLabel('Category',{exact:true}).selectOption(category);
    assert.equal(await alice.getByLabel('Scenario',{exact:true}).inputValue(),'');
    assert(await alice.getByRole('button',{name:'Start session',exact:true}).isDisabled());
    const choices = catalog.filter(item=>item.category===category);
    for (const scenario of choices.slice(0,2)) {
      await alice.getByLabel('Scenario',{exact:true}).selectOption(scenario.id);
      assert.equal(await alice.locator('#scenario-title').innerText(),scenario.title);
      assert.equal(await alice.locator('#context-title + p').textContent(),scenario.context);
      assert.equal(await alice.locator('#tension-title + p').textContent(),scenario.conflict);
      assert.equal(await alice.locator('#opening-title + p').textContent(),scenario.opening_situation);
    }
  }
  await alice.getByLabel('Category',{exact:true}).selectOption('');
  await alice.getByLabel('Scenario',{exact:true}).selectOption(catalog[0].id);
  for (const width of [375,768,1024,1440]) {
    await alice.setViewportSize({width,height:1000});
    assert(await alice.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),`Lobby overflow at ${width}px`);
    assert(await alice.getByRole('button',{name:'Start session',exact:true}).isVisible());
    await capture(`lobby-scenario-${width}`);
  }
  await alice.route(roomPattern, route=>route.fulfill({status:503,json:{detail:'Room updates temporarily unavailable'}}));
  await alice.getByRole('button',{name:'Refresh status',exact:true}).click();
  await text(alice,'Updates unavailable:');
  assert(await alice.getByRole('button',{name:'Start session',exact:true}).isDisabled());
  assert(await alice.getByRole('button',{name:'Send message',exact:true}).isDisabled());
  await capture('lobby-update-error');
  await alice.unroute(roomPattern);
  await alice.getByRole('button',{name:'Retry room updates',exact:true}).click();
  await waitFor(async()=>await alice.getByRole('button',{name:'Start session',exact:true}).isEnabled(),'Room updates recovered');
  // Do not start here: the existing two-browser test verifies session creation and
  // confirms both participants reach the unchanged Active Session interface.
  console.log('PASS: lobby loading/error recovery, participant join/leave polling, profile edits, shared chat, all category changes and exact preview text, responsive 375/768/1024/1440px.');
};
