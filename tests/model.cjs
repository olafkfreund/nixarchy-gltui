const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const model = {};
vm.createContext(model);
vm.runInContext(fs.readFileSync('PipelinesModel.js', 'utf8'), model);
const repos = [{repo: 'group/sub/project', url: 'https://gitlab.com/group/sub/project', runs: [{id: 7, status: 'in_progress', conclusion: 'running', name: 'CI', head_branch: 'main', run_number: 3, html_url: 'https://gitlab.com/p/-/pipelines/7'}]}];
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
assert.equal(model.selection(rows, runKey + ':stage:build', 0), 2);
assert.equal(model.selection([], 'missing', 5), 0);
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
assert.equal(agg('canceled', 'success'), 'canceled');
assert.equal(agg('manual', 'manual'), 'manual');
assert.equal(agg('manual', 'skipped'), 'skipped');
assert.equal(model.duration({started_at:'2026-01-01T00:00:00Z'}, Date.parse('2026-01-01T00:01:15Z')), '1m 15s');
assert.equal(model.icon('success'), '✓');
assert.equal(model.icon('failed'), '✕');
assert.equal(model.icon('running'), '◷');
assert.equal(model.icon('canceling'), '◷');
assert.equal(model.icon('canceled'), '⊘');
for (const status of ['skipped', 'manual', 'scheduled']) assert.equal(model.icon(status), '−');
assert.equal(model.icon('pending'), '○');
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
assert.equal(model.syncRows(list, [first[1], first[0]]), true);
assert.equal(backing[1], originalA, 'Reordering moves the row instead of recreating it');
model.syncRows(list, [first[0]]);
assert.equal(list.count, 1);
assert.equal(backing[0].rowKey, 'a');
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
console.log('Model: stage hierarchy, aggregation, filtering, progress, selection and duration passed');
