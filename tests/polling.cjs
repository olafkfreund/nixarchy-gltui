const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const {test} = require('node:test');
// Baseline 0.2.2 / 91f6bde: activity waits 2s after each 1s response;
// selected summaries issue six sequential pages, then wait 30s. No inspected job.
function baseline(duration = 1800000) {
  let requests = 2; // catalogue pages
  for (let start = 2000; start < duration; start += 3000) requests++;
  for (let start = 0; start < duration; start += 36000)
    for (let page = 0; page < 6; page++) if (start + page * 1000 < duration) requests++;
  return {requests, coldScanMs: 2000 + 136 * 3000 + 1000};
}
assert.deepEqual(baseline(), {requests:902, coldScanMs:411000});
console.log('Baseline (137 repos, 1s responses, 30min idle):', baseline());
if (!fs.existsSync('Polling.js')) process.exit(0);
const polling = {};
vm.createContext(polling);
vm.runInContext(fs.readFileSync('Polling.js', 'utf8'), polling);
test('recent idle projects back off from 10 to 20, 40, then 60 minutes', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true; s.catalogueAt=12000000;
  const r={repo:'a/b',lastActivity:new Date(0).toISOString()}; s.repos=[r];
  for(const [now,level,wake] of [[0,0,600000],[600000,1,1800000],[1800000,2,4200000],[4200000,3,7800000],[7800000,3,11400000]]) {
    polling.activity(s,r,[],now,0);
    polling.seed(s,now);
    assert.equal(r.idle,level);
    assert.equal(s.wakeAt,wake);
  }
});
test('last activity sets the first idle level and running activity resets it', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  const old={repo:'old/p',lastActivity:new Date(-60*86400000).toISOString()};
  const threeDays={repo:'three/p',lastActivity:new Date(-3*86400000).toISOString()};
  const unknown={repo:'unknown/p'};
  s.repos=[old,threeDays,unknown];
  for(const r of s.repos) polling.activity(s,r,[],0,0);
  assert.deepEqual(s.repos.map(r=>r.idle),[3,1,0]);
  polling.activity(s,old,[{id:7,status:'in_progress'}],1000,1);
  assert.equal(old.idle,0);
});
test('a run lookup that finds a running pipeline resets idle back-off', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  const r={repo:'a/b',idle:3,active:0,activityAt:0}; s.repos=[r];
  polling.ensure(s,'run','a/b','7','active',1000);
  const request=polling.next(s,1000); assert.equal(request.kind,'run');
  polling.complete(s,response(request,{id:7,status:'in_progress'}),1100);
  assert.equal(r.active,1); assert.equal(r.idle,0);
});
test('selection and manual refresh reset idle back-off', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  const a={repo:'a/b',idle:3}, b={repo:'c/d',idle:3}; s.repos=[a,b];
  polling.select(s,'a/b','',{},1000,false);
  polling.select(s,'','',{},1100,false);
  assert.equal(a.idle,0,'selection resets before debounce completes');
  a.idle=3; polling.select(s,'a/b','',{},2000,true);
  a.idle=3; polling.manual(s,2100,false);
  assert.equal(a.idle,0); assert.equal(b.idle,3);
  a.idle=3; polling.manual(s,2200,true);
  assert.equal(a.idle,0); assert.equal(b.idle,0);
});
test('pins use a minute interval and separate queue group', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true; s.catalogueAt=1000000;
  s.repos=['pin/one','pin/two','idle/one','idle/two'].map(repo=>({repo,activityAt:0}));
  polling.pin(s,['pin/one','pin/two']); polling.seed(s,59999);
  assert.equal(Object.keys(s.tasks).length,0);
  polling.seed(s,60000);
  assert.deepEqual(Object.values(s.tasks).map(t=>t.repo).sort(),['pin/one','pin/two']);
  polling.seed(s,600000);
  assert.equal(Object.values(s.tasks).filter(t=>t.group==='pinned').length,2);
  assert.equal(Object.values(s.tasks).filter(t=>t.group==='background').length,1);
  s.repos.push({repo:'run/one',active:1,activityAt:0}); s.slot=3; polling.seed(s,601000);
  const request=polling.next(s,601000); assert.equal(request.repo,'run/one');
});
test('pin seeds incomplete catalogue, replaces map, and clears orphan retry', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false;
  polling.pin(s,['g/old']); assert.equal(s.repos[0].repo,'g/old');
  polling.pin(s,['g/new']); assert.equal(s.pinned['g/old'],undefined);
  polling.seed(s,0); const task=s.tasks['activity:g/old:'];
  if (task) task.failures=1;
  s.repos=s.repos.filter(r=>r.repo!=='g/old'); s.catalogueComplete=true;
  polling.pin(s,['g/later']); assert.equal(s.repos.some(r=>r.repo==='g/later'),false);
  polling.seed(s,0); assert.equal(s.tasks['activity:g/old:'],undefined);
  polling.ensure(s,'activity','g/orphan','','pinned',0);
  s.flight={key:'activity:g/orphan:'}; polling.seed(s,0);
  assert.ok(s.tasks['activity:g/orphan:']);
});
test('selected pins use summary and reopen respects last check', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  s.repos=[{repo:'g/p',activityAt:0,summaryAt:0}]; polling.pin(s,['g/p']);
  polling.select(s,'g/p','',{},60000,true); polling.seed(s,60000);
  assert.ok(s.tasks['summary:g/p:']); assert.equal(s.tasks['activity:g/p:'],undefined);
  polling.select(s,'','',{},60000,true); s.repos[0].activityAt=60000;
  polling.close(s); polling.open(s,90000); s.discover=false; polling.seed(s,90000);
  assert.equal(s.tasks['activity:g/p:'],undefined);
  polling.seed(s,121000); assert.ok(s.tasks['activity:g/p:']);
});
test('busy slots preserve background capacity and delay idle pins', () => {
  const s=polling.create(); polling.open(s,0); s.catalogueComplete=true;
  s.repos=[{repo:'selected/p'}, ...Array.from({length:10},(_,i)=>({repo:`pin/p${i}`})),
    ...Array.from({length:3},(_,i)=>({repo:`running/p${i}`,active:1}))];
  polling.pin(s,s.repos.slice(1,11).map(r=>r.repo));
  polling.select(s,'selected/p','1',{'selected/p:1':true},0,true);
  polling.ensure(s,'jobs','selected/p','1','interactive',0);
  for(const repo of s.repos.slice(1,11)) polling.ensure(s,'activity',repo.repo,'','pinned',0);
  for(const repo of s.repos.slice(11)) polling.ensure(s,'activity',repo.repo,'','active',0);
  polling.ensure(s,'catalogue','','','background',0);
  s.wakeAt=Infinity;
  const served=[];
  for(let now=0;now<100000;now+=1000) {
    const req=polling.next(s,now); assert.ok(req);
    const task=s.tasks[s.flight.key]; served.push(task.group);
    s.flight=null; task.due=now; task.order=++s.order;
  }
  assert.equal(served.filter(group=>group==='background').length,20);
  assert.equal(served.filter(group=>group==='pinned').length,0);
  assert.equal(s.starts.length,60);
  for(const id of Object.keys(s.tasks)) if(s.tasks[id].group==='active') delete s.tasks[id];
  s.slot=3;
  const req=polling.next(s,100000); assert.ok(req.repo.startsWith('pin/'));
});
test('a spare slot serves a due pin before background work', () => {
  const s=polling.create(); polling.open(s,0); s.catalogueComplete=true; s.discover=false;
  s.repos=[{repo:'pin/p'},{repo:'idle/p'}];
  polling.pin(s,['pin/p']);
  polling.ensure(s,'activity','idle/p','','background',0);
  polling.ensure(s,'activity','pin/p','','pinned',0);
  s.wakeAt=Infinity; s.slot=0; // an interactive slot with nothing interactive or active due
  assert.equal(polling.next(s,0).repo,'pin/p');
});
test('completed catalogue removes an orphan retry but keeps its flight until completion', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false;
  polling.pin(s,['old/p']); polling.ensure(s,'activity','old/p','','pinned',0).failures=1;
  s.discover=true; s.slot=4;
  const req=polling.next(s,0); assert.equal(req.kind,'catalogue');
  polling.complete(s,response(req,[{repo:'new/p'}]),1000);
  polling.seed(s,1000);
  assert.equal(s.tasks['activity:old/p:'],undefined);
  polling.ensure(s,'activity','old/p','','pinned',0);
  s.flight={key:'activity:old/p:'}; polling.seed(s,1000);
  assert.ok(s.tasks['activity:old/p:']);
});
function response(request, data=[], nextPage=0) { return {requestId:request.requestId,data,nextPage,error:'',errorType:'',remaining:4000}; }
function simulation(activeCount=0, duration=1800000) {
  const s=polling.create(), repos=Array.from({length:137},(_,i)=>({repo:`org/r${i}`}));
  polling.open(s,0); polling.select(s,'org/r0',activeCount ? '1' : '',activeCount ? {'org/r0:1':true} : {},0,false);
  let flight=null, cold=null, summary=null, catalogue=null;
  const history=[], ages={jobs:0,selected:0,active:0};
  function run(i) { return {id:i+1,status:'in_progress',run_attempt:1,name:'CI'}; }
  for(let now=0; now<duration; now+=250) {
    if(flight && now>=flight.end) {
      const req=flight.req; let data=[],next=0;
      const i=Number(req.repo.split('r').pop());
      if(req.kind==='catalogue') { data=req.page===1?repos.slice(0,100):repos.slice(100); next=req.page===1?2:0; }
      else if(req.kind==='activity' || req.kind==='summary' && ['recent','running'].includes(req.status)) data=i<activeCount?[run(i)]:[];
      else if(req.kind==='jobs') data=[{id:1,status:'in_progress',steps:[]}];
      polling.complete(s,response(req,data,next),now); flight=null;
      if(!catalogue && s.catalogueComplete) catalogue=now;
      if(!cold && s.repos.length===137 && s.repos.every(r=>r.activityAt!==undefined)) cold=now;
      if(!summary && s.repos[0]?.summaryAt!==undefined) summary=now;
    }
    if(now>60000 && activeCount) {
      const r=s.repos.find(r=>r.repo==='org/r0'), d=s.details['org/r0:1'];
      if(d) ages.jobs=Math.max(ages.jobs,now-d.jobsAt);
      if(r?.activityAt!==undefined) ages.selected=Math.max(ages.selected,now-r.activityAt);
      for(const r of s.repos.slice(1,activeCount)) if(r.activityAt!==undefined) ages.active=Math.max(ages.active,now-r.activityAt);
    }
    const req=polling.next(s,now);
    if(req) { assert.equal(flight,null); history.push({at:now,...req,group:s.tasks[s.flight.key].group}); flight={req,end:now+1000}; }
  }
  for(let i=0;i<history.length;i++) {
    if(i) assert.ok(history[i].at-history[i-1].at>=1000);
    if(i>=60) assert.ok(history[i].at-history[i-60].at>=60000);
  }
  return {s,history,cold,summary,catalogue,ages};
}
const idle=simulation();
assert.ok(idle.history.length<baseline().requests, `${idle.history.length} idle requests must beat baseline`);
assert.ok(idle.cold<baseline().coldScanMs);
const busy=simulation(4,180000);
assert.ok(busy.catalogue<=20000,`catalogue ${busy.catalogue}`);
assert.ok(busy.summary<=20000,`summary ${busy.summary}`);
assert.ok(busy.ages.jobs<=10000,`jobs age ${busy.ages.jobs}`);
assert.ok(busy.ages.selected<=15000,`selected age ${busy.ages.selected}`);
assert.ok(busy.ages.active<=25000,`active age ${busy.ages.active}`);
console.log('Candidate:', {idleRequests:idle.history.length,coldScanMs:idle.cold,summaryMs:busy.summary,warmAges:busy.ages});

