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
assert.equal(view({host:42}).tooltip.startsWith('GitLab Pipelines\n'),true);
assert.equal(view({host:'h'.repeat(105)}).tooltip.startsWith(`GitLab Pipelines · ${'h'.repeat(100)}\n`),true);
assert.equal(view({running:Infinity,failed:'bad'}).label,glyph);
assert.equal(view({countsAt:0}).tooltip.includes('Project counts from'),false);
assert.equal(view({countsAt:0}).tooltip.includes(':'),false);
const reason='x'.repeat(125);
assert.equal(view({state:'stopped',reason}).label,`${glyph} !`);
assert.equal(view({state:'stopped',reason}).tooltip,`GitLab Pipelines stopped: ${'x'.repeat(120)}. Open the panel to fix it.`);
assert.equal(view({state:'stopped',reason:{message:'bad'}}).tooltip,'GitLab Pipelines stopped. Open the panel to fix it.');
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

// A single-host `hosts` entry keeps single-host output unchanged.
assert.deepEqual(view({hosts:[{host:'gitlab.com',state:'ok',running:2,failed:1,countsAt:stamp,cooldownUntil:0,reason:''}]}), view());

const sooner=now+30000, later=now+90000;
const hosts=[
  {host:'one.test',state:'ok',running:2,failed:1,countsAt:stamp,cooldownUntil:0,reason:''},
  {host:'two.test',state:'rate',running:3,failed:0,countsAt:stamp,cooldownUntil:later,reason:''},
  {host:'three.test',state:'stopped',running:0,failed:0,countsAt:0,cooldownUntil:0,reason:'sign in'},
  {host:'four.test',state:'none',running:0,failed:0,countsAt:0,cooldownUntil:0,reason:''}
];
const hostLines=[
  'one.test: ●2 ✕1',
  `two.test: paused until ${clock(later)}`,
  'three.test: stopped — sign in',
  'four.test: no data'
];

const multiOk=view({host:'one.test +3',running:5,failed:1,hosts});
assert.equal(multiOk.state,'ok');
assert.equal(multiOk.recheckAt,later);
assert.equal(multiOk.tooltip,[
  'GitLab Pipelines · one.test +3',
  '5 running pipelines, 1 failed project',
  `Project counts from ${clock(stamp)}; watched pipelines are live`,
  ...hostLines
].join('\n'));
assert.equal(multiOk.accessible,[
  'GitLab Pipelines · one.test +3',
  '5 running pipelines, 1 failed project',
  `Project counts from ${clock(stamp)}; watched pipelines are live`,
  ...hostLines
].join(', '));

const multiNone=view({state:'none',countsAt:0,running:0,failed:0,hosts:[
  {host:'one.test',state:'none',running:0,failed:0,countsAt:0,cooldownUntil:0,reason:''},
  {host:'two.test',state:'none',running:0,failed:0,countsAt:0,cooldownUntil:0,reason:''}
]});
assert.deepEqual(multiNone,{
  state:'none',
  label:glyph,
  tooltip:'Open GitLab Pipelines to load\none.test: no data\ntwo.test: no data',
  accessible:'Open GitLab Pipelines to load, one.test: no data, two.test: no data',
  active:false,
  dimmed:true,
  recheckAt:0
});

const multiRate=view({state:'rate',host:'one.test +1',running:3,failed:0,cooldownUntil:later,hosts:[
  {host:'one.test',state:'rate',running:1,failed:0,countsAt:stamp,cooldownUntil:later,reason:''},
  {host:'two.test',state:'rate',running:2,failed:0,countsAt:stamp,cooldownUntil:sooner,reason:''}
]});
assert.equal(multiRate.state,'rate');
assert.equal(multiRate.dimmed,true);
assert.equal(multiRate.recheckAt,sooner);
assert.equal(multiRate.tooltip,[
  `GitLab paused until ${clock(later)}`,
  'GitLab Pipelines · one.test +1',
  '3 running pipelines, 0 failed projects',
  `Project counts from ${clock(stamp)}; watched pipelines are live`,
  `one.test: paused until ${clock(later)}`,
  `two.test: paused until ${clock(sooner)}`
].join('\n'));

const multiStopped=view({state:'stopped',host:'one.test +1',reason:'one.test: sign in',hosts:[
  {host:'one.test',state:'stopped',running:0,failed:0,countsAt:0,cooldownUntil:0,reason:'sign in'},
  {host:'two.test',state:'none',running:0,failed:0,countsAt:0,cooldownUntil:0,reason:''}
]});
assert.equal(multiStopped.state,'stopped');
assert.equal(multiStopped.active,true);
assert.equal(multiStopped.recheckAt,0);
assert.equal(multiStopped.tooltip,[
  'GitLab Pipelines stopped: one.test: sign in. Open the panel to fix it.',
  'one.test: stopped — sign in',
  'two.test: no data'
].join('\n'));

// Expired per-host pauses re-derive to ok (with countsAt) or none (without countsAt), and clamp/cut values.
const expiredHosts=view({host:'one.test +1',hosts:[
  {host:'a'.repeat(105),state:'rate',running:2.9,failed:-1,countsAt:stamp,cooldownUntil:now,reason:''},
  {host:'two.test',state:'rate',running:4,failed:1,countsAt:0,cooldownUntil:now-1000,reason:''},
  {host:'three.test',state:'stopped',running:0,failed:0,countsAt:0,cooldownUntil:0,reason:'r'.repeat(125)}
]});
assert.equal(expiredHosts.recheckAt,0);
assert.ok(expiredHosts.tooltip.includes(`${'a'.repeat(100)}: ●2 ✕0`));
assert.ok(expiredHosts.tooltip.includes('two.test: no data'));
assert.ok(expiredHosts.tooltip.includes(`three.test: stopped — ${'r'.repeat(120)}`));
