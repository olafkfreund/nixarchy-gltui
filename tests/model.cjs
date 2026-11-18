const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const model = {};
vm.createContext(model);
vm.runInContext(fs.readFileSync('PipelinesModel.js', 'utf8'), model);
const open = (payload, host = 'gitlab.example.org') => JSON.parse(JSON.stringify(model.openFilter(payload, host)));
const empty = {filter: null, notice: ''};
for (const payload of ['{}', '', 'null', '[]', '3', '{bad', {filter: 3}, {filter: '  '}])
  assert.deepEqual(open(payload), empty);
assert.deepEqual(open('{"filter":" group/p "}'), {filter: 'group/p', notice: ''});
assert.deepEqual(open({filter: ' a\n\u0007\u0085b '}), {filter: 'ab', notice: ''});
assert.deepEqual(open({filter: 'x'.repeat(200)}), {filter: 'x'.repeat(200), notice: ''});
assert.deepEqual(open({filter: 'x'.repeat(201)}), empty);
assert.deepEqual(open({filter: 'group/p'}), {filter: 'group/p', notice: ''});
assert.deepEqual(open({filter: 'g/p', host: 'GITLAB.EXAMPLE.ORG'}), {filter: 'g/p', notice: ''});
assert.deepEqual(open({filter: 'g/p', host: 'gitlab.example.org'}, 'gitlab.example.org:8443'), {filter: 'g/p', notice: ''});
assert.deepEqual(open({filter: 'g/p', host: 'elsewhere.example'}),
  {filter: null, notice: 'Repository is on elsewhere.example; this panel shows gitlab.example.org'});
assert.deepEqual(open({filter: 'g/p', host: 'x\u0007' + 'y'.repeat(120)}),
  {filter: null, notice: 'Repository is on x' + 'y'.repeat(99) + '; this panel shows gitlab.example.org'});