// Continuous work in all classes, including page continuations, cannot starve either reserved class.
const fair=polling.create(); polling.open(fair,0); fair.discover=false; fair.catalogueComplete=true;
fair.repos=[{repo:'a/b'}];
for(const [group,kind] of [['interactive','jobs'],['active','run'],['background','catalogue']])
  polling.ensure(fair,kind,'a/b','1',group,0);
fair.selected='a/b'; fair.inspected='1'; fair.expanded={'a/b:1':true};
const served=[];
for(let now=0;now<20000;now+=1000) {
  const req=polling.next(fair,now); assert.ok(req);
  const task=fair.tasks[fair.flight.key]; served.push(task.group);
  // Keep all three tasks due without requiring resource fixtures.
  fair.flight=null; task.page++; task.due=now; task.order=++fair.order;
}
for(let i=0;i<served.length;i+=5) assert.deepEqual(served.slice(i,i+5),['interactive','interactive','interactive','active','background']);

const limited=polling.create(); polling.open(limited,0);
let req=polling.next(limited,0);
polling.complete(limited,{...response(req),errorType:'rate',error:'rate',retryAt:90000,remaining:0,resetAt:120000},1000);
assert.equal(limited.cooldown,120000);
polling.manual(limited,2000,true); assert.equal(polling.next(limited,119999),null);
polling.close(limited); polling.open(limited,4000); assert.equal(polling.next(limited,119999),null);
req=polling.next(limited,120000); assert.ok(req);
polling.complete(limited,{...response(req),errorType:'rate',error:'rate'},121000);
assert.equal(limited.cooldown,241000); // second secondary-limit fallback doubles
const old=req; polling.close(limited); polling.open(limited,250000);
req=polling.next(limited,250000); assert.ok(req);
assert.equal(polling.complete(limited,response(old),251000),false);
assert.equal(limited.flight.request.requestId,req.requestId);
polling.complete(limited,{...response(req),remaining:0,resetAt:300000},251000);
assert.equal(limited.catalogueComplete,true); assert.equal(polling.next(limited,299999),null);

// Debounce, same-run navigation, completion reconciliation, final cache and rerun invalidation.
const s=polling.create(); s.repos=[{repo:'a/b',runs:[{id:7,status:'in_progress',run_attempt:1}],activityAt:0,summaryAt:0,active:1}];
s.catalogueComplete=true; polling.open(s,0); s.discover=false;
s.details['a/b:7']={bridges:[],bridgesAt:0,bridgesAttempt:1};
polling.select(s,'a/b','7',{'a/b:7':true},0,false);
assert.equal(polling.next(s,200),null);
req=polling.next(s,250); assert.equal(req.kind,'jobs');
polling.complete(s,response(req,[{id:1,status:'in_progress'}]),500);
polling.select(s,'a/b','7',{'a/b:7':true},4500,false);
req=polling.next(s,5500); assert.equal(req.kind,'jobs');
polling.complete(s,response(req,[{id:1,status:'in_progress'}]),5600);
polling.activity(s,s.repos[0],[],6000);
assert.equal(s.repos[0].active,0); assert.equal(s.repos[0].runs[0].awaitingFinal,true);
req=polling.next(s,6500); assert.equal(req.kind,'run');
polling.complete(s,response(req,{id:7,status:'completed',conclusion:'success',run_attempt:1}),6600);
req=polling.next(s,7500); assert.equal(req.kind,'jobs');
polling.complete(s,response(req,[{id:1,status:'completed'}]),7600);
assert.equal(s.details['a/b:7'].finalAttempt,1);
assert.equal(polling.next(s,13000),null);
assert.equal(polling.next(s,16000)?.kind,'activity');
polling.mergeRuns(s,s.repos[0],[{id:7,status:'in_progress',run_attempt:2}]);
assert.equal(s.details['a/b:7'],undefined);
// A hostile Retry-After cannot stop polling for more than an hour.
const capped=polling.create(); polling.open(capped,0);
let capReq=polling.next(capped,1000);
polling.complete(capped,{...response(capReq),errorType:'rate',error:'rate',retryAt:1000+365*86400000},1000);
assert.equal(capped.cooldown,3601000);
// Replies with the wrong data shape stop polling with a setup error until a manual refresh, never an exception.
for (const [kind,data] of [['catalogue',null],['run',[]],['jobs',{}],['catalogue',[1]],['jobs',[null]]]) {
  const bad=polling.create(); polling.open(bad,0); bad.discover=false; bad.catalogueComplete=true;
  bad.repos=[{repo:'a/b'}];
  polling.ensure(bad,kind,'a/b','1','interactive',0);
  bad.selected='a/b'; bad.inspected='1'; bad.expanded={'a/b:1':true};
  const badReq=polling.next(bad,0); assert.equal(badReq.kind,kind);
  const task=bad.tasks[bad.flight.key];
  assert.equal(polling.complete(bad,response(badReq,data),1000),true);
  assert.equal(bad.error,'GitLab helper returned invalid data');
  assert.equal(bad.auth,true);
  assert.equal(polling.next(bad,task.due+1),null);
  polling.manual(bad,task.due+1,false); assert.equal(bad.auth,false);
}
// Large projects: one page per unfinished status, and the rest is counted, not fetched (#15).
{
  const big=polling.create(); polling.open(big,0); big.discover=false; big.catalogueComplete=true;
  const run=(id)=>({id,status:'in_progress',run_attempt:1,name:'CI'});
  big.repos=[{repo:'a/b',runs:[run(1),run(2),run(3)]}];
  big.expanded={'a/b:2':true};
  polling.ensure(big,'activity','a/b','','active',0);
  const req=polling.next(big,0); assert.equal(req.kind,'activity');
  const page=Array.from({length:100},(_,i)=>run(1000+i));
  assert.equal(polling.complete(big,{...response(req,page),total:250},1000),true);
  const r=big.repos[0];
  assert.equal(r.active,250);
  assert.equal(r.hidden.running,150);
  const ids=r.runs.map(x=>x.id);
  assert.ok(!ids.includes(1) && !ids.includes(3),'unviewed runs missing from a partial page are dropped');
  assert.ok(ids.includes(2),'an expanded run is kept');
  // GitLab omits X-Total above 10,000: the helper reports -1, "more, count unknown".
  const huge=polling.create(); polling.open(huge,0); huge.discover=false; huge.catalogueComplete=true;
  huge.repos=[{repo:'a/b',runs:[]}];
  polling.ensure(huge,'activity','a/b','','active',0);
  const hugeReq=polling.next(huge,0);
  polling.complete(huge,{...response(hugeReq,page),total:-1},1000);
  assert.equal(huge.repos[0].hidden.running,-1);
  assert.equal(huge.repos[0].active,100);
}
console.log('Polling: fairness, budgets, cooldown, debounce, lifecycle, completion and rerun checks passed');
const partial=polling.create(); polling.open(partial,0); partial.discover=false; partial.catalogueComplete=true;
partial.repos=[{repo:'a/b',summaryAt:0,runs:[{id:7,status:'in_progress'}]}, {repo:'other/repo',summaryAt:0}];
polling.select(partial,'a/b','',{},0,true);
req=polling.next(partial,0); assert.equal(req.kind,'activity');
polling.complete(partial,response(req,[],2),100);
assert.equal(partial.repos[0].checked,undefined);
assert.equal(partial.repos[0].runs[0].status,'in_progress');
req=polling.next(partial,1000);
polling.complete(partial,{...response(req),error:'offline',errorType:'network'},1100);
assert.equal(partial.repos[0].checked,undefined);
assert.equal(partial.repos[0].runs[0].awaitingFinal,undefined);
req=polling.next(partial,2000); assert.equal(req.repo,'other/repo','one failed repository does not freeze background work');
polling.complete(partial,response(req),2100);
assert.equal(polling.next(partial,6000),null);
req=polling.next(partial,6100); assert.equal(req.page,1,'retry starts a fresh complete snapshot');
polling.complete(partial,{...response(req),error:'permission',errorType:'permission'},6200);
assert.equal(partial.repos[0].blocked,true);
assert.equal(polling.next(partial,15000),null);
polling.manual(partial,15000,false); assert.equal(partial.repos[0].blocked,false);
req=polling.next(partial,15000); assert.equal(req.kind,'summary');
polling.complete(partial,{...response(req),error:'login',errorType:'auth'},15100);
assert.equal(polling.next(partial,40000),null);
polling.close(partial); polling.open(partial,41000);
assert.equal(partial.auth,false);

