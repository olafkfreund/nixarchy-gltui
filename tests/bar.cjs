const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const model = {};
vm.createContext(model);
vm.runInContext(fs.readFileSync('bar-widget/BarModel.js', 'utf8'), model);
const plain = value => JSON.parse(JSON.stringify(value));
const now = new Date(2026, 0, 2, 12, 30).getTime();
const stamp = new Date(2026, 0, 2, 11, 5).getTime();
const clock = value => `${String(new Date(value).getHours()).padStart(2, '0')}:${String(new Date(value).getMinutes()).padStart(2, '0')}`;
const base = {version:1,state:'ok',host:'gitlab.com',running:2,failed:1,countsAt:stamp,cooldownUntil:0,reason:''};
const view = (changes={}, time=now, vertical=false) => plain(model.view(JSON.stringify({...base,...changes}), time, vertical));
const glyph = '\uF296';
const none = {state:'none',label:glyph,tooltip:'Open GitLab Pipelines to load',
  accessible:'Open GitLab Pipelines to load',active:false,dimmed:true,recheckAt:0};
for (const text of ['', '{bad', 'null', '[]', '"text"', JSON.stringify({...base,version:0}), JSON.stringify({...base,state:'unknown'})])
  assert.deepEqual(plain(model.view(text, now, false)), none);
assert.deepEqual(view({state:'none'}), none);
assert.deepEqual(view(), {state:'ok',label:`${glyph} ●2 ✕1`,
  tooltip:`GitLab Pipelines · gitlab.com\n2 running pipelines, 1 failed project\nProject counts from ${clock(stamp)}; watched pipelines are live`,
  accessible:`GitLab Pipelines · gitlab.com, 2 running pipelines, 1 failed project, Project counts from ${clock(stamp)}; watched pipelines are live`,
  active:true,dimmed:false,recheckAt:0});
assert.equal(view({},now,true).label,`${glyph}\n●2\n✕1`);
assert.equal(view({running:0,failed:0}).label,glyph);
assert.equal(view({running:1,failed:2}).tooltip.includes('1 running pipeline, 2 failed projects'),true);
assert.equal(view({running:-3.7,failed:'4.9',host:''}).label,`${glyph} ✕4`);
assert.equal(view({running:-3.7,failed:'4.9',host:''}).tooltip.startsWith('GitLab Pipelines\n'),true);
assert.equal(view({running:Infinity,failed:'bad'}).label,glyph);
assert.equal(view({countsAt:0}).tooltip.includes('Project counts from'),false);
assert.equal(view({countsAt:0}).tooltip.includes(':'),false);
const reason='x'.repeat(125);
assert.equal(view({state:'stopped',reason}).label,`${glyph} !`);
assert.equal(view({state:'stopped',reason}).tooltip,`GitLab Pipelines stopped: ${'x'.repeat(120)}. Open the panel to fix it.`);
assert.equal(view({state:'stopped'}).active,true);
const until=now+60000;
const rate=view({state:'rate',cooldownUntil:until});
assert.equal(rate.label,`${glyph} ●2 ✕1`);
assert.equal(rate.tooltip.startsWith(`GitLab paused until ${clock(until)}\nGitLab Pipelines · gitlab.com`),true);
assert.equal(rate.active,true);
assert.equal(rate.dimmed,true);
assert.equal(rate.recheckAt,until);
assert.equal(view({state:'rate',cooldownUntil:until,countsAt:0}).tooltip,`GitLab paused until ${clock(until)}`);
assert.equal(view({state:'rate',cooldownUntil:until},until).state,'ok');
assert.deepEqual(view({state:'rate',cooldownUntil:until,countsAt:0},until),none);