for (const host of [5, '']) assert.deepEqual(open({filter: 'g/p', host}), empty);
const repos = [{repo: 'group/sub/project', url: 'https://gitlab.com/group/sub/project', runs: [{id: 7, status: 'in_progress', conclusion: 'running', name: 'CI', head_branch: 'main', run_number: 3, sha: 'a'.repeat(40), html_url: 'https://gitlab.com/p/-/pipelines/7'}]}];
const runKey = 'group/sub/project:7';
const expanded = {'repo:group/sub/project': true, [runKey]: true, [runKey + ':stage:build']: true};
const jobs = [
  {id: 8, name: 'compile', stage: 'build', status: 'completed', conclusion: 'success', started_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:01:00Z', html_url: 'https://gitlab.com/p/-/jobs/8'},
  {id: 9, name: 'lint', stage: 'build', status: 'in_progress', conclusion: 'running', started_at: '2026-01-01T00:00:30Z'},
  {id: 10, name: 'unit', stage: 'test', status: 'queued', conclusion: 'created'}];
const details = {[runKey]: {jobs}};
const rows = model.rows(repos, expanded, details, '', Date.parse('2026-01-01T00:02:00Z'));
assert.equal(rows.map(r => r.kind).join(), 'repo,run,stage,job,job,stage');
assert.equal(rows[0].url, 'https://gitlab.com/group/sub/project/-/pipelines');
assert.equal(rows[0].status, 'running');
assert.equal(rows[2].title, 'build');
assert.equal(rows[2].status, 'running');
assert.equal(rows[2].info, '1/2 jobs · 2m 0s');
assert.equal(rows[3].title, 'compile');
assert.equal(rows[3].status, 'success');
assert.equal(rows[3].url, 'https://gitlab.com/p/-/jobs/8');
assert.equal(rows[3].parent, rows[2].key);
assert.equal(rows[5].title, 'test');
assert.equal(rows[5].status, 'pending');
assert.equal(Object.hasOwn(rows[0], 'sha'), false);
assert.ok(rows.slice(1).every(row => row.sha === 'a'.repeat(40)));
assert.equal(model.selection(rows, runKey + ':stage:build', 0), 2);
assert.equal(model.selection([], 'missing', 5), 0);
const failures = [
  {kind:'repo', status:'failed'}, {kind:'run', status:'failed'},
  {kind:'job', status:'allowed to fail'}, {kind:'stage', status:'error'},
  {kind:'message', status:'failed'}, {kind:'stage', status:'failed'},
  {kind:'job', status:'unavailable'}, {kind:'job', status:'failed'}
];
assert.equal(model.nextFailure(failures, 0), 1);
assert.equal(model.nextFailure(failures, 1), 5);
assert.equal(model.nextFailure(failures, 5), 7);
assert.equal(model.nextFailure(failures, 7), 1);
assert.equal(model.nextFailure([{kind:'job', status:'failed'}], 0), 0);
assert.equal(model.nextFailure([{kind:'run', status:'success'}, {kind:'job', status:'allowed to fail'}], 0), -1);
assert.equal(model.nextFailure([], 0), -1);
const copied = (row, what) => JSON.parse(JSON.stringify(model.copyText(row, what)));
assert.deepEqual(copied({url:'https://gitlab.com/p', sha:'a'.repeat(40)}, 'url'), {text:'https://gitlab.com/p', label:'Copied URL'});
assert.deepEqual(copied({}, 'url'), {text:'', label:'Nothing to copy'});
assert.deepEqual(copied({sha:'a'.repeat(40)}, 'sha'), {text:'a'.repeat(40), label:'Copied aaaaaaaa'});
assert.deepEqual(copied({}, 'sha'), {text:'', label:'No commit for this row'});
assert.deepEqual(copied(null, 'sha'), {text:'', label:'Nothing to copy'});
assert.equal(model.rows(repos, {}, details, '', Date.now()).length, 1);
assert.equal(model.rows(repos, {'repo:group/sub/project': true}, {}, 'main', Date.now()).length, 2);
assert.equal(model.rows(repos, {'repo:group/sub/project': true}, {}, 'running', Date.now()).length, 2);
assert.equal(model.rows(repos, expanded, details, 'missing', Date.now()).length, 0);
assert.equal(model.rows(repos, expanded, {}, '', Date.now())[2].title, 'Loading jobs…');
// Stage aggregation, in GitLab's precedence.
const agg = (...c) => model.stageStatus(c.map(x => ({conclusion: x.replace('?', ''), allow_failure: x.endsWith('?')})));  // '?' = allow_failure
assert.equal(agg('failed', 'running'), 'running');
assert.equal(agg('success', 'failed'), 'failed');
assert.equal(agg('success', 'failed?'), 'success', 'allowed failures do not fail the stage');
assert.equal(agg('success', 'pending'), 'pending');
assert.equal(agg('success', 'waiting_for_callback'), 'pending');
assert.equal(agg('failed?'), 'success', 'a stage with only allowed failures is success');
const failureNow = Date.parse('2026-01-01T00:02:00Z');
const allowedJob = {id: 1, name: 'flaky', stage: 'build', status: 'completed', conclusion: 'failed', allow_failure: true,
  started_at: '2026-01-01T00:00:00Z', completed_at: '2026-01-01T00:01:02Z'};
const allowed = model.rows(repos, expanded, {[runKey]: {jobs: [allowedJob]}}, '', failureNow);
assert.equal(allowed[2].status, 'success');
assert.equal(allowed[3].status, 'allowed to fail');
assert.equal(allowed[3].info, model.duration(allowedJob, failureNow));
const blocked = model.rows(repos, expanded, {[runKey]: {jobs: [{...allowedJob, allow_failure: false}]}}, '', failureNow);
assert.equal(blocked[3].status, 'failed', 'a blocking failed job stays failed');
const odd = model.stages(['constructor', 'toString', '__proto__'].map((stage, id) => ({id, stage, conclusion: 'success', status: 'completed'})));
assert.equal(odd.map(x => x.name).join(), 'constructor,toString,__proto__');
assert.equal(odd.map(x => x.jobs.length).join(), '1,1,1');
assert.equal(agg('canceled', 'success'), 'canceled');
assert.equal(agg('manual', 'manual'), 'manual');
assert.equal(agg('manual', 'skipped'), 'skipped');
assert.equal(model.duration({started_at:'2026-01-01T00:00:00Z'}, Date.parse('2026-01-01T00:01:15Z')), '1m 15s');
const now = Date.parse('2026-01-01T00:02:00Z');
for (const suffix of ['head', 'merge', 'train'])
  assert.equal(model.shortRef('refs/merge-requests/123/' + suffix), '!123');
for (const ref of ['main', 'refs/merge-requests/123/other', 'refs/merge-requests/x/head'])
  assert.equal(model.shortRef(ref), ref);
assert.equal(model.runMatches({head_branch:'refs/merge-requests/123/head'}, '!123'), true);
assert.equal(model.runMatches({head_branch:'refs/merge-requests/123/head'}, '123'), true);
for (const [s, expected] of [[9,'just now'],[10,'10s ago'],[59,'59s ago'],[60,'1m ago'],
  [3599,'59m ago'],[3600,'1h ago'],[86399,'23h ago'],[86400,'1d ago']])
  assert.equal(model.ago(new Date(now - s * 1000).toISOString(), now), expected);
assert.equal(model.ago(new Date(now + 1000).toISOString(), now), 'just now');
assert.equal(model.ago('', now), '');
assert.equal(model.ago('invalid', now), '');
for (const [code, expected] of Object.entries({script_failure:'script failure', runner_system_failure:'runner error',
  stuck_or_timeout_failure:'timed out', job_execution_timeout:'timed out', api_failure:'API error',
  missing_dependency_failure:'missing dependency', runner_unsupported:'runner unsupported',
  scheduler_failure:'scheduler error', data_integrity_failure:'data error', unknown_failure:'unknown failure',
  new_code:'new code', constructor:'constructor'}))
  assert.equal(model.reasonText(code), expected);
assert.equal(model.reasonText(''), '');
assert.equal(model.seconds(45), '45s');
assert.equal(model.seconds(62), '1m 2s');
assert.equal(model.seconds(3900), '1h 5m');
assert.equal(model.duration({started_at:'2026-01-01T00:00:00Z', completed_at:'2026-01-01T00:01:02Z'}, now), '1m 2s');
const at = s => new Date(now - s * 1000).toISOString();
assert.equal(model.infoText({kind:'repo', info:'2 running', checked:at(10)}, now), '2 running · checked 10s ago');
assert.equal(model.infoText({kind:'repo', info:'not checked', checked:at(10)}, now), 'not checked');
assert.equal(model.infoText({kind:'repo', info:'archived', checked:at(10)}, now), 'archived');
assert.equal(model.infoText({kind:'run', status:'success', started:at(70), ended:at(10), finished:at(9)}, now),
  'success · 1m 0s · just now');
assert.equal(model.infoText({kind:'stage', status:'running', done:1, total:2, started:at(70)}, now),
  'running · 1/2 jobs · 1m 10s');
assert.equal(model.infoText({kind:'job', status:'running', started:at(30), serverDuration:5}, now), 'running · 30s');
assert.equal(model.infoText({kind:'job', status:'success', complete:true, serverDuration:0}, now), 'success · 0s');
assert.equal(model.infoText({kind:'job', status:'failed', complete:true, serverDuration:62,
  reason:'script_failure', queued:40, finished:at(20)}, now),
  'failed · script failure · 1m 2s · queued 40s · 20s ago');
assert.equal(model.infoText({kind:'job', status:'allowed to fail', complete:true, serverDuration:62,
  reason:'script_failure'}, now), 'allowed to fail · script failure · 1m 2s');
assert.equal(model.infoText({kind:'message', status:'queued', info:''}, now), 'queued');
assert.equal(model.infoText({kind:'message', status:'error', info:'unavailable'}, now), 'error · unavailable');
assert.equal(model.subtitleText({kind:'run', subtitle:'!42 · #1 · abc', fetched:at(20)}, now),
  '!42 · #1 · abc · jobs fetched 20s ago');
assert.equal(model.subtitleText({kind:'run', subtitle:'main', fetched:''}, now), 'main');
assert.equal(model.subtitleText({kind:'job', subtitle:'job', fetched:at(20)}, now), 'job');
const detailRows = model.rows([{repo:'g/p', checked:at(20), runs:[{id:1, head_branch:'refs/merge-requests/42/head',
  status:'completed', conclusion:'success', run_number:1, run_started_at:at(70), completed_at:at(10)}]}],
  {'repo:g/p':true, 'g/p:1':true, 'g/p:1:stage:build':true},
  {'g/p:1':{updated:at(20), jobs:[{id:2, name:'job', stage:'build', status:'completed', conclusion:'failed',
    started_at:at(60), completed_at:at(10), duration:0, queued_duration:4, failure_reason:'script_failure'}]}}, '', now);
assert.equal(detailRows[0].checked, at(20));
assert.equal(detailRows[1].subtitle, '!42 · #1 · ');
assert.deepEqual([detailRows[1].started, detailRows[1].ended, detailRows[1].finished, detailRows[1].fetched],
  [at(70), at(10), at(10), at(20)]);
assert.deepEqual([detailRows[2].started, detailRows[2].ended, detailRows[2].done, detailRows[2].total],
  [at(60), at(10), 1, 1]);
assert.deepEqual([detailRows[3].started, detailRows[3].ended, detailRows[3].finished, detailRows[3].complete,
  detailRows[3].serverDuration, detailRows[3].queued, detailRows[3].reason],
  [at(60), at(10), at(10), true, 0, 4, 'script_failure']);
const groups = [
  ['running', '●', ['running', 'canceling']],
  ['success', '✓', ['success']],
  ['failed', '✕', ['failed', 'error', 'unavailable']],
  ['allowed', '!', ['allowed to fail']],
  ['manual', '▶', ['manual']],
  ['scheduled', '◷', ['scheduled']],
  ['queued', '◌', ['created', 'pending', 'waiting_for_resource', 'preparing', 'waiting_for_callback', 'queued', 'awaiting final status']],
  ['skipped', '−', ['skipped']],
  ['canceled', '⊘', ['canceled']],
  ['neutral', '·', ['neutral']],
  ['unknown', '○', ['frobnicated']]
];
for (const [group, icon, statuses] of groups) for (const status of statuses) {
  assert.equal(model.group(status), group, status);
  assert.equal(model.icon(status), icon, status);
}
assert.equal(model.group('constructor'), 'unknown');
assert.equal(model.icon('constructor'), '○');
assert.equal(new Set(groups.map(([, icon]) => icon)).size, 11);
assert.equal(model.reply('{"repos":[]}', 0, 5), '{"repos":[]}');
// A failing helper yields fixed text; stderr never reaches the panel.
assert.deepEqual(JSON.parse(model.reply('', 127, 5)), {requestId: 5, errorType: 'setup', error: 'python3 not found'});
const failed = JSON.parse(model.reply('', 2, 5));
assert.equal(failed.error, 'GitLab helper failed (exit 2); see the shell log');
assert.equal(failed.errorType, 'setup');
const ranked = model.rows([{repo:'z/idle', checked:'now', active:0}, {repo:'a/unchecked'}, {repo:'b/running', active:2, checked:'now'}], {}, {}, '', Date.now());
assert.equal(ranked[0].title, 'b/running');
assert.equal(ranked[0].info, '2 running');
assert.equal(ranked[2].info, 'not checked');
assert.equal(model.rows([{repo:'a/b', description:'find this project'}], {}, {}, 'find this', Date.now()).length, 1);
const searchRepos = [
  {repo:'needle-project', runs:[{name:'CI'}]},
  {repo:'description-match', description:'needle', runs:[{name:'CI'}]},
  {repo:'pipeline-name', runs:[{name:'needle'}]},
  {repo:'pipeline-title', runs:[{display_title:'needle'}]},
  {repo:'pipeline-branch', runs:[{head_branch:'needle'}]},
  {repo:'pipeline-status', runs:[{conclusion:'needle'}]},
  {repo:'no-match', runs:[{name:'CI'}]}
];
assert.equal(JSON.stringify(model.autoOpen(searchRepos, '')), '{}');
assert.equal(JSON.stringify(model.autoOpen(searchRepos, 'NEEDLE')),
  JSON.stringify({'repo:pipeline-name':true, 'repo:pipeline-title':true,
    'repo:pipeline-branch':true, 'repo:pipeline-status':true}));
const explicit = {'repo:constructor':true, 'pipeline:1':true};
const automatic = {'repo:pipeline-name':true};
const collapsed = {'pipeline:1':true};
const before = [JSON.stringify(explicit), JSON.stringify(automatic), JSON.stringify(collapsed)];
assert.equal(JSON.stringify(model.merge(explicit, automatic, collapsed)),
  JSON.stringify({'repo:constructor':true, 'repo:pipeline-name':true}));
assert.deepEqual([JSON.stringify(explicit), JSON.stringify(automatic), JSON.stringify(collapsed)], before);
const backing = [];
let edits = 0;
const list = {
  get count() { return backing.length; },
  get(i) { return backing[i]; },
  insert(i, value) { backing.splice(i, 0, value); edits++; },
  move(from, to) { backing.splice(to, 0, ...backing.splice(from, 1)); edits++; },
  remove(i, count) { backing.splice(i, count); edits++; },
  setProperty(i, role, value) { backing[i][role] = value; edits++; }
};
const first = [{key:'a',title:'A',status:'queued'}, {key:'b',title:'B',status:'queued'}];
assert.equal(model.syncRows(list, first), true);
const originalA = backing[0];
edits = 0;
assert.equal(model.syncRows(list, first), false);
assert.equal(edits, 0, 'Identical polling result must not reset or update delegates');
assert.equal(model.syncRows(list, [{...first[0],status:'in_progress'}, first[1]]), false);
assert.equal(backing[0], originalA, 'Status update preserves existing row');
edits = 0;
assert.equal(model.syncRows(list, [{...first[0],status:'in_progress',sha:'b'.repeat(40)}, first[1]]), false);
assert.equal(backing[0].rowData.sha, 'b'.repeat(40), 'SHA-only update refreshes rowData');
assert.equal(edits, 1);
assert.equal(model.syncRows(list, [first[1], first[0]]), true);
assert.equal(backing[1], originalA, 'Reordering moves the row instead of recreating it');
model.syncRows(list, [first[0]]);
assert.equal(list.count, 1);
assert.equal(backing[0].rowKey, 'a');
for (const field of ['checked','started','ended','finished','fetched','done','total','complete',
  'serverDuration','queued','reason']) {
  const value = field === 'serverDuration' ? 0 : field === 'complete' ? false : 'value';
  model.syncRows(list, [{...first[0], [field]:value}]);
  assert.equal(backing[0].rowData[field], value, field + ' appeared');
  model.syncRows(list, [first[0]]);
  assert.equal(backing[0].rowData[field], undefined, field + ' disappeared');
}
// Large projects: a "more" row for pipelines counted but not fetched (#15).
const bigRepo = {repo:'g/p', url:'https://gitlab.com/g/p', checked:true,
  hidden:{running:150, pending:1500, created:0, waiting_for_resource:-1},
  runs:[{id:1, status:'in_progress', name:'CI', run_number:1}, {id:2, status:'completed', conclusion:'success', name:'CI', run_number:2}]};
const bigRows = model.rows([bigRepo], {'repo:g/p': true}, {}, '', Date.now());
const more = bigRows.find(row => row.kind === 'more');
assert.equal(more.title, '+150 more running · +about 1500 more pending · +more waiting for resource');
assert.equal(more.subtitle, 'o opens GitLab');
assert.equal(more.url, 'https://gitlab.com/g/p/-/pipelines');
assert.equal(JSON.stringify(bigRows.map(row => row.kind)), JSON.stringify(['repo', 'run', 'more', 'run']), 'more row sits before the first completed pipeline');
assert.ok(!model.rows([{...bigRepo, hidden:{}}], {'repo:g/p': true}, {}, '', Date.now()).some(row => row.kind === 'more'));
// syncRows stays linear for what polling does: a removal at the top, new rows, every status changed.
const n = 3000, bigBacking = [];
let gets = 0, structural = 0;
const bigList = {
  get count() { return bigBacking.length; },
  get(i) { gets++; return bigBacking[i]; },
  insert(i, value) { bigBacking.splice(i, 0, value); structural++; },
  move(from, to) { bigBacking.splice(to, 0, ...bigBacking.splice(from, 1)); structural++; },
  remove(i, count) { bigBacking.splice(i, count); structural++; },
  setProperty(i, role, value) { bigBacking[i][role] = value; }
};
const start = Array.from({length: n}, (_, i) => ({key: 'k' + i, title: 'T' + i, status: 'queued'}));
model.syncRows(bigList, start);
const next = start.slice(1).map(row => ({...row, status: 'in_progress'}))
  .concat(Array.from({length: 50}, (_, i) => ({key: 'new' + i, title: 'N' + i, status: 'queued'})));
gets = 0; structural = 0;
model.syncRows(bigList, next);
assert.deepEqual(bigBacking.map(row => row.rowKey), next.map(row => row.key));
assert.ok(bigBacking.every((row, i) => row.rowData.status === next[i].status));
assert.ok(gets < 20 * n, `syncRows used ${gets} get() calls for ${n} rows`);
assert.ok(structural <= 51, `one removal and 50 inserts cost ${structural} model edits, not a move per row`);
// o opens only plain https URLs on the configured host (#15).
assert.equal(model.browsable('https://gitlab.com/g/p/-/pipelines/1', 'gitlab.com'), true);
assert.equal(model.browsable('https://git.example.org:8443/g/p', 'git.example.org:8443'), true);
for (const url of ['https://evil.com/x', 'https://gitlab.com.evil/x', 'https://gitlabXcom/x', 'https://gitlab.com/a\u0007b', 'https://gitlab.com/a b', 'http://gitlab.com/x', 5, undefined])
  assert.equal(model.browsable(url, 'gitlab.com'), false, String(url));
// Zoom steps: 75..200, multiples of 10 from 100, no allowed level skipped (#22).
const levels = [75]; for (let l = 80; l <= 200; l += 10) levels.push(l);
for (let p = 75; p <= 200; p++) for (const dir of [1, -1]) {
  const r = model.zoomStep(p, dir);
  assert.ok(r === 75 || r % 10 === 0, `${p},${dir} -> ${r}`);
  assert.ok(r >= 75 && r <= 200, `${p},${dir} -> ${r}`);
  assert.ok(dir > 0 ? r > p || p === 200 : r < p || p === 75, `${p},${dir} -> ${r}`);
  assert.ok(!levels.some(l => dir > 0 ? l > p && l < r : l < p && l > r), `${p},${dir} skips a level -> ${r}`);
  assert.equal(model.zoomStep(p, 0), 100);
}
let z = 100; const down = [];
for (let i = 0; i < 4; i++) down.push(z = model.zoomStep(z, -1));
assert.deepEqual(down, [90, 80, 75, 75]);
z = 75; const up = [];
for (let i = 0; i < 14; i++) up.push(z = model.zoomStep(z, 1));
assert.deepEqual(up, [80, 90, 100, 110, 120, 130, 140, 150, 160, 170, 180, 190, 200, 200]);
console.log('Model: stage hierarchy, aggregation, filtering, progress, selection and duration passed');
// A stored null that the ListModel hands back as undefined must not count as a change (#28 review).
{
  const rows = [{key:'n', title:'N', status:'queued', serverDuration:null, queued:null}];
  model.syncRows(list, rows);
  backing[0].rowData = {...backing[0].rowData, serverDuration:undefined, queued:undefined};
  edits = 0;
  model.syncRows(list, rows);
  assert.equal(edits, 0, 'null and undefined compare equal in syncRows');
  model.syncRows(list, [{...rows[0], serverDuration:0}]);
  assert.equal(backing[0].rowData.serverDuration, 0, 'null to 0 is still a change');
}