const churn=polling.create(); polling.open(churn,0); churn.discover=false; churn.catalogueComplete=true;
churn.repos=Array.from({length:20},(_,i)=>({repo:`x/r${i}`,activityAt:0}));
for(let now=0;now<1000;now+=50) {
  polling.select(churn,`x/r${now/50}`,'',{},now,false);
  assert.equal(polling.next(churn,now),null,'rapid navigation should not fetch intermediate repositories');
}
req=polling.next(churn,1250); assert.equal(req.repo,'x/r19');
assert.equal(req.kind,'summary');
const taskCount=Object.keys(churn.tasks).length;
for(let n=0;n<50;n++) polling.manual(churn,1300,false);
assert.equal(Object.keys(churn.tasks).length,taskCount,'manual refresh coalesces work');
polling.select(churn,'x/r0','',{},1400,false);
polling.complete(churn,response(req,[{id:1,status:'completed'}]),1500);
req=polling.next(churn,2250); assert.equal(req.repo,'x/r0','obsolete summary continuation loses priority');
assert.equal(Object.values(churn.tasks).some(t=>t.repo==='x/r19'),false);
console.log('Polling: partial snapshots, permission isolation, auth retry and rapid navigation passed');

const overload=simulation(30,300000);
assert.ok(overload.ages.active>25000,'overload stretches freshness rather than bypassing the budget');
assert.ok(overload.history.filter(x=>x.group==='background').length>=Math.floor(overload.history.length/5));
const ordered=polling.create(); polling.open(ordered,0); ordered.discover=false; ordered.catalogueComplete=true;
ordered.repos=[{repo:'newer/check',activityAt:1000},{repo:'oldest/check',activityAt:0}];
req=polling.next(ordered,700000); assert.equal(req.repo,'oldest/check','idle background checks oldest data first');
console.log('Polling: overload preserves budget/fairness; idle data ordered by freshness');

const overlap=polling.create(); polling.open(overlap,0); overlap.discover=false; overlap.catalogueComplete=true;
overlap.repos=[{repo:'a/b',summaryAt:0}]; polling.select(overlap,'a/b','',{},0,true);
req=polling.next(overlap,0); polling.complete(overlap,response(req,[{id:7,status:'in_progress'}],2),100);
assert.equal(overlap.repos[0].checked,undefined);
req=polling.next(overlap,1000); polling.complete(overlap,response(req,[{id:7,status:'in_progress'}]),1100);
assert.equal(overlap.repos[0].active,1,'overlapping pages cannot double-count active workflows');
console.log('Polling: overlapping pages deduplicate workflow IDs');

const sorted=polling.create(); polling.open(sorted,0); sorted.discover=true;
req=polling.next(sorted,0); assert.equal(req.kind,'catalogue');
polling.complete(sorted,response(req,[{repo:'g/old',lastActivity:'2026-01-01T00:00:00Z'},{repo:'g/none'},{repo:'g/new',lastActivity:'2026-09-01T00:00:00Z'}]),100);
assert.equal(sorted.repos.map(r=>r.repo).join(),'g/new,g/old,g/none','catalogue ordered by last activity');

const rerun=polling.create(); rerun.repos=[{repo:'a/b',runs:[{id:7,status:'in_progress',run_attempt:'active'}]}];
rerun.details['a/b:7']={jobs:[]};
polling.mergeRuns(rerun,rerun.repos[0],[{id:7,status:'completed',run_attempt:'t1'}]);
assert.ok(rerun.details['a/b:7'],'finishing does not discard jobs');
polling.mergeRuns(rerun,rerun.repos[0],[{id:7,status:'completed',run_attempt:'t2'}]);
assert.equal(rerun.details['a/b:7'],undefined,'finished pipeline with new updated_at is a rerun');
console.log('Polling: GitLab catalogue order and rerun detection passed');

test('attempt change between jobs pages restarts the snapshot', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:[{id:7,status:'completed',run_attempt:'t1'}],activityAt:0,summaryAt:0}];
  polling.select(x,'a/b','7',{'a/b:7':true},0,true);
  let request=polling.next(x,0); assert.equal(request.kind,'jobs');
  polling.complete(x,response(request,[{id:1,status:'completed'}],2),100);
  polling.mergeRuns(x,x.repos[0],[{id:7,status:'completed',run_attempt:'t2'}]);
  assert.equal(x.details['a/b:7'],undefined);
  request=polling.next(x,1000);
  if(request.kind==='bridges') { polling.complete(x,response(request,[]),1100); request=polling.next(x,2000); }
  assert.equal(request.kind,'jobs'); assert.equal(request.page,1);
  polling.complete(x,response(request,[{id:2,status:'completed'}]),1100);
  assert.deepEqual(Array.from(x.details['a/b:7'].jobs, job=>job.id),[2]);
  assert.equal(x.details['a/b:7'].finalAttempt,'t2');
});

test('active to finished to active discards an in-flight jobs page', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:[{id:7,status:'in_progress',run_attempt:'active'}],activityAt:0,summaryAt:0}];
  polling.select(x,'a/b','7',{'a/b:7':true},0,true);
  let request=polling.next(x,0); assert.equal(request.kind,'jobs');
  polling.complete(x,response(request,[{id:1,status:'in_progress'}],2),100);
  request=polling.next(x,1000);
  if(request.kind==='bridges') { polling.complete(x,response(request,[]),1100); request=polling.next(x,2000); }
  assert.equal(request.kind,'jobs'); assert.equal(request.page,2);
  polling.mergeRuns(x,x.repos[0],[{id:7,status:'completed',run_attempt:'t1'}]);
  polling.mergeRuns(x,x.repos[0],[{id:7,status:'in_progress',run_attempt:'active'}]);
  polling.complete(x,response(request,[{id:2,status:'in_progress'}]),1100);
  assert.equal(x.details['a/b:7'],undefined);
  request=polling.next(x,3000); assert.equal(request.kind,'jobs'); assert.equal(request.page,1);
});

test('manual refresh clears a selected summary retry delay', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',activityAt:0}]; polling.select(x,'a/b','',{},0,true);
  let now=0, task;
  for(let i=0;i<7;i++) {
    const request=polling.next(x,now); assert.equal(request.kind,'summary');
    now+=1000;
    polling.complete(x,{...response(request),error:'offline',errorType:'network'},now);
    task=x.tasks['summary:a/b:'];
    if(i<6) now=task.due;
  }
  assert.ok(task.due-now>=300000);
  polling.manual(x,now,false);
  assert.equal(task.due,now);
  assert.equal(task.failures,0);
});

test('manual refresh discards an in-flight summary and restarts at recent page one', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',activityAt:0,runs:[]}]; polling.select(x,'a/b','',{},0,true);
  let request=polling.next(x,0); assert.equal(request.status,'recent');
  polling.complete(x,response(request,[]),100);
  request=polling.next(x,1000); assert.equal(request.status,'running');
  polling.complete(x,response(request,[]),1100);
  request=polling.next(x,2000); assert.equal(request.status,'pending');
  polling.manual(x,2100,false);
  assert.equal(polling.complete(x,response(request,[{id:99,status:'in_progress'}]),2200),true);
  assert.equal(x.repos[0].runs.length,0);
  request=polling.next(x,3000);
  assert.equal(request.kind,'summary');
  assert.equal(request.status,'recent');
  assert.equal(request.page,1);
});

test('rate limit on a restarted task still sets cooldown', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',activityAt:0}]; polling.select(x,'a/b','',{},0,true);
  const request=polling.next(x,0); assert.equal(request.kind,'summary');
  polling.manual(x,100,false);
  polling.complete(x,{...response(request),error:'rate',errorType:'rate',remaining:0,resetAt:120000},200);
  assert.equal(x.cooldown,120000);
  assert.equal(x.tasks['summary:a/b:'].due,200);
});

test('catalogue permission error stops discovery until manual catalogue refresh', () => {
  const x=polling.create(); polling.open(x,0);
  let request=polling.next(x,0); assert.equal(request.kind,'catalogue');
  polling.complete(x,{...response(request),error:'forbidden',errorType:'permission'},100);
  assert.equal(x.catalogueError,'forbidden');
  x.repos=[{repo:'a/b'}]; // never checked, so its activity request is due at once
  let served=0;
  for(let now=200;now<=10000;now+=1000) { request=polling.next(x,now); if(request) { served++; assert.notEqual(request.kind,'catalogue'); polling.complete(x,response(request,[]),now+10); } }
  assert.ok(served>0,'known projects keep polling');
  assert.equal(x.error,'','a successful request clears the transient error');
  assert.equal(x.catalogueError,'forbidden','the catalogue refusal survives successful requests');
  polling.close(x); polling.open(x,20000);
  for(let now=20000;now<=30000;now+=1000) { request=polling.next(x,now); if(request) { assert.notEqual(request.kind,'catalogue'); polling.complete(x,response(request,[]),now+10); } }
  polling.manual(x,31000,true);
  assert.equal(x.catalogueError,'');
  request=polling.next(x,31000); assert.equal(request.kind,'catalogue');
});

test('the completed catalogue wakes and refreshes every five minutes', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true; s.catalogueAt=1000;
  assert.equal(polling.next(s,1000),null);
  assert.equal(s.wakeAt,301000);
  assert.equal(polling.next(s,300999),null);
  const request=polling.next(s,301000); assert.equal(request.kind,'catalogue');
  assert.equal(s.periodic,true);
  polling.complete(s,response(request,[]),301100);
  assert.equal(s.periodic,false); assert.equal(s.catalogueAt,301100);
});

test('catalogue permission errors prevent periodic scans and reopen scans', () => {
  const s=polling.create(); polling.open(s,0); s.catalogueComplete=true;
  const request=polling.next(s,0); assert.equal(request.kind,'catalogue');
  polling.complete(s,{...response(request),error:'forbidden',errorType:'permission'},100);
  assert.equal(polling.next(s,300000),null);
  assert.equal(s.discover,false); assert.equal(s.periodic,false);
  polling.close(s); polling.open(s,400000);
  assert.equal(polling.next(s,400000),null); assert.equal(s.discover,false);
});

test('a periodic merge keeps blocked projects; full refreshes clear them', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  const r={repo:'a/b',blocked:true,error:'forbidden',activityAt:0,lastActivity:'old'}; s.repos=[r];
  let request=polling.next(s,300000); assert.equal(request.kind,'catalogue'); assert.equal(s.periodic,true);
  polling.complete(s,response(request,[{repo:'a/b',lastActivity:'old'}]),300100);
  assert.equal(r.blocked,true); assert.equal(r.error,'forbidden');
  polling.manual(s,300200,true);
  request=polling.next(s,301000); assert.equal(request.kind,'catalogue'); assert.equal(s.periodic,false);
  polling.complete(s,response(request,[{repo:'a/b',lastActivity:'old'}]),301100);
  assert.equal(r.blocked,false); assert.equal(r.error,'');
  r.blocked=true; r.error='forbidden';
  polling.close(s); polling.open(s,302000);
  request=polling.next(s,302000); assert.equal(request.kind,'catalogue'); assert.equal(s.periodic,false);
  polling.complete(s,response(request,[{repo:'a/b',lastActivity:'old'}]),302100);
  assert.equal(r.blocked,false); assert.equal(r.error,'');
});

