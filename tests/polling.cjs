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
s.catalogueComplete=true; s.discover=false; polling.open(s,0);
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
  request=polling.next(x,1000); assert.equal(request.page,1);
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
  request=polling.next(x,1000); assert.equal(request.page,2);
  polling.mergeRuns(x,x.repos[0],[{id:7,status:'completed',run_attempt:'t1'}]);
  polling.mergeRuns(x,x.repos[0],[{id:7,status:'in_progress',run_attempt:'active'}]);
  polling.complete(x,response(request,[{id:2,status:'in_progress'}]),1100);
  assert.equal(x.details['a/b:7'],undefined);
  request=polling.next(x,2000); assert.equal(request.kind,'jobs'); assert.equal(request.page,1);
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

test('background queued run is looked up after 15 seconds', () => {
  const x=polling.create(); polling.open(x,0); x.discover=false; x.catalogueComplete=true;
  x.repos=[{repo:'a/b',active:0,activityAt:0,runs:[{id:7,status:'queued'}]}];
  assert.equal(polling.next(x,0),null);
  assert.equal(polling.next(x,14000),null);
  const request=polling.next(x,15000);
  assert.equal(request.kind,'run'); assert.equal(request.run,'7');
  assert.equal(x.tasks[x.flight.key].group,'background');
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
  x.repos=[{repo:'a/b'}]; x.details['a/b:7']={jobs:[]};
  const old=polling.next(x,0); assert.equal(old.kind,'activity');
  x.cooldown=5;
  const y=polling.resetHost(x);
  assert.notEqual(y,x);
  assert.equal(y.repos.length,0); assert.equal(Object.keys(y.details).length,0); assert.equal(y.cooldown,0);
  assert.equal(y.starts.length,1); assert.equal(y.opened,true);
  assert.equal(y.generation,x.generation+1);
  assert.equal(polling.complete(y,response(old,[]),100),false);
  const fresh=polling.next(y,2000); assert.equal(fresh.kind,'catalogue');
  assert.equal(polling.complete(y,response(old,[{repo:'old/host'}]),2100),false);
  assert.equal(y.repos.length,0);
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