test('closing during a periodic scan makes the reopen scan a full one', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  const r={repo:'a/b',blocked:true,error:'forbidden',activityAt:0}; s.repos=[r];
  let request=polling.next(s,300000); assert.equal(request.kind,'catalogue'); assert.equal(s.periodic,true);
  polling.close(s); polling.open(s,301000); assert.equal(s.periodic,false);
  request=polling.next(s,301000); assert.equal(request.kind,'catalogue');
  polling.complete(s,response(request,[{repo:'a/b'}]),301100);
  assert.equal(r.blocked,false);
});
test('a changed activity time on a never-checked project is not a hint', () => {
  const s=polling.create(); polling.open(s,0); s.catalogueComplete=true;
  const r={repo:'new/p',lastActivity:'old'}; s.repos=[r];
  const request=polling.next(s,0); assert.equal(request.kind,'catalogue');
  polling.complete(s,response(request,[{repo:'new/p',lastActivity:'new'}]),1000);
  assert.equal(r.hinted,undefined);
});
test('overdue reopen and R use full scans, including R during page two', () => {
  for(const mode of ['reopen','R']) {
    const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
    const r={repo:'a/b',blocked:true,error:'forbidden',activityAt:0}; s.repos=[r];
    if(mode==='reopen') { polling.close(s); polling.open(s,400000); }
    else polling.manual(s,400000,true);
    let request=polling.next(s,400000); assert.equal(request.kind,'catalogue'); assert.equal(s.periodic,false);
    polling.complete(s,response(request,[{repo:'a/b'}],2),400100);
    request=polling.next(s,401000); assert.equal(request.page,2);
    polling.manual(s,401100,true);
    assert.equal(polling.complete(s,response(request,[]),401200),true);
    request=polling.next(s,402000); assert.equal(request.page,1); assert.equal(s.periodic,false);
    polling.complete(s,response(request,[{repo:'a/b'}]),402100);
    assert.equal(r.blocked,false); assert.equal(r.error,'');
  }
});

test('R upgrades a periodic scan after page one and clears blocked projects', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  const blocked={repo:'a/b',blocked:true,error:'forbidden',activityAt:0,idle:3};
  s.repos=[blocked,{repo:'c/d',activityAt:0,idle:3}];
  let request=polling.next(s,300000); assert.equal(request.kind,'catalogue'); assert.equal(s.periodic,true);
  polling.complete(s,response(request,[{repo:'c/d'}],2),300100);
  assert.equal(s.tasks['catalogue::'].page,2);
  polling.manual(s,300200,true);
  request=polling.next(s,301000); assert.equal(request.page,1);
  polling.complete(s,response(request,[{repo:'c/d'}],2),301100);
  request=polling.next(s,302000); assert.equal(request.page,2);
  polling.complete(s,response(request,[{repo:'a/b'}]),302100);
  assert.equal(blocked.blocked,false); assert.equal(blocked.error,'');
});

test('changed catalogue activity hints a background check and preserves a retry deadline', () => {
  const s=polling.create(); polling.open(s,0); s.catalogueComplete=true;
  const r={repo:'hint/p',lastActivity:'old',activityAt:0,idle:3};
  const other={repo:'other/p',activityAt:0,idle:3}; s.repos=[r,other];
  const request=polling.next(s,0); assert.equal(request.kind,'catalogue');
  polling.complete(s,response(request,[{repo:'hint/p',lastActivity:'new'},{repo:'other/p'}]),1000);
  assert.equal(r.hinted,true); assert.equal(r.idle,0);
  const retry=polling.ensure(s,'activity','other/p','','background',20000); retry.failures=1;
  polling.seed(s,2000);
  assert.equal(s.tasks['activity:hint/p:'].due,2000);
  assert.equal(retry.due,20000);
  const hint=polling.next(s,2000); assert.equal(hint.repo,'hint/p');
  polling.complete(s,response(hint,[]),2100);
  assert.equal(r.hinted,undefined);
});

test('hint ordering admits the hinted repo before an ordinary background repo', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  s.repos=[{repo:'ordinary/p'},{repo:'hint/p',activityAt:0,hinted:true,idle:3}];
  polling.seed(s,1000);
  assert.ok(s.tasks['activity:hint/p:']);
  assert.equal(s.tasks['activity:ordinary/p:'],undefined);
});

test('a hint keeps its own activity error retry deadline', () => {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  s.repos=[{repo:'hint/p',activityAt:0,hinted:true,idle:3}];
  const retry=polling.ensure(s,'activity','hint/p','','background',20000); retry.failures=1;
  assert.equal(polling.next(s,1000),null);
  assert.equal(retry.due,20000); assert.equal(s.wakeAt,20000);
});

test('catalogue page retries do not repeatedly seed while waiting', () => {
  const s=polling.create(); polling.open(s,0);
  const request=polling.next(s,0); assert.equal(request.kind,'catalogue');
  polling.complete(s,{...response(request),error:'offline',errorType:'network'},1000);
  const before=s.seeds;
  for(let now=1250;now<6000;now+=250) assert.equal(polling.next(s,now),null);
  assert.ok(s.seeds-before<10,`seeded ${s.seeds-before} times during retry`);
  assert.equal(s.wakeAt,6000);
});

test('background queued run is looked up after 15 seconds', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',active:0,activityAt:0,runs:[{id:7,status:'queued'}]}];
  assert.equal(polling.next(x,0),null);
  assert.equal(polling.next(x,14000),null);
  const request=polling.next(x,15000);
  assert.equal(request.kind,'run'); assert.equal(request.run,'7');
  assert.equal(x.tasks[x.flight.key].group,'background');
});

function queuedFixture() {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true; s.catalogueAt=1000000000;
  s.repos=[{repo:'a/b',activityAt:0,idle:3,runs:[{id:7,status:'queued',followupAt:0}]}];
  return s;
}
test('queued lookups back off through 15, 30, 60, 120, 240 and 300 seconds', () => {
  const s=queuedFixture(); let at=0;
  for(const [level,delay] of [[0,15000],[1,30000],[2,60000],[3,120000],[4,240000],[5,300000],[5,300000]]) {
    assert.equal(polling.next(s,at+delay-1),null);
    assert.equal(s.wakeAt,at+delay);
    const request=polling.next(s,at+delay); assert.equal(request.kind,'run');
    at+=delay+1000;
    polling.complete(s,response(request,{id:7,status:'queued'}),at);
    assert.equal(s.queued['a/b:7'],Math.min(5,level+1));
  }
});
test('a backed-off queued task is created only at its full delay with that due time', () => {
  const s=queuedFixture(); s.queued['a/b:7']=3; s.repos[0].runs[0].followupAt=5000;
  polling.seed(s,20000);
  assert.equal(s.tasks['run:a/b:7'],undefined);
  polling.seed(s,125000);
  assert.equal(s.tasks['run:a/b:7'].due,125000);
});
test('watched, selected and awaiting-final queued runs keep the 15-second delay', () => {
  for(const mode of ['watched','selected','awaitingFinal']) {
    const s=queuedFixture(), run=s.repos[0].runs[0];
    if(mode==='watched') assert.equal(polling.watch(s,'a/b',7,0),'watching');
    if(mode==='selected') { s.repos[0].summaryAt=0; s.repos[0].activityAt=15000; polling.select(s,'a/b','',{},0,true); }
    if(mode==='awaitingFinal') run.awaitingFinal=true;
    s.queued['a/b:7']=5;
    assert.equal(polling.next(s,0),null);
    assert.equal(s.wakeAt,15000,mode);
    const request=polling.next(s,15000); assert.equal(request.kind,'run',mode);
  }
});
test('selected and watched lookups that stay queued do not raise the level', () => {
  for(const mode of ['selected','watched']) {
    const s=queuedFixture();
    if(mode==='watched') assert.equal(polling.watch(s,'a/b',7,0),'watching');
    else { s.repos[0].summaryAt=0; s.repos[0].activityAt=15000; polling.select(s,'a/b','',{},0,true); }
    const request=polling.next(s,15000); assert.equal(request.kind,'run',mode);
    polling.complete(s,response(request,{id:7,status:'queued'}),16000);
    assert.equal(s.queued['a/b:7'],undefined,mode);
  }
});
test('a running lookup and selection clear queued levels', () => {
  const s=queuedFixture(); s.queued['a/b:7']=1;
  const request=polling.next(s,30000); assert.equal(request.kind,'run');
  polling.complete(s,response(request,{id:7,status:'in_progress'}),31000);
  assert.equal(s.queued['a/b:7'],undefined);
  const selected=queuedFixture(); selected.queued['a/b:7']=5;
  polling.select(selected,'a/b','',{},0,true);
  assert.equal(selected.queued['a/b:7'],undefined);
  polling.select(selected,'','',{},100,true);
  assert.equal(polling.next(selected,15000).kind,'run');
});
test('summary completion clears a queued level while the run stays cached', () => {
  const s=queuedFixture();
  let request=polling.next(s,15000); assert.equal(request.kind,'run');
  polling.select(s,'a/b','',{},15100,true);
  polling.complete(s,response(request,{id:7,status:'queued'}),15200);
  assert.equal(s.queued['a/b:7'],undefined,'a lookup finishing after selection does not raise');
  s.queued['a/b:7']=1; // a level left from before selection
  request=polling.next(s,16000); assert.equal(request.kind,'summary');
  polling.complete(s,response(request,[{id:7,status:'completed'}]),16100);
  assert.equal(s.repos[0].runs[0].status,'completed');
  assert.equal(s.queued['a/b:7'],undefined);
});
test('trim, dropped activity and catalogue removal clear queued levels', () => {
  const trim=queuedFixture(), r=trim.repos[0];
  r.runs=completedRuns(1,10); trim.queued['a/b:1']=3;
  polling.mergeRuns(trim,r,[{id:11,status:'completed'}]);
  assert.equal(trim.queued['a/b:1'],undefined);
  const dropped=queuedFixture(), d=dropped.repos[0];
  d.runs=[{id:7,status:'in_progress'}]; dropped.queued['a/b:7']=3;
  polling.activity(dropped,d,[{id:8,status:'in_progress'}],1000,250);
  assert.equal(dropped.queued['a/b:7'],undefined);
  const removed=queuedFixture(); removed.queued['a/b:7']=5;
  polling.manual(removed,0,true);
  let request=polling.next(removed,0); assert.equal(request.kind,'catalogue');
  polling.complete(removed,response(request,[]),1000);
  assert.equal(removed.queued['a/b:7'],undefined);
  polling.manual(removed,2000,true);
  request=polling.next(removed,2000); assert.equal(request.kind,'catalogue');
  polling.complete(removed,response(request,[{repo:'a/b'}]),3000);
  removed.repos[0].activityAt=3000; removed.repos[0].idle=3;
  removed.repos[0].runs=[{id:7,status:'queued',followupAt:3000}];
  assert.equal(polling.next(removed,18000).kind,'run');
});
test('a five-minute queued wait does not repeatedly seed', () => {
  const s=queuedFixture(); s.queued['a/b:7']=5;
  assert.equal(polling.next(s,0),null); assert.equal(s.wakeAt,300000);
  const before=s.seeds;
  for(let now=250;now<300000;now+=250) assert.equal(polling.next(s,now),null);
  assert.ok(s.seeds-before<10); assert.equal(polling.next(s,300000).kind,'run');
});
test('a watch respects a lookup error retry and advances an ordinary queued wait', () => {
  const retry=queuedFixture();
  let request=polling.next(retry,15000); assert.equal(request.kind,'run');
  polling.complete(retry,{...response(request,{}),error:'offline',errorType:'network'},16000);
  assert.equal(retry.queued['a/b:7'],undefined);
  assert.equal(polling.watch(retry,'a/b',7,17000),'watching');
  assert.equal(polling.next(retry,20000),null);
  request=polling.next(retry,21000); assert.equal(request.kind,'run');
  const ordinary=queuedFixture(); ordinary.queued['a/b:7']=5; ordinary.repos[0].runs[0].followupAt=16000;
  assert.equal(polling.next(ordinary,0),null);
  assert.equal(polling.watch(ordinary,'a/b',7,17000),'watching');
  assert.equal(polling.next(ordinary,17000),null);
  assert.equal(ordinary.wakeAt,30000);
  request=polling.next(ordinary,30000); assert.equal(request.kind,'run');
});
test('resetHost drops queued lookup levels', () => {
  const s=queuedFixture(); s.queued['a/b:7']=5;
  assert.equal(Object.keys(polling.resetHost(s).queued).length,0);
});

for(const [status,errorType] of [['in_progress',''],['completed',''],['queued','permission']])
  test(`queued run follow-up stops after ${errorType || status}`, () => {
    const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
    x.repos=[{repo:'a/b',active:0,activityAt:0,runs:[{id:7,status:'queued'}]}];
    assert.equal(polling.next(x,0),null);
    const request=polling.next(x,15000); assert.equal(request.kind,'run');
    polling.complete(x,errorType ? {...response(request,{}),error:'forbidden',errorType} : response(request,{id:7,status}),16000);
    const later=polling.next(x,31000);
    assert.notEqual(later && later.kind,'run');
    assert.equal(x.repos[0].runs[0].lookupError,errorType ? 'forbidden' : undefined);
  });

test('queued background lookups coexist with running projects and inspected jobs under the request cap', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  const queued=Array.from({length:3},(_,i)=>({repo:`queued/r${i}`,active:0,activityAt:0,
    runs:Array.from({length:10},(_,j)=>({id:i*10+j+1,status:'queued'}))}));
  const running=Array.from({length:5},(_,i)=>({repo:`running/r${i}`,active:1,activityAt:i*1000,
    runs:[{id:100+i,status:'in_progress'}]}));
  running[0].summaryAt=0;
  running[0].runs.push({id:200,status:'completed',run_attempt:1});
  x.repos=running.concat(queued);
  polling.select(x,'running/r0','200',{'running/r0:200':true},0,true);
  const history=[], checked={};
  for(let now=0;now<600000;now+=250) {
    const request=polling.next(x,now);
    if(request) {
      history.push({at:now,kind:request.kind,repo:request.repo,run:request.run});
      if(request.kind==='run') checked[request.repo+':'+request.run]=true;
      let data=[];
      if(request.kind==='activity' || request.kind==='summary' && request.status==='running')
        data=[{id:100+Number(request.repo.slice(-1)),status:'in_progress'}];
      else if(request.kind==='run') data={id:Number(request.run),status:'queued'};
      else if(request.kind==='jobs') data=[{id:1,status:'completed'}];
      polling.complete(x,response(request,data),now);
      if(request.kind==='jobs') polling.select(x,'','',{},now,true);
    }
  }
  for(let i=60;i<history.length;i++) assert.ok(history[i].at-history[i-60].at>=60000);
  for(const repo of running) {
    const times=history.filter(h=>h.repo===repo.repo && (h.kind==='activity' || h.kind==='summary' && h.at>=15000)).map(h=>h.at);
    assert.ok(times.length>0,repo.repo+' was never checked');
    for(let i=1;i<times.length;i++) assert.ok(times[i]-times[i-1]<=16000,repo.repo+' went unchecked for '+(times[i]-times[i-1])+' ms');
  }
  assert.equal(Object.keys(checked).length,30,'every queued run is looked up');
  assert.ok(history.some(h=>h.kind==='jobs'),'inspected jobs are fetched');
});

// Step 8: a total from the activity reply is not overwritten by a run lookup.
test('run lookup keeps the active count taken from the activity total', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:[{id:7,status:'in_progress'}],activityAt:0}];
  polling.select(x,'',  '', {'a/b:7':true},0,true);
  polling.activity(x,x.repos[0],[],1000,250);
  assert.equal(x.repos[0].active,250);
  assert.equal(x.repos[0].runs[0].awaitingFinal,true);
  const request=polling.next(x,2000); assert.equal(request.kind,'run');
  polling.complete(x,response(request,{id:7,status:'in_progress'}),2100);
  assert.equal(x.repos[0].runs[0].awaitingFinal,false);
  assert.equal(x.repos[0].active,250);
  polling.activity(x,x.repos[0],[{id:7,status:'in_progress'}],3000);
  assert.equal(x.repos[0].active,1);
  assert.equal(x.repos[0].activeFromTotal,false);
});

// Step 9: details of runs that leave r.runs are pruned.
const completedRuns=(from,to)=>{const l=[]; for(let i=from;i<=to;i++) l.push({id:i,status:'completed',run_attempt:1}); return l;};
function pruneFixture() {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:completedRuns(1,10),activityAt:0}];
  x.details['a/b:1']={jobs:[]};
  return x;
}
test('a run dropped by a summary page loses its details', () => {
  const x=pruneFixture();
  assert.ok(x.details['a/b:1']);
  polling.mergeRuns(x,x.repos[0],[{id:11,status:'completed',run_attempt:1}]);
  assert.equal(x.repos[0].runs.some(r=>r.id===1),false);
  assert.equal(x.details['a/b:1'],undefined);
});
test('a run dropped by a run lookup loses its details', () => {
  const x=pruneFixture();
  x.repos[0].runs=completedRuns(2,11).concat([{id:1,status:'in_progress',awaitingFinal:true}]);
  const request=polling.next(x,1000); assert.equal(request.kind,'run'); assert.equal(request.run,'1');
  polling.complete(x,response(request,{id:1,status:'completed',run_attempt:1}),1100);
  assert.equal(x.repos[0].runs.some(r=>r.id===1),false);
  assert.equal(x.details['a/b:1'],undefined);
});
test('a completed run absent from the final summary loses its details', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:[{id:5,status:'completed',run_attempt:1}],activityAt:0}];
  x.details['a/b:5']={jobs:[]};
  polling.select(x,'a/b','',{},0,true);
  let n=0;
  for(let now=0;x.tasks['summary:a/b:'] || n===0;now+=1000) {
    const request=polling.next(x,now); if(!request) continue;
    assert.equal(request.kind,'summary'); n++;
    polling.complete(x,response(request,[]),now+10);
  }
  assert.equal(n,6);
  assert.equal(x.repos[0].runs.length,0);
  assert.equal(x.details['a/b:5'],undefined);
});
test('a run dropped by activity on a partial page loses its details', () => {
  const x=polling.create(); polling.open(x,0);
  x.repos=[{repo:'a/b',runs:[{id:7,status:'in_progress'}]}];
  x.details['a/b:7']={jobs:[]};
  polling.activity(x,x.repos[0],[{id:8,status:'in_progress'}],1000,250);
  assert.equal(x.repos[0].runs.some(r=>r.id===7),false);
  assert.equal(x.details['a/b:7'],undefined);
});
test('runs of a project removed from the catalogue lose their details', () => {
  const x=polling.create(); polling.open(x,0); x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:[]},{repo:'x/y',runs:[{id:7}]}];
  x.details['x/y:7']={jobs:[]}; x.details['a/b:7']={jobs:[]};
  polling.manual(x,0,true);
  const request=polling.next(x,0); assert.equal(request.kind,'catalogue');
  polling.complete(x,response(request,[{repo:'a/b'}]),100);
  assert.equal(x.repos.length,1);
  assert.equal(x.details['x/y:7'],undefined);
  assert.ok(x.details['a/b:7']);
});
test('an expanded run beyond the recent ten keeps its details', () => {
  const x=pruneFixture();
  x.expanded={'a/b:1':true};
  polling.mergeRuns(x,x.repos[0],[{id:11,status:'completed',run_attempt:1}]);
  assert.equal(x.repos[0].runs.some(r=>r.id===1),true);
  assert.ok(x.details['a/b:1']);
});

// Step 10: a host change replaces the state and drops the old flight.
test('resetHost starts a new generation and ignores the old reply', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',idle:3,hinted:true}]; x.details['a/b:7']={jobs:[]};
  const old=polling.next(x,0); assert.equal(old.kind,'activity');
  x.cooldown=5;
  const y=polling.resetHost(x);
  assert.notEqual(y,x);
  assert.equal(y.repos.length,0); assert.equal(Object.keys(y.details).length,0); assert.equal(y.cooldown,0);
  assert.equal(y.starts.length,1); assert.equal(y.opened,true);
  assert.equal(y.generation,x.generation+1);
  assert.equal(polling.complete(y,response(old,[]),100),false);
  const fresh=polling.next(y,2000); assert.equal(fresh.kind,'catalogue');
  polling.complete(y,response(fresh,[{repo:'a/b'}]),2050);
  assert.equal(y.repos[0].idle,undefined); assert.equal(y.repos[0].hinted,undefined);
  assert.equal(polling.complete(y,response(old,[{repo:'old/host'}]),2100),false);
  assert.equal(y.repos.length,1);
});

test('idle polling seeds once until selection changes', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',active:0,activityAt:0}];
  for(let now=0;now<50000;now+=1000) assert.equal(polling.next(x,now),null);
  assert.equal(x.seeds,1);
  polling.select(x,'a/b','',{},50000,true);
  const request=polling.next(x,50000);
  assert.equal(request.kind,'summary');
  assert.equal(x.seeds,2);
});

test('a future task wakes polling when it becomes due', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  polling.ensure(x,'catalogue','','','background',5000);
  assert.equal(polling.next(x,0),null);
  assert.equal(x.wakeAt,5000);
  assert.equal(polling.next(x,4000),null);
  const request=polling.next(x,5000);
  assert.equal(request.kind,'catalogue');
  assert.equal(x.seeds,2);
});

test('a queued run that starts running moves its project to the active cadence', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:[{id:7,status:'queued'}]},{repo:'c/d'}];
  polling.select(x,'c/d','',{},0,true);
  let request;
  for(let now=0;now<5000 && !(request && request.kind==='activity' && request.repo==='a/b');now+=1000) {
    request=polling.next(x,now);
    if(request && !(request.kind==='activity' && request.repo==='a/b')) { polling.complete(x,response(request,[]),now+10); request=null; }
  }
  assert.equal(request.kind,'activity');
  polling.complete(x,{...response(request,[]),total:0},4100);
  assert.equal(x.repos[0].active,0); assert.equal(x.repos[0].activeFromTotal,true);
  let lookup=null;
  for(let now=5000;now<=25000 && !lookup;now+=1000) {
    const r=polling.next(x,now);
    if(r && r.kind==='run' && r.repo==='a/b') lookup={r,now};
    else if(r) polling.complete(x,response(r,r.kind==='run'?{}:[]),now+10);
  }
  assert.ok(lookup,'queued run is looked up');
  polling.complete(x,response(lookup.r,{id:7,status:'in_progress'}),lookup.now+10);
  assert.equal(x.repos[0].active,1,'a confirmed running pipeline counts as active');
});

test('manual refresh also clears an inspected jobs retry delay', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',runs:[{id:7,status:'in_progress',run_attempt:'active'}]}];
  polling.select(x,'a/b','7',{'a/b:7':true},0,true);
  const jobs=polling.ensure(x,'jobs','a/b','7','interactive',0);
  jobs.due=300000; jobs.failures=6; // focused fixture: a jobs task deep in network backoff
  polling.manual(x,1000,false);
  assert.equal(jobs.due,1000); assert.equal(jobs.failures,0);
});

test('an idle selected project wakes for its summary', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',summaryAt:0,activityAt:55000,runs:[]}];
  polling.select(x,'a/b','',{},0,true);
  assert.equal(polling.next(x,1000),null);
  assert.equal(x.wakeAt,60000);
  assert.equal(polling.next(x,60000).kind,'summary');
});

test('an inspected unfinished pipeline wakes for its jobs', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',summaryAt:1000,activityAt:1000,runs:[{id:7,status:'in_progress',run_attempt:'active'}]}];
  x.details['a/b:7']={jobs:[],jobsAt:1000,bridges:[],bridgesAt:1000};
  polling.select(x,'a/b','7',{'a/b:7':true},0,true);
  assert.equal(polling.next(x,2000),null);
  assert.equal(x.wakeAt,6000);
  assert.equal(polling.next(x,6000).kind,'jobs');
});

function bridgeFixture(run={id:7,status:'completed',run_attempt:1}) {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true; s.catalogueAt=1000000;
  s.repos=[{repo:'a/b',summaryAt:1000000,activityAt:1000000,runs:[run]}];
  s.details['a/b:7']={jobs:[],jobsAt:0,finalAttempt:1};
  polling.select(s,'a/b','7',{'a/b:7':true},0,true);
  return s;
}
function bridge(s,now=0) {
  const q=polling.next(s,now); assert.equal(q.kind,'bridges'); return q;
}
test('bridges seed only for the selected inspected expanded run and keep their due time', () => {
  const s=bridgeFixture(); polling.seed(s,0);
  const t=s.tasks['bridges:a/b:7']; assert.equal(t.route,'bridges');
  t.due=9000; polling.seed(s,1000); assert.equal(t.due,9000); assert.equal(s.wakeAt,9000);
  polling.select(s,'a/b','7',{},2000,true); polling.seed(s,2000); assert.equal(s.tasks[t.key],undefined);
  polling.select(s,'a/b','8',{'a/b:8':true},3000,true); polling.seed(s,3000); assert.equal(s.tasks[t.key],undefined);
  polling.select(s,'', '',{'a/b:7':true},4000,true); polling.seed(s,4000); assert.equal(s.tasks[t.key],undefined);
});
test('bridges refresh every 15 seconds while a downstream runs, then stop at finality', () => {
  const s=bridgeFixture(); let q=bridge(s);
  polling.complete(s,response(q,[{id:2,status:'completed',downstream:{status:'in_progress'}}]),100);
  assert.equal(polling.next(s,1000),null); assert.equal(s.tasks['bridges:a/b:7'],undefined);
  assert.equal(s.wakeAt,15100);
  q=bridge(s,15100);
  polling.complete(s,response(q,[{id:2,status:'completed',downstream:{status:'completed'}}]),15200);
  polling.seed(s,15200); assert.equal(s.tasks['bridges:a/b:7'],undefined);
});
test('a bridges snapshot from before the parent finished is not final', () => {
  const s=bridgeFixture({id:7,status:'in_progress',run_attempt:1}); const q=bridge(s);
  polling.complete(s,response(q,[{id:2,status:'completed',downstream:null}]),100);
  assert.equal(s.details['a/b:7'].bridgesAttempt,0);
  s.repos[0].runs[0].status='completed';
  polling.seed(s,15100); assert.ok(s.tasks['bridges:a/b:7']);
  const again=bridge(s,15100);
  polling.complete(s,response(again,[{id:2,status:'completed',downstream:{status:'in_progress'}}]),15200);
  assert.equal(s.details['a/b:7'].bridgesAttempt,1);
  polling.seed(s,30200); assert.ok(s.tasks['bridges:a/b:7']);
});
test('manual and scheduled downstreams stop polling; manual refresh restarts it', () => {
  for(const conclusion of ['manual','scheduled']) {
    const s=bridgeFixture(); const q=bridge(s);
    // The helper normalises manual and scheduled to status "completed".
    polling.complete(s,response(q,[{id:2,status:'completed',downstream:{status:'completed',conclusion}}]),100);
    polling.seed(s,20000); assert.equal(s.tasks['bridges:a/b:7'],undefined);
    polling.manual(s,21000,false); assert.equal(s.tasks['bridges:a/b:7'].due,21000);
  }
});
test('jobs unavailable does not suppress bridges; bridge permission leaves jobs and project alone', () => {
  const s=bridgeFixture(); s.details['a/b:7']={jobs:[],unavailable:true,error:'jobs denied'};
  let q=bridge(s); polling.complete(s,{requestId:q.requestId,errorType:'permission',error:'bridges denied'},100);
  assert.equal(s.repos[0].blocked,undefined); assert.equal(s.details['a/b:7'].unavailable,true);
  assert.equal(s.details['a/b:7'].error,'jobs denied'); assert.equal(s.details['a/b:7'].bridgesUnavailable,true);
  assert.equal(s.details['a/b:7'].bridgesAt,100);
  polling.seed(s,20000); assert.equal(s.tasks['bridges:a/b:7'],undefined);
  polling.manual(s,21000,false); assert.equal(s.details['a/b:7'].bridgesUnavailable,false);
  assert.equal(s.details['a/b:7'].bridgesError,'');
});
test('bridge network retry keeps cached data and success clears its error', () => {
  const s=bridgeFixture(); s.details['a/b:7'].bridges=[{id:1,status:'in_progress'}];
  let q=bridge(s); polling.complete(s,{requestId:q.requestId,errorType:'network',error:'offline'},100);
  assert.equal(s.details['a/b:7'].bridgesError,'offline'); assert.equal(s.details['a/b:7'].bridges.length,1);
  assert.equal(s.tasks['bridges:a/b:7'].due,5100);
  q=bridge(s,5100); polling.complete(s,response(q,[]),5200);
  assert.equal(s.details['a/b:7'].bridgesError,''); assert.equal(s.details['a/b:7'].bridges.length,0);
});
test('route fallback is a new request, then becomes the host preference on success', () => {
  const s=bridgeFixture(); let q=bridge(s); assert.equal(q.route,'bridges');
  polling.complete(s,{requestId:q.requestId,errorType:'route',error:'missing'},100);
  assert.equal(s.bridgeRoute,'bridges'); assert.equal(s.details['a/b:7'].bridgesError,undefined);
  q=bridge(s,1000); assert.equal(q.route,'trigger_jobs'); assert.equal(s.requests,2);
  polling.complete(s,response(q,[]),1100); assert.equal(s.bridgeRoute,'trigger_jobs');
  assert.equal(polling.resetHost(s).bridgeRoute,'bridges');
});
test('a second route error is local permission and later pipelines use bridges', () => {
  const s=bridgeFixture(); let q=bridge(s);
  polling.complete(s,{requestId:q.requestId,errorType:'route',error:'missing'},100);
  q=bridge(s,1000); polling.complete(s,{requestId:q.requestId,errorType:'route',error:'still missing'},1100);
  assert.equal(s.details['a/b:7'].bridgesUnavailable,true); assert.equal(s.repos[0].blocked,undefined);
  assert.equal(s.bridgeRoute,'bridges');
  s.repos[0].runs.push({id:8,status:'completed',run_attempt:1}); s.details['a/b:8']={jobs:[],finalAttempt:1};
  polling.select(s,'a/b','8',{'a/b:8':true},2000,true);
  assert.equal(bridge(s,2000).route,'bridges');
});
test('navigation and collapse discard bridge pages; attempt change restarts page one', () => {
  for(const expanded of [{}, {'a/b:8':true}]) {
    const s=bridgeFixture(); const q=bridge(s);
    polling.complete(s,response(q,[{id:1,status:'completed'}],2),100);
    polling.select(s,'a/b',expanded['a/b:8']?'8':'7',expanded,200,true);
    polling.seed(s,200); assert.equal(s.tasks['bridges:a/b:7'],undefined);
  }
  const s=bridgeFixture(); let q=bridge(s);
  polling.complete(s,response(q,[{id:1,status:'completed'}],2),100);
  polling.mergeRuns(s,s.repos[0],[{id:7,status:'completed',run_attempt:2}]);
  q=bridge(s,1000); assert.equal(q.page,1);
  polling.complete(s,response(q,[{id:2,status:'completed'}]),1100);
  assert.deepEqual(Array.from(s.details['a/b:7'].bridges,x=>x.id),[2]);
});
test('jobs and bridges preserve each other in both arrival orders and permission recovery', () => {
  for(const first of ['jobs','bridges']) {
    const s=bridgeFixture(); s.details['a/b:7']={};
    const kinds=first==='jobs'?['jobs','bridges']:['bridges','jobs'];
    for(const kind of kinds) {
      const t=polling.ensure(s,kind,'a/b','7','interactive',0); if(kind==='bridges') t.route='bridges';
      const q=polling.next(s,1000+s.requests*1000); assert.equal(q.kind,kind);
      polling.complete(s,response(q,kind==='jobs'?[{id:1,status:'completed'}]:[{id:2,status:'completed'}]),1100+s.requests*1000);
    }
    assert.equal(s.details['a/b:7'].jobs.length,1); assert.equal(s.details['a/b:7'].bridges.length,1);
  }
  const s=bridgeFixture(); s.details['a/b:7'].bridges=[{id:2,status:'completed'}];
  polling.ensure(s,'bridges','a/b','7','interactive',0).route='bridges';
  let q=bridge(s); polling.complete(s,{requestId:q.requestId,errorType:'permission',error:'denied'},100);
  polling.ensure(s,'jobs','a/b','7','interactive',1000);
  q=polling.next(s,1000); polling.complete(s,{requestId:q.requestId,errorType:'permission',error:'jobs denied'},1100);
  assert.equal(s.details['a/b:7'].bridgesUnavailable,true);
  polling.manual(s,2000,false);
  delete s.tasks['summary:a/b:'];
  q=polling.next(s,2000); assert.equal(q.kind,'jobs');
  polling.complete(s,response(q,[{id:1,status:'completed'}]),2100);
  assert.equal(s.details['a/b:7'].error,''); assert.equal(s.details['a/b:7'].unavailable,false);
  assert.equal(s.details['a/b:7'].bridges.length,1);
});
test('bridges never poll while closed or in watch-only mode', () => {
  const s=bridgeFixture(); polling.close(s); assert.equal(polling.next(s,0),null);
  polling.open(s,1000); polling.seed(s,1000); assert.ok(s.tasks['bridges:a/b:7']);
  polling.close(s); polling.watch(s,'a/b',7,1000);
  const q=polling.next(s,31000); assert.equal(q.kind,'run');
  assert.equal(s.tasks['bridges:a/b:7'],undefined);
});
test('manual refresh restarts a bridge retry immediately', () => {
  const s=bridgeFixture(), t=polling.ensure(s,'bridges','a/b','7','interactive',300000);
  t.route='bridges'; t.failures=3;
  polling.manual(s,1000,false);
  assert.equal(t.due,1000); assert.equal(t.failures,0);
});
test('a running child costs about 120 bridge requests in 30 minutes', () => {
  const s=bridgeFixture(); let flight=null, count=0;
  s.repos[0].summaryAt=2000000; s.repos[0].activityAt=2000000; s.catalogueAt=2000000;
  for(let now=0;now<1800000;now+=250) {
    if(flight && now>=flight.end) {
      polling.complete(s,response(flight.req,[{id:2,status:'completed',downstream:{status:'in_progress'}}]),now);
      flight=null;
    }
    const q=polling.next(s,now);
    if(q) { assert.equal(q.kind,'bridges'); count++; flight={req:q,end:now+1000}; }
  }
  console.log('inspected parent with running child, 30 min bridge requests',count);
  assert.ok(count>=110 && count<=125);
});

function watchFixture(count=2) {
  const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
  s.repos=[{repo:'x/y',activityAt:0,summaryAt:0,runs:Array.from({length:count},(_,i)=>
    ({id:i+1,run_number:i+11,head_branch:'main',status:'in_progress'}))}];
  for(let i=1;i<=count;i++) assert.equal(polling.watch(s,'x/y',i,0),'watching');
  return s;
}
test('watch codes, finished conclusions, cap, and unfinished statuses', () => {
  const s=watchFixture(5);
  assert.equal(polling.watch(s,'x/y',1,0),'unwatched');
  assert.equal(polling.watch(s,'x/y',99,0),'missing');
  for(const conclusion of ['success','failed','canceled','skipped']) {
    s.repos[0].runs[0].conclusion=conclusion;
    assert.equal(polling.watch(s,'x/y',1,0),'finished');
  }
  for(const status of ['manual','scheduled']) {
    s.repos[0].runs[0]={id:1,status};
    assert.equal(polling.watch(s,'x/y',1,0),'watching');
    assert.equal(polling.watch(s,'x/y',1,0),'unwatched');
  }
  assert.equal(polling.watch(s,'x/y',1,0),'watching');
  s.repos[0].runs.push({id:6,status:'in_progress'});
  assert.equal(polling.watch(s,'x/y',6,0),'cap');
});
test('closed mode requests only watched runs every thirty seconds', () => {
  const s=watchFixture(); polling.select(s,'x/y','1',{'x/y:1':true},0,true); polling.close(s);
  polling.ensure(s,'activity','x/y','','active',0);
  polling.ensure(s,'run','x/y','3','active',0);
  let req=polling.next(s,30000); assert.equal(req.kind,'run'); assert.equal(req.repo,'x/y'); assert.equal(req.run,'1');
  polling.complete(s,response(req,{id:1,status:'in_progress'}),30000);
  req=polling.next(s,31000); assert.equal(req.kind,'run'); assert.equal(req.repo,'x/y'); assert.equal(req.run,'2');
  polling.complete(s,response(req,{id:2,status:'in_progress'}),31000);
  assert.equal(Object.values(s.tasks).some(t=>t.kind!=='run' || t.run==='3'),false);
  assert.equal(polling.next(s,32000),null);
  req=polling.next(s,60000); assert.equal(req.kind,'run'); assert.equal(req.run,'1');
  polling.complete(s,response(req,{id:1,status:'completed',conclusion:'success'}),60000);
  assert.equal(s.events.length,1); assert.equal(s.events[0].type,'finished');
  assert.equal(s.tasks['jobs:x/y:1'],undefined);
  req=polling.next(s,61000); assert.equal(req.kind,'run'); assert.equal(req.run,'2');
  polling.complete(s,response(req,{id:2,status:'completed',conclusion:'failed'}),61000);
  assert.equal(polling.next(s,62000),null); assert.equal(polling.next(s,100000),null);
});
test('activity and intermediate summary pages settle a finish once', () => {
  const s=watchFixture(1), r=s.repos[0];
  const lookup=polling.next(s,30000); assert.equal(lookup.kind,'run');
  polling.activity(s,r,[{id:1,status:'completed',conclusion:'success'}],1000);
  polling.settle(s,1000);
  polling.complete(s,response(lookup,{id:1,status:'completed',conclusion:'success'}),30100);
  assert.equal(s.events.length,1);
  const x=watchFixture(1); x.repos[0].summaryAt=undefined; polling.select(x,'x/y','',{},0,true);
  let req=polling.next(x,0); assert.equal(req.kind,'summary');
  polling.complete(x,response(req,[{id:1,status:'completed',conclusion:'failed'}]),100);
  assert.equal(x.events.length,1); assert.equal(x.events[0].conclusion,'failed');
});
test('watched run survives the completed trim until lookup finishes it', () => {
  const s=watchFixture(1); s.repos[0].runs[0].status='completed';
  polling.mergeRuns(s,s.repos[0],Array.from({length:10},(_,i)=>({id:i+2,status:'completed'})));
  assert.ok(polling.runFor(s,'x/y',1));
  polling.close(s);
  const req=polling.next(s,30000); assert.equal(req.run,'1');
  polling.complete(s,response(req,{id:1,status:'completed',conclusion:'failed'}),30000);
  assert.equal(s.events.length,1); assert.equal(s.events[0].conclusion,'failed');
});
test('idle open watch wakes at its next lookup', () => {
  const s=watchFixture(1); s.repos[0].activityAt=1000; s.repos[0].summaryAt=1000;
  const req=polling.next(s,30000); assert.equal(req.kind,'run');
  polling.complete(s,response(req,{id:1,status:'completed'}),30000);
  assert.ok(s.wakeAt<=60000);
  assert.equal(polling.next(s,59000),null);
  assert.equal(polling.next(s,60000).kind,'run');
});
test('expiry runs before cooldown or auth and keeps its original deadline', () => {
  const s=watchFixture(1), until=s.watches['x/y:1'].until;
  polling.close(s); polling.open(s,1000); assert.equal(s.watches['x/y:1'].until,until);
  s.cooldown=until+1000; s.auth=true;
  assert.equal(polling.next(s,until),null);
  assert.equal(s.events[0].type,'expired'); assert.equal(Object.keys(s.watches).length,0);
});
test('watched lookup errors isolate permission, stop closed auth, and retain network retry', () => {
  const permission=watchFixture(); polling.close(permission);
  let req=polling.next(permission,30000);
  polling.complete(permission,{...response(req,{}),error:'forbidden',errorType:'permission'},30000);
  assert.equal(permission.events.length,1); assert.equal(permission.events[0].type,'unavailable');
  assert.deepEqual(Object.keys(permission.watches),['x/y:2']);
  const auth=watchFixture(); polling.close(auth);
  req=polling.next(auth,30000);
  polling.complete(auth,{...response(req,{}),error:'login',errorType:'auth'},30000);
  assert.equal(auth.events[0].type,'auth'); assert.equal(auth.events[0].count,2);
  assert.equal(Object.keys(auth.watches).length,0);
  const open=watchFixture(1); req=polling.next(open,30000);
  polling.complete(open,{...response(req,{}),error:'login',errorType:'auth'},30000);
  assert.equal(Object.keys(open.watches).length,1);
  const network=watchFixture(1); polling.close(network); req=polling.next(network,30000);
  polling.complete(network,{...response(req,{}),error:'offline',errorType:'network'},30000);
  assert.equal(Object.keys(network.watches).length,1);
  assert.equal(network.tasks['run:x/y:1'].failures,1);
});
test('close reports auth, open accepts a closed flight, close rejects an open flight', () => {
  const s=watchFixture(1); s.auth=true; polling.close(s);
  assert.equal(s.events[0].type,'auth'); assert.equal(s.events[0].count,1);
  const x=watchFixture(1); polling.close(x);
  let req=polling.next(x,30000); polling.open(x,30100);
  assert.equal(polling.complete(x,response(req,{id:1,status:'in_progress'}),30200),true);
  assert.equal(x.flight,null);
  polling.ensure(x,'activity','x/y','','active',40000);
  req=polling.next(x,40000); assert.ok(req);
  polling.close(x); assert.equal(polling.complete(x,response(req,[]),40100),false);
});
test('catalogue removal settles unavailable, blocked retry survives seed, reset drops watches', () => {
  const s=watchFixture(1); s.discover=true; s.slot=4;
  let req=polling.next(s,0); assert.equal(req.kind,'catalogue');
  polling.complete(s,response(req,[]),100);
  assert.equal(s.events[0].type,'unavailable');
  const x=watchFixture(1); x.repos[0].blocked=true;
  const task=polling.ensure(x,'run','x/y','1','active',50000); task.failures=2;
  polling.seed(x,1000); assert.equal(x.tasks[task.key],task);
  assert.equal(task.due,50000); assert.equal(task.failures,2);
  assert.equal(Object.keys(polling.resetHost(x).watches).length,0);
});
test('a retried watched run remains watched', () => {
  const s=watchFixture(1); polling.close(s);
  // A failed job was retried: GitLab reports the pipeline as running (then pending), which is not finished.
  let req=polling.next(s,30000);
  polling.complete(s,response(req,{id:1,status:'in_progress',conclusion:'running'}),30000);
  req=polling.next(s,61000);
  polling.complete(s,response(req,{id:1,status:'queued',conclusion:'pending'}),61000);
  assert.equal(Object.keys(s.watches).length,1); assert.equal(s.events.length,0);
  assert.equal(s.repos[0].runs[0].conclusion,'pending');
});
test('a setup error while closed retries instead of ending the watches', () => {
  const s=watchFixture(2); polling.close(s);
  const req=polling.next(s,30000);
  assert.ok(polling.complete(s,{requestId:req.requestId,error:'GitLab helper returned invalid data',errorType:'setup'},30000));
  assert.equal(Object.keys(s.watches).length,2); assert.equal(s.events.length,0); assert.equal(s.auth,false);
  assert.equal(s.tasks[s.flight ? '' : 'run:x/y:'+req.run].failures,1);
});
test('a matching reply that is no longer wanted still clears the flight', () => {
  const s=watchFixture(1); polling.close(s);
  const req=polling.next(s,30000); assert.ok(req);
  s.watches['x/y:1'].until=30000; polling.next(s,31000); // expires the last watch while in flight
  assert.equal(polling.complete(s,response(req,{id:1,status:'in_progress',conclusion:'running'}),31000),false);
  assert.equal(s.flight,null);
});


test('touch creates a run task and clears a backed-off snapshot', () => {
  const s=polling.create(); s.repos=[{repo:'a/b',summaryAt:9000}];
  polling.touch(s,'a/b','7',10000);
  assert.equal(s.tasks['run:a/b:7'].due,10000);
  assert.equal(s.repos[0].summaryAt,undefined);
  const task=s.tasks['run:a/b:7']; task.due=50000; task.failures=3; task.page=2; task.items=[{id:1}];
  polling.touch(s,'a/b','7',11000);
  assert.equal(task.due,11000); assert.equal(task.failures,0);
  assert.equal(task.page,1); assert.equal(task.items.length,0);
  assert.equal(s.tasks['summary:a/b:'],undefined,'touch does not create a summary task');
  s.expanded['a/b:7']=true;
  polling.touch(s,'a/b','7',12000);
  assert.equal(s.tasks['jobs:a/b:7'].due,12000);
});

test('touch restarts in-flight run, summary and paged jobs without publishing stale data', () => {
  for (const kind of ['run','summary','jobs']) {
    const s=polling.create(); polling.open(s,0); s.discover=false; s.catalogueComplete=true;
    s.repos=[{repo:'a/b',summaryAt:0,runs:[{id:7,status:'in_progress',conclusion:'running'}]}];
    s.selected='a/b'; s.inspected='7'; s.expanded={'a/b:7':true};
    s.details['a/b:7']={jobs:[{id:1}],jobsAt:0};
    const task=polling.ensure(s,kind,'a/b',kind==='summary'?'':'7','interactive',1000);
    if(kind==='jobs') { task.page=2; task.items=[{id:1}]; }
    s.wakeAt=Infinity;
    const request=polling.next(s,1000); assert.equal(request.kind,kind);
    polling.touch(s,'a/b','7',1100);
    assert.equal(task.restart,true);
    const stale=kind==='run' ? {id:7,status:'completed',conclusion:'failed'} :
      kind==='summary' ? [{id:99,status:'completed'}] : [{id:2,status:'completed'}];
    assert.equal(polling.complete(s,response(request,stale),1200),true);
    assert.equal(task.page,1); assert.equal(task.due,1200);
    assert.equal(task.restart,undefined);
    assert.equal(s.repos[0].runs[0].conclusion,'running');
    assert.equal(s.repos[0].runs.some(run=>run.id===99),false);
    assert.equal(s.details['a/b:7'].jobs[0].id,1);
  }
});

test('touch does not settle a watched pipeline from a stale run reply', () => {
  const s=watchFixture(1); s.discover=false; s.catalogueComplete=true;
  const request=polling.next(s,30000); assert.equal(request.kind,'run');
  polling.touch(s,'x/y','1',30100);
  polling.complete(s,response(request,{id:1,status:'completed',conclusion:'failed'}),30200);
  assert.ok(s.watches['x/y:1']); assert.equal(s.events.length,0);
  assert.equal(s.tasks['run:x/y:1'].due,30200);
});

test('write metadata cools polling without changing read errors, tasks or starts', () => {
  const s=polling.create(); s.error='offline'; s.auth=true; s.repos=[{repo:'a/b',blocked:true}];
  const task=polling.ensure(s,'run','a/b','7','interactive',5000);
  s.starts.push(1000); s.wakeAt=5000;
  polling.noteWrite(s,{ok:true,remaining:0,resetAt:120000},2000);
  assert.equal(s.cooldown,120000); assert.equal(s.wakeAt,0);
  assert.equal(s.error,'offline'); assert.equal(s.auth,true); assert.equal(s.repos[0].blocked,true);
  assert.equal(s.tasks[task.key],task); assert.equal(s.starts.length,1); assert.equal(s.starts[0],1000);
  polling.noteWrite(s,{errorType:'rate'},120000);
  assert.equal(s.cooldown,180000); assert.equal(s.rateFailures,1);
});

test('a write pauses reads for one second without consuming the read budget', () => {
  const s=polling.create(); polling.open(s,0);
  s.discover=true; polling.writeStarted(s,5000);
  assert.equal(polling.next(s,5999),null);
  assert.equal(s.starts.length,0); assert.equal(s.writeAt,5000);
  assert.equal(polling.resetHost(s).writeAt,5000);
  const request=polling.next(s,6000); assert.equal(request.kind,'catalogue');
  assert.equal(s.starts.length,1);
});

// Measurement (#35): 137 projects (5 active within a day, 15 within a week, 117 older), org/r0 selected, 1s responses.
// Baseline before #35: realistic 30 min 713 requests (idle 408); realistic 2 h 2830 (idle 1632); queued 30 min 1800 (lookups 1413).
function scenario({duration, queued=0}) {
  const DAY=86400000, age=i=>i<5?DAY/4:i<20?3*DAY:60*DAY;
  const s=polling.create(), repos=Array.from({length:137},(_,i)=>({repo:`org/r${i}`,lastActivity:new Date(-age(i)).toISOString()}));
  polling.open(s,0); polling.select(s,'org/r0','',{},0,false);
  let flight=null, seeded=false; const counts={total:0};
  for(let now=0;now<duration;now+=250) {
    if(flight && now>=flight.end) {
      const q=flight.req; let data=[],next=0;
      if(q.kind==='catalogue') { data=q.page===1?repos.slice(0,100):repos.slice(100); next=q.page===1?2:0; }
      if(q.kind==='run') data={id:Number(q.run),status:'queued',conclusion:'pending',run_attempt:1,name:'CI'};
      polling.complete(s,response(q,data,next),now); flight=null;
      if(queued && !seeded && q.kind==='catalogue' && s.catalogueComplete) {
        seeded=true;
        for(let i=0;i<queued;i++) s.repos.find(r=>r.repo===`org/r${i+1}`).runs=[{id:1000+i,status:'queued',conclusion:'pending',run_attempt:1}];
        s.wakeAt=0;
      }
    }
    const q=polling.next(s,now);
    if(q) { counts.total++; const k=q.kind==='activity'?'activity/'+s.tasks[s.flight.key].group:q.kind; counts[k]=(counts[k]||0)+1; flight={req:q,end:now+1000}; }
  }
  return counts;
}
const realistic30=scenario({duration:1800000}), realistic2h=scenario({duration:7200000}), queued30=scenario({duration:1800000,queued:30});
console.log('realistic 30 min', realistic30); console.log('realistic 2 h', realistic2h); console.log('queued 30 min', queued30);
assert.ok(realistic30.total<500,`realistic 30 min ${realistic30.total}`);
assert.ok(realistic2h['activity/background']<653,`realistic 2 h background activity ${realistic2h['activity/background']}`);
assert.ok(queued30.run<707,`queued 30 min lookups ${queued30.run}`);
